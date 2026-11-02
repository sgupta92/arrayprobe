# SPDX-License-Identifier: BSD-3-Clause
"""The proc-rewriting appliers never write a (time, 2) variable in one call.

A whole-variable write of an unlimited-``time`` (time, 2) ``position`` at netCDF-C's default
(1, 2) chunking costs ~7 KB of memory per chunk -- ~50 GB on a 7.33 M-particle proc.
The appliers now
byte-copy and edit in place, or rebuild in bounded blocks. These tests pin (a) that the
values, dtypes, dimensions and attributes are what the old variable-by-variable rebuild wrote,
and (b) that a 200 k-row rebuild stays under 300 MB of resident memory.
"""
from __future__ import annotations

import filecmp
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements import int_arr_rollback_fix as rb
from arrayprobe_enhancements import particle_number_all_fix as pna
from arrayprobe_enhancements import particle_time_glitch_fix as g


def _make_proc(path, n, *, fmt="NETCDF4", block=16_384, fill_pna=True):
    """A small synthetic proc: unlimited ``time``, a (time, 2) int16 ``position``."""
    rng = np.random.default_rng(7)
    t = 36000.0 + np.arange(n) * 0.01
    if n > 10:
        t[n // 2:] -= 86400.0 * (n > 1000)  # one midnight rollback when large enough
    with netCDF4.Dataset(path, "w", format=fmt) as ds:
        ds.title = "synthetic"
        ds.createDimension("time", None)
        ds.createDimension("pos_count", 2)
        ds.createDimension("bins", 4)
        cols = {
            "position": ("i2", ("time", "pos_count"),
                         rng.integers(0, 3000, (n, 2)).astype("i2")),
            "Time_in_seconds": ("f8", ("time",), t),
            "particle_time": ("i4", ("time",), (100000 + np.arange(n) // 100).astype("i4")),
            "diam": ("f4", ("time",), rng.random(n).astype("f4")),
            "Particle_number_all": ("i4", ("time",),
                                    np.full(n, -999, "i4") if fill_pna
                                    else np.arange(n, dtype="i4")),
        }
        for name, (dt, dims, data) in cols.items():
            v = ds.createVariable(name, dt, dims,
                                  fill_value=-999 if name == "Particle_number_all" else None)
            v.units = "x"
            v.set_auto_mask(False)
            for i0 in range(0, n, block):
                v[i0:min(i0 + block, n)] = data[i0:min(i0 + block, n)]
        b = ds.createVariable("bin_stats", "f8", ("bins",))
        b[:] = np.arange(4.0)


def _old_rebuild(src, dst, *, override=None, drop=None):
    """The variable-by-variable rebuild the appliers used before (whole-variable writes)."""
    override = override or {}
    with netCDF4.Dataset(src) as ds_in, \
            netCDF4.Dataset(dst, "w", format=ds_in.file_format) as ds_out:
        ds_out.setncatts({k: ds_in.getncattr(k) for k in ds_in.ncattrs()})
        for name, dim in ds_in.dimensions.items():
            ds_out.createDimension(name, None if dim.isunlimited() else len(dim))
        for name, var in ds_in.variables.items():
            if name == drop:
                continue
            var.set_auto_mask(False)
            out = ds_out.createVariable(
                name, var.dtype, var.dimensions,
                fill_value=(var.getncattr("_FillValue")
                            if "_FillValue" in var.ncattrs() else None))
            out.setncatts({k: var.getncattr(k) for k in var.ncattrs() if k != "_FillValue"})
            out.set_auto_mask(False)
            if name in override:
                out[:] = override[name].astype(var.dtype).reshape(var.shape)
            elif var.size:
                out[:] = np.asarray(var[:])


def _assert_same(tc, a, b):
    with netCDF4.Dataset(a) as da, netCDF4.Dataset(b) as db:
        da.set_auto_mask(False)
        db.set_auto_mask(False)
        tc.assertEqual(da.file_format, db.file_format)
        tc.assertEqual({k: da.getncattr(k) for k in da.ncattrs()},
                       {k: db.getncattr(k) for k in db.ncattrs()})
        tc.assertEqual({k: (len(d), d.isunlimited()) for k, d in da.dimensions.items()},
                       {k: (len(d), d.isunlimited()) for k, d in db.dimensions.items()})
        tc.assertEqual(list(da.variables), list(db.variables))
        for name in da.variables:
            va, vb = da[name], db[name]
            tc.assertEqual(va.dtype, vb.dtype, name)
            tc.assertEqual(va.dimensions, vb.dimensions, name)
            tc.assertEqual({k: va.getncattr(k) for k in va.ncattrs()},
                           {k: vb.getncattr(k) for k in vb.ncattrs()}, name)
            tc.assertTrue(np.array_equal(va[:], vb[:]), name)


class ValuesMatchTheOldRebuild(unittest.TestCase):
    N = 3000

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_int_arr_rollback_fix(self):
        for fmt in ("NETCDF4", "NETCDF3_CLASSIC"):
            src = self.dir / f"src_{fmt}.nc"
            _make_proc(src, self.N, fmt=fmt)
            new, old = self.dir / f"new_{fmt}.nc", self.dir / f"old_{fmt}.nc"
            rep = rb.proc_file_with_rollback_corrected(src, new, step=rb.SECONDS_PER_DAY)
            self.assertGreater(rep["changed"], 0)
            with netCDF4.Dataset(src) as ds:
                ds.set_auto_mask(False)
                raw = np.asarray(ds["Time_in_seconds"][:], dtype=np.float64)
            fixed = rb.corrected_time_in_seconds(raw, step=rb.SECONDS_PER_DAY)
            _old_rebuild(src, old, override={"Time_in_seconds": fixed})
            _assert_same(self, new, old)

    def test_particle_number_all_fix_drop_and_keep(self):
        for fmt in ("NETCDF4", "NETCDF3_CLASSIC"):
            src = self.dir / f"src_{fmt}.nc"
            _make_proc(src, self.N, fmt=fmt)
            new, old = self.dir / f"new_{fmt}.nc", self.dir / f"old_{fmt}.nc"
            self.assertTrue(pna.corrected_proc_file(src, new)["removed"])
            _old_rebuild(src, old, drop=pna.VARIABLE)
            _assert_same(self, new, old)
            # Nothing to drop (variable absent): the byte-copy path, identical to its source.
            nopna = self.dir / f"nopna_{fmt}.nc"
            _old_rebuild(src, nopna, drop=pna.VARIABLE)
            new2 = self.dir / f"new2_{fmt}.nc"
            self.assertFalse(pna.corrected_proc_file(nopna, new2)["removed"])
            self.assertTrue(filecmp.cmp(nopna, new2, shallow=False))

    def test_glitch_fix_block_size_does_not_change_the_file(self):
        src = self.dir / "src.nc"
        _make_proc(src, 40_000, fmt="NETCDF4")
        small, large = self.dir / "small.nc", self.dir / "large.nc"
        g.corrected_proc_file(src, small, 1)
        saved = g._BLOCK
        g._BLOCK = 200_000  # the block size before the bounded-memory change
        try:
            g.corrected_proc_file(src, large, 1)
        finally:
            g._BLOCK = saved
        _assert_same(self, small, large)


_CHILD = textwrap.dedent("""
    import os, sys, threading, time
    import psutil
    sys.path[:0] = [p for p in sys.argv[3].split(os.pathsep) if p]
    import importlib
    tests = importlib.import_module("test_proc_rewrite_bounded_memory")
    from arrayprobe_enhancements import particle_number_all_fix as pna
    src, dst = sys.argv[1], sys.argv[2]
    tests._make_proc(src, 200_000)
    p = psutil.Process(); base = p.memory_info().rss; peak = [base]; stop = [False]
    def mon():
        while not stop[0]:
            peak[0] = max(peak[0], p.memory_info().rss); time.sleep(0.01)
    th = threading.Thread(target=mon); th.start()
    pna.corrected_proc_file(src, dst)
    stop[0] = True; th.join()
    print((peak[0] - base) // 2**20)
""")


class RebuildMemoryIsBounded(unittest.TestCase):
    def test_200k_row_rebuild_under_300_mb(self):
        try:
            import psutil  # noqa: F401
        except ImportError:
            self.skipTest("psutil not installed: resident memory is not measurable here")
        with tempfile.TemporaryDirectory() as d:
            here = str(Path(__file__).resolve().parent)
            path = os.pathsep.join([here] + sys.path)
            r = subprocess.run(
                [sys.executable, "-W", "ignore", "-c", _CHILD,
                 str(Path(d) / "src.nc"), str(Path(d) / "dst.nc"), path],
                capture_output=True, text=True, timeout=240)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            mb = int(r.stdout.strip().splitlines()[-1])
            self.assertLess(mb, 300, f"peak RSS above baseline {mb} MB")


if __name__ == "__main__":
    unittest.main()
