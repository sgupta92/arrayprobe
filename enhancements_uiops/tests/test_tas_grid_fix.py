# SPDX-License-Identifier: BSD-3-Clause
"""Tests for tas_grid_fix.py."""

from __future__ import annotations

import csv
import sys as _sys
import unittest
from pathlib import Path

_sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np

import _upstream  # noqa: E402
from arrayprobe_enhancements.tas_grid_fix import (
    collapse_tas_grid,
    duplicate_seconds,
    empty_intervals,
    floor_to_seconds,
)

_TAS = Path(__file__).resolve().parents[2] / "_decoded" / "base160906104932.tas.csv"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class FloorMatchesMatlab(unittest.TestCase):
    def test_truncates_fractional_seconds(self):
        # sizeDist.m:88 floors each component; 110247.997 is still second 110247.
        np.testing.assert_array_equal(
            floor_to_seconds([110247.107, 110247.997, 110249.0]),
            [11 * 3600 + 2 * 60 + 47, 11 * 3600 + 2 * 60 + 47, 11 * 3600 + 2 * 60 + 49])


class TheDefect(unittest.TestCase):
    def test_duplicate_second_creates_an_empty_interval(self):
        times = np.array([110246.1, 110247.1, 110247.9, 110249.0])
        np.testing.assert_array_equal(duplicate_seconds(times), [11 * 3600 + 2 * 60 + 47])
        # the interval starting at index 1 is [t, t) -- empty
        np.testing.assert_array_equal(empty_intervals(times), [1])

    def test_a_clean_grid_has_none(self):
        times = np.array([110246.1, 110247.1, 110248.4, 110249.0])
        self.assertEqual(duplicate_seconds(times).size, 0)
        self.assertEqual(empty_intervals(times).size, 0)


class Collapse(unittest.TestCase):
    def test_keeps_the_first_row_of_each_second_with_its_tas(self):
        times = np.array([110246.1, 110247.1, 110247.9, 110249.0])
        tas = np.array([100.0, 101.0, 102.0, 103.0])
        out_tas, out_times, report = collapse_tas_grid(tas, times)
        np.testing.assert_array_equal(out_times, [110246.1, 110247.1, 110249.0])
        np.testing.assert_array_equal(out_tas, [100.0, 101.0, 103.0])
        self.assertEqual((report["rows_in"], report["rows_out"], report["removed"]), (4, 3, 1))
        self.assertEqual(report["empty_intervals_before"], 1)

    def test_no_empty_interval_survives(self):
        times = np.array([110246.1, 110247.1, 110247.9, 110247.95, 110249.0, 110249.5])
        _, out_times, _ = collapse_tas_grid(np.arange(times.size, dtype=float), times)
        self.assertEqual(empty_intervals(out_times).size, 0)
        self.assertEqual(duplicate_seconds(out_times).size, 0)

    def test_is_a_no_op_on_a_clean_grid(self):
        times = np.array([110246.1, 110247.1, 110248.4])
        tas = np.array([1.0, 2.0, 3.0])
        out_tas, out_times, report = collapse_tas_grid(tas, times)
        np.testing.assert_array_equal(out_times, times)
        np.testing.assert_array_equal(out_tas, tas)
        self.assertEqual(report["removed"], 0)

    def test_empty_input(self):
        out_tas, out_times, report = collapse_tas_grid([], [])
        self.assertEqual((out_tas.size, out_times.size, report["rows_in"]), (0, 0, 0))

    def test_shape_mismatch_raises(self):
        with self.assertRaises(ValueError):
            collapse_tas_grid([1.0, 2.0], [110246.1])


@unittest.skipUnless(_TAS.exists(), "Real TAS sidecar is not distributed with the package; this "
                                    "test runs in the development repository")
class OnARealTasFile(unittest.TestCase):
    def setUp(self):
        with open(_TAS, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.times = np.array([float(r[0]) for r in rows])
        self.tas = np.array([float(r[1]) for r in rows])

    def test_the_defect_is_present_and_the_collapse_removes_it(self):
        self.assertGreater(duplicate_seconds(self.times).size, 0,
                           "this file is the one A17 was measured on")
        self.assertGreater(empty_intervals(self.times).size, 0)
        _, out_times, report = collapse_tas_grid(self.tas, self.times)
        self.assertEqual(empty_intervals(out_times).size, 0)
        self.assertEqual(report["rows_out"], np.unique(floor_to_seconds(self.times)).size)
        self.assertEqual(report["rows_in"] - report["rows_out"], report["removed"])

    def test_every_second_survives_exactly_once(self):
        _, out_times, _ = collapse_tas_grid(self.tas, self.times)
        before = np.unique(floor_to_seconds(self.times))
        after = floor_to_seconds(out_times)
        np.testing.assert_array_equal(np.sort(after), before)


class TheFormulaMatchesV35SizeDistM135(unittest.TestCase):
    """``tas_grid_fix.floor_to_seconds`` is ``sizeDist.m:88``'s formula in v3.1.4, and it is
    also, verified here rather than assumed, v3.5's own ``tas_time`` at ``sizeDist.m:135``
    (``single_vt.m`` byte-identity does not apply here -- ``sizeDist.m`` is NOT byte-identical
    between the two releases, so this module's ``applicability.py`` row cites the v3.5 line
    directly). No module change is needed: ``collapse_tas_grid`` operates purely in memory on
    ``(tas, timehhmmss)`` before either engine's ``sizedist.run`` ever sees them, so the same
    collapse is correct input to whichever engine reads it."""

    def test_v35_matlab_source_line_135_is_the_same_three_term_construct(self):
        _upstream.require("uiops35")
        v35_src = _upstream.source("uiops35") / "sizeDist.m"
        lines = v35_src.read_text(encoding="utf-8", errors="replace").splitlines()
        self.assertEqual(
            lines[134].strip(),  # sizeDist.m:135, 1-based
            "tas_time = floor(timehhmmss/10000)*3600+floor(mod(timehhmmss,10000)/100)*60"
            "+floor(mod(timehhmmss,100));")

    def test_v35_ports_own_translation_uses_the_same_expression(self):
        """``arrayprobe_uiops/sizedist.py:826-828``, read directly rather than restated."""
        import arrayprobe_uiops.sizedist as sd35
        src = Path(sd35.__file__).read_text(encoding="utf-8")
        for fragment in ("np.floor(timehhmmss / 10000) * 3600",
                         "np.floor((timehhmmss % 10000) / 100) * 60",
                         "np.floor(timehhmmss % 100)"):
            self.assertIn(fragment, src)

    def test_floor_to_seconds_numerically_matches_the_v35_translation(self):
        t = np.array([60640.0, 110247.997, 235959.5, 0.0])
        # The same three-term expression the two source citations above confirm --
        # arrayprobe_uiops/sizedist.py:826-828 is not importable standalone (it lives inside
        # `_run`), so it is evaluated inline here rather than re-derived.
        v35_style = (np.floor(t / 10000) * 3600
                    + np.floor((t % 10000) / 100) * 60
                    + np.floor(t % 100))
        np.testing.assert_array_equal(floor_to_seconds(t), v35_style)


if __name__ == "__main__":
    unittest.main()
