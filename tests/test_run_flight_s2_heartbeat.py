# SPDX-License-Identifier: BSD-3-Clause
"""A --jobs worker's S2 parallel decode writes a heartbeat into the worker's log.

Measured 2026-10-08 on flight 160925 (C3 re-validation): the parts' merge after
an ``--s2-jobs`` decode (``readers/spec.py`` ``_merge_parts``/``_merge_sidecars``)
prints nothing and ran about 30 min on a large raw file, past the 30-min
``--worker-stall-min``, so the parent's ``_await_workers`` killed a live worker.


Covers: a slowed merge under the S2 heartbeat emits heartbeat lines; and every
call in ``run_flight.py`` to a parallel decode, a parts merge or a chunk merge is
lexically inside a heartbeat ``with`` -- a static scan shown to fire on a planted
unwrapped call.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._driver import driver_source
from tests._repo import needs_v314_engine  # noqa: E402

_TOOLS = Path(__file__).resolve().parent.parent / "scripts"
_SPEC = importlib.util.spec_from_file_location("run_flight", _TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)

SILENT_CALLS = {"read_binary_SPEC_parallel", "read_binary_spec_v35_parallel",
                "_merge_parts", "merge_chunks", "merge_chunks_v35"}


def unwrapped_silent_calls(source: str) -> tuple[list[int], list[int]]:
    """(every silent call's line, those outside a heartbeat ``with``)."""
    found: list[int] = []
    unwrapped: list[int] = []

    def is_beat(expr: ast.expr) -> bool:
        if isinstance(expr, ast.Name):
            return expr.id in {"beat", "s2_beat"}
        return isinstance(expr, ast.Call) and getattr(expr.func, "id", "") == "_log_heartbeat"

    def visit(node: ast.AST, wrapped: bool) -> None:
        if isinstance(node, ast.With):
            wrapped = wrapped or any(is_beat(item.context_expr) for item in node.items)
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in SILENT_CALLS:
                found.append(node.lineno)
                if not wrapped:
                    unwrapped.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, wrapped)

    visit(ast.parse(source), False)
    return found, unwrapped


class SlowMergeBeats(unittest.TestCase):
    @needs_v314_engine
    def test_a_slowed_parts_merge_under_the_heartbeat_logs_alive_lines(self):
        from arrayprobe.readers import spec

        def slow_merge(*_a, **_k):
            time.sleep(0.4)

        out = io.StringIO()
        with mock.patch.object(spec, "_merge_parts", slow_merge), \
                contextlib.redirect_stdout(out):
            with run_flight._log_heartbeat("S2 parallel decode", 0.05):
                spec._merge_parts()
        self.assertGreaterEqual(out.getvalue().count("S2 parallel decode alive"), 3)

    def test_the_interval_follows_the_stall_budget(self):
        # 30 min stall -> a beat every 300 s, well inside the parent's budget.
        self.assertEqual(run_flight._heartbeat_interval(30 * 60), 300.0)
        self.assertEqual(run_flight._heartbeat_interval(4 * 60), 60.0)

    def test_stage2_takes_the_stall_budget(self):
        import inspect
        self.assertIn("worker_stall_min", inspect.signature(run_flight.stage2).parameters)


class EverySilentCallIsWrapped(unittest.TestCase):
    def test_run_flight_has_no_silent_call_outside_a_heartbeat(self):
        found, unwrapped = unwrapped_silent_calls(
            driver_source("run_flight.py").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(found), 4, f"expected the S2 and S3 call sites, found {found}")
        self.assertEqual(unwrapped, [], f"silent calls outside a heartbeat at lines {unwrapped}")

    def test_the_scan_fires_on_a_planted_unwrapped_call(self):
        planted = ("def f(spec, raw):\n"
                   "    with s2_beat:\n"
                   "        spec.read_binary_SPEC_parallel(raw)\n"
                   "    spec.read_binary_SPEC_parallel(raw)\n")
        self.assertEqual(unwrapped_silent_calls(planted), ([3, 4], [4]))


if __name__ == "__main__":
    unittest.main()
