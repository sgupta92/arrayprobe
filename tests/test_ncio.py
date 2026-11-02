# SPDX-License-Identifier: BSD-3-Clause
"""Acceptance tests for ``arrayprobe.ncio``.

No MATLAB is needed: the shipped ``2DS.20151205_subset1.V.cdf`` was written by
MATLAB UIOOPS, so it *is* the oracle for the dimension reversal, the type map and
the file format.

That file is 52 MB and therefore gitignored, so the structural tests run instead
against ``tests/data/2DS_header_fixture.nc`` -- a 160 KiB cut of the same file,
header preserved exactly (see ``make_2ds_header_fixture.py``).  A fresh clone
therefore still exercises the reversal rather than skipping it.  Only the tests
that genuinely need many records skip when the original is absent, and
:meth:`TestFixtureFidelity.test_fixture_header_matches_the_original` keeps the
fixture from drifting whenever both are present.

Tests that would need a MATLAB-written *output* file (a genuine
record dimension, and the imgProc/sizeDist headers) stay unwritten until the
ORACLES reference pair is reviewed.

Test names carry the ``file:line`` they protect, so a future "cleanup" that
changes behaviour fails a test that names its own source line.
"""

import os
import tempfile
import unittest

import numpy as np
from netCDF4 import Dataset
from tests import _upstream

from arrayprobe import ncio

_HERE = os.path.dirname(os.path.abspath(__file__))
_MWE = str(_upstream.source("uiops314") / "minimal_working_example")
REAL_2DS = os.path.abspath(os.path.join(_MWE, "2DS.20151205_subset1.V.cdf"))
REAL_HVPS = os.path.abspath(os.path.join(_MWE, "HVPS.20151205_subset.V.cdf"))
REAL_FLIGHT = os.path.abspath(os.path.join(_MWE, "flightData_20151205.cdf"))
FIXTURE_2DS = os.path.join(_HERE, "data", "2DS_header_fixture.nc")

_HAS_REAL = os.path.exists(REAL_2DS)

# The header oracle: the real MATLAB-written file when it is on this machine,
# otherwise the tracked cut of it. Structurally identical by construction.
ORACLE_2DS = REAL_2DS if _HAS_REAL else FIXTURE_2DS


class TempFileMixin:
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = os.path.join(self._tmpdir.name, "out.cdf")

    def tearDown(self):
        self._tmpdir.cleanup()


# --------------------------------------------------------------------------
# Constants and the type map
# --------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_get_constant_values(self):
        """imgProc_sm.m:214,218 -- the only two constants UIOOPS asks for."""
        self.assertEqual(ncio.get_constant("NC_UNLIMITED"), 0)
        self.assertEqual(ncio.get_constant("NC_GLOBAL"), -1)

    def test_unknown_constant_names_its_own_limitation(self):
        with self.assertRaises(ValueError) as ctx:
            ncio.get_constant("NC_NOFILL")
        self.assertIn("NC_UNLIMITED", str(ctx.exception))

    def test_byte_is_signed_int8(self):
        """read_binary_SPEC.m:49-53 -- 'byte' is SIGNED; uint8 would corrupt dates."""
        self.assertIs(ncio.MATLAB_NC_TYPES["byte"], np.int8)

    def test_char_type_maps_to_S1(self):
        """Measured under Octave's netcdf package; tests/test_ncio_char.py holds it to the file."""
        self.assertEqual(ncio.MATLAB_NC_TYPES["char"], "S1")

    def test_nc_fill_matches_netcdf3_defaults(self):
        """No _FillValue is ever written (design doc §1.6), so these are what an
        unwritten record holds and what get_var returns raw."""
        self.assertEqual(ncio.NC_FILL["int"], -2147483647)
        self.assertEqual(ncio.NC_FILL["short"], -32767)
        self.assertEqual(ncio.NC_FILL["byte"], -127)


# --------------------------------------------------------------------------
# The dimension reversal, against the MATLAB-written file
# --------------------------------------------------------------------------

