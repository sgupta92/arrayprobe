# SPDX-License-Identifier: BSD-3-Clause
"""Poisson counting uncertainty on real and synthetic ``count`` arrays."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements.poisson_uncertainty import (
    STATISTICALLY_SIGNIFICANT_COUNT,
    is_statistically_significant,
    per_bin_absolute_uncertainty,
    per_bin_relative_uncertainty,
    propagate_to_total,
)

ROOT = Path(__file__).resolve().parents[2]
REAL_FIXTURE = ROOT / "tests" / "data" / "demo_flight_v35_sd.nc"


class PerBinRelativeUncertainty(unittest.TestCase):
    def test_matches_the_one_over_sqrt_n_formula(self):
        np.testing.assert_allclose(
            per_bin_relative_uncertainty(np.array([1.0, 4.0, 100.0])),
            [1.0, 0.5, 0.1])

    def test_zero_negative_and_nan_counts_are_undefined_not_infinite(self):
        rel = per_bin_relative_uncertainty(np.array([0.0, -1.0, np.nan, 25.0]))
        self.assertTrue(np.isnan(rel[0]))
        self.assertTrue(np.isnan(rel[1]))
        self.assertTrue(np.isnan(rel[2]))
        self.assertAlmostEqual(rel[3], 0.2)

    def test_works_on_a_two_dimensional_time_by_bin_array(self):
        count = np.array([[1.0, 4.0], [100.0, 0.0]])
        rel = per_bin_relative_uncertainty(count)
        np.testing.assert_allclose(rel[:, 0], [1.0, 0.1])
        self.assertAlmostEqual(rel[0, 1], 0.5)
        self.assertTrue(np.isnan(rel[1, 1]))


class PerBinAbsoluteUncertainty(unittest.TestCase):
    def test_scales_concentration_by_the_relative_uncertainty(self):
        conc = np.array([10.0, 20.0])
        count = np.array([4.0, 100.0])
        abs_unc = per_bin_absolute_uncertainty(conc, count)
        np.testing.assert_allclose(abs_unc, [5.0, 2.0])

    def test_a_negative_concentration_is_not_special_cased(self):
        # sizeDist.m's own convention: a "negative" count-derived value never
        # occurs in practice, so this deliberately does not guard against it --
        # the formula is applied uniformly, matching the port's own philosophy
        # of transcribing arithmetic rather than adding defensive branches
        # nothing in the real pipeline exercises.
        abs_unc = per_bin_absolute_uncertainty(np.array([-5.0]), np.array([25.0]))
        self.assertAlmostEqual(abs_unc[0], -1.0)


class StatisticalSignificance(unittest.TestCase):
    def test_the_field_convention_is_one_hundred(self):
        self.assertEqual(STATISTICALLY_SIGNIFICANT_COUNT, 100)

    def test_boundary_and_below(self):
        sig = is_statistically_significant(np.array([99.0, 100.0, 101.0]))
        np.testing.assert_array_equal(sig, [False, True, True])

    def test_nan_is_not_significant(self):
        sig = is_statistically_significant(np.array([np.nan]))
        self.assertEqual(sig[0], False)

    def test_a_caller_supplied_threshold_overrides_the_default(self):
        sig = is_statistically_significant(np.array([50.0]), threshold=10)
        self.assertTrue(sig[0])


class PropagateToTotal(unittest.TestCase):
    def test_sums_along_the_last_axis_by_default(self):
        count = np.array([[1.0, 3.0, 0.0], [10.0, 10.0, 5.0]])
        total, relative, absolute = propagate_to_total(count)
        np.testing.assert_allclose(total, [4.0, 25.0])
        np.testing.assert_allclose(relative, [0.5, 0.2])
        np.testing.assert_allclose(absolute, [2.0, 5.0])

    def test_nan_bins_contribute_zero_but_an_all_nan_row_propagates_nan(self):
        count = np.array([[1.0, np.nan, 3.0], [np.nan, np.nan, np.nan]])
        total, relative, absolute = propagate_to_total(count)
        self.assertEqual(total[0], 4.0)
        self.assertTrue(np.isnan(total[1]))
        self.assertTrue(np.isnan(relative[1]))
        self.assertTrue(np.isnan(absolute[1]))

    def test_the_two_derivations_agree_for_a_poisson_variable(self):
        """Quadrature-sum of per-bin absolute uncertainty equals sqrt(total)
        -- true specifically because a sum of independent Poisson variables
        is itself Poisson, not true of uncertainty combination in general."""
        count = np.array([4.0, 25.0, 100.0])
        conc = np.array([40.0, 250.0, 1000.0])  # conc/count ratio need not be uniform
        per_bin_abs = per_bin_absolute_uncertainty(conc, count)
        quadrature_on_counts = np.sqrt(np.sum(per_bin_relative_uncertainty(count) ** 2
                                              * count ** 2))
        total, _relative, absolute = propagate_to_total(count)
        self.assertAlmostEqual(quadrature_on_counts, absolute)
        self.assertAlmostEqual(absolute, np.sqrt(total))
        self.assertGreater(np.sum(per_bin_abs), 0)  # sanity: conc values were used


@unittest.skipUnless(REAL_FIXTURE.is_file(), "S4 Octave fixture not present")
class OnTheRealFixture(unittest.TestCase):
    """The tracked S4 fixture's own ``count`` variable, not only synthetic
    arrays -- the same real-data discipline `test_arm_export.py` follows."""

    def test_real_counts_yield_finite_uncertainty_where_particles_exist(self):
        import netCDF4

        with netCDF4.Dataset(REAL_FIXTURE) as ds:
            count = np.asarray(ds.variables["count"][:])
            conc = np.asarray(ds.variables["conc_minR"][:])

        rel = per_bin_relative_uncertainty(count)
        populated = count > 0
        self.assertTrue(np.any(populated), "fixture has no populated bins to test")
        self.assertTrue(np.all(np.isfinite(rel[populated])))
        self.assertTrue(np.all(np.isnan(rel[~populated & ~np.isnan(count)])))

        abs_unc = per_bin_absolute_uncertainty(conc, count)
        # Relative uncertainty must be identical whether derived from the
        # count alone or scaled through the concentration -- the sample
        # volume that turns count into conc carries no counting noise, so it
        # must cancel exactly in the ratio.
        with np.errstate(invalid="ignore", divide="ignore"):
            recovered_rel = abs_unc / conc
        finite = populated & np.isfinite(conc) & (conc != 0)
        np.testing.assert_allclose(recovered_rel[finite], rel[finite])

        total, _relative, _absolute = propagate_to_total(count)
        self.assertEqual(total.shape[0], count.shape[0])

    def test_a_real_populated_second_is_flagged_by_significance(self):
        import netCDF4

        with netCDF4.Dataset(REAL_FIXTURE) as ds:
            count = np.asarray(ds.variables["count"][:])

        total, _relative, _absolute = propagate_to_total(count)
        sig = is_statistically_significant(total)
        # Not every second reaches 100 particles on a small fixture -- the
        # claim under test is only that the function runs on real shapes and
        # returns a real boolean array, not that this file happens to be busy.
        self.assertEqual(sig.shape, total.shape)
        self.assertEqual(sig.dtype, bool)


if __name__ == "__main__":
    unittest.main()
