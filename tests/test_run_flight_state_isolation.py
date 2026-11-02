# SPDX-License-Identifier: BSD-3-Clause
"""Guard: a ``run_flight.main`` call restored through ``tests/_run_flight_state``
leaves no UPPER_CASE global of the shared module rebound.

A leaked ``ENGINE='3.5'`` once sent a later module's ``setUpClass`` down the
probetype-2 branch, which raised and left ``run_flight.log`` silenced for the
rest of the process.
The self-test proves the comparison can fire.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import re
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests import _run_flight_state
from tests._repo import needs_v314_engine  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_RF_SPEC = importlib.util.spec_from_file_location("run_flight", _ROOT / "scripts" / "run_flight.py")


def _shared_run_flight():
    """The registered module every other test reaches, created only if absent."""
    if _RF_SPEC.name not in sys.modules:
        rf = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = rf
        _RF_SPEC.loader.exec_module(rf)
    return sys.modules[_RF_SPEC.name]


class MainLeavesNoGlobalAfterRestore(unittest.TestCase):

    def test_a_refused_v35_run_is_fully_restored(self):
        rf = _shared_run_flight()
        before = _run_flight_state.snapshot(rf)
        try:
            with redirect_stdout(io.StringIO()):
                rc = rf.main(["--engine", "3.5", "--profile", "stock-v3.5",
                              "--preset", "ORACLES_2016_2DS_H",
                              "--probe-case", "no-such-case-9f3a", "nosuch-raw.2DS"])
            self.assertEqual(rc, 2)
            # The call really does rebind globals, so the restore is doing work.
            self.assertTrue(_run_flight_state.diff(rf, before))
        finally:
            _run_flight_state.restore(rf, before)
        self.assertEqual(_run_flight_state.diff(rf, before), [])


#: Modules whose tests call ``main()`` in-process with a stock-v3.5 config. Without the
#: restore, ``test_config_time_offset`` left ``PROFILE = stock-v3.5`` behind and six
#: engine-3.1.4 tests of ``test_engine_flag_parity`` failed when run after it (2026-10-02).
_MAIN_CALLING_MODULES = ("tests.test_config_time_offset", "tests.test_v35_time_offset_driver")


class WholeModulesLeaveNoGlobal(unittest.TestCase):

    @needs_v314_engine
    def test_each_module_leaves_the_shared_module_unchanged(self):
        for name in _MAIN_CALLING_MODULES:
            with self.subTest(module=name):
                suite = unittest.defaultTestLoader.loadTestsFromName(name)
                # The module's own run_flight: shared when it registered first, private
                # otherwise -- either way the one its main() calls rebind.
                rf = importlib.import_module(name).run_flight
                before = _run_flight_state.snapshot(rf)
                try:
                    with redirect_stdout(io.StringIO()):
                        res = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
                    self.assertTrue(res.wasSuccessful(), name)
                    self.assertEqual(_run_flight_state.diff(rf, before), [], name)
                finally:
                    _run_flight_state.restore(rf, before)


_DRIVER_ENTRIES = frozenset({"main", "_apply_config", "use_preset"})

#: Modules that call a driver entry point without ``_run_flight_state.preserve``/
#: ``preserve_module``, each with its reason. An entry that no longer calls the driver,
#: or now uses the helper, is stale and fails ``test_no_stale_allowance``. Empty since
#: 2026-10-02: test_run_flight and test_run_flight_config merged preserve_module into their
#: module_hooks() setUpModule, and test_triage_reads_v35_decode's hand-typed restore became
#: preserve plus a restore of the lowercase ``log`` it silences.
_ALLOWED: dict[str, str] = {}


def _driver_names(tree: ast.AST, src: str) -> set[str]:
    """Names bound, directly or through a chain of assignments, to the driver module."""
    names = {"run_flight"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                bound = [a.asname or a.name for a in node.names
                         if a.name.split(".")[-1] == "run_flight"]
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                seg = ast.get_source_segment(src, node.value) or ""
                if "run_flight" not in seg and not any(
                        isinstance(n, ast.Name) and n.id in names for n in ast.walk(node.value)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                bound = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
            else:
                continue
            for name in bound:
                if name not in names:
                    names.add(name)
                    changed = True
    return names


def driver_calls(src: str) -> list[str]:
    """``<driver>.main/_apply_config/use_preset`` calls in a test module's source."""
    tree = ast.parse(src)
    names = _driver_names(tree, src)
    return sorted({f"{n.func.value.id}.{n.func.attr}" for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr in _DRIVER_ENTRIES and isinstance(n.func.value, ast.Name)
                   and n.func.value.id in names})


