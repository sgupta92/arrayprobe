# SPDX-License-Identifier: BSD-3-Clause
"""Decision #10 (2026-08-28): the config loader selects, never sets."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from arrayprobe.config import ConfigError, load_config
from arrayprobe.profiles import ORACLES_PRODUCTION

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
from tests._repo import needs_v314_engine  # noqa: E402

setUpModule, tearDownModule = module_hooks()




def _write(text: str) -> Path:
    d = tempfile.mkdtemp()
    p = Path(d) / "run.toml"
    p.write_text(text, encoding="utf-8")
    return p


class LoadConfig(unittest.TestCase):
    def test_full_example(self):
        cfg = load_config(_write('''
[fidelity]
profile = "ORACLES_PRODUCTION"
[shattering]
threshold_file = "2DS_intArrThreshold_MISSING.cdf"
[masking]
diodes = { base160910124240 = [95], base160910071623 = [77] }
[export]
format = "NETCDF3_CLASSIC"
[enhancements]
last_record_fix = true
zero_image_recovery = false
'''))
        self.assertIs(cfg.profile, ORACLES_PRODUCTION)
        self.assertEqual(cfg.shattering_threshold_file, "2DS_intArrThreshold_MISSING.cdf")
        self.assertEqual(cfg.diode_masks, {"base160910124240": (95,), "base160910071623": (77,)})
        self.assertTrue(cfg.enabled("last_record_fix"))
        self.assertFalse(cfg.enabled("zero_image_recovery"))
        self.assertFalse(cfg.enabled("not_mentioned"), "enhancements default OFF")

    def test_profile_is_required(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[export]\nformat = "NETCDF4"\n'))

    def test_unknown_profile(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "MY_TREE"\n'))

    def test_raw_threshold_key_is_rejected_anywhere(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n[run]\nrej_hollow = 0\n'))

    def test_shattering_section_needs_explicit_file(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n[shattering]\n'))
        cfg = load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'))
        self.assertIsNone(cfg.shattering_threshold_file)

    def test_mask_validation(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n[masking]\n'
                               'diodes = { x = [0] }\n'))

    def test_enhancement_must_be_bool(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n[enhancements]\nk = 1\n'))

    def test_unknown_section(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n[magic]\nx = 1\n'))


_ARM_BASE = '[fidelity]\nprofile = "STOCK_V314"\n'


class ConfigValidatesArmKeys(unittest.TestCase):
    """``[arm]`` -- the real ARM identifiers ``arrayprobe_enhancements.arm_export``
    needs to run through the enhancements driver. The whole point is that these are never
    invented or defaulted, so most of this class is refusals."""

    def test_no_arm_section_is_empty_and_not_an_error(self):
        cfg = load_config(_write(_ARM_BASE))
        self.assertEqual(cfg.arm, {})

    def test_all_three_required_ids_are_accepted(self):
        cfg = load_config(_write(
            _ARM_BASE + '[arm]\nsite_id = "ena"\nplatform_id = "aaf2dsharrayprobev35"\n'
                       'facility_id = "F1"\n'))
        self.assertEqual(cfg.arm, {"site_id": "ena", "platform_id": "aaf2dsharrayprobev35",
                                   "facility_id": "F1"})

    def test_data_level_is_optional_and_carried_verbatim_when_given(self):
        cfg = load_config(_write(
            _ARM_BASE + '[arm]\nsite_id = "ena"\nplatform_id = "aaf2dsh"\nfacility_id = "F1"\n'
                       'data_level = "b1"\n'))
        self.assertEqual(cfg.arm["data_level"], "b1")

    def test_data_level_absent_means_absent_not_defaulted_here(self):
        """The default ("c1") is arm_export.export()'s own, applied at call time -- the
        loader itself never invents a value for a key the file did not set."""
        cfg = load_config(_write(
            _ARM_BASE + '[arm]\nsite_id = "ena"\nplatform_id = "aaf2dsh"\nfacility_id = "F1"\n'))
        self.assertNotIn("data_level", cfg.arm)

    def test_site_id_alone_is_refused(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(_write(_ARM_BASE + '[arm]\nsite_id = "ena"\n'))
        self.assertIn("platform_id", str(cm.exception))
        self.assertIn("facility_id", str(cm.exception))

    def test_two_of_three_is_still_refused(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(_write(
                _ARM_BASE + '[arm]\nsite_id = "ena"\nplatform_id = "aaf2dsh"\n'))
        self.assertIn("facility_id", str(cm.exception))

    def test_empty_section_is_refused(self):
        with self.assertRaises(ConfigError):
            load_config(_write(_ARM_BASE + '[arm]\n'))

    def test_unknown_key_is_refused(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(_write(
                _ARM_BASE + '[arm]\nsite_id = "ena"\nplatform_id = "aaf2dsh"\n'
                           'facility_id = "F1"\ncampaign = "ACE-ENA"\n'))
        self.assertIn("campaign", str(cm.exception))

    def test_a_blank_id_is_refused_not_treated_as_present(self):
        with self.assertRaises(ConfigError):
            load_config(_write(
                _ARM_BASE + '[arm]\nsite_id = ""\nplatform_id = "aaf2dsh"\n'
                           'facility_id = "F1"\n'))

    def test_a_non_string_id_is_refused(self):
        with self.assertRaises(ConfigError):
            load_config(_write(
                _ARM_BASE + '[arm]\nsite_id = 1\nplatform_id = "aaf2dsh"\nfacility_id = "F1"\n'))

    def test_arm_under_soda2_is_validated_at_load_and_refused_at_run(self):
        """Since 2026-10-08 (f13243f, slice S7a) the loader accepts ``[arm]`` under
        engine = "soda2" and validates it by the same rules as a UIOOPS file; ``arrayprobe soda2
        run`` then refuses it by name at exit 2 while the SODA-2 ARM output is unbuilt. The
        run-time refusal is ``test_cli_soda2_outputs.SODA2OutputsSection
        .test_arm_is_refused_while_the_arm_output_is_unbuilt``; this test holds the load-time
        half: a well-formed ``[arm]`` loads on its own, and a malformed one is refused here."""
        base = '[run]\nengine = "soda2"\n[soda2]\nfn = "x.pbp"\noutdir = "out"\n'
        cfg = load_config(_write(
            base + '[arm]\nsite_id = "ena"\nplatform_id = "aaf2dsh"\nfacility_id = "F1"\n'))
        self.assertEqual(cfg.arm["site_id"], "ena")
        with self.assertRaises(ConfigError) as cm:
            load_config(_write(
                base + '[arm]\nsite_id = "ena"\nplatform_id = "aaf2dsh"\n'
                       'facility_id = "F1"\ncampaign = "ACE-ENA"\n'))
        self.assertIn("campaign", str(cm.exception))


class ProfileModule(unittest.TestCase):
    """``[fidelity].profile_module`` -- makes a ``register_profile()`` profile
    resolvable by a config file, which is what lets it survive a fresh
    subprocess (2026-09-10: found missing when a registered profile silently
    fell back to the default under ``run_flight.py --chunks``/``--jobs``,
    because each worker re-imports ``arrayprobe.profiles`` from scratch and
    never re-runs whatever registered the profile in the parent)."""

    def _write_module(self, profile_name: str) -> tuple[Path, str]:
        """A tiny importable module that registers one fork profile at import
        time -- the shape a real fork's own plugin module would take."""
        import dataclasses

        from arrayprobe.profiles import STOCK_V314
        d = tempfile.mkdtemp()
        sys.path.insert(0, d)
        self.addCleanup(sys.path.remove, d)
        mod_name = f"_test_profile_module_{abs(hash(profile_name))}"
        fields = dataclasses.asdict(STOCK_V314)
        fields["reject_thresholds"] = STOCK_V314.reject_thresholds
        fields["name"] = profile_name
        fields["description"] = "registered by test_config.py"
        fields["spec_buffer_guard"] = False
        args = ", ".join(f"{k}={v!r}" for k, v in fields.items())
        (Path(d) / f"{mod_name}.py").write_text(
            "from arrayprobe.profiles import FidelityProfile, register_profile\n"
            "from arrayprobe.reject import RejectConfig\n"
            f"register_profile(FidelityProfile({args}))\n",
            encoding="utf-8")
        return d, mod_name

    @needs_v314_engine
    def test_a_registered_profile_is_selectable_once_its_module_is_named(self):
        _, mod_name = self._write_module("test-fork-2026-09-10")
        cfg = load_config(_write(
            '[fidelity]\n'
            f'profile = "test-fork-2026-09-10"\n'
            f'profile_module = "{mod_name}"\n'))
        self.assertEqual(cfg.profile.name, "test-fork-2026-09-10")
        self.assertEqual(cfg.profile_module, mod_name)

    def test_without_profile_module_an_unregistered_profile_is_still_unknown(self):
        """The control: naming the profile without naming its module must
        still fail exactly as it always has -- profile_module is additive,
        never a way to skip validation."""
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "test-fork-never-registered"\n'))

    def test_a_module_that_does_not_exist_is_a_config_error_not_a_crash(self):
        with self.assertRaises(ConfigError):
            load_config(_write(
                '[fidelity]\nprofile = "STOCK_V314"\n'
                'profile_module = "this_module_does_not_exist_anywhere"\n'))

    def test_profile_module_absent_is_none_not_an_error(self):
        """The overwhelming majority of configs name a shipped profile and
        have no module to import at all -- this must stay silent and free."""
        cfg = load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'))
        self.assertIsNone(cfg.profile_module)


