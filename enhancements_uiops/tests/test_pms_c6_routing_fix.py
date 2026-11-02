# SPDX-License-Identifier: BSD-3-Clause
"""Tests for pms_c6_routing_fix.py (the misfiled F2DC scalar fields).

No real PMS/2DC/F2DC campaign data exists on this machine (checked repeatedly across sessions),
so every test here is synthetic -- honestly labeled as such. This matches how the original A11
finding itself was established ("constructing a small
synthetic OAP file... and tracing both output files under Octave"): the bug is a pure
file-routing error, not something that depends on real physics, so a synthetic fixture is a
complete validation, not a placeholder for a better one.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
from arrayprobe.readers import pms
from arrayprobe_uiops import ncio

from arrayprobe_enhancements.pms_c6_routing_fix import read_binary_PMS_corrected


def _record(tag, hour, minute, second, year, month, day, tas, millisec, wkday, fill_start=1):
    """Same construction as tests/test_pms.py's helper of the same name."""
    out = bytes(tag) + struct.pack(">9H", hour, minute, second, year, month, day,
                                    tas, millisec, wkday)
    data = np.zeros(4096, dtype=np.uint8)
    pattern = np.arange(fill_start, fill_start + 16, dtype=np.uint8)
    data[: len(pattern)] = pattern
    out += data.tobytes()
    return out


def _raw_file(path, records, header=b'<?xml version="1.0"?>\n<OAP>\n</OAP>\n'):
    with open(path, "wb") as fh:
        fh.write(header)
        for r in records:
            fh.write(r)


class C6RoutingFixTests(unittest.TestCase):

    def test_port_still_reproduces_the_bug(self):
        """Reference point: the unmodified port puts C6 scalars in the 2DC file."""
        records = [_record((67, 54), 6, 6, 45, 2016, 9, 2, 171, 260, 5)]
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            _raw_file(infile, records)
            out = str(Path(d) / "out")
            pms.read_binary_PMS(infile, out)
            with ncio.open(out + ".2dc.cdf") as f:
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                self.assertEqual(int(second[0]), 45)   # wrong file, but that's the bug
            with ncio.open(out + ".f2dc.cdf") as f:
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                self.assertNotEqual(int(second[0]), 45)   # fill value, not 45

    def test_corrected_reader_puts_c6_scalars_in_f2dc_with_the_image(self):
        records = [_record((67, 54), 6, 6, 45, 2016, 9, 2, 171, 260, 5)]
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            _raw_file(infile, records)
            out = str(Path(d) / "out")
            counts = read_binary_PMS_corrected(infile, out)
            self.assertEqual(counts, (0, 1, 0, 0))
            with ncio.open(out + ".f2dc.cdf") as f:
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                tas = np.asarray(f.get_var(f.inq_var_id("tas"))).reshape(-1)
                data = np.asarray(f.get_var(f.inq_var_id("data")))
                self.assertEqual(int(second[0]), 45)
                self.assertEqual(float(tas[0]), 171.0)
                self.assertTrue(np.any(data != 0))   # the image landed too, same row
            with ncio.open(out + ".2dc.cdf") as f:
                # no 'C1' record in this fixture at all -- nothing written, not
                # even a contaminated row (2DC's own dimension is unlimited/empty).
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                self.assertEqual(second.size, 0)

    def test_mixed_stream_c1_and_c6_route_correctly(self):
        """The fix to 'C6' must not perturb 'C1''s already-correct routing.

        Deliberately no 'C4' record here -- see the next test and
        enhancements_uiops/docs/CORRECTIONS.md, part `pms_c6_routing_fix.py`'s addendum for why mixing 'C4' and
        'C6' in one file hits a second, separate, NOT-fixed-here issue
        (the misfiled F2DC scalar fields addendum: kk2/kk3 are independent counters
        into the same physical F2DC file).
        """
        records = [
            _record((67, 49), 6, 6, 1, 2016, 9, 2, 100, 0, 5),   # 2DC ('C1')
            _record((67, 54), 6, 6, 3, 2016, 9, 2, 102, 0, 5),   # F2DC ('C6')
            _record((80, 1), 6, 6, 4, 2016, 9, 2, 103, 0, 5),    # 2DP
        ]
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            _raw_file(infile, records)
            out = str(Path(d) / "out")
            counts = read_binary_PMS_corrected(infile, out)
            self.assertEqual(counts, (1, 1, 0, 1))   # (2dc, f2dc_c6, f2dc_c4, 2dp)

            with ncio.open(out + ".2dc.cdf") as f:
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                self.assertEqual(list(second), [1])   # only the real 2DC record

            with ncio.open(out + ".f2dc.cdf") as f:
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                self.assertEqual(list(second), [3])

            with ncio.open(out + ".2dp.cdf") as f:
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                self.assertEqual(list(second), [4])

    def test_c4_and_c6_together_still_collide_a_separate_unfixed_issue(self):
        """A11 addendum, 2026-08-27: 'C4' (kk3) and 'C6'
        (kk2) are independent counters into the SAME physical F2DC file, both
        direct-index writes, not appends. This module fixes only the A11
        file-handle bug -- it deliberately does not also merge kk2/kk3, since
        that is a separate design question (does the UIOOPS author want the two
        record types interleaved into one series, or given disjoint index
        ranges?) that only the original authors can answer. This test proves
        the collision is real on the corrected reader, so a future session
        doesn't have to rediscover it before touching this module again.
        """
        records = [
            _record((67, 52), 6, 6, 10, 2016, 9, 2, 200, 0, 5),   # F2DC ('C4') first
            _record((67, 54), 6, 6, 20, 2016, 9, 2, 201, 0, 5),   # F2DC ('C6') second
        ]
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            _raw_file(infile, records)
            out = str(Path(d) / "out")
            counts = read_binary_PMS_corrected(infile, out)
            self.assertEqual(counts, (0, 1, 1, 0))   # both counters record one write each
            with ncio.open(out + ".f2dc.cdf") as f:
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                # both wrote to index 0 (kk3-1 == kk2-1 == 0); the second
                # decoded record (C6, second=20) wins the physical row.
                self.assertEqual(second.size, 1)
                self.assertEqual(int(second[0]), 20)
                self.assertNotEqual(int(second[0]), 10)   # the C4 record is gone

    def test_no_real_campaign_data_on_this_machine(self):
        """Documents the honest limit of this test module -- see BACKLOG_STATUS.md."""
        real_data_dirs = [
            Path(__file__).resolve().parent.parent.parent / "_decoded",
        ]
        has_real_pms = any(
            list(d.glob("*.PMS")) or list(d.glob("*.pms")) for d in real_data_dirs
            if d.is_dir()
        )
        self.assertFalse(
            has_real_pms,
            "Real PMS data now exists -- add a real-data test per "
            "enhancements_uiops/docs/CORRECTIONS.md, part `pms_c6_routing_fix.py`'s validation strategy §3, "
            "and update enhancements_uiops/BACKLOG_STATUS.md's A11 row.",
        )


if __name__ == "__main__":
    unittest.main()
