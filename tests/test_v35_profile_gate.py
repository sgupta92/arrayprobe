# SPDX-License-Identifier: BSD-3-Clause
"""The ``--engine 3.5`` profile gate: which profiles it admits, and why.

**What this guards.** Until 2026-09-17 ``run_flight.py`` admitted exactly one
object under ``--engine 3.5``: ``PROFILE is not STOCK_V35`` -> exit 2. The v3.5
engine reads only ``reject_thresholds`` from a profile, so pinning the *identity*
pinned the *thresholds* too, and two pieces of work hit the same wall:

* the author's 2026-09-17 instruction to report CIP results under stock **and**
  ORACLES-production thresholds "both thresholds side by side"; and
* **CMP-2** (2026-09-16), parked because scoring the v3.5 engine against the
  author's 466 triage labels would have confounded *engine* with *profile* -- on
  exactly the thresholds worth 38.15 % of used-bin particles.

The gate is now :func:`arrayprobe.profiles.is_v35_flavoured`.

**The trap these tests exist for.** The obvious implementation -- compare the
behaviour fields against ``stock-v3.5`` -- **admits ``stock-v3.1.4``**, because
``STOCK_V35`` was built by measuring that every field holds the same value as
``stock-v3.1.4``. The two are field-identical and no comparison of values can
separate them; only a *declaration* of which tree the citations name can. A v3.5
run under ``stock-v3.1.4`` would compute correct numbers and stamp a ``.call``
naming a tree that was never consulted. ``test_the_field_comparison_alone_would_
admit_stock_v314`` pins that reasoning so the declaration is not later optimised
away as redundant.
"""

from __future__ import annotations

import dataclasses
import unittest

from arrayprobe.profiles import (
    _BEHAVIOUR_FIELDS,
    ORACLES_2016,
    ORACLES_PRODUCTION,
    ORACLES_PRODUCTION_V35,
    PROFILES,
    SHIPPED,
    STOCK_V35,
    STOCK_V314,
    FidelityProfile,
    is_v35_flavoured,
    register_profile,
)


class TheShippedProfilesAreSortedCorrectly(unittest.TestCase):
    """Each shipped profile is admitted or refused, and the reason is the tree."""

    def test_the_two_v35_profiles_are_admitted(self):
        for p in (STOCK_V35, ORACLES_PRODUCTION_V35):
            with self.subTest(profile=p.name):
                self.assertTrue(is_v35_flavoured(p))

    def test_the_three_v314_profiles_are_refused(self):
        for p in (STOCK_V314, ORACLES_2016, ORACLES_PRODUCTION):
            with self.subTest(profile=p.name):
                self.assertFalse(
                    is_v35_flavoured(p),
                    f"{p.name} cites the v3.1.4 tree; admitting it would let a v3.5 run "
                    "stamp a .call naming a tree that was never consulted")

    def test_oracles_production_v35_is_shipped_and_reachable_three_ways(self):
        self.assertIn("oracles-production-v3.5", SHIPPED)
        self.assertIs(PROFILES["oracles-production-v3.5"], ORACLES_PRODUCTION_V35)
        from arrayprobe.profiles import profile as lookup
        self.assertIs(lookup("oracles-production-v3.5"), ORACLES_PRODUCTION_V35)


class TheNewProfileIsStockV35PlusOracesThresholdsAndNothingElse(unittest.TestCase):
    """It varies one axis. If it varied two, a difference would be unattributable."""

    def test_only_reject_thresholds_differ_from_stock_v35(self):
        for f in _BEHAVIOUR_FIELDS:
            with self.subTest(field=f):
                self.assertEqual(
                    getattr(ORACLES_PRODUCTION_V35, f), getattr(STOCK_V35, f),
                    f"{f} differs from stock-v3.5, so a run difference could not be "
                    "attributed to the thresholds alone")

    def test_the_thresholds_are_the_oracles_production_ones(self):
        self.assertEqual(
            ORACLES_PRODUCTION_V35.reject_thresholds, ORACLES_PRODUCTION.reject_thresholds)
        self.assertNotEqual(
            ORACLES_PRODUCTION_V35.reject_thresholds, STOCK_V35.reject_thresholds)

    def test_the_three_edited_values_are_the_ones_the_oracles_fork_edited(self):
        """``uioops_testing/calculate_reject_unified.m`` :72, :76, :77 -- read, not assumed."""
        r = ORACLES_PRODUCTION_V35.reject_thresholds
        self.assertFalse(r.rej_hollow)          # :72   1 -> 0
        self.assertEqual(r.max_edge_img_ar, 4)  # :76   6 -> 4
        self.assertEqual(r.max_comp_img_ar, 4)  # :77   5 -> 4
        s = STOCK_V35.reject_thresholds         # v3.5 :60-66, the side it departs from
        self.assertTrue(s.rej_hollow)
        self.assertEqual((s.max_edge_img_ar, s.max_comp_img_ar), (6, 5))

    def test_its_description_says_it_reproduces_nothing(self):
        """A synthetic configuration that reads as a reproduction is the dangerous case.

        No MATLAB tree ever ran the v3.5 engine under the ORACLES thresholds -- the
        ORACLES fork froze at v3.1.4 and was never rebased. The description has to
        say so, because the ``.call`` stamp carries the name and a later reader will
        ask what it reproduced.
        """
        d = ORACLES_PRODUCTION_V35.description.lower()
        self.assertIn("synthetic", d)
        self.assertIn("no archived product", d)