class TestDimensionReversal(TempFileMixin, unittest.TestCase):
    """Runs against the header oracle, so it never skips on a fresh clone."""

    def _write_spec_header(self, path, n_records=4):
        """Transliterate read_binary_SPEC.m:42-57 verbatim."""
        f = ncio.create(path)
        dimid0 = ncio.def_dim(f, "time", ncio.get_constant("NC_UNLIMITED"))  # :44
        dimid1 = ncio.def_dim(f, "ImgRowlen", 8)                              # :45
        dimid2 = ncio.def_dim(f, "ImgBlocklen", 1700)                         # :46
        ids = {}
        ids["year"] = ncio.def_var(f, "year", "short", [dimid0])              # :48
        for name in ("month", "day", "hour", "minute", "second"):             # :49-53
            ids[name] = ncio.def_var(f, name, "byte", [dimid0])
        ids["millisec"] = ncio.def_var(f, "millisec", "short", [dimid0])      # :54
        ids["wkday"] = ncio.def_var(f, "wkday", "byte", [dimid0])             # :55
        ids["data"] = ncio.def_var(f, "data", "int", [dimid1, dimid2, dimid0])  # :56
        ncio.end_def(f)
        for i in range(n_records):
            ncio.put_var(f, ids["year"], [i], [1], 2015)
            for name in ("month", "day", "hour", "minute", "second", "wkday"):
                ncio.put_var(f, ids[name], [i], [1], 1)
            ncio.put_var(f, ids["millisec"], [i], [1], 0)
        return f, ids

    def test_defvar_reverses_dims_to_match_real_file(self):
        """read_binary_SPEC.m:56 -- [ImgRowlen ImgBlocklen time] lands on disk as
        ('time','ImgBlocklen','ImgRowlen'). The claim, tested directly."""
        f, _ = self._write_spec_header(self.tmp)
        ncio.close(f)

        with open(self.tmp, "rb") as syn_bytes, open(ORACLE_2DS, "rb") as ref_bytes:
            self.assertEqual(syn_bytes.read(4), b"CDF\x01")
            self.assertEqual(ref_bytes.read(4), b"CDF\x01")

        with Dataset(self.tmp) as syn, Dataset(ORACLE_2DS) as ref:
            self.assertEqual(list(syn.dimensions), list(ref.dimensions))
            self.assertEqual(list(syn.variables), list(ref.variables))
            for name in ref.variables:
                self.assertEqual(
                    syn[name].dimensions, ref[name].dimensions,
                    f"{name}: dimension order diverged from the MATLAB-written file",
                )
                self.assertEqual(syn[name].dtype, ref[name].dtype, f"{name}: dtype")
            self.assertEqual(syn["data"].dimensions, ("time", "ImgBlocklen", "ImgRowlen"))

    @unittest.skipUnless(_HAS_REAL, "needs the 52 MB 2DS file (record 999)")
    def test_getvar_start_count_matches_python_slice(self):
        """imgProc_sm.m:493 + :495 against a direct netCDF4 slice, on real data."""
        f = ncio.open(REAL_2DS)
        vid = ncio.inq_var_id(f, "data")
        with Dataset(REAL_2DS) as ds:
            ds["data"].set_auto_maskandscale(False)
            for i in (0, 1, 17, 999):
                temp = ncio.get_var(f, vid, [0, 0, i], [8, 1700, 1])
                self.assertEqual(temp.shape, (8, 1700))
                self.assertTrue(np.array_equal(temp.T, ds["data"][i, :, :]))
                fused = ncio.read_image_record(f, vid, i, 8, 1700)
                self.assertEqual(fused.shape, (1700, 8))
                self.assertTrue(np.array_equal(fused, temp.T))
        ncio.close(f)

    def test_boundary_marker_orientation(self):
        """imgProc_sm.m:159 -- the 2DS boundary fills a whole 8-element slice, so
        all-43690 runs lie along the LAST axis of `data` after :495."""
        f = ncio.open(ORACLE_2DS)
        vid = ncio.inq_var_id(f, "data")
        data = ncio.read_image_record(f, vid, 0, 8, 1700)
        ncio.close(f)
        self.assertEqual(int((data == 43690).all(axis=1).sum()), 16)
        self.assertEqual(int((data == 43690).all(axis=0).sum()), 0)

    def test_ncread_returns_matlab_order(self):
        """run_imgProc_Munich.m:24,32-34 -- ncread('data') is 8 x 1700 x Ntime."""
        arr = ncio.ncread(ORACLE_2DS, "data")
        with Dataset(ORACLE_2DS) as ds:
            n_time = ds.dimensions["time"].size
        self.assertEqual(arr.shape, (8, 1700, n_time))

    def test_inq_dim_uses_creation_order_ids(self):
        """imgProc_sm.m:205-206 reads dimensions 2 and 0 by bare number."""
        f = ncio.open(ORACLE_2DS)
        self.assertEqual(ncio.inq_dim(f, 0)[0], "time")
        self.assertEqual(ncio.inq_dim(f, 2)[0], "ImgBlocklen")
        self.assertEqual(ncio.inq_dim(f, 2)[1], 1700)
        ncio.close(f)

    @unittest.skipUnless(os.path.exists(REAL_HVPS), "needs the 27 MB HVPS file")
    def test_hvps_file_shares_the_layout(self):
        """The reversal is not a 2DS accident -- HVPS is written the same way."""
        with Dataset(REAL_HVPS) as ds:
            self.assertEqual(ds["data"].dimensions, ("time", "ImgBlocklen", "ImgRowlen"))

    @unittest.skipUnless(os.path.exists(REAL_FLIGHT), "needs flightData_20151205.cdf")
    def test_reader_accepts_64bit_offset_input(self):
        """flightData_20151205.cdf is CDF\\x02 and is read at imgProc_sm.m:169-170."""
        arr = ncio.ncread(REAL_FLIGHT, "TAS")
        self.assertGreater(arr.size, 0)


