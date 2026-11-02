# SPDX-License-Identifier: BSD-3-Clause
"""``applicability.py``'s declarations, checked against places it did not write.

The requirement (2026-09-12) is a final state in which a user is not left
*"not knowing what functions/enhancements apply to what"*. The declaration
answers that; this file is what keeps the declaration true.

**Three sides, three sources.**

1. The set of modules declared, against the ``.py`` files actually shipped --
   so a new enhancement cannot land without saying which engines it covers.
2. The ``SUPERSEDED`` set, against the hand-read
   *"already fixed in v3.5"* table -- a document in the other package,
   maintained by a different act (reading v3.5's source), which is the only
   thing that can establish a fix. Neither side is generated from the other.
3. The ``UNESTABLISHED`` set, against ``classify_findings_v35.py`` run live on
   the vendored v3.5 tree -- these rows exist *because* the classifier could
   not locate the construct, and if it starts locating one the row is wrong in
   whichever direction and must be re-read.

The hazard being guarded is concrete: four of these modules correct defects the
UIOOPS developers fixed themselves in v3.5, so running one there produces a
silently double-corrected number. That is worse than a crash and worse than a
no-op, and no amount of documentation prevents it.

Sides two and three read sources the release does not carry, so they run from
``test_engine_applicability_dev.py``.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from arrayprobe_enhancements import applicability as app

_WIDE_HOLLOW_ON_DISK = (Path(app.__file__).parent / "wide_hollow_fix.py").exists()
_NEEDS_V314 = "needs the v3.1.4 engine, which this distribution omits"

ENH = Path(__file__).resolve().parents[1]
ROOT = ENH.parent
SRC = ENH / "src" / "arrayprobe_enhancements"

#: Files in the package that are not enhancements. Mirrors
#: ``test_publish_ready.py``'s ``_NOT_ENHANCEMENTS`` -- infrastructure, not a
#: correction anybody can switch on. ``pipeline`` joined 2026-09-14: the driver that
#: applies whichever enhancements ``registry``/``applicability`` resolve ON, not itself one.
NOT_ENHANCEMENTS = {"__init__", "registry", "applicability", "pipeline"}


def _shipped_modules() -> set[str]:
    return {p.stem for p in SRC.glob("*.py") if p.stem not in NOT_ENHANCEMENTS}


class EveryShippedModuleDeclaresItsEngines(unittest.TestCase):
    def test_the_declaration_covers_exactly_what_ships(self):
        declared = set(app.APPLICABILITY)
        shipped = _shipped_modules()
        self.assertEqual(
            sorted(declared - shipped), [],
            "declared but not shipped -- a declaration must not outlive its "
            "module")
        self.assertEqual(
            sorted(shipped - declared), [],
            "shipped with no engine applicability declared. Every enhancement "
            "must say which engines it is for; see applicability.py")

    def test_there_are_enough_of_them_to_be_checking_something(self):
        self.assertGreaterEqual(len(app.APPLICABILITY), 30)

    def test_every_entry_covers_every_engine(self):
        missing = {n: sorted(set(app.ENGINES) - set(e.state))
                   for n, e in app.APPLICABILITY.items()
                   if set(app.ENGINES) - set(e.state)}
        self.assertEqual(missing, {},
                         f"entries silent about an engine: {missing}")

    def test_every_entry_says_how_it_was_established(self):
        thin = [n for n, e in app.APPLICABILITY.items() if len(e.basis) < 25]
        self.assertEqual(thin, [], f"entries with no real basis line: {thin}")

    def test_every_superseded_row_says_how_to_get_the_upstream_fix(self):
        """Author's instruction, 2026-09-12: *"for the findings from 314 that
        are fixed in 35, we use the fixes from 35 port. and apply them."* A row
        that says only "superseded" leaves a v3.1.4 user with a correction the
        developers have already improved on and no route to theirs. Each must
        say which -- a delegation, or the plain fact that there is nothing to
        borrow and the answer is to run the v3.5 engine."""
        silent = [n for n, e in app.APPLICABILITY.items()
                  if e.state.get("3.5") == app.SUPERSEDED
                  and len(e.upstream_route) < 40]
        self.assertEqual(
            silent, [],
            f"superseded rows with no upstream route declared: {silent}")

    #: The verdicts a superseded row may carry. A closed set, so a row cannot
    #: acquire a vague fifth answer -- and each is a claim someone measured,
    #: which `tests/test_superseded_corrections_on_the_merits.py` re-measures.
    VERDICTS = ("COMPOSED FROM BOTH", "EQUIVALENT:", "THEIRS IS BETTER",
                "OURS IS BETTER", "DELEGATES to")

    def test_each_route_carries_one_of_the_allowed_verdicts(self):
        """Author, 2026-09-12: *"we use the better correction, not the 3.5
        correction blankly."* So each row states which is better and why, and
        the vocabulary is closed so "it's complicated" cannot become an
        answer."""
        vague = [n for n, e in app.APPLICABILITY.items()
                 if e.state.get("3.5") == app.SUPERSEDED
                 and not e.upstream_route.startswith(self.VERDICTS)]
        self.assertEqual(vague, [], f"routes carrying no verdict: {vague}")

    def test_the_verdicts_are_not_all_the_same(self):
        """If every row said the same thing, a rule would have done and the
        per-row measurement would be theatre. Three distinct answers across
        four rows is what makes it worth doing."""
        # The declarations are the subject, so the rows of modules this distribution omits
        # (applicability.OMITTED_APPLICABILITY) still count: the table states them.
        declared = {**app.APPLICABILITY, **app.OMITTED_APPLICABILITY}
        seen = {v for v in self.VERDICTS
                for e in declared.values()
                if e.state.get("3.5") == app.SUPERSEDED
                and e.upstream_route.startswith(v)}
        self.assertGreaterEqual(
            len(seen), 3,
            f"the superseded rows now carry {len(seen)} distinct verdict(s): "
            f"{sorted(seen)}")

    @unittest.skipUnless(_WIDE_HOLLOW_ON_DISK, _NEEDS_V314)
    def test_a_composed_route_is_neither_ours_nor_theirs(self):
        """A row claiming a composition must actually differ from both parents,
        or "composed" is a word covering a plain delegation. Three sides: the
        route string, the registry, and the two implementations it names."""
        import numpy as np
        from arrayprobe_uiops.reject import is_it_hollow as upstream

        from arrayprobe_enhancements import registry
        from arrayprobe_enhancements.wide_hollow_fix import wide_is_it_hollow

        composed = [n for n, e in app.APPLICABILITY.items()
                    if e.upstream_route.startswith("COMPOSED FROM BOTH")]
        self.assertEqual(composed, ["wide_hollow_fix"])
        fn = registry.entry_point("wide_hollow_fix")

        # Structured particles: uniform noise does not exercise the guard the
        # composition declines, which is recorded at length in
        # tests/test_wide_hollow_vs_upstream.py.
        rng = np.random.default_rng(5)
        differs_from_ours = differs_from_theirs = 0
        for _ in range(600):
            w, n = 64, int(rng.integers(4, 14))
            lit = np.zeros((n, w), dtype=bool)
            for i in range(n):
                lit[i, int(rng.integers(0, w // 3 + 1)):
                       int(rng.integers(2 * w // 3, w))] = True
                g = int(rng.integers(1, w - 2))
                lit[i, g:g + int(rng.integers(1, 4))] = False
            s = ~lit
            got = tuple(fn(s, n, w))
            differs_from_ours += got != tuple(wide_is_it_hollow(s, n, w))
            differs_from_theirs += got != tuple(upstream(s, n))
        self.assertGreater(differs_from_ours, 0,
                           "the composition equals our original everywhere")
        self.assertGreater(differs_from_theirs, 0,
                           "the composition equals v3.5 everywhere, so it is a "
                           "delegation wearing another name")

    def test_a_superseded_entry_names_the_v35_line_that_fixed_it(self):
        """A claim that upstream fixed something is checkable or it is
        nothing. Each must name where."""
        unsourced = [n for n, e in app.APPLICABILITY.items()
                     if app.SUPERSEDED in e.state.values() and not e.v35_site]
        self.assertEqual(unsourced, [],
                         f"superseded without a v3.5 site: {unsourced}")


class TheRefusalActuallyRefuses(unittest.TestCase):
    """The guard is executed, not read (four checks here have matched nothing
    while reading fine)."""

    @unittest.skipUnless(_WIDE_HOLLOW_ON_DISK, _NEEDS_V314)
    def test_a_superseded_enhancement_is_refused_on_v35(self):
        with self.assertRaises(app.NotApplicableToEngine) as caught:
            app.check("wide_hollow_fix", "3.5")
        message = str(caught.exception)
        self.assertIn("superseded", message)
        self.assertIn("calculate_reject_unified.m:374", message)
        self.assertIn("already-corrected value", message)

    def test_the_same_enhancement_is_allowed_on_v314(self):
        app.check("reshape_fix", "3.1.4")
        self.assertTrue(app.applicable("reshape_fix", "3.1.4"))

    def test_an_unestablished_enhancement_is_refused_on_v35(self):
        """No shipped module is UNESTABLISHED any more (the v3.5 read all five
        the classifier missed against the v3.5 source directly), so this
        exercises the refusal mechanism itself via a synthetic entry rather
        than naming a real module that is no longer in that state."""
        synthetic = app.Applicability(
            finding="TEST-ONLY", state={"3.1.4": app.APPLIES},
            basis="synthetic row for this test only")
        with mock.patch.dict(app.APPLICABILITY,
                              {"_test_only_unestablished": synthetic}):
            with self.assertRaises(app.NotApplicableToEngine) as caught:
                app.check("_test_only_unestablished", "3.5")
        self.assertIn("unestablished", str(caught.exception))

    def test_a_variant_only_enhancement_is_refused_on_v35(self):
        with self.assertRaises(app.NotApplicableToEngine) as caught:
            app.check("mask_presence_fix", "3.5")
        message = str(caught.exception)
        self.assertIn("variant-only", message)
        self.assertIn("field campaign's modified UIOOPS", message)

    def test_a_read_row_is_allowed_on_v35(self):
        app.check("hole_edge_swap", "3.5")

    def test_a_live_enhancement_passes_on_both(self):
        for engine in app.ENGINES:
            app.check("spot_edge_fix", engine)

    def test_soda2_is_not_an_engine_here(self):
        """The author's decision of 2026-09-12: SODA-2 is a separate tool, not
        a version of the same call."""
        with self.assertRaises(app.UnknownEngine):
            app.applicable("spot_edge_fix", "soda2")

    def test_an_undeclared_name_raises_rather_than_defaulting(self):
        with self.assertRaises(KeyError):
            app.applicable("no_such_enhancement")

    def test_the_default_engine_is_v35(self):
        self.assertEqual(app.DEFAULT_ENGINE, "3.5")
        self.assertFalse(app.applicable("reshape_fix"))
        self.assertTrue(app.applicable("reshape_fix", "3.1.4"))

    def test_for_engine_splits_the_set(self):
        on_314 = app.for_engine("3.1.4")
        on_35 = app.for_engine("3.5")
        self.assertTrue(all(on_314.values()),
                        "every enhancement here was written for v3.1.4")
        self.assertLess(sum(on_35.values()), len(on_35),
                        "some enhancements must be refused on v3.5, or this "
                        "whole module is a no-op")


class RegisterEngineHook(unittest.TestCase):
    """``register_engine`` (2026-09-14) -- for a *future* UIOOPS-family
    lineage that shares ``pipeline.py``'s driver. Never for SODA-2 (design record fact 0.8): its own isolation test,
    ``enhancements_soda2/tests/test_lineage_isolation.py``, forbids importing
    this module at all, so this hook is deliberately not wired to it.
    """

    def setUp(self):
        self._engines = app.ENGINES
        self.addCleanup(self._restore)

    def _restore(self):
        app.ENGINES = self._engines

    def test_registering_a_new_engine_extends_engines(self):
        app.register_engine("x")
        self.assertIn("x", app.ENGINES)

    def test_an_unread_module_is_refused_as_unestablished_on_the_new_engine(self):
        app.register_engine("x")
        with self.assertRaises(app.NotApplicableToEngine) as caught:
            app.check("hole_edge_swap", "x")
        self.assertIn("unestablished", str(caught.exception))

    def test_registering_an_engine_already_in_engines_raises(self):
        with self.assertRaises(ValueError):
            app.register_engine("3.5")

    def test_registering_the_same_new_engine_twice_raises(self):
        app.register_engine("x")
        with self.assertRaises(ValueError):
            app.register_engine("x")

    def test_default_engine_is_unchanged_by_registration(self):
        app.register_engine("x")
        self.assertEqual(app.DEFAULT_ENGINE, "3.5")

    def test_registrys_resolve_sees_the_extended_engines(self):
        """Two sides: the registry's own refusal text vs the applicability
        tuple. ``registry.resolve`` calls into ``applicability.check``/
        ``applicable`` at call time, which read the module-level ``ENGINES``
        as it stands then -- so a registration made after both modules were
        imported is still visible, and ``"x"`` is refused as *unestablished*
        rather than as an *unknown engine* (ranked uncertainty 6, design record)."""
        from arrayprobe_enhancements import registry as reg
        app.register_engine("x")
        with self.assertRaises(app.NotApplicableToEngine) as caught:
            reg.resolve({"hole_edge_swap": True}, engine="x")
        self.assertIn("unestablished", str(caught.exception))

    def test_a_table_supplies_declarations_for_the_new_engines_own_modules(self):
        entry = app.Applicability(
            finding=None, state={"y": app.APPLIES},
            basis="synthetic row for this test only")
        app.register_engine("y", table={"_test_only_new_engine_module": entry})
        self.addCleanup(app.APPLICABILITY.pop, "_test_only_new_engine_module",
                        None)
        self.assertTrue(app.applicable("_test_only_new_engine_module", "y"))


class DocumentedEntryPointsAgreeWithTheRegistry(unittest.TestCase):
    """The third S1 inconsistency: ``wide_hollow_fix.py``'s own docstring
    used to name ``upstream_is_it_hollow`` as "the recommended entry point"
    while the registry and ``applicability.py`` both wire ``better_is_it_
    hollow``. Checked against the registry rather than restated, so the two
    cannot drift apart silently again."""

    @unittest.skipUnless(_WIDE_HOLLOW_ON_DISK, _NEEDS_V314)
    def test_wide_hollow_fix_names_its_own_registered_entry_point(self):
        import inspect

        from arrayprobe_enhancements import registry as reg
        from arrayprobe_enhancements import wide_hollow_fix

        entry_point = reg.REGISTRY["wide_hollow_fix"].entry_point
        doc = inspect.getdoc(wide_hollow_fix) or ""
        self.assertIn(
            entry_point, doc,
            f"registry.REGISTRY['wide_hollow_fix'].entry_point is "
            f"{entry_point!r}, but the module's own docstring never names it")


if __name__ == "__main__":
    unittest.main()
