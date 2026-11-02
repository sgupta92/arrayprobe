# SPDX-License-Identifier: BSD-3-Clause
"""P10, 2026-09-13: the ``--chunks`` parent no longer waits forever.

An overnight incident was root-caused: a
real overnight incident: the 0704/H chunk-1 worker deadlocked inside a DLL
load (numba's lazy first-call JIT pulling in ``scipy.linalg.lapack`` on the
chunk's first particle), and ``run_flight.py``'s ``stage3()`` waited on a bare
``proc.wait()`` -- no timeout, no liveness check -- for 6 h 25 min before
anyone noticed. This file is the regression coverage for the fix: a bounded,
fail-closed ``_await_workers`` (stall watchdog on the worker's own log
growth, tree-kill via ``_kill_tree``) plus a completion record
(``<chunk>.done``) ``stage3`` refuses to merge without.

``run_parallel()`` (``--jobs``) was converted to the same bounded wait the
same day (pair G): ``tests/test_run_flight_jobs_watchdog.py``.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._slow import slow

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402

_TOOLS = Path(__file__).resolve().parent.parent / "scripts"

_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", _TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules["make_demo_flight"] = make_demo_flight
_DEMO_SPEC.loader.exec_module(make_demo_flight)
_build_raw_flight = make_demo_flight.build_demo_flight

_SPEC = importlib.util.spec_from_file_location("run_flight", _TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)

DATA = Path(__file__).parent / "data"
INPUT = DATA / "2DS_s3_input_fixture.nc"

NONDETERMINISTIC_ATTRS = frozenset({"Creation Time", "Image Source"})


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: 2DS_s3_input_fixture.nc is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "2DS_s3_input_fixture.nc").exists():
    raise unittest.SkipTest(
        "2DS_s3_input_fixture.nc is not distributed with the package")


def _record_count(path) -> int:
    with netCDF4.Dataset(path) as ds:
        return len(ds.dimensions["time"])


def _pid_is_running(pid: int) -> bool:
    """Windows: ``tasklist`` sees native processes MSYS ``ps -ef`` does not
    (the exact blind spot §1c of the P10 plan names). POSIX: ``kill(pid, 0)``,
    with a zombie (killed, not yet reaped -- state ``Z`` in ``/proc``) read as
    gone, since it holds no CPU and cannot write another byte."""
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, check=False)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("State:"):
                return not line.split()[1].startswith("Z")
    return True


class _FakeProc:
    """A ``Popen``-shaped stub: only ``poll()``/``wait()``/``pid`` are used
    by ``_await_workers`` when the real process is never actually spawned."""

    def __init__(self, rc=0, pid=999999):
        self._rc = rc
        self.pid = pid

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        return self._rc


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
@slow  # real subprocess chunk workers (2026-09-14: ~10.0s measured)
class AwaitWorkersTests(unittest.TestCase):
    """Direct tests of ``_await_workers``/``_kill_tree`` against real
    subprocesses -- no flight data needed, no Octave."""

    def _spawn(self, tmp: Path, label: str, body: str):
        script = tmp / f"{label.replace(' ', '_')}.py"
        script.write_text(body)
        log_path = tmp / f"{label.replace(' ', '_')}.log"
        log_f = open(log_path, "w")
        proc = subprocess.Popen([sys.executable, str(script)],
                                stdout=log_f, stderr=subprocess.STDOUT)
        return label, proc, log_f, log_path

    def test_a_wedged_worker_fails_the_parent_fast_and_leaves_no_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pidfile = tmp / "pid.txt"
            body = (
                "import os, sys, time\n"
                "sys.stdout.write('started\\n'); sys.stdout.flush()\n"
                f"open(r'{pidfile}', 'w').write(str(os.getpid()))\n"
                "time.sleep(3600)\n"
            )
            worker = self._spawn(tmp, "chunk 1", body)
            # The pidfile write races the parent's first poll -- give it a
            # moment before asserting on it, but the watchdog itself must
            # still fire within the 15 s this test bounds either way.
            import time as _t
            deadline = _t.monotonic() + 5
            while not pidfile.exists() and _t.monotonic() < deadline:
                _t.sleep(0.1)
            t0 = _t.monotonic()
            with self.assertRaises(RuntimeError) as ctx:
                run_flight._await_workers([worker], stall_s=3, poll_s=0.5, what="TEST")
            elapsed = _t.monotonic() - t0
            self.assertLess(elapsed, 15, "the watchdog must fire well inside its budget")
            self.assertIn("stalled", str(ctx.exception))
            self.assertIn("chunk 1", str(ctx.exception))
            self.assertTrue(worker[3].exists(), "the log is kept, not deleted, on failure")
            self.assertTrue(pidfile.exists(), "the worker got far enough to record its pid")
            pid = int(pidfile.read_text())
            self.assertFalse(
                _pid_is_running(pid),
                f"pid {pid} (the real interpreter, possibly a grandchild of the "
                "venv launcher pid -- P10 measured PID 100536 -> 61876 on this "
                "machine) must be gone after _kill_tree's taskkill /T")

    def test_a_sibling_is_killed_when_one_worker_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            failer = self._spawn(tmp, "worker A",
                                 "import sys; sys.stdout.write('x\\n'); sys.exit(2)\n")
            pidfile = tmp / "pid_b.txt"
            sleeper = self._spawn(tmp, "worker B", (
                "import os, sys, time\n"
                "sys.stdout.write('x\\n'); sys.stdout.flush()\n"
                f"open(r'{pidfile}', 'w').write(str(os.getpid()))\n"
                "time.sleep(3600)\n"
            ))
            import time as _t
            deadline = _t.monotonic() + 5
            while not pidfile.exists() and _t.monotonic() < deadline:
                _t.sleep(0.1)
            with self.assertRaises(RuntimeError) as ctx:
                run_flight._await_workers([failer, sleeper], stall_s=60,
                                          poll_s=0.2, what="TEST")
            msg = str(ctx.exception)
            self.assertIn("worker A", msg)
            self.assertIn("exit 2", msg)
            self.assertNotIn("worker B", msg,
                            "a killed sibling is not itself reported as failed")
            if pidfile.exists():
                pid = int(pidfile.read_text())
                self.assertFalse(_pid_is_running(pid),
                                "the sibling is killed too, not left running")

    def test_stall_zero_is_the_old_unbounded_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            worker = self._spawn(tmp, "w1", "import time; time.sleep(2)\n")
            rcs = run_flight._await_workers([worker], stall_s=0, poll_s=0.2, what="TEST")
            self.assertEqual(rcs, {"w1": 0})

    def test_all_succeed_returns_every_rc(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            w1 = self._spawn(tmp, "w1", "print('ok')\n")
            w2 = self._spawn(tmp, "w2", "print('ok')\n")
            rcs = run_flight._await_workers([w1, w2], stall_s=30, poll_s=0.1, what="TEST")
            self.assertEqual(rcs, {"w1": 0, "w2": 0})


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
@slow  # real chunk workers via stage3 (2026-09-14: ~9.0s measured)
class Stage3ChunkCompletionCheckTests(unittest.TestCase):
    """``stage3``'s post-wait completion check, exercised through a mocked
    ``Popen`` so the test controls exactly what a "worker" leaves behind
    without needing a real 6-argv re-exec.

    ``cmd`` positions below (see ``stage3``'s ``cmd_base``): ``[..., PROBE(4),
    PROJECT(5), PROFILE.name(6), PROFILE_MODULE or ""(7),
    str(worker_stall_min)(8), chunk_path(9), i(10), n_every(11)]``.
    """

    def setUp(self):
        self._real_popen = run_flight.subprocess.Popen
        self._real_log = run_flight.log
        run_flight.log = lambda *a, **kw: None
        self.addCleanup(setattr, run_flight.subprocess, "Popen", self._real_popen)
        self.addCleanup(setattr, run_flight, "log", self._real_log)

    @needs_v314_engine
    def test_a_zero_exit_without_a_done_record_is_refused_not_merged(self):
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            chunk_path = Path(cmd[10])
            i = int(cmd[11])
            n_every_i = int(cmd[12])
            written = run_flight.imgproc.imgproc_sm(
                str(INPUT), str(chunk_path), run_flight.PROBE, i, n_every_i,
                run_flight.PROJECT, profile=run_flight.PROFILE)
            if i != 1:
                # Every worker but chunk 1 behaves: writes its completion
                # record. Chunk 1 "exits 0" (poll() below returns 0) but
                # never wrote one -- the exact shape a worker that got
                # through startup and stopped before finishing would leave.
                chunk_path.with_name(chunk_path.name + ".done").write_text(f"{written}\n")
            return _FakeProc(rc=0)
        run_flight.subprocess.Popen = fake_popen

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                run_flight.stage3(INPUT, Path(tmp), chunks=2, worker_stall_min=1)
        self.assertIn("completion record", str(ctx.exception))
        self.assertTrue(seen_cmds, "expected two chunk workers to be spawned")

    @needs_v314_engine
    def test_a_mismatched_particle_count_is_refused_not_merged(self):
        """Two sides from two places (the worker's own claim vs. the file's
        own dimension) -- a worker that lied, or a truncated write, both
        caught the same way."""
        def fake_popen(cmd, **kw):
            chunk_path = Path(cmd[10])
            i = int(cmd[11])
            n_every_i = int(cmd[12])
            written = run_flight.imgproc.imgproc_sm(
                str(INPUT), str(chunk_path), run_flight.PROBE, i, n_every_i,
                run_flight.PROJECT, profile=run_flight.PROFILE)
            claimed = written + 1 if i == 1 else written
            chunk_path.with_name(chunk_path.name + ".done").write_text(f"{claimed}\n")
            return _FakeProc(rc=0)
        run_flight.subprocess.Popen = fake_popen

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                run_flight.stage3(INPUT, Path(tmp), chunks=2, worker_stall_min=1)
        self.assertIn("particles, file holds", str(ctx.exception))

    @needs_v314_engine
    def test_worker_stall_min_reaches_the_chunk_workers_positional_argv(self):
        """The flag that does not survive the LITERAL-quoted-flag check in
        ``test_worker_argument_forwarding.py`` (it travels positionally, like
        PROBE/PROJECT/PROFILE.name) still has to actually arrive."""
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            chunk_path = Path(cmd[10])
            i = int(cmd[11])
            n_every_i = int(cmd[12])
            written = run_flight.imgproc.imgproc_sm(
                str(INPUT), str(chunk_path), run_flight.PROBE, i, n_every_i,
                run_flight.PROJECT, profile=run_flight.PROFILE)
            chunk_path.with_name(chunk_path.name + ".done").write_text(f"{written}\n")
            return _FakeProc(rc=0)
        run_flight.subprocess.Popen = fake_popen

        with tempfile.TemporaryDirectory() as tmp:
            run_flight.stage3(INPUT, Path(tmp), chunks=2, worker_stall_min=17.5)
        self.assertTrue(seen_cmds)
        for cmd in seen_cmds:
            self.assertEqual(cmd[9], "17.5")  # after TAS_FILE (cmd[8]), pair D


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
@slow  # real chunked stage3 vs. single-chunk (2026-09-14: ~4.4s measured)
class ChunkedStage3ByteIdentityTests(unittest.TestCase):
    """The healthy-path guard (this
    change moves no written byte). Real subprocesses, real ``--_run-chunk``
    re-execs, real merge -- the actual new code path, not a lower-level
    stand-in."""

    def _assert_identical(self, path_a: Path, path_b: Path):
        with netCDF4.Dataset(path_a) as a, netCDF4.Dataset(path_b) as b:
            self.assertEqual(list(a.variables), list(b.variables))
            self.assertEqual(len(a.dimensions["time"]), len(b.dimensions["time"]))
            for name in a.variables:
                with self.subTest(variable=name):
                    va = np.asarray(a.variables[name][:]).astype(np.float64)
                    vb = np.asarray(b.variables[name][:]).astype(np.float64)
                    self.assertTrue(np.array_equal(va, vb, equal_nan=True),
                                    f"{name}: values differ")
            for attr in a.ncattrs():
                if attr in NONDETERMINISTIC_ATTRS:
                    continue
                with self.subTest(attribute=attr):
                    self.assertEqual(getattr(a, attr), getattr(b, attr))

    @needs_v314_engine
    def test_chunked_stage3_is_byte_identical_to_a_single_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            raw = tmp / "base160906064000.2DS"
            _build_raw_flight(raw)
            self._real_log = run_flight.log
            run_flight.log = lambda *a, **kw: None
            try:
                image = run_flight.stage2(raw, tmp)
                single_dir = tmp / "single"
                single_dir.mkdir()
                chunked_dir = tmp / "chunked"
                chunked_dir.mkdir()
                single = run_flight.stage3(image, single_dir, chunks=1)
                # worker_stall_min=0.5 min == 30 s: the discriminating test
                # for U1 (the healthy path must not trip the watchdog).
                # Measured 2026-09-13: 3 s (the plan's own suggested budget,
                # written for the in-process fixture test_imgproc_merge_
                # chunks.py uses) is too tight here because THIS test drives
                # a real --_run-chunk re-exec -- a fresh interpreter that has
                # to start up and import arrayprobe/numpy/netCDF4/numba
                # before its first progress line, unlike a direct in-process
                # imgproc_sm() call. 30 s is comfortably clear of that
                # one-time cold-start cost on a normal machine while still
                # being a real, bounded budget.
                chunked = run_flight.stage3(image, chunked_dir, chunks=2,
                                            worker_stall_min=0.5)
            finally:
                run_flight.log = self._real_log
            self._assert_identical(single, chunked)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
