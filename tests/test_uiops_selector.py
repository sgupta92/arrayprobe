# SPDX-License-Identifier: BSD-3-Clause
"""``uiops``'s catalogue, checked against the two vendored MATLAB trees.

The selector's whole value is that it tells a user something they could not
otherwise find out: for any given module, does asking for v3.5 get them a v3.5
translation, or the v3.1.4 one reused because the MATLAB source never changed?
A catalogue that answered that from memory would be worse than no catalogue,
because it would be believed.

**Two sides, and neither is generated from the other.** One is
``uiops.CATALOGUE``'s classification per module. The other is
``sha256`` over ``UIOPS-v3.1.4/`` and ``UIOPS-v3.5/``, both vendored and
tracked, plus the set of ``.py`` files actually on disk in each package. A
``SHARED`` row whose source diverged, an ``OVERRIDDEN`` row whose source turns
out to be byte-identical, a ``FORK_ONLY`` row whose file is in fact in a stock
release: each is a failure here rather than a sentence somebody has to notice.

The one row that cannot be hashed says so and names the line that established
it -- ``READ_SHARED`` -- and this file asserts that such a row is rare and
cited rather than a hole anybody can widen.
"""
from __future__ import annotations

import ast
import hashlib
import unittest
from pathlib import Path

from tests import _upstream  # noqa: E402
from tests._repo import PKG_ROOT, repo_only  # noqa: E402

import uiops

ROOT = Path(__file__).resolve().parents[1]
SRC = PKG_ROOT / "src"
V314_TREE = _upstream.source("uiops314")
V35_TREE = _upstream.source("uiops35")


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops314")
    _upstream.require("uiops35")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _port_modules() -> set[str]:
    """Every module of the v3.1.4 port, as the catalogue names them.

    ``readers/spec.py`` -> ``readers.spec``; the package root ->
    the empty string. Read from the filesystem, so a new module joins by
    existing rather than by being remembered.
    """
    pkg = SRC / "arrayprobe"
    out = set()
    for p in pkg.rglob("*.py"):
        rel = p.relative_to(pkg).with_suffix("")
        parts = [q for q in rel.parts if q != "__init__"]
        out.add(".".join(parts))
    return out


#: Present in the development repository, absent from a release tree (it does not ship).
ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"
#: The documentation builder ships in both trees; its ``MODULES_HELD_BACK`` names the
#: modules held back from the release, and itself checks them against the allow-list.
APIDOC = ROOT / "docs" / "_build" / "apidoc.py"


def _v314_engine_present() -> bool:
    from arrayprobe._v314_lazy import engine_present
    return engine_present()


def _apidoc_held_back(package: str = "arrayprobe") -> set[str]:
    """``MODULES_HELD_BACK``'s modules of ``package``, as catalogue names.

    Read as a literal from the shipped builder's source rather than by importing it,
    so this test does not run the documentation build's import-time state."""
    tree = ast.parse(APIDOC.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == "MODULES_HELD_BACK"):
            held = ast.literal_eval(node.value)
            break
    else:
        raise AssertionError(f"{APIDOC} defines no MODULES_HELD_BACK")
    out = set()
    for pkg, module in held:
        if pkg == package:
            parts = [q for q in Path(module).with_suffix("").parts if q != "__init__"]
            out.add(".".join(parts))
    return out


def release_held_back(catalogue=None, *, allowlist: Path = ALLOWLIST,
                      engine_present: bool | None = None) -> set[str]:
    """Catalogue rows whose module a release tree may lack, because the release holds it back.

    Empty where the allow-list is present (the development tree), so there the catalogue
    and the disk must agree exactly. In a release tree: every ``OVERRIDDEN`` row when the
    v3.1.4 engine is absent (the release omits that engine, and an ``OVERRIDDEN`` row is
    by definition one the v3.5 engine translates itself), plus the ``arrayprobe`` modules
    the shipped ``docs/_build/apidoc.py`` holds back. A ``SHARED``, ``TOOLING`` or other
    row that is not held back is never excused."""
    if allowlist.is_file():
        return set()
    catalogue = uiops.CATALOGUE if catalogue is None else catalogue
    if engine_present is None:
        engine_present = _v314_engine_present()
    held = set() if engine_present else {
        n for n, e in catalogue.items() if e.state == uiops.OVERRIDDEN}
    return held | (_apidoc_held_back() & set(catalogue))


def gone_entries(catalogue, on_disk: set[str], excused: set[str] = frozenset()) -> list[str]:
    """Catalogue rows with no module on disk, less those in ``excused``."""
    return sorted(set(catalogue) - on_disk - set(excused))


