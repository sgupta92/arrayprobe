# SPDX-License-Identifier: BSD-3-Clause
"""The parallel DMT (CIP/PIP ``.cip``) decode must be byte-identical to serial.

``readers.dmt.read_binary_DMT_parallel`` is port-space speed work: opt-in,
default serial, no new dependency, and the byte-identity claim is these tests.
The planned tests are T1-T9
(this file carries T1 and T7 through a subprocess-bounded
real pool, gated behind ``ARRAYPROBE_SLOW``, and T2-T6 and T8 in process).

The in-process tests call the range worker and the merge directly, so every
split is checked without spawning; the one real-pool test runs in a
subprocess with a timeout, because a spawned-worker death on Windows makes
``ProcessPoolExecutor.map`` wait forever (the ``test_spec_parallel`` hang,
2026-09-11).
"""
from __future__ import annotations

import concurrent.futures
import concurrent.futures.process
import filecmp
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import warnings
from pathlib import Path
from unittest import mock

from tests._slow import slow

from arrayprobe.readers import dmt
from arrayprobe_uiops.spec_core import SpawnRetryWarning

FIXTURE = Path(__file__).resolve().parent / "data" / "dmt_raw_synthetic.cip"
REC = 4112
POOL_TIMEOUT_S = 300


def _serial(src: Path, out: Path):
    """Serial decode; returns (count, None) or (None, exception)."""
    try:
        return dmt.read_binary_DMT(src, out), None
    except Exception as exc:  # noqa: BLE001
        return None, exc


def _split_in_process(src: Path, out: Path, edges, tmp: Path, block=256):
    """Run the worker per range and the merge, all in this process."""
    parts = [
        dmt._decode_dmt_range((str(src), str(tmp / f"p{k:03d}"), lo, hi, block, 0))
        for k, (lo, hi) in enumerate(itertools.pairwise(edges))
    ]
    try:
        return dmt._merge_dmt_parts(parts, out, None, tail=(str(src), False)), None
    except Exception as exc:  # noqa: BLE001
        return None, exc


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dmtpar_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def assertSameFile(self, a: Path, b: Path):  # noqa: N802
        self.assertTrue(filecmp.cmp(a, b, shallow=False), f"{a} != {b}")


class FixtureIsWhatTheTestsAssume(unittest.TestCase):
    def test_fixture_is_twelve_whole_records(self):
        self.assertEqual(FIXTURE.stat().st_size, 12 * REC)
        self.assertEqual(dmt._n_decodable_records(FIXTURE), 12)


# Gated: 232 splits cost ~33 s (measured 2026-09-26, class run alone). The default run still
# checks in-process byte-identity through TailHandling, FailureParity, SpawnRetry and
# SyntheticMultiWindow (seams 255/256/257).
@slow
class EverySplitOfTheFixture(_Tmp):
    """T2: every contiguous split with 1-3 seams, plus one record per part.

    If any state crossed a record boundary, the twelve-part split would
    expose it.
    """

    def test_every_split_is_byte_identical(self):
        ref = self.tmp / "serial.nc"
        n, err = _serial(FIXTURE, ref)
        self.assertIsNone(err)
        self.assertEqual(n, 12)
        splits = [list(range(13))]
        for seams in (1, 2, 3):
            for cut in itertools.combinations(range(1, 12), seams):
                splits.append([0, *cut, 12])
        self.assertEqual(len(splits), 1 + 11 + 55 + 165)
        for i, edges in enumerate(splits):
            with self.subTest(edges=edges):
                out = self.tmp / f"par{i}.nc"
                got, perr = _split_in_process(FIXTURE, out, edges, self.tmp / f"w{i}")
                self.assertIsNone(perr)
                self.assertEqual(got, 12)
                self.assertSameFile(ref, out)
                out.unlink()

    def test_small_spill_block_is_byte_identical(self):
        """Spilling every 1, 5 and 256 records changes nothing written."""
        ref = self.tmp / "serial.nc"
        _serial(FIXTURE, ref)
        for block in (1, 5, 256):
            with self.subTest(block=block):
                out = self.tmp / f"b{block}.nc"
                _split_in_process(FIXTURE, out, [0, 7, 12], self.tmp / f"wb{block}",
                                  block=block)
                self.assertSameFile(ref, out)


class TailHandling(_Tmp):
    """T4: a ragged tail ends the file the way serial does.

    Under 20 bytes the EOF probe ends the run; a 4111-byte tail is a record
    with a 4095-byte payload and decodes; 20 to 4110 bytes die at
    ``read_binary_DMT.m:109``. Octave-measured
    (``tests/test_reader_edge_octave.py::DmtAgainstOctave``).
    """

    def test_trailing_bytes(self):
        from arrayprobe.matlab_compat import MatlabIndexError
        raw = FIXTURE.read_bytes()
        for extra, want in ((0, 12), (15, 12), (16, 12), (19, 12), (20, None),
                            (2000, None), (4111, 13)):
            with self.subTest(extra=extra):
                src = self.tmp / f"tail{extra}.cip"
                src.write_bytes(raw + raw[:extra])
                self.assertEqual(dmt._n_decodable_records(src), 12)
                ref = self.tmp / f"s{extra}.nc"
                n, err = _serial(src, ref)
                out = self.tmp / f"p{extra}.nc"
                got, perr = _split_in_process(src, out, [0, 5, 12], self.tmp / f"w{extra}")
                if want is None:
                    self.assertIsInstance(err, MatlabIndexError)
                    self.assertIsInstance(perr, MatlabIndexError)
                    self.assertEqual(str(perr), str(err))
                else:
                    self.assertIsNone(err)
                    self.assertEqual(n, want)
                    self.assertEqual(got, n)
                self.assertSameFile(ref, out)


