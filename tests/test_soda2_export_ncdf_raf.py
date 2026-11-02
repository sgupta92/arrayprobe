# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.export_ncdf_raf`` -- ``soda2_export_ncdf_raf.pro``
the first section (`:1-237`) on synthetic ``data`` built like the sibling's tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_soda2.export_ascii import compute_bulk_simple, unnormalize
from arrayprobe_soda2.export_ncdf import (
    DimensionNameInUse,
    MinsizeBinstartOutOfRange,
    _tags,
    compute_area,
)
from arrayprobe_soda2.export_ncdf_raf import (
    BulkAttnameCarryOver,
    soda2_export_ncdf_raf,
    sps1_size,
)

ENDBINS = np.array([10, 20, 30, 50, 100, 200, 400, 800, 1600], dtype=np.float32)


def _data(n: int = 3, rate: float = 1.0) -> dict:
    op = {"probetype": "2DS", "date": "20160906", "rate": np.float32(rate),
          "endbins": ENDBINS, "arendbins": np.linspace(0, 1, 11, dtype=np.float32),
          "comment": ""}
    return {
        "op": op,
        "date_processed": "2026/10/06",
        "time": np.arange(n, dtype=np.float64) + 36000.7,
        "tas": np.full(n, 100.0, dtype=np.float32),
        "midbins": (ENDBINS[:-1] + ENDBINS[1:]) / np.float32(2),
        "sa": np.full(8, 1e-4, dtype=np.float32),
        "activetime": np.full(n, 0.9, dtype=np.float32),
        "conc1d": np.arange(n * 8, dtype=np.float32).reshape(n, 8) + 1,
        "spec1d": np.full((n, 8), 10.0, dtype=np.float32),
        "spec2d": (np.arange(n * 8 * 10, dtype=np.float32).reshape(n, 8, 10) % 7),
        "intspec_all": np.ones((n, 4), dtype=np.float32),
        "intmidbins": np.array([1e-6, 1e-5, 1e-4, 1e-3], dtype=np.float32),
        "skipped_tag": np.zeros(n),
    }


