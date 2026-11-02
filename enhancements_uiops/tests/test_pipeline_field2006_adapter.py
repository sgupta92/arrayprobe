# SPDX-License-Identifier: BSD-3-Clause
"""The Process2D-derived Field et al. (2006) driver adapter, on synthetic proc/sd files.

Opt-in only, writes ``<stem>.enh.sd.nc``, never opens the engine's own files for writing, and
stamps the copy as Process2D-derived.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements import field2006_shatter as f06
from arrayprobe_enhancements import pipeline, registry

STEM = "base000101000000"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_proc(path: Path, inttime: np.ndarray, tsec: np.ndarray) -> None:
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("pos_count", inttime.size)
        ds.createVariable("inter_arrival", "f8", ("pos_count",))[:] = inttime
        ds.createVariable("Time_in_seconds", "f8", ("pos_count",))[:] = tsec


def _write_sd(path: Path, hhmmss: np.ndarray, nbins: int = 3) -> None:
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("Time", hhmmss.size)
        ds.createDimension("Vector", nbins)
        ds.createVariable("time", "f8", ("Time",))[:] = hhmmss
        ds.createVariable("conc_minR", "f4", ("Time", "Vector"))[:] = np.ones((hhmmss.size, nbins))
        ds.createVariable("count", "f4", ("Time", "Vector"))[:] = np.ones((hhmmss.size, nbins))


def _stream(seed: int = 0, seconds: int = 8, per_second: int = 300):
    rng = np.random.default_rng(seed)
    parts_t, parts_s = [], []
    for k in range(seconds):
        n = per_second
        # a double-Poisson mixture: shattered fragments (short gaps) plus real particles
        gaps = np.where(rng.random(n) < 0.3, rng.exponential(2e-6, n), rng.exponential(3e-3, n))
        parts_t.append(gaps)
        parts_s.append(36000.0 + k + np.linspace(0.0, 0.99, n))
    return np.concatenate(parts_t), np.concatenate(parts_s)


class Field2006Adapter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.inttime, self.tsec = _stream()
        self.proc = self.dir / f"{STEM}.proc.nc"
        self.sd = self.dir / f"{STEM}.sd.nc"
        _write_proc(self.proc, self.inttime, self.tsec)
        self.hhmmss = np.array([100000.0 + k for k in range(8)])
        _write_sd(self.sd, self.hhmmss)
        self.outputs = pipeline._RunOutputs(
            out_dir=self.dir, raw_stem=STEM, engine="3.5", image=None,
            proc=self.proc, sd=self.sd, combined=None)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_off_and_selected_only_when_named(self):
        self.assertFalse(registry.resolve({})["field2006_shatter"])
        self.assertTrue(registry.resolve({"field2006_shatter": True})["field2006_shatter"])

    def test_has_an_adapter_and_no_no_adapter_reason(self):
        self.assertIn("field2006_shatter", pipeline._APPLIERS)
        self.assertNotIn("field2006_shatter", pipeline._NO_ADAPTER_REASON_BY_NAME)

    def test_writes_enh_sd_and_leaves_engine_outputs_untouched(self):
        before = (_digest(self.proc), _digest(self.sd))
        out = pipeline._apply_field2006_shatter(self.outputs)
        self.assertEqual(out, self.dir / f"{STEM}.enh.sd.nc")
        self.assertEqual((_digest(self.proc), _digest(self.sd)), before)

    def test_diagnostics_stamp_and_corrected_concentrations(self):
        out = pipeline._apply_field2006_shatter(self.outputs)
        result = f06.apply(self.inttime, np.floor(self.tsec))
        diag = f06.align_to_axis(result, pipeline._hhmmss_to_seconds(self.hhmmss))
        factor = f06.applied_corrfac(diag["field2006_corrfac"])
        with netCDF4.Dataset(out) as ds:
            self.assertIn("process2d-derived", ds.getncattr("field2006_stamp"))
            self.assertIn("field2006_shatter", ds.getncattr("enhancements_applied"))
            for name in f06.DIAGNOSTIC_VARIABLES:
                self.assertIn(name, ds.variables)
            conc = np.asarray(ds.variables["conc_minR"][:], dtype=np.float64)
            count = np.asarray(ds.variables["count"][:], dtype=np.float64)
        np.testing.assert_allclose(conc, np.ones((8, 3)) * factor[:, None], rtol=1e-6)
        np.testing.assert_array_equal(count, np.ones((8, 3)))
        self.assertTrue(np.all(factor >= 1.0))

    def test_named_skip_without_inter_arrival(self):
        with netCDF4.Dataset(self.proc, "w", format="NETCDF3_CLASSIC") as ds:
            ds.createDimension("pos_count", 2)
            ds.createVariable("Time_in_seconds", "f8", ("pos_count",))[:] = [1.0, 2.0]
        with self.assertRaises(pipeline.ApplierSkip):
            pipeline._apply_field2006_shatter(self.outputs)
        self.assertFalse((self.dir / f"{STEM}.enh.sd.nc").exists())

    def test_named_skip_on_out_of_order_times(self):
        _write_proc(self.proc, self.inttime[:4], np.array([5.0, 4.0, 6.0, 7.0]))
        with self.assertRaises(pipeline.ApplierSkip):
            pipeline._apply_field2006_shatter(self.outputs)


if __name__ == "__main__":
    unittest.main()
