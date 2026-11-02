# SPDX-License-Identifier: BSD-3-Clause
"""The record strip reads only the proc rows it shows (triage-server memory incident, 2026-10-01).

``diagnostic_views.record_strip`` used to read ``parent_rec_num``, ``position``,
``image_auto_reject`` and ``holroyd_habit`` whole on every request. On a 17.8M-particle flight
that took the triage server to 44 GB, and because the read held the server's netCDF lock, every
particle and image request queued behind it for over 120 s.

Two sides, from different places:

* **how much is read** is counted by a proxy around each netCDF variable, not inferred from the
  code: a strip of a few records out of a large synthetic file must read a number of elements
  bounded by the particles shown plus O(log n), never the variable's length;
* **what is shown** is compared with a verbatim copy of the old whole-read implementation
  (``_old_record_strip`` below), run on the same files: records, shadow, boundary, particles and
  categories must be identical, for strips at the start, middle and end of the file, a strip of
  records holding no particles, a strip clipped at the file's end, both colourings, and a file
  whose ``parent_rec_num`` is not in record order (which must fall back to the whole read).
"""

from __future__ import annotations

import math
import shutil
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe import diagnostic_views as views

DATA = Path(__file__).resolve().parent / "data"


def _old_record_strip(image_ds, proc_ds, first_record, n_records=6, *, colour_by="reject",
                      boundary_word=views.BOUNDARY_WORD):
    """``record_strip`` as it was before 2026-10-01, kept verbatim as the reference."""
    data = image_ds.variables["data"]
    total = int(data.shape[0])
    last = min(total, first_record + n_records - 1)
    records = tuple(range(first_record, last + 1))
    blocks = [np.asarray(data[r - 1, :, :]) for r in records]
    shadow = np.stack([views._shadow_of_block(b) for b in blocks])
    boundary = np.stack([np.all((b.astype(np.int64) & 0xFFFF) == boundary_word, axis=1)
                         for b in blocks])
    parent = np.asarray(proc_ds.variables["parent_rec_num"][:]).reshape(-1)
    position = np.asarray(proc_ds.variables["position"][:]).reshape(-1, 2)
    reject = (np.asarray(proc_ds.variables["image_auto_reject"][:]).reshape(-1)
              if "image_auto_reject" in proc_ds.variables else None)
    habit = (np.asarray(proc_ds.variables["holroyd_habit"][:]).reshape(-1)
             if "holroyd_habit" in proc_ds.variables else None)
    rows = np.nonzero((parent >= first_record) & (parent <= last))[0]
    particles = tuple(
        views.StripParticle(
            index=int(i), record=int(parent[i]),
            first_slice=int(position[i, 0]), last_slice=int(position[i, 1]),
            reject=views._char(reject[i], views._REJECT_BY_VALUE) if reject is not None else None,
            habit=views._char(habit[i], views._HABIT_BY_VALUE) if habit is not None else None)
        for i in rows)
    categories = tuple(sorted({p.category(colour_by) for p in particles},
                              key=lambda c: (c != "accepted", c)))
    return views.RecordStrip(records, shadow, boundary, particles, colour_by, categories)


class _CountingVar:
    """A netCDF variable that counts the elements every read returns."""

    def __init__(self, var, tally, name):
        self._var, self._tally, self._name = var, tally, name
        self.shape, self.ndim, self.dimensions = var.shape, var.ndim, var.dimensions

    def __getitem__(self, key):
        out = self._var[key]
        self._tally[self._name] = self._tally.get(self._name, 0) + int(np.size(out))
        self._tally["largest single read"] = max(self._tally.get("largest single read", 0),
                                                 int(np.size(out)))
        return out


class _CountingDataset:
    def __init__(self, ds):
        self._ds = ds
        self.tally: dict[str, int] = {}
        self.variables = {n: _CountingVar(v, self.tally, n) for n, v in ds.variables.items()}

    def filepath(self):
        return self._ds.filepath()


def _write_proc(path: Path, parent: np.ndarray, rng) -> None:
    n = parent.size
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("time", n)
        d.createDimension("pos_count", 2)
        d.createVariable("parent_rec_num", "f8", ("time",))[:] = parent
        first = rng.integers(1, 1600, n)
        pos = np.stack([first, first + rng.integers(0, 90, n)], axis=1)
        d.createVariable("position", "i2", ("time", "pos_count"))[:] = pos
        d.createVariable("image_auto_reject", "f8", ("time",))[:] = rng.choice(
            [48.0, 48.0, 48.0, 97.0, 104.0, 115.0], n)
        d.createVariable("holroyd_habit", "f8", ("time",))[:] = rng.choice(
            [77.0, 116.0, 111.0, 108.0, 115.0], n)


class _Image:
    """The decode's ``data`` variable as an in-memory array; only the proc side is counted."""

    def __init__(self, n_records: int, rng):
        words = rng.integers(0, 65536, (n_records, 1700, 2)).astype(np.uint16)
        words[:, 1650:, :] = views.BOUNDARY_WORD
        self.variables = {"data": words}