class FailureParity(_Tmp):
    """T5: a record that cannot be decoded fails the same way in both paths."""

    def _bad_record(self) -> bytes:
        raw = FIXTURE.read_bytes()
        bad = raw[:16] + bytes(4096)
        probe = self.tmp / "probe.cip"
        probe.write_bytes(bad)
        _, err = _serial(probe, self.tmp / "probe.nc")
        if err is None:
            self.skipTest("an all-zero payload decodes; need another bad record")
        return bad

    def _file_with_bad(self, at: list[int]) -> Path:
        raw = FIXTURE.read_bytes()
        bad = self._bad_record()
        recs = [raw[i * REC:(i + 1) * REC] for i in range(12)]
        for k in at:
            recs[k] = bad
        src = self.tmp / ("bad_" + "_".join(map(str, at)) + ".cip")
        src.write_bytes(b"".join(recs))
        return src

    def _check(self, src: Path, edges):
        ref = self.tmp / (src.stem + "_s.nc")
        _, serr = _serial(src, ref)
        self.assertIsNotNone(serr)
        out = self.tmp / (src.stem + "_p.nc")
        _, perr = _split_in_process(src, out, edges, self.tmp / (src.stem + "_w"))
        self.assertIsNotNone(perr)
        self.assertIs(type(perr), type(serr))
        self.assertEqual(str(perr), str(serr))
        self.assertSameFile(ref, out)

    def test_one_bad_record_in_the_second_part(self):
        self._check(self._file_with_bad([6]), [0, 4, 8, 12])

    def test_lowest_failing_record_wins(self):
        self._check(self._file_with_bad([9, 5]), [0, 4, 8, 12])


class Delegation(_Tmp):
    """T6: one job, or a file of at most one record, is the serial function."""

    def test_one_job_calls_the_serial_function(self):
        with mock.patch.object(dmt, "read_binary_DMT", return_value=12) as m:
            self.assertEqual(
                dmt.read_binary_DMT_parallel(FIXTURE, self.tmp / "o.nc", jobs=1), 12)
        m.assert_called_once()

    def test_one_record_file_delegates(self):
        src = self.tmp / "one.cip"
        src.write_bytes(FIXTURE.read_bytes()[:REC + 30])
        with mock.patch.object(dmt, "read_binary_DMT", return_value=1) as m:
            dmt.read_binary_DMT_parallel(src, self.tmp / "o.nc", jobs=4)
        m.assert_called_once()

    def test_progress_sequence_equals_serial(self):
        seen_s: list[int] = []
        seen_p: list[int] = []
        dmt.read_binary_DMT(FIXTURE, self.tmp / "s.nc", progress=seen_s.append)
        parts = [
            dmt._decode_dmt_range((str(FIXTURE), str(self.tmp / f"q{k}"), lo, hi, 256, 0))
            for k, (lo, hi) in enumerate(((0, 5), (5, 12)))
        ]
        dmt._merge_dmt_parts(parts, self.tmp / "p.nc", seen_p.append)
        self.assertEqual(seen_s, seen_p)
        self.assertEqual(seen_s, list(range(1, 13)))


N_SYNTH = 620


def _synthetic(tmp: Path) -> Path:
    """T3's file: the fixture's twelve records tiled to 620 (> two 256 blocks)."""
    raw = FIXTURE.read_bytes()
    recs = [raw[i * REC:(i + 1) * REC] for i in range(12)]
    src = tmp / "synth.cip"
    src.write_bytes(b"".join(recs[i % 12] for i in range(N_SYNTH)))
    return src


def _pool_driver(tmp: Path) -> Path:
    script = textwrap.dedent("""
        import sys
        from arrayprobe.readers import dmt
        src, out, jobs, wd = sys.argv[1:5]
        if __name__ == "__main__":
            print(dmt.read_binary_DMT_parallel(src, out, jobs=int(jobs), workdir=wd))
    """)
    driver = tmp / "drive.py"
    driver.write_text(script, encoding="utf-8")
    return driver


def _run_pool(tc, driver: Path, src: Path, out: Path, jobs: int, wd: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(driver), str(src), str(out), str(jobs), str(wd)],
        capture_output=True, text=True, timeout=POOL_TIMEOUT_S, env=dict(os.environ))
    tc.assertEqual(proc.returncode, 0, proc.stderr)
    return proc.stdout.strip()


