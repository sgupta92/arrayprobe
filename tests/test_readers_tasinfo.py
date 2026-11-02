# SPDX-License-Identifier: BSD-3-Clause
"""Tests for arrayprobe.readers.tasinfo -- loadTASinfo_2DS.m's CSV reader.

See tasinfo.py's module docstring for why Octave cannot run the real source
at all (a real Octave limitation, textscan's REPEAT=Inf) and why the tracked
shim/oracle stands in instead.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe.readers.tasinfo import load_tas_info

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "s9_tasinfo_octave_golden.json"


class TestMatchesOctaveShim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._skip_reason = None
        if not GOLDEN.exists():
            cls._skip_reason = f"oracle golden not found: {GOLDEN}"
            return
        cls.golden = json.loads(GOLDEN.read_text())

    def setUp(self):
        # Raised here, not in setUpClass: a SkipTest from setUpClass is recorded
        # against an _ErrorHolder, so it never increments testsRun and never joins
        # the skipped tally -- the suite reports one FEWER test instead of one more
        # skip. See tests/test_class_level_skips_are_visible.py.
        if self._skip_reason:
            self.skipTest(self._skip_reason)

    def test_two_columns_extracted_matches_octave_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fixture.tas.csv"
            csv_path.write_text(self.golden["csv_text"])
            timehhmmss, tas = load_tas_info(csv_path)

        np.testing.assert_array_equal(
            timehhmmss, np.array(self.golden["octave_timehhmmss"]))
        np.testing.assert_array_equal(
            tas, np.array(self.golden["octave_tas"]))

    def test_trailing_all_zero_row_dropped(self):
        # The fixture's own CSV ends with a trailing all-zero row (the
        # dlmread-on-trailing-newline artifact) -- confirm the golden
        # (n_rows real data rows) is what's returned, not n_rows + 1.
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fixture.tas.csv"
            csv_path.write_text(self.golden["csv_text"])
            timehhmmss, _tas = load_tas_info(csv_path)
        self.assertEqual(len(timehhmmss), self.golden["n_rows"])


class TestEdgeCases(unittest.TestCase):
    def test_non_numeric_extra_columns_are_ignored(self):
        # The real .tas.csv has seven columns after (time, tas); the source's
        # own '%f%f%*s...' skips them unconditionally, whatever they hold.
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fixture.tas.csv"
            csv_path.write_text("60000.0,120.5,abc,def,,,,,\n"
                                 "60001.0,121.0,xyz,,,,,,\n")
            timehhmmss, tas = load_tas_info(csv_path)
        np.testing.assert_allclose(timehhmmss, [60000.0, 60001.0])
        np.testing.assert_allclose(tas, [120.5, 121.0])

    def test_single_row_file_stays_two_dimensional(self):
        # np.loadtxt collapses a one-row file to 1-D; atleast_2d must
        # restore the MATLAB dlmread shape unconditionally, or the column
        # indexing below breaks.
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fixture.tas.csv"
            csv_path.write_text("60000.0,120.5,a,b,c,d,e,f,g\n")
            timehhmmss, tas = load_tas_info(csv_path)
        self.assertEqual(len(timehhmmss), 1)
        self.assertAlmostEqual(float(timehhmmss[0]), 60000.0)
        self.assertAlmostEqual(float(tas[0]), 120.5)

    def test_no_trailing_zero_row_present_nothing_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fixture.tas.csv"
            csv_path.write_text("60000.0,120.5,,,,,,,\n"
                                 "60001.0,121.0,,,,,,,\n"
                                 "60002.0,122.0,,,,,,,\n")
            timehhmmss, tas = load_tas_info(csv_path)
        self.assertEqual(len(timehhmmss), 3)

    def test_a_real_zero_row_in_the_middle_is_not_dropped(self):
        # Only the LAST row is checked/dropped -- a genuine (0, 0) sample
        # elsewhere in the file is real data, not the trailing-newline
        # artifact, and must survive.
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fixture.tas.csv"
            csv_path.write_text("60000.0,120.5,,,,,,,\n"
                                 "0,0,,,,,,,\n"
                                 "60002.0,122.0,,,,,,,\n")
            timehhmmss, tas = load_tas_info(csv_path)
        self.assertEqual(len(timehhmmss), 3)
        np.testing.assert_allclose(timehhmmss, [60000.0, 0.0, 60002.0])


if __name__ == "__main__":
    unittest.main()
