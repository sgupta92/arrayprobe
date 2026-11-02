# SPDX-License-Identifier: BSD-3-Clause
"""Every user-facing CLI refusal prints a plain message and exits 2, never a traceback (C11).

Measured on 2026-10-18 before the fix: ``make-tas-file`` raised ``ValueError`` tracebacks (exit
1) for a constant series running past :59, a negative ``--start-hhmmss`` and a
``--from-tas-csv`` file that does not parse; ``compare`` and ``intarr-threshold`` raised
``OSError`` on a file that is not netCDF, and ``intarr-threshold`` a ``KeyError`` on a netCDF
file with no ``Time``. ``docs/06-configuration.md``'s own ``--constant-tas`` example was one of
them. The library function ``constant_tas`` still raises (``test_make_tas_file.py``); only the
command line converts.
"""
from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from arrayprobe import cli

ROOT = Path(__file__).resolve().parents[1]


class _Refusals(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.junk = self.root / "junk.nc"
        self.junk.write_text("not a netcdf file\n", encoding="ascii")
        self.csv = self.root / "junk.tas.csv"
        self.csv.write_text("hello,world\n", encoding="ascii")

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli.main(list(argv))
            except SystemExit as exc:
                rc = exc.code
        return rc, err.getvalue()

    def assertRefused(self, *argv, written=None):
        rc, err = self._run(*argv)
        self.assertEqual(rc, 2, f"{argv}: exit {rc}\n{err}")
        self.assertNotIn("Traceback", err)
        self.assertTrue(err.strip(), f"{argv}: refused with no message")
        if written is not None:
            self.assertFalse(Path(written).exists(), f"{argv} wrote {written}")
        return err


class MakeTasFile(_Refusals):

    def test_a_constant_series_past_the_minute_is_refused(self):
        out = self.root / "a.cdf"
        err = self.assertRefused("make-tas-file", str(out), "--constant-tas", "130",
                                 "--start-hhmmss", "60638", "--seconds", "30", written=out)
        self.assertIn("runs past", err)

    def test_a_start_that_is_not_a_clock_time_is_refused(self):
        for start in ("-5", "99", "66000", "480000"):
            out = self.root / f"b{start}.cdf"
            with self.subTest(start=start):
                err = self.assertRefused("make-tas-file", str(out), "--constant-tas", "130",
                                         "--start-hhmmss", start, "--seconds", "1",
                                         written=out)
                self.assertIn("--start-hhmmss", err)

    def test_an_unwrapped_midnight_hour_is_still_accepted(self):
        # UIOOPS counts 240000, 240001, ... after midnight (write_tas_file's clock rule).
        rc, err = self._run("make-tas-file", str(self.root / "c.cdf"), "--constant-tas",
                            "130", "--start-hhmmss", "250000", "--seconds", "10")
        self.assertEqual(rc, 0, err)

    def test_a_tas_csv_that_does_not_parse_is_refused(self):
        out = self.root / "d.cdf"
        err = self.assertRefused("make-tas-file", str(out), "--from-tas-csv", str(self.csv),
                                 written=out)
        self.assertIn(str(self.csv), err)

    def test_the_documented_constant_example_writes(self):
        page = (ROOT / "docs" / "06-configuration.md").read_text(encoding="utf-8")
        m = re.search(r"^arrayprobe make-tas-file (\S+) (--constant-tas .*)$", page, re.M)
        self.assertIsNotNone(m, "06-configuration.md carries no --constant-tas example")
        rc, err = self._run("make-tas-file", str(self.root / m.group(1)),
                            *m.group(2).split())
        self.assertEqual(rc, 0, f"the documented example fails:\n{err}")


class Compare(_Refusals):

    def test_a_file_that_is_not_netcdf_is_refused(self):
        self.assertRefused("compare", str(self.junk), str(self.junk))

    def test_a_right_hand_file_that_is_not_netcdf_is_refused(self):
        import netCDF4

        left = self.root / "left.nc"
        with netCDF4.Dataset(left, "w") as d:
            d.createDimension("time", 1)
        self.assertRefused("compare", str(left), str(self.junk))

    def test_a_file_whose_data_does_not_read_is_refused(self):
        # A netCDF4/HDF5 file whose header opens (file_kind reads its dimensions) fails only
        # when compare_files reads variable data. netCDF4 raises RuntimeError for a failed
        # variable read and OSError for a failed open; both are refused in one line.
        from unittest import mock

        from arrayprobe import compare as compare_module

        for exc in (RuntimeError("NetCDF: HDF error"), OSError(-101, "NetCDF: HDF error")):
            with self.subTest(exc=type(exc).__name__):
                broken = mock.patch.object(compare_module, "compare_files", side_effect=exc)
                kind = mock.patch.object(compare_module, "file_kind", return_value="proc")
                with kind, broken:
                    err = self.assertRefused("compare", str(self.junk), str(self.junk))
                self.assertIn("not a readable netCDF file", err)
                self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_a_real_file_with_corrupt_chunks_is_refused(self):
        # A real file, not a mock: a NETCDF4 proc file whose compressed chunks are zeroed. Its
        # header opens, so file_kind accepts it, and the data read raises RuntimeError. (A
        # truncated file is no fixture for this: HDF5 refuses it at open, measured 2026-10-18
        # at ten cut points from 5 % to 95 % of the file.)
        import netCDF4
        import numpy as np

        from arrayprobe import compare as compare_module

        n = 5000
        good = self.root / "good.nc"
        with netCDF4.Dataset(good, "w", format="NETCDF4") as d:
            d.createDimension("time", n)
            d.createDimension("pos_count", 2)
            for name in ("Date", "Time", "parent_rec_num"):
                d.createVariable(name, "i4", ("time",), zlib=True)[:] = np.arange(n)
            d.createVariable("position", "i4", ("time", "pos_count"),
                             zlib=True)[:] = np.arange(2 * n).reshape(n, 2)
            d.createVariable("image_area", "f8", ("time",),
                             zlib=True)[:] = np.random.default_rng(0).random(n)
        raw = bytearray(good.read_bytes())
        lo, hi = len(raw) // 2, len(raw) * 9 // 10
        raw[lo:hi] = bytes(hi - lo)
        bad = self.root / "bad.nc"
        bad.write_bytes(bytes(raw))
        # The two preconditions that make this the case under test, measured, not assumed.
        self.assertEqual(compare_module.file_kind(bad), "proc")
        with self.assertRaises(RuntimeError):
            compare_module.compare_files(bad, good)
        err = self.assertRefused("compare", str(bad), str(good))
        self.assertIn("not a readable netCDF file", err)
        self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_a_value_error_inside_the_comparison_keeps_its_traceback(self):
        from unittest import mock

        from arrayprobe import compare as compare_module

        for exc in (ValueError("internal defect"), NotImplementedError("internal defect"),
                    RecursionError("internal defect")):
            with self.subTest(exc=type(exc).__name__):
                defect = mock.patch.object(compare_module, "compare_files", side_effect=exc)
                kind = mock.patch.object(compare_module, "file_kind", return_value="proc")
                with kind, defect:
                    with self.assertRaises(type(exc)):
                        cli.main(["compare", str(self.junk), str(self.junk)])


class IntarrThreshold(_Refusals):

    def test_a_file_that_is_not_netcdf_is_refused(self):
        out = self.root / "it.nc"
        self.assertRefused("intarr-threshold", "--probe", "2DS", "--flight-date", "160906",
                           str(self.junk), str(out), written=out)

    def test_a_netcdf_file_without_time_is_refused(self):
        import netCDF4

        empty = self.root / "empty.nc"
        with netCDF4.Dataset(empty, "w") as d:
            d.createDimension("x", 1)
        out = self.root / "it2.nc"
        err = self.assertRefused("intarr-threshold", "--probe", "2DS", "--flight-date",
                                 "160906", str(empty), str(out), written=out)
        self.assertIn("Time", err)

    def test_a_missing_file_keeps_the_dispatcher_message(self):
        err = self.assertRefused("intarr-threshold", "--probe", "2DS", "--flight-date",
                                 "160906", str(self.root / "nofile.nc"),
                                 str(self.root / "it3.nc"))
        self.assertIn("No such file", err)


if __name__ == "__main__":
    unittest.main()