class SyntheticMultiWindow(_Tmp):
    """T3: a 620-record file with seams straddling the 256-record flush."""

    def test_the_file_exercises_what_it_claims(self):
        src = _synthetic(self.tmp)
        self.assertEqual(dmt._n_decodable_records(src), N_SYNTH)
        self.assertGreater(N_SYNTH, 2 * 256)

    def test_seams_at_the_flush_boundary_are_byte_identical(self):
        src = _synthetic(self.tmp)
        ref = self.tmp / "serial.nc"
        n, err = _serial(src, ref)
        self.assertIsNone(err)
        self.assertEqual(n, N_SYNTH)
        for seam in (255, 256, 257):
            for edges in ([0, seam, N_SYNTH], [0, seam, 2 * seam, N_SYNTH]):
                with self.subTest(edges=edges):
                    out = self.tmp / f"s{len(edges)}_{seam}.nc"
                    got, perr = _split_in_process(
                        src, out, edges, self.tmp / f"w{len(edges)}_{seam}")
                    self.assertIsNone(perr)
                    self.assertEqual(got, N_SYNTH)
                    self.assertSameFile(ref, out)
                    out.unlink()


class _FakePool:
    """Stands in for ProcessPoolExecutor: dies once, then maps in process."""

    calls = 0

    def __init__(self, max_workers=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, tasks):
        type(self).calls += 1
        if type(self).calls == 1:
            raise concurrent.futures.process.BrokenProcessPool("killed once")
        return [fn(t) for t in tasks]


class SpawnRetry(_Tmp):
    """T8: a pool that dies once retries with SpawnRetryWarning, same bytes."""

    def test_pool_killed_once_retries_and_matches(self):
        ref = self.tmp / "serial.nc"
        _serial(FIXTURE, ref)
        _FakePool.calls = 0
        out = self.tmp / "retry.nc"
        with (mock.patch.object(concurrent.futures, "ProcessPoolExecutor", _FakePool),
              mock.patch("time.sleep"),
              warnings.catch_warnings(record=True) as caught):
            warnings.simplefilter("always")
            n = dmt.read_binary_DMT_parallel(FIXTURE, out, jobs=3, workdir=self.tmp)
        self.assertEqual(n, 12)
        self.assertEqual(_FakePool.calls, 2)
        self.assertEqual(
            [w.category for w in caught if issubclass(w.category, SpawnRetryWarning)],
            [SpawnRetryWarning])
        self.assertSameFile(ref, out)

    def test_retries_exhausted_reraises(self):
        class _AlwaysDies(_FakePool):
            def map(self, fn, tasks):
                raise concurrent.futures.process.BrokenProcessPool("always")
        with (mock.patch.object(concurrent.futures, "ProcessPoolExecutor", _AlwaysDies),
              mock.patch("time.sleep"), warnings.catch_warnings()):
            warnings.simplefilter("ignore")
            with self.assertRaises(concurrent.futures.process.BrokenProcessPool):
                dmt.read_binary_DMT_parallel(FIXTURE, self.tmp / "x.nc", jobs=2,
                                             workdir=self.tmp, spawn_retries=1)


@slow
class SyntheticMultiWindowThroughAPool(_Tmp):
    """T7: T3's file through a real spawned pool, bounded by a subprocess timeout."""

    def test_pool_jobs_3(self):
        src = _synthetic(self.tmp)
        ref = self.tmp / "serial.nc"
        _serial(src, ref)
        out = self.tmp / "pool3.nc"
        got = _run_pool(self, _pool_driver(self.tmp), src, out, 3, self.tmp)
        self.assertEqual(got, str(N_SYNTH))
        self.assertSameFile(ref, out)


@slow
class ParallelMatchesSerialThroughAPool(_Tmp):
    """T1: a real spawned pool, bounded by a subprocess timeout."""

    def test_pool_jobs_2_3_4(self):
        ref = self.tmp / "serial.nc"
        _serial(FIXTURE, ref)
        script = textwrap.dedent("""
            import sys
            from arrayprobe.readers import dmt
            src, out, jobs, wd = sys.argv[1:5]
            if __name__ == "__main__":
                print(dmt.read_binary_DMT_parallel(src, out, jobs=int(jobs), workdir=wd))
        """)
        driver = self.tmp / "drive.py"
        driver.write_text(script, encoding="utf-8")
        for jobs in (2, 3, 4):
            with self.subTest(jobs=jobs):
                out = self.tmp / f"pool{jobs}.nc"
                proc = subprocess.run(
                    [sys.executable, str(driver), str(FIXTURE), str(out), str(jobs),
                     str(self.tmp)],
                    capture_output=True, text=True, timeout=POOL_TIMEOUT_S,
                    env=dict(os.environ))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout.strip(), "12")
                self.assertSameFile(ref, out)

# _release_fixture_guard: real-data derived fixtures are excluded from the release
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402

_RFG_EXCLUDED = ('dmt_raw_synthetic.cip',)
if not all((_rfg_pathlib.Path(__file__).resolve().parent / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "real-data derived fixtures (UIOPS PECAN DMT / minimal-example 2D-S samples) "
        "are not shipped in the release")

if __name__ == "__main__":
    unittest.main()
