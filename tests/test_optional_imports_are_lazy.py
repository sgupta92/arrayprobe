# SPDX-License-Identifier: BSD-3-Clause
"""No module under ``src/`` imports an optional dependency at module level.

WHY THIS TEST EXISTS. ``pyproject.toml`` declares two runtime dependencies (numpy and
netCDF4) and puts everything else behind an extra: scipy, matplotlib and psutil in
``[extra]``, numba in ``[jit]``, the test and lint tooling in ``[dev]``. That split is a
promise to whoever runs ``pip install arrayprobe``: every module imports with the core
alone, and an extra is needed only by the function that uses it. A single
``import matplotlib.pyplot`` at the top of a module breaks the promise for every caller
of that module, including the ones that never draw anything, and the failure surfaces
as an ``ImportError`` at ``import arrayprobe.<module>`` time -- in an environment this
repository's own suite never builds, because the development venv installs every extra.

Measured when this check was written (2026-10-01): 144 modules under ``src/``, 30
imports of an optional module (20 of a declared extra, 10 of a sibling enhancement
package), every one of them already inside a function or a ``try`` guarded by
``ImportError``. So the allowlist starts empty; this file exists so
that it stays that way by construction rather than by attention.

WHAT COUNTS AS LAZY. An import of an optional module is accepted when it sits

* inside a function (``def``, ``async def`` or ``lambda``), at any depth;
* in the body of a ``try`` whose handlers catch ``ImportError`` or
  ``ModuleNotFoundError`` -- the body only: an import in the handler, the ``else`` or
  the ``finally`` runs unguarded and is module level;
* in the body of an ``if TYPE_CHECKING:`` block, which never runs.

Anything else -- module level, a class body, an ordinary ``if`` -- is a finding, unless
it is on :data:`ALLOWLIST` with its reason. The allowlist is shrink-only: its size may
not exceed :data:`ALLOWLIST_CEILING`, an entry that no longer occurs fails, and the
ceiling is lowered when an entry is removed, never raised to admit one.

WHAT IS OPTIONAL. Every distribution named in any group of
``[project.optional-dependencies]``, read from ``pyproject.toml`` with ``tomllib``, plus
the two sibling enhancement packages, which the core never declares (they depend on it,
not the reverse) and reaches only lazily. The other direction is checked too: a
third-party module imported anywhere under ``src/`` must be declared, as a core
dependency or in an extra.

The two sides come from different places -- the declarations from ``pyproject.toml``,
the imports from the source tree's syntax -- and the walker is shown to fire on a
synthetic source before its silence over the real tree is trusted.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
import unittest
from pathlib import Path

from tests._repo import needs_source

_PORT_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _PORT_ROOT / "pyproject.toml"
_SRC = _PORT_ROOT / "src"

#: Distribution name -> top-level import name, where the two differ. Every optional
#: distribution declared today imports under its own name; an entry here is needed only
#: when one does not (``scikit-learn`` -> ``sklearn``, ``pyyaml`` -> ``yaml``).
IMPORT_NAME: dict[str, str] = {}

#: Sibling packages the core reaches only lazily and never declares.
SIBLING_PACKAGES: frozenset[str] = frozenset(
    {"arrayprobe_enhancements", "arrayprobe_soda2_enhancements"})

#: ``(path relative to src/, imported module) -> why it cannot move``. Each entry is a
#: module-level import of an optional dependency that was not trivially movable into the
#: one function that uses it. Empty since this check was written: every optional import
#: in the tree was already lazy.
ALLOWLIST: dict[tuple[str, str], str] = {}

#: The allowlist may not grow past this. Lower it when an entry is removed; raising it to
#: admit a new entry is the change a reviewer should refuse.
ALLOWLIST_CEILING = 0

#: Anti-vacuity floors, below the counts measured when this was written (144 modules,
#: 30 lazy imports of an optional module).
MIN_MODULES_WALKED = 100
MIN_LAZY_IMPORTS_SEEN = 15

_GUARD_EXCEPTIONS = frozenset({"ImportError", "ModuleNotFoundError"})


#: Extras that only restate other declarations at exact versions (``pinned``): they name no
#: dependency of their own and are not optional groups.
MIRROR_EXTRAS: frozenset[str] = frozenset({"pinned"})


def _distribution_name(requirement: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.\-]+)", requirement)
    if not match:
        raise ValueError(f"unparseable requirement {requirement!r}")
    return match.group(1)


def _import_name(distribution: str) -> str:
    """Import names are case-sensitive (``netCDF4``), distribution names are not, so the
    requirement's own spelling is kept and only the lookup is case-folded."""
    return IMPORT_NAME.get(distribution.lower(), distribution.replace("-", "_"))