class TheCatalogueCoversThePortExactly(unittest.TestCase):
    def test_every_module_on_disk_is_classified(self):
        missing = sorted(_port_modules() - set(uiops.CATALOGUE))
        self.assertEqual(
            missing, [],
            "these v3.1.4-port modules are not in uiops.CATALOGUE, so the "
            "selector cannot say what the v3.5 engine does about them: "
            f"{missing}")

    @repo_only  # reads scripts/release_allowlist.txt, which an sdist omits
    def test_no_entry_names_a_module_that_is_gone(self):
        extra = gone_entries(uiops.CATALOGUE, _port_modules(), release_held_back())
        self.assertEqual(extra, [],
                         f"catalogue entries with no module on disk: {extra}")

    @repo_only  # reads scripts/release_allowlist.txt, which an sdist omits
    def test_the_development_view_excuses_no_absent_module(self):
        """With the allow-list present, a catalogued module missing from disk still fails."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            allow = Path(tmp) / "release_allowlist.txt"
            allow.write_text("src/arrayprobe/**\tshared tooling\n", encoding="utf-8")
            excused = release_held_back(allowlist=allow, engine_present=False)
        self.assertEqual(excused, set())
        on_disk = set(uiops.CATALOGUE) - {"reject", "lwc"}
        self.assertEqual(gone_entries(uiops.CATALOGUE, on_disk, excused), ["lwc", "reject"])

    @repo_only  # reads scripts/release_allowlist.txt, which an sdist omits
    def test_the_release_view_excuses_only_held_back_modules(self):
        """Without the allow-list, an absent OVERRIDDEN row is excused only when the v3.1.4
        engine is absent, and a SHARED row (``lwc``) never is."""
        missing = Path(ROOT / "no_such_dir" / "release_allowlist.txt")
        on_disk = set(uiops.CATALOGUE) - {"reject", "lwc"}
        absent = release_held_back(allowlist=missing, engine_present=False)
        self.assertIn("reject", absent)
        self.assertNotIn("lwc", absent)
        self.assertEqual(gone_entries(uiops.CATALOGUE, on_disk, absent), ["lwc"])
        present = release_held_back(allowlist=missing, engine_present=True)
        self.assertNotIn("reject", present)
        self.assertEqual(gone_entries(uiops.CATALOGUE, on_disk, present), ["lwc", "reject"])
        self.assertLessEqual(_apidoc_held_back() & set(uiops.CATALOGUE), present)

    def test_there_are_enough_entries_to_be_checking_something(self):
        self.assertGreaterEqual(len(uiops.CATALOGUE), 40)

    def test_every_override_target_imports(self):
        import importlib
        for name, entry in uiops.CATALOGUE.items():
            if not entry.v35:
                continue
            with self.subTest(name):
                self.assertIsNotNone(importlib.import_module(entry.v35))


class TheClassificationsAgreeWithTheVendoredTrees(unittest.TestCase):
    """The measured side. Both trees are tracked, so in a checkout this never
    skips; an unpacked sdist does not carry them, and the methods that read
    them skip there."""

    @repo_only
    def test_both_trees_are_present(self):
        self.assertTrue(V314_TREE.is_dir(), f"{V314_TREE} is missing")
        self.assertTrue(V35_TREE.is_dir(), f"{V35_TREE} is missing")

    @repo_only
    def test_shared_rows_name_sources_that_are_byte_identical(self):
        wrong = []
        for name, entry in uiops.CATALOGUE.items():
            if entry.state != uiops.SHARED:
                continue
            if not entry.sources:
                wrong.append(f"{name}: SHARED but names no source file")
                continue
            for src in entry.sources:
                a, b = V314_TREE / src, V35_TREE / src
                if not a.is_file() or not b.is_file():
                    wrong.append(f"{name}: {src} is not in both stock trees")
                elif _sha256(a) != _sha256(b):
                    wrong.append(
                        f"{name}: {src} DIVERGED between v3.1.4 and v3.5, so "
                        f"reusing the v3.1.4 translation for v3.5 is no longer "
                        f"licensed -- it needs its own translation")
        self.assertEqual(sorted(wrong), [], "; ".join(sorted(wrong)))

    @repo_only
    def test_overridden_rows_name_a_source_that_actually_changed(self):
        """An override whose source turns out identical is wasted work at
        best and a second, divergent translation of the same file at worst."""
        wrong = []
        for name, entry in uiops.CATALOGUE.items():
            if entry.state != uiops.OVERRIDDEN:
                continue
            if not entry.sources:
                wrong.append(f"{name}: OVERRIDDEN but names no source file")
                continue
            changed = False
            for src in entry.sources:
                a, b = V314_TREE / src, V35_TREE / src
                if not a.is_file() or not b.is_file():
                    changed = True          # present in one release only
                elif _sha256(a) != _sha256(b):
                    changed = True
            if not changed:
                wrong.append(
                    f"{name}: every source of an OVERRIDDEN row "
                    f"({', '.join(entry.sources)}) is byte-identical between "
                    f"the releases, so v3.5 needs no separate translation")
        self.assertEqual(sorted(wrong), [], "; ".join(sorted(wrong)))

    @repo_only
    def test_fork_only_rows_name_files_in_no_stock_release(self):
        wrong = []
        for name, entry in uiops.CATALOGUE.items():
            if entry.state != uiops.FORK_ONLY:
                continue
            for src in entry.sources:
                where = [t.name for t in (V314_TREE, V35_TREE)
                         if (t / src).is_file()]
                if where:
                    wrong.append(
                        f"{name}: {src} IS in stock UIOPS ({where}), so this "
                        f"is not fork-only -- reclassify it")
        self.assertEqual(sorted(wrong), [], "; ".join(sorted(wrong)))

    def test_tooling_rows_name_no_matlab_source(self):
        wrong = [n for n, e in uiops.CATALOGUE.items()
                 if e.state == uiops.TOOLING and e.sources]
        self.assertEqual(wrong, [],
                         f"TOOLING rows that name a MATLAB source: {wrong}")

    def test_only_overridden_or_borrowed_fork_only_rows_name_a_v35_module(self):
        # A FORK_ONLY row may name a v3.5 module since 2026-09-13: `combine` is
        # the fork's combine borrowed for v3.5, opt-in. TOOLING,
        # SHARED and READ_SHARED rows never may -- one implementation serves both.
        allowed = (uiops.OVERRIDDEN, uiops.FORK_ONLY)
        wrong = [n for n, e in uiops.CATALOGUE.items()
                 if e.state not in allowed and e.v35]
        self.assertEqual(
            wrong, [],
            f"rows naming a v3.5 module outside OVERRIDDEN/borrowed-FORK_ONLY: {wrong}")
        borrowed = [n for n, e in uiops.CATALOGUE.items()
                    if e.state == uiops.FORK_ONLY and e.v35]
        self.assertEqual(borrowed, ["combine"],
                         "a new borrowed FORK_ONLY row needs its own opt-in and label")

    def test_the_unhashable_row_is_rare_and_cited(self):
        """``READ_SHARED`` is the one state a measurement cannot settle, so it
        is the one an inattentive edit could widen into a hole. Each such row
        must cite what established it, and there must be few of them."""
        rows = {n: e for n, e in uiops.CATALOGUE.items()
                if e.state == uiops.READ_SHARED}
        self.assertLessEqual(
            len(rows), 3,
            f"READ_SHARED is the state no hash can check; {len(rows)} rows is "
            f"too many to be exceptions: {sorted(rows)}")
        uncited = [n for n, e in rows.items() if ".py:" not in e.note]
        self.assertEqual(
            uncited, [],
            f"READ_SHARED rows citing no file:line that established them: "
            f"{uncited}")


class SelectingAVersion(unittest.TestCase):
    def test_the_default_is_v35(self):
        self.assertEqual(uiops.DEFAULT_VERSION, "3.5")
        self.assertEqual(uiops.engine().version, "3.5")
        self.assertTrue(uiops.engine().is_default)

    def test_v314_is_still_selectable(self):
        """The author's decision of 2026-09-12: it remains an option."""
        eng = uiops.engine("3.1.4")
        self.assertEqual(eng.version, "3.1.4")
        self.assertFalse(eng.is_default)

    def test_soda2_is_refused_with_a_pointer(self):
        with self.assertRaises(uiops.UnknownVersion) as caught:
            uiops.engine("soda2")
        self.assertIn("arrayprobe_soda2", str(caught.exception))

    def test_an_unknown_version_is_refused(self):
        with self.assertRaises(uiops.UnknownVersion):
            uiops.engine("3.3")

    def test_an_unknown_module_is_refused(self):
        with self.assertRaises(uiops.UnknownModule):
            uiops.engine().module("no_such_module")


