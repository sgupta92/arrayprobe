# SPDX-License-Identifier: BSD-3-Clause
"""Run page slice 2: dry run, detached launch, run records, run status (``arrayprobe.run_page``).

Design: ``RUN_PAGE_PLAN.md`` section 3, slice 2. No test here starts a processing run: the
launcher is a fake that records its argv and kwargs, and the one real-subprocess test (gated
``ARRAYPROBE_SLOW=1``) runs a stub command through the real wrapper, never the driver.
"""

import datetime as dt
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests._slow import slow

from arrayprobe import run_page


def _form(tmp: Path, **over):
    raw = tmp / "base160906064017.2DS"
    raw.write_bytes(b"")
    form = {"engine": "3.5", "profile": "stock-v3.5", "preset": "DEMO_2DS_H",
            "raw": str(raw), "out": str(tmp / "out"), "stages": "234", "name": "demo",
            "jobs": 1, "s2_jobs": 1, "chunks": 1}
    form.update(over)
    return form


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class FakePopen:
    """Records argv and kwargs; writes a canned log line through the handle it was given."""

    calls: list = []

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 4242
        kwargs["stdout"].write(b"preflight ok\n")
        FakePopen.calls.append(self)


class _Done:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class TestDryRun(_Tmp):
    def test_refusal_text_is_returned_verbatim(self):
        seen = {}
        text = "refused: --engine 3.1.4 needs --port-validation\n"

        def launcher(argv, **kwargs):
            seen["argv"], seen["kwargs"] = argv, kwargs
            return _Done(2, text, "stderr line\n")

        argv = run_page.build_argv(_form(self.tmp), self.tmp / "c.toml", dry_run=True)
        code, out = run_page.dry_run(argv, self.tmp, launcher=launcher)
        self.assertEqual(code, 2)
        self.assertEqual(out, text + "stderr line\n")
        self.assertIs(seen["argv"], argv)
        self.assertNotIn("shell", seen["kwargs"])
        self.assertEqual(seen["kwargs"]["stdin"], subprocess.DEVNULL)

    def test_timeout_is_reported_not_raised(self):
        def launcher(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output="half")

        code, out = run_page.dry_run(["x"], self.tmp, timeout=3, launcher=launcher)
        self.assertEqual(code, -1)
        self.assertIn("half", out)
        self.assertIn("did not finish within 3 s", out)

    def test_a_shell_string_is_refused(self):
        with self.assertRaises(TypeError):
            run_page.dry_run("arrayprobe run x.toml", self.tmp, launcher=lambda *a, **k: None)


