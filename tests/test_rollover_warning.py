# SPDX-License-Identifier: BSD-3-Clause
"""The midnight correction warns when it shifts particles on no crossover.

The correction itself is preserved bug-for-bug (a documented preserved bug, ``sizeDist.m``
``:544-545``); what changes is that the port now *says* when it fires on a clock glitch rather
than on midnight. A warning changes no written byte, so the tests assert both halves: the
message names the count and the enhancement to run, and the corrected array is unchanged.
"""

from __future__ import annotations

import unittest

import numpy as np
from tests._repo import needs_v314_engine

from arrayprobe_uiops import sizedist as v35

try:  # the v3.1.4 engine is not part of the public distribution
    from arrayprobe import sizedist as v314
except ImportError:
    v314 = None

GLITCH = np.array([95600, 95601, 202, 95602, 95603, 95604], dtype=float)
MIDNIGHT = np.array([235958, 235959, 0, 1, 2], dtype=float)


@needs_v314_engine
class TestV314(unittest.TestCase):
    def test_a_glitch_warns_with_the_count_and_the_way_out(self):
        with self.assertLogs("arrayprobe.sizedist", level="WARNING") as cm:
            moved = v314.warn_suspect_rollover(GLITCH, "3.1.4")
        self.assertEqual(moved, 4)
        msg = "\n".join(cm.output)
        self.assertIn("all 4 later particles", msg)
        self.assertIn("particle_time_glitch_fix", msg)

    def test_a_real_crossover_is_silent(self):
        with self.assertNoLogs("arrayprobe.sizedist", level="WARNING"):
            self.assertEqual(v314.warn_suspect_rollover(MIDNIGHT, "3.1.4"), 0)

    def test_no_decrease_is_silent(self):
        with self.assertNoLogs("arrayprobe.sizedist", level="WARNING"):
            self.assertEqual(v314.warn_suspect_rollover(np.arange(5.0), "3.1.4"), 0)

    def test_the_warning_reads_and_never_writes(self):
        x = GLITCH.copy()
        with self.assertLogs("arrayprobe.sizedist", level="WARNING"):
            v314.warn_suspect_rollover(x, "3.1.4")
        np.testing.assert_array_equal(x, GLITCH)
        # And the preserved correction still does exactly what the MATLAB does.
        expected = GLITCH.copy()
        expected[2:] += 240000
        np.testing.assert_array_equal(v314._rollover_240000(x), expected)


class TestV35(unittest.TestCase):
    def test_a_single_glitch_warns_and_still_shifts(self):
        with self.assertLogs("arrayprobe.sizedist", level="WARNING") as cm:
            out, applied = v35.fix_multiday_particle_times(GLITCH)
        self.assertTrue(applied)
        expected = GLITCH.copy()
        expected[2:] += 240000
        np.testing.assert_array_equal(out, expected)
        self.assertIn("engine 3.5", "\n".join(cm.output))

    def test_an_all_ones_header_passing_the_test_warns(self):
        x = np.array([95600, 316363, 80000, 95602, 95500], dtype=float)
        with self.assertLogs("arrayprobe_uiops.sizedist", level="WARNING") as cm:
            out, applied = v35.fix_multiday_particle_times(x)
        self.assertTrue(applied)
        np.testing.assert_array_equal(out[2:], x[2:] + 240000)
        self.assertIn("316363, not a valid HHMMSS", "\n".join(cm.output))

    def test_a_real_crossover_among_several_decreases_is_silent(self):
        x = np.array([235958, 235959, 0, 1, 0.5, 2], dtype=float)
        with self.assertNoLogs("arrayprobe_uiops.sizedist", level="WARNING"):
            out, applied = v35.fix_multiday_particle_times(x)
        self.assertTrue(applied)


if __name__ == "__main__":
    unittest.main()
