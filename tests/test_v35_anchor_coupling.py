# SPDX-License-Identifier: BSD-3-Clause
"""Pins every name the v3.5 engine imports from the v3.1.4 anchor package.

``arrayprobe_uiops`` is the default engine, and it reuses a large part of the earlier translation
(``arrayprobe``): readers, geometry kernels, reject helpers, ``ncio``, ``provenance`` and
dozens of private helpers. Measured 2026-09-26 with the AST walk below: 83 symbols from 16
modules, 33 of them ``_``-prefixed. The default engine's numbers therefore depend on the
anchor's, and a rename or semantic change in ``arrayprobe`` can move them silently.

This module pins the exact per-module import set (``PINNED``), checks that every pinned
symbol still exists in the anchor, and forbids wildcard imports from it. It parses the v3.5
sources with ``ast`` and never imports ``arrayprobe_uiops``.

A failure means the coupling moved. If the move is deliberate, print the current literal
with ``python tests/test_v35_anchor_coupling.py --print``, paste it over ``PINNED``, and say
in the commit which coupling moved and why.

Excluded by name: ``sizedist.py``. A rework in progress since 2026-09-25 may replace the
private v3.1.4 names it reaches through ``from arrayprobe import sizedist as v314`` with public
names or its own symbol-level guard; pinning it here would break on that merge. Add it once that
rework lands. ``test_the_exclusion_list_is_still_needed`` fails when an exclusion covers
nothing.

Residual not covered: attribute access through a whole-module import, e.g. ``combine.py``'s
``_fork_combine.MATLAB_VARID`` and ``_fork_combine.combine_sizedist``. Only the import
statement itself is pinned, not the attributes read from the imported module.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
import unittest
from pathlib import Path

from tests._repo import needs_source

V35_ROOT = Path(__file__).resolve().parents[1] / "src" / "arrayprobe_uiops"
ANCHOR = "arrayprobe"
MODULE_SENTINEL = "<module>"

EXCLUDED: dict[str, str] = {}


def _is_anchor(module: str | None) -> bool:
    """True for ``arrayprobe`` and ``arrayprobe.*``; the sibling packages
    (``arrayprobe_uiops``, ``arrayprobe_soda2``, ``arrayprobe_enhancements``) do not count."""
    return module is not None and (module == ANCHOR or module.startswith(ANCHOR + "."))


def _anchor_nodes(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and _is_anchor(node.module):
                assert node.module is not None
                found.extend((node.module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Import):
            found.extend(
                (alias.name, MODULE_SENTINEL) for alias in node.names if _is_anchor(alias.name)
            )
    return found


def anchor_imports(path: Path) -> list[str]:
    """Every ``arrayprobe``/``arrayprobe.*`` import in one module, anywhere in the tree
    (module level or nested), as ``module:name``; a bare ``import arrayprobe.x`` is
    ``arrayprobe.x:<module>``."""
    return sorted({f"{mod}:{name}" for mod, name in _anchor_nodes(path)})


def measured() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in sorted(V35_ROOT.rglob("*.py")):
        if "__pycache__" in p.parts or p.name in EXCLUDED:
            continue
        names = anchor_imports(p)
        if names:
            out[p.relative_to(V35_ROOT).as_posix()] = names
    return out


def render(current: dict[str, list[str]]) -> str:
    lines = ["PINNED: dict[str, tuple[str, ...]] = {"]
    for rel, names in current.items():
        lines.append(f'    "{rel}": (')
        lines.extend(f'        "{n}",' for n in names)
        lines.append("    ),")
    lines.append("}")
    return "\n".join(lines)


PINNED: dict[str, tuple[str, ...]] = {
    "jit_kernels.py": (
        "arrayprobe:jit_kernels",
    ),
}


@needs_source
class TestV35ImportsFromTheAnchor(unittest.TestCase):
    def test_the_imported_symbol_set_is_exactly_the_pinned_one(self) -> None:
        current = measured()
        for rel in sorted(set(current) | set(PINNED)):
            have = set(current.get(rel, ()))
            want = set(PINNED.get(rel, ()))
            with self.subTest(module=rel):
                self.assertEqual(
                    have,
                    want,
                    f"arrayprobe_uiops/{rel}: imports from the v3.1.4 anchor changed; "
                    f"added {sorted(have - want)}, removed {sorted(want - have)}. "
                    "If deliberate, run `python tests/test_v35_anchor_coupling.py --print`, "
                    "paste the literal over PINNED and name the change in the commit.",
                )

    def test_every_pinned_symbol_still_exists_in_the_anchor(self) -> None:
        for rel, names in PINNED.items():
            for entry in names:
                mod_name, _, name = entry.partition(":")
                with self.subTest(module=rel, symbol=entry):
                    module = importlib.import_module(mod_name)
                    if name != MODULE_SENTINEL:
                        # ``from arrayprobe import jit_kernels`` names a submodule, which is
                        # an attribute only once loaded; find_spec checks it without importing.
                        self.assertTrue(
                            hasattr(module, name)
                            or importlib.util.find_spec(f"{mod_name}.{name}") is not None,
                            f"{mod_name}.{name} is gone from the anchor, but "
                            f"arrayprobe_uiops/{rel} imports it",
                        )

    def test_no_wildcard_import_from_the_anchor(self) -> None:
        files = sorted(V35_ROOT.rglob("*.py"))
        self.assertTrue(files, f"no .py files found under {V35_ROOT}; "
                               "the sweep below would pass on an empty set")
        for p in files:
            if "__pycache__" in p.parts:
                continue
            stars = [mod for mod, name in _anchor_nodes(p) if name == "*"]
            self.assertEqual(stars, [], f"wildcard import from the anchor in {p.name}")

    def test_the_exclusion_list_is_still_needed(self) -> None:
        for name, reason in EXCLUDED.items():
            path = V35_ROOT / name
            with self.subTest(excluded=name):
                self.assertTrue(path.is_file(), f"excluded {name} no longer exists ({reason})")
                self.assertTrue(
                    anchor_imports(path),
                    f"excluded {name} no longer imports from the anchor; drop the exclusion",
                )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(render(measured()))
    else:
        unittest.main()
