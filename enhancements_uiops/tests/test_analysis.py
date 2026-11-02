# SPDX-License-Identifier: BSD-3-Clause
"""PSD moments, D_m, and leg aggregation -- against synthetic arrays and the
real tracked S4 Octave golden fixture."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements.analysis import (
    leg_mean,
    leg_total_count_with_uncertainty,
    mass_weighted_mean_diameter,
    moment,
)

ROOT = Path(__file__).resolve().parents[2]
REAL_FIXTURE = ROOT / "tests" / "data" / "demo_flight_v35_sd.nc"


class Moment(unittest.TestCase):
    def test_order_zero_is_the_integral_of_the_density(self):
        # Two bins, 1 mm wide (converts to 0.1 cm), density 10 cm-4 each ->
        # M0 = 10*0.1 + 10*0.1 = 2.0.
        bin_mid = np.array([1.0, 2.0])
        bin_dD = np.array([1.0, 1.0])
        density = np.array([10.0, 10.0])
        self.assertAlmostEqual(moment(bin_mid, bin_dD, density, order=0), 2.0)

    def test_order_one_weights_by_diameter(self):
        bin_mid = np.array([1.0, 2.0])
        bin_dD = np.array([1.0, 1.0])
        density = np.array([10.0, 10.0])
        # M1 = 1*10*0.1 + 2*10*0.1 = 1.0 + 2.0 = 3.0
        self.assertAlmostEqual(moment(bin_mid, bin_dD, density, order=1), 3.0)

    def test_nan_bins_are_excluded_not_zeroed_silently(self):
        bin_mid = np.array([1.0, 2.0])
        bin_dD = np.array([1.0, 1.0])
        density = np.array([10.0, np.nan])
        self.assertAlmostEqual(moment(bin_mid, bin_dD, density, order=0), 1.0)

    def test_works_on_a_time_by_bin_array_along_the_last_axis(self):
        bin_mid = np.array([1.0, 2.0])
        bin_dD = np.array([1.0, 1.0])
        density = np.array([[10.0, 10.0], [0.0, 0.0]])
        m0 = moment(bin_mid, bin_dD, density, order=0)
        np.testing.assert_allclose(m0, [2.0, 0.0])


class MassWeightedMeanDiameter(unittest.TestCase):
    def test_balances_at_the_diameter_the_mass_is_concentrated_at(self):
        # All mass in one bin at D=5 -- D_m must equal 5 exactly regardless
        # of the density's absolute scale.
        bin_mid = np.array([1.0, 5.0, 9.0])
        bin_dD = np.array([1.0, 1.0, 1.0])
        mass_density = np.array([0.0, 7.0, 0.0])
        self.assertAlmostEqual(mass_weighted_mean_diameter(bin_mid, bin_dD, mass_density), 5.0)

    def test_two_equal_masses_average_to_the_midpoint(self):
        bin_mid = np.array([2.0, 8.0])
        bin_dD = np.array([1.0, 1.0])
        mass_density = np.array([3.0, 3.0])
        self.assertAlmostEqual(mass_weighted_mean_diameter(bin_mid, bin_dD, mass_density), 5.0)

    def test_zero_total_mass_is_nan_not_zero(self):
        bin_mid = np.array([1.0, 2.0])
        bin_dD = np.array([1.0, 1.0])
        mass_density = np.array([0.0, 0.0])
        self.assertTrue(np.isnan(mass_weighted_mean_diameter(bin_mid, bin_dD, mass_density)))


class LegMean(unittest.TestCase):
    def test_defaults_to_the_whole_array(self):
        self.assertAlmostEqual(leg_mean(np.array([1.0, 2.0, 3.0])), 2.0)

    def test_a_slice_restricts_to_the_named_seconds(self):
        self.assertAlmostEqual(leg_mean(np.array([1.0, 2.0, 3.0, 100.0]), start=0, end=3), 2.0)

    def test_nan_seconds_are_excluded(self):
        self.assertAlmostEqual(leg_mean(np.array([1.0, np.nan, 3.0])), 2.0)


class LegTotalCountWithUncertainty(unittest.TestCase):
    def test_sums_every_bin_and_second_as_one_poisson_process(self):
        count = np.array([[4.0, 0.0], [0.0, 21.0]])
        total, relative, absolute = leg_total_count_with_uncertainty(count)
        self.assertAlmostEqual(total, 25.0)
        self.assertAlmostEqual(relative, 0.2)
        self.assertAlmostEqual(absolute, 5.0)

    def test_a_leg_slice_restricts_the_seconds_summed(self):
        count = np.array([[4.0, 0.0], [0.0, 100.0], [0.0, 21.0]])
        total, _relative, _absolute = leg_total_count_with_uncertainty(count, start=0, end=2)
        self.assertAlmostEqual(total, 104.0)


@unittest.skipUnless(REAL_FIXTURE.is_file(), "S4 Octave fixture not present")
class OnTheRealFixture(unittest.TestCase):
    def setUp(self):
        import netCDF4

        with netCDF4.Dataset(REAL_FIXTURE) as ds:
            self.bin_mid = np.asarray(ds.variables["bin_mid"][:])
            self.bin_dD = np.asarray(ds.variables["bin_dD"][:])
            self.conc_minR = np.asarray(ds.variables["conc_minR"][:])
            self.mass = np.asarray(ds.variables["mass"][:])
            self.n = np.asarray(ds.variables["n"][:])
            self.count = np.asarray(ds.variables["count"][:])

    def test_the_zeroth_moment_of_conc_minr_reproduces_n_exactly(self):
        """This is the claim the module docstring makes about the density
        convention -- checked here, not only asserted in prose."""
        m0 = moment(self.bin_mid, self.bin_dD, self.conc_minR, order=0)
        np.testing.assert_allclose(m0, self.n, rtol=1e-12)

    def test_dm_is_finite_where_real_mass_exists_and_nan_elsewhere(self):
        dm = mass_weighted_mean_diameter(self.bin_mid, self.bin_dD, self.mass)
        has_mass = np.nansum(self.mass, axis=1) > 0
        self.assertTrue(np.all(np.isfinite(dm[has_mass])))
        self.assertTrue(np.all(np.isnan(dm[~has_mass])))
        # D_m must fall within the populated bins' own range -- a weighted
        # average cannot land outside the values it averages.
        for i in np.where(has_mass)[0]:
            populated = self.mass[i] > 0
            # A tiny float tolerance for the upper bound only -- a
            # single-bin second's D_m equals that bin's own midpoint
            # exactly in exact arithmetic, but floating-point division can
            # land a few ULP above it.
            self.assertGreaterEqual(dm[i], self.bin_mid[populated].min())
            self.assertLessEqual(dm[i], self.bin_mid[populated].max() + 1e-9)

    def test_leg_total_count_over_the_whole_fixture_is_finite_and_positive(self):
        total, relative, absolute = leg_total_count_with_uncertainty(self.count)
        self.assertGreater(total, 0)
        self.assertTrue(np.isfinite(relative))
        self.assertAlmostEqual(absolute, relative * total)


if __name__ == "__main__":
    unittest.main()
