# SPDX-License-Identifier: BSD-3-Clause
"""A fork can name its own MATLAB variant without editing this package.

WHY THIS EXISTS (2026-09-09).  UIOOPS is forked, edited and re-forked --
that is how the ORACLES variant this port validates against came to exist -- so
a group running their own tree has to be able to say *my fork differs here*.
Until now the three shipped profiles were the only three nameable, and
``config.py`` held a **second copy** of them under CONSTANT-style keys that
nothing compared with the first: a fourth profile added to ``profiles.py`` would
have been invisible to every config file, silently.

What is deliberately NOT opened is the other direction. A profile is registered
from Python, where the caller constructs a ``FidelityProfile`` and the dataclass
requires every field, so each divergence is named. A config file still cannot
*describe* a profile, only select one -- a standing rule of the project (2026-08-28), and the
reason ``config.py`` refuses ``rej_hollow`` and its siblings anywhere in a file.

Every test here restores the registry afterwards: it is process-global state,
and a leaked registration would make a later test's ``sorted(PROFILES)`` depend
on which tests ran first.
"""

from __future__ import annotations

import dataclasses
import unittest

from arrayprobe import config, profiles
from arrayprobe.profiles import (
    ORACLES_PRODUCTION,
    PROFILES,
    SHIPPED,
    STOCK_V35,
    STOCK_V314,
    FidelityProfile,
    register_profile,
)

#: Tests here call ``register_profile()``, which mutates a module-level registry
#: that outlives the test. Nothing restored it, so a profile registered by one
#: test stayed visible to every later test IN THE WHOLE SUITE -- and
#: ``test_docs_site.test_profile_table_matches_profiles_py`` reads that live
#: registry, so it passed alone and failed under ``unittest discover`` (found
#: 2026-09-10). Snapshot and restore, so registering is local to this file.
_REGISTRY_BEFORE: dict = {}


# The shared helper also restores _V35_TREE_PROFILES, the register-once caches
# and the registering modules' sys.modules entries (tests/_profile_registry_guard.py).
from tests._profile_registry_guard import module_hooks  # noqa: E402

setUpModule, tearDownModule = module_hooks()


def _fork(name: str = "some-fork-2019", **overrides) -> FidelityProfile:
    """A plausible fork: stock, with the buffer guards taken back out."""
    fields = dataclasses.asdict(STOCK_V314)
    fields["reject_thresholds"] = STOCK_V314.reject_thresholds   # asdict() flattens it
    fields["name"] = name
    fields["description"] = "A fork invented by tests/test_profile_registry.py."
    fields["spec_buffer_guard"] = False
    fields.update(overrides)
    return FidelityProfile(**fields)


class _RegistryCase(unittest.TestCase):
    def setUp(self):
        before = dict(PROFILES)
        # `_V35_TREE_PROFILES` too, since 2026-09-17: `register_profile` now also
        # records which tree a variant's citations name, in a second module-level
        # set. Restoring only `_REGISTRY` would leave a test fork permanently
        # admitted to the `--engine 3.5` gate -- and a leak here is paid for two
        # modules away, as `test_v35_profile_gate`'s own docstring records.
        before_v35 = set(profiles._V35_TREE_PROFILES)
        self.addCleanup(self._restore, before, before_v35)

    @staticmethod
    def _restore(before, before_v35=None):
        for name in list(PROFILES):
            if name not in before:
                del profiles._REGISTRY[name]
        if before_v35 is not None:
            profiles._V35_TREE_PROFILES.clear()
            profiles._V35_TREE_PROFILES.update(before_v35)


