# SPDX-License-Identifier: BSD-3-Clause
"""Tests for mask_presence_fix.py (the upstream silent missing mask file, and the unloadable empty mask name's near miss).

Both states are exercised on the same directory: ``required=True`` (the correction) must
raise, and ``required=False`` (MATLAB's own silence, plus a report) must not.  The near-miss
case is the real one -- the recovered 2016 masks are named ``diode.<date><time>.mat``, with no
orientation letter, so ``imgProc_sm.m:288`` could never have found them.

The mask fixtures are the port's own tracked ones, so the "found" side is a real MAT-file
written by MATLAB rather than something this package invented.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from arrayprobe_enhancements.mask_presence_fix import (
    MaskNotFoundError,
    check_mask,
    expected_mask_path,
    near_miss_candidates,
    provenance_entry,
)

PORT_DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
FIXTURE = PORT_DATA / "shadow_diode_fixture.mat"
EMPTY_FIXTURE = PORT_DATA / "shadow_diode_empty_fixture.mat"

FLIGHT, FILE = "160906", "064403"
INFILE = "base160906064403.V.cdf"


class TheNameMatlabBuilds(unittest.TestCase):
    def test_it_is_the_ports_own_construction(self):
        path = expected_mask_path("/masks", FLIGHT, FILE, INFILE)
        self.assertEqual(path.name, "diode.160906064403.V.mat")

    def test_the_orientation_comes_from_infile_end_minus_4(self):
        self.assertEqual(
            expected_mask_path("/masks", FLIGHT, FILE, "base160906064403.H.cdf").name,
            "diode.160906064403.H.mat")


class WhenTheMaskIsSimplyAbsent(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_correction_on_raises_and_names_the_path(self):
        with self.assertRaises(MaskNotFoundError) as caught:
            check_mask(self.tmp, FLIGHT, FILE, INFILE)
        self.assertIn("diode.160906064403.V.mat", str(caught.exception))

    def test_the_correction_off_is_silent_exactly_like_matlab(self):
        lookup = check_mask(self.tmp, FLIGHT, FILE, INFILE, required=False)
        self.assertFalse(lookup)
        self.assertIsNone(lookup.mask)
        self.assertIn("proceed with unmasked images", lookup.verdict)

    def test_the_provenance_line_records_the_absence(self):
        lookup = check_mask(self.tmp, FLIGHT, FILE, INFILE, required=False)
        self.assertEqual(provenance_entry(lookup),
                         "diode_mask=none expected=diode.160906064403.V.mat")

    def test_a_directory_that_does_not_exist_is_not_a_near_miss_hunt(self):
        self.assertEqual(near_miss_candidates(self.tmp / "nope", FLIGHT, FILE, INFILE), [])


class WhenTheMaskExistsUnderAnUnfindableName(unittest.TestCase):
    """The real 2016 case: `diode.160906064403.mat`, no orientation letter."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy2(FIXTURE, self.tmp / "diode.160906064403.mat")
        # F2: an empty mask saved as `...<or>empty.mat`, which the loader cannot construct.
        shutil.copy2(EMPTY_FIXTURE, self.tmp / "diode.160906064403.Vempty.mat")

    def test_the_near_misses_are_found_and_named(self):
        """Named, and in ONE order on every platform.

        This assertion used to read [".mat", ".Vempty.mat"], which is what
        Windows produces and only Windows: `sorted()` over Path objects compares
        WindowsPath case-insensitively ("vempty" > "mat") and PosixPath
        case-sensitively ("V" < "m"), so the same two files came back in
        opposite orders on the author's laptop and on Linux. The first
        cross-platform CI run (2026-09-08) caught it. The source now sorts on
        `p.name` as a plain string, so the expected order is the case-sensitive
        one everywhere -- capital V before lower-case m.
        """
        names = [p.name for p in near_miss_candidates(self.tmp, FLIGHT, FILE, INFILE)]
        self.assertEqual(names,
                         ["diode.160906064403.Vempty.mat", "diode.160906064403.mat"])

    def test_the_correction_reports_them_rather_than_just_missing(self):
        with self.assertRaises(MaskNotFoundError) as caught:
            check_mask(self.tmp, FLIGHT, FILE, INFILE)
        message = str(caught.exception)
        self.assertIn("near miss", message)
        self.assertIn("diode.160906064403.mat", message)

    def test_it_still_refuses_to_load_one(self):
        """A near miss is diagnosed, never adopted -- which channel it is, is unknown."""
        lookup = check_mask(self.tmp, FLIGHT, FILE, INFILE, required=False)
        self.assertIsNone(lookup.mask)
        self.assertFalse(lookup.found)

    def test_a_mask_for_another_flight_is_not_offered(self):
        shutil.copy2(FIXTURE, self.tmp / "diode.160910124240.V.mat")
        names = [p.name for p in near_miss_candidates(self.tmp, FLIGHT, FILE, INFILE)]
        self.assertNotIn("diode.160910124240.V.mat", names)


class WhenTheMaskIsThere(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_real_mask_loads_and_reports_its_diode_count(self):
        shutil.copy2(FIXTURE, self.tmp / "diode.160906064403.V.mat")
        lookup = check_mask(self.tmp, FLIGHT, FILE, INFILE)
        self.assertTrue(lookup)
        self.assertGreater(len(lookup.mask), 0)
        self.assertIn("mask found", lookup.verdict)
        self.assertIn(f"diodes={len(lookup.mask)}", provenance_entry(lookup))

    def test_an_empty_mask_found_under_the_right_name_says_so(self):
        """Distinguishable from "absent" -- which is the whole point of F2's entry."""
        shutil.copy2(EMPTY_FIXTURE, self.tmp / "diode.160906064403.V.mat")
        lookup = check_mask(self.tmp, FLIGHT, FILE, INFILE)
        self.assertTrue(lookup.found)
        self.assertEqual(len(lookup.mask), 0)
        self.assertIn("changes nothing", lookup.verdict)


if __name__ == "__main__":
    unittest.main()
