# SPDX-License-Identifier: BSD-3-Clause
"""The whole-flight render: classification, the PNG bytes, and the tree it writes.

**Why this is separate from the other render tests.** The other renderers draw a
handful of particles for a person to look at; this one writes a whole flight, so
its failure modes are different -- a misfiled particle, a corrupt PNG, or a
resumed run that redoes or skips work. Each gets a test.

Visualisation never changes a computed number, which is why this lives in the
core package (author, 2026-08-27) and why these tests assert about files and
counts rather than about anything scientific.
"""
from __future__ import annotations

import re
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np

from arrayprobe.render import (
    PARTICLE_CLASSES,
    _hhmmss,
    _png_bytes,
    classify_particle,
    render_flight_to_disk,
    write_flight_index,
)


class _FakeVar:
    def __init__(self, data):
        self._d = np.asarray(data)

    def __getitem__(self, k):
        return self._d[k]

    def __len__(self):
        return len(self._d)


class _FakeProc:
    """Enough of a proc dataset for the renderer, with a known answer.

    Hand-built rather than a real file so the expected tree is something this
    test states, not something it reads back from the code under test.
    """

    def __init__(self, times, rejects):
        n = len(times)
        self.variables = {
            "Time": _FakeVar(times),
            "image_auto_reject": _FakeVar(rejects),
            "parent_rec_num": _FakeVar(np.ones(n)),
            "position": _FakeVar(np.tile([1.0, 2.0], (n, 1))),
        }


class _FakeImage:
    """One image record whose every particle is a block with two lit bits."""

    def __init__(self):
        block = np.full((1, 1700, 1), 65535 - 0b0000000000000011, dtype=np.int64)
        self.variables = {"data": _FakeVar(block)}


class Classification(unittest.TestCase):
    def test_the_code_decides_accepted_and_rejected(self):
        self.assertEqual(classify_particle(ord("0"), None), "accepted")
        self.assertEqual(classify_particle(ord("z"), None), "rejected")
        self.assertEqual(classify_particle(ord("a"), None), "rejected")

    def test_hollow_and_sizeDist_good_codes_are_kept_not_rejected(self):
        # sizeDist.m:1209 accepts 0 H h u R; v3.5 keeps hollow particles, so the gallery must too.
        for c in "0HhuR":
            self.assertEqual(classify_particle(ord(c), None), "accepted", c)
        for c in "zaicts":
            self.assertEqual(classify_particle(ord(c), None), "rejected", c)

    def test_a_human_unsure_verdict_overrides_either(self):
        """Unsure is a person's word, not the code's, so it wins over both."""
        self.assertEqual(classify_particle(ord("0"), "unsure"), "unsure")
        self.assertEqual(classify_particle(ord("z"), "unsure"), "unsure")

    def test_the_other_human_verdicts_do_not_refile_a_particle(self):
        """A particle a person called real or artifact still files by the code's
        verdict. Only unsure has no counterpart in image_auto_reject.
        """
        self.assertEqual(classify_particle(ord("0"), "real"), "accepted")
        self.assertEqual(classify_particle(ord("0"), "artifact"), "accepted")
        self.assertEqual(classify_particle(ord("z"), "real"), "rejected")

    def test_time_is_formatted_not_converted(self):
        """Time is MATLAB's HHMMSS packed in a float, so 73928 is 07:39:28 and
        must not be read as a count of seconds.
        """
        self.assertEqual(_hhmmss(73928.0), "073928")
        self.assertEqual(_hhmmss(104036.0), "104036")
        self.assertEqual(_hhmmss(1.0), "000001")


