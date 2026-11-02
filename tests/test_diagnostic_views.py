# SPDX-License-Identifier: BSD-3-Clause
"""Plan row 16's last two views -- the record strip and the one-second comparison.

Each test checks what a view *claims* against a second source, never against the view's own
arithmetic (a check must draw its two sides from different places):

* the strip's shadow inside a particle window is checked against
  :func:`arrayprobe.render.reconstruct_particle_image` -- the gallery's decode, which goes through
  ``dec2bin_concat`` where the strip unpacks bits;
* the strip's boundary marks are checked against the proc file's own framing (``position``):
  every particle window must end one slice before a boundary slice;
* the PNG is decoded here, by a reader written in this file, and its pixels counted;
* the comparison's cells are checked against the netCDF files read directly, and against a copy
  with one cell deliberately changed;
* the rate panel's per-second counts must sum to the proc file's particle count.

Fixtures: the tracked v3.1.4 demo reference (``tests/data/demo_flight_v314_*``, one particle per
record) and a three-second dense demo flight built in ``setUpClass`` (twelve particles per record,
accepted and rejected, so a strip has something to colour).
"""

from __future__ import annotations

import http.client
import importlib.util
import shutil
import struct
import sys
import tempfile
import threading
import unittest
import zlib
from pathlib import Path

import netCDF4
import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import diagnostic_views as views
from arrayprobe import provenance
from arrayprobe.cli import main as cli_main
from arrayprobe.render import reconstruct_particle_image

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
IMAGE = DATA / "demo_flight_v314_image.cdf"
PROC = DATA / "demo_flight_v314_proc.nc"
SD = DATA / "demo_flight_v314_sd.nc"

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")


def _run_flight():
    """The registered ``run_flight`` module, or a fresh one registered under that name (the same
    rule ``tests/test_demo_flight_thresholds.py`` follows, so the suite shares one object)."""
    mod = sys.modules.get(_RF_SPEC.name)
    if mod is None:
        mod = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = mod
        _RF_SPEC.loader.exec_module(mod)
    return mod


