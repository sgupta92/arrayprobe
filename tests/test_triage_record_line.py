# SPDX-License-Identifier: BSD-3-Clause
"""The particle page's record line (viewer-survey item 1, after xpms2d): record number, record
time, TAS, overload / dead time and inter-arrival, read as stored and shown as "—" when a file
does not carry them."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests.test_triage_server import HAVE_MPL, _make_proc_file, netCDF4

if HAVE_MPL and netCDF4 is not None:
    from arrayprobe import triage_server as ts

NEEDS = unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")


def _make_full_proc(path: Path) -> None:
    """Two particles in record 7 at 06:40:17, with every field the record line reads."""
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", None)
        values = {"parent_rec_num": [7, 7], "particle_num": [1, 2], "Time": [64017, 64017],
                  "msec": [250, 251], "DMT_DOF_SPEC_OVERLOAD": [0.0, 1.0],
                  "inter_arrival": [1.25e-5, 3.5e-4]}
        for name, vals in values.items():
            v = ds.createVariable(name, "f8", ("time",))
            v[:] = np.asarray(vals, dtype=float)
        ds.variables["DMT_DOF_SPEC_OVERLOAD"].Units = "ms (Fast2DC/2DC/2DP only)"


class RecordLine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        ts._TAS_ROWS.clear()
        self._tmp.cleanup()

    @NEEDS
    def test_the_sidecar_is_found_beside_the_proc_file(self):
        self.assertEqual(ts._tas_csv_of(self.dir / "proc.base1.H.nc"),
                         self.dir / "base1.tas.csv")
        self.assertIsNone(ts._tas_csv_of(self.dir / "other.nc"))

    @NEEDS
    def test_values_render_as_stored(self):
        proc = self.dir / "proc.fR.H.nc"
        _make_full_proc(proc)
        (self.dir / "fR.tas.csv").write_text(
            "64016, 150.25, 1, 0, 0, 0, 0, 0, 0\n"
            "64017, 152.375, 2, 0, 0, 0, 0, 0, 0\n"
            "64017, 160, 3, 0, 0, 0, 0, 0, 0\n", encoding="utf-8")
        paths = {"proc": proc, "image": None, "probe": "2DS"}
        extras, _ = ts._particle_extras(paths, 1, None)
        line = ts.record_line_html(extras["record"])
        self.assertIn("#7, particle 2", line)
        self.assertIn("06:40:17.251 UTC", line)
        self.assertIn("152.4 m/s", line)          # the first row at the record's second
        self.assertIn("first of 2 .tas.csv row(s)", line)
        self.assertIn("ms (Fast2DC/2DC/2DP only)", line)
        self.assertIn("0.000350 s", line)
        self.assertNotIn(ts.NO_VALUE, line)
        meta = ts.particle_meta_html({"reject_code": 48}, extras)
        self.assertLess(meta.find("id='pmeta'"), meta.find("id='prec'"))

    @NEEDS
    def test_a_file_without_the_fields_shows_a_dash(self):
        proc = self.dir / "proc.fD.H.nc"
        _make_proc_file(proc, [{"parent_rec_num": 3, "start": 1, "end": 3, "width": 4,
                                "length": 3, "particle_num": 1}])
        paths = {"proc": proc, "image": None, "probe": "2DS"}
        extras, _ = ts._particle_extras(paths, 0, None)
        line = ts.record_line_html(extras["record"])
        self.assertIn("#3, particle 1", line)       # what the file does carry still shows
        for key in ("time", "tas", "over", "ia"):
            self.assertRegex(line, rf"class='pr pr-{key}'[^>]*><span class='pm-k'>[^<]+</span>"
                                   rf" {ts.NO_VALUE}</span>")
        self.assertIn("no .tas.csv beside the proc file", line)

    @NEEDS
    def test_a_sidecar_without_the_second_says_so(self):
        proc = self.dir / "proc.fS.H.nc"
        _make_full_proc(proc)
        (self.dir / "fS.tas.csv").write_text("70000, 150, 1, 0, 0, 0, 0, 0, 0\n",
                                             encoding="utf-8")
        extras, _ = ts._particle_extras({"proc": proc, "image": None, "probe": "2DS"}, 0, None)
        line = ts.record_line_html(extras["record"])
        self.assertIn(f"<span class='pm-k'>TAS</span> {ts.NO_VALUE}", line)
        self.assertIn("no fS.tas.csv row at this second", line)

    @NEEDS
    def test_no_record_at_all_is_all_dashes(self):
        line = ts.record_line_html(None)
        self.assertEqual(line.count(f" {ts.NO_VALUE}</span>"), 5)


if __name__ == "__main__":
    unittest.main()
