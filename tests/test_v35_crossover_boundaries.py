# SPDX-License-Identifier: BSD-3-Clause
"""v3.5's midnight-crossover tests, on their exact thresholds (pass 5, item 3).

``sizeDist.m:796-797`` (v3.5) shifts particle times by ``+240000`` at the first
decrease where ``x(d) > 230000`` and ``x(d) - x(d+1) > 230000``; ``:808-810`` adds
``240000`` to every particle when the flight's ``timehhmmss`` has any value
``> 240000`` and the particles none.  All three comparisons are strict, and
turning any one into ``>=`` (or raising the ``230000`` by one) left every v3.5 test
green: no fixture sits on a threshold.  Expected values are *derived* from those
lines, not measured under Octave.
"""
from __future__ import annotations

import unittest

import numpy as np

from arrayprobe_uiops.sizedist import apply_flight_day_carryover, fix_multiday_particle_times


class TheCrossoverTest(unittest.TestCase):
    def test_a_drop_of_exactly_230000_is_not_a_crossover(self):
        x = np.array([100.0, 50.0, 230001.0, 1.0])  # two decreases; the second drops 230000
        with self.assertLogs("arrayprobe_uiops", level="WARNING"):
            got, shifted = fix_multiday_particle_times(x)
        self.assertFalse(shifted)
        np.testing.assert_array_equal(got, x)

    def test_just_above_both_thresholds_is_a_crossover(self):
        x = np.array([100.0, 50.0, 230001.0, 0.0])  # 230001 > 230000, drop 230001
        got, shifted = fix_multiday_particle_times(x)
        self.assertTrue(shifted)
        np.testing.assert_array_equal(got, [100.0, 50.0, 230001.0, 240000.0])


class TheFlightDayCarryover(unittest.TestCase):
    def test_a_flight_time_of_exactly_240000_carries_nothing(self):
        x = np.array([10.0, 20.0])
        np.testing.assert_array_equal(
            apply_flight_day_carryover(x, np.array([235959.0, 240000.0])), x)

    def test_a_flight_time_past_240000_carries_every_particle(self):
        x = np.array([10.0, 20.0])
        np.testing.assert_array_equal(
            apply_flight_day_carryover(x, np.array([235959.0, 240001.0])), x + 240000.0)


if __name__ == "__main__":
    unittest.main()
