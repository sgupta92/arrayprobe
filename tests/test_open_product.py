# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.open_product`` reads a product exactly as netCDF4 does.

Each tracked fixture is opened twice, once by :func:`open_product` and once by ``netCDF4``
directly, and the two are compared variable by variable: dimensions, dtype, values and
attributes. In the raw mode netCDF4's automatic masking and scaling is switched off, which is
the ``netcdf.getVar`` view; in the ``cf`` mode it is left on, the ``ncread`` view.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

from arrayprobe.products import XARRAY_EXTRA, open_product

_DATA = Path(__file__).resolve().parent / "data"

#: One fixture per product kind: a decoded image file (classic format), a particle file and a
#: size-distribution file (netCDF4 format, ``Units`` and ``units`` spellings respectively).
FIXTURES = (
    "2DS_header_fixture.nc",
    "demo_flight_v35_proc.nc",
    "demo_flight_v35_sd.nc",
)

_HAVE_XARRAY = importlib.util.find_spec("xarray") is not None


def _attrs(obj) -> dict:
    return {k: obj.getncattr(k) for k in obj.ncattrs()}


def _same_attrs(test: unittest.TestCase, got: dict, want: dict, where: str) -> None:
    test.assertEqual(sorted(got), sorted(want), where)
    for key, value in want.items():
        g = got[key]
        if isinstance(value, np.ndarray) or isinstance(g, np.ndarray):
            np.testing.assert_array_equal(
                np.asarray(g), np.asarray(value), err_msg=f"{where} {key}")
        else:
            test.assertEqual(g, value, f"{where} {key}")


@unittest.skipUnless(_HAVE_XARRAY, "xarray is not installed (the optional zarr extra); "
                                   "open_product cannot be exercised")
class OpensLikeNetCDF4(unittest.TestCase):
    def _compare(self, name: str, decode: str) -> None:
        ds = open_product(_DATA / name, decode=decode)
        with netCDF4.Dataset(_DATA / name) as nc:
            nc.set_auto_maskandscale(decode == "cf")
            self.assertEqual(dict(ds.sizes), {d: len(v) for d, v in nc.dimensions.items()
                                              if any(d in var.dimensions
                                                     for var in nc.variables.values())})
            self.assertEqual(sorted(ds.variables), sorted(nc.variables))
            _same_attrs(self, dict(ds.attrs), _attrs(nc), f"{name} global")
            for vname, var in nc.variables.items():
                where = f"{name}:{vname}"
                got = ds[vname]
                self.assertEqual(got.dims, var.dimensions, where)
                want = np.ma.filled(var[...], np.nan) if decode == "cf" else var[...]
                if decode == "raw":
                    self.assertEqual(got.dtype, var.dtype, where)
                np.testing.assert_array_equal(got.values, np.asarray(want), err_msg=where)
                attrs = dict(got.attrs)
                want_attrs = _attrs(var)
                if decode == "cf":
                    for moved in ("_FillValue", "missing_value", "scale_factor", "add_offset"):
                        want_attrs.pop(moved, None)
                _same_attrs(self, attrs, want_attrs, where)

    def test_raw_mode_equals_getvar(self):
        for name in FIXTURES:
            with self.subTest(fixture=name):
                self._compare(name, "raw")

    def test_cf_mode_equals_ncread(self):
        for name in FIXTURES:
            with self.subTest(fixture=name):
                self._compare(name, "cf")

    def test_time_is_the_stored_clock_reading(self):
        ds = open_product(_DATA / "demo_flight_v35_sd.nc")
        self.assertEqual(ds["time"].attrs["units"], "HHMMSS")
        self.assertTrue(np.issubdtype(ds["time"].dtype, np.floating))

    def test_attribute_names_with_spaces_survive(self):
        ds = open_product(_DATA / "demo_flight_v35_sd.nc")
        self.assertIn("SA Method", ds.attrs)
        proc = open_product(_DATA / "demo_flight_v35_proc.nc")
        self.assertIn("Creation Time", proc.attrs)
        self.assertIn("Units", proc["Time"].attrs)
        self.assertNotIn("units", proc["Time"].attrs)

    def test_loaded_dataset_holds_no_file_open(self):
        ds = open_product(_DATA / "demo_flight_v35_sd.nc")
        ds.close()
        self.assertGreater(float(ds["bin_mid"].sum()), 0.0)

    def test_lazy_mode_returns_an_open_dataset(self):
        ds = open_product(_DATA / "demo_flight_v35_sd.nc", load=False)
        try:
            self.assertIn("conc_minR", ds)
        finally:
            ds.close()

    def test_unknown_decode_is_refused(self):
        with self.assertRaises(ValueError):
            open_product(_DATA / "demo_flight_v35_sd.nc", decode="ncread")


class WithoutXarray(unittest.TestCase):
    def test_import_error_names_the_extra(self):
        with mock.patch.dict("sys.modules", {"xarray": None}):
            with self.assertRaises(ImportError) as cm:
                open_product(_DATA / "demo_flight_v35_sd.nc")
        self.assertIn(f"arrayprobe[{XARRAY_EXTRA}]", str(cm.exception))
        self.assertIn("pip install xarray", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
