# SPDX-License-Identifier: BSD-3-Clause
"""The author-defaults file (minimal form, project decision 2026-09-28):
a base profile plus cited overrides for the six reject thresholds, in a content-hashed file,
reached from a run config through ``[fidelity].authordefaults``.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

# The shared helper restores the live profile registry after every test in this module
# (register_profile() mutates module-level state that otherwise leaks into later tests).
from tests._profile_registry_guard import module_hooks  # noqa: E402

from arrayprobe.authordefaults import (
    AuthorDefaultsError,
    content_hash,
    expected_filename,
    load_authordefaults,
    resolve_profile,
)
from arrayprobe.config import ConfigError, load_config
from arrayprobe.profiles import STOCK_V314

setUpModule, tearDownModule = module_hooks()


def _write_authordefaults(d: Path, body: str) -> Path:
    """Write ``body`` under the file name its own content demands."""
    data = body.encode("utf-8")
    p = d / expected_filename(data)
    p.write_bytes(data)
    return p


_ONE_OVERRIDE = '''
[fidelity]
base_profile = "STOCK_V314"

[thresholds.rej_hollow]
value = false
citation = "S. Gupta, 2026-09-28: matches ORACLES production for this instrument."
'''

_TWO_OVERRIDES = '''
[fidelity]
base_profile = "STOCK_V314"

[thresholds.rej_hollow]
value = false
citation = "author choice A"

[thresholds.max_edge_img_ar]
value = 4.5
citation = "author choice B"
'''


class LoadAuthorDefaults(unittest.TestCase):
    def test_loads_a_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), _ONE_OVERRIDE)
            ad = load_authordefaults(p)
        self.assertEqual(ad.base_profile_name, "stock-v3.1.4")
        self.assertEqual(ad.overrides, {"rej_hollow": False})
        self.assertIn("S. Gupta", ad.citations["rej_hollow"])
        self.assertEqual(ad.hash, content_hash(_ONE_OVERRIDE.encode("utf-8")))
        self.assertEqual(ad.stamp(), f"authordefaults:{p}#{ad.hash}")

    def test_multiple_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), _TWO_OVERRIDES)
            ad = load_authordefaults(p)
        self.assertEqual(ad.overrides, {"rej_hollow": False, "max_edge_img_ar": 4.5})

    def test_refuses_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # Correctly named for DIFFERENT content -- write the two-override body under the
            # one-override body's expected name.
            wrong_name = d / expected_filename(_ONE_OVERRIDE.encode("utf-8"))
            wrong_name.write_text(_TWO_OVERRIDES, encoding="utf-8")
            with self.assertRaises(AuthorDefaultsError) as ctx:
                load_authordefaults(wrong_name)
        self.assertIn("does not match its own content", str(ctx.exception))

    def test_refuses_a_name_with_no_hash_shape(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "authordefaults.toml"
            p.write_text(_ONE_OVERRIDE, encoding="utf-8")
            with self.assertRaises(AuthorDefaultsError) as ctx:
                load_authordefaults(p)
        self.assertIn("not a valid author-defaults file name", str(ctx.exception))

    def test_refuses_unknown_threshold_key(self):
        body = '''
[fidelity]
base_profile = "STOCK_V314"

[thresholds.spec_buffer_guard]
value = false
citation = "not one of the six"
'''
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), body)
            with self.assertRaises(AuthorDefaultsError) as ctx:
                load_authordefaults(p)
        self.assertIn("not one of the six reject thresholds", str(ctx.exception))

    def test_refuses_unknown_section(self):
        body = '''
[fidelity]
base_profile = "STOCK_V314"

[run]
engine = "3.1.4"
'''
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), body)
            with self.assertRaises(AuthorDefaultsError) as ctx:
                load_authordefaults(p)
        self.assertIn("unknown section(s)", str(ctx.exception))

    def test_refuses_missing_citation(self):
        body = '''
[fidelity]
base_profile = "STOCK_V314"

[thresholds.rej_hollow]
value = false
'''
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), body)
            with self.assertRaises(AuthorDefaultsError) as ctx:
                load_authordefaults(p)
        self.assertIn("must be a table with exactly 'value' and 'citation'", str(ctx.exception))

    def test_refuses_a_boolean_threshold_given_as_a_number(self):
        body = '''
[fidelity]
base_profile = "STOCK_V314"

[thresholds.rej_hollow]
value = 0
citation = "should be true/false, not 0/1"
'''
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), body)
            with self.assertRaises(AuthorDefaultsError) as ctx:
                load_authordefaults(p)
        self.assertIn("must be true or false", str(ctx.exception))

    def test_refuses_a_numeric_threshold_given_as_a_boolean(self):
        body = '''
[fidelity]
base_profile = "STOCK_V314"

[thresholds.max_edge_img_ar]
value = true
citation = "should be a number"
'''
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), body)
            with self.assertRaises(AuthorDefaultsError) as ctx:
                load_authordefaults(p)
        self.assertIn("must be a number", str(ctx.exception))

    def test_refuses_unknown_base_profile(self):
        body = '''
[fidelity]
base_profile = "NOT_A_REAL_PROFILE"
'''
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), body)
            with self.assertRaises(AuthorDefaultsError) as ctx:
                load_authordefaults(p)
        self.assertIn("unknown base profile", str(ctx.exception))

    def test_refuses_a_directory(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AuthorDefaultsError):
                load_authordefaults(Path(d))


class ResolveProfile(unittest.TestCase):
    def test_generates_a_full_profile_with_overrides_applied(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), _TWO_OVERRIDES)
            ad = load_authordefaults(p)
            profile = resolve_profile(ad)
        self.assertEqual(profile.name, f"authordefaults-{ad.hash}")
        self.assertFalse(profile.reject_thresholds.rej_hollow)
        self.assertEqual(profile.reject_thresholds.max_edge_img_ar, 4.5)
        # Every non-overridden field, including the other reject thresholds, is the base's.
        self.assertEqual(profile.reject_thresholds.rej_zero_area,
                         STOCK_V314.reject_thresholds.rej_zero_area)
        self.assertEqual(profile.spec_buffer_guard, STOCK_V314.spec_buffer_guard)

    def test_idempotent_within_one_process(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_authordefaults(Path(d), _ONE_OVERRIDE)
            ad = load_authordefaults(p)
            first = resolve_profile(ad)
            second = resolve_profile(ad)
        self.assertIs(first, second)


class ConfigIntegration(unittest.TestCase):
    """``[fidelity].authordefaults`` reached from a run config -- ``load_config``'s own wiring."""

    def test_selects_a_generated_profile(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_authordefaults(d, _ONE_OVERRIDE)
            ad_name = expected_filename(_ONE_OVERRIDE.encode("utf-8"))
            run_toml = d / "run.toml"
            run_toml.write_text(f'''
[fidelity]
authordefaults = "{ad_name}"
''', encoding="utf-8")
            cfg = load_config(run_toml)
        self.assertFalse(cfg.profile.reject_thresholds.rej_hollow)
        self.assertIsNotNone(cfg.authordefaults_stamp)
        self.assertTrue(cfg.authordefaults_stamp.startswith("authordefaults:"))
        expected_hash = content_hash(_ONE_OVERRIDE.encode("utf-8"))
        self.assertIn(f"#{expected_hash}", cfg.authordefaults_stamp)

    def test_absent_key_changes_nothing(self):
        """Bit-identical resolution: a config with no [fidelity].authordefaults behaves exactly
        as it did before this feature existed."""
        with tempfile.TemporaryDirectory() as d:
            run_toml = Path(d) / "run.toml"
            run_toml.write_text('''
[fidelity]
profile = "ORACLES_PRODUCTION"
''', encoding="utf-8")
            cfg = load_config(run_toml)
        self.assertIsNone(cfg.authordefaults_stamp)
        self.assertEqual(cfg.profile.name, "oracles-production")

    def test_refuses_both_profile_and_authordefaults(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_authordefaults(d, _ONE_OVERRIDE)
            ad_name = expected_filename(_ONE_OVERRIDE.encode("utf-8"))
            run_toml = d / "run.toml"
            run_toml.write_text(f'''
[fidelity]
profile = "ORACLES_PRODUCTION"
authordefaults = "{ad_name}"
''', encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_config(run_toml)
        self.assertIn("names both profile and authordefaults", str(ctx.exception))

    def test_refuses_neither_profile_nor_authordefaults(self):
        with tempfile.TemporaryDirectory() as d:
            run_toml = Path(d) / "run.toml"
            run_toml.write_text('[fidelity]\n', encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_config(run_toml)
        self.assertIn("profile or [fidelity].authordefaults is required", str(ctx.exception))

    def test_propagates_a_bad_authordefaults_file_as_configerror(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            body = ('[fidelity]\nbase_profile = "STOCK_V314"\n'
                    '[thresholds.bogus]\nvalue=1\ncitation="x"\n')
            _write_authordefaults(d, body)
            ad_name = expected_filename(body.encode("utf-8"))
            run_toml = d / "run.toml"
            run_toml.write_text(f'[fidelity]\nauthordefaults = "{ad_name}"\n', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(run_toml)

    def test_missing_authordefaults_file_is_a_configerror(self):
        with tempfile.TemporaryDirectory() as d:
            run_toml = Path(d) / "run.toml"
            run_toml.write_text(
                '[fidelity]\nauthordefaults = "authordefaults-0000000000000000.toml"\n',
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_config(run_toml)
        self.assertIn("not found", str(ctx.exception))


class ContentHash(unittest.TestCase):
    def test_matches_sha256_prefix(self):
        data = b"hello"
        self.assertEqual(content_hash(data), hashlib.sha256(data).hexdigest()[:16])

    def test_expected_filename_shape(self):
        name = expected_filename(b"x")
        self.assertTrue(name.startswith("authordefaults-"))
        self.assertTrue(name.endswith(".toml"))


if __name__ == "__main__":
    unittest.main()
