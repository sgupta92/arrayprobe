# SPDX-License-Identifier: BSD-3-Clause
"""ARM file-standard gaps closed in arm_export: S5.1 naming and the S5.1.1
length checks, S6.6.2 missing_value (opt-in), and the six S6.7.1 recommended
attributes (written only when supplied)."""
from __future__ import annotations

import datetime as _dt
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements.arm_export import (
    RECOMMENDED_ATTRIBUTES,
    ArmFilenameError,
    build_filename,
    check_filename,
    export,
)


def _write_source(path: Path) -> None:
    """A minimal sizeDist-shaped file, built here so this module has no import
    of a sibling test module and travels in the distribution."""
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("Time", 4)
        d.createVariable("time", "f8", ("Time",))[:] = [235959.0, 240000.0, 240001.0, 240002.0]
        n = d.createVariable("n", "f8", ("Time",))
        n[:] = [1.0, 2.0, 3.0, 4.0]
        n.units = "cm-3"
        n.long_name = "number concentration"


class FileNaming(unittest.TestCase):
    def test_builds_the_s5_1_grammar(self):
        name = build_filename("ena", "aaf2dsh", "F1", "c1", _dt.datetime(2017, 7, 6, 9, 5, 3))
        self.assertEqual(name, "enaaaf2dshF1.c1.20170706.090503.nc")

    def test_total_over_60_characters_raises(self):
        with self.assertRaises(ArmFilenameError):
            check_filename("a" * 57 + ".nc" + "x")

    def test_datastream_portion_over_33_characters_raises(self):
        with self.assertRaisesRegex(ArmFilenameError, "datastream"):
            build_filename("ena", "x" * 24, "F1", "c1" + "q" * 6, _dt.datetime(2017, 1, 1))

    def test_instrument_portion_over_24_characters_raises(self):
        with self.assertRaisesRegex(ArmFilenameError, "instrument"):
            build_filename("ena", "x" * 25, "F1", "c1", _dt.datetime(2017, 1, 1))

    def test_disallowed_character_raises(self):
        with self.assertRaises(ArmFilenameError):
            check_filename("ena_aaf2dsh.nc")


class ExportOptions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "sd.nc"
        _write_source(self.src)
        self.kw = dict(flight_date=_dt.date(2016, 9, 6), site_id="p3",
                       platform_id="foap2ds", facility_id="F1")

    def test_default_writes_no_missing_value_and_no_recommended_attrs(self):
        out = self.tmp / "a.nc"
        export(self.src, out, **self.kw)
        with netCDF4.Dataset(out) as d:
            self.assertNotIn("missing_value", d.variables["n"].ncattrs())
            for a in RECOMMENDED_ATTRIBUTES:
                self.assertNotIn(a, d.ncattrs())

    def test_missing_value_declared_on_request_with_matching_type(self):
        out = self.tmp / "b.nc"
        export(self.src, out, declare_missing_value=True, **self.kw)
        with netCDF4.Dataset(out) as d:
            var = d.variables["n"]
            mv = var.getncattr("missing_value")
            self.assertTrue(np.isnan(mv))
            self.assertEqual(np.asarray(mv).dtype, var.dtype)
            self.assertNotIn("missing_value", d.variables["time"].ncattrs())

    def test_recommended_attributes_written_when_supplied(self):
        out = self.tmp / "c.nc"
        export(self.src, out, recommended_attributes={"sampling_interval": "1 s"}, **self.kw)
        with netCDF4.Dataset(out) as d:
            self.assertEqual(d.sampling_interval, "1 s")

    def test_unknown_recommended_attribute_is_refused(self):
        with self.assertRaises(ValueError):
            export(self.src, self.tmp / "d.nc", recommended_attributes={"doi": "x"}, **self.kw)

    def test_check_name_refuses_a_nonstandard_outfile(self):
        with self.assertRaises(ArmFilenameError):
            export(self.src, self.tmp / "not_arm.nc", check_name=True, **self.kw)


if __name__ == "__main__":
    unittest.main()