def uses_preserve(src: str) -> bool:
    return re.search(r"_run_flight_state\.preserve(_module)?\(", src) is not None


class EveryDriverCallerRestores(unittest.TestCase):
    """Static sweep: a test module that calls the driver in-process restores its globals
    through the shared helper, not a hand-typed list that misses a name (TIME_OFFSET,
    2026-10-02)."""

    def _modules(self):
        for path in sorted((_ROOT / "tests").glob("test_*.py")):
            src = path.read_text(encoding="utf-8")
            yield path.name, src, driver_calls(src)

    def test_every_caller_uses_preserve(self):
        offenders = [f"{name}: {calls}" for name, src, calls in self._modules()
                     if calls and not uses_preserve(src) and name not in _ALLOWED]
        self.assertEqual(offenders, [], "call _run_flight_state.preserve (setUp/setUpClass) or "
                         "preserve_module (setUpModule)")

    def test_no_stale_allowance(self):
        live = {name for name, src, calls in self._modules() if calls and not uses_preserve(src)}
        self.assertEqual(sorted(set(_ALLOWED) - live), [])

    def test_the_scan_fires(self):
        src = "\n".join([
            "spec = importlib.util.spec_from_file_location('run_flight', 'x')",
            "mod = importlib.util.module_from_spec(spec)",
            "mod.use_preset('X')", "rf.main([])"])
        self.assertEqual(driver_calls(src), ["mod.use_preset"])
        self.assertFalse(uses_preserve(src))
        self.assertTrue(uses_preserve(src + "_run_flight_state.preserve_module(mod)"))


class TheComparisonFires(unittest.TestCase):

    def test_a_rebound_added_or_removed_global_is_reported(self):
        rf = _shared_run_flight()
        before = _run_flight_state.snapshot(rf)
        try:
            rf.ENGINE = object()                  # rebound
            rf.GUARD_SELFTEST_ADDED_9F3A = 1      # added
            self.assertEqual(_run_flight_state.diff(rf, before),
                             ["ENGINE", "GUARD_SELFTEST_ADDED_9F3A"])
        finally:
            _run_flight_state.restore(rf, before)
        self.assertEqual(_run_flight_state.diff(rf, before), [])
        self.assertFalse(hasattr(rf, "GUARD_SELFTEST_ADDED_9F3A"))


class InventoryRowsAreRestored(unittest.TestCase):
    """``INVENTORY_ROWS`` is filled in place by ``inventory_preflight`` and ``stage2`` stamps
    from it, so a rebind-only restore left one test's rows for the next test."""

    def test_rows_added_in_place_are_reported_and_removed(self):
        rf = _shared_run_flight()
        before = _run_flight_state.snapshot(rf)
        try:
            rf.INVENTORY_ROWS["guard-selftest-9f3a"] = {"sha256": "0" * 64}
            self.assertEqual(_run_flight_state.diff(rf, before), ["INVENTORY_ROWS"])
        finally:
            _run_flight_state.restore(rf, before)
        self.assertEqual(_run_flight_state.diff(rf, before), [])
        self.assertNotIn("guard-selftest-9f3a", rf.INVENTORY_ROWS)


if __name__ == "__main__":
    unittest.main()