def declared_dependencies() -> tuple[set[str], dict[str, set[str]]]:
    """``(core import names, {extra: import names})`` from ``pyproject.toml``."""
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    core = {_import_name(_distribution_name(r)) for r in project.get("dependencies", [])}
    extras = {
        group: {_import_name(_distribution_name(r)) for r in requirements}
        for group, requirements in project.get("optional-dependencies", {}).items()
        if group not in MIRROR_EXTRAS
    }
    return core, extras


def _catches_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        caught = handler.type
        names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
        for name in names:
            if isinstance(name, ast.Name) and name.id in _GUARD_EXCEPTIONS:
                return True
    return False


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


def iter_imports(tree: ast.AST):
    """Yield ``(lineno, top-level module, full module, is_lazy)`` for every absolute import."""

    def visit(node: ast.AST, lazy: bool):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for child in ast.iter_child_nodes(node):
                yield from visit(child, True)
            return
        if isinstance(node, ast.Try) and _catches_import_error(node):
            for child in node.body:
                yield from visit(child, True)
            for child in [*node.handlers, *node.orelse, *node.finalbody]:
                yield from visit(child, lazy)
            return
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for child in node.body:
                yield from visit(child, True)
            for child in node.orelse:
                yield from visit(child, lazy)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0], alias.name, lazy
            return
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.lineno, node.module.split(".")[0], node.module, lazy
            return
        for child in ast.iter_child_nodes(node):
            yield from visit(child, lazy)

    yield from visit(tree, False)


def eager_optional_imports(source: str, optional: set[str]) -> list[tuple[int, str]]:
    """``(lineno, module)`` for each import of an optional module that is not lazy."""
    return [(lineno, full)
            for lineno, top, full, lazy in iter_imports(ast.parse(source))
            if top in optional and not lazy]


def _src_modules() -> list[Path]:
    return sorted(_SRC.rglob("*.py"))


def _first_party() -> set[str]:
    return {p.name for p in _SRC.iterdir() if (p / "__init__.py").is_file()}


class TheWalkerFires(unittest.TestCase):
    """The walker, on a synthetic source whose answer is known line by line."""

    SOURCE = '''\
import os
import matplotlib.pyplot as plt                     # 2: module level -> finding
from scipy import optimize                          # 3: module level -> finding
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psutil                                   # 7: never runs -> lazy

try:
    import numba                                    # 10: guarded -> lazy
except ImportError:
    import scipy.io                                 # 12: the handler runs -> finding
else:
    import matplotlib                               # 14: else runs -> finding

try:
    import numba.core                               # 17: wrong guard -> finding
except ValueError:
    pass

if os.name == "nt":
    import psutil                                   # 22: plain if -> finding


class Plotter:
    import matplotlib.figure                        # 26: class body -> finding

    def draw(self):
        import matplotlib.pyplot                    # 29: function -> lazy
        return matplotlib.pyplot


def fit():
    from scipy.optimize import least_squares        # 34: function -> lazy
    return least_squares


helper = lambda: __import__("numba")                # 38: not an import statement

try:
    from numba import njit                          # 41: tuple guard -> lazy
except (AttributeError, ModuleNotFoundError):
    njit = None
'''

    def test_it_reports_exactly_the_eager_imports(self):
        found = eager_optional_imports(
            self.SOURCE, {"matplotlib", "scipy", "psutil", "numba"})
        self.assertEqual(found, [
            (2, "matplotlib.pyplot"),
            (3, "scipy"),
            (12, "scipy.io"),
            (14, "matplotlib"),
            (17, "numba.core"),
            (22, "psutil"),
            (26, "matplotlib.figure"),
        ])

    def test_it_sees_the_lazy_ones_as_imports(self):
        lazy = sorted(lineno for lineno, top, _, is_lazy in iter_imports(ast.parse(self.SOURCE))
                      if is_lazy and top in {"matplotlib", "scipy", "psutil", "numba"})
        self.assertEqual(lazy, [7, 10, 29, 34, 41])

    def test_a_non_optional_import_is_never_a_finding(self):
        self.assertEqual(eager_optional_imports("import numpy\nimport os\n", {"scipy"}), [])


