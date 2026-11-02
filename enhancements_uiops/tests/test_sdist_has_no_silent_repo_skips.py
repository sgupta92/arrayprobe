# SPDX-License-Identifier: BSD-3-Clause
"""No shipped test may reach a path above its own distribution root.

**Why, measured 2026-09-21.** This package owns no fixtures. Its
fixture-guarded tests reach the port's tracked data by a repository-relative
path::

    FIXTURE = Path(__file__).resolve().parents[2] / "python_port" / "tests" / "data" / ...

In the repository that resolves. In an unpacked
``arrayprobe_enhancements-0.1.0/`` it points above the tarball root, so
the file is absent and the ``skipUnless`` guard fires -- with a reason that is
a claim about the machine ("tracked dense raw fixture not present") for a
cause that is not about the machine. The recipient sees a green-ish suite that
checked far less than it says.

The number, from the unpacked sdist against a clean install: **749 tests, 134
skipped, 65 errors**, against the same suite's repository run. That is the
2026-09-08 failure shape the port's ``MANIFEST.in`` header records, never
carried across to the two packages split out later, and the fifth member of
this repository's guards-that-match-nothing family.

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
        # (4) the vendored-upstream resolver: `_upstream.source(...)` reads a
        # UIOPS/SODA-2 source tree, and no upstream source ships in a release
        if isinstance(node, ast.Import):
            if any(a.name == "_upstream" for a in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module == "_upstream":
                return True
    # (5) a climb split across a name binding: `ROOT = Path(__file__).parents[1]`
    # then `ROOT.parent`, or `HERE = ....parent` then `HERE.parents[1]`. Each
    # expression stays inside on its own; the depth only adds up through the name.
    # Measured 2026-10-14: two modules (`_ROOT.parent / "<file name>"`,
    # `HERE.parents[1] / "src"`) escaped rules 1-3 this way.
    return _climbs_through_a_name(tree)


def _climbs_through_a_name(tree: ast.AST) -> bool:
    """True when a path expression, following module-level name bindings,
    climbs three or more levels from ``__file__`` (file -> tests -> root -> out)."""
    names: dict[str, int] = {}

    def depth(node: ast.AST) -> int | None:
        if isinstance(node, ast.Name):
            return names.get(node.id)
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "Path" and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "__file__"):
                return 0
            if isinstance(func, ast.Attribute) and func.attr in ("resolve", "absolute"):
                return depth(func.value)
            return None
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            d = depth(node.value)
            return None if d is None else d + 1
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                and node.value.attr == "parents" and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, int)):
            d = depth(node.value.value)
            return None if d is None else d + node.slice.value + 1
        return None

    assigns = sorted(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.Assign) and len(n.targets) == 1
         and isinstance(n.targets[0], ast.Name)),
        key=lambda n: n.lineno)
    for a in assigns:
        d = depth(a.value)
        if d is not None:
            names[a.targets[0].id] = d
    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            d = depth(node)
            if d is not None and d >= 3:
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


def _release_withheld_tests() -> set[str]:
    """Test modules the release allowlist keeps out of the public tree.

    Read from ``scripts/release_allowlist.txt`` in a repository checkout, where
    those modules exist on disk but the built release (and so the sdist) never
    carries them, which is why ``MANIFEST.in`` need not exclude them. Empty
    when the allowlist is absent (an unpacked sdist, or a built release tree):
    there every escaping module must be excluded by name.
    """
    allowlist = DIST_ROOT.parent / "scripts" / "release_allowlist.txt"
    if not allowlist.is_file():
        return set()
    prefix = "!" + DIST_ROOT.name + "/tests/"
    withheld = set()
    for line in allowlist.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            name = line[len(prefix):].split("	", 1)[0].strip()
            if "/" not in name:
                withheld.add(name)
    return withheld


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
        # (4) and (5), added 2026-10-14 after two modules escaped rules 1-3
        self.assertTrue(_escapes("import _upstream\nX = _upstream.source('uiops35')"))
        self.assertTrue(_escapes(
            'R = Path(__file__).resolve().parents[1]\nD = R.parent / "NOTES.md"'))
        self.assertTrue(_escapes(
            "H = Path(__file__).resolve().parent\nsys.path.insert(0, str(H.parents[1]))"))
        self.assertTrue(_escapes(
            "E = Path(__file__).resolve().parents[1]\nROOT = E.parent"))

    def test_it_does_not_match_a_path_that_stays_inside(self):
        self.assertFalse(_escapes("DIST = Path(__file__).resolve().parents[1]"))
        self.assertFalse(_escapes("HERE = Path(__file__).resolve().parent.parent"))
        self.assertFalse(_escapes('X = DIST / "tests" / "data"'))
        self.assertFalse(_escapes("import unittest"))
        self.assertFalse(_escapes(
            'H = Path(__file__).resolve().parent\nS = H.parent / "src"\nD = H / "data"'))
        self.assertFalse(_escapes(
            'E = Path(__file__).resolve().parents[1]\nS = E / "src" / "pkg"'))

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
                "packaging -- 134 such skips were measured in this distribution on "
                "2026-09-21. Either exclude the module in MANIFEST.in or give it a "
                "fixture that travels.")
        else:
            # A root-escaping module the release allowlist withholds exists in a
            # repository checkout but never reaches the built tree or the sdist,
            # so MANIFEST.in need not name it.
            expected = sorted(set(offenders) - _release_withheld_tests()
                              | (set(offenders) & set(_manifest_exclusions())))
            self.assertEqual(
                expected, _manifest_exclusions(),
                "MANIFEST.in's exclusion list and the set of root-escaping test modules "
                "have diverged. Excluded but no longer escaping: "
                f"{sorted(set(_manifest_exclusions()) - set(offenders))}; escaping but "
                f"neither excluded nor withheld by the release allowlist: "
                f"{sorted(set(offenders) - set(_manifest_exclusions()) - _release_withheld_tests())}. "
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
