# SPDX-License-Identifier: BSD-3-Clause
"""No test gives a call that is expected to succeed a timeout a loaded machine can miss.

WHY THIS TEST EXISTS. On 2026-10-02 a full suite went red on a loaded machine
in tests whose subject was not speed: ``test_wait_for_suite`` gave a helper
5 s, and the triage-server tests gave each request to their in-process server
10 s. Nothing had hung; the machine was busy. A timeout on a call expected to
succeed exists to bound a hang, so it must be loose enough that only a hang
reaches it. The class was first drawn as "a literal timeout under 30 s on a
call that raises when it expires", fixed at 60 s.

That floor was too low. In the full suite of the same night (suite_m1002b,
2026-10-02) two tests that pass alone failed only under load, on subprocess
timeouts the 30 s floor let through: ``test_refuse_foreground_suite`` (30 s)
and ``test_presuite_finds_the_venv`` (60 s). The floor is now 120 s; the 52
call sites it then reported were raised to 120 s in one pass, and this test
refuses the next one.

What is scanned: every ``.py`` under ``tests/``, every call to a function that
raises on expiry (``subprocess.run``, ``check_output``, ``check_call``,
``communicate``, ``wait``, ``HTTPConnection``, ``urlopen``,
``create_connection``, ``settimeout``) whose timeout is a literal, or a
module-level constant, below ``_FLOOR_S``. A call inside an ``assertRaises``
block asserts the hang itself and keeps its short timeout. Calls that wait
without raising (``Thread.join``) are not scanned: expiry fails nothing.
"""

from __future__ import annotations

import ast
import functools
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_FLOOR_S = 120.0  # suite_m1002b, 2026-10-02: 30 s and 60 s both missed under load

#: Final attribute or function names of calls that raise when their timeout expires.
_RAISING = frozenset({
    "run", "check_output", "check_call", "communicate", "wait",
    "HTTPConnection", "HTTPSConnection", "urlopen", "create_connection", "settimeout",
})

#: "<file>::<enclosing function>" -> why a short timeout is right there.
_ALLOWED: dict[str, str] = {}


def _callee(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _timeout_arg(node: ast.Call, name: str) -> ast.expr | None:
    for kw in node.keywords:
        if kw.arg == "timeout":
            return kw.value
    if name == "settimeout" and node.args:
        return node.args[0]
    if name == "create_connection" and len(node.args) > 1:
        return node.args[1]
    return None


def _constants(tree: ast.Module) -> dict[str, object]:
    out: dict[str, object] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name):
            try:
                out[stmt.targets[0].id] = ast.literal_eval(stmt.value)
            except ValueError:
                pass
    return out


def _is_assert_raises(item: ast.withitem) -> bool:
    expr = item.context_expr
    return isinstance(expr, ast.Call) and _callee(expr) in ("assertRaises", "assertRaisesRegex")


def short_timeouts(source: str, filename: str) -> list[tuple[str, int, str, float]]:
    """``(key, line, callee, seconds)`` for each short timeout on a call expected to succeed."""
    tree = ast.parse(source, filename=filename)
    consts = _constants(tree)
    found: list[tuple[str, int, str, float]] = []

    def visit(node: ast.AST, func: str, expecting_raise: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        if isinstance(node, ast.With) and any(_is_assert_raises(i) for i in node.items):
            expecting_raise = True
        if isinstance(node, ast.Call) and not expecting_raise:
            name = _callee(node)
            arg = _timeout_arg(node, name) if name in _RAISING else None
            value: object = None
            if isinstance(arg, ast.Name):
                value = consts.get(arg.id)
            elif arg is not None:
                try:
                    value = ast.literal_eval(arg)
                except ValueError:
                    value = None
            if isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and value < _FLOOR_S:
                found.append((f"{filename}::{func}", node.lineno, name, float(value)))
        for child in ast.iter_child_nodes(node):
            visit(child, func, expecting_raise)

    visit(tree, "<module>", False)
    return found


@functools.lru_cache(maxsize=1)
def _scan_tests() -> tuple[tuple[str, int, str, float], ...]:
    """Every short timeout under ``tests/``, keyed by repo-relative file, in one pass."""
    out: list[tuple[str, int, str, float]] = []
    for path in sorted(_TESTS.rglob("*.py")):
        rel = path.relative_to(_TESTS).as_posix()
        out.extend(short_timeouts(path.read_text(encoding="utf-8"), rel))
    return tuple(out)


class ShortTimeoutTests(unittest.TestCase):
    def test_no_short_timeout_on_a_call_expected_to_succeed(self) -> None:
        offenders = [
            f"{key.split('::')[0]}:{line} {name}(timeout={secs:g})"
            for key, line, name, secs in _scan_tests() if key not in _ALLOWED
        ]
        self.assertEqual(
            offenders, [],
            f"timeouts under {_FLOOR_S:g} s on calls expected to succeed fail on a loaded "
            "machine; use 120 s, wrap a deliberate hang in assertRaises, or add the function "
            "to _ALLOWED with the reason",
        )

    def test_every_allowance_still_matches_a_short_timeout(self) -> None:
        live = {key for key, *_ in _scan_tests()}
        for key in _ALLOWED:
            with self.subTest(allowance=key):
                self.assertIn(key, live, f"stale allowance {key!r}")


class ScannerFiresTests(unittest.TestCase):
    """The scanner is executed against known cases, not only read."""

    def test_flags_literal_constant_and_socket_forms(self) -> None:
        src = (
            "import subprocess, http.client, socket\n"
            "T = 5\n"
            "def f():\n"
            "    subprocess.run(['x'], timeout=5)\n"
            "    subprocess.run(['x'], timeout=T)\n"
            "    http.client.HTTPConnection('h', 1, timeout=10)\n"
            "    socket.socket().settimeout(2)\n"
        )
        lines = [line for _, line, _, _ in short_timeouts(src, "x.py")]
        self.assertEqual(lines, [4, 5, 6, 7])

    def test_passes_load_tolerant_hang_asserting_and_non_raising_waits(self) -> None:
        src = (
            "import subprocess\n"
            "class C:\n"
            "    def f(self):\n"
            "        subprocess.run(['x'], timeout=120)\n"
            "        with self.assertRaises(subprocess.TimeoutExpired):\n"
            "            subprocess.run(['x'], timeout=1)\n"
            "        self.thread.join(timeout=5)\n"
            "        subprocess.run(['x'], timeout=self.t)\n"
        )
        self.assertEqual(short_timeouts(src, "x.py"), [])


if __name__ == "__main__":
    unittest.main()