class TheDeclarationIsLoadBearing(unittest.TestCase):
    """Why the gate is not merely a field comparison."""

    def test_the_field_comparison_alone_would_admit_stock_v314(self):
        """The whole reason ``_V35_TREE_PROFILES`` exists.

        If this ever fails, ``stock-v3.1.4`` and ``stock-v3.5`` have stopped being
        field-identical -- then a pure field comparison *would* separate them and
        the declaration could in principle be dropped. Until then it cannot be, and
        this test is the record of why.
        """
        field_match = all(
            getattr(STOCK_V314, f) == getattr(STOCK_V35, f) for f in _BEHAVIOUR_FIELDS)
        self.assertTrue(
            field_match,
            "stock-v3.1.4 and stock-v3.5 are no longer field-identical; re-read "
            "is_v35_flavoured, the declaration may now be redundant")
        self.assertFalse(
            is_v35_flavoured(STOCK_V314),
            "the gate admitted stock-v3.1.4 -- the declaration is not being checked")


class AForksOwnVariant(unittest.TestCase):
    """``register_profile(..., cites_tree=...)`` in all four states.

    **This class leaked global state until 2026-09-17 and a different test module
    paid for it.** The first version registered three forks with no cleanup, so
    they stayed in ``profiles._REGISTRY`` for the rest of the process — and
    ``test_docs_site.test_profile_table_matches_profiles_py``, running later in
    the same interpreter, compared the generated profile table against a registry
    holding ``t-fork-ok``, ``t-fork-liar`` and ``t-fork-quiet`` and correctly
    reported it stale. The failure surfaced two modules away from its cause,
    which is exactly why a registration test has to clean up after itself.

    Two registries need restoring, not one: ``_REGISTRY`` and — new with this
    gate — ``_V35_TREE_PROFILES``, the declaration set. Forgetting the second
    would leave a fork permanently admitted to the v3.5 gate.
    """

    def setUp(self):
        from arrayprobe import profiles as _p
        before_registry = dict(_p._REGISTRY)
        before_v35 = set(_p._V35_TREE_PROFILES)
        self.addCleanup(self._restore, before_registry, before_v35)

    @staticmethod
    def _restore(before_registry, before_v35):
        from arrayprobe import profiles as _p
        for name in list(_p._REGISTRY):
            if name not in before_registry:
                del _p._REGISTRY[name]
        _p._V35_TREE_PROFILES.clear()
        _p._V35_TREE_PROFILES.update(before_v35)

    @staticmethod
    def _named(base: FidelityProfile, name: str) -> FidelityProfile:
        return dataclasses.replace(base, name=name, description=f"test variant {name}")

    def test_declared_v35_with_v35_behaviour_is_admitted(self):
        p = self._named(STOCK_V35, "t-fork-ok")
        register_profile(p, cites_tree="3.5")
        self.assertTrue(is_v35_flavoured(PROFILES["t-fork-ok"]))

    def test_declared_v35_over_v314_behaviour_is_still_refused(self):
        """The declaration is necessary, not sufficient."""
        p = self._named(ORACLES_PRODUCTION, "t-fork-liar")
        register_profile(p, cites_tree="3.5")
        self.assertFalse(is_v35_flavoured(PROFILES["t-fork-liar"]))

    def test_saying_nothing_fails_closed(self):
        p = self._named(STOCK_V35, "t-fork-quiet")
        register_profile(p)
        self.assertFalse(
            is_v35_flavoured(PROFILES["t-fork-quiet"]),
            "the default must refuse, so a fork is kept out of the v3.5 gate until it opts in")

    def test_an_unknown_tree_is_refused_at_registration(self):
        p = self._named(STOCK_V35, "t-fork-bad")
        with self.assertRaises(ValueError) as cm:
            register_profile(p, cites_tree="4.0")
        self.assertIn("3.1.4", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
