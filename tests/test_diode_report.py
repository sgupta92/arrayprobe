# SPDX-License-Identifier: BSD-3-Clause
"""The diode-uniformity report and SPEC's noisy-diode test.

A stuck diode is invisible per particle and obvious per flight: `imgProc_sm`
judges each silhouette on its own, and a column dark in all of them is
perfectly consistent with a stream of narrow particles. So these tests are
built around synthetic flights with a *known* stuck column, and they check that
the report finds it and that a healthy flight does not trip the detector.

Two things are asserted about honesty rather than arithmetic, and they are the
reason this module is a report and not a repair:

* the SPEC criterion carries which of its parts were transcribed from the
  manual and which was inferred, and the inferred one must stay labelled;
* stuck-bit *repair* is recorded as not built, with the sections that would be
  needed to build it -- writing values into a silhouette from an invented rule
  would put fabricated pixels into every downstream size, area and habit.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from arrayprobe.diode_report import (
    NOT_BUILT,
    SPEC_NOISY_DIODE,
    SpecNoisyDiodeCriterion,
    accumulate_occupancy,
    flag_noisy_diodes,
)

N_DIODES = 16


def _particle(n_slices: int, columns, stuck: int | None = None, seed: int = 0):
    """One silhouette: `columns` lit per slice at random, plus a stuck column."""
    rng = np.random.default_rng(seed)
    shadow = np.zeros((n_slices, N_DIODES), dtype=bool)
    for row in range(n_slices):
        shadow[row, rng.choice(N_DIODES, size=columns, replace=False)] = True
    if stuck is not None:
        shadow[:, stuck] = True
    return shadow


class TheReportCountsWhatItSaysItCounts(unittest.TestCase):
    def test_occupancy_is_shadowed_slices_over_all_slices(self):
        a = np.zeros((4, N_DIODES), dtype=bool)
        a[:, 3] = True          # one column dark in every slice
        a[0, 7] = True          # one slice of another
        report = accumulate_occupancy([a])
        self.assertEqual(report.total_slices, 4)
        self.assertEqual(report.total_images, 1)
        self.assertAlmostEqual(report.occupancy[3], 1.0)
        self.assertAlmostEqual(report.occupancy[7], 0.25)
        self.assertAlmostEqual(report.occupancy[0], 0.0)

    def test_images_present_counts_images_not_slices(self):
        """The SPEC criterion counts images; occupancy counts slices.

        Conflating them would make a single long particle look like many
        events, which is the difference between a threshold that means
        something and one that does not.
        """
        a = np.zeros((100, N_DIODES), dtype=bool)
        a[:, 2] = True
        report = accumulate_occupancy([a])
        self.assertEqual(report.shadowed_slices[2], 100)
        self.assertEqual(report.images_present[2], 1)

    def test_an_empty_particle_contributes_nothing_rather_than_raising(self):
        report = accumulate_occupancy([np.zeros((0, N_DIODES), dtype=bool),
                                       _particle(3, 2)])
        self.assertEqual(report.total_images, 1)

    def test_no_particles_at_all_is_an_empty_report_not_a_crash(self):
        report = accumulate_occupancy([])
        self.assertEqual(report.total_images, 0)
        self.assertEqual(report.occupancy.size, 0)
        self.assertIn("nothing to report", report.summary())

    def test_a_changing_diode_count_is_refused(self):
        """Two array widths in one report would silently average two probes."""
        with self.assertRaises(ValueError):
            accumulate_occupancy([_particle(3, 2),
                                  np.zeros((3, N_DIODES + 1), dtype=bool)])


class AStuckDiodeIsVisibleAtFlightScaleOnly(unittest.TestCase):
    def test_the_stuck_column_has_the_highest_occupancy(self):
        stuck = 9
        report = accumulate_occupancy(
            _particle(6, 2, stuck=stuck, seed=i) for i in range(200))
        self.assertEqual(int(np.argmax(report.occupancy)), stuck)
        self.assertAlmostEqual(report.occupancy[stuck], 1.0)

    def test_the_summary_names_the_worst_diode_one_based(self):
        report = accumulate_occupancy(
            _particle(6, 2, stuck=4, seed=i) for i in range(50))
        self.assertIn("diode 5", report.summary())

    def test_a_stuck_diode_is_flagged_and_the_others_are_not(self):
        report = accumulate_occupancy(
            _particle(6, 1, stuck=11, seed=i) for i in range(500))
        flagged, threshold, mean = flag_noisy_diodes(report)
        self.assertIn(11, flagged.tolist())
        self.assertEqual(len(flagged), 1,
                         f"only the stuck diode should trip TH={threshold:.1f} "
                         f"(mean {mean:.1f}); flagged {flagged.tolist()}")

    def test_a_healthy_flight_flags_nothing(self):
        """The other direction: a detector that fires on clean data is noise."""
        report = accumulate_occupancy(_particle(6, 3, seed=i) for i in range(500))
        flagged, _threshold, _mean = flag_noisy_diodes(report)
        self.assertEqual(flagged.tolist(), [])


class TheThresholdIsTheManufacturersArithmetic(unittest.TestCase):
    def test_the_formula_is_M_plus_five_root_M(self):
        self.assertAlmostEqual(SPEC_NOISY_DIODE.threshold(100.0),
                               100.0 + 5.0 * math.sqrt(100.0))

    def test_the_floor_applies_where_the_formula_falls_below_it(self):
        """M = 0 gives 0, and the manual's floor is what stops a threshold of
        zero flagging every diode in an empty window."""
        self.assertEqual(SPEC_NOISY_DIODE.threshold(0.0), 1.5)

    def test_a_negative_mean_raises_rather_than_returning_nan(self):
        """sqrt of a negative is NaN, and NaN as a threshold flags nothing --
        a detector that silently switches itself off."""
        with self.assertRaises(ValueError):
            SPEC_NOISY_DIODE.threshold(-1.0)

    def test_the_transcribed_constants_are_the_manuals(self):
        self.assertEqual(SPEC_NOISY_DIODE.sigma_coefficient, 5.0)
        self.assertEqual(SPEC_NOISY_DIODE.floor, 1.5)
        self.assertEqual(SPEC_NOISY_DIODE.window_images, 4000)
        self.assertEqual(SPEC_NOISY_DIODE.refresh_every, 100)
        self.assertIn("Appendix B", SPEC_NOISY_DIODE.source)

    def test_a_caller_can_supply_its_own_criterion(self):
        strict = SpecNoisyDiodeCriterion(
            sigma_coefficient=1.0, floor=0.0, window_images=10,
            refresh_every=1, source="test", m_definition_established="derived",
            m_definition_note="test")
        self.assertAlmostEqual(strict.threshold(4.0), 6.0)


class WhatIsInferredStaysLabelled(unittest.TestCase):
    """The honesty the m-D registry established, applied to a second source."""

    def test_the_meaning_of_M_is_marked_derived_not_transcribed(self):
        self.assertEqual(SPEC_NOISY_DIODE.m_definition_established, "derived",
                         "what the manual says M counts has not been read here; "
                         "promoting this to 'transcribed' requires reading "
                         "Appendix B, not deciding the reading looks right")

    def test_the_note_says_what_would_confirm_it(self):
        note = SPEC_NOISY_DIODE.m_definition_note
        self.assertIn("App. B", note)
        self.assertGreater(len(note), 100, "a gap note too short to act on")

    def test_stuck_bit_repair_is_recorded_as_not_built(self):
        self.assertIn("stuck_bit_repair", NOT_BUILT)
        why = NOT_BUILT["stuck_bit_repair"]
        self.assertIn("1.1", why)
        self.assertIn("1.2", why)
        self.assertIn("enhancements_uiops/", why,
                      "a repair changes numbers, so it belongs outside the port")


if __name__ == "__main__":
    unittest.main()
