# SPDX-License-Identifier: BSD-3-Clause
"""The v3.5 writer stores ``position`` in ``[1024, 2]`` blocks, and no value moves.

``position`` is ``short (pos_count, time)`` in MATLAB order, one 4-byte pair per particle.
With no chunk argument netCDF-C 4.9.3 gives it ``[1, 2]`` on disk, one HDF5 chunk per
particle (measured on the 2016-09-06 ``125407`` proc file in September 2026), which dominated the
merge's write and read time. The author approved block storage (2026-09-30); its build
plan names these tests:

- :class:`TestDefVarChunksizesKeyword` (B): ``ncio.def_var``'s ``chunksizes`` keyword,
  MATLAB order, default unchanged, failing closed on a classic file or a wrong length.
- :class:`TestTheWriterSetsThePositionChunkShape` (A): ``_create_output`` stores
  ``position`` as ``[1024, 2]`` and leaves every other variable at the library default.
  The gap itself (D) is pinned by ``test_v35_imgproc.TestWriterGaps``.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from arrayprobe import ncio
from arrayprobe_uiops import imgproc as v35


def _two_dim_file(path: Path, fmt: str = "NETCDF4"):
    """A file with the v3.5 writer's two ``position`` dimensions, in define mode."""
    f = ncio.create(str(path), "clobber", format=fmt)
    ncio.def_dim(f, "time", ncio.get_constant("NC_UNLIMITED"))
    ncio.def_dim(f, "pos_count", 2)
    return f


class TestDefVarChunksizesKeyword(unittest.TestCase):
    """B. ``chunksizes`` mirrors ``netcdf.defVarChunking``: MATLAB order like ``dimids``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _chunking(self, path: Path, name: str):
        with Dataset(path) as ds:
            return ds[name].chunking()

    def test_none_is_the_call_without_the_keyword(self):
        # The library default on either side, read from the file rather than typed.
        path = self.dir / "a.nc"
        f = _two_dim_file(path)
        ncio.def_var(f, "without", "short", [1, 0])
        ncio.def_var(f, "with_none", "short", [1, 0], chunksizes=None)
        ncio.close(f)
        self.assertEqual(self._chunking(path, "with_none"), self._chunking(path, "without"))

    def test_matlab_order_sizes_are_reversed_like_the_dimids(self):
        path = self.dir / "b.nc"
        f = _two_dim_file(path)
        ncio.def_var(f, "position", "short", [1, 0], chunksizes=(2, 16))
        ncio.close(f)
        with Dataset(path) as ds:
            self.assertEqual(ds["position"].dimensions, ("time", "pos_count"))
            self.assertEqual(ds["position"].chunking(), [16, 2])

    def test_the_ncfile_method_takes_the_same_keyword(self):
        path = self.dir / "c.nc"
        f = _two_dim_file(path)
        f.def_var("position", "short", [1, 0], chunksizes=(2, 8))
        ncio.close(f)
        self.assertEqual(self._chunking(path, "position"), [8, 2])

    def test_a_classic_file_has_no_chunks_and_refuses(self):
        f = _two_dim_file(self.dir / "d.nc", fmt="NETCDF3_CLASSIC")
        try:
            with self.assertRaises(ValueError):
                ncio.def_var(f, "position", "short", [1, 0], chunksizes=(2, 16))
        finally:
            ncio.close(f)

    def test_a_length_that_differs_from_the_dimids_refuses(self):
        f = _two_dim_file(self.dir / "e.nc")
        try:
            with self.assertRaises(ValueError):
                ncio.def_var(f, "position", "short", [1, 0], chunksizes=(16,))
        finally:
            ncio.close(f)


#: ``_create_output``'s positional arguments after ``outfile``: 128 diodes, all four
#: options off, no extended ellipse outputs, as ``test_engine_profile_attrs`` calls it.
_CREATE_ARGS = (128, "T", "in.H.nc", "2DS", 0, 0, 0, 0, None, "t", "t",
                "oracles-production-v3.5")


class TestTheWriterSetsThePositionChunkShape(unittest.TestCase):
    """A. The v3.5 writer's ``position`` is ``[1024, 2]`` on disk; the old one gave ``[1, 2]``."""

    N_PARTICLES = 3000  # not a multiple of 1024: the last chunk is partial

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.path = tmp / "proc.nc"
        cls.written = (np.arange(2 * cls.N_PARTICLES, dtype=np.int64)
                       .reshape(cls.N_PARTICLES, 2) % 1700)
        f = v35._create_output(str(cls.path), *_CREATE_ARGS)
        try:
            ncio.write_record_block(f, ncio.inq_var_id(f, "position"), 0, cls.written)
        finally:
            ncio.close(f)
        # Every other variable, defined with no chunk argument in a file of the same
        # dimensions: the library default, read from disk rather than typed.
        cls.default_path = tmp / "default.nc"
        g = ncio.create(str(cls.default_path), "clobber", format="NETCDF4")
        dimid = {"time": ncio.def_dim(g, "time", ncio.get_constant("NC_UNLIMITED")),
                 "pos_count": ncio.def_dim(g, "pos_count", 2),
                 "bin_count": ncio.def_dim(g, "bin_count", 128)}
        cls.specs = list(v35.imgproc_variables_v35(
            iRectEllipse=0, iCalcAllDiodeStats=0, iQC=0, iNewHabit=0,
            extended_ellipse_outputs=None, probetype=2))
        for spec in cls.specs:
            ncio.def_var(g, spec.name, spec.xtype, [dimid[d] for d in spec.dims],
                         chunksizes=None)
        ncio.close(g)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_position_is_stored_in_1024_particle_blocks(self):
        self.assertEqual(v35.WRITER_CHUNKING, {"position": (2, 1024)})
        with Dataset(self.path) as ds:
            self.assertEqual(ds["position"].dimensions, ("time", "pos_count"))
            self.assertEqual(ds["position"].chunking(), [1024, 2])

    def test_the_values_written_read_back_unchanged(self):
        with Dataset(self.path) as ds:
            ds.set_auto_maskandscale(False)
            got = ds["position"][:]
        self.assertEqual(got.shape, (self.N_PARTICLES, 2))
        np.testing.assert_array_equal(got, self.written)

    def test_every_other_variable_keeps_the_library_default(self):
        with Dataset(self.path) as ds, Dataset(self.default_path) as ref:
            names = [s.name for s in self.specs if s.name not in v35.WRITER_CHUNKING]
            self.assertTrue(names)
            for name in names:
                with self.subTest(variable=name):
                    self.assertEqual(ds[name].chunking(), ref[name].chunking())

    def test_the_default_differs_from_the_set_shape(self):
        # Without this the first test could pass on a library whose default is already
        # [1024, 2]; the old writer's [1, 2] is what changed.
        with Dataset(self.default_path) as ref:
            self.assertNotEqual(ref["position"].chunking(), [1024, 2])


if __name__ == "__main__":
    unittest.main()
