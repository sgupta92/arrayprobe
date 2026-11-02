# SPDX-License-Identifier: BSD-3-Clause
"""Enhancements are opt-in: absent means OFF, and the driver refuses a config that
does not say. Flipped 2026-09-16 on the cold-start
usability audit's finding 1.1.

**This file exists because the opposite shipped.** From 2026-09-10 to that date the
resolution default was ON, so ``arrayprobe-enhanced run`` applied corrections nobody had
named while ``README.md``, ``docs/05-enhancements.md`` and
a script's own comment all said opt-in. A cold-start
usability audit measured it: a config whose only entry was ``outoffocus = false``
resolved **31 of 40** modules ON under the default v3.5 engine (39 of 40 under v3.1.4,
where fewer are superseded) and applied four, two of which change numbers. Nothing
failed. The run returned 0.

**Measured against the old behaviour**, 2026-09-16, by flipping
``EnhancementSpec.default_on`` back to ``True`` and rerunning this file: ``FAILED
(failures=9)`` -- all three of ``NothingIsOnByDefault``, all three of
``NamingOneModuleResolvesExactlyThatOne`` and all three of
``TheAuditsOwnConfigResolvesOneModule``. The other seven pass either way, because
``require_enhancement_policy`` and ``format_resolution`` are new machinery rather than a
changed default; they are here because the audit asked for all three (default, refusal,
disclosure) and each is a separate way the same wrong number gets published.

The counts here are read from ``REGISTRY`` rather than typed, so growing the package
does not make a test wrong -- what is pinned is the *shape* of the answer.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe.config import load_config

from arrayprobe_enhancements import pipeline
from arrayprobe_enhancements.registry import REGISTRY, resolve, resolve_from_config

#: v3.1.4 throughout, for the reason ``test_enhancement_registry.py`` gives: every
#: enhancement was written for it, so the engine axis is a constant and these tests go on
#: measuring the config axis alone. The engine axis has its own file.
ENGINE = "3.1.4"


def _config(body: str):
    d = Path(tempfile.mkdtemp())
    p = d / "run.toml"
    p.write_text('[fidelity]\nprofile = "ORACLES_PRODUCTION"\n'
                 '[run]\nengine = "3.1.4"\npreset = "DEMO_2DS_H"\n' + body,
                 encoding="utf-8")
    return load_config(p), p


class NothingIsOnByDefault(unittest.TestCase):
    """An empty config resolves none. Under default-ON all three assertions fail."""

    def test_no_table_at_all_resolves_nothing_on(self):
        got = resolve(None, engine=ENGINE)
        self.assertEqual(set(got), set(REGISTRY), "every module must still get a decision")
        self.assertEqual(sorted(n for n, on in got.items() if on), [])

    def test_an_empty_table_resolves_nothing_on(self):
        self.assertEqual(sorted(n for n, on in resolve({}, engine=ENGINE).items() if on), [])

    def test_no_registered_module_claims_a_default_on_exemption(self):
        """The control, not the rule: ``default_on`` is kept as a field for the SODA-2
        lineage's shape, so this is what stops one module quietly getting it back."""
        self.assertEqual(sorted(n for n, s in REGISTRY.items() if s.default_on), [])


class NothingStillDescribesTheOldDefault(unittest.TestCase):
    """The flip changed the default but left three sentences describing the old one.

    The error a user sees for a mistyped key explained itself by the default-ON scheme
    ("an unrecognised key would leave the enhancement running"), which has not been true
    since the flip: under opt-in a mistyped key is a correction that silently does *not*
    run. A message that states the wrong default teaches the user the wrong default.
    """

    #: Present-tense descriptions of the superseded default. A sentence recording the
    #: history ("was ON until the flip") is fine and does not use these phrasings.
    STALE = ("Under default-ON", "default-ON scheme", "Registry default ON")

    def test_the_unknown_key_error_describes_the_opt_in_default(self):
        from arrayprobe_enhancements.registry import UnknownEnhancement
        with self.assertRaises(UnknownEnhancement) as ctx:
            resolve({"hole_edge_swapp": True}, engine=ENGINE)
        message = str(ctx.exception)
        self.assertNotIn("default-ON", message)
        self.assertIn("hole_edge_swapp", message)
        self.assertIn("would not run", message)

    def test_no_source_line_states_the_superseded_default_as_current(self):
        src = Path(__file__).resolve().parent.parent / "src" / "arrayprobe_enhancements"
        hits = [f"{path.name}:{n}"
                for path in sorted(src.glob("*.py"))
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if any(phrase in line for phrase in self.STALE)]
        self.assertEqual(hits, [], "the enhancement default is opt-in; these lines say ON")