def _decode_png(data: bytes) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """A minimal reader for the 8-bit palette, filter-0 PNGs the strip writes."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, palette, width, height = 8, b"", [], 0, 0
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag, payload = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", payload[:10])
            assert (depth, ctype) == (8, 3), (depth, ctype)
        elif tag == b"PLTE":
            palette = [tuple(payload[i:i + 3]) for i in range(0, len(payload), 3)]
        elif tag == b"IDAT":
            idat += payload
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(height, width + 1)
    assert not raw[:, 0].any(), "every scanline is filter type 0"
    return raw[:, 1:], palette


class TheStripOnTheTrackedReference(unittest.TestCase):
    """One particle per record: the simplest case, on files nobody built for this test."""

    def setUp(self):
        self.im = netCDF4.Dataset(str(IMAGE))
        self.pr = netCDF4.Dataset(str(PROC))
        self.addCleanup(self.im.close)
        self.addCleanup(self.pr.close)

    def test_each_particle_window_holds_the_gallery_s_silhouette(self):
        strip = views.record_strip(self.im, self.pr, 1, 6)
        self.assertEqual(len(strip.particles), 5)
        for p in strip.particles:
            k = strip.records.index(p.record)
            np.testing.assert_array_equal(
                strip.shadow[k, p.first_slice - 1:p.last_slice],
                reconstruct_particle_image(self.im, self.pr, p.index))

    def test_it_lists_exactly_the_proc_rows_of_the_records_shown(self):
        parent = np.asarray(self.pr.variables["parent_rec_num"][:]).astype(int)
        strip = views.record_strip(self.im, self.pr, 2, 2)
        self.assertEqual(strip.records, (2, 3))
        self.assertEqual([p.index for p in strip.particles],
                         [i for i, r in enumerate(parent) if r in (2, 3)])

    def test_the_last_record_is_clipped_to_the_file(self):
        strip = views.record_strip(self.im, self.pr, 4, 6)
        self.assertEqual(strip.records, (4, 5))

    def test_a_record_outside_the_file_raises_and_names_the_range(self):
        with self.assertRaisesRegex(ValueError, r"outside this file's 1\.\.5"):
            views.record_strip(self.im, self.pr, 6)

    def test_an_unknown_colouring_is_refused(self):
        with self.assertRaises(ValueError):
            views.record_strip(self.im, self.pr, 1, colour_by="size")


@needs_v314_engine
class TheStripOnADenseFlight(unittest.TestCase):
    """Twelve particles a record, accepted and aspect-ratio-rejected, built once."""

    @classmethod
    def setUpClass(cls):
        from arrayprobe.tools.make_demo_flight import build_dense_demo_flight

        rf = _run_flight()
        cls._real_log = rf.log
        rf.log = lambda *a, **kw: None
        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name)
        raw = out / "base160101000000.2DS"
        build_dense_demo_flight(raw, n_seconds=3)
        cls.image = rf.stage2(raw, out)
        cls.proc = rf.stage3(cls.image, out)
        cls.im = netCDF4.Dataset(str(cls.image))
        cls.pr = netCDF4.Dataset(str(cls.proc))
        cls.strip = views.record_strip(cls.im, cls.pr, 1, 6)

    @classmethod
    def tearDownClass(cls):
        cls.im.close()
        cls.pr.close()
        _run_flight().log = cls._real_log
        cls._tmp.cleanup()

    def test_the_flight_has_several_particles_a_record_and_two_classes(self):
        self.assertGreater(len(self.strip.particles), len(self.strip.records))
        self.assertIn("accepted", self.strip.categories)
        self.assertTrue(any(c.startswith("reject ") for c in self.strip.categories))

    def test_every_window_holds_the_gallery_s_silhouette(self):
        for p in self.strip.particles:
            k = self.strip.records.index(p.record)
            np.testing.assert_array_equal(
                self.strip.shadow[k, p.first_slice - 1:p.last_slice],
                reconstruct_particle_image(self.im, self.pr, p.index),
                err_msg=f"proc row {p.index}")

    def test_every_window_ends_just_before_a_boundary_slice(self):
        """The boundary marks come from the raw words; ``position`` comes from ``imgProc_sm``'s
        framing. They agree, or one of them is drawn in the wrong place."""
        for p in self.strip.particles:
            k = self.strip.records.index(p.record)
            self.assertTrue(self.strip.boundary[k, p.last_slice],   # 0-based: slice last+1
                            f"proc row {p.index}")
            self.assertFalse(self.strip.boundary[k, p.first_slice - 1:p.last_slice].any())

    def test_the_png_is_the_index_image_and_each_colour_counts_its_particles(self):
        img, palette = views.strip_index_image(self.strip)
        decoded, png_palette = _decode_png(views.record_strip_png(self.strip))
        np.testing.assert_array_equal(decoded, img)
        self.assertEqual(png_palette, [tuple(c) for c in palette])
        for k, cat in enumerate(self.strip.categories):
            members = [p for p in self.strip.particles
                       if p.category(self.strip.colour_by) == cat]
            expected = sum(int(reconstruct_particle_image(self.im, self.pr, p.index).sum())
                           for p in members)
            self.assertEqual(int((decoded == 5 + k).sum()), expected, cat)
        self.assertEqual(palette[5 + self.strip.categories.index("accepted")], (0, 0, 0))

    def test_every_fifth_particle_is_ticked_above_its_first_slice(self):
        img, _ = views.strip_index_image(self.strip)
        band = 4 + self.strip.shadow.shape[2]
        ticked = {(r // band, c) for r, c in zip(*np.nonzero(img == 4), strict=True)}
        expected = {(self.strip.records.index(p.record), p.first_slice - 1)
                    for n, p in enumerate(self.strip.particles, start=1) if n % 5 == 0}
        self.assertEqual(ticked, expected)

    def test_colouring_by_habit_names_the_particles_own_habits(self):
        strip = views.record_strip(self.im, self.pr, 1, 6, colour_by="habit")
        habits = {f"habit {p.habit}" for p in strip.particles}
        self.assertEqual(set(strip.categories), habits)

    def test_the_same_strip_gives_the_same_bytes(self):
        again = views.record_strip(self.im, self.pr, 1, 6)
        self.assertEqual(views.record_strip_png(again), views.record_strip_png(self.strip))

    def test_the_page_has_a_row_per_particle_and_a_legend_that_adds_up(self):
        import re

        page = views.record_strip_html(self.strip)
        self.assertEqual(page.count("<tr><td>"), len(self.strip.particles))
        legend = dict(re.findall(r"</span> ([^<(]+?) \((\d+)\)</span>", page))
        self.assertEqual(set(legend), set(self.strip.categories))
        self.assertEqual(sum(int(v) for v in legend.values()), len(self.strip.particles))

    def test_per_second_counts_sum_to_the_particles_in_the_file(self):
        t = np.asarray(self.pr.variables["Time"][:])
        seconds, counts = views.per_second_counts(t)
        self.assertEqual(int(counts.sum()), len(t))
        self.assertEqual(len(seconds), 3)
        self.assertEqual(set(counts.tolist()), {12})


class TheOneSecondComparison(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _perturbed(self, second_row: int, bin0: int, delta: float, name: str = "") -> Path:
        path = self.tmp / f"sd_{second_row}_{bin0}{name}.nc"
        shutil.copyfile(SD, path)
        with netCDF4.Dataset(str(path), "a") as ds:
            ds.set_auto_maskandscale(False)
            var = ds.variables["count"]
            var[second_row:second_row + 1, bin0:bin0 + 1] = np.array(
                [[float(var[second_row, bin0]) + delta]])
        return path

    def test_a_file_against_itself_differs_nowhere(self):
        cmp = views.compare_second(SD, SD, 60641, proc=PROC)
        self.assertEqual(cmp.n_differing, 0)
        self.assertEqual(cmp.particles, ())

    def test_one_changed_cell_is_the_one_cell_reported_with_the_files_values(self):
        theirs = self._perturbed(0, 4, 3.0)
        cmp = views.compare_second(SD, theirs, 60640, proc=PROC)
        self.assertEqual(np.nonzero(cmp.differing)[0].tolist(), [4])
        with netCDF4.Dataset(str(SD)) as a, netCDF4.Dataset(str(theirs)) as b:
            np.testing.assert_array_equal(cmp.ours, np.asarray(a.variables["count"][0, :]))
            np.testing.assert_array_equal(cmp.theirs, np.asarray(b.variables["count"][0, :]))
            np.testing.assert_array_equal(cmp.bin_min, np.asarray(a.variables["bin_min"][:]))

    def test_the_particle_of_that_second_in_that_bin_is_listed_and_no_other(self):
        """Demo particle ``i`` sits in second ``60640 + i`` at 0.048 mm: bin 5, [0.045, 0.055)."""
        cmp = views.compare_second(SD, self._perturbed(1, 4, 1.0), 60641, proc=PROC)
        self.assertEqual([p["index"] for p in cmp.particles], [1])
        (p,) = cmp.particles
        self.assertEqual((p["bin"], p["reject"], p["center_in"]), (5, "0", 1))
        self.assertIn("proc row 1: bin 5", cmp.summary())

    def test_a_differing_bin_the_particle_is_not_in_lists_nothing(self):
        cmp = views.compare_second(SD, self._perturbed(1, 40, 1.0), 60641, proc=PROC)
        self.assertEqual(cmp.n_differing, 1)
        self.assertEqual(cmp.particles, ())

    def test_rtol_hides_a_small_relative_difference_and_exact_does_not(self):
        ours = self._perturbed(2, 4, 100.0, "a")
        theirs = self._perturbed(2, 4, 100.0 + 1e-6, "b")
        self.assertEqual(views.compare_second(ours, theirs, 60642).n_differing, 1)
        self.assertEqual(views.compare_second(ours, theirs, 60642, rtol=1e-6).n_differing, 0)
        # Relative means relative: against a zero cell no rtol hides a difference.
        zero_vs_small = self._perturbed(2, 4, 1e-9, "c")
        self.assertEqual(views.compare_second(SD, zero_vs_small, 60642, rtol=0.5).n_differing, 1)

    def test_a_missing_second_names_the_nearest_ones(self):
        with self.assertRaisesRegex(KeyError, "no second 120000; nearest 060643"):
            views.compare_second(SD, SD, 120000)

    def test_two_bin_ladders_are_refused(self):
        other = self.tmp / "ladder.nc"
        shutil.copyfile(SD, other)
        with netCDF4.Dataset(str(other), "a") as ds:
            ds.variables["bin_min"][0] = 0.001
        with self.assertRaisesRegex(ValueError, "different bin ladders"):
            views.compare_second(SD, other, 60640)

    def test_the_page_marks_the_differing_row_and_states_the_size_variable(self):
        cmp = views.compare_second(SD, self._perturbed(0, 4, 3.0), 60640, proc=PROC)
        page = views.second_comparison_html(cmp)
        self.assertEqual(page.count("differs</td>"), 1)
        self.assertIn("image_diam_minR", page)
        self.assertIn("where to look, not what was counted", page)


class TheViewsReachTheCommandLine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_view_strip_writes_the_png_the_library_writes(self):
        out = self.tmp / "strip.png"
        self.assertEqual(cli_main(["view", "strip", str(IMAGE), str(PROC), "--out", str(out)]), 0)
        with netCDF4.Dataset(str(IMAGE)) as im, netCDF4.Dataset(str(PROC)) as pr:
            expected = views.record_strip_png(views.record_strip(im, pr, 1, 6))
        self.assertEqual(out.read_bytes(), expected)

    def test_view_second_writes_a_page(self):
        out = self.tmp / "second.html"
        self.assertEqual(cli_main(["view", "second", str(SD), str(SD), "--second", "60640",
                                   "--proc", str(PROC), "--out", str(out)]), 0)
        self.assertIn("0 of 128 bin(s) differ", out.read_text(encoding="utf-8"))


_UNSET = object()


class TheTriageServerServesTheStrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer

        from arrayprobe.triage_server import TriageServer

        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        shutil.copyfile(IMAGE, d / "demoA.H.cdf")
        proc_path = d / "proc.demoA.H.nc"
        shutil.copyfile(PROC, proc_path)
        # 2026-09-18: _discover_flights now refuses a proc file with no
        # recorded provenance, so a bare copy of the tracked fixture no longer
        # registers as a flight. Stamp it -- the driver-format shape
        # run_flight.py itself writes -- rather than setting accept_unstamped,
        # since these tests are exercising the ordinary served-flight pages,
        # not the refusal path (that is test_triage_refuses_unstamped.py's job).
        provenance.call_path(proc_path).write_text(
            "engine=3.1.4 profile=oracles-production reject=(rej_hollow=0) shadow_diode=none\n",
            encoding="utf-8")
        cls._saved = TriageServer.__dict__.get("decoded_dir", _UNSET)
        TriageServer.decoded_dir = d
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TriageServer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        from arrayprobe.triage_server import TriageServer

        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        if cls._saved is _UNSET:
            del TriageServer.decoded_dir
        else:
            TriageServer.decoded_dir = cls._saved
        cls._tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", "replace")
        conn.close()
        return resp.status, body

    def test_the_strip_page_shows_the_records_and_links_each_particle(self):
        status, body = self._get("/strip/demoA?rec=2&n=2")
        self.assertEqual(status, 200)
        self.assertIn("Records 2-3 of 5", body)
        self.assertIn("/particle/demoA/1", body)
        self.assertIn("/particle/demoA/2", body)
        self.assertNotIn("/particle/demoA/3'", body)
        self.assertIn("data:image/png;base64,", body)

    def test_a_record_past_the_end_says_so(self):
        status, body = self._get("/strip/demoA?rec=9")
        self.assertEqual(status, 200)
        self.assertIn("outside this file", body)

    def test_the_particle_page_links_to_its_record(self):
        status, body = self._get("/particle/demoA/3")
        self.assertEqual(status, 200)
        self.assertIn("/strip/demoA?rec=4", body)


if __name__ == "__main__":
    unittest.main()
