# SPDX-License-Identifier: BSD-3-Clause
"""The enhancement registry: opt-in by name, unknown names loud (the 2026-09-16 cold-start usability audit).

The per-run selection mechanism, with 2026-09-16's opt-in default. Two properties matter, checked from
different places:

* the **resolution** rules (default-off, explicit opt-in, unknown-is-an-error) are
  checked against the registry's own API -- the opt-in default itself, and the
  measurement that forced it, are in ``test_enhancement_opt_in.py``;
* the **membership** of the registry is checked against the ``.py`` files on disk,
  not against another document, so the two sides are independent and agreement is
  evidence rather than tautology -- the same argument ``test_backlog_status.py``
  makes for its own table.

The unwired modules are a **ratchet**, not an exemption list: ``_NOT_YET_REGISTERED``
may only shrink. A new module added without a registry entry fails here rather than
being silently unreachable from a config file, which under opt-in means a user cannot
turn it on at all.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from arrayprobe_enhancements import applicability, registry
from arrayprobe_enhancements.registry import (
    REGISTRY,
    EnhancementSpec,
    UnknownEnhancement,
    entry_point,
    resolve,
    resolve_from_config,
)

_WIDE_HOLLOW_ON_DISK = (Path(registry.__file__).parent / "wide_hollow_fix.py").exists()
_NEEDS_V314 = "needs the v3.1.4 engine, which this distribution omits"
#: The installed package's own directory, so the installed-package CI leg (src/ moved away)
#: compares the registry with the modules it actually installed.
_SRC = Path(registry.__file__).resolve().parent

#: Modules that ship but are not yet registered. RATCHET: this set may only shrink,
#: never regrow -- ``test_the_ratchet_is_empty`` below is the shape of that check,
#: not just a comment. Emptied 2026-09-14: all 29 modules this set used to
#: name are now registered in ``registry.py`` with an ``entry_point`` (or an explicit
#: ``None`` for a toolkit module with no single "apply this" callable), a ``stage``
#: and a ``consumes`` declaration. The set stays here, asserted empty rather than
#: deleted, so a future module that ships unregistered has somewhere to land and a
#: test that catches it landing there.
_NOT_YET_REGISTERED: set[str] = set()

#: The registered exceptions to default-OFF. **Empty, and it must stay empty** since 2026-09-16
#: (2026-09-16), which flipped resolution from opt-out to opt-in on the cold-start audit's
#: measurement -- see ``test_enhancement_opt_in.py`` for the measurement and the controls.
#: Written out here rather than read from the registry, so the two sides differ.
_DEFAULT_ON: list[str] = []


def _modules_on_disk() -> set[str]:
    # "pipeline" joined 2026-09-14: the driver that applies whichever
    # enhancements registry/applicability resolve ON, not itself a registrable one --
    # same standing as registry.py/applicability.py. Mirrors test_engine_applicability.py's
    # NOT_ENHANCEMENTS and test_publish_ready.py's _NOT_ENHANCEMENTS.
    return {p.stem for p in _SRC.glob("*.py")
            if p.stem not in ("__init__", "registry", "applicability", "pipeline")}


class TheRegistryMatchesTheModulesOnDisk(unittest.TestCase):
    def test_every_registered_name_is_a_real_module(self):
        missing = sorted(set(REGISTRY) - _modules_on_disk())
        self.assertEqual(
            missing, [],
            f"registered but no such module: {missing}. A config file could name these "
            "and resolve() would report them on, with nothing behind them.")

    def test_every_module_is_registered_or_on_the_ratchet(self):
        unaccounted = sorted(_modules_on_disk() - set(REGISTRY) - _NOT_YET_REGISTERED)
        self.assertEqual(
            unaccounted, [],
            f"module(s) {unaccounted} ship but are neither registered nor listed in "
            "_NOT_YET_REGISTERED. An unregistered enhancement cannot be switched on "
            "from a config file at all -- register it, or add it to the "
            "ratchet with a note in enhancement_registry_design.md.")

    def test_the_ratchet_names_only_real_modules(self):
        """A module deleted or renamed must not leave a stale ratchet entry behind,
        which would otherwise mask a genuinely unregistered module forever."""
        stale = sorted(_NOT_YET_REGISTERED - _modules_on_disk())
        self.assertEqual(stale, [], f"ratchet names non-existent module(s): {stale}")

    def test_the_ratchet_and_the_registry_do_not_overlap(self):
        both = sorted(_NOT_YET_REGISTERED & set(REGISTRY))
        self.assertEqual(both, [], f"registered AND on the ratchet: {both}")

    def test_the_ratchet_is_empty(self):
        """2026-09-14: the 29 modules this ratchet used to name are all
        registered now. The set stays in the file (asserted empty rather than
        deleted) so a future unregistered module has somewhere to land -- see
        ``test_every_module_is_registered_or_on_the_ratchet`` above, which is
        what actually catches one landing there."""
        self.assertEqual(
            _NOT_YET_REGISTERED, set(),
            "the ratchet grew back -- a module was added here instead of "
            "being registered in registry.py with an entry_point, stage and "
            "consumes")


class ResolutionIsOptIn(unittest.TestCase):
    #: Every test in this class names the engine, since 2026-09-12. Resolution
    #: has two axes now -- what the config file said, and whether the
    #: enhancement applies to the engine being run -- and a test that named
    #: neither would be reading whichever axis happened to move. v3.1.4 is used
    #: here because every enhancement was written for it, so the engine axis is
    #: a constant and these tests go on measuring the config axis alone.
    ENGINE = "3.1.4"

    def test_no_config_at_all_turns_everything_off(self):
        """the 2026-09-16 cold-start usability audit flipped this: absent used to mean ON.

        The measurement that forced it, and the full set of opt-in assertions, is in
        ``test_enhancement_opt_in.py``; this one stays here so the registry's own
        resolution contract is stated where the rest of it is.
        """
        got = resolve(None, engine=self.ENGINE)
        self.assertEqual(got, {n: False for n in REGISTRY})
        self.assertEqual(sorted(n for n, on in got.items() if on), _DEFAULT_ON)
        self.assertEqual(set(got), set(REGISTRY))

    def test_any_enhancement_turns_on_by_name(self):
        for name in ("hole_edge_swap", "spot_edge_fix", "published_dof"):
            self.assertTrue(resolve({name: True}, engine=self.ENGINE)[name])

    def test_an_empty_table_turns_everything_off(self):
        got = resolve({}, engine=self.ENGINE)
        self.assertEqual(sorted(n for n, on in got.items() if on), _DEFAULT_ON)

    def test_naming_one_true_opts_into_only_that_one(self):
        got = resolve({"hole_edge_swap": True}, engine=self.ENGINE)
        self.assertTrue(got["hole_edge_swap"])
        self.assertFalse(got["spot_edge_fix"])
        self.assertFalse(got["dmax_sensitivity"])

    def test_naming_one_false_is_redundant_but_accepted(self):
        self.assertFalse(
            resolve({"hole_edge_swap": False},
                    engine=self.ENGINE)["hole_edge_swap"])

    def test_opting_into_everything_is_expressible(self):
        on = {name: True for name in REGISTRY}
        self.assertEqual(set(resolve(on, engine=self.ENGINE).values()), {True})

    def test_an_unknown_name_is_an_error_not_an_ignored_line(self):
        with self.assertRaises(UnknownEnhancement) as caught:
            resolve({"wide_hollow_fx": False}, engine=self.ENGINE)
        self.assertIn("wide_hollow_fx", str(caught.exception))

    def test_the_result_covers_every_registered_enhancement(self):
        """Not just the ones the file mentioned -- a driver reads this as the
        complete decision, so a missing key would be an implicit default."""
        self.assertEqual(set(resolve({"spot_edge_fix": False},
                                     engine=self.ENGINE)), set(REGISTRY))


class ResolutionFromARealRunConfig(unittest.TestCase):
    """End to end through the port's own loader, proving the two packages meet
    where the design says they do -- `RunConfig.enhancements`, carried verbatim."""

    def _config(self, body: str):
        import tempfile

        from arrayprobe.config import load_config
        d = Path(tempfile.mkdtemp())
        p = d / "run.toml"
        p.write_text('[fidelity]\nprofile = "ORACLES_PRODUCTION"\n' + body, encoding="utf-8")
        return load_config(p)

    def test_a_config_with_no_enhancements_section_turns_everything_off(self):
        cfg = self._config("")
        self.assertEqual(cfg.enhancements, {})
        got = resolve_from_config(cfg, engine="3.1.4")
        self.assertEqual(sorted(n for n, on in got.items() if on), _DEFAULT_ON)

    def test_a_config_opting_in_is_honoured(self):
        cfg = self._config("\n[enhancements]\nhole_edge_swap = true\n")
        got = resolve_from_config(cfg, engine="3.1.4")
        self.assertTrue(got["hole_edge_swap"])
        self.assertFalse(got["spot_edge_fix"])

    def test_naming_a_newly_registered_module_is_no_longer_unknown(self):
        """Before 2026-09-14, only 4 of 33 modules were registered, so a config line
        naming any of the other 29 -- e.g. ``conc_arear_fix = true`` -- raised
        ``UnknownEnhancement``: a user could not reach 29 of 33 by name.
        This is the survey's own worked example.
        """
        cfg = self._config("\n[enhancements]\nint_arr_rollback_fix = true\n")
        got = resolve_from_config(cfg, engine="3.1.4")
        self.assertTrue(got["int_arr_rollback_fix"])

    def test_the_port_and_this_package_agree_about_the_default(self):
        """They disagreed on purpose until 2026-09-16, and that divergence was
        itself the defect the cold-start audit found. One file, one meaning."""
        cfg = self._config("")
        got = resolve_from_config(cfg, engine="3.1.4")
        for name in REGISTRY:
            self.assertEqual(cfg.enabled(name), got[name], name)


class ResolutionAlsoDependsOnTheEngine(unittest.TestCase):
    """The second axis, added 2026-09-12 with the author's decision that v3.5
    is the default engine.

    Four of these modules correct defects the UIOOPS developers fixed in v3.5.
    Left on there they would not be inert -- they would correct an
    already-corrected value. So resolution asks two questions, and the answers
    have deliberately different shapes: an enhancement that simply does not
    apply resolves **off**, while one the config file switched **on** by name
    raises, because silently ignoring an explicit instruction is how a user
    ends up believing a correction ran.
    """

    def test_the_default_engine_is_v35(self):
        self.assertEqual(applicability.DEFAULT_ENGINE, "3.5")

    def test_a_superseded_enhancement_is_off_on_v35_even_when_asked_for(self):
        """Asked for by name it raises (next test); asked for as part of a whole-registry
        opt-in it resolves off, which is how a config that names every module still runs
        on v3.5. Under v3.1.4 the same request is honoured."""
        everything = {name: True for name in REGISTRY}
        with self.assertRaises(applicability.NotApplicableToEngine):
            resolve(everything)
        self.assertTrue(resolve(everything, engine="3.1.4")["reshape_fix"])
        self.assertFalse(resolve(None)["reshape_fix"])

    def test_switching_a_superseded_one_on_by_name_raises(self):
        with self.assertRaises(applicability.NotApplicableToEngine) as caught:
            resolve({"reshape_fix": True})
        self.assertIn("superseded", str(caught.exception))

    def test_opting_out_of_a_superseded_one_is_not_an_error(self):
        """``false`` and "does not apply" agree, so there is nothing to warn
        about -- refusing here would make a correct config file fail."""
        self.assertFalse(resolve({"reshape_fix": False})["reshape_fix"])

    def test_a_live_enhancement_is_unaffected_by_the_engine(self):
        for engine in applicability.ENGINES:
            self.assertTrue(
                resolve({"spot_edge_fix": True}, engine=engine)["spot_edge_fix"])

    def test_an_unknown_engine_raises(self):
        with self.assertRaises(applicability.UnknownEngine):
            resolve({"spot_edge_fix": True}, engine="soda2")


class OmittedModulesAreOnlyTheV314Ones(unittest.TestCase):
    """The release omits the v3.1.4 engine and the six modules that repair its output; nothing
    else may go missing quietly. Two sides written in different places: the spec flags in
    ``registry.py`` and ``applicability.REQUIRES_V314``."""

    def test_requires_v314_agrees_with_applicability(self):
        flagged = {n for n, s in {**REGISTRY, **registry.OMITTED}.items() if s.requires_v314}
        self.assertEqual(flagged, set(applicability.REQUIRES_V314))

    def test_only_v314_modules_may_be_omitted(self):
        here = Path(registry.__file__).parent
        self.assertLessEqual(set(registry.OMITTED), set(applicability.REQUIRES_V314))
        self.assertEqual(set(registry.OMITTED), set(applicability.OMITTED_APPLICABILITY))
        for name in registry.OMITTED:
            with self.subTest(name=name):
                self.assertFalse((here / f"{name}.py").exists())

    def test_an_omitted_name_is_refused_with_the_reason(self):
        for name in registry.OMITTED:
            with self.subTest(name=name):
                with self.assertRaises(UnknownEnhancement) as caught:
                    resolve({name: True})
                self.assertIn("not part of this distribution", str(caught.exception))
                with self.assertRaises(UnknownEnhancement):
                    entry_point(name)


class EntryPointsAreReal(unittest.TestCase):
    def test_every_wired_entry_point_imports_and_is_callable(self):
        for name, spec in REGISTRY.items():
            if spec.entry_point is None:
                continue
            with self.subTest(name=name):
                self.assertTrue(callable(entry_point(name)))

    def test_the_three_wired_modules_reach_their_real_functions(self):
        from arrayprobe_enhancements.dmax_sensitivity import compute_sensitivity
        from arrayprobe_enhancements.spot_edge_fix import correct_part_z_size_factor

        self.assertIs(entry_point("spot_edge_fix"), correct_part_z_size_factor)
        self.assertIs(entry_point("dmax_sensitivity"), compute_sensitivity)

    @unittest.skipUnless(_WIDE_HOLLOW_ON_DISK, _NEEDS_V314)
    def test_wide_hollow_fix_reaches_its_real_function(self):
        # `better_is_it_hollow` since 2026-09-12: the requirement is *the
        # better correction*, not v3.5's blankly. v3.5 fixed the diode-32 hollow test and the late-start hole window and
        # regressed the coverage guard, so the wired entry point takes the
        # first two and declines the third. Measured in
        # `tests/test_wide_hollow_vs_upstream.py`.
        from arrayprobe_enhancements.wide_hollow_fix import better_is_it_hollow

        self.assertIs(entry_point("wide_hollow_fix"), better_is_it_hollow)

    def test_an_unknown_name_has_no_entry_point(self):
        with self.assertRaises(UnknownEnhancement):
            entry_point("no_such_enhancement")

    def test_a_registered_but_unwired_enhancement_says_so(self):
        spec = EnhancementSpec(name="_probe_only", summary="test double", entry_point=None)
        registry.register(spec)
        try:
            with self.assertRaises(LookupError):
                entry_point("_probe_only")
        finally:
            del REGISTRY["_probe_only"]

    def test_registering_the_same_name_twice_is_refused(self):
        with self.assertRaises(ValueError):
            registry.register(REGISTRY["spot_edge_fix"])


if __name__ == "__main__":
    unittest.main()
