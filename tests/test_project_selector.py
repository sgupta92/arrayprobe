# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.engine()`` -- the project-level selector.

The author's instruction was about a schematic: every drawing of this package
showed one selector box with three engines under it, and the box was labelled
``uiops.engine()`` -- which **raises** if asked for SODA-2. Rather than redraw
the picture to match a narrower selector, the selector was widened to match the
picture, and renamed so it is not called after one of the two upstreams it
spans.

So the property under test is not "the name changed". It is that **the name is
now true**: one call reaches all three engines, it still computes nothing, and
it still imports nothing until asked. A label on a diagram is only as good as
the function it names.

The three structural guards below mirror ``test_uiops_selector.py``'s, because
this module makes the same promise that one does and would fail the same way.
"""
from __future__ import annotations

import ast
import dataclasses
import subprocess
import sys
import unittest
from pathlib import Path

from tests._repo import needs_v314_engine  # noqa: E402

import arrayprobe
from arrayprobe.selector import (
    DEFAULT_ENGINE,
    ENGINES,
    Engine,
    UnknownEngine,
    engine,
)

SRC = Path(arrayprobe.__file__).resolve().parent / "selector.py"


class ItReachesEveryEngine(unittest.TestCase):
    """The point of the rename: the picture's three arrows all land."""

    @needs_v314_engine
    def test_all_three_engines_dispatch(self):
        got = {engine(name).package for name in ENGINES}
        self.assertEqual(
            got, {"arrayprobe_uiops", "arrayprobe_soda2", "arrayprobe"},
            "the selector must reach all three engines -- that is the whole "
            "reason it is not called uiops.engine()")

    def test_soda2_dispatches_here_where_uiops_refuses(self):
        """The exact contrast that made the old label wrong.

        ``uiops.engine('soda2')`` raises, and correctly so: SODA-2 is not a
        UIOOPS release. This selector answers the broader question, so it must
        not raise.
        """
        import uiops

        with self.assertRaises(uiops.UnknownVersion):
            uiops.engine("soda2")
        self.assertEqual(engine("soda2").package, "arrayprobe_soda2")

    def test_the_default_is_unchanged_by_widening_the_selector(self):
        self.assertEqual(DEFAULT_ENGINE, "3.5")
        self.assertEqual(engine().name, "3.5")
        self.assertTrue(engine().is_default)

    def test_it_is_reachable_as_the_author_named_it(self):
        """``arrayprobe.engine`` is the spelling in the instruction and in
        every schematic; the module path is an implementation detail."""
        self.assertIs(arrayprobe.engine, engine)
        self.assertIs(arrayprobe.Engine, Engine)

    @needs_v314_engine
    def test_each_engine_says_what_it_is_validated_against(self):
        for name in ENGINES:
            with self.subTest(engine=name):
                e = engine(name)
                self.assertTrue(e.validation.startswith("layer "))
                self.assertTrue(e.upstream)
        self.assertIn("layer 1", engine("3.1.4").validation,
                      "the anchor is the only layer-1 engine and must say so")

    @needs_v314_engine
    def test_load_returns_the_package_it_names(self):
        for name in ENGINES:
            with self.subTest(engine=name):
                self.assertEqual(engine(name).load().__name__,
                                 engine(name).package)


class ItRefusesRatherThanGuesses(unittest.TestCase):
    def test_an_unknown_name_raises_and_names_what_exists(self):
        with self.assertRaises(UnknownEngine) as cm:
            engine("v4")
        self.assertIn("3.5", str(cm.exception))
        self.assertIn("soda2", str(cm.exception))

    def test_it_does_not_fall_through_to_the_default(self):
        """A selector that defaults on an unrecognised name silently runs the
        wrong lineage, which is worse than an error."""
        for bad in ("uiops3", "soda3", "", "  ", "3.4.1"):
            with self.subTest(name=bad), self.assertRaises(UnknownEngine):
                engine(bad)

    def test_engines_are_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            engine().name = "soda2"  # type: ignore[misc]


