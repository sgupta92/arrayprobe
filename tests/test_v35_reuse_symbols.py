# SPDX-License-Identifier: BSD-3-Clause
"""Pins every underscore-private v3.1.4-port symbol the v3.5 engine borrows (2026-09-25 code review).

WHAT THIS PROTECTS. ``arrayprobe_uiops`` reaches into the earlier translation (``arrayprobe``) for
private names -- ``v314._process_population``, ``v314._VARS``, ``from arrayprobe.spec import
_decode_runs_auto`` and so on -- because their MATLAB source is byte-identical between the two
releases (``test_v35_reuse_byte_identity.py`` pins that at FILE level). Nothing pinned the
contract at SYMBOL level: a rename or edit of one of these privates in ``arrayprobe`` would break
or silently change the v3.5 engine, and no test would name the cause. The review
offered two fixes;
this is the one that leaves v3.1.4 port code untouched.

THREE CHECKS.
1. ``test_the_borrow_list_is_complete`` -- an AST sweep of every ``arrayprobe_uiops`` module finds
   every private name it takes from ``arrayprobe`` (``from arrayprobe.X import _n`` and
   ``alias._n`` where ``alias`` is bound to an ``arrayprobe`` module) and requires the set to
   equal ``BORROWED`` exactly, so a new borrow must be registered here and a dropped one removed.
2. ``test_every_borrowed_symbol_exists_and_is_unchanged`` -- each name still exists and its
   fingerprint (sha256 of ``inspect.getsource`` for a function/class, of ``repr`` for a value)
   matches the pin. A change fails with the name, so whoever edits the v3.1.4 private learns it
   feeds v3.5, re-verifies the v3.5 goldens, and only then updates the pin.
3. ``test_the_check_fires`` -- the checker is executed against a doctored table (a renamed
   name and a wrong hash) and must report both; a guard that cannot fail guards nothing.

Regenerate the table (after re-verifying v3.5 against its goldens) with::

    .venv/Scripts/python.exe tests/test_v35_reuse_symbols.py --print
"""
# ruff: noqa: E501  (the pin table's rows are one key and one sha256 each)
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import inspect
import sys
import unittest
from pathlib import Path

from tests._repo import needs_v314_engine  # noqa: E402

V35_SRC = Path(__file__).resolve().parents[1] / "src" / "arrayprobe_uiops"

#: (v3.1.4-port module, private name) -> sha256 fingerprint, measured 2026-09-26.
BORROWED: dict[tuple[str, str], str] = {
}


def _resolve_from(node: ast.ImportFrom) -> str | None:
    if node.level == 0 and node.module and (
            node.module == "arrayprobe" or node.module.startswith("arrayprobe.")):
        return node.module
    return None


def find_borrows() -> set[tuple[str, str]]:
    """Every (arrayprobe module, private name) any arrayprobe_uiops module takes."""
    found: set[tuple[str, str]] = set()
    for path in sorted(V35_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = _resolve_from(node)
                if mod is None:
                    continue
                for a in node.names:
                    if a.name.startswith("_") and not a.name.startswith("__"):
                        found.add((mod, a.name))
                    sub = f"{mod}.{a.name}"
                    try:
                        is_mod = importlib.util.find_spec(sub) is not None
                    except (ImportError, ValueError):
                        is_mod = False
                    if is_mod:
                        aliases[a.asname or a.name] = sub
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "arrayprobe" or a.name.startswith("arrayprobe."):
                        if a.asname:
                            aliases[a.asname] = a.name
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in aliases and node.attr.startswith("_")
                    and not node.attr.startswith("__")):
                found.add((aliases[node.value.id], node.attr))
    return found


def fingerprint(module: str, name: str) -> str:
    obj = getattr(importlib.import_module(module), name)
    if inspect.isfunction(obj) or inspect.isclass(obj):
        text = inspect.getsource(obj)
    else:
        text = repr(obj)
    # CRLF-normalised so a checkout's line-ending policy cannot fail the pin.
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def problems(table: dict[tuple[str, str], str]) -> list[str]:
    out = []
    for (module, name), pin in sorted(table.items()):
        mod = importlib.import_module(module)
        if not hasattr(mod, name):
            out.append(f"{module}.{name}: MISSING (renamed or removed in the v3.1.4 port?)")
            continue
        got = fingerprint(module, name)
        if got != pin:
            out.append(f"{module}.{name}: CHANGED (pinned {pin[:12]}, now {got[:12]})")
    return out


class BorrowedPrivateSymbols(unittest.TestCase):
    def test_the_borrow_list_is_complete(self):
        found = find_borrows()
        pinned = set(BORROWED)
        self.assertEqual(
            sorted(found - pinned), [],
            "arrayprobe_uiops borrows these v3.1.4 privates without a pin here; add them")
        self.assertEqual(
            sorted(pinned - found), [],
            "these pins are no longer borrowed by arrayprobe_uiops; remove them")

    def test_every_borrowed_symbol_exists_and_is_unchanged(self):
        # 2026-10-09 (split slice 8b): floor 20 -> 10; eight sizedist pins left with their symbols.
        # 2026-10-10 (cut S2): floor 10 -> 5; the three imgproc pins left with their symbols.
        # 2026-10-10 (cut S2, sizedist): the last nine pins left; arrayprobe_uiops borrows no private.
        self.assertEqual(len(BORROWED), 0)
        self.assertEqual(
            problems(BORROWED), [],
            "a v3.1.4-port private that arrayprobe_uiops borrows was renamed or edited: re-verify "
            "the v3.5 Octave goldens, then regenerate the pin (see module docstring)")

    @needs_v314_engine
    def test_the_check_fires(self):
        # No live pin remains, so exercise the checker on a symbol that exists in the anchor.
        (module, name), pin = ('arrayprobe.sizedist', '_d_length'), "0" * 64
        doctored = {(module, name + "_renamed"): pin, (module, name): "0" * 64}
        got = problems(doctored)
        self.assertEqual(len(got), 2, got)
        self.assertIn("MISSING", " ".join(got))
        self.assertIn("CHANGED", " ".join(got))


if __name__ == "__main__" and "--print" in sys.argv:
    for key in sorted(find_borrows()):
        print(f"    {key!r}: {fingerprint(*key)!r},")
elif __name__ == "__main__":
    unittest.main()