class PngBytes(unittest.TestCase):
    def test_it_is_a_png_a_decoder_would_accept(self):
        raw = _png_bytes(np.array([[True, False], [False, True]]))
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
        width, height, depth, colour = struct.unpack(">IIBB", raw[16:26])
        self.assertEqual((width, height, depth, colour), (2, 2, 8, 0))

    def test_every_chunk_carries_a_correct_crc(self):
        """A wrong CRC still renders in some viewers and fails in others, which
        is the kind of defect that surfaces only once someone else opens it.
        """
        raw = _png_bytes(np.array([[True, False]]), scale=2)
        pos, seen = 8, []
        while pos < len(raw):
            (length,) = struct.unpack(">I", raw[pos:pos + 4])
            tag = raw[pos + 4:pos + 8]
            payload = raw[pos + 8:pos + 8 + length]
            (stored,) = struct.unpack(">I", raw[pos + 8 + length:pos + 12 + length])
            self.assertEqual(stored, zlib.crc32(tag + payload) & 0xFFFFFFFF, tag)
            seen.append(tag)
            pos += 12 + length
        self.assertEqual(seen, [b"IHDR", b"IDAT", b"IEND"])

    def test_shadowed_is_black_and_scale_multiplies_both_axes(self):
        raw = _png_bytes(np.array([[True, False]]), scale=3)
        width, height = struct.unpack(">II", raw[16:24])
        self.assertEqual((width, height), (6, 3))
        idat_start = raw.index(b"IDAT") + 4
        (length,) = struct.unpack(">I", raw[idat_start - 8:idat_start - 4])
        rows = zlib.decompress(raw[idat_start:idat_start + length])
        self.assertEqual(rows[0], 0)                        # filter byte
        self.assertEqual(list(rows[1:4]), [0, 0, 0])        # shadowed -> black
        self.assertEqual(list(rows[4:7]), [255, 255, 255])  # background -> white


class TreeLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # three particles in one second, one in the next; one of them rejected
        self.proc = _FakeProc([73928.0, 73928.0, 73928.0, 73929.0],
                              [ord("0"), ord("z"), ord("0"), ord("0")])
        self.image = _FakeImage()

    def test_one_directory_per_second_and_per_class(self):
        counts = render_flight_to_disk(self.image, self.proc, self.tmp)
        self.assertEqual(counts["accepted"], 3)
        self.assertEqual(counts["rejected"], 1)
        self.assertEqual(counts["seconds"], 2)
        self.assertTrue((self.tmp / "073928" / "accepted").is_dir())
        self.assertTrue((self.tmp / "073928" / "rejected").is_dir())
        self.assertEqual(len(list((self.tmp / "073928" / "accepted").glob("*.png"))), 2)
        self.assertEqual(len(list((self.tmp / "073929" / "accepted").glob("*.png"))), 1)

    def test_selecting_classes_is_how_a_large_flight_is_started(self):
        counts = render_flight_to_disk(self.image, self.proc, self.tmp,
                                       classes=("accepted",))
        self.assertEqual(counts["accepted"], 3)
        self.assertEqual(counts["skipped"], 1)
        self.assertFalse((self.tmp / "073928" / "rejected").exists())

    def test_a_second_run_skips_what_is_already_there(self):
        """Resumability is what makes an hours-long run safe to interrupt, so it
        is asserted rather than assumed: the second run reports the same
        particles and does not rewrite their bytes.
        """
        render_flight_to_disk(self.image, self.proc, self.tmp)
        target = self.tmp / "073928" / "accepted" / "p0000000.png"
        target.write_bytes(b"sentinel")
        counts = render_flight_to_disk(self.image, self.proc, self.tmp)
        self.assertEqual(counts["accepted"], 3)
        self.assertEqual(target.read_bytes(), b"sentinel",
                         "an existing particle was rewritten, so a resumed run "
                         "would redo all the work it was meant to skip")

    def test_a_human_unsure_verdict_moves_the_file(self):
        counts = render_flight_to_disk(self.image, self.proc, self.tmp,
                                       verdicts={"0": {"verdict": "unsure"}})
        self.assertEqual(counts["unsure"], 1)
        self.assertEqual(counts["accepted"], 2)
        self.assertTrue((self.tmp / "073928" / "unsure" / "p0000000.png").exists())
        self.assertFalse((self.tmp / "073928" / "accepted" / "p0000000.png").exists())

    def test_the_index_describes_the_tree_on_disk(self):
        render_flight_to_disk(self.image, self.proc, self.tmp)
        write_flight_index(self.tmp, title="test-flight")
        self.assertTrue((self.tmp / "index.html").exists())
        self.assertTrue((self.tmp / "073928" / "index.html").exists())
        top = (self.tmp / "index.html").read_text(encoding="utf-8")
        self.assertIn("test-flight", top)
        self.assertIn("073928/index.html", top)
        self.assertIn("2 seconds, 4 particles", top)
        second = (self.tmp / "073928" / "index.html").read_text(encoding="utf-8")
        self.assertIn("accepted/p0000000.png", second)
        self.assertIn("rejected/p0000001.png", second)

    def test_the_index_reads_the_disk_not_a_return_value(self):
        """An index built after a partial or resumed run must describe what is
        actually there. Rendering one class and indexing must not invent the
        others.
        """
        render_flight_to_disk(self.image, self.proc, self.tmp, classes=("accepted",))
        write_flight_index(self.tmp)
        top = (self.tmp / "index.html").read_text(encoding="utf-8")
        self.assertIn("2 seconds, 3 particles", top)

    def test_every_class_name_appears_in_the_index_header(self):
        render_flight_to_disk(self.image, self.proc, self.tmp)
        write_flight_index(self.tmp)
        top = (self.tmp / "index.html").read_text(encoding="utf-8")
        for name in PARTICLE_CLASSES:
            self.assertIn(f"<th>{name}</th>", top)