class TestRafS1(unittest.TestCase):
    def _write(self, data: dict, **kw) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "x.nc")
            soda2_export_ncdf_raf(data, path, date_created="fixed", **kw)
            with netCDF4.Dataset(path) as ds:
                return {
                    "dims": {k: len(v) for k, v in ds.dimensions.items()},
                    "vars": {k: (v.dtype, v.dimensions, {a: v.getncattr(a) for a in v.ncattrs()},
                                 v[...].filled(np.nan) if np.ma.isMaskedArray(v[...])
                                 else np.asarray(v[...]))
                             for k, v in ds.variables.items()},
                    "globals": {a: ds.getncattr(a) for a in ds.ncattrs()},
                }

    def test_dimensions(self):
        out = self._write(_data())
        for k, n in {"Time": 3, "sps1": 1, "Vector8": 8, "Vector4": 4, "Vector10": 10}.items():
            self.assertEqual(out["dims"][k], n)
        self.assertEqual(sps1_size(np.float32(0.1)), 10)
        self.assertEqual(sps1_size(np.float32(0.3)), 3)
        self.assertEqual(sps1_size(np.float32(10.0)), 1)

    def test_conc1d_variable(self):
        d = _data()
        out = self._write(d)
        dt, dims, atts, val = out["vars"]["C2DS"]
        self.assertEqual(dt, np.float32)
        self.assertEqual(dims, ("Time", "sps1", "Vector8"))
        self.assertEqual(atts["_FillValue"], np.float32(-32767.0))
        self.assertEqual(np.asarray(atts["FirstBin"]).dtype, np.int32)
        self.assertEqual(int(atts["LastBin"]), 7)
        np.testing.assert_array_equal(atts["CellSizes"], ENDBINS)
        self.assertEqual(atts["CellSizeNote"], "CellSizes are lower bin limits as particle size")
        self.assertTrue(np.array_equal(val[:, 0, :], d["conc1d"]))
        self.assertEqual(out["vars"]["A2DS"][1], ("Time", "sps1", "Vector8"))
        self.assertEqual(out["vars"]["INTSPEC_ALL"][1], ("Time", "Vector4"))
        self.assertNotIn("SKIPPED_TAG", out["vars"])

    def test_normalize_0_is_unnormalize_over_1e3(self):
        d = _data()
        out = self._write(d, normalize=0)
        want = unnormalize(d["conc1d"], ENDBINS) / np.float32(1e3)
        self.assertTrue(np.array_equal(out["vars"]["C2DS"][3][:, 0, :], want.astype(np.float32)))
        self.assertEqual(out["vars"]["C2DS"][2]["units"], "#/L")

    def test_legacybinning_pads_bin_zero(self):
        d = _data()
        out = self._write(d, legacybinning=1, suffix="_LWI")
        self.assertEqual(out["dims"]["Vector9"], 9)
        _, dims, atts, val = out["vars"]["C2DS_LWI"]
        self.assertEqual(dims, ("Time", "sps1", "Vector9"))
        self.assertTrue(np.all(val[:, 0, 0] == 0))
        self.assertEqual(int(atts["FirstBin"]), 1)
        self.assertEqual(int(atts["LastBin"]), 8)
        self.assertIn("upper", atts["CellSizeNote"])
        self.assertEqual(out["vars"]["SA_LWI"][3][0], 0)

    def test_time_variables_truncate(self):
        d = _data()
        out = self._write(d)
        self.assertEqual(out["vars"]["Time"][0], np.int32)
        np.testing.assert_array_equal(out["vars"]["Time"][3], [0, 1, 2])
        np.testing.assert_array_equal(out["vars"]["utc_time"][3], [36000, 36001, 36002])
        days1970 = (np.datetime64("2016-09-06") - np.datetime64("1970-01-01")).astype(int)
        self.assertEqual(int(out["vars"]["base_time"][3]), 36000 + int(days1970) * 86400)
        self.assertEqual(out["globals"]["Conventions"], "NCAR-RAF/nimbus")
        self.assertEqual(out["globals"]["FlightDate"], "09/06/2016")

    def test_empty_op_string_written_back_as_none(self):
        d = _data()
        out = self._write(d)
        self.assertEqual(out["globals"]["COMMENT"], "none")
        self.assertEqual(d["op"]["comment"], "none")

    def test_vector_collision(self):
        d = _data()
        d["intmidbins"] = np.zeros(8, dtype=np.float32)
        with self.assertRaises(DimensionNameInUse):
            self._write(d)

    def test_bulk_variables_equal_their_helpers(self):
        d = _data()
        out = self._write(d)
        tags = _tags(_data())
        bulkall = compute_bulk_simple(d["conc1d"], ENDBINS, binstart=0)
        i100 = 4  # min(where(endbins ge 100)), `:241`
        bulk100 = compute_bulk_simple(d["conc1d"], ENDBINS, binstart=i100)
        want = {"LWC": bulkall["lwc"], "IWC": bulkall["iwc"], "MVD": bulkall["mvd"],
                "MND": bulkall["mnd"], "NT": bulkall["nt"], "NT100": bulk100["nt"],
                "MND100": bulk100["mnd"], "MVD100": bulk100["mvd"],
                "IWC100": bulk100["iwc"], "AREA": compute_area(tags)["area"],
                "AREA100": compute_area(tags, binstart=i100)["area"]}
        for name, w in want.items():
            dt, dims, atts, val = out["vars"][name]
            self.assertEqual(dt, np.float32, name)
            self.assertEqual(dims, ("Time",), name)
            self.assertEqual(sorted(atts), ["long_name", "units"], name)
            np.testing.assert_array_equal(val, np.asarray(w, dtype=np.float32), name)
        self.assertEqual(out["vars"]["NT100"][2]["units"], "#/m3")
        self.assertEqual(out["vars"]["AREA"][2]["long_name"],
                         "Projected Particle Area, All Particles")
        # compute_bulk_simple's other tags (DBZ, DMASS, MSD, ...) fall to ELSE (`:290`).
        for skipped in ("DBZ", "DMASS", "MSD", "MASSPARAM"):
            self.assertNotIn(skipped, out["vars"])

    def test_bulk_uses_normalized_conc1d_whatever_normalize(self):
        a = self._write(_data(), normalize=0)
        b = self._write(_data(), normalize=1)
        np.testing.assert_array_equal(a["vars"]["NT"][3], b["vars"]["NT"][3])

    def test_no_edge_reaches_100um_is_refused(self):
        d = _data()
        d["op"]["endbins"] = np.linspace(10, 90, 9, dtype=np.float32)
        with self.assertRaises(MinsizeBinstartOutOfRange):
            self._write(d)

    def test_last_tag_conc1d_or_spec1d_is_refused(self):
        for last in ("conc1d", "spec1d"):
            d = _data()
            d.pop("skipped_tag")
            d[last] = d.pop(last)  # move to the end
            with self.assertRaises(BulkAttnameCarryOver, msg=last):
                self._write(d)


if __name__ == "__main__":
    unittest.main()
