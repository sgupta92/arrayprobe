# SPDX-License-Identifier: BSD-3-Clause
"""``export_parquet(..., layout="particles")``: one Parquet row per particle of a proc file.

The default layout only ever sees size-distribution exports (time x bin), so a particle table
needs its own layout. The two sides of each check come from different places: the row count and
column set from netCDF4 reading the tracked proc fixture, the table from pyarrow reading the
written file.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe import attributed_export as ae

_HAVE_PYARROW = importlib.util.find_spec("pyarrow") is not None
if _HAVE_PYARROW:
    import pyarrow.parquet as pq

DATA = Path(__file__).resolve().parent / "data"
PROC = DATA / "demo_flight_v35_proc.nc"


def _expected_columns(path: Path) -> tuple[int, list[str]]:
    with netCDF4.Dataset(path) as ds:
        n = len(ds.dimensions["time"])
        cols: list[str] = []
        for name, var in ds.variables.items():
            if var.dimensions[:1] != ("time",):
                continue
            if len(var.dimensions) == 1:
                cols.append(name)
            else:
                cols += [f"{name}[{j + 1}]" for j in range(var.shape[1])]
    return n, cols


@unittest.skipUnless(_HAVE_PYARROW, "pyarrow not installed (the [parquet] extra)")
class AParticleTableHasOneRowPerParticle(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.proc = self.dir / PROC.name
        shutil.copy(PROC, self.proc)
        # The driver writes the stamp as <file>.call (run_flight.read_stamp).
        shutil.copy(PROC.with_suffix(".call"), Path(str(self.proc) + ".call"))

    def test_rows_equal_particles_and_columns_equal_per_particle_variables(self):
        out = ae.export_parquet(self.proc, layout="particles")
        tbl = pq.read_table(out)
        n, cols = _expected_columns(self.proc)
        self.assertGreater(n, 0)
        self.assertEqual(tbl.num_rows, n)
        self.assertEqual(tbl.column_names, cols)

    def test_values_are_the_proc_files(self):
        out = ae.export_parquet(self.proc, layout="particles")
        tbl = pq.read_table(out)
        with netCDF4.Dataset(self.proc) as ds:
            ds.set_auto_maskandscale(False)
            for name, var in ds.variables.items():
                if var.dimensions == ("time",):
                    np.testing.assert_array_equal(tbl[name].to_numpy(), var[...])

    def test_metadata_carries_run_record_and_checksum(self):
        out = ae.export_parquet(self.proc, layout="particles")
        meta = {k.decode(): v.decode() for k, v in pq.read_schema(out).metadata.items()}
        self.assertEqual(meta["arrayprobe_source_sha256"], ae.sha256_of(PROC))
        self.assertEqual(json.loads(meta["arrayprobe_call_stamp"]), ae.read_stamp(self.proc))
        self.assertIsNotNone(ae.read_stamp(self.proc))
        self.assertEqual(meta["arrayprobe_layout"], "particles")

    def test_must_fire_a_dropped_column_is_caught(self):
        """The column check fires: a table missing one per-particle variable fails it."""
        out = ae.export_parquet(self.proc, layout="particles")
        tbl = pq.read_table(out).drop_columns([_expected_columns(self.proc)[1][0]])
        with self.assertRaises(AssertionError):
            self.assertEqual(tbl.column_names, _expected_columns(self.proc)[1])

    def test_unknown_layout_refused(self):
        with self.assertRaises(ae.AttributedExportError):
            ae.export_parquet(self.proc, layout="rows")

    def test_refuses_to_overwrite(self):
        out = ae.export_parquet(self.proc, layout="particles")
        with self.assertRaises(ae.AttributedExportError):
            ae.export_parquet(self.proc, out, layout="particles")


@unittest.skipUnless(_HAVE_PYARROW, "pyarrow not installed (the [parquet] extra)")
class TheDefaultLayoutIsUnchanged(unittest.TestCase):
    def test_default_and_explicit_dimensions_write_identical_tables(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        nc = d / "a.nc"
        with netCDF4.Dataset(nc, "w", format="NETCDF4") as ds:
            ds.createDimension("time", 3)
            ds.createDimension("bin", 2)
            ds.createVariable("conc", "f8", ("time", "bin"))[:] = np.arange(6.0).reshape(3, 2)
        a = ae.export_parquet(nc, d / "default")
        b = ae.export_parquet(nc, d / "explicit", layout="dimensions")
        self.assertEqual(sorted(p.name for p in a.iterdir()), ["time__bin.parquet"])
        self.assertEqual(sorted(p.name for p in a.iterdir()),
                         sorted(p.name for p in b.iterdir()))
        self.assertTrue(pq.read_table(a / "time__bin.parquet").equals(
            pq.read_table(b / "time__bin.parquet")))


if __name__ == "__main__":
    unittest.main()
