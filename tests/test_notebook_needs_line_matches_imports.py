# SPDX-License-Identifier: BSD-3-Clause
"""Every shipped notebook's **Needs:** line names each optional extra its code imports.

**The defect this was written after.** On 2026-10-30 a full read of the examples found
notebooks whose cell 0 said *"Needs: core package only"* while their code imported matplotlib,
pandas, xarray or the enhancements packages, so a reader with ``pip install arrayprobe`` alone
hit an ``ImportError`` on the first plot. The two sides come from different places: the
required extras are read from the notebook's own code (``ast``), mapped through
``pyproject.toml``'s ``[project.optional-dependencies]``; the claim is cell 0's text. Which
notebooks ship is ``test_notebook_outputs_name_no_absent_engine.shipped_notebooks`` (the
release builder's allow-list matcher), imported rather than copied.

An import is *required* when it sits in an untagged code cell outside a ``try`` whose handler
catches ``ImportError``/``ModuleNotFoundError`` (a guarded import is an optional section).
A required extra is *named* when the Needs text contains ``arrayprobe[<extra>]``, or, for the
enhancements packages, the words "enhancements package".
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
import unittest

from tests._repo import repo_only
from tests.test_notebook_outputs_name_no_absent_engine import ROOT, shipped_notebooks

PYPROJECT = ROOT / "pyproject.toml"

#: Import name -> distribution name, where the two differ (or the module is reached
#: through another distribution's dependency).
IMPORT_TO_DIST = {
    "netCDF4": "netcdf4",
    "pandas": "xarray",          # no extra lists pandas; xarray (the [zarr] extra) requires it
    "_style": "matplotlib",      # examples/_style.py imports matplotlib at module level
    "arrayprobe_enhancements": "arrayprobe-uiops-enhancements",
    "arrayprobe_soda2_enhancements": "arrayprobe-soda2-enhancements",
}

#: This package's own modules and the repository helper scripts the notebooks import: core.
OWN_MODULES = frozenset({"arrayprobe", "arrayprobe_uiops", "arrayprobe_soda2", "uiops",
                         "run_flight", "make_demo_flight", "make_demo_reference",
                         "truth_harness"})

_NEEDS = re.compile(r"\*\*Needs:\*\*(.*)")
_PIP_EXTRAS = re.compile(r"arrayprobe\[([^\]]+)\]")
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def _dist(requirement: str) -> str:
    return _REQ_NAME.match(requirement).group(1).lower().replace("_", "-")


def dependency_map(pyproject: dict) -> tuple[frozenset[str], dict[str, str]]:
    """(core distributions, distribution -> the first extra that provides it)."""
    project = pyproject["project"]
    core = frozenset(_dist(r) for r in project.get("dependencies", []))
    provider: dict[str, str] = {}
    for extra, reqs in project.get("optional-dependencies", {}).items():
        if extra in ("dev", "pinned"):
            continue
        for r in reqs:
            provider.setdefault(_dist(r), extra)
    return core, provider


def _guarded(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True if ``node`` sits in a ``try`` body whose handler catches an import error."""
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.Try):
            for h in node.handlers:
                names = [h.type] if not isinstance(h.type, ast.Tuple) else h.type.elts
                if h.type is None or any(isinstance(n, ast.Name) and n.id in (
                        "ImportError", "ModuleNotFoundError", "Exception") for n in names):
                    return True
    return False


def required_modules(notebook: dict) -> set[str]:
    """Top-level modules imported unguarded by the notebook's untagged code cells."""
    mods: set[str] = set()
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code" or (cell.get("metadata") or {}).get("tags"):
            continue
        src = "".join(cell.get("source", []))
        src = "\n".join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith(("%", "!")))
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import) and not _guarded(n, parents):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif (isinstance(n, ast.ImportFrom) and n.level == 0 and n.module
                  and not _guarded(n, parents)):
                mods.add(n.module.split(".")[0])
    return mods


