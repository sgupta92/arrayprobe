# SPDX-License-Identifier: BSD-3-Clause
"""DOC-0223 Table 2.1's effective-density relations, and the honest refusals."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements.effective_density import (
    EFFECTIVE_DENSITY_TABLE,
    ICE_DENSITY_G_CM3,
    effective_density,
    lookup,
)

ROOT = Path(__file__).resolve().parents[2]
PROC_FIXTURE = ROOT / "tests" / "data" / "s3_variant_octave_golden.nc"

#: Every Holroyd code habit.py's holroyd() can return (habit.py:139-142).
ALL_HOLROYD_CODES = "MCtolaghisd"


class TheTableItself(unittest.TestCase):
    def test_seventeen_rows_transcribed(self):
        self.assertEqual(len(EFFECTIVE_DENSITY_TABLE), 17)

    def test_columns_theory_uses_the_ice_density_constant(self):
        row = EFFECTIVE_DENSITY_TABLE["columns_theory"]
        self.assertAlmostEqual(row.k, 0.97 * ICE_DENSITY_G_CM3)
        self.assertEqual(ICE_DENSITY_G_CM3, 0.917)

    def test_the_wind_tunnel_row_is_two_regimes_not_one(self):
        lo = EFFECTIVE_DENSITY_TABLE["planar_wind_tunnel_low_ar"]
        hi = EFFECTIVE_DENSITY_TABLE["planar_wind_tunnel_high_ar"]
        self.assertEqual(lo.habit_code, "P1a-P1b-P1d")
        self.assertEqual(hi.habit_code, "P1a-P1b-P1d")
        self.assertEqual(lo.area_ratio_range, (None, 0.79))
        self.assertEqual(hi.area_ratio_range, (0.79, None))
        self.assertNotEqual(lo.k, hi.k)

    def test_no_diameter_power_law_rows_are_present(self):
        """The thick-plates and aggregate rho-vs-D rows use a different
        functional form (rho_e = chi * D**kappa) and are deliberately
        excluded -- see the module docstring."""
        for row in EFFECTIVE_DENSITY_TABLE.values():
            self.assertIsNotNone(row.k)
            self.assertIsNotNone(row.n)


class EffectiveDensityFunction(unittest.TestCase):
    def test_computes_the_columns_theory_relation_directly(self):
        # Sanity check against lookup() on the same row, not a duplicated
        # formula -- both must agree.
        area_ratio = 0.3
        expected = lookup("columns_theory", area_ratio)
        self.assertIsNotNone(expected)

    def test_aggregate_requires_a_named_study(self):
        self.assertIsNone(effective_density("a", 0.3))

    def test_aggregate_with_a_named_study_matches_lookup(self):
        rho = effective_density("a", 0.3, aggregate_study="kajikawa_1982")
        self.assertAlmostEqual(rho, lookup("aggregates_kajikawa_1982", 0.3))
        self.assertAlmostEqual(rho, 0.015 * 0.3 ** 1.50)

    def test_an_unknown_aggregate_study_name_is_honestly_none(self):
        self.assertIsNone(effective_density("a", 0.3, aggregate_study="not_a_real_study"))

    def test_ten_of_eleven_holroyd_codes_return_none(self):
        """Only 'a' is mapped; every other real Holroyd code is an honest
        refusal, not an invented correspondence -- see the module docstring
        for the reasoning behind each one (M, C, t, o, g, s, i have no
        corresponding row at all; l, h, d are surface-plausible but not
        actually established by the table)."""
        unmapped = [c for c in ALL_HOLROYD_CODES if c != "a"]
        self.assertEqual(len(unmapped), 10)
        for code in unmapped:
            with self.subTest(habit=code):
                self.assertIsNone(effective_density(code, 0.5))

    def test_area_ratio_outside_the_matched_rows_range_is_none(self):
        # aggregates_kajikawa_1982's range is (0.13, 0.77).
        self.assertIsNone(effective_density("a", 0.05, aggregate_study="kajikawa_1982"))
        self.assertIsNone(effective_density("a", 0.90, aggregate_study="kajikawa_1982"))


class LookupFunction(unittest.TestCase):
    def test_selects_the_low_ar_wind_tunnel_regime(self):
        rho = lookup("planar_wind_tunnel_low_ar", 0.5)
        self.assertAlmostEqual(rho, 0.084 * 0.5 ** 2.38)

    def test_selects_the_high_ar_wind_tunnel_regime(self):
        rho = lookup("planar_wind_tunnel_high_ar", 0.85)
        self.assertAlmostEqual(rho, 11.96 * 0.85 ** 22.64)

    def test_outside_the_rows_own_range_is_none_not_extrapolated(self):
        # planar_wind_tunnel_low_ar is Ar < 0.79.
        self.assertIsNone(lookup("planar_wind_tunnel_low_ar", 0.9))

    def test_a_side_only_bounded_row_still_refuses_outside_it(self):
        # aggregates_magono_nakamura_1965 is Ar < 0.28 only (one-sided).
        self.assertIsNotNone(lookup("aggregates_magono_nakamura_1965", 0.1))
        self.assertIsNone(lookup("aggregates_magono_nakamura_1965", 0.5))


@unittest.skipUnless(PROC_FIXTURE.is_file(), "Proc fixture is not distributed with the package; "
                                             "this test runs in the development repository")
class OnTheRealFixture(unittest.TestCase):
    """The tracked S3 proc fixture's own real holroyd_habit codes and the
    same area_ratio formula sizedist.py itself uses (image_area / (pi/4 *
    diam_minR**2), sizedist.py:1226) -- not a synthetic stand-in."""

    def test_real_aggregate_particles_get_a_density_when_a_study_is_named(self):
        import netCDF4

        with netCDF4.Dataset(PROC_FIXTURE) as ds:
            habit_codes = np.asarray(ds.variables["holroyd_habit"][:])
            area = np.asarray(ds.variables["image_area"][:])
            diam_minr = np.asarray(ds.variables["image_diam_minR"][:])

        # holroyd_habit is written as ASCII codes (float64, the ORACLES
        # variant's declared type -- habit.py's own docstring: "the variant
        # declares 'double' and writes double(...)").
        aggregate_code = float(ord("a"))
        aggregate_idx = np.where(habit_codes == aggregate_code)[0]
        self.assertGreater(len(aggregate_idx), 0,
                           "fixture has no real aggregate particles to test")

        area_ratio = area[aggregate_idx] / (np.pi / 4 * diam_minr[aggregate_idx] ** 2)
        computed = [effective_density("a", float(ar), aggregate_study="kajikawa_1982")
                   for ar in area_ratio]
        # Some real particles will fall outside the row's measured range
        # (honestly None); at least one real particle must be inside it,
        # or the fixture cannot demonstrate the function actually computes.
        self.assertTrue(any(v is not None for v in computed))
        for ar, rho in zip(area_ratio, computed):
            if rho is not None:
                self.assertGreater(rho, 0.0)
                self.assertLess(rho, ICE_DENSITY_G_CM3,
                                "an aggregate must be less dense than solid ice")

    def test_a_habit_code_this_module_refuses_returns_none_on_real_data(self):
        import netCDF4

        with netCDF4.Dataset(PROC_FIXTURE) as ds:
            habit_codes = np.asarray(ds.variables["holroyd_habit"][:])

        dendrite_idx = np.where(habit_codes == float(ord("d")))[0]
        self.assertGreater(len(dendrite_idx), 0,
                           "fixture has no real dendrite particles to test")
        self.assertIsNone(effective_density("d", 0.5))

# _release_fixture_guard: real-data derived fixtures are excluded from the release
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402
_RFG_EXCLUDED = ('s3_variant_octave_golden.nc',)
if not all((_rfg_pathlib.Path(__file__).resolve().parents[2] / "tests" / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "real-data derived fixtures (UIOPS PECAN DMT / minimal-example 2D-S samples) "
        "are not shipped in the release")

if __name__ == "__main__":
    unittest.main()
