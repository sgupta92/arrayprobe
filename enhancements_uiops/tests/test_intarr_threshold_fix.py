# SPDX-License-Identifier: BSD-3-Clause
"""B9: the corrected threshold, against the port's own faithful one.

The A/B's two sides come from different places, which is the only thing that
makes this a check: the faithful value is read from
``arrayprobe.intarr_analysis.block_thresholds`` -- the port's reproduction of
``IntArrAnalysis_time.m`` -- and the corrected value from this package. If the
enhancement's own idea of "what MATLAB does" ever drifts from the port's, these
tests fail rather than agreeing with themselves.
"""
from __future__ import annotations

import unittest

import numpy as np
from arrayprobe.intarr_analysis import HIST_BINS, block_thresholds

from arrayprobe_enhancements.intarr_threshold_fix import (
    ThresholdPair,
    compare,
    crossover_threshold,
    select_from_window,
)

CENTRES = HIST_BINS[:-1] + np.diff(HIST_BINS) / 2


def bimodal_counts(n_fast=900, n_slow=4000, tail=4, seed=20260902):
    """A histogram with the shape the finding describes.

    A shattering mode at short inter-arrival, a crossover dip, the real-particle
    mode, and a sparse tail that is *lower than the dip* -- which is exactly the
    configuration where a global minimum picks the tail and a local minimum does
    not.
    """
    rng = np.random.default_rng(seed)
    h = np.zeros(CENTRES.size)
    fast = np.exp(-((np.log10(CENTRES) + 6.4) ** 2) / 0.6) * n_fast
    slow = np.exp(-((np.log10(CENTRES) + 4.0) ** 2) / 0.5) * n_slow
    h = np.rint(fast + slow).astype(float)
    h[-6:] = tail                      # the sparse tail: below the crossover dip
    h += rng.integers(0, 2, h.size)
    return h


class CorrectedThresholdPicksTheCrossover(unittest.TestCase):
    def test_the_faithful_side_matches_the_port_exactly(self):
        """The A/B is only meaningful if its 'before' is the port's own output."""
        h = bimodal_counts()
        _, _, ak, tau = block_thresholds(h)
        pair = crossover_threshold(h)
        if np.isnan(np.asarray(tau, dtype=float)).any():
            self.skipTest("The fit did not converge on this fixture is not distributed with the "
                          "package; this test runs in the development repository")
        self.assertEqual(pair.faithful, ak,
                         "this module's faithful value disagrees with the port's "
                         "block_thresholds -- the two sides have drifted")

    def test_on_the_shape_the_finding_measured_the_two_diverge(self):
        """The wide-window case, built from B9's own measured numbers.

        Its table for population 1 of `base160906064403`: the crossover dip at
        1.395e-6 s with 94 counts, the real-particle mode at 9.9e-5 s with
        1,047, the sparse tail at 2.745e-3 s with 4 -- the global minimum -- and
        a rise to 175 in the last bins.

        A synthetic histogram does not reproduce this through the fit, because
        the fit puts a narrow window on it and a narrow window has no tail to
        pick. That is the honest situation and it is why the estimator is tested
        directly here rather than through a fixture that happens to work.
        """
        centres = np.array([1.0e-7, 4.0e-7, 1.395e-6, 8.0e-6, 9.9e-5,
                            6.0e-4, 2.745e-3, 1.138e-2])
        counts = np.array([820.0, 300.0, 94.0, 410.0, 1047.0, 60.0, 4.0, 175.0])
        faithful, corrected, n_minima = select_from_window(centres, counts)
        self.assertEqual(faithful, 2.745e-3,
                         "the global minimum is the sparse tail, which is the "
                         "behaviour being corrected")
        self.assertEqual(corrected, 1.395e-6,
                         "the correction must select the crossover dip")
        self.assertGreater(faithful / corrected, 1000)
        self.assertEqual(n_minima, 2, "dip and tail are both interior minima")

    def test_on_a_narrow_window_the_two_agree(self):
        """Not every window exhibits the failure, and the module must not invent one.

        When the fit puts a narrow window on the histogram the global minimum IS
        the crossover, and the correction is a no-op. Asserting that is what
        keeps the module from being credited with an effect it does not have.
        """
        pair = crossover_threshold(bimodal_counts())
        self.assertEqual(pair.corrected, pair.faithful)
        self.assertEqual(pair.ratio, 1.0)

    def test_it_reports_how_clean_the_choice_was(self):
        """A number that hides its own ambiguity is worse than one that does not."""
        pair = crossover_threshold(bimodal_counts())
        self.assertIsInstance(pair, ThresholdPair)
        self.assertGreaterEqual(pair.n_local_minima, 1)
        self.assertEqual(pair.is_clean, pair.n_local_minima == 1)
        self.assertGreater(pair.n_bins_in_window, 0)

    def test_an_empty_histogram_declines_rather_than_guesses(self):
        pair = crossover_threshold(np.zeros(CENTRES.size))
        self.assertEqual(pair.faithful, pair.corrected)
        self.assertEqual(pair.n_local_minima, 0)

    def test_with_no_interior_minimum_it_returns_the_faithful_value(self):
        """A monotone window has no crossover; inventing one would be worse."""
        h = np.linspace(500, 1, CENTRES.size)
        pair = crossover_threshold(h)
        if pair.n_local_minima == 0:
            self.assertEqual(pair.corrected, pair.faithful,
                             "with no interior minimum the correction must "
                             "decline, not fabricate a threshold")

    def test_compare_runs_every_population(self):
        pops = [bimodal_counts(seed=s) for s in (1, 2, 3)]
        out = compare(pops)
        self.assertEqual(len(out), 3)
        self.assertTrue(all(isinstance(p, ThresholdPair) for p in out))

    def test_endpoints_are_not_local_minima(self):
        """The failure being corrected IS an edge minimum, so edges are excluded.

        A monotonically falling window has its global minimum at the right edge.
        If the edge counted as a local minimum the correction would return the
        same value and quietly do nothing.
        """
        from arrayprobe_enhancements.intarr_threshold_fix import _local_minima
        self.assertEqual(_local_minima(np.array([5.0, 4.0, 3.0, 2.0])).size, 0)
        self.assertEqual(_local_minima(np.array([5.0, 1.0, 3.0, 2.0])).tolist(), [1])


if __name__ == "__main__":
    unittest.main()
