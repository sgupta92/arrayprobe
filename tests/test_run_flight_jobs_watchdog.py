# SPDX-License-Identifier: BSD-3-Clause
"""Pair G, 2026-09-13: ``run_parallel()`` (``--jobs``) is bounded the same way
P10 bounded ``stage3``'s ``--chunks`` wait -- ``_await_workers`` instead of a
bare ``proc.wait()``, so a wedged ``--jobs`` worker no longer blocks forever.

Measured on the 14 real ``--jobs`` worker logs on disk (scratch ``gaps.py``):
a healthy worker's own log is silent for its ENTIRE nested chunked S3 -- 264,
170, 136, 132, 99, 73, 45, 44 and 34 minutes on nine of them -- because chunk
progress goes to the per-chunk logs, not the worker's own. A naive 30-min
log-growth watchdog on the worker's own log would have killed 9 of these 14
healthy runs. ``_await_workers`` now writes a growth-conditional heartbeat
into its own log (see ``_heartbeat_interval``) so a ``--jobs`` worker's log
is a valid liveness signal for the parent's own wait, which uses the same
``--worker-stall-min`` value (forwarded by ``_spawn_worker`` since this
pass).

Covers: a stalled ``--jobs`` worker is killed, reported with the files it
held, and its siblings are left running (they hold DIFFERENT files -- unlike
the ``--chunks`` case, one bad file must not take the others down);
``--worker-stall-min`` is forwarded literally; ``stall_s <= 0`` reproduces
the old unbounded wait; the heartbeat fires only while a worker's log is
actually growing; and a byte-identity guard for a healthy
``--jobs 2 --chunks 2`` run against the serial equivalent
(this change moves no written byte).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import time
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

NONDETERMINISTIC_ATTRS = frozenset({
    "Creation Time", "Image Source",
    # sizedist.py:1843 writes sd.*.nc's "Data Source" as str(the proc file's
    # own path) -- unlike everything else compared here, it necessarily
    # differs between serial_dir and jobs_dir (two different output
    # directories), not a fidelity divergence. Measured 2026-09-13 (pair G):
    # test_run_flight_chunk_watchdog.py's byte-identity guard never hit this
    # because its single/chunked proc files share ONE decoded image path;
    # this test's two runs write proc files into two different directories.
    "Data Source",
})


def _pid_is_running(pid: int) -> bool:
    """Windows-only: ``tasklist`` sees native processes MSYS ``ps -ef`` does
    not (the exact blind spot ``test_run_flight_chunk_watchdog.py`` names)."""
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                         capture_output=True, text=True, check=False)
    return str(pid) in out.stdout


class _FakeProc:
    """A finished worker, as ``_await_workers`` sees one: it polls rather
    than blocks, so a fake needs ``poll``/``pid``, not only ``wait``."""

    pid = 0

    def __init__(self, rc=0):
        self._rc = rc

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        return self._rc


def _fake_args(out: Path, jobs: int, chunks: int = 1, worker_stall_min: float = 30.0):
    """Same shape as ``test_run_flight.py``'s ``RunParallelTests._fake_args``,
    plus ``worker_stall_min`` (pair G's seventh forwarded flag)."""
    class _Args:
        pass
    a = _Args()
    a.out = out
    a.stages = "234"
    a.iat_file = run_flight.IAT_FILE
    a.jobs = jobs
    a.chunks = chunks
    a.diode_corrected = False
    a.accept_unstamped = False
    a.s2_jobs = 1
    a.preset = run_flight.ORACLES_2016_2DS_H.name
    a.presets = None
    a.config = None
    a.allow_mixed_config = False
    a.tas_file = None
    a.worker_stall_min = worker_stall_min
    a.engine = "3.1.4"  # --engine is required; _spawn_worker reads it
    return a


@slow  # real subprocess workers + sleeps (2026-09-14: ~14.4s measured)
class JobsWatchdogTests(unittest.TestCase):
    """``run_parallel``'s bounded wait, with real subprocesses standing in
    for the actual --jobs workers (``subprocess.Popen`` is patched to run a
    small inline script instead of a full re-exec, so these tests do not
    need real raw/flight data)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._real_popen = run_flight.subprocess.Popen
        self._real_log = run_flight.log
        self.logged = []
        run_flight.log = self.logged.append
        self.addCleanup(setattr, run_flight, "log", self._real_log)
        self.addCleanup(setattr, run_flight.subprocess, "Popen", self._real_popen)

    def test_a_stalled_worker_is_killed_reported_with_its_files_and_rc_one(self):
        pidfile = self.out / "pid.txt"
        body1 = (
            "import os, sys, time\n"
            "sys.stdout.write('started\\n'); sys.stdout.flush()\n"
            f"open(r'{pidfile}', 'w').write(str(os.getpid()))\n"
            "time.sleep(25)\n"
        )
        body2 = "import sys; sys.stdout.write('done\\n')\n"
        calls = {"n": 0}

        def fake_popen(cmd, **kw):
            calls["n"] += 1
            body = body1 if calls["n"] == 1 else body2
            return self._real_popen([sys.executable, "-c", body], **kw)
        run_flight.subprocess.Popen = fake_popen

        args = _fake_args(self.out, jobs=2, worker_stall_min=0.05)  # 3 s
        files = [Path("a.2DS"), Path("b.2DS")]  # worker 1 gets a.2DS (round robin)
        t0 = time.monotonic()
        rc = run_flight.run_parallel(args, files)
        elapsed = time.monotonic() - t0
        # Deliberate: under mutation M1 (bare loop restored) worker 1's real
        # 25 s sleep finishes on its own, rc is 0 and this fails in ~25 s
        # instead of the ~3-5 s the watchdog needs -- no throwaway script
        # required to see the mutation fail.
        self.assertEqual(rc, 1)
        self.assertLess(elapsed, 15, "the watchdog must fire well inside its budget")
        self.assertTrue(any("STALLED" in ln and "worker 1" in ln for ln in self.logged),
                        self.logged)
        self.assertTrue(any("worker 1 held" in ln and "a.2DS" in ln for ln in self.logged),
                        self.logged)
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(pidfile.exists(), "the worker got far enough to record its pid")
        pid = int(pidfile.read_text())
        self.assertFalse(
            _pid_is_running(pid),
            f"pid {pid} must be gone after _kill_tree's taskkill /T")

    def test_stall_zero_is_the_old_unbounded_wait(self):
        def fake_popen(cmd, **kw):
            return self._real_popen(
                [sys.executable, "-c", "import time; time.sleep(2)"], **kw)
        run_flight.subprocess.Popen = fake_popen

        args = _fake_args(self.out, jobs=1, worker_stall_min=0)
        rc = run_flight.run_parallel(args, [Path("a.2DS")])
        self.assertEqual(rc, 0)
        self.assertTrue(any("all workers done" in ln for ln in self.logged))

    def test_a_failed_sibling_does_not_kill_a_healthy_worker(self):
        """The discriminating test for ``on_fail_kill_all=False``: --jobs
        siblings hold DIFFERENT files, so one worker's failure must not take
        the others down (unlike --chunks, where a partial merge is
        impossible and every sibling IS killed)."""
        calls = {"n": 0}
        body1 = "import sys; sys.exit(2)\n"
        body2 = ("import sys, time\n"
                "time.sleep(2)\n"
                "sys.stdout.write('B finished\\n')\n")

        def fake_popen(cmd, **kw):
            calls["n"] += 1
            body = body1 if calls["n"] == 1 else body2
            return self._real_popen([sys.executable, "-c", body], **kw)
        run_flight.subprocess.Popen = fake_popen

        args = _fake_args(self.out, jobs=2, worker_stall_min=30.0)
        files = [Path("a.2DS"), Path("b.2DS")]
        rc = run_flight.run_parallel(args, files)
        self.assertEqual(rc, 1)
        log2 = self.out / "run_job2_b.log"
        self.assertTrue(log2.exists(), sorted(p.name for p in self.out.iterdir()))
        self.assertIn("B finished", log2.read_text())
        self.assertTrue(any("worker 1" in ln and "exit 2" in ln for ln in self.logged),
                        self.logged)
        self.assertFalse(any("KILLING" in ln for ln in self.logged), self.logged)


class _ScriptedProc:
    """A running worker that exits with ``rc`` on its ``exit_after``-th poll,
    recording that moment in the shared ``events`` list the test's patched
    ``log`` also writes to, so the list's order is the order things happened.
    With ``log_path`` it appends a line there on every poll, as a live worker
    does, so the stall watchdog never reads it as wedged."""

    def __init__(self, label, rc, exit_after, events, log_path=None):
        self.label, self._rc, self._left, self._events = label, rc, exit_after, events
        self.pid = 0
        self._log_path = log_path
        self._done = False

    def poll(self):
        if self._done:
            return self._rc
        if self._log_path is not None:
            with open(self._log_path, "a") as f:
                f.write("progress; ")
        self._left -= 1
        if self._left <= 0:
            self._done = True
            self._events.append(f"<{self.label} exited rc={self._rc}>")
            return self._rc
        return None


class _NullLog:
    def close(self):
        pass


class FailureIsLoggedWhenDetectedTests(unittest.TestCase):
    """2026-10-08, C3 flight 160925:

    under ``on_fail_kill_all=False`` (the --jobs path) a worker the stall
    watchdog killed at 09:36 was logged ``JOBS FAILED worker 1`` only at
    18:02, when its sibling finished, so the launch log showed no failure
    for 8.5 h. The FAILED line, and the ``held`` line naming the worker's
    files, must appear at the poll that detects the failure, once per worker,
    while the sibling is still running. Fake workers: no subprocess, no sleep."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.events = []
        self._real_log = run_flight.log
        run_flight.log = self.events.append
        self.addCleanup(setattr, run_flight, "log", self._real_log)
        self._real_kill = run_flight._kill_tree
        run_flight._kill_tree = lambda proc: None
        self.addCleanup(setattr, run_flight, "_kill_tree", self._real_kill)

    def _run(self, w1_proc, held):
        w2_proc = _ScriptedProc("worker 2", 0, 40, self.events,
                                log_path=self.tmp / "w2.log")
        workers = [("worker 1", w1_proc, _NullLog(), self.tmp / "w1.log"),
                   ("worker 2", w2_proc, _NullLog(), self.tmp / "w2.log")]
        extra = {} if held is None else {"held": held}
        with self.assertRaises(RuntimeError) as ctx:
            run_flight._await_workers(workers, stall_s=30, poll_s=0.0, what="JOBS",
                                      on_fail_kill_all=False, heartbeat_s=0, **extra)
        self.assertIn("worker 1", str(ctx.exception))
        self.assertNotIn("worker 2", str(ctx.exception))
        return self.events.index("<worker 2 exited rc=0>")

    def _before(self, end, needle):
        return [ln for ln in self.events[:end] if needle in ln]

    def test_an_exit_failure_is_logged_before_the_sibling_finishes_and_once(self):
        end = self._run(_ScriptedProc("worker 1", 2, 1, self.events),
                        held={"worker 1": "a.2DS"})
        failed = self._before(end, "JOBS FAILED worker 1")
        self.assertEqual(len(failed), 1, self.events)
        self.assertIn("exit 2", failed[0])
        held_lines = self._before(end, "worker 1 held")
        self.assertEqual(len(held_lines), 1, self.events)
        self.assertIn("a.2DS", held_lines[0])
        self.assertFalse(self._before(end, "worker 2 held"), self.events)
        # The end-of-loop summary still restates it.
        self.assertTrue(any("JOBS FAILED worker 1" in ln for ln in self.events[end:]),
                        self.events)

    def test_a_stall_is_logged_failed_before_the_sibling_finishes_and_once(self):
        class _Wedged:
            pid = 0

            def poll(self):
                return None
        real_monotonic = run_flight.time.monotonic
        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 1.0   # one simulated second per reading
            return clock["t"]
        run_flight.time.monotonic = fake_monotonic
        self.addCleanup(setattr, run_flight.time, "monotonic", real_monotonic)
        end = self._run(_Wedged(), held=None)
        self.assertEqual(len(self._before(end, "STALLED worker 1")), 1, self.events)
        failed = self._before(end, "JOBS FAILED worker 1")
        self.assertEqual(len(failed), 1, self.events)
        self.assertIn("stalled", failed[0])


class WorkerStallMinIsForwardedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._real_popen = run_flight.subprocess.Popen
        self._real_log = run_flight.log
        run_flight.log = lambda *a, **kw: None
        self.addCleanup(setattr, run_flight, "log", self._real_log)
        self.addCleanup(setattr, run_flight.subprocess, "Popen", self._real_popen)

    def test_worker_stall_min_is_forwarded_literally(self):
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            return _FakeProc(0)
        run_flight.subprocess.Popen = fake_popen

        args = _fake_args(Path(self._tmp.name), jobs=2, worker_stall_min=17.5)
        run_flight.run_parallel(args, [Path("a.2DS"), Path("b.2DS")])
        self.assertTrue(seen_cmds)
        for cmd in seen_cmds:
            self.assertEqual(cmd[cmd.index("--worker-stall-min") + 1], "17.5")


@slow  # real subprocess workers + heartbeat sleeps (2026-09-14: ~5.7s measured)
class HeartbeatTests(unittest.TestCase):
    """Direct ``_await_workers`` calls -- no flight data, no Popen patch:
    the worker really is a tiny inline script."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._real_log = run_flight.log
        self.logged = []
        run_flight.log = self.logged.append
        self.addCleanup(setattr, run_flight, "log", self._real_log)

    def _spawn(self, tmp: Path, label: str, body: str):
        script = tmp / f"{label.replace(' ', '_')}.py"
        script.write_text(body)
        log_path = tmp / f"{label.replace(' ', '_')}.log"
        log_f = open(log_path, "w")
        proc = subprocess.Popen([sys.executable, str(script)],
                                stdout=log_f, stderr=subprocess.STDOUT)
        return label, proc, log_f, log_path

    def test_heartbeat_fires_while_a_workers_log_grows(self):
        tmp = Path(self._tmp.name)
        body = (
            "import sys, time\n"
            "for i in range(15):\n"
            "    sys.stdout.write('line %d\\n' % i); sys.stdout.flush(); time.sleep(0.2)\n"
        )
        worker = self._spawn(tmp, "w1", body)
        run_flight._await_workers([worker], stall_s=30, poll_s=0.1, what="TEST",
                                  heartbeat_s=0.5)
        self.assertGreaterEqual(
            sum(1 for ln in self.logged if "alive" in ln), 3, self.logged)

    def test_heartbeat_is_silent_while_no_log_grows(self):
        tmp = Path(self._tmp.name)
        body = "import sys, time\nsys.stdout.write('x\\n'); sys.stdout.flush(); time.sleep(2)\n"
        worker = self._spawn(tmp, "w2", body)
        run_flight._await_workers([worker], stall_s=0, poll_s=0.1, what="TEST",
                                  heartbeat_s=0.3)
        self.assertLessEqual(
            sum(1 for ln in self.logged if "alive" in ln), 1, self.logged)

    def test_the_first_size_reading_is_a_baseline_not_growth(self):
        # suite_0929f: under load the worker started after the first heartbeat window, so the
        # watchdog's first reading (-1 -> 0) and the real write landed in two windows.
        tmp = Path(self._tmp.name)
        body = ("import sys, time\ntime.sleep(0.8)\n"
                "sys.stdout.write('x\\n'); sys.stdout.flush(); time.sleep(1.5)\n")
        worker = self._spawn(tmp, "w3", body)
        run_flight._await_workers([worker], stall_s=0, poll_s=0.1, what="TEST",
                                  heartbeat_s=0.3)
        self.assertLessEqual(
            sum(1 for ln in self.logged if "alive" in ln), 1, self.logged)

    def test_heartbeat_interval_is_a_quarter_of_the_budget_capped_at_five_minutes(self):
        self.assertEqual(run_flight._heartbeat_interval(1800), 300)
        self.assertEqual(run_flight._heartbeat_interval(180), 45)
        self.assertEqual(run_flight._heartbeat_interval(0), 300)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
@slow  # real --jobs run vs. serial (2026-09-14: ~9.7s measured)
class JobsByteIdentityTests(unittest.TestCase):
    """The healthy-path guard (this
    change moves no written byte). Real re-execs at BOTH levels -- a --jobs
    worker, and that worker's own nested --chunks re-exec -- so U1 (the
    heartbeat keeps a healthy --jobs/--chunks worker alive) is exercised
    end to end, not just asserted."""

    def _assert_identical(self, path_a: Path, path_b: Path):
        with netCDF4.Dataset(path_a) as a, netCDF4.Dataset(path_b) as b:
            self.assertEqual(list(a.variables), list(b.variables))
            # proc.*.nc dimensions the record count "time"; sd.*.nc dimensions
            # it "Time" (capitalised, one of the case inconsistencies of
            # names) while still exposing a lowercase "time" VARIABLE -- so
            # pick whichever dimension name this file actually has.
            time_dim = "time" if "time" in a.dimensions else "Time"
            self.assertEqual(len(a.dimensions[time_dim]), len(b.dimensions[time_dim]))
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
    def test_a_jobs_run_is_byte_identical_to_the_serial_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            raw1 = tmp / "base160906064000.2DS"
            raw2 = tmp / "base160906070000.2DS"
            _build_raw_flight(raw1)
            _build_raw_flight(raw2, start_hour=7, start_minute=0, start_second=0)
            serial_dir = tmp / "serial"
            serial_dir.mkdir()
            jobs_dir = tmp / "jobs"
            jobs_dir.mkdir()
            self._real_log = run_flight.log
            run_flight.log = lambda *a, **kw: None
            try:
                # --preset and --yes are both required and neither is cosmetic:
                # --preset stopped defaulting on 2026-09-15 and the
                # `proceed with this configuration? [y/N]` prompt arrived with
                # the confirmation gate (`622fecd`). This test is @slow-gated, so it runs only
                # under ARRAYPROBE_SLOW=1 and went unnoticed erroring with
                # "the following arguments are required: --preset" until the
                # 2026-09-19 gate run. DEMO_2DS_H matches what builds these
                # files -- make_demo_flight.build_demo_flight, imported above.
                rc_serial = run_flight.main(
                    ["--stages", "234", "--engine", "3.1.4", "--port-validation",
                     "--preset", "DEMO_2DS_H", "--yes",
                     "--out", str(serial_dir), str(raw1), str(raw2)])
                # worker_stall_min=1.0 min == 60 s and --chunks 2 so the nested
                # heartbeat path (U1) is exercised end to end, not just the
                # outer --jobs wait. The plan's own suggested 0.5 (30 s) was
                # measured to flake once under this machine's load (this test
                # spawns SIX cold-start interpreters: two --jobs workers, each
                # spawning two nested --chunks workers, on top of the serial
                # run) -- raised per the plan's own U4 remedy ("if T6 flakes
                # on cold start, raise to worker_stall_min=1.0 ... do not
                # loosen further").
                rc_jobs = run_flight.main(
                    ["--stages", "234", "--engine", "3.1.4", "--port-validation",
                     "--preset", "DEMO_2DS_H", "--yes",
                     "--jobs", "2", "--chunks", "2",
                     "--worker-stall-min", "1.0", "--out", str(jobs_dir),
                     str(raw1), str(raw2)])
            finally:
                run_flight.log = self._real_log
            self.assertEqual(rc_serial, 0)
            self.assertEqual(rc_jobs, 0)
            for stem in (raw1.stem, raw2.stem):
                proc_a = next(serial_dir.glob(f"proc.{stem}*.nc"))
                proc_b = next(jobs_dir.glob(f"proc.{stem}*.nc"))
                self._assert_identical(proc_a, proc_b)
                sd_a = next(serial_dir.glob(f"sd.{stem}*.nc"))
                sd_b = next(jobs_dir.glob(f"sd.{stem}*.nc"))
                self._assert_identical(sd_a, sd_b)


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