class TestFixtureFidelity(unittest.TestCase):
    """The tracked fixture stands in for a 52 MB oracle, so it must not drift."""

    def test_fixture_exists_and_is_small(self):
        self.assertTrue(
            os.path.exists(FIXTURE_2DS),
            "regenerate with tests/data/make_2ds_header_fixture_synthetic.py",
        )
        self.assertLess(os.path.getsize(FIXTURE_2DS), 1_000_000)

    def test_fixture_is_netcdf3_classic(self):
        with open(FIXTURE_2DS, "rb") as fh:
            self.assertEqual(fh.read(4), b"CDF\x01")

    @unittest.skipUnless(_HAS_REAL, "needs the original to compare against")
    def test_fixture_header_matches_the_original(self):
        """Every header property the acceptance tests rely on, compared field by
        field against the MATLAB-written original."""
        with Dataset(FIXTURE_2DS) as fix, Dataset(REAL_2DS) as ref:
            self.assertEqual(list(fix.dimensions), list(ref.dimensions))
            self.assertEqual(list(fix.variables), list(ref.variables))
            self.assertEqual(fix.ncattrs(), ref.ncattrs())
            for name in ref.variables:
                with self.subTest(variable=name):
                    self.assertEqual(fix[name].dimensions, ref[name].dimensions)
                    self.assertEqual(fix[name].dtype, ref[name].dtype)
                    self.assertEqual(fix[name].ncattrs(), ref[name].ncattrs())
            for dim in ref.dimensions:
                if dim != "time":
                    self.assertEqual(len(fix.dimensions[dim]), len(ref.dimensions[dim]))

    @unittest.skipUnless(_HAS_REAL, "needs the original to compare against")
    def test_fixture_records_are_verbatim(self):
        """The retained records are copies, not regenerated values -- so a
        data-level assertion means the same thing against either file."""
        n = len(Dataset(FIXTURE_2DS).dimensions["time"])
        with Dataset(FIXTURE_2DS) as fix, Dataset(REAL_2DS) as ref:
            fix["data"].set_auto_maskandscale(False)
            ref["data"].set_auto_maskandscale(False)
            self.assertTrue(np.array_equal(fix["data"][:n], ref["data"][:n]))


# --------------------------------------------------------------------------
# Round-tripping without the real file
# --------------------------------------------------------------------------