class ItDispatchesAndComputesNothing(unittest.TestCase):
    """Structural guards, mirroring ``test_uiops_selector.py``.

    These are what make "it computes nothing" a checked claim rather than a
    sentence in a docstring and a caption in a manuscript.
    """

    def test_the_module_contains_no_arithmetic(self):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        # Annotations are excluded: `str | None` is a BitOp to the parser and
        # arithmetic to nobody. Everything else counts.
        annotated = set()
        for node in ast.walk(tree):
            for ann in (getattr(node, "annotation", None),
                        getattr(node, "returns", None)):
                if ann is not None:
                    annotated.update(id(n) for n in ast.walk(ann))
        bad = [
            f"{type(node.op).__name__} at line {node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, (ast.BinOp, ast.AugAssign))
            and id(node) not in annotated
        ]
        self.assertEqual(
            bad, [],
            f"the selector must contain no arithmetic; found: {bad}. If a "
            f"number is computed here, a value can change because a call came "
            f"through the selector, which is exactly what it promises not to do")

    def test_no_engine_is_imported_at_module_level(self):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        engines = {"arrayprobe_uiops", "arrayprobe_soda2"}
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            # Only module level: an import nested in a function is the point.
            if any(isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))
                   for p in ast.walk(tree) if node in ast.walk(p)
                   and p is not tree):
                continue
            names = ([a.name for a in node.names]
                     if isinstance(node, ast.Import) else [node.module or ""])
            found += [n for n in names if n.split(".")[0] in engines]
        self.assertEqual(
            found, [],
            f"an engine is imported at module level: {found}. Importing the "
            f"selector must not pull the engines into the process")

    def test_importing_the_selector_loads_no_engine(self):
        """Measured in a clean interpreter, because the assertion above reads
        the source and this one observes the behaviour -- two sides, two
        places. In-process this is untestable: the suite has already imported
        the engines. The v3.1.4 package imports the v3.5 engine's shared leaf modules
        (code both engines share lives there); the one allowlist of them is
        ``tests.test_lazy_numba_and_v35_import.V35_SHARED``, read here rather than repeated."""
        from tests.test_lazy_numba_and_v35_import import V35_SHARED

        code = (
            "import sys, arrayprobe.selector as s;"
            f"shared={sorted(V35_SHARED)!r};"
            "loaded=sorted(m for m in sys.modules "
            "if m.split('.')[0] in ('arrayprobe_uiops','arrayprobe_soda2') "
            "and m not in shared);"
            "print(','.join(loaded))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(
            out.stdout.strip(), "",
            f"importing the selector pulled in {out.stdout.strip()}")


class TheOldSelectorStillWorks(unittest.TestCase):
    """Nothing is deprecated. ``uiops.engine()`` answers a narrower question
    and keeps answering it; a reader who has it in a script is not broken."""

    @needs_v314_engine
    def test_uiops_still_dispatches_its_two(self):
        import uiops

        self.assertEqual(uiops.engine().version, "3.5")
        self.assertEqual(uiops.engine("3.1.4").version, "3.1.4")

    def test_the_two_selectors_agree_on_the_default(self):
        import uiops

        self.assertEqual(uiops.DEFAULT_VERSION, DEFAULT_ENGINE)


class WithoutTheV314Engine(unittest.TestCase):
    """Where the v3.1.4 engine is absent, both selectors refuse it by name."""

    def test_uiops_refuses_and_lists_only_v35(self):
        from unittest import mock

        import uiops

        # uiops asks the v3.5 engine, so the selector never imports the v3.1.4 package.
        with mock.patch("arrayprobe_uiops.engine_absence.engine_present", return_value=False):
            with self.assertRaises(ImportError):
                uiops.engine("3.1.4")
            self.assertEqual(uiops.versions(), ("3.5",))

    def test_project_selector_refuses_and_omits_it(self):
        from unittest import mock

        from arrayprobe.selector import engines

        with mock.patch("arrayprobe._v314_lazy.engine_present", return_value=False):
            for name in ("oracles", "3.1.4"):
                with self.subTest(name=name), self.assertRaises(ImportError):
                    arrayprobe.engine(name)
            self.assertNotIn("3.1.4", engines())


if __name__ == "__main__":
    unittest.main()
