# SPDX-License-Identifier: BSD-3-Clause
"""The reproduction report: identical pair reads exact; one planted cell is named."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.reproduce_report import build_report, render_markdown, write_report


def _write(path, counts):
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", counts.shape[0])
        ds.createDimension("bins", counts.shape[1])
        v = ds.createVariable("Counts", "f8", ("time", "bins"))
        v[:] = counts
        t = ds.createVariable("time", "i4", ("time",))
        t[:] = np.arange(counts.shape[0])


class TestReproduceReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.base = np.arange(12, dtype=float).reshape(3, 4)
        self.base[0, 0] = np.nan
        _write(self.d / "a.nc", self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_pair_is_exact_with_no_differing_cells(self):
        _write(self.d / "b.nc", self.base)
        rep = build_report(self.d / "a.nc", self.d / "b.nc")
        self.assertTrue(rep["identical"])
        self.assertEqual(rep["differing_cells"], [])
        self.assertEqual(rep["cells"], 15)
        self.assertEqual(rep["exact"], 15)
        self.assertIn("**EXACT**", render_markdown(rep))

    def test_one_planted_cell_is_named_exactly(self):
        planted = self.base.copy()
        planted[2, 1] = 99.0
        _write(self.d / "b.nc", planted)
        rep = build_report(self.d / "a.nc", self.d / "b.nc")
        self.assertFalse(rep["identical"])
        self.assertEqual(rep["differing_cells"],
                         [{"variable": "Counts", "index": [2, 1],
                           "product": 9.0, "archived": 99.0}])
        row = next(v for v in rep["variables"] if v["name"] == "Counts")
        self.assertEqual(row["max_abs"], 90.0)
        self.assertAlmostEqual(row["max_rel"], 90.0 / 99.0)
        self.assertIn("| Counts | (2, 1) | 9.0 | 99.0 |", render_markdown(rep))

    def test_reads_only_and_reports_call_engine(self):
        _write(self.d / "b.nc", self.base)
        (self.d / "a.nc.call").write_text("engine=3.5 preset=X", encoding="utf-8")
        before = [hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (self.d / "a.nc", self.d / "b.nc")]
        rep = write_report(self.d / "a.nc", self.d / "b.nc",
                           out_md=self.d / "r.md", out_json=self.d / "r.json")
        after = [hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (self.d / "a.nc", self.d / "b.nc")]
        self.assertEqual(before, after)
        self.assertEqual(rep["call"]["product"]["engine"], "3.5")
        self.assertIsNone(rep["call"]["archived"])
        self.assertTrue(json.loads((self.d / "r.json").read_text())["identical"])

    def test_cli_exit_code_and_report_file(self):
        from arrayprobe.cli import main
        planted = self.base.copy()
        planted[1, 3] = -1.0
        _write(self.d / "b.nc", planted)
        out = self.d / "r.md"
        rc = main(["reproduce-report", str(self.d / "a.nc"), str(self.d / "b.nc"),
                   "--out", str(out)])
        self.assertEqual(rc, 1)
        self.assertIn("| Counts | (1, 3) | 7.0 | -1.0 |", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
