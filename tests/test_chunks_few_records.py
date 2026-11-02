# SPDX-License-Identifier: BSD-3-Clause
"""``--chunks N`` on a file with few records (measured defect, 2026-10-18).

``arrayprobe run ... --chunks 4`` on a 5-record decode raised ``IndexError`` in
``arrayprobe_uiops.imgproc._scan_seam_states``: ``stage3`` took
``n_every = ceil(5/4) = 2`` but kept four chunks, so chunk 4 started at record 7,
past the file, and the seam scan indexed a header row that does not exist.

The driver now derives the chunk count from ``n_every``
(:func:`arrayprobe.driver.run_flight._chunk_plan`), so no chunk is empty and
``n_every`` -- the only number a chunk worker's records depend on -- is what it
always was.  The scan refuses a stop past the file with a ``ValueError`` naming
it, rather than an ``IndexError``.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe.driver.run_flight import _chunk_plan
from arrayprobe_uiops.imgproc import chunk_primes_v35

SPEC_INPUT = Path(__file__).resolve().parent / "data" / "2DS_s3_input_fixture.nc"  # 25 records


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: 2DS_s3_input_fixture.nc is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "2DS_s3_input_fixture.nc").exists():
    raise unittest.SkipTest(
        "2DS_s3_input_fixture.nc is not distributed with the package")


class TestChunkPlanLeavesNoChunkEmpty(unittest.TestCase):
    def test_every_chunk_starts_inside_the_file_and_together_they_cover_it(self):
        for n_records in range(1, 41):
            for requested in range(1, 13):
                with self.subTest(n_records=n_records, chunks=requested):
                    n_every, chunks = _chunk_plan(n_records, requested)
                    self.assertEqual(n_every, -(-n_records // requested))
                    self.assertTrue(1 <= chunks <= requested)
                    self.assertLessEqual((chunks - 1) * n_every + 1, n_records)
                    self.assertGreaterEqual(chunks * n_every, n_records)

    def test_the_measured_case_five_records_four_chunks_becomes_three(self):
        self.assertEqual(_chunk_plan(5, 4), (2, 3))

    def test_a_plan_with_no_empty_chunk_is_unchanged(self):
        # Any request that worked before keeps its chunk count and n_every.
        for n_records in range(1, 41):
            for requested in range(1, 13):
                n_every = -(-n_records // requested)
                old = min(requested, n_records) or 1
                if (old - 1) * n_every + 1 <= n_records:
                    self.assertEqual(_chunk_plan(n_records, requested), (n_every, old))

    def test_zero_records_is_one_chunk(self):
        self.assertEqual(_chunk_plan(0, 4)[1], 1)


class TestSeamScanRefusesAStopPastTheFile(unittest.TestCase):
    def test_a_chunk_starting_past_the_last_record_is_a_value_error(self):
        # 25 records, n_every=3, 10 chunks: chunk 10 would start at record 28.
        with self.assertRaisesRegex(ValueError, "past the file"):
            chunk_primes_v35(str(SPEC_INPUT), "2DS", 3, 10,
                             tas_time=np.array([]), tas=np.array([]))

    def test_a_chunk_starting_one_past_the_last_record_is_a_value_error(self):
        # 25 records, n_every=5, 6 chunks: chunk 6 would start at record 26, which
        # the scan reads up to without error, and holds no records.
        with self.assertRaisesRegex(ValueError, "past the file"):
            chunk_primes_v35(str(SPEC_INPUT), "2DS", 5, 6,
                             tas_time=np.array([]), tas=np.array([]))

    def test_an_empty_file_gets_one_chunk_and_no_prime(self):
        # A decoded file with no records: _chunk_plan(0, N) gives one chunk, and its
        # prime is None, as for any first chunk. Refusing it would advise fewer chunks
        # than one.
        import tempfile

        import netCDF4

        self.assertEqual(_chunk_plan(0, 10)[1], 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.nc"
            with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as d:
                d.createDimension("time", 0)
                d.createVariable("data", "i2", ("time",))   # a decoded file's image variable
            primes = chunk_primes_v35(str(path), "2DS", 1, 1,
                                      tas_time=np.array([]), tas=np.array([]))
        self.assertEqual(primes, [None])

    def test_a_chunk_starting_on_the_last_record_is_accepted(self):
        # 25 records, n_every=4, 7 chunks: chunk 7 starts at record 25, the last.
        primes = chunk_primes_v35(str(SPEC_INPUT), "2DS", 4, 7,
                                  tas_time=np.array([]), tas=np.array([]))
        self.assertEqual(len(primes), 7)

    def test_a_plan_from_the_driver_scans_cleanly(self):
        n_every, chunks = _chunk_plan(25, 10)
        primes = chunk_primes_v35(str(SPEC_INPUT), "2DS", n_every, chunks,
                                  tas_time=np.array([]), tas=np.array([]))
        self.assertEqual(len(primes), chunks)
        self.assertIsNone(primes[0])


if __name__ == "__main__":
    unittest.main()
