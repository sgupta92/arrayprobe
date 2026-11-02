# SPDX-License-Identifier: BSD-3-Clause
"""``dmax_sensitivity`` -- the six ``d_choice`` diameters compared, real
particles."""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None  # type: ignore[assignment]  # optional-dependency sentinel: mypy cannot type a module-or-None name

from arrayprobe_enhancements.dmax_sensitivity import compute_sensitivity

FIXTURE = (Path(__file__).resolve().parents[2] / "tests" / "data"
          / "demo_flight_v35_proc.nc")


class SyntheticCases(unittest.TestCase):
    def test_a_square_particle_still_disagrees_on_hypotenuse(self):
        """length == width == minR: d_length/d_width/d_mean/d_max agree with
        each other (all int16-saturating, per A2), but d_hypot does not --
        ``sqrt`` promotes to double and escapes the saturation, exactly as
        ``_d_hypot``'s own docstring documents. A real, measured consequence
        of the choice, not a bug in this module."""
        length = width = np.array([40], dtype=np.int16)
        minr = np.array([40 * 0.01])
        result = compute_sensitivity(length, width, 0.01, minr)
        self.assertEqual(result.diameters.shape, (1, 6))
        d = dict(zip(result.d_choice_labels, result.diameters[0]))
        self.assertAlmostEqual(d["L_x"], d["L_y"], places=6)
        self.assertAlmostEqual(d["L_x"], d["mean(L_x,L_y)"], places=6)
        self.assertAlmostEqual(d["L_x"], d["max(L_x,L_y)"], places=6)
        self.assertNotAlmostEqual(d["hypotenuse(L_x,L_y)"], d["L_x"], places=6)
        self.assertGreater(d["hypotenuse(L_x,L_y)"], 0.0)

    def test_an_elongated_particle_shows_real_spread(self):
        """length >> width: d_length and d_width diverge sharply; d_hypot
        exceeds both since it is the diagonal."""
        length = np.array([100], dtype=np.int16)
        width = np.array([10], dtype=np.int16)
        minr = np.array([50 * 0.01])
        result = compute_sensitivity(length, width, 0.01, minr)
        d = dict(zip(result.d_choice_labels, result.diameters[0]))
        self.assertGreater(d["hypotenuse(L_x,L_y)"], d["L_x"])
        self.assertGreater(d["L_x"], d["L_y"])
        self.assertGreater(result.spread_relative[0], 0.5)

    def test_summary_is_pooled_correctly(self):
        length = np.array([40, 100], dtype=np.int16)
        width = np.array([40, 10], dtype=np.int16)
        minr = np.array([40 * 0.01, 50 * 0.01])
        result = compute_sensitivity(length, width, 0.01, minr)
        summary = result.summary()
        self.assertEqual(summary["n_particles"], 2)
        self.assertGreaterEqual(summary["max_relative_spread_pct"],
                                summary["mean_relative_spread_pct"])

    def test_zero_size_particle_is_nan_not_a_crash(self):
        length = width = np.array([0], dtype=np.int16)
        minr = np.array([0.0])
        result = compute_sensitivity(length, width, 0.01, minr)
        self.assertTrue(np.isnan(result.spread_relative[0]))


@unittest.skipUnless(netCDF4 is not None and FIXTURE.is_file(),
                     "netCDF4 or the tracked v3.5 demo proc is not available")
class RealParticles(unittest.TestCase):
    """The sensitivity table over every particle of the shipped synthetic
    v3.5 demo proc, not hand-built geometry."""

    def test_real_particles_have_measurable_spread(self):
        with netCDF4.Dataset(str(FIXTURE)) as ds:
            length = np.asarray(ds.variables["image_length"][:])
            width = np.asarray(ds.variables["image_width"][:])
            minr = np.asarray(ds.variables["image_diam_minR"][:], dtype=float)

        result = compute_sensitivity(length, width, 0.01, minr)
        self.assertEqual(result.diameters.shape[0], length.shape[0])
        summary = result.summary()
        # A real, reproducible measurement -- not a bound picked to pass.
        # Printed so it lands in the design doc verbatim, not retyped.
        print(f"\n[dmax_sensitivity] {summary}")
        self.assertGreater(summary["n_particles"], 0)
        self.assertFalse(np.isnan(summary["mean_relative_spread_pct"]))


