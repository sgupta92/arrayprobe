# SPDX-License-Identifier: BSD-3-Clause
"""Shape tests for ``arrayprobe_soda2_enhancements.registry`` -- stage 1.

No SODA-2 correction is registered yet; these tests exercise the mechanism itself and must
keep passing as stages 2+ add modules (``test_every_module_on_disk_is_registered_and_vice_versa``
is the ratchet that makes that true rather than assumed).
"""
from __future__ import annotations

import importlib
import unittest
from pathlib import Path

from arrayprobe_soda2_enhancements import registry as reg_mod
from arrayprobe_soda2_enhancements.registry import (
    REGISTRY,
    EnhancementSpec,
    UnknownEnhancement,
    resolve,
)

#: The installed package's own directory, so the installed-package CI leg (src/ moved away)
#: compares the registry with the modules it actually installed.
_SRC = Path(reg_mod.__file__).resolve().parent
_NON_MODULE_STEMS = {"__init__", "registry"}


class TestRegistryShape(unittest.TestCase):
    def setUp(self) -> None:
        # REGISTRY is process-global; snapshot and restore so a test that registers a
        # synthetic spec cannot leak into another test's REGISTRY-shape assumptions.
        self._saved = dict(REGISTRY)
        # addCleanup runs LIFO -- added last runs first, so `clear` (added second) fires
        # before `update` (added first), leaving the restored snapshot as the final state.
        self.addCleanup(REGISTRY.update, self._saved)
        self.addCleanup(REGISTRY.clear)

    def test_resolve_empty_registry_returns_empty_dict(self) -> None:
        REGISTRY.clear()
        self.assertEqual(resolve(None), {})
        self.assertEqual(resolve({}), {})

    def test_unknown_name_raises_UnknownEnhancement(self) -> None:
        REGISTRY.clear()
        with self.assertRaises(UnknownEnhancement):
            resolve({"not_a_real_module": False})

    def test_reachability_must_be_one_of_three_words(self) -> None:
        with self.assertRaises(ValueError):
            EnhancementSpec(
                name="synthetic_probe", summary="test-only", finding="S0-z",
                reachability="maybe", entry_point=None,
            )
        # The three real words all construct cleanly.
        for word in ("live", "latent", "flagged"):
            EnhancementSpec(
                name=f"synthetic_{word}", summary="test-only", finding="S0-z",
                reachability=word, entry_point=None,
            )

    def test_every_module_on_disk_is_registered_and_vice_versa(self) -> None:
        on_disk = {
            p.stem for p in _SRC.glob("*.py")
            if p.stem not in _NON_MODULE_STEMS and not p.stem.startswith("_")
        }
        # Registration is an import-time side effect, so import every module first:
        # without this the check passed only when other test modules happened to
        # have imported them, and failed when run on its own (stage 8).
        for stem in sorted(on_disk):
            importlib.import_module(f"arrayprobe_soda2_enhancements.{stem}")
        registered = set(reg_mod.REGISTRY)
        self.assertEqual(
            on_disk, registered,
            f"on disk but not registered: {on_disk - registered}; "
            f"registered but no module on disk: {registered - on_disk}",
        )


class TestProtectiveSet(unittest.TestCase):
    """A14 (2026-09-28): ordinary corrections opt-in; the protective set on by default,
    because SODA-2 has written no archived product for any probe."""

    def test_every_probe_gets_the_whole_protective_set(self) -> None:
        self.assertEqual(reg_mod.LINEAGE_PROBES, frozenset())
        for probe in ("", "2DS", "HVPS", "CIP", "anything"):
            self.assertEqual(reg_mod.protective_set(probe=probe), reg_mod.PROTECTIVE)

    def test_protective_names_are_registered_and_not_default_on(self) -> None:
        reg_mod.load_all()
        self.assertEqual(len(reg_mod.PROTECTIVE), 5)
        for name in reg_mod.PROTECTIVE:
            self.assertIn(name, REGISTRY)
            self.assertFalse(REGISTRY[name].default_on, name)

    def test_no_registered_correction_is_default_on(self) -> None:
        reg_mod.load_all()
        self.assertEqual([n for n, s in REGISTRY.items() if s.default_on], [])

    def test_the_protective_key_is_a_switch_not_a_module(self) -> None:
        reg_mod.load_all()
        for value in (True, False):
            got = resolve({reg_mod.PROTECTIVE_KEY: value})
            self.assertNotIn(reg_mod.PROTECTIVE_KEY, got)
            self.assertFalse(any(got.values()))

    def test_protective_membership_is_not_checked_as_a_request(self) -> None:
        reg_mod.load_all()
        got = resolve({}, protective=frozenset({"not_registered_here"}))
        self.assertNotIn("not_registered_here", got)
        with self.assertRaises(UnknownEnhancement):
            resolve({"not_registered_here": True}, protective=reg_mod.PROTECTIVE)


if __name__ == "__main__":
    unittest.main()