class StripReadsOnlyTheRowsItShows(unittest.TestCase):
    N_RECORDS = 400

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="strip_bounded_"))
        rng = np.random.default_rng(20261001)
        counts = rng.integers(0, 600, cls.N_RECORDS)
        counts[[9, 10, 11]] = 0                     # records 10-12 hold no particle
        cls.parent = np.repeat(np.arange(1, cls.N_RECORDS + 1), counts).astype(float)
        cls.proc = cls.tmp / "proc.nc"
        _write_proc(cls.proc, cls.parent, rng)
        cls.image = _Image(cls.N_RECORDS, rng)
        shuffled = cls.parent.copy()
        rng.shuffle(shuffled)
        cls.unordered = cls.tmp / "proc_unordered.nc"
        _write_proc(cls.unordered, shuffled, rng)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _open(self, path):
        ds = netCDF4.Dataset(str(path))
        self.addCleanup(ds.close)
        return ds

    def assertSameStrip(self, new, old):
        self.assertEqual(new.records, old.records)
        np.testing.assert_array_equal(new.shadow, old.shadow)
        np.testing.assert_array_equal(new.boundary, old.boundary)
        self.assertEqual(new.particles, old.particles)
        self.assertEqual(new.categories, old.categories)
        self.assertEqual(new.colour_by, old.colour_by)

    def test_a_few_records_read_the_shown_rows_plus_a_logarithm_never_the_variable(self):
        n = self.parent.size
        self.assertGreater(n, 50_000)
        views.record_strip(self.image, self._open(self.proc), 1, 1)   # the once-per-file scan
        for first in (1, 200, self.N_RECORDS - 2):
            proxy = _CountingDataset(self._open(self.proc))
            strip = views.record_strip(self.image, proxy, first, 3)
            shown = len(strip.particles)
            # parent_rec_num twice (search, then the block), position 2 per row, reject, habit;
            # plus two binary searches of one element per step.
            budget = 5 * shown + 2 * (math.ceil(math.log2(n + 1)) + 1)
            total = sum(v for k, v in proxy.tally.items() if k != "largest single read")
            self.assertLessEqual(total, budget, (first, shown, proxy.tally))
            for name, count in proxy.tally.items():
                self.assertLess(count, n // 10, (name, proxy.tally))

    def test_the_record_order_scan_is_chunked_and_runs_once_per_file(self):
        n = self.parent.size
        chunk = views._ORDER_SCAN_CHUNK
        views._ORDER_SCAN_CHUNK = 4096
        self.addCleanup(setattr, views, "_ORDER_SCAN_CHUNK", chunk)
        views._RECORD_ORDER_CACHE.clear()
        first = _CountingDataset(self._open(self.proc))
        views.record_strip(self.image, first, 200, 3)
        self.assertGreaterEqual(first.tally["parent_rec_num"], n)        # the scan ran
        self.assertLessEqual(first.tally["largest single read"], 4096)   # in bounded chunks
        second = _CountingDataset(self._open(self.proc))
        views.record_strip(self.image, second, 200, 3)
        self.assertLess(second.tally["parent_rec_num"], n // 10)         # and not again

    def test_what_is_shown_is_identical_to_the_whole_read(self):
        ds = self._open(self.proc)
        for first, k in ((1, 6), (2, 1), (10, 3), (9, 5), (200, 6), (self.N_RECORDS - 2, 6),
                         (self.N_RECORDS, 1)):
            for by in ("reject", "habit"):
                with self.subTest(first=first, n=k, by=by):
                    self.assertSameStrip(
                        views.record_strip(self.image, ds, first, k, colour_by=by),
                        _old_record_strip(self.image, ds, first, k, colour_by=by))

    def test_records_with_no_particles_show_none(self):
        strip = views.record_strip(self.image, self._open(self.proc), 10, 3)
        self.assertEqual(strip.records, (10, 11, 12))
        self.assertEqual(strip.particles, ())

    def test_a_file_not_in_record_order_falls_back_to_the_whole_read(self):
        ds = self._open(self.unordered)
        for first in (1, 150, self.N_RECORDS - 1):
            with self.subTest(first=first):
                self.assertSameStrip(views.record_strip(self.image, ds, first, 4),
                                     _old_record_strip(self.image, ds, first, 4))

    def test_the_tracked_demo_reference_is_unchanged(self):
        im = self._open(DATA / "demo_flight_v314_image.cdf")
        pr = self._open(DATA / "demo_flight_v314_proc.nc")
        total = int(im.variables["data"].shape[0])
        for first in range(1, total + 1):
            for k in (1, 2, 6):
                with self.subTest(first=first, n=k):
                    self.assertSameStrip(views.record_strip(im, pr, first, k),
                                         _old_record_strip(im, pr, first, k))


if __name__ == "__main__":
    unittest.main()
