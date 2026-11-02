# SPDX-License-Identifier: BSD-3-Clause
"""Tests for particle_number_all_fix.py.

Both states are covered: a proc file in the *defective* state (the variable defined by
``imgProc_sm.m:265`` and never written by ``:879``) and one in the *correct* state (written,
because the probetype is not 0 or 3).  The correction must act on the first and refuse the
second.

**The defective file here is synthetic, and that is stated rather than hidden.**  The defect
only occurs for probetype 0/3 (2DC, 2DP, Fast2DC); no such raw data or product exists on this
machine, so the fixture is built to the proc file's own layout by the test.  The *correct*
state is checked against a real ORACLES 2D-S proc file when one is present.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements.particle_number_all_fix import (
    VARIABLE,
    audit_proc_file,
    corrected_proc_file,
    defines_variable,
    is_inconsistent,
    writes_variable,
)

_REAL_PROC = (Path(__file__).resolve().parents[2] / "_decoded"
              / "proc.base160906064403.H.nc")

_N = 5


def _write_proc_like(path, *, write_particle_number_all: bool):
    """A miniature proc file with the two variables the finding is about.

    Layout follows ``imgproc.py``'s own spec table: an unlimited ``time`` dimension, an
    ``int`` ``Particle_number_all`` carrying the attribute the finding quotes, and a couple
    of neighbours so the copy has something to preserve.
    """
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.setncattr("Software", "synthetic fixture for C5b")
        ds.createDimension("time", None)
        ds.createDimension("pos_count", 2)
        time = ds.createVariable("Time", "i4", ("time",))
        time.Units = "HHMMSS"
        time[:] = np.arange(_N, dtype=np.int32) + 64403
        pos = ds.createVariable("position", "i2", ("time", "pos_count"))
        pos[:] = np.arange(_N * 2, dtype=np.int16).reshape(_N, 2)
        pna = ds.createVariable(VARIABLE, "i4", ("time",))
        pna.Units = "--"
        pna.Description = "Index of particle in 2-D buffer"
        if write_particle_number_all:
            pna[:] = np.arange(1, _N + 1, dtype=np.int32)


class TheTwoGuards(unittest.TestCase):
    """`:265`'s `||` against `:879`'s `&&`, reproduced as written."""

    def test_the_definition_guard_is_true_for_every_probetype(self):
        for probetype in (0, 1, 2, 3):
            with self.subTest(probetype=probetype):
                self.assertTrue(defines_variable(probetype))

    def test_the_write_guard_excludes_2dc_2dp_and_fast2dc(self):
        self.assertEqual([writes_variable(p) for p in (0, 1, 2, 3)],
                         [False, True, True, False])

    def test_only_probetypes_0_and_3_are_inconsistent(self):
        self.assertEqual([is_inconsistent(p) for p in (0, 1, 2, 3)],
                         [True, False, False, True])


class OnADefectiveFile(unittest.TestCase):
    """The correction ON: the variable is all fill, and the copy omits it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = self.tmp / "proc.probetype0.nc"
        _write_proc_like(self.src, write_particle_number_all=False)

    def test_the_audit_names_the_defect(self):
        report = audit_proc_file(self.src)
        self.assertTrue(report["present"])
        self.assertTrue(report["all_fill"])
        self.assertEqual((report["n"], report["n_real"]), (_N, 0))
        self.assertIn("never wrote it", report["verdict"])

    def test_the_correction_removes_the_variable_and_keeps_everything_else(self):
        dst = self.tmp / "corrected.nc"
        report = corrected_proc_file(self.src, dst)
        self.assertTrue(report["removed"])
        with netCDF4.Dataset(dst) as ds:
            self.assertNotIn(VARIABLE, ds.variables)
            np.testing.assert_array_equal(ds.variables["Time"][:],
                                          np.arange(_N) + 64403)
            np.testing.assert_array_equal(
                ds.variables["position"][:], np.arange(_N * 2).reshape(_N, 2))
            self.assertEqual(ds.getncattr("Software"), "synthetic fixture for C5b")
            self.assertEqual(ds.variables["Time"].Units, "HHMMSS")
            self.assertTrue(ds.dimensions["time"].isunlimited())

    def test_the_source_file_is_untouched(self):
        before = self.src.read_bytes()
        corrected_proc_file(self.src, self.tmp / "corrected.nc")
        self.assertEqual(self.src.read_bytes(), before)

    def test_the_corrected_file_audits_clean(self):
        dst = self.tmp / "corrected.nc"
        corrected_proc_file(self.src, dst)
        report = audit_proc_file(dst)
        self.assertFalse(report["present"])
        self.assertFalse(report["all_fill"])


class OnACorrectFile(unittest.TestCase):
    """The correction OFF by construction: nothing to do, and it must refuse to act."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = self.tmp / "proc.probetype2.nc"
        _write_proc_like(self.src, write_particle_number_all=True)

    def test_the_audit_says_it_was_written_as_intended(self):
        report = audit_proc_file(self.src)
        self.assertFalse(report["all_fill"])
        self.assertEqual(report["n_real"], _N)
        self.assertIn("written as intended", report["verdict"])

    def test_the_correction_refuses_to_delete_real_data(self):
        with self.assertRaises(ValueError):
            corrected_proc_file(self.src, self.tmp / "corrected.nc")

    def test_force_is_the_only_way_past_that_and_it_says_so(self):
        dst = self.tmp / "forced.nc"
        report = corrected_proc_file(self.src, dst, force=True)
        self.assertTrue(report["removed"])
        with netCDF4.Dataset(dst) as ds:
            self.assertNotIn(VARIABLE, ds.variables)


@unittest.skipUnless(_REAL_PROC.exists(), "Real proc file is not distributed with the package; "
                                          "this test runs in the development repository")
class OnARealOraclesProcFile(unittest.TestCase):
    """A real 2D-S product is probetype 2, so the module must find nothing to do."""

    def test_the_variable_is_written_and_the_module_is_a_no_op(self):
        report = audit_proc_file(_REAL_PROC)
        self.assertTrue(report["present"])
        self.assertFalse(report["all_fill"])
        self.assertGreater(report["n_real"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                corrected_proc_file(_REAL_PROC, Path(tmp) / "no.nc")


if __name__ == "__main__":
    unittest.main()