class BusySecondsArePaginated(unittest.TestCase):
    """A second is not a small unit, and the first real flight proved it.

    Rendering base170817073523 gave a per-second particle count with a median
    of 2 and a maximum of **53,926**. One index page holding fifty thousand
    image tags is not browsable however lazy the loading, so a busy second is
    split. The numbers here are small, but the property is the one that matters
    on the real tree.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        n = 7
        self.proc = _FakeProc([73928.0] * n, [ord("0")] * n)
        self.image = _FakeImage()
        render_flight_to_disk(self.image, self.proc, self.tmp)

    def test_a_busy_second_is_split_across_numbered_pages(self):
        write_flight_index(self.tmp, page_size=3)
        second = self.tmp / "073928"
        self.assertTrue((second / "index.html").exists())
        self.assertTrue((second / "index-2.html").exists())
        self.assertTrue((second / "index-3.html").exists())
        self.assertFalse((second / "index-4.html").exists())

    def test_page_one_keeps_the_plain_name(self):
        """So a link to the second's directory works whether or not that second
        turned out to need paginating."""
        write_flight_index(self.tmp, page_size=3)
        top = (self.tmp / "index.html").read_text(encoding="utf-8")
        self.assertIn("073928/index.html", top)

    def test_every_particle_appears_exactly_once_across_the_pages(self):
        """Pagination that drops or repeats a particle would be worse than none,
        because the tree would look complete."""
        write_flight_index(self.tmp, page_size=3)
        second = self.tmp / "073928"
        seen = []
        for page in sorted(second.glob("index*.html")):
            seen += re.findall(r'src="accepted/(p\d+\.png)"',
                               page.read_text(encoding="utf-8"))
        on_disk = sorted(f.name for f in (second / "accepted").glob("*.png"))
        self.assertEqual(sorted(seen), on_disk)
        self.assertEqual(len(seen), len(set(seen)), "a particle is listed twice")

    def test_the_pages_link_to_each_other(self):
        write_flight_index(self.tmp, page_size=3)
        first = (self.tmp / "073928" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="index-2.html"', first)
        self.assertIn('href="index-3.html"', first)
        second_page = (self.tmp / "073928" / "index-2.html").read_text(encoding="utf-8")
        self.assertIn('href="index.html"', second_page)

    def test_a_quiet_second_gets_one_page_and_no_pager(self):
        write_flight_index(self.tmp, page_size=50)
        second = self.tmp / "073928"
        self.assertEqual(sorted(p.name for p in second.glob("index*.html")),
                         ["index.html"])
        self.assertNotIn("per page", (second / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
