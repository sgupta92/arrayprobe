# SPDX-License-Identifier: BSD-3-Clause
"""Tests for rollover_fix.py.

Both states are exercised throughout: ``matlab_rollover`` is the correction *off*
(the port's own, first-decrease-only behaviour) and ``corrected_rollover`` is the
correction *on*.  The off state is not re-argued here -- it is asserted equal to
``arrayprobe.sizedist._rollover_240000``, the port's faithful transcription, so the
two sides of every A/B below come from different places.
"""

from __future__ import annotations

import unittest

import numpy as np
from arrayprobe_uiops.sizedist_core import _rollover_240000

from arrayprobe_enhancements.rollover_fix import (
    ROLLOVER,
    corrected_rollover,
    decrease_indices,
    halves_for_engine,
    matlab_rollover,
    rollover_report,
)

#: A flight that crosses midnight twice: 23:59 -> 00:00 -> 23:59 -> 00:00.
_TWO_CROSSINGS = [235958.0, 235959.0, 1.0, 2.0, 235959.5, 3.0]


class TheOffStateIsThePortsOwnBehaviour(unittest.TestCase):
    """The module's "before" side must be the port's, not a second transcription."""

    CASES = [
        [],
        [120000.0],
        [120000.0, 120001.0, 120002.0],          # no decrease at all
        [235959.0, 1.0, 2.0],                    # one crossing
        _TWO_CROSSINGS,                          # two crossings
        [5.0, 4.0, 3.0, 2.0],                    # every step decreases
    ]

    def test_matches_rollover_240000_element_for_element(self):
        for case in self.CASES:
            with self.subTest(case=case):
                port = _rollover_240000(np.array(case, dtype=np.float64))
                np.testing.assert_array_equal(matlab_rollover(case), port)

    def test_the_port_is_not_mutated_through_us(self):
        """`_rollover_240000` mutates in place; ours must not touch the caller's array."""
        original = np.array(_TWO_CROSSINGS, dtype=np.float64)
        keep = original.copy()
        matlab_rollover(original)
        corrected_rollover(original)
        np.testing.assert_array_equal(original, keep)


class TheDefect(unittest.TestCase):
    def test_only_the_first_decrease_is_corrected(self):
        out = matlab_rollover(_TWO_CROSSINGS)
        # The whole tail from the first crossing is shifted by one day...
        np.testing.assert_array_equal(
            out,
            [235958.0, 235959.0, 1.0 + ROLLOVER, 2.0 + ROLLOVER,
             235959.5 + ROLLOVER, 3.0 + ROLLOVER])
        # ...so the second crossing survives, un-rolled, as a decrease of nearly a day.
        self.assertEqual(decrease_indices(out).tolist(), [5])
        self.assertAlmostEqual(out[4] - out[5], 235956.5)

    def test_a_single_crossing_is_handled_correctly_by_the_original(self):
        """The defect needs two decreases; with one, both behaviours agree exactly."""
        one = [235959.0, 1.0, 2.0]
        np.testing.assert_array_equal(matlab_rollover(one), corrected_rollover(one))


class TheCorrection(unittest.TestCase):
    def test_every_crossing_is_corrected_and_the_result_is_monotonic(self):
        out = corrected_rollover(_TWO_CROSSINGS)
        np.testing.assert_array_equal(
            out,
            [235958.0, 235959.0, 1.0 + ROLLOVER, 2.0 + ROLLOVER,
             235959.5 + ROLLOVER, 3.0 + 2 * ROLLOVER])
        self.assertEqual(decrease_indices(out).size, 0)

    def test_it_is_a_no_op_where_there_is_no_decrease(self):
        clean = [64410.8, 64411.0, 75250.3]
        np.testing.assert_array_equal(corrected_rollover(clean), clean)
        np.testing.assert_array_equal(matlab_rollover(clean), clean)

    def test_short_and_empty_inputs_do_not_raise(self):
        for case in ([], [120000.0]):
            with self.subTest(case=case):
                self.assertEqual(corrected_rollover(case).size, len(case))
                self.assertEqual(matlab_rollover(case).size, len(case))

    def test_the_cumulative_form_equals_a_walk_over_the_decreases(self):
        """Adding a constant to a suffix cannot create or destroy a decrease, which is
        what makes the one-pass form correct; asserted rather than asserted-in-prose."""
        rng = np.random.default_rng(20260901)
        for _ in range(20):
            v = np.floor(rng.uniform(0, 240000, size=40))
            walked = v.astype(np.float64).copy()
            for i in np.flatnonzero(np.diff(walked) < 0) + 1:
                walked[i:] += ROLLOVER
            np.testing.assert_array_equal(corrected_rollover(v), walked)


