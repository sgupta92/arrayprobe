# SPDX-License-Identifier: BSD-3-Clause
"""A ``--jobs`` worker is never handed an engine the parent did not name.

``--engine`` is required (since 2026-09-23), and ``main()`` refuses a run without it before
``run_parallel`` is reached, so every production ``args`` carries it. ``_spawn_worker`` used to
read it as ``getattr(args, "engine", "3.1.4")``: unreachable today, but a future caller whose
``args`` lacked the attribute would have spawned v3.1.4 workers under whatever engine it meant,
and stamped their output accordingly. It now reads ``args.engine``, so such a caller raises.

Two checks, one behavioural and one on the source, because the behavioural one passes for any
spelling that raises while the source check names the exact regression.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import shutil
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
assert spec is not None and spec.loader is not None
run_flight = importlib.util.module_from_spec(spec)
sys.modules.setdefault(spec.name, run_flight)
spec.loader.exec_module(run_flight)


def _args(root: Path, **extra) -> types.SimpleNamespace:
    """Every attribute ``_spawn_worker`` reads, except whatever ``extra`` adds."""
    return types.SimpleNamespace(
        stages="234", out=root, chunks=1, s2_jobs=1, iat_file="",
        preset="DEMO_2DS_H", tas_file=None, presets=None, config=None,
        allow_mixed_config=False, accept_unstamped=False, diode_corrected=False,
        worker_stall_min=30.0, **extra,
    )


class SpawnWorkerNeverDefaultsTheEngine(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_args_without_an_engine_raise_rather_than_spawn_a_v314_worker(self):
        with mock.patch.object(run_flight.subprocess, "Popen",
                               return_value=mock.Mock()) as popen:
            with self.assertRaises(AttributeError):
                _proc, log_f = run_flight._spawn_worker(
                    [self.root / "a.2DS"], _args(self.root), self.root / "worker.log")
                log_f.close()
        popen.assert_not_called()

    def test_the_named_engine_is_forwarded_verbatim(self):
        for engine in ("3.5", "3.1.4"):
            with self.subTest(engine=engine), mock.patch.object(
                    run_flight.subprocess, "Popen", return_value=mock.Mock()) as popen:
                _proc, log_f = run_flight._spawn_worker(
                    [self.root / "a.2DS"], _args(self.root, engine=engine),
                    self.root / f"worker_{engine}.log")
                log_f.close()
                cmd = popen.call_args.args[0]
                self.assertEqual(cmd[cmd.index("--engine") + 1], engine)

    def test_the_source_has_no_getattr_engine_fallback(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(run_flight._spawn_worker)))
        offenders = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) >= 3
            and isinstance(node.args[1], ast.Constant) and node.args[1].value == "engine"
        ]
        self.assertEqual(offenders, [], "_spawn_worker reads --engine through getattr with a "
                                        "default; a missing engine must raise, not fall back")


if __name__ == "__main__":
    unittest.main()