class DispatchGoesWhereTheCatalogueSays(unittest.TestCase):
    def test_an_overridden_module_differs_between_the_engines(self):
        self.assertEqual(uiops.engine("3.5").dotted("reject"),
                         "arrayprobe_uiops.reject")
        self.assertEqual(uiops.engine("3.1.4").dotted("reject"),
                         "arrayprobe.reject")

    def test_a_shared_module_is_the_same_object_for_both(self):
        """Not merely the same name -- the same imported module, since the
        point of SHARED is that there is one translation."""
        self.assertIs(uiops.engine("3.5").module("lwc"),
                      uiops.engine("3.1.4").module("lwc"))

    @unittest.skipIf(not ALLOWLIST.is_file() and not _v314_engine_present(),
                     "release tree without the v3.1.4 engine: "
                     "test_v314_reports_its_absence_by_name checks it instead")
    def test_get_reaches_a_real_callable(self):
        fn = uiops.engine("3.1.4").get("reject", "calculate_reject_unified")
        self.assertTrue(callable(fn))

    @unittest.skipIf(ALLOWLIST.is_file() or _v314_engine_present(),
                     "the v3.1.4 engine is present here")
    def test_v314_reports_its_absence_by_name(self):
        from arrayprobe_uiops.engine_absence import V314EngineAbsent
        with self.assertRaises(V314EngineAbsent):
            uiops.engine("3.1.4").get("reject", "calculate_reject_unified")

    @unittest.skipIf(not ALLOWLIST.is_file() and not _v314_engine_present(),
                     "release tree without the v3.1.4 engine: "
                     "test_v314_reports_its_absence_by_name checks it instead")
    def test_the_two_engines_really_are_different_code(self):
        """A selector that dispatched everything to one engine would pass
        every naming test above and mean nothing."""
        a = uiops.engine("3.1.4").get("reject", "calculate_reject_unified")
        b = uiops.engine("3.5").get("reject", "calculate_reject_unified")
        self.assertIsNot(a, b)

    def test_v314_overrides_nothing(self):
        self.assertEqual(uiops.engine("3.1.4").overrides(), ())
        self.assertGreaterEqual(len(uiops.engine("3.5").overrides()), 6)

    def test_the_catalogue_renders_for_both_engines(self):
        for version in uiops.VERSIONS:
            cat = uiops.engine(version).catalogue()
            self.assertEqual(set(cat), set(uiops.CATALOGUE))
            self.assertTrue(all(len(line) > 20 for line in cat.values()))


