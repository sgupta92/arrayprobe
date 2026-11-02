# SPDX-License-Identifier: BSD-3-Clause
"""arrayprobe.ai_ready: the AI-ready claims of arrayprobe.attributed_export, as a machine check."""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from netCDF4 import Dataset

from arrayprobe import ai_ready
from arrayprobe import attributed_export as ae

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_attributed_export import _faithful  # noqa: E402

WHEN = "2026-10-08T00:00:00+00:00"


class TheExportPassesItsOwnClaims(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.source = _faithful(self.dir)
        self.out = ae.export(self.source, self.dir / "a.nc", export_time=WHEN)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_default_export_passes(self):
        self.assertEqual(ai_ready.check(self.out), [])

    def test_an_unstamped_export_passes_on_its_absent_statement(self):
        sub = self.dir / "u"
        sub.mkdir()
        src = _faithful(sub, stamp=None)
        out = ae.export(src, self.dir / "u.nc", accept_unstamped=True, export_time=WHEN)
        self.assertEqual(ai_ready.check(out), [])

    def test_the_plain_export_fails_on_chunking_and_compression(self):
        plain = ae.export(self.source, self.dir / "plain.nc", export_time=WHEN,
                          analysis_ready=False)
        failures = ai_ready.check(plain)
        self.assertTrue(failures)
        self.assertTrue(all(f.startswith("chunked_and_compressed:") for f in failures), failures)
        self.assertTrue(any("contiguous" in f for f in failures))
        self.assertTrue(any("zlib" in f for f in failures))

    def test_a_variable_without_units_fails_by_name(self):
        bad = self.dir / "bad.nc"
        shutil.copyfile(self.out, bad)
        ds = Dataset(str(bad), "a")
        try:
            ds.variables["Bin Midpoints"].delncattr("units")
        finally:
            ds.close()
        failures = ai_ready.check(bad)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("'Bin Midpoints'", failures[0])
        self.assertIn("units", failures[0])

    def test_a_missing_acdd_attribute_and_an_added_fill_value_fail(self):
        bad = self.dir / "bad2.nc"
        shutil.copyfile(self.out, bad)
        ds = Dataset(str(bad), "a")
        try:
            ds.delncattr("history")
            ds.delncattr(f"{ae.ATTR_PREFIX}encoding")
        finally:
            ds.close()
        failures = ai_ready.check(bad)
        self.assertTrue(any(f.startswith("acdd_discovery:") and "'history'" in f
                            for f in failures), failures)
        self.assertTrue(any(f.startswith("encoding_statement:") for f in failures), failures)

    def test_main_exit_codes(self):
        plain = ae.export(self.source, self.dir / "plain.nc", export_time=WHEN,
                          analysis_ready=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(ai_ready.main([str(self.out)]), 0)
            self.assertEqual(ai_ready.main([str(self.out), str(plain)]), 1)
            self.assertEqual(ai_ready.main([]), 2)
        text = buf.getvalue()
        self.assertIn(f"PASS {self.out}", text)
        self.assertIn(f"FAIL {plain}", text)

    def test_an_unreadable_path_fails_rather_than_crashing(self):
        junk = self.dir / "junk.nc"
        junk.write_bytes(b"not a netCDF file")
        failures = ai_ready.check(junk)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].startswith("unreadable:"))


class TheZarrStorePasses(unittest.TestCase):

    def setUp(self):
        try:
            import xarray  # noqa: F401
            import zarr  # noqa: F401
        except ImportError:
            self.skipTest("zarr/xarray not installed (the [zarr] extra)")
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_zarr_store_from_export_zarr_passes(self):
        nc = ae.export(_faithful(self.dir), self.dir / "a.nc", export_time=WHEN)
        store = ae.export_zarr(nc)
        self.assertEqual(ai_ready.check(store), [])


if __name__ == "__main__":
    unittest.main()