class TestRoundTrip(TempFileMixin, unittest.TestCase):
    def _make(self, n_time=5, n_other=2):
        f = ncio.create(self.tmp)
        dt = ncio.def_dim(f, "time", ncio.NC_UNLIMITED)
        do = ncio.def_dim(f, "other", n_other)
        # MATLAB order [other time] -> on disk ('time','other')
        vid = ncio.def_var(f, "position", "int", [do, dt])
        vid1 = ncio.def_var(f, "scalarish", "double", [dt])
        ncio.end_def(f)
        return f, vid, vid1

    def test_default_format_is_netcdf3_classic(self):
        """Every netcdf.create site passes a bare 'clobber' (design doc §1.5)."""
        f, _, _ = self._make()
        ncio.close(f)
        with open(self.tmp, "rb") as fh:
            self.assertEqual(fh.read(4), b"CDF\x01")

    def test_putvar_absorbs_the_matlab_transpose(self):
        """imgProc_sm.m:885 -- putVar(...,[0 wstart],[2 n], images.position')
        writes a (2,n) MATLAB array that lands on disk as (time,2)."""
        f, vid, _ = self._make(n_other=2)
        n = 3
        position = np.array([[10, 11, 12], [20, 21, 22]], dtype=np.int32)  # 2 x n
        ncio.put_var(f, vid, [0, 0], [2, n], position)
        ncio.close(f)
        with Dataset(self.tmp) as ds:
            ds["position"].set_auto_maskandscale(False)
            on_disk = ds["position"][:n, :]
        self.assertEqual(on_disk.shape, (n, 2))
        self.assertTrue(np.array_equal(on_disk, position.T))

    def test_write_read_roundtrip_preserves_matlab_orientation(self):
        f, vid, _ = self._make(n_other=2)
        position = np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.int32)
        ncio.put_var(f, vid, [0, 0], [2, 4], position)
        back = ncio.get_var(f, vid, [0, 0], [2, 4])
        self.assertTrue(np.array_equal(back, position))
        ncio.close(f)

    def test_getvar_does_not_mask_but_ncread_does(self):
        """The single most important behavioural distinction in the module.

        netCDF4-python masks by default even with no _FillValue attribute;
        MATLAB's low-level netcdf.getVar does not, but its high-level ncread does.
        """
        # netCDF3 only accepts _FillValue at creation, so build this one directly.
        fill = np.int32(ncio.NC_FILL["int"])
        with Dataset(self.tmp, "w", format="NETCDF3_CLASSIC") as ds:
            ds.createDimension("time", 6)
            var = ds.createVariable("v", np.int32, ("time",), fill_value=fill)
            var.set_auto_maskandscale(False)
            var[0:2] = np.array([7, 8], dtype=np.int32)

        f = ncio.open(self.tmp)
        vid = ncio.inq_var_id(f, "v")
        raw = ncio.get_var(f, vid)
        ncio.close(f)
        self.assertFalse(np.ma.isMaskedArray(raw))
        self.assertEqual(int(raw[5, 0]), int(fill))   # the raw fill, not a mask

        masked = ncio.ncread(self.tmp, "v")
        self.assertTrue(np.ma.isMaskedArray(masked))
        self.assertTrue(bool(np.ma.getmaskarray(masked)[5, 0]))
        self.assertEqual(int(masked[0, 0]), 7)

    def test_getvar_returns_a_column_for_1d_variables(self):
        """Diff-orientation gap / design doc §T3 -- sizeDist.m:815 does [0;diff(...)], a vertical
        concatenation, which only makes sense on an Nx1 column."""
        f, _, vid1 = self._make()
        ncio.put_var(f, vid1, [0], [3], np.array([1.0, 2.0, 3.0]))
        whole = ncio.get_var(f, vid1)
        self.assertEqual(whole.ndim, 2)
        self.assertEqual(whole.shape[1], 1)
        ncio.close(f)

    def test_write_record_block_wants_on_disk_order(self):
        """The fused imgProc_sm.m:873-929 idiom takes C order, and says so loudly
        when handed a MATLAB-order array instead."""
        f, vid, _ = self._make(n_other=2)
        block = np.array([[1, 2], [3, 4], [5, 6]], dtype=np.int32)  # (time, other)
        ncio.write_record_block(f, vid, 0, block)
        back = ncio.get_var(f, vid, [0, 0], [2, 3])
        self.assertTrue(np.array_equal(back, block.T))
        with self.assertRaises(ValueError) as ctx:
            ncio.write_record_block(f, vid, 0, block.T)
        self.assertIn("put_var", str(ctx.exception))
        ncio.close(f)

    def test_attribute_names_with_spaces_survive_netcdf3(self):
        """Attribute-name gap -- 'Creation Time', 'SA Method' and friends are the output
        contract (imgProc_sm.m:219-237). If netCDF-C rejected them, every global
        attribute would need a workaround."""
        f, vid, _ = self._make()
        ncio.close(f)
        f = ncio.create(self.tmp)
        d = ncio.def_dim(f, "time", ncio.NC_UNLIMITED)
        v = ncio.def_var(f, "x", "double", [d])
        ncio.put_att(f, ncio.NC_GLOBAL, "Creation Time", "05-Dec-2015 00:00:00")
        ncio.put_att(f, ncio.NC_GLOBAL, "Optional parameters active", "Shatter removal")
        ncio.put_att(f, v, "Units", "millimeter")   # imgProc_sm.m's capitalization
        ncio.put_att(f, v, "units", "mm")           # sizeDist.m's -- both preserved
        ncio.end_def(f)
        ncio.close(f)
        with Dataset(self.tmp) as ds:
            self.assertEqual(ds.getncattr("Creation Time"), "05-Dec-2015 00:00:00")
            self.assertEqual(ds.getncattr("Optional parameters active"), "Shatter removal")
            self.assertEqual(ds["x"].getncattr("Units"), "millimeter")
            self.assertEqual(ds["x"].getncattr("units"), "mm")