class NamingOneModuleResolvesExactlyThatOne(unittest.TestCase):
    """The audit's user's belief, made true: one line, one correction."""

    def test_one_true_resolves_exactly_one(self):
        got = resolve({"hole_edge_swap": True}, engine=ENGINE)
        self.assertEqual(sorted(n for n, on in got.items() if on), ["hole_edge_swap"])

    def test_two_true_resolve_exactly_two(self):
        got = resolve({"hole_edge_swap": True, "spot_edge_fix": True}, engine=ENGINE)
        self.assertEqual(sorted(n for n, on in got.items() if on),
                         ["hole_edge_swap", "spot_edge_fix"])

    def test_one_false_is_not_an_instruction_to_run_the_rest(self):
        """The measured failure exactly: ``outoffocus = false`` as the only entry."""
        got = resolve({"outoffocus": False}, engine=ENGINE)
        self.assertEqual(sorted(n for n, on in got.items() if on), [])


class TheAuditsOwnConfigResolvesOneModule(unittest.TestCase):
    """End to end through the port's loader, on the file the audit actually wrote."""

    def test_the_audits_off_config_resolves_nothing(self):
        cfg, _ = _config("\n[enhancements]\noutoffocus = false\n")
        got = resolve_from_config(cfg, engine=ENGINE)
        self.assertEqual(sorted(n for n, on in got.items() if on), [])

    def test_the_audits_on_config_resolves_only_outoffocus(self):
        cfg, _ = _config("\n[enhancements]\noutoffocus = true\n")
        got = resolve_from_config(cfg, engine=ENGINE)
        self.assertEqual(sorted(n for n, on in got.items() if on), ["outoffocus"])

    def test_the_port_and_this_package_now_agree(self):
        """They disagreed on purpose until 2026-09-16; the divergence itself was the defect."""
        cfg, _ = _config("\n[enhancements]\nhole_edge_swap = true\n")
        got = resolve_from_config(cfg, engine=ENGINE)
        for name in REGISTRY:
            self.assertEqual(cfg.enabled(name), got[name], name)


class TheDriverRefusesAConfigWithNoPolicy(unittest.TestCase):
    """Absent is not "off" either -- it is "the file did not say"."""

    def test_no_enhancements_section_is_refused(self):
        cfg, path = _config("")
        self.assertFalse(cfg.enhancements_declared)
        with self.assertRaises(pipeline.NoEnhancementPolicy) as caught:
            pipeline.require_enhancement_policy(cfg, path)
        self.assertIn("[enhancements]", str(caught.exception))

    def test_an_empty_section_is_an_explicit_policy_and_is_accepted(self):
        cfg, path = _config("\n[enhancements]\n")
        self.assertTrue(cfg.enhancements_declared)
        self.assertEqual(cfg.enhancements, {})
        pipeline.require_enhancement_policy(cfg, path)  # does not raise

    def test_a_populated_section_is_accepted(self):
        cfg, path = _config("\n[enhancements]\nhole_edge_swap = true\n")
        pipeline.require_enhancement_policy(cfg, path)  # does not raise

    def test_the_cli_reports_it_as_exit_2_and_one_line_not_a_traceback(self):
        _cfg, path = _config("")
        self.assertEqual(pipeline.main(["run", str(path)]), 2)


class TheResolvedSetIsPrinted(unittest.TestCase):
    """A user can never be wrong about what was applied, because the run says so."""

    def test_every_on_module_is_named_not_counted(self):
        resolved = {n: (n == "hole_edge_swap") for n in REGISTRY}
        text = pipeline.format_resolution(resolved, ENGINE, "run.toml")
        self.assertIn("hole_edge_swap", text)
        self.assertIn(f"1 of {len(REGISTRY)} ON", text)

    def test_an_all_off_run_says_so_rather_than_printing_an_empty_list(self):
        text = pipeline.format_resolution({n: False for n in REGISTRY}, ENGINE, "run.toml")
        self.assertIn(f"0 of {len(REGISTRY)} ON", text)
        self.assertIn("unmodified", text)

    def test_the_line_says_whether_a_resolved_module_actually_has_an_adapter(self):
        resolved = {n: n in ("hole_edge_swap", "md_relations") for n in REGISTRY}
        text = pipeline.format_resolution(resolved, ENGINE, "run.toml")
        self.assertIn("hole_edge_swap", text)
        self.assertIn("no driver adapter", text)


if __name__ == "__main__":
    unittest.main()