class TestLaunch(_Tmp):
    def setUp(self):
        super().setUp()
        FakePopen.calls = []

    def test_record_written_with_pid_argv_toml_log(self):
        now = dt.datetime(2026, 10, 7, 17, 5, 9)
        rec = run_page.start_run(_form(self.tmp), popen=FakePopen, now=now)
        self.assertEqual(rec["run_id"], "20261007-170509-demo")
        self.assertEqual(rec["pid"], 4242)
        out = (self.tmp / "out").resolve()
        run_dir = out / "_runs" / rec["run_id"]
        self.assertEqual(Path(rec["toml"]), run_dir / "config.toml")
        self.assertTrue(Path(rec["toml"]).is_file())
        self.assertEqual(Path(rec["log"]), run_dir / "run.log")
        self.assertEqual(run_page.read_record(out, rec["run_id"]), rec)
        # The documented entry point behind the wrapper, with the TOML the page wrote.
        fake = FakePopen.calls[0]
        self.assertEqual(fake.argv[:6], [sys.executable, "-m", "arrayprobe.run_page", "_wrap",
                                         rec["run_id"], "--"])
        self.assertEqual(fake.argv[6:], rec["argv"])
        self.assertEqual(rec["argv"][1:4], ["-m", "arrayprobe", "run"])
        self.assertEqual(rec["argv"][4], rec["toml"])
        self.assertIn("--yes", rec["argv"])
        self.assertNotIn("--dry-run", rec["argv"])
        log = Path(rec["log"]).read_text(encoding="utf-8")
        self.assertIn("preflight ok", log)
        self.assertIn("=== pid: 4242", log)

    def test_run_id_charset(self):
        now = dt.datetime(2026, 1, 2, 3, 4, 5)
        self.assertEqual(run_page.new_run_id("a.b_c-1", now), "20260102-030405-a.b_c-1")
        for bad in ("", "../x", "a b", "a/b", "a\\b", "x" * 65, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                run_page.new_run_id(bad, now)

    def test_unknown_run_id_never_reaches_a_path(self):
        out = self.tmp / "out"
        (out / "_runs" / "..").mkdir(parents=True, exist_ok=True)
        (self.tmp / "run.json").write_text("{}", encoding="utf-8")
        for bad in ("..", "../..", "20261007-170509-demo", "nope"):
            self.assertIsNone(run_page.read_record(out, bad))
        self.assertEqual(run_page.list_runs(out), [])

    def test_record_with_a_foreign_run_id_is_refused(self):
        with self.assertRaises(ValueError):
            run_page.write_record(self.tmp, {"run_id": "../escape"})


class TestDetached(_Tmp):
    def setUp(self):
        super().setUp()
        FakePopen.calls = []

    def _launch(self):
        log = self.tmp / "r" / "run.log"
        pid = run_page.launch_detached(["prog", "a"], log, self.tmp,
                                       run_id="20261007-170509-demo", popen=FakePopen)
        return pid, FakePopen.calls[0].kwargs, log

    @unittest.skipUnless(os.name == "nt", "Windows creation flags")
    def test_windows_creationflags_set(self):
        _, kwargs, _ = self._launch()
        flags = kwargs["creationflags"]
        self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & subprocess.DETACHED_PROCESS)
        self.assertNotIn("start_new_session", kwargs)

    @unittest.skipIf(os.name == "nt", "POSIX session")
    def test_posix_new_session(self):
        _, kwargs, _ = self._launch()
        self.assertTrue(kwargs["start_new_session"])

    def test_output_goes_to_the_log_never_a_pipe(self):
        pid, kwargs, log = self._launch()
        self.assertEqual(pid, 4242)
        self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertNotIn("shell", kwargs)
        self.assertTrue(kwargs["close_fds"])
        text = log.read_text(encoding="utf-8")
        # The launch header must not counterfeit the completion marker.
        self.assertNotIn(" exited ", text)

    def test_constants_match_subprocess(self):
        if os.name == "nt":
            self.assertEqual(run_page.CREATE_NEW_PROCESS_GROUP,
                             subprocess.CREATE_NEW_PROCESS_GROUP)
            self.assertEqual(run_page.DETACHED_PROCESS, subprocess.DETACHED_PROCESS)