def required_extras(notebook: dict, core: frozenset[str], provider: dict[str, str]) -> set[str]:
    extras = set()
    for mod in required_modules(notebook):
        if mod in sys.stdlib_module_names or mod in OWN_MODULES:
            continue
        dist = IMPORT_TO_DIST.get(mod, mod).lower().replace("_", "-")
        if dist in core:
            continue
        extras.add(provider.get(dist, f"<no extra provides {dist}>"))
    return extras


def needs_text(notebook: dict) -> str:
    cells = notebook.get("cells", [])
    m = _NEEDS.search("".join(cells[0].get("source", []))) if cells else None
    return m.group(1) if m else ""


def needs_problems(notebook: dict, core: frozenset[str], provider: dict[str, str]) -> list[str]:
    text = needs_text(notebook)
    out = []
    for extra in sorted(required_extras(notebook, core, provider)):
        listed = {e.strip() for group in _PIP_EXTRAS.findall(text) for e in group.split(",")}
        named = ("enhancements package" in text if extra == "enhancements"
                 else extra in listed)
        if not named:
            out.append(f"imports need [{extra}] but Needs says {text.strip()!r}")
    return out


def _deps() -> tuple[frozenset[str], dict[str, str]]:
    with PYPROJECT.open("rb") as fh:
        return dependency_map(tomllib.load(fh))


def _fixture(needs: str, code: str, tags: list[str] | None = None) -> dict:
    meta = {"tags": tags} if tags else {}
    return {"cells": [
        {"cell_type": "markdown", "metadata": {}, "source": [f"# X\n\n**Needs:** {needs}\n"]},
        {"cell_type": "code", "metadata": meta, "outputs": [], "source": [code]}]}


class TestGuardFires(unittest.TestCase):
    def setUp(self):
        self.core, self.provider = _deps()

    def _p(self, needs, code, tags=None):
        return needs_problems(_fixture(needs, code, tags), self.core, self.provider)

    def test_core_claim_with_matplotlib_is_caught(self):
        self.assertTrue(self._p("core package only.", "import matplotlib.pyplot as plt"))

    def test_each_optional_module_is_caught(self):
        for code in ("import pandas as pd", "import xarray", "from zarr import open",
                     "import arrayprobe_enhancements.x", "import pyarrow", "import _style"):
            with self.subTest(code=code):
                self.assertTrue(self._p("core package only.", code))

    def test_enhancements_only_does_not_cover_matplotlib(self):
        self.assertTrue(self._p("the enhancements package.",
                                "import arrayprobe_enhancements\nimport matplotlib"))

    def test_naming_the_extras_passes(self):
        self.assertEqual(self._p('the enhancements package and `pip install "arrayprobe[extra]"`.',
                                 "import arrayprobe_enhancements\nimport matplotlib"), [])

    def test_core_stdlib_and_own_modules_pass(self):
        self.assertEqual(self._p("core package only.", "import numpy, json, netCDF4, scipy\n"
                                 "from arrayprobe_uiops import imgproc\nimport run_flight"), [])

    def test_guarded_and_tagged_imports_are_optional(self):
        self.assertEqual(self._p("core package only.",
                                 "try:\n    import xarray\nexcept ImportError:\n    pass"), [])
        self.assertEqual(self._p("core package only.", "import matplotlib", tags=["v314-only"]), [])


@repo_only
class TestShippedNotebooks(unittest.TestCase):
    def test_every_needs_line_names_the_extras_its_imports_need(self):
        core, provider = _deps()
        notebooks = shipped_notebooks()
        self.assertTrue(notebooks, "no shipped example notebooks found")
        found = []
        for path in notebooks:
            nb = json.loads(path.read_text(encoding="utf-8"))
            for problem in needs_problems(nb, core, provider):
                found.append(f"{path.relative_to(ROOT).as_posix()}: {problem}")
        self.assertEqual(found, [], f"{len(found)} notebook(s):\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