class AForkCanRegisterItsOwnVariant(_RegistryCase):
    def test_it_becomes_findable_by_name(self):
        register_profile(_fork())
        self.assertIs(profiles.profile("some-fork-2019").spec_buffer_guard, False)

    def test_the_registry_view_is_live_rather_than_a_snapshot(self):
        """``PROFILES`` is a read-only *view*, so a registration shows through it."""
        self.assertNotIn("some-fork-2019", PROFILES)
        register_profile(_fork())
        self.assertIn("some-fork-2019", PROFILES)

    def test_the_view_is_still_read_only(self):
        with self.assertRaises(TypeError):
            PROFILES["sneaked-in"] = STOCK_V314          # type: ignore[index]

    def test_a_config_file_can_then_select_it(self, ):
        import tempfile
        from pathlib import Path
        register_profile(_fork())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.toml"
            path.write_text('[fidelity]\nprofile = "some-fork-2019"\n', encoding="utf-8")
            cfg = config.load_config(path)
        self.assertEqual(cfg.profile.name, "some-fork-2019")

    def test_a_config_file_still_cannot_describe_one(self):
        """The point of that rule: selecting is allowed, setting is not."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.toml"
            path.write_text('[fidelity]\nprofile = "STOCK_V314"\nspec_buffer_guard = false\n',
                            encoding="utf-8")
            with self.assertRaises(config.ConfigError) as caught:
                config.load_config(path)
        self.assertIn("spec_buffer_guard", str(caught.exception))


class ANameKeepsMeaningOneVariant(_RegistryCase):
    def test_a_shipped_name_cannot_be_taken(self):
        for name in sorted(SHIPPED):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as caught:
                    register_profile(_fork(name=name))
                self.assertIn("shipped with this package", str(caught.exception))

    def test_a_registered_name_cannot_be_taken_twice(self):
        register_profile(_fork())
        with self.assertRaises(ValueError) as caught:
            register_profile(_fork())
        self.assertIn("already registered", str(caught.exception))

    def test_the_shipped_set_does_not_grow_with_registrations(self):
        """``SHIPPED`` is what makes "is this one of ours?" survive a registration."""
        register_profile(_fork())
        # Five since 2026-09-17: ORACLES_PRODUCTION_V35 joined as a SHIPPED name.
        # The assertion this test makes is unchanged -- SHIPPED must not grow *because of a
        # registration* -- and register_profile() above is still the thing under test.
        self.assertEqual(SHIPPED, frozenset(
            {STOCK_V314.name, "oracles-2016", ORACLES_PRODUCTION.name, STOCK_V35.name,
             "oracles-production-v3.5"}))

    def test_a_failed_registration_leaves_the_registry_alone(self):
        before = dict(PROFILES)
        with self.assertRaises(ValueError):
            register_profile(_fork(name=STOCK_V314.name))
        self.assertEqual(dict(PROFILES), before)


class ARegistrationStatesWhatItIs(_RegistryCase):
    def test_a_nameless_profile_is_refused(self):
        with self.assertRaises(ValueError):
            register_profile(_fork(name="   "))

    def test_a_profile_with_no_description_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            register_profile(_fork(description=""))
        self.assertIn("cannot be checked against anything", str(caught.exception))

    def test_something_that_is_not_a_profile_is_refused(self):
        with self.assertRaises(TypeError):
            register_profile("oracles-production")                # type: ignore[arg-type]

    def test_every_field_must_be_stated_to_construct_one_at_all(self):
        """The dataclass is the real guard: it has no defaults, so a fork cannot
        register a variant that is only half-described."""
        with self.assertRaises(TypeError):
            FidelityProfile(name="half", description="half a profile")


class TheTwoRegistriesCannotDrift(unittest.TestCase):
    """``config.PROFILES`` used to be a hand-typed copy of the same three objects.

    A fourth profile added to ``profiles.py`` would not have appeared in it, and
    nothing would have said so -- a config file naming the new profile would
    have been told it was unknown. It is derived now, and this is what holds it
    derived.
    """

    def test_every_registry_profile_is_selectable_from_a_config_file(self):
        missing = [name for name in PROFILES if name not in config.PROFILES]
        self.assertEqual(missing, [], "profiles that no config file can name")

    def test_the_constant_style_aliases_still_resolve(self):
        """Written config files use these spellings; they are not free to move."""
        self.assertIs(config.PROFILES["ORACLES_PRODUCTION"], ORACLES_PRODUCTION)
        self.assertIs(config.PROFILES["STOCK_V314"], STOCK_V314)
        self.assertIs(config.PROFILES["ORACLES_2016"], PROFILES["oracles-2016"])

    def test_an_alias_resolves_through_the_registry_and_not_past_it(self):
        for alias, target in config._ALIASES.items():
            with self.subTest(alias=alias):
                self.assertIs(config.PROFILES[alias], PROFILES[target])

    def test_the_error_message_lists_both_spellings(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.toml"
            path.write_text('[fidelity]\nprofile = "nope"\n', encoding="utf-8")
            with self.assertRaises(config.ConfigError) as caught:
                config.load_config(path)
        message = str(caught.exception)
        self.assertIn("ORACLES_PRODUCTION", message)
        self.assertIn("oracles-production", message)


if __name__ == "__main__":
    unittest.main()