class TestStatus(_Tmp):
    def _record(self, log_text, run_id="20261007-170509-demo"):
        out = self.tmp / "out"
        out.mkdir(exist_ok=True)
        log = out / "_runs" / run_id / "run.log"
        log.parent.mkdir(parents=True)
        log.write_text(log_text, encoding="utf-8")
        started = dt.datetime.now().astimezone() - dt.timedelta(seconds=5)
        return {"run_id": run_id, "pid": 4242, "log": str(log), "out": str(out),
                "started": started.isoformat(timespec="seconds")}

    def test_log_tail_and_call_files_listed(self):
        rec = self._record("".join(f"line {i}\n" for i in range(100)))
        out = Path(rec["out"])
        (out / "base.proc.call").write_text("engine=3.5", encoding="utf-8")
        # A nested run file, built from parts so the audit's repository-path check does
        # not read a fixture created at runtime as a missing tracked file.
        nested = Path("sub", "base.sd.call")
        (out / nested.parent).mkdir()
        (out / nested).write_text("engine=3.5", encoding="utf-8")
        old = out / "stale.call"
        old.write_text("x", encoding="utf-8")
        past = time.time() - 3600
        os.utime(old, (past, past))
        st = run_page.run_status(rec, tail_lines=10, alive=lambda pid: True)
        self.assertEqual(st["state"], "running")
        self.assertTrue(st["alive"])
        self.assertIsNone(st["exit_code"])
        self.assertEqual(st["log_tail"], [f"line {i}" for i in range(90, 100)])
        self.assertEqual(st["call_files"], ["base.proc.call", nested.as_posix()])
        self.assertIsNotNone(st["newest_output_mtime"])

    def test_finished_run_reports_exit_line(self):
        rec = self._record("work\nOK\n=== 20261007-170509-demo exited 0 2026-10-07T17:10 ===\n")
        st = run_page.run_status(rec, alive=lambda pid: self.fail("not asked once exited"))
        self.assertEqual(st["state"], "finished")
        self.assertEqual(st["exit_code"], 0)
        self.assertIn("OK", st["verdict_lines"])

    def test_failed_run_and_verdict_lines(self):
        rec = self._record("Traceback (most recent call last):\nrun refused: bad preset\n"
                           "=== 20261007-170509-demo exited 2 2026-10-07T17:10 ===\n")
        st = run_page.run_status(rec, alive=lambda pid: False)
        self.assertEqual(st["state"], "failed")
        self.assertEqual(st["exit_code"], 2)
        self.assertEqual(len(st["verdict_lines"]), 2)

    def test_dead_without_exit_line_is_named(self):
        rec = self._record("work\n")
        st = run_page.run_status(rec, alive=lambda pid: False)
        self.assertEqual(st["state"], "ended without an exit line")

    def test_another_runs_exit_line_is_not_this_ones(self):
        rec = self._record("=== 20261007-000000-other exited 0 x ===\n")
        st = run_page.run_status(rec, alive=lambda pid: True)
        self.assertIsNone(st["exit_code"])
        self.assertEqual(st["state"], "running")

    def test_own_pid_reads_alive(self):
        self.assertTrue(run_page._pid_alive(os.getpid()))
        self.assertFalse(run_page._pid_alive(0))


@slow
class TestDetachedIntegration(_Tmp):
    """A stub command (never the driver) through the real wrapper and real detach: the log fills
    and carries the exit line after ``launch_detached`` has returned."""

    def tearDown(self):
        # The wrapper writes the exit line and only then releases run.log; on Windows the
        # handle can outlive the line by a moment (WinError 32 in suite_1007g), so retry.
        deadline = time.time() + 30
        while True:
            try:
                self._td.cleanup()
                return
            except PermissionError:
                if time.time() > deadline:
                    raise
                time.sleep(0.5)

    def test_stub_run_writes_its_output_and_exit_line(self):
        src = str(Path(run_page.__file__).resolve().parents[1])
        env_path = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = src + (os.pathsep + env_path if env_path else "")
        try:
            log = self.tmp / "run.log"
            run_id = "20261007-170509-stub"
            pid = run_page.launch_detached(
                [sys.executable, "-c", "print('stub ran'); raise SystemExit(3)"],
                log, self.tmp, run_id=run_id)
        finally:
            os.environ["PYTHONPATH"] = env_path
        rec = {"run_id": run_id, "pid": pid, "log": str(log), "out": str(self.tmp),
               "started": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
        deadline = time.time() + 60
        st = run_page.run_status(rec)
        while st["exit_code"] is None and time.time() < deadline:
            time.sleep(0.5)
            st = run_page.run_status(rec)
        self.assertEqual(st["exit_code"], 3, log.read_text(encoding="utf-8"))
        self.assertIn("stub ran", log.read_text(encoding="utf-8"))
        self.assertEqual(st["state"], "failed")


if __name__ == "__main__":
    unittest.main()
