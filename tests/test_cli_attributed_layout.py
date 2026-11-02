# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe attributed --layout``: the CLI reaches ``export_parquet(layout="particles")``.

Default (``dimensions``) must delegate to ``attributed_export.main`` with exactly the argv it
built before the option existed; ``particles`` writes one row per particle. The row count is read
from the proc file by netCDF4, the table by pyarrow.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4

from arrayprobe import attributed_export, cli

_HAVE_PYARROW = importlib.util.find_spec("pyarrow") is not None
if _HAVE_PYARROW:
    import pyarrow.parquet as pq

PROC = Path(__file__).resolve().parent / "data" / "demo_flight_v35_proc.nc"


class TheDefaultLayoutIsUnchanged(unittest.TestCase):
    def test_default_delegates_with_the_same_argv(self):
        with mock.patch.object(attributed_export, "main", return_value=0) as m, \
                mock.patch.object(attributed_export, "export_parquet") as ep:
            rc = cli.main(["attributed", "src.cdf", "out.nc", "--accept-unstamped"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with(["src.cdf", "out.nc", "--accept-unstamped"])
        ep.assert_not_called()

    def test_explicit_dimensions_is_the_default(self):
        with mock.patch.object(attributed_export, "main", return_value=0) as m:
            cli.main(["attributed", "src.cdf", "--layout", "dimensions"])
        m.assert_called_once_with(["src.cdf"])


@unittest.skipUnless(_HAVE_PYARROW, "needs the [parquet] extra (pyarrow)")
class TheParticlesLayoutWritesOneRowPerParticle(unittest.TestCase):
    def test_particles_layout(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        proc = d / PROC.name
        shutil.copy(PROC, proc)
        shutil.copy(PROC.with_suffix(".call"), Path(str(proc) + ".call"))
        out = d / "t.parquet"
        with mock.patch.object(attributed_export, "main") as m, \
                contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["attributed", str(proc), str(out), "--layout", "particles"])
        self.assertEqual(rc, 0)
        m.assert_not_called()
        with netCDF4.Dataset(proc) as ds:
            n = len(ds.dimensions[attributed_export.PARTICLE_DIM])
        self.assertGreater(n, 0)
        self.assertEqual(pq.read_table(out).num_rows, n)


class TheParticlesLayoutRefusesInOneLine(unittest.TestCase):
    """Its refusals print one line and exit 2, like every other subcommand's."""

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, err.getvalue()

    def test_export_refusal_is_one_line_not_a_traceback(self):
        def refuse(*a, **k):
            raise attributed_export.AttributedExportError("output exists: t.parquet")
        with mock.patch.object(attributed_export, "export_parquet", refuse):
            rc, err = self._run("attributed", "proc.nc", "t.parquet", "--layout", "particles")
        self.assertEqual(rc, 2)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertIn("output exists", err)

    def test_dimensions_only_flags_are_refused_not_ignored(self):
        for extra in (["--accept-unstamped"], ["--enhancements", "x.toml"]):
            with mock.patch.object(attributed_export, "export_parquet") as ep:
                rc, err = self._run("attributed", "proc.nc", "t.parquet",
                                    "--layout", "particles", *extra)
            self.assertEqual(rc, 2, extra)
            ep.assert_not_called()
            self.assertIn("--layout dimensions only", err)


if __name__ == "__main__":
    unittest.main()
