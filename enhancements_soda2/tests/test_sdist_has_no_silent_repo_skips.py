# SPDX-License-Identifier: BSD-3-Clause
"""No shipped test may reach a path above its own distribution root.

**Why, measured 2026-09-21.** This package owns no fixtures. Its
fixture-guarded tests reach the port's tracked data by a repository-relative
path::

    FIXTURE = Path(__file__).resolve().parents[2] / "python_port" / "tests" / "data" / ...

In the repository that resolves. In an unpacked
``arrayprobe_soda2_enhancements-0.1.0/`` it points above the tarball root,
so the file is absent.

The numbers, from the unpacked sdist against a clean install on 2026-09-21:
**113 tests, 0 skipped, 33 errors** -- 32 ``FileNotFoundError``, one
``ModuleNotFoundError`` and one ``ImportError`` from a ``sys.path.insert`` of
``parents[2] / "python_port" / "gdl_oracle"``. This half of the family fails
loudly rather than skipping, which is better; the sibling package
(``arrayprobe-enhancements``) measured **749 tests, 134 skipped, 65 errors** in
the same pass and is the silent half. Either way a tarball whose suite is red
or hollow on a correct install "trains the reader to ignore red" -- the port's
own ``MANIFEST.in`` header, 2026-09-08 -- so the same rule applies to both.

**What this test is.** Two sides from different places: one is a text scan of
the shipped ``tests/`` directory for a root-escaping path expression; the other
is ``MANIFEST.in``'s own exclusion list. Inside a distribution the scan must
come back **empty** -- that is the "count of silent skips is zero" assertion,
and it holds for any recipient, on any machine, with no repository present.
In the repository the two sides must name the same set, so a module added
tomorrow with a ``parents[2]`` in it fails the suite instead of quietly
becoming the 135th skip.

This module ships deliberately: a check on what travelled has to travel.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

#: This distribution's root -- the directory holding ``pyproject.toml`` in the
#: repository, and the tarball root in an unpacked sdist. ``parents[1]``, not
#: ``parents[2]``: this module must itself obey the rule it enforces.
DIST_ROOT = Path(__file__).resolve().parents[1]
TESTS = DIST_ROOT / "tests"

#: setuptools writes ``PKG-INFO`` into an sdist root and nothing writes it into
#: a git checkout, so this is the distribution/repository discriminator and it
#: comes from the build system rather than from a flag this project sets.
IN_DISTRIBUTION = (DIST_ROOT / "PKG-INFO").is_file()

#: Repository directories that sit beside a distribution root and never inside
#: one. A string literal naming one of them is a path that leaves the tarball
#: just as surely as ``parents[2]`` does -- and it is how four modules escaped
#: this detector on its first run (2026-09-21): ``ROOT = ENH.parent`` on one
#: line and ``ROOT / "python_port" / "docs"`` on another, a two-hop spelling no
#: single-expression pattern catches.
_SIBLING_DIRECTORIES = (
    "python_port", "uioops_testing", "UIOPS-v3.1.4", "UIOPS-v3.5", "SODA2",
    "_decoded", "_build", "paper", "archive", "project",
)


def _strip_docstrings(tree: ast.AST) -> None:
    """Blank every docstring, so prose about this rule is not evidence of it."""
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            first.value.value = ""


def _escapes(text: str) -> bool:
    """True when the module's **code** reaches outside its distribution root.

    Three spellings, because the first alone missed four modules when this was
    first run (2026-09-21) -- which is itself the lesson: a detector is not
    believed until the set it returns has been checked against a real run.

    1. ``parents[N]`` for N >= 2, or ``parent.parent.parent`` -- one expression
       that climbs past the root.
    2. A string literal naming a sibling repository directory. This catches the
       two-hop spelling, where the climb and the name are on different lines.
    3. An ``import test_x`` of a sibling test module: if that module is excluded
       from the distribution, its importer cannot run there either -- measured
       as two ``unittest.loader._FailedTest`` entries.

    Docstrings are blanked first: a module that documents this rule (this one)
    quotes every pattern above, and a text scan would convict it of the thing it
    enforces. Comments never reach the AST at all.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return True  # unparseable is not a licence to pass
    _strip_docstrings(tree)

    for node in ast.walk(tree):
        # (1) the climbing expressions
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            if node.value.attr == "parents" and isinstance(node.slice, ast.Constant):
                if isinstance(node.slice.value, int) and node.slice.value >= 2:
                    return True
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            inner = node.value
            if (isinstance(inner, ast.Attribute) and inner.attr == "parent"
                    and isinstance(inner.value, ast.Attribute)
                    and inner.value.attr == "parent"):
                return True
        # (2) a sibling repository directory named as a path segment
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(s in _SIBLING_DIRECTORIES for s in re.split(r"[\\/]", node.value)):
                return True
        # (3) importing a sibling test module
        if isinstance(node, ast.Import):
            if any(a.name.startswith("test_") for a in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("test_"):
                return True
    return False


def _root_escaping_modules() -> list[str]:
    """Every shipped ``tests/test_*.py`` that reaches above the root.

    This module itself is exempt from rule 2 and only rule 2: it IS the
    detector, so it names the sibling directories as ordinary code
    constants, which is exactly the pattern rule 2 looks for. Rules 1 and 3
    still apply to it, and ``DIST_ROOT`` above is deliberately
    ``parents[1]``.
    """
    here = Path(__file__).name
    return sorted(
        p.name for p in TESTS.glob("test_*.py")
        if p.name != here
        and _escapes(p.read_text(encoding="utf-8", errors="replace"))
    )


def _manifest_exclusions() -> list[str]:
    """The ``exclude tests/…`` names in this distribution's MANIFEST.in."""
    manifest = DIST_ROOT / "MANIFEST.in"
    names = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("exclude tests/"):
            names.append(stripped.split("/", 1)[1])
    return sorted(names)


class TheDetectorItselfFires(unittest.TestCase):
    """A guard nobody has seen fire is not a guard -- so fire it here.

    This runs everywhere, including inside a tarball where there may be
    nothing left to find, so the sweep below can never pass because the
    detector silently stopped matching.
    """

    def test_it_matches_every_spelling_that_leaves_the_root(self):
        self.assertTrue(_escapes('X = Path(__file__).resolve().parents[2] / "d"'))
        self.assertTrue(_escapes("X = Path(__file__).resolve().parent.parent.parent"))
        self.assertTrue(_escapes("sys.path.insert(0, str(P.parents[3]))"))
        self.assertTrue(_escapes('X = ROOT / "python_port" / "tests" / "data"'))
        self.assertTrue(_escapes("import test_outoffocus"))
        self.assertTrue(_escapes("from test_outoffocus import helper"))

    def test_it_does_not_match_a_path_that_stays_inside(self):
        self.assertFalse(_escapes("DIST = Path(__file__).resolve().parents[1]"))
        self.assertFalse(_escapes("HERE = Path(__file__).resolve().parent.parent"))
        self.assertFalse(_escapes('X = DIST / "tests" / "data"'))
        self.assertFalse(_escapes("import unittest"))

    def test_it_ignores_prose(self):
        """Otherwise this very module convicts itself for documenting the rule."""
        self.assertFalse(_escapes('"""Mentions parents[2] and python_port."""\nx = 1\n'))
        self.assertFalse(_escapes("x = 1  # parent.parent.parent in a comment\n"))


class NoShippedTestReachesOutsideTheTarball(unittest.TestCase):
    def test_the_scan_finds_the_tests_directory(self):
        """Otherwise the sweep below is vacuous on an empty glob."""
        self.assertTrue(TESTS.is_dir(), f"{TESTS} is not a directory")
        self.assertGreater(
            len(list(TESTS.glob("test_*.py"))), 0,
            f"no test modules found under {TESTS}; the sweep would pass vacuously")

    def test_no_shipped_module_depends_on_a_path_outside_the_distribution(self):
        offenders = _root_escaping_modules()
        if IN_DISTRIBUTION:
            self.assertEqual(
                offenders, [],
                f"{len(offenders)} shipped test module(s) reach above the tarball root: "
                f"{offenders}. Every fixture guard in them skips for a reason that is a "
                "claim about the recipient's machine and is really a claim about the "
                "packaging -- 33 such errors were measured in this distribution, and "
                "134 silent skips in its sibling, on 2026-09-21. Either exclude the "
                "module in MANIFEST.in or give it a "
                "fixture that travels.")
        else:
            self.assertEqual(
                offenders, _manifest_exclusions(),
                "MANIFEST.in's exclusion list and the set of root-escaping test modules "
                "have diverged. Excluded but no longer escaping: "
                f"{sorted(set(_manifest_exclusions()) - set(offenders))}; escaping but "
                f"not excluded: {sorted(set(offenders) - set(_manifest_exclusions()))}. "
                "The list is derived, not typed -- regenerate it rather than adding a "
                "name, or the list goes stale the way the port's did (audit 2026-09-21 "
                "§3.6).")

    def test_every_excluded_name_exists(self):
        """A list that names a deleted module hides a real one behind it."""
        if IN_DISTRIBUTION:
            self.skipTest(
                "the excluded modules are, by construction, absent from a distribution; "
                "this direction is a repository check and says so rather than claiming "
                "a fact about the machine")
        for name in _manifest_exclusions():
            with self.subTest(module=name):
                self.assertTrue(
                    (TESTS / name).is_file(),
                    f"MANIFEST.in excludes tests/{name}, which does not exist")


if __name__ == "__main__":
    unittest.main()
