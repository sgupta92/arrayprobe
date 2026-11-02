# SPDX-License-Identifier: BSD-3-Clause
"""``--resume-chunks``: a chunked S3 run killed after its chunks finished reuses them.

A 2016-09-12 re-validation run was killed in its merge after about 10 h of chunk work, and the
rerun had to rebuild every chunk, because nothing on disk said what built them. With the flag,
the parent writes each chunk's intent (``.chunkN.call``) before spawning, the worker copies the
intent's hash into its completion record (``.chunkN.done``), and a later run reuses a chunk
only when both agree with the intent it computes fresh.


Two things are guarded here: a reused chunk merges byte-identical to a fresh run, and every way
the intent can differ rebuilds the chunk. The default (flag off) is unchanged: a valid set is
still deleted and rebuilt.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import netCDF4
import numpy as np
from tests import _run_flight_state
from tests._repo import needs_v314_engine  # noqa: E402
from tests._slow import slow

_TOOLS = Path(__file__).resolve().parent.parent / "scripts"
_SPEC = importlib.util.spec_from_file_location("run_flight", _TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("run_flight", run_flight)
_SPEC.loader.exec_module(run_flight)
run_flight = sys.modules["run_flight"]

INPUT = Path(__file__).parent / "data" / "2DS_s3_input_fixture.nc"
NONDETERMINISTIC_ATTRS = frozenset({"Creation Time", "Image Source"})


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: 2DS_s3_input_fixture.nc is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "2DS_s3_input_fixture.nc").exists():
    raise unittest.SkipTest(
        "2DS_s3_input_fixture.nc is not distributed with the package")


class _FakeProc:
    pid = 999999

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _assert_identical(tc: unittest.TestCase, path_a: Path, path_b: Path) -> None:
    with netCDF4.Dataset(path_a) as a, netCDF4.Dataset(path_b) as b:
        tc.assertEqual(list(a.variables), list(b.variables))
        for name in a.variables:
            va = np.asarray(a.variables[name][:]).astype(np.float64)
            vb = np.asarray(b.variables[name][:]).astype(np.float64)
            tc.assertTrue(np.array_equal(va, vb, equal_nan=True), f"{name}: values differ")
        for attr in a.ncattrs():
            if attr not in NONDETERMINISTIC_ATTRS:
                tc.assertEqual(getattr(a, attr), getattr(b, attr), attr)


class ResumeDecisionTests(unittest.TestCase):
    """Mocked ``Popen`` standing in for the ``--_run-chunk`` worker, so each case controls what
    a previous attempt left on disk and counts what is respawned."""

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        self.logged: list[str] = []
        self.spawned: list[int] = []
        self.cmds: list[list[str]] = []
        patches = [
            mock.patch.object(run_flight, "log", lambda msg, *a, **kw: self.logged.append(msg)),
            mock.patch.object(run_flight.subprocess, "Popen", self._fake_popen),
            mock.patch.object(run_flight, "_code_identity", lambda: "code-A"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _fake_popen(self, cmd, **kw):
        """What the worker does: build the chunk, then write the count and the intent token."""
        self.cmds.append(list(cmd))
        chunk_path, i, n_every = Path(cmd[10]), int(cmd[11]), int(cmd[12])
        self.spawned.append(i)
        written = run_flight.imgproc.imgproc_sm(
            str(INPUT), str(chunk_path), run_flight.PROBE, i, n_every,
            run_flight.PROJECT, profile=run_flight.PROFILE)
        record = f"{written}\n"
        for token in cmd[13:]:
            if token.startswith("intent="):
                record += token + "\n"
        chunk_path.with_name(chunk_path.name + ".done").write_text(record)
        return _FakeProc()

    def _killed_in_merge(self, chunks: int = 2) -> None:
        """A resumable attempt whose merge dies, leaving its chunks on disk."""
        with mock.patch.object(run_flight.imgproc, "merge_chunks",
                               side_effect=RuntimeError("simulated kill")):
            with self.assertRaises(RuntimeError):
                run_flight.stage3(INPUT, self.tmp, chunks=chunks, worker_stall_min=1,
                                  resume_chunks=True)
        self.spawned.clear()

    def _chunk(self, i: int, suffix: str = "") -> Path:
        return self.tmp / f"proc.{INPUT.name.replace('.cdf', '.nc')}.chunk{i}{suffix}"

    def _resume(self, chunks: int = 2) -> Path:
        return run_flight.stage3(INPUT, self.tmp, chunks=chunks, worker_stall_min=1,
                                 resume_chunks=True)

    @needs_v314_engine
    def test_a_full_resume_spawns_nothing_and_merges_identically(self):
        with tempfile.TemporaryDirectory() as ref_dir:
            reference = run_flight.stage3(INPUT, Path(ref_dir), chunks=2, worker_stall_min=1)
            self.spawned.clear()
            self._killed_in_merge()
            resumed = self._resume()
            self.assertEqual(self.spawned, [])
            _assert_identical(self, reference, resumed)
        self.assertIn("S3 resume chunk 1: reused", " ".join(self.logged))

    @needs_v314_engine
    def test_a_partial_resume_rebuilds_only_the_unfinished_chunk(self):
        self._killed_in_merge()
        self._chunk(2, ".done").unlink()
        self._resume()
        self.assertEqual(self.spawned, [2])

    @needs_v314_engine
    def test_the_merge_success_removes_every_chunk_file(self):
        self._killed_in_merge()
        self._resume()
        self.assertEqual(sorted(self.tmp.glob("*.chunk*")), [])

    @needs_v314_engine
    def test_without_the_flag_a_valid_set_is_still_rebuilt(self):
        self._killed_in_merge()
        run_flight.stage3(INPUT, self.tmp, chunks=2, worker_stall_min=1)
        self.assertEqual(self.spawned, [1, 2])
        self.assertFalse(any("intent=" in t for c in self.cmds[-2:] for t in c),
                         "the default path must not pass an intent token")

    @needs_v314_engine
    def test_the_call_file_records_the_workers_exact_argv(self):
        """The single-source guard: whatever the parent passes a worker is in its intent, so
        the next token added to the worker argv cannot skip it."""
        self._killed_in_merge()
        self.cmds.clear()
        self._chunk(1, ".done").unlink()
        self._resume()
        spawned = self.cmds[-1]
        self.assertTrue(spawned[-1].startswith("intent="))
        text = run_flight._chunk_intent_text(spawned[:-1], run_flight.proc_call_label(), INPUT,
                                             run_flight.image_record_count(INPUT), 2, "code-A")
        self.assertIn("argv=" + json.dumps(spawned[:-1]), text.splitlines())
        self.assertEqual(spawned[-1], "intent=" + hashlib.sha256(text.encode()).hexdigest())

    def _assert_all_recomputed(self, reason_fragment: str) -> None:
        self._resume()
        self.assertEqual(self.spawned, [1, 2])
        self.assertTrue(any(reason_fragment in m for m in self.logged),
                        f"no log line naming {reason_fragment!r}: {self.logged[-6:]}")

    @needs_v314_engine
    def test_a_completion_record_from_an_older_driver_is_not_reused(self):
        self._killed_in_merge()
        for i in (1, 2):
            d = self._chunk(i, ".done")
            d.write_text(d.read_text().splitlines()[0] + "\n")
        self._assert_all_recomputed("completion record is not from this intent")

    @needs_v314_engine
    def test_a_missing_intent_file_is_not_reused(self):
        self._killed_in_merge()
        for i in (1, 2):
            self._chunk(i, ".call").unlink()
        self._assert_all_recomputed(".call")

    @needs_v314_engine
    def test_swapped_completion_records_are_not_reused(self):
        self._killed_in_merge()
        one, two = self._chunk(1, ".done"), self._chunk(2, ".done")
        a, b = one.read_text(), two.read_text()
        one.write_text(b)
        two.write_text(a)
        self._assert_all_recomputed("completion record is not from this intent")

    @needs_v314_engine
    def test_a_count_that_disagrees_with_the_file_is_not_reused(self):
        self._killed_in_merge()
        for i in (1, 2):
            d = self._chunk(i, ".done")
            lines = d.read_text().splitlines()
            d.write_text("\n".join([str(int(lines[0]) + 1), *lines[1:]]) + "\n")
        self._assert_all_recomputed("!= file")

    @needs_v314_engine
    def test_a_touched_source_is_not_reused(self):
        self._killed_in_merge()
        st = INPUT.stat()
        self.addCleanup(os.utime, INPUT, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.utime(INPUT, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        self._assert_all_recomputed("source_mtime_ns")

    @needs_v314_engine
    def test_changed_code_is_not_reused(self):
        self._killed_in_merge()
        with mock.patch.object(run_flight, "_code_identity", lambda: "code-B"):
            self._assert_all_recomputed("code")

    @needs_v314_engine
    def test_unknown_code_state_reuses_nothing_and_records_no_intent(self):
        self._killed_in_merge()
        with mock.patch.object(run_flight, "_code_identity", lambda: None):
            with mock.patch.object(run_flight.imgproc, "merge_chunks",
                                   side_effect=RuntimeError("simulated kill")):
                with self.assertRaises(RuntimeError):
                    self._resume()
        self.assertEqual(self.spawned, [1, 2])
        self.assertFalse(self._chunk(1, ".call").exists())
        self.assertFalse(any(t.startswith("intent=") for c in self.cmds[-2:] for t in c))

    @needs_v314_engine
    def test_a_jit_toggle_is_not_reused(self):
        self._killed_in_merge()
        run_flight.JIT = True
        self._assert_all_recomputed("argv")

    @needs_v314_engine
    def test_a_tas_policy_change_is_not_reused(self):
        self._killed_in_merge()
        old = run_flight.TAS_POLICY
        run_flight.TAS_POLICY = run_flight._mtf.TasPolicy(old.cutoff_mps + 1, old.default_mps)
        self._assert_all_recomputed("argv")

    @needs_v314_engine
    def test_a_different_chunk_count_rebuilds_and_clears_the_extra_chunks(self):
        self._killed_in_merge(chunks=3)
        self.assertTrue(self._chunk(3).exists())
        self._assert_all_recomputed("argv")
        self.assertEqual(sorted(self.tmp.glob("*.chunk3*")), [])


class _Args(SimpleNamespace):
    """An argparse result where every flag the test does not set is unset (None)."""

    def __getattr__(self, name):
        return None


class JobsForwardingTests(unittest.TestCase):
    def _worker_cmd(self, **flags) -> list[str]:
        captured = {}

        def fake_popen(cmd, **kw):
            captured["cmd"] = cmd
            return _FakeProc()

        args = _Args(stages="123", out=Path("."), chunks=2, worker_stall_min=30.0,
                               s2_jobs=1, iat_file="x", preset="p", **flags)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(run_flight.subprocess, "Popen", fake_popen):
            _, log_f = run_flight._spawn_worker([Path("a.2DS")], args, Path(tmp) / "w.log")
            log_f.close()
        return captured["cmd"]

    def test_resume_chunks_reaches_a_jobs_worker(self):
        self.assertIn("--resume-chunks", self._worker_cmd(resume_chunks=True))
        self.assertNotIn("--resume-chunks", self._worker_cmd(resume_chunks=False))


@slow  # real --_run-chunk re-execs, three stage3 passes
class RealWorkerResumeTests(unittest.TestCase):
    """The real worker writes the intent hash into ``.done``, and a real resume is identical."""

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        p = mock.patch.object(run_flight, "log", lambda *a, **kw: None)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(run_flight, "_code_identity", lambda: "code-A")
        p.start()
        self.addCleanup(p.stop)

    @needs_v314_engine
    def test_real_workers_resume_byte_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "ref").mkdir()
            (tmp / "run").mkdir()
            reference = run_flight.stage3(INPUT, tmp / "ref", chunks=1)
            with mock.patch.object(run_flight.imgproc, "merge_chunks",
                                   side_effect=RuntimeError("simulated kill")):
                with self.assertRaises(RuntimeError):
                    run_flight.stage3(INPUT, tmp / "run", chunks=2, worker_stall_min=0.5,
                                      resume_chunks=True)
            dones = sorted((tmp / "run").glob("*.done"))
            self.assertEqual(len(dones), 2)
            for d in dones:
                self.assertTrue(any(ln.startswith("intent=") for ln in d.read_text().splitlines()),
                                f"{d.name} carries no intent hash")
            with mock.patch.object(run_flight.subprocess, "Popen",
                                   side_effect=AssertionError("a chunk was respawned")):
                resumed = run_flight.stage3(INPUT, tmp / "run", chunks=2, worker_stall_min=0.5,
                                            resume_chunks=True)
            _assert_identical(self, reference, resumed)


class CodeIdentityTests(unittest.TestCase):
    def test_a_directory_outside_git_has_no_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_ok = subprocess.run(["git", "--version"], capture_output=True).returncode == 0
            if not env_ok:
                self.skipTest("git not installed")
            self.assertIsNone(run_flight._git_tree_identity(Path(tmp)))

    def test_an_untracked_file_makes_a_tree_unverifiable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            run = lambda *a: subprocess.run(["git", "-C", str(tmp), *a],  # noqa: E731
                                            capture_output=True, check=True)
            try:
                run("init", "-q")
                run("config", "user.email", "t@example.invalid")
                run("config", "user.name", "t")
            except (OSError, subprocess.CalledProcessError):
                self.skipTest("git not usable")
            (tmp / "src").mkdir()
            (tmp / "src" / "a.py").write_text("x = 1\n")
            run("add", ".")
            run("commit", "-qm", "a")
            clean = run_flight._git_tree_identity(tmp / "src")
            self.assertIsNotNone(clean)
            (tmp / "src" / "b.py").write_text("y = 2\n")
            self.assertIsNone(run_flight._git_tree_identity(tmp / "src"))
            (tmp / "src" / "b.py").unlink()
            (tmp / "src" / "a.py").write_text("x = 2\n")
            self.assertIsNone(run_flight._git_tree_identity(tmp / "src"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