class TheDifferenceBetweenDefaultAndAuthoritativeIsStated(unittest.TestCase):
    """"Default" and "what the layer-1 claim rests on" are different engines
    here, deliberately. A user who read only the default would conclude the
    wrong thing, so selection says it at the point of selection."""

    def test_v314_is_named_as_the_layer_1_engine(self):
        text = uiops.engine("3.1.4").validation
        self.assertIn("layer 1", text)
        self.assertIn("archived", text)

    def test_v35_states_its_ceiling(self):
        text = uiops.engine("3.5").validation
        self.assertIn("layer 2", text)
        self.assertIn("never will be", text)


class TheSelectorComputesNothing(unittest.TestCase):
    """It dispatches. A number must not change because a call came through
    here, and the only way to keep that true is for this package to contain no
    arithmetic at all."""

    def test_the_module_defines_no_numeric_work(self):
        tree = ast.parse((SRC / "uiops" / "__init__.py").read_text(
            encoding="utf-8"))
        # Arithmetic operators only. `str | None` is a BinOp too (PEP 604
        # union, BitOr) and appears twice in the annotations -- a check that
        # counted those would fail on a type hint and teach the next person
        # to delete it.
        arithmetic = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                      ast.Mod, ast.Pow)
        offending = [
            ast.unparse(n) for n in ast.walk(tree)
            if (isinstance(n, ast.BinOp) and isinstance(n.op, arithmetic))
            or (isinstance(n, ast.AugAssign) and isinstance(n.op, arithmetic))]
        self.assertEqual(
            offending, [],
            f"uiops contains arithmetic ({offending}); it is a dispatcher and "
            f"must stay one")

    def test_that_check_fires_on_arithmetic(self):
        """Executed, not read: the narrowing above must not have narrowed the
        check to nothing."""
        tree = ast.parse("x = 2 + 2\ny: int | None = None\n")
        arithmetic = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                      ast.Mod, ast.Pow)
        found = [ast.unparse(n) for n in ast.walk(tree)
                 if isinstance(n, ast.BinOp) and isinstance(n.op, arithmetic)]
        self.assertEqual(found, ["2 + 2"],
                         "the arithmetic check no longer sees arithmetic, or "
                         "now sees PEP 604 unions again")

    def test_it_imports_neither_engine_at_module_level(self):
        """Importing ``uiops`` must not drag in both engines -- the dispatch
        is by name, resolved when a module is actually asked for."""
        tree = ast.parse((SRC / "uiops" / "__init__.py").read_text(
            encoding="utf-8"))
        imported = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(
            imported & {"arrayprobe", "arrayprobe_uiops", "arrayprobe_soda2"},
            set(),
            f"uiops imports an engine at module level: {sorted(imported)}")


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite.
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
