# SPDX-License-Identifier: BSD-3-Clause
"""`arrayprobe.diagnostic_views.hollow_share` and `arrayprobe view hollow`, on synthetic v3.5 procs.

v3.5 divides a hollow 'H' particle's ``image_diam_minR`` by its Korolev ``size_factor``; SODA-2
does not. The census says, per bin, how many accepted 'H' particles that division moves out of
and into the bin, and whether the net shift is large enough to explain a between-engine
difference. The cases:

* the in/out bookkeeping closes: ``accepted = undivided - out + in`` in every bin, and each
  moved particle is counted once out and once in when both its bins are in range;
* a rejected code and a centre-out particle are never counted;
* a range where most accepted particles are 'H' and move out fires the verdict;
* a range where few 'H' particles move does not;
* the file is read, never written.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover - netCDF4 is a runtime dependency
    netCDF4 = None

from arrayprobe import diagnostic_views as views

EDGES = [55.0, 65.0, 75.0, 85.0]


def _write_proc(path: Path, rows) -> None:
    """rows: (code, diam_um, size_factor, centre_in) -> a v3.5-shaped proc file."""
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("pos", len(rows))
        d.createVariable("Time", "f8", ("pos",))[:] = np.full(len(rows), 113000.0)
        d.createVariable("image_auto_reject", "i2", ("pos",))[:] = [ord(r[0]) for r in rows]
        d.createVariable("image_diam_minR", "f8", ("pos",))[:] = [r[1] / 1000.0 for r in rows]
        d.createVariable("size_factor", "f8", ("pos",))[:] = [r[2] for r in rows]
        d.createVariable("image_center_in", "i2", ("pos",))[:] = [r[3] for r in rows]


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestBookkeeping(unittest.TestCase):
    ROWS = [
        ("0", 60.0, 1.0, 1),   # bin 0, not hollow
        ("H", 60.0, 1.2, 1),   # written bin 0, undivided 72 -> bin 1: out of 1, into 0
        ("H", 70.0, 1.1, 1),   # written bin 1, undivided 77 -> bin 2: out of 2, into 1
        ("H", 80.0, 1.5, 1),   # written bin 2, undivided 120 -> beyond range: into 2 only
        ("H", 50.0, 1.2, 1),   # written below range, undivided 60 -> bin 0: out of 0 only
        ("H", 62.0, 1.01, 1),  # written and undivided both bin 0: not moved
        ("a", 60.0, 1.0, 1),   # rejected code: never counted
        ("H", 60.0, 1.5, 0),   # centre out: never counted
        ("h", 80.0, 1.0, 1),   # accepted 'h', bin 2
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "proc.synthetic.H.nc"
        _write_proc(self.path, self.ROWS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_per_bin(self):
        s = views.hollow_share(self.path, EDGES)
        np.testing.assert_array_equal(s.accepted, [3, 1, 2])
        np.testing.assert_array_equal(s.accepted_h, [2, 1, 1])
        np.testing.assert_array_equal(s.moved_in, [1, 1, 1])
        np.testing.assert_array_equal(s.moved_out, [1, 1, 1])
        np.testing.assert_array_equal(s.accepted_undivided, [3, 1, 2])

    def test_in_out_closes_in_every_bin(self):
        s = views.hollow_share(self.path, EDGES)
        np.testing.assert_array_equal(s.accepted, s.accepted_undivided - s.moved_out + s.moved_in)
        np.testing.assert_allclose(s.h_share, [2 / 3, 1.0, 0.5])

    def test_the_file_is_not_written(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        views.hollow_share(self.path, EDGES)
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_bad_edges_are_refused(self):
        with self.assertRaises(ValueError):
            views.hollow_share(self.path, [65.0, 55.0])

    def test_at_or_above_threshold_summary(self):
        # >= 55 um as written: 0@60, H@60, H@70, H@80, H@62, h@80 -> 6 accepted, 4 'H'.
        # Undivided adds H@50 x 1.2 = 60 (the one 'H' the division took below 55) -> 7.
        s = views.hollow_share_at_or_above(self.path, 55.0)
        self.assertEqual((s["accepted"], s["accepted_h"], s["accepted_undivided"]), (6, 4, 7))
        self.assertAlmostEqual(s["h_share"], 4 / 6)
        self.assertAlmostEqual(s["ratio_undivided_to_written"], 7 / 6)
        self.assertEqual(s["threshold_um"], 55.0)

    def test_at_or_above_an_empty_range_gives_nan_not_an_error(self):
        s = views.hollow_share_at_or_above(self.path, 1000.0)
        self.assertEqual(s["accepted"], 0)
        self.assertTrue(np.isnan(s["ratio_undivided_to_written"]))


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestVerdict(unittest.TestCase):
    def _share(self, rows, edges=(55.0, 115.0)):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proc.v.H.nc"
            _write_proc(path, rows)
            return views.hollow_share(path, list(edges))

    def test_fires_when_most_particles_leave_the_range(self):
        # the 07-07 shape: half the undivided particles are 'H' and the division takes them
        # below 55 um, with nothing above 115 um to move down
        rows = [("0", 80.0, 1.0, 1)] * 100 + [("H", 45.0, 1.6, 1)] * 100
        s = self._share(rows)
        self.assertEqual((int(s.accepted.sum()), int(s.accepted_undivided.sum())), (100, 200))
        self.assertEqual(s.net_shift, -100)
        self.assertTrue(s.fires)
        self.assertTrue(s.verdict().startswith("YES"))
        self.assertAlmostEqual(float(s.ratio_undivided_to_written[0]), 2.0)

    def test_quiet_when_few_move(self):
        rows = [("0", 80.0, 1.0, 1)] * 1000 + [("H", 50.0, 1.2, 1)] * 10
        s = self._share(rows)
        self.assertEqual(s.net_shift, -10)       # 1 % of the count
        self.assertFalse(s.fires)
        self.assertTrue(s.verdict().startswith("NO"))

    def test_quiet_on_a_sparse_range_below_the_poisson_clause(self):
        # 2 of 4 move: 50 % of the count, but 2 is not more than 2 sqrt(2)
        rows = [("0", 80.0, 1.0, 1)] * 2 + [("H", 50.0, 1.2, 1)] * 2
        s = self._share(rows)
        self.assertEqual(s.net_shift, -2)
        self.assertFalse(s.fires)

    def test_refill_from_above_cancels(self):
        # the 07-08 shape: as many 'H' move in from above 115 um as leave below 55 um
        rows = ([("0", 80.0, 1.0, 1)] * 100 + [("H", 50.0, 1.2, 1)] * 50
                + [("H", 100.0, 1.3, 1)] * 50)
        s = self._share(rows)
        self.assertEqual(s.net_shift, 0)
        self.assertFalse(s.fires)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestCli(unittest.TestCase):
    def test_view_hollow_prints_the_table_and_verdict(self):
        from arrayprobe import cli

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proc.v.H.nc"
            _write_proc(path, [("0", 80.0, 1.0, 1)] * 100 + [("H", 45.0, 1.6, 1)] * 100)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli.main(["view", "hollow", str(path), "--edges-um", "55,85,115"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("55-85", out)
        self.assertIn("YES:", out)

    def test_edges_are_required(self):
        from arrayprobe import cli

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["view", "hollow", "proc.nc"])


if __name__ == "__main__":
    unittest.main()