V35_PROC = (Path(__file__).resolve().parents[2] / "tests" / "data"
           / "demo_flight_v35_proc.nc")


@unittest.skipUnless(netCDF4 is not None and V35_PROC.is_file(),
                     "netCDF4 or the tracked v3.5 demo proc is not available")
class EngineParameter(unittest.TestCase):
    """``engine=`` selects which port's d_choice math is reused."""

    def test_default_engine_is_byte_identical_to_before_the_engine_parameter(self):
        """Two independent code paths -- the module's own default call, and a
        direct reimplementation of the pre-``engine`` loop over
        ``_D_CHOICE_SPECS`` -- must agree exactly. This is the "before" side
        the plan asks for, reimplemented rather than a stale pinned copy."""
        from arrayprobe_enhancements.dmax_sensitivity import _D_CHOICE_SPECS
        length = np.array([4, 100, 40], dtype=np.int16)
        width = np.array([4, 10, 40], dtype=np.int16)
        minr = np.array([0.048, 0.5, 0.4])
        expected_labels = []
        expected_columns = []
        for _n, _key, fn, label, _cite in _D_CHOICE_SPECS:
            expected_labels.append(label)
            expected_columns.append(np.asarray(
                fn(length, width, 0.01, minr), dtype=float))
        expected = np.column_stack(expected_columns)

        default_result = compute_sensitivity(length, width, 0.01, minr)
        explicit_result = compute_sensitivity(length, width, 0.01, minr, engine="3.1.4")
        for result in (default_result, explicit_result):
            self.assertEqual(result.d_choice_labels, tuple(expected_labels))
            np.testing.assert_array_equal(result.diameters, expected)

    def test_unknown_engine_raises(self):
        with self.assertRaises(ValueError):
            compute_sensitivity(np.array([4], dtype=np.int16),
                                np.array([4], dtype=np.int16), 0.01,
                                np.array([0.04]), engine="2.9")

    def test_v35_and_v314_spreads_differ_only_where_A2_saturation_bites(self):
        """On the tracked v3.5 demo proc's real particles (5, all
        ``image_length == image_width == 4``), A2's ``int16 x double``
        rounding collapses the 3.1.4 engine's ``d_choice`` 1/2/3/5 columns
        toward zero (``4 * 0.01`` rounds to integer 0 before the cast); the
        3.5 engine casts to ``float64`` first (measured ``sizeDist.m:941-
        942``) and keeps the real value. ``d_choice == 6`` reads
        ``image_diam_minR`` directly on both engines and must match exactly.
        """
        with netCDF4.Dataset(str(V35_PROC)) as ds:
            length = np.asarray(ds.variables["image_length"][:])
            width = np.asarray(ds.variables["image_width"][:])
            minr = np.asarray(ds.variables["image_diam_minR"][:], dtype=float)

        v314 = compute_sensitivity(length, width, 0.01, minr, engine="3.1.4")
        v35 = compute_sensitivity(length, width, 0.01, minr, engine="3.5")
        self.assertEqual(v314.d_choice_labels, v35.d_choice_labels)

        d_minr_col = v314.d_choice_labels.index("D of minimum enclosing circle")
        np.testing.assert_array_equal(v314.diameters[:, d_minr_col],
                                      v35.diameters[:, d_minr_col])

        saturating = {"L_x", "L_y", "mean(L_x,L_y)", "max(L_x,L_y)"}
        saturated_any = False
        for label in v314.d_choice_labels:
            if label not in saturating:
                continue
            col = v314.d_choice_labels.index(label)
            if np.any(v314.diameters[:, col] == 0.0) and np.all(v35.diameters[:, col] > 0.0):
                saturated_any = True
                self.assertTrue(np.all(v314.diameters[:, col] != v35.diameters[:, col]))
        self.assertTrue(saturated_any,
                        "expected at least one d_choice column to show A2's "
                        "3.1.4-only saturation on this fixture -- if this "
                        "fails, the fixture's particles no longer exercise "
                        "the collapse-toward-zero rounding this test measures")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