class RunSection(unittest.TestCase):
    """``[run]`` selects (engine, preset) and locates (raw, out, stages); it
    never describes a threshold or a campaign field."""

    def test_run_keys_are_validated_not_passed_through(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'
                               '[run]\nengin = "3.1.4"\n'))
        self.assertIn("engin", str(ctx.exception))

    def test_engine_must_name_a_known_port(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'
                               '[run]\nengine = "3.4.1"\n'))

    def test_raw_must_be_a_list_of_strings(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'
                               '[run]\nraw = "x.2DS"\n'))

    def test_a_full_run_section_round_trips(self):
        cfg = load_config(_write('''
[fidelity]
profile = "STOCK_V314"
[run]
engine = "3.1.4"
preset = "ORACLES_2016_2DS_H"
raw = ["../raw/base1609*.2DS"]
out = "../_decoded"
stages = "234"
'''))
        self.assertEqual(cfg.run, {
            "engine": "3.1.4",
            "preset": "ORACLES_2016_2DS_H",
            "raw": ["../raw/base1609*.2DS"],
            "out": "../_decoded",
            "stages": "234",
        })

    def test_a_threshold_under_run_is_still_refused(self):
        # Already covered by LoadConfig.test_raw_threshold_key_is_rejected_anywhere;
        # confirmed here only to keep the two forms of rejection (unknown [run]
        # key vs. forbidden key anywhere) visibly distinct in one place.
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'
                               '[run]\nrej_hollow = 0\n'))

    def test_tas_file_is_a_run_key_and_must_be_a_string(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'
                               '[run]\ntas_file = 3\n'))
        cfg = load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'
                                 '[run]\ntas_file = "x.cdf"\n'))
        self.assertEqual(cfg.run["tas_file"], "x.cdf")

    def test_a_threshold_beside_tas_file_is_still_refused(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(_write('[fidelity]\nprofile = "STOCK_V314"\n'
                               '[run]\ntas_file = "x.cdf"\nrej_hollow = 0\n'))
        self.assertIn("rej_hollow", str(ctx.exception))

    def test_probe_is_a_run_key_and_must_be_a_string(self):
        with self.assertRaises(ConfigError):
            load_config(_write('[fidelity]\nprofile = "stock-v3.5"\n'
                               '[run]\nengine = "3.5"\nprobe = 1\n'))
        cfg = load_config(_write('[fidelity]\nprofile = "stock-v3.5"\n'
                                 '[run]\nengine = "3.5"\nprobe = "CIP"\n'))
        self.assertEqual(cfg.run["probe"], "CIP")

    def test_tas_from_probe_is_a_list_of_paths(self):
        for bad in ('"a.tas.csv"', '[1]'):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                load_config(_write('[fidelity]\nprofile = "stock-v3.5"\n'
                                   f'[run]\nengine = "3.5"\ntas_from_probe = {bad}\n'))
        cfg = load_config(_write('[fidelity]\nprofile = "stock-v3.5"\n'
                                 '[run]\nengine = "3.5"\ntas_from_probe = ["d/*.tas.csv"]\n'))
        self.assertEqual(cfg.run["tas_from_probe"], ["d/*.tas.csv"])


if __name__ == "__main__":
    unittest.main()