class MinDropIsOptInAndOffByDefault(unittest.TestCase):
    def test_the_default_treats_any_decrease_as_midnight_exactly_like_matlab(self):
        jitter = [120000.0, 120000.5, 120000.4, 120001.0]
        self.assertEqual(decrease_indices(jitter).tolist(), [2])
        self.assertEqual(corrected_rollover(jitter)[2], 120000.4 + ROLLOVER)

    def test_a_threshold_can_exclude_a_sub_second_jitter(self):
        jitter = [120000.0, 120000.5, 120000.4, 120001.0]
        np.testing.assert_array_equal(corrected_rollover(jitter, min_drop=1.0), jitter)


class Report(unittest.TestCase):
    def test_it_names_the_residual_the_original_leaves(self):
        r = rollover_report(_TWO_CROSSINGS)
        self.assertEqual(r["decreases"], 2)
        self.assertEqual(r["corrected_by_matlab"], 1)
        self.assertEqual(r["uncorrected_decreases_remaining"], 1)
        self.assertTrue(r["monotonic_after_correction"])
        self.assertTrue(r["changed"])

    def test_a_clean_flight_reports_nothing_to_do(self):
        """The state every real ORACLES flight measured is in -- see the module docstring."""
        r = rollover_report([64410.8, 64411.0, 75250.3])
        self.assertEqual(r["decreases"], 0)
        self.assertEqual(r["uncorrected_decreases_remaining"], 0)
        self.assertFalse(r["changed"])


class EngineSplitOnV35(unittest.TestCase):
    """the two rollover sites diverged on v3.5 (S1's read against
    ``sizeDist.m:130-131`` / ``:788-799``); ``halves_for_engine`` states that
    split as data, and these tests measure it against the v3.5 port itself."""

    def test_halves_for_engine_314_both_apply(self):
        self.assertEqual(halves_for_engine("3.1.4"),
                         {"timehhmmss": "APPLIES", "particle_time": "APPLIES"})

    def test_halves_for_engine_35_particle_time_is_superseded(self):
        self.assertEqual(halves_for_engine("3.5"),
                         {"timehhmmss": "APPLIES", "particle_time": "SUPERSEDED"})

    def test_an_unknown_engine_raises_rather_than_defaulting(self):
        with self.assertRaises(ValueError):
            halves_for_engine("2.9")

    def test_single_crossing_the_timehhmmss_half_agrees_on_both_engines(self):
        """A single crossing is the case v3.5's own multi-day branch
        (``numel(find(...))==1``) also applies identically -- all three
        agree: the port's faithful transcription, this module's "before"
        side, and v3.5's own particle-time fix."""
        from arrayprobe_uiops.sizedist import fix_multiday_particle_times

        one = [235959.0, 1.0, 2.0]
        port = _rollover_240000(np.array(one, dtype=np.float64))
        v35_particle, applied = fix_multiday_particle_times(np.array(one))
        np.testing.assert_array_equal(matlab_rollover(one), port)
        np.testing.assert_array_equal(corrected_rollover(one), port)
        np.testing.assert_array_equal(v35_particle, port)
        self.assertTrue(applied)

    def test_double_crossing_names_the_first_crossover_residual_rather_than_asserting_equality(self):
        """v3.5's ``fix_multiday_particle_times`` (``sizeDist.m:788-799``) stops
        at the FIRST genuine crossover it finds and returns -- it does not loop
        over every one.  ``corrected_rollover`` applies every decrease,
        cumulatively.  On a two-crossing series they therefore agree everywhere
        except the tail, where the second, un-processed crossing leaves v3.5's
        own fix exactly one ROLLOVER short.  Read this before assuming the two
        corrections are interchangeable on a multi-crossing flight."""
        from arrayprobe_uiops.sizedist import fix_multiday_particle_times

        v35_out, applied = fix_multiday_particle_times(np.array(_TWO_CROSSINGS))
        ours = corrected_rollover(_TWO_CROSSINGS)
        self.assertTrue(applied)
        np.testing.assert_array_equal(v35_out[:5], ours[:5])
        self.assertEqual(ours[5] - v35_out[5], ROLLOVER)


if __name__ == "__main__":
    unittest.main()
