# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.tune.diodes``: stuck diodes from a proc file's ``bin_stats``, on synthetic files.

Pins the lit path (ORACLES-profile stamp), the shadowed path (v3.5 stamp, ``lit = S - shadow``
with ``S`` from ``position``), a case where the unconverted shadow count would flag the wrong
diodes, the high-count (``mean``) branch, and what an unstamped file is read as.  Every expected
number is worked from the synthetic counts below; no real flight file is read.
"""
from __future__ import annotations

import io
import logging
import subprocess
import sys
import tempfile
import tomllib
import unittest
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from unittest import mock

import numpy as np
from netCDF4 import Dataset

from arrayprobe.tune import diodes
from arrayprobe_uiops import diode_mask

#: The out-of-process worker test's bound: the code's own 120 s pool wait, plus spawn and import.
_WORKER_TIMEOUT_S = 240


def _write_proc(path: Path, bin_stats, position=None, stamp: str | None = None) -> Path:
    with Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("pos_count", 2)
        ds.createDimension("bin_count", len(bin_stats))
        ds.createVariable("bin_stats", "i4", ("bin_count",))[:] = np.asarray(bin_stats)
        if position is not None:
            pos = np.asarray(position, dtype=np.int16)
            ds.createVariable("position", "i2", ("time", "pos_count"))[:pos.shape[0], :] = pos
    if stamp is not None:
        path.with_name(path.name + ".call").write_text(stamp + "\n", encoding="utf-8")
    return path


# 128 diodes. Shadowed: 200 on most, 100 on diodes 1 and 128, 950 on diode 60 (stuck dark).
# Ten particles of 100 slices each, so S = 1000 and lit = 800, 900 and 50.
SHADOW = np.full(128, 200)
SHADOW[[0, 127]] = 100
SHADOW[59] = 950
POSITION = [(1, 100)] * 10
S = 1000


class LitPath(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_oracles_profile_counts_are_used_as_they_are(self):
        lit = S - SHADOW
        f = _write_proc(self.tmp / "p.cdf", lit, POSITION,
                        "engine=3.1.4 profile=oracles-production channels=H")
        rep = diodes.report(f)
        self.assertFalse(rep["shadowed"])
        self.assertIsNone(rep["S"])
        self.assertEqual(rep["flagged"], [60])
        self.assertEqual(rep["branch"], "max")
        self.assertEqual(rep["threshold"], 720.0)          # int32(0.80 * 900)
        self.assertEqual(rep["rule_source"], diodes.RULE_SOURCE["max"])
        rule = diode_mask.stuck_diodes(lit)
        self.assertEqual(rep["flagged"], [int(d) for d in rule.shadow_diode])
        d60 = rep["per_diode"][59]
        self.assertEqual((d60["lit"], d60["flagged"]), (50, True))
        self.assertAlmostEqual(d60["fraction_of_max"], 50 / 900)

    def test_fractions_are_the_rule_module_constants(self):
        rep = diodes.report_from_counts(S - SHADOW)
        self.assertIs(rep["stuck_fraction"], diode_mask.STUCK_FRACTION)
        self.assertIs(rep["high_fraction"], diode_mask.HIGH_FRACTION)


class ShadowedPath(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_v35_counts_are_converted_and_lit_plus_shadow_is_S(self):
        f = _write_proc(self.tmp / "p.cdf", SHADOW, POSITION, "engine=3.5 profile=stock-v3.5")
        rep = diodes.report(f)
        self.assertTrue(rep["shadowed"])
        self.assertEqual(rep["S"], S)
        self.assertEqual(rep["image_slice_offset"], 0)
        lit = [d["lit"] for d in rep["per_diode"]]
        self.assertTrue(all(a + b == S for a, b in zip(lit, SHADOW, strict=True)))
        self.assertEqual(rep["flagged"], [60])

    def test_unconverted_shadow_count_would_flag_the_wrong_diodes(self):
        wrong = diode_mask.stuck_diodes(SHADOW)
        self.assertEqual([int(d) for d in wrong.shadow_diode], [1, 128])
        self.assertEqual([int(d) for d in wrong.ill_diode], [60])
        f = _write_proc(self.tmp / "p.cdf", SHADOW, POSITION, "engine=3.5 profile=stock-v3.5")
        self.assertEqual(diodes.report(f)["flagged"], [60])

    def test_stock_v314_profile_is_shadowed_too(self):
        f = _write_proc(self.tmp / "p.cdf", SHADOW, POSITION, "engine=3.1.4 profile=stock-v3.1.4")
        rep = diodes.report(f)
        self.assertTrue(rep["shadowed"])
        self.assertEqual(rep["flagged"], [60])

    def test_slice_offset_is_subtracted_per_particle(self):
        lit, total = diodes.lit_counts([10, 20], shadowed=True, position=[(1, 100), (5, 54)],
                                       offset=1)
        self.assertEqual(total, 99 + 49)
        self.assertEqual(list(lit), [138, 128])

    def test_offset_from_probe_or_from_an_unambiguous_width(self):
        self.assertEqual(diodes.slice_offset(32, "2DC")[0], 1)
        self.assertEqual(diodes.slice_offset(128)[0], 0)
        with self.assertRaises(diodes.DiodeReportError):
            diodes.slice_offset(128, "no-such-probe")

    def test_a_shadow_count_above_S_is_refused(self):
        f = _write_proc(self.tmp / "p.cdf", SHADOW, [(1, 100)], "engine=3.5 profile=stock-v3.5")
        with self.assertRaises(diodes.DiodeReportError):
            diodes.report(f)

    def test_no_position_is_refused_for_a_shadow_count(self):
        f = _write_proc(self.tmp / "p.cdf", SHADOW, None, "engine=3.5 profile=stock-v3.5")
        with self.assertRaises(diodes.DiodeReportError):
            diodes.report(f)


class BlockwiseSliceTotal(unittest.TestCase):
    """``S`` read from a file in blocks equals the whole-array sum, tail and workers included."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        rng = np.random.default_rng(20261001)
        start = rng.integers(1, 1600, size=10_007)
        self.pos = np.stack([start, start + rng.integers(0, 100, size=start.size)], axis=1)
        self.f = _write_proc(self.tmp / "p.cdf", SHADOW, self.pos)

    def _straight(self, offset):
        pos = self.pos.astype(np.int64)
        return int(np.sum(pos[:, 1] - pos[:, 0] + 1 - offset))

    def test_blocks_with_an_uneven_tail_sum_to_the_straight_total(self):
        for offset in (0, 1):
            for block_rows in (1, 7, 1000, 10_006, 10_007, 50_000):
                with self.subTest(offset=offset, block_rows=block_rows):
                    self.assertEqual(
                        diodes.position_slice_total(self.f, offset, block_rows=block_rows,
                                                    jobs=1),
                        self._straight(offset))

    def test_worker_processes_sum_to_the_straight_total(self):
        # Run out of process, bounded: on 2026-10-28 this call hung a detached full suite for
        # 16 min with no worker left and no CPU used, past _parallel_total's own 120 s wait,
        # while the module alone passed in 5 s. The subprocess dumps its stacks before the
        # timeout, so a hang fails here by name (test_spec_parallel.py's pattern).
        child = ("import faulthandler, sys\n"
                 "faulthandler.dump_traceback_later(float(sys.argv[2]), exit=False)\n"
                 "from arrayprobe.tune import diodes\n"
                 "print(diodes.position_slice_total(sys.argv[1], 1, block_rows=999, jobs=2))\n")
        try:
            done = subprocess.run([sys.executable, "-c", child, str(self.f),
                                   str(_WORKER_TIMEOUT_S - 15)],
                                  capture_output=True, text=True, timeout=_WORKER_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            err = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (
                exc.stderr or "")
            self.fail(f"the parallel read hung past {_WORKER_TIMEOUT_S} s; child stacks:\n"
                      f"{err[-3000:]}")
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertEqual(int(done.stdout.strip().splitlines()[-1]), self._straight(1))

    def test_lit_counts_from_a_total_equal_lit_counts_from_position(self):
        a = diodes.lit_counts(SHADOW, shadowed=True, position=self.pos, offset=1)
        b = diodes.lit_counts(SHADOW, shadowed=True, offset=1,
                              total=diodes.position_slice_total(self.f, 1, block_rows=333))
        self.assertEqual(a[1], b[1])
        self.assertTrue(np.array_equal(a[0], b[0]))

    def test_a_file_without_position_gives_none(self):
        f = _write_proc(self.tmp / "q.cdf", SHADOW, None)
        self.assertIsNone(diodes.position_slice_total(f, 0))


class _FakePool:
    """A stand-in for ``ProcessPoolExecutor``: no process is started."""

    instances: list = []

    def __init__(self, max_workers=None, *, submit=None):
        self.max_workers = max_workers
        self._submit = submit
        self.shutdown_calls: list = []
        _FakePool.instances.append(self)

    def submit(self, fn, *args):
        return self._submit(fn, *args)

    def shutdown(self, wait=True, *, cancel_futures=False):
        self.shutdown_calls.append((wait, cancel_futures))


def _fake_pool(submit):
    _FakePool.instances = []
    return mock.patch("concurrent.futures.ProcessPoolExecutor",
                      lambda max_workers=None: _FakePool(max_workers, submit=submit))


class ParallelReadFailsSafe(unittest.TestCase):
    """A pool that dies at spawn, breaks or stalls falls back to the serial read, same ``S``."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        rng = np.random.default_rng(20261002)
        start = rng.integers(1, 1600, size=5_003)
        pos = np.stack([start, start + rng.integers(0, 100, size=start.size)], axis=1)
        self.f = _write_proc(self.tmp / "p.cdf", SHADOW, pos)
        self.serial = diodes.position_slice_total(self.f, 1, block_rows=500, jobs=1)

    def _run(self, submit):
        err = io.StringIO()
        handler = logging.StreamHandler(err)
        log = logging.getLogger("arrayprobe.tune.diodes")
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)
        with (_fake_pool(submit),
              mock.patch.object(diodes, "_parallel_timeout", lambda *a: 0.05)):
            total = diodes.position_slice_total(self.f, 1, block_rows=500, jobs=3)
        return total, err.getvalue()

    def _assert_fell_back(self, total, err, why):
        self.assertEqual(total, self.serial)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertIn("reading it serially", err)
        self.assertIn(why, err)
        self.assertEqual(_FakePool.instances[0].shutdown_calls, [(False, True)])

    def test_winerror_6_at_spawn_falls_back(self):
        def submit(fn, *args):
            raise OSError(6, "The handle is invalid")
        self._assert_fell_back(*self._run(submit), "The handle is invalid")

    def test_a_broken_pool_falls_back(self):
        def submit(fn, *args):
            f = Future()
            f.set_exception(BrokenProcessPool("a child process terminated abruptly"))
            return f
        self._assert_fell_back(*self._run(submit), "BrokenProcessPool")

    def test_workers_that_never_answer_time_out_and_fall_back(self):
        self._assert_fell_back(*self._run(lambda fn, *args: Future()), "no result within")

    def test_a_working_pool_is_used_and_shut_down_normally(self):
        def submit(fn, *args):
            f = Future()
            f.set_result(fn(*args))
            return f
        total, err = self._run(submit)
        self.assertEqual(total, self.serial)
        self.assertEqual(err, "")
        self.assertEqual(_FakePool.instances[0].shutdown_calls, [(True, False)])

    def test_a_worker_error_that_is_not_a_pool_failure_propagates(self):
        def submit(fn, *args):
            f = Future()
            f.set_exception(ValueError("bad block"))
            return f
        with self.assertRaisesRegex(ValueError, "bad block"):
            self._run(submit)

    def test_jobs_1_never_constructs_a_pool(self):
        with mock.patch("concurrent.futures.ProcessPoolExecutor") as pool:
            self.assertEqual(diodes.position_slice_total(self.f, 1, block_rows=500, jobs=1),
                             self.serial)
        pool.assert_not_called()

    def test_the_timeout_is_per_block_with_a_floor(self):
        # 17.8 M rows, 8 workers, 1 M-row blocks: 3 blocks x 1 M rows x 200 us = 600 s.
        self.assertAlmostEqual(diodes._parallel_timeout(17_800_000, 8, 1_000_000), 600.0)
        self.assertEqual(diodes._parallel_timeout(10_000, 2, 500),
                         diodes.PARALLEL_TIMEOUT_FLOOR_S)


class HighBranch(unittest.TestCase):
    def test_a_diode_masked_in_flight_switches_to_the_mean_rule(self):
        # 32 diodes: 30 at 1000, diode 7 lit on every slice (2000), diode 20 at 700.
        # mean 1021.9 -> diode 7 over 1.2 x mean; replaced by int32(30700/32) = 959;
        # mean then 31659/32 = 989.3, threshold 791.5 -> diode 20 flagged.
        lit = np.full(32, 1000)
        lit[6], lit[19] = 2000, 700
        rep = diodes.report_from_counts(lit)
        self.assertEqual(rep["branch"], "mean")
        self.assertEqual(rep["ill_diode"], [7])
        self.assertEqual(rep["flagged"], [20])
        self.assertAlmostEqual(rep["threshold"], 0.80 * 31659 / 32)
        self.assertEqual(rep["per_diode"][6]["saved"], 959)
        self.assertEqual(rep["rule_source"], diodes.RULE_SOURCE["mean"])


class Provenance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_unstamped_file_is_read_as_v314_and_needs_a_profile(self):
        f = _write_proc(self.tmp / "p.cdf", S - SHADOW, POSITION)
        with self.assertRaises(diodes.DiodeReportError):
            diodes.report(f)
        rep = diodes.report(f, profile="oracles-2016")
        self.assertEqual(rep["engine"], "3.1.4")
        self.assertEqual(rep["engine_source"], "no stamp: read as v3.1.4")
        self.assertFalse(rep["shadowed"])
        self.assertEqual(rep["flagged"], [60])

    def test_a_stamp_with_no_engine_key_is_read_as_v314(self):
        f = _write_proc(self.tmp / "p.cdf", S - SHADOW, POSITION, "profile=oracles-production")
        conv = diodes.counting_convention(f)
        self.assertEqual((conv["engine"], conv["shadowed"]), ("3.1.4", False))

    def test_a_profile_contradicting_the_stamp_is_refused(self):
        f = _write_proc(self.tmp / "p.cdf", S - SHADOW, POSITION,
                        "engine=3.1.4 profile=oracles-production")
        with self.assertRaises(diodes.DiodeReportError):
            diodes.counting_convention(f, "stock-v3.1.4")

    def test_soda2_is_refused(self):
        f = _write_proc(self.tmp / "p.cdf", S - SHADOW, POSITION, '{"engine": "soda2"}')
        with self.assertRaises(diodes.DiodeReportError):
            diodes.counting_convention(f)

    def test_in_file_attributes_are_read_when_there_is_no_sidecar(self):
        f = _write_proc(self.tmp / "p.cdf", SHADOW, POSITION)
        with Dataset(f, "a") as ds:
            ds.setncattr("arrayprobe_engine", "3.5")
            ds.setncattr("arrayprobe_profile", "stock-v3.5")
        self.assertTrue(diodes.counting_convention(f)["shadowed"])


class TomlLine(unittest.TestCase):
    def test_the_line_loads_as_the_masking_table(self):
        doc = tomllib.loads(diodes.toml_line("base160910124240", [95]))
        self.assertEqual(doc, {"masking": {"diodes": {"base160910124240": [95]}}})

    def test_summary_names_the_flagged_diode(self):
        rep = diodes.report_from_counts(S - SHADOW)
        rep.update(proc="p.cdf", engine="3.5", engine_source="stamp", profile=None,
                   counts="lit", S=None)
        text = "\n".join(diodes.summary_lines(rep))
        self.assertIn("flagged: [60]", text)


if __name__ == "__main__":
    unittest.main()
