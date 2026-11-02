# SPDX-License-Identifier: BSD-3-Clause
"""Tests for poisson_restore.py -- Korolev & Field (2015) Eq. 1-2, verified
against the real paper text (AMT 8, 761-777, 2015), not a secondary summary."""
from __future__ import annotations

import math
import unittest

import numpy as np

from arrayprobe_enhancements.poisson_restore import (
    large_particle_reacceptance_floor,
    mean_intact_interarrival_time,
    poisson_pair_false_rejection_probability,
    restoration_scale_factor,
    scale_size_distribution,
)


class MeanIntactInterarrivalTime(unittest.TestCase):
    def test_matches_eq1_by_hand(self):
        # tau = 1 / (n * S * u); n=10 m^-3, S=1e-4 m^2, u=100 m/s
        tau = mean_intact_interarrival_time(10.0, 1e-4, 100.0)
        self.assertAlmostEqual(tau, 1.0 / (10.0 * 1e-4 * 100.0))

    def test_higher_concentration_means_shorter_mean_spacing(self):
        low = mean_intact_interarrival_time(1.0, 1e-4, 100.0)
        high = mean_intact_interarrival_time(100.0, 1e-4, 100.0)
        self.assertGreater(low, high)


class PoissonPairFalseRejectionProbability(unittest.TestCase):
    def test_matches_eq2_by_hand(self):
        tau, tau_star = 0.01, 0.002
        expected = 0.5 * (tau_star / tau) ** 2 * math.exp(-tau_star / tau)
        self.assertAlmostEqual(
            poisson_pair_false_rejection_probability(tau, tau_star), expected)

    def test_zero_cutoff_means_no_false_rejections(self):
        """tau* = 0: no two particles can ever be "too close", so the false
        rejection probability must vanish -- Eq. 2 at tau* -> 0."""
        self.assertEqual(poisson_pair_false_rejection_probability(1.0, 0.0), 0.0)

    def test_increases_with_the_cutoff_time(self):
        """The paper states this explicitly (p. 764, just below Eq. 2): a
        larger tau* means more intact pairs are mistaken for shattering."""
        tau = 0.01
        p_small = poisson_pair_false_rejection_probability(tau, 0.001)
        p_large = poisson_pair_false_rejection_probability(tau, 0.005)
        self.assertLess(p_small, p_large)

    def test_increases_with_concentration(self):
        """Higher concentration -> shorter tau -> more false rejections at a
        fixed tau* (also stated explicitly on p. 764)."""
        tau_star = 0.002
        tau_sparse = mean_intact_interarrival_time(1.0, 1e-4, 100.0)
        tau_dense = mean_intact_interarrival_time(50.0, 1e-4, 100.0)
        p_sparse = poisson_pair_false_rejection_probability(tau_sparse, tau_star)
        p_dense = poisson_pair_false_rejection_probability(tau_dense, tau_star)
        self.assertLess(p_sparse, p_dense)


class RestorationScaleFactor(unittest.TestCase):
    def test_zero_rejection_is_a_no_op(self):
        self.assertEqual(restoration_scale_factor(0.0), 1.0)

    def test_half_rejected_doubles_the_surviving_population(self):
        self.assertAlmostEqual(restoration_scale_factor(0.5), 2.0)

    def test_rejection_fraction_of_one_or_more_is_rejected(self):
        """The model is undefined at f=1 (implies the whole population was
        removed) -- refuse rather than return inf silently."""
        with self.assertRaises(ValueError):
            restoration_scale_factor(1.0)
        with self.assertRaises(ValueError):
            restoration_scale_factor(1.5)

    def test_negative_fraction_is_rejected(self):
        with self.assertRaises(ValueError):
            restoration_scale_factor(-0.1)


class ScaleSizeDistribution(unittest.TestCase):
    def test_scales_every_bin_uniformly(self):
        conc = [1.0, 2.0, 0.0, 4.0]
        scaled = scale_size_distribution(conc, 0.5)
        np.testing.assert_allclose(scaled, [2.0, 4.0, 0.0, 8.0])

    def test_zero_stays_zero(self):
        """A bin with no particles has nothing to restore, at any scale."""
        scaled = scale_size_distribution([0.0], 0.9)
        self.assertEqual(scaled[0], 0.0)


class LargeParticleReacceptanceFloor(unittest.TestCase):
    def test_floor_has_no_default(self):
        """The exact threshold is an unverified citation (module docstring)
        -- calling without one must be a TypeError, not a silent guess."""
        with self.assertRaises(TypeError):
            large_particle_reacceptance_floor([1.0, 2.0])  # no floor given, on purpose

    def test_selects_particles_at_or_above_the_floor(self):
        diam = [100e-6, 500e-6, 500e-6 - 1e-9, 1000e-6]
        mask = large_particle_reacceptance_floor(diam, floor=500e-6)
        np.testing.assert_array_equal(mask, [False, True, False, True])

    def test_restricted_to_already_rejected_particles(self):
        """A particle the shattering rejection never touched has nothing to
        restore, however large it is."""
        diam = [1000e-6, 1000e-6]
        rejected = [True, False]
        mask = large_particle_reacceptance_floor(diam, floor=500e-6,
                                                  rejected_mask=rejected)
        np.testing.assert_array_equal(mask, [True, False])

    def test_no_rejected_mask_means_every_large_particle_is_a_candidate(self):
        diam = [1000e-6, 100e-6]
        mask = large_particle_reacceptance_floor(diam, floor=500e-6)
        np.testing.assert_array_equal(mask, [True, False])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