@needs_source
class OptionalImportsAreLazy(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.core, cls.extras = declared_dependencies()
        cls.optional = set().union(*cls.extras.values()) | SIBLING_PACKAGES
        cls.modules = _src_modules()
        cls.eager: dict[tuple[str, str], int] = {}
        cls.lazy_seen = 0
        cls.third_party: dict[str, str] = {}
        stdlib = set(sys.stdlib_module_names)
        first_party = _first_party()
        for path in cls.modules:
            rel = path.relative_to(_SRC).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for lineno, top, full, lazy in iter_imports(tree):
                if top in cls.optional:
                    if lazy:
                        cls.lazy_seen += 1
                    else:
                        cls.eager.setdefault((rel, full), lineno)
                elif top not in stdlib and top not in first_party:
                    cls.third_party.setdefault(top, f"{rel}:{lineno}")

    def test_the_inputs_are_not_empty(self):
        """Assert the readers found something before trusting their silence."""
        self.assertIn("numpy", self.core)
        self.assertIn("netCDF4", self.core)
        for group, name in (("extra", "scipy"), ("extra", "matplotlib"),
                            ("extra", "psutil"), ("jit", "numba")):
            with self.subTest(group=group, name=name):
                self.assertIn(name, self.extras.get(group, set()))
        self.assertGreaterEqual(len(self.modules), MIN_MODULES_WALKED)
        self.assertGreaterEqual(
            self.lazy_seen, MIN_LAZY_IMPORTS_SEEN,
            "the walker saw fewer lazy optional imports than the tree held when this "
            "check was written; either they were deleted (lower the floor) or the walker "
            "stopped seeing imports (fix it)")

    def test_no_optional_dependency_is_imported_at_module_level(self):
        unexplained = {f"{rel}:{line} imports {mod}"
                       for (rel, mod), line in self.eager.items()
                       if (rel, mod) not in ALLOWLIST}
        self.assertEqual(
            sorted(unexplained), [],
            "an optional dependency is imported at module level, so the module fails to "
            "import without that extra installed. Move the import into the function that "
            "uses it, or guard it with try/except ImportError.")

    def test_every_allowlist_entry_still_occurs(self):
        stale = sorted(f"{rel} imports {mod}" for rel, mod in ALLOWLIST
                       if (rel, mod) not in self.eager)
        self.assertEqual(stale, [], "allowlist entries that no longer occur; remove them "
                                    "and lower ALLOWLIST_CEILING")

    def test_the_allowlist_only_shrinks(self):
        self.assertLessEqual(len(ALLOWLIST), ALLOWLIST_CEILING)
        self.assertEqual(len(ALLOWLIST), ALLOWLIST_CEILING,
                         "an entry was removed: lower ALLOWLIST_CEILING to match")
        for key, reason in ALLOWLIST.items():
            with self.subTest(key=key):
                self.assertGreater(len(reason.strip()), 20, "an entry needs its reason")

    def test_every_third_party_import_is_declared(self):
        declared = self.core | self.optional
        undeclared = {top: where for top, where in self.third_party.items()
                      if top not in declared}
        self.assertEqual(undeclared, {},
                         "imported under src/ but declared neither as a dependency nor "
                         "in an extra of pyproject.toml")
        self.assertIn("numpy", self.third_party,
                      "the third-party sweep found no numpy import; it is not reading imports")


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
