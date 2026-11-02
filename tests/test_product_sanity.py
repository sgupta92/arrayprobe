# SPDX-License-Identifier: BSD-3-Clause
"""The product-sanity check flags empty sds and procs whose particle clock misses the axis.

The failure this guards: a CIP v3.5 sd that was NaN/zero in every second
because its proc's ``particle_time`` was never shifted to UTC (24,570 s off).
"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_uiops import product_sanity  # noqa: E402

OFFSET_S = 24570


def _sod_to_hhmmss(sod):
    sod = np.asarray(sod, dtype=float)
    h = np.floor(sod / 3600)
    m = np.floor((sod % 3600) / 60)
    s = sod % 60
    return h * 10000 + m * 100 + s


def _write_sd(path, n, conc):
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("Time", n.size)
        ds.createDimension("CIPcorrlen", conc.shape[1])
        ds.createVariable("time", "f8", ("Time",))[:] = _sod_to_hhmmss(
            30000 + np.arange(n.size))
        ds.createVariable("n", "f8", ("Time",))[:] = n
        ds.createVariable("conc_minR", "f8", ("Time", "CIPcorrlen"))[:] = conc


def _write_proc(path, offset):
    rec = 30000 + np.repeat(np.arange(50), 4)
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", rec.size)
        ds.createVariable("Time", "f8", ("time",))[:] = _sod_to_hhmmss(rec)
        ds.createVariable("particle_time", "f8", ("time",))[:] = _sod_to_hhmmss(
            rec + offset)


class ProductSanityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *paths):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = product_sanity.main([str(p) for p in paths])
        return code, buf.getvalue()

    def test_normal_sd_and_proc_are_ok(self):
        sd = self.dir / "sd.ok.nc"
        n = np.array([0, 3, 5, 0, 2, 7, 1, 0, 4, 2], dtype=float)
        conc = np.outer(n, [1.0, 0.5, 0.0])
        _write_sd(sd, n, conc)
        proc = self.dir / "proc.ok.nc"
        _write_proc(proc, 0)
        (Path(str(sd) + ".call")).write_text("engine=3.5 profile=x\n", encoding="utf-8")
        code, out = self._run(sd, proc)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("OK "), 2, out)
        self.assertIn("call=engine=3.5", out)
        self.assertIn("frac_bins_always_empty=0.3333", out)

    def test_all_zero_sd_is_an_anomaly(self):
        sd = self.dir / "sd.zero.nc"
        conc = np.full((10, 3), np.nan)
        conc[4] = 0.0
        _write_sd(sd, np.zeros(10), conc)
        code, out = self._run(sd)
        self.assertEqual(code, 1, out)
        self.assertIn("ANOMALY", out)
        self.assertIn("all zero/NaN", out)
        self.assertIn("call=absent", out)

    def test_proc_whose_particle_time_misses_the_axis_is_an_anomaly(self):
        proc = self.dir / "proc.unshifted.nc"
        _write_proc(proc, -OFFSET_S)
        rep = product_sanity.check_file(str(proc))
        self.assertEqual(rep.verdict, "ANOMALY")
        self.assertEqual(rep.facts["frac_particle_time_on_axis"], 0.0)
        self.assertEqual(rep.facts["median_offset_s"], -OFFSET_S)
        code, _ = self._run(proc)
        self.assertEqual(code, 1)

    def test_unrecognised_file_is_skipped_not_failed(self):
        other = self.dir / "other.nc"
        with netCDF4.Dataset(other, "w") as ds:
            ds.createDimension("x", 2)
            ds.createVariable("foo", "f8", ("x",))[:] = [1, 2]
        code, out = self._run(other)
        self.assertEqual(code, 0)
        self.assertIn("SKIP", out)


if __name__ == "__main__":
    unittest.main()