class TestDefineModeDiscipline(TempFileMixin, unittest.TestCase):
    """UIOOPS never calls netcdf.reDef, so define mode is a one-way door."""

    def test_putvar_before_enddef_fails_like_matlab(self):
        f = ncio.create(self.tmp)
        d = ncio.def_dim(f, "time", ncio.NC_UNLIMITED)
        v = ncio.def_var(f, "x", "double", [d])
        with self.assertRaises(RuntimeError) as ctx:
            ncio.put_var(f, v, [0], [1], 1.0)
        self.assertIn("endDef", str(ctx.exception))
        ncio.close(f)

    def test_putatt_after_enddef_fails_like_matlab(self):
        f = ncio.create(self.tmp)
        d = ncio.def_dim(f, "time", ncio.NC_UNLIMITED)
        ncio.def_var(f, "x", "double", [d])
        ncio.end_def(f)
        with self.assertRaises(RuntimeError) as ctx:
            ncio.put_att(f, ncio.NC_GLOBAL, "Creation Time", "x")
        self.assertIn("reDef", str(ctx.exception))
        ncio.close(f)

    def test_char_type_defines_an_S1_variable(self):
        f = ncio.create(self.tmp)
        d = ncio.def_dim(f, "time", 3)
        vid = ncio.def_var(f, "s", "char", [d])
        self.assertEqual(f.variable(vid).dtype, np.dtype("S1"))
        ncio.close(f)

    def test_close_is_idempotent(self):
        """A second close must be a no-op, and must not damage what was written.

        Asserted rather than merely executed since 2026-09-06: the body was
        four calls and no assertion, so it passed whatever they did short of
        raising -- including truncating the file on the second close.
        """
        f = ncio.create(self.tmp)
        ncio.end_def(f)
        ncio.close(f)
        size_after_first = os.path.getsize(self.tmp)
        ncio.close(f)
        self.assertTrue(os.path.isfile(self.tmp),
                        "the second close removed the file")
        self.assertEqual(os.path.getsize(self.tmp), size_after_first,
                         "the second close changed the file on disk")

    def test_context_manager_closes(self):
        with ncio.create(self.tmp) as f:
            ncio.def_dim(f, "time", 2)
            ncio.end_def(f)
        self.assertFalse(f.dataset.isopen())


if __name__ == "__main__":
    unittest.main()
