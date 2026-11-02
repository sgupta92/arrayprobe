# SPDX-License-Identifier: BSD-3-Clause
"""The ARCO export must be lossless by default, and honest when it is not.

**Why these are the assertions.** This package's whole claim is fidelity, so an
export that quietly loses precision would be worse than no export at all. The
default path must round-trip every value exactly, and the opt-in lossy path must
*measure* the error it introduces rather than describe it as "float32
precision".

**One design decision worth pinning.** `shuffle` is chosen per variable, not
globally, because it was measured to help integral data and HURT float data on
this project's own files -- 8.6 % of baseline with it against 10.7 % without for
an integral variable, but 46.4 % with against 24.9 % without for a float one. A
later contributor turning it on everywhere would make float variables roughly
twice as large while believing they had optimised.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements.arco_export import export, plan_variable


def _write_source(path: Path, n: int = 5000) -> None:
    """A file shaped like a port output: everything float64, some integral."""
    rng = np.random.default_rng(20260901)
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("time", n)
        d.createVariable("counts", "f8", ("time",))[:] = rng.integers(0, 900, n)
        d.createVariable("small", "f8", ("time",))[:] = rng.integers(0, 200, n)
        d.createVariable("diam", "f8", ("time",))[:] = rng.random(n) * 9.4
        holed = rng.random(n) * 5
        holed[::97] = np.nan
        d.createVariable("integral_with_nan", "f8", ("time",))[:] = np.where(
            np.isnan(holed), np.nan, np.round(holed))


class PlanningIsDrivenByTheData(unittest.TestCase):
    def test_an_integral_variable_narrows_to_an_exact_integer_type(self):
        p = plan_variable("v", np.arange(0, 900, dtype=float))
        # Assert the WIDTH, not the exact code: i2 and u2 both hold [0, 899] in
        # two bytes and either is correct. An earlier version of this test
        # demanded u2 and failed on a correct i2.
        self.assertEqual(np.dtype(p.dtype).itemsize, 2)
        self.assertTrue(p.lossless)

    def test_a_small_integral_variable_narrows_further(self):
        p = plan_variable("v", np.arange(0, 200, dtype=float))
        self.assertIn(p.dtype, ("u1", "i2", "u2"))
        self.assertTrue(p.lossless)

    def test_an_integral_variable_carrying_nan_is_not_narrowed(self):
        """An integer type cannot hold NaN, and inventing a fill value would
        change what a reader sees -- so the float is kept and zlib does the work."""
        v = np.arange(0, 500, dtype=float)
        v[7] = np.nan
        p = plan_variable("v", v)
        self.assertEqual(p.dtype, "f8")
        self.assertTrue(p.lossless)

    def test_shuffle_is_on_for_integral_and_off_for_float(self):
        """Measured, not conventional: shuffle helps integral data and hurts
        float data on this project's files."""
        self.assertTrue(plan_variable("v", np.arange(0, 900, dtype=float)).shuffle)
        self.assertFalse(plan_variable("v", np.random.random(1000) * 9).shuffle)

    def test_floats_are_kept_at_full_width_by_default(self):
        p = plan_variable("v", np.random.random(1000) * 9)
        self.assertEqual(p.dtype, "f8")
        self.assertTrue(p.lossless)

    def test_lossy_mode_measures_the_error_it_introduces(self):
        v = np.random.default_rng(0).random(1000) * 9
        p = plan_variable("v", v, lossy_floats=True)
        self.assertEqual(p.dtype, "f4")
        self.assertFalse(p.lossless)
        self.assertGreater(p.max_rel_error, 0.0,
                           "a lossy plan must report a measured error, not zero")
        self.assertLess(p.max_rel_error, 1e-6)


class TheExportRoundTrips(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "src.nc"
        self.dst = self.tmp / "dst.nc"
        _write_source(self.src)

    def test_every_value_survives_exactly(self):
        export(self.src, self.dst)
        with netCDF4.Dataset(str(self.src)) as a, netCDF4.Dataset(str(self.dst)) as b:
            for name in a.variables:
                x = np.asarray(a.variables[name][:], dtype=float)
                y = np.asarray(b.variables[name][:], dtype=float)
                self.assertTrue(
                    np.array_equal(x, y, equal_nan=True),
                    f"{name} did not round-trip exactly")

    def test_the_source_is_not_modified(self):
        before = self.src.read_bytes()
        export(self.src, self.dst)
        self.assertEqual(before, self.src.read_bytes(),
                         "the export must never touch the faithful output")

    def test_the_output_records_what_it_did_per_variable(self):
        export(self.src, self.dst)
        with netCDF4.Dataset(str(self.dst)) as b:
            self.assertEqual(b.getncattr("arrayprobe_all_lossless"), "true")
            for name, v in b.variables.items():
                self.assertIn("arrayprobe_source_dtype", v.ncattrs(),
                              f"{name} does not record its source type")
                self.assertIn("arrayprobe_lossless", v.ncattrs())

    def test_it_is_actually_smaller(self):
        export(self.src, self.dst)
        self.assertLess(self.dst.stat().st_size, self.src.stat().st_size,
                        "an export that does not shrink the file has no purpose")

    def test_lossy_mode_is_declared_in_the_file(self):
        export(self.src, self.dst, lossy_floats=True)
        with netCDF4.Dataset(str(self.dst)) as b:
            self.assertEqual(b.getncattr("arrayprobe_all_lossless"), "false")


if __name__ == "__main__":
    unittest.main()


class ASourceFillValueIsCarried(unittest.TestCase):
    """2026-10-05: an sd carrying a NaN-filled float32 variable (the Field-2006 diagnostics)
    made export raise, because netCDF4 accepts ``_FillValue`` only when a variable is created
    and the attribute loop tried to set it afterwards."""

    def test_a_nan_fill_survives_and_the_values_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "sd.nc", Path(d) / "sd.arco.nc"
            with netCDF4.Dataset(src, "w", format="NETCDF3_CLASSIC") as nc:
                nc.createDimension("Time", 4)
                v = nc.createVariable("diag", "f4", ("Time",), fill_value=np.float32(np.nan))
                v[:] = np.array([1.0, np.nan, 3.0, 4.0], dtype=np.float32)
            export(src, dst)
            with netCDF4.Dataset(dst) as nc:
                out = nc.variables["diag"]
                self.assertIn("_FillValue", out.ncattrs())
                self.assertTrue(np.isnan(out.getncattr("_FillValue")))
                out.set_auto_mask(False)
                got = np.asarray(out[:], dtype=np.float32)
            np.testing.assert_array_equal(got, np.array([1.0, np.nan, 3.0, 4.0], np.float32))
