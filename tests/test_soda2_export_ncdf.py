# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for ``export_ncdf.py`` (``soda2_export_ncdf.pro``)
that need no GDL: the refusals by name, ``sfm2hms`` without the 86400 wrap,
and the ``INTENDDBINS`` typo. The GDL comparison is
``test_soda2_export_ncdf_gdl.py``."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_soda2.export_ncdf import (
    NoskipNonNumericNotPorted,
    PthfileNotPorted,
    compute_meanar,
    idl_sfm2hms,
    soda2_export_ncdf,
    tas_qc_attrs,
)

ENDBINS = np.array([50, 100, 150, 200, 300, 400, 600, 800, 1000], dtype=np.float32)


def _data(n: int = 3) -> dict:
    op = {"probetype": "2DS", "date": "20160906", "water": np.int16(0),
          "res": np.float32(10.0), "endbins": ENDBINS}
    return {
        "op": op,
        "time": np.arange(n, dtype=np.float64) + 0.5,
        "tas": np.full(n, 100.0, dtype=np.float32),
        "midbins": (ENDBINS[:-1] + ENDBINS[1:]) / np.float32(2),
        "activetime": np.full(n, 0.9, dtype=np.float32),
        "sa": np.full(8, 1e-4, dtype=np.float32),
        "conc1d": np.full((n, 8), 100.0, dtype=np.float32),
        "spec1d": np.full((n, 8), 10.0, dtype=np.float32),
    }


class TestSfm2hms(unittest.TestCase):
    def test_no_wrap_at_midnight(self):
        """``sfm2hms.pro`` has no ``mod 86400``: 86401 s is 240001."""
        self.assertEqual(idl_sfm2hms(86401.0), 240001)
        self.assertEqual(idl_sfm2hms(3600.6), 10000)  # long() truncates


class TestRefusals(unittest.TestCase):
    def test_pthfile_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(PthfileNotPorted):
            soda2_export_ncdf(_data(), str(Path(tmp) / "x.nc"), pthfile="pth.sav")

    def test_noskip_on_a_string_tag_of_time_length_is_refused(self):
        d = _data(1)
        d["date_processed"] = "2026/09/15"  # n_elements 1 == n_elements(time)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(NoskipNonNumericNotPorted):
            soda2_export_ncdf(d, str(Path(tmp) / "x.nc"), noskip=1, date_created="x")


class TestIntenddbinsTypo(unittest.TestCase):
    def test_intendbins_gets_a_dimension_but_no_variable(self):
        """`:160` tests 'INTENDDBINS', so INTENDBINS falls to ELSE."""
        import netCDF4

        d = _data()
        d["intendbins"] = np.array([1e-7, 1e-5, 1e-3, 1e-1, 10.0], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "x.nc")
            soda2_export_ncdf(d, out, date_created="x")
            with netCDF4.Dataset(out) as ds:
                self.assertIn("Vector5", ds.dimensions)
                self.assertNotIn("INTENDBINS", ds.variables)
                self.assertEqual(ds.file_format, "NETCDF3_CLASSIC")


class TestComputeMeanar(unittest.TestCase):
    def test_empty_bin_is_zero(self):
        s = np.zeros((1, 2, 3), dtype=np.float32)
        s[0, 0, :] = [1, 1, 2]
        out = compute_meanar(s, np.array([0.15, 0.45, 0.8], dtype=np.float32))
        self.assertAlmostEqual(float(out[0, 0]), (0.15 + 0.45 + 1.6) / 4, places=6)
        self.assertEqual(float(out[0, 1]), 0.0)


class TestTasQualityRecord(unittest.TestCase):
    """The export says where its airspeed came from and which seconds had none."""

    def _write(self, data: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            out = soda2_export_ncdf(data, str(Path(tmp) / "x.nc"), date_created="fixed")
            with netCDF4.Dataset(out) as ds:
                return {a: ds.getncattr(a) for a in ds.ncattrs() if a.startswith("arrayprobe_tas")}

    def test_every_second_measured(self):
        got = self._write(_data())
        self.assertEqual(got["arrayprobe_tas_source"], "probe")
        self.assertEqual(int(got["arrayprobe_tas_seconds_total"]), 3)
        self.assertEqual(int(got["arrayprobe_tas_nonpositive_count"]), 0)
        self.assertEqual(got["arrayprobe_tas_nonpositive_ranges"], "none")

    def test_seconds_without_airspeed_are_counted_and_ranged(self):
        data = _data(5)
        data["time"] = np.array([36000.5, 36001.5, 36002.5, 36003.5, 36004.5])
        data["tas"] = np.array([100.0, 0.0, 0.0, np.nan, 100.0], dtype=np.float32)
        got = self._write(data)
        self.assertEqual(int(got["arrayprobe_tas_nonpositive_count"]), 3)
        self.assertEqual(got["arrayprobe_tas_nonpositive_ranges"], "100001-100003")
        self.assertIn("3 of 5 seconds", got["arrayprobe_tas_uncertainty"])

    def test_source_names_the_branch_the_driver_takes(self):
        tags = {"TIME": np.array([0.5]), "TAS": np.array([1.0])}
        self.assertEqual(tas_qc_attrs(tags, {"pth": "a.csv"})["arrayprobe_tas_source"],
                         "pth file (csv)")
        self.assertIn("fixedtas 120 m/s", tas_qc_attrs(tags, {"fixedtas": 120.0})
                      ["arrayprobe_tas_source"])
        self.assertIn("is not read", tas_qc_attrs(tags, {"pth": "a.xyz"})
                      ["arrayprobe_tas_source"])

    def test_an_upper_case_pth_suffix_is_not_read(self):
        """``process_2d`` matches the suffix case-sensitively (``.CSV`` leaves ``got_pth = 0``),
        so the record must not claim the file was read."""
        tags = {"TIME": np.array([0.5]), "TAS": np.array([1.0])}
        self.assertIn("is not read", tas_qc_attrs(tags, {"pth": "a.CSV"})
                      ["arrayprobe_tas_source"])

    def test_no_variable_changes(self):
        """The record is attributes only: the variable set and values are what they were."""
        data = _data()
        with tempfile.TemporaryDirectory() as tmp:
            out = soda2_export_ncdf(data, str(Path(tmp) / "x.nc"), date_created="fixed")
            with netCDF4.Dataset(out) as ds:
                names = list(ds.variables)
        self.assertFalse([n for n in names if "tas_qc" in n.lower()])


if __name__ == "__main__":
    unittest.main()
