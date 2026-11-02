# SPDX-License-Identifier: BSD-3-Clause
"""The chunk merge after a chunked S3 writes a heartbeat into the worker's log.

Measured 2026-09-23 on the 2016-09-12 re-validation (``_decoded/reval_160912``,
``queue_0923.launch.log`` 17:39-21:40): every chunk of all three ``--jobs`` workers
finished, then ``merge_chunks`` ran silently past the 30-min ``--worker-stall-min``
on 9.5-13.3 GB raw files, and the parent's ``_await_workers`` killed each worker
mid-merge. A ``--jobs`` worker's own log is its only liveness signal, so a silent
step longer than the stall budget is indistinguishable from a hang.

Covers: ``_log_heartbeat`` writes lines while its block runs and none after it; an
interval of 0 disables it; and both merge call sites (v3.1.4 ``merge_chunks`` and
v3.5 ``merge_chunks_v35``) sit inside the heartbeat's ``with`` block -- checked on
the source, so removing the wrapper fails here rather than on the next large flight.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests._driver import driver_source

_TOOLS = Path(__file__).resolve().parent.parent / "scripts"
_SPEC = importlib.util.spec_from_file_location("run_flight", _TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)


class LogHeartbeat(unittest.TestCase):
    def _run(self, interval: float, seconds: float, watch: Path | None = None) -> list[str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with run_flight._log_heartbeat("S3 merge", interval, watch):
                time.sleep(seconds)
            time.sleep(interval * 3 if interval > 0 else 0.1)  # nothing may follow the block
        return [line for line in out.getvalue().splitlines() if "S3 merge alive" in line]

    def test_it_beats_while_the_block_runs(self):
        # 1.5 s at a 0.05 s interval is ~30 beats; macOS runners managed 2 in 0.4 s (CI run
        # 41338745088), so the margin is wide and the claim (it beats repeatedly) unchanged.
        self.assertGreaterEqual(len(self._run(0.05, 1.5)), 3)

    def test_it_stops_when_the_block_ends(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with run_flight._log_heartbeat("S3 merge", 0.05):
                time.sleep(0.2)
            during = out.getvalue().count("S3 merge alive")
            time.sleep(0.3)
        self.assertEqual(out.getvalue().count("S3 merge alive"), during)

    def test_zero_interval_disables_it(self):
        self.assertEqual(self._run(0, 0.2), [])

    def test_it_reports_the_file_it_watches(self):
        with tempfile.TemporaryDirectory() as tmp:
            watched = Path(tmp) / "proc.x.nc.partial"
            watched.write_bytes(b"\0" * 2_000_000)
            lines = self._run(0.05, 0.2, watched)
        self.assertTrue(lines)
        self.assertIn("2 MB written", lines[0])

    def test_it_stops_even_when_the_block_raises(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(RuntimeError):
                with run_flight._log_heartbeat("S3 merge", 0.05):
                    time.sleep(0.12)
                    raise RuntimeError("merge failed")
            during = out.getvalue().count("S3 merge alive")
            time.sleep(0.3)
        self.assertEqual(out.getvalue().count("S3 merge alive"), during)


class BothMergeCallsAreWrapped(unittest.TestCase):
    """The wiring, read from the source: every call to ``merge_chunks`` or
    ``merge_chunks_v35`` in ``run_flight.py`` is lexically inside a ``with`` whose
    context expression is the heartbeat."""

    MERGES = {"merge_chunks", "merge_chunks_v35"}

    def test_every_merge_call_is_inside_the_heartbeat(self):
        tree = ast.parse(driver_source("run_flight.py").read_text(encoding="utf-8"))
        found, unwrapped = [], []

        def visit(node: ast.AST, wrapped: bool) -> None:
            if isinstance(node, ast.With):
                wrapped = wrapped or any(
                    isinstance(item.context_expr, ast.Name) and item.context_expr.id == "beat"
                    or isinstance(item.context_expr, ast.Call)
                    and getattr(item.context_expr.func, "id", "") == "_log_heartbeat"
                    for item in node.items)
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in self.MERGES:
                    found.append(node.lineno)
                    if not wrapped:
                        unwrapped.append(node.lineno)
            for child in ast.iter_child_nodes(node):
                visit(child, wrapped)

        visit(tree, False)
        self.assertEqual(len(found), 2, f"expected the two merge call sites, found {found}")
        self.assertEqual(unwrapped, [], f"merge calls outside the heartbeat at lines {unwrapped}")


if __name__ == "__main__":
    unittest.main()
