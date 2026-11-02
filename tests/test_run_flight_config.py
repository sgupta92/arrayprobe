# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py --config`` selects, logs, and never overrides the command line.

The config file exists so a run's fidelity-sensitive decisions are declared in one place. That
only helps if what it changed is visible, so this pins the three properties that matter: the
command line wins, every change is logged, and a config cannot silently enable masking.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
run_flight = importlib.util.module_from_spec(spec)
# Registered in sys.modules before exec: with `from __future__ import annotations`,
# dataclasses resolves a string annotation by looking the defining module up in
# sys.modules, and gets None if it was never put there. Added 2026-09-08, when
# run_flight gained a dataclass and every loader written this way broke at import.
sys.modules.setdefault(spec.name, run_flight)
spec.loader.exec_module(run_flight)

# AuthorDefaultsStamp registers a generated profile (register_profile()); restore the live
# registry afterward so it does not leak into a later test module (see
# tests/_profile_registry_guard.py's own docstring).
from tests import _run_flight_state  # noqa: E402
from tests._profile_registry_guard import module_hooks  # noqa: E402

# The registry restore and the driver-state restore both run as module cleanups, so
# they unwind in reverse of setup: run_flight's globals first, then the registry.
_registry_setup, _registry_teardown = module_hooks()


def setUpModule():  # noqa: N802 -- unittest's name
    _registry_setup()
    unittest.addModuleCleanup(_registry_teardown)
    _run_flight_state.preserve_module(run_flight)


def _toml(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "run.toml"
    path.write_text(text, encoding="utf-8")
    return path


class _Args:
    def __init__(self, **kw):
        self.iat_file = run_flight.IAT_FILE
        self.diode_corrected = False
        self.accept_unstamped = False
        # --engine is required at the argparse level; _apply_config reads it directly.
        self.engine = "3.1.4"
        self.__dict__.update(kw)


BASE = '[fidelity]\nprofile = "ORACLES_PRODUCTION"\n'


class ConfigApplication(unittest.TestCase):
    def setUp(self):
        self._masks = dict(run_flight.SHADOW_DIODE_OVERRIDES)

    def tearDown(self):
        run_flight.SHADOW_DIODE_OVERRIDES.clear()
        run_flight.SHADOW_DIODE_OVERRIDES.update(self._masks)

    def _apply(self, toml_text, args=None, argv=()):
        args = args or _Args()
        args.config = _toml(toml_text)
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_flight._apply_config(args, None, list(argv))
        return out, buf.getvalue()

    def test_a_namespace_without_engine_raises_rather_than_stamping_v314(self):
        # Cloud pass 8, item 4: _apply_config once read getattr(args, "engine", "3.1.4"), so a
        # hand-built Namespace with no engine ran silently as v3.1.4. It must now refuse.
        args = _Args()
        del args.engine
        with self.assertRaises(AttributeError):
            self._apply(BASE, args=args)

    def test_threshold_file_is_taken_from_the_config(self):
        args, log = self._apply(BASE + '[shattering]\nthreshold_file = "other.cdf"\n')
        self.assertEqual(args.iat_file, "other.cdf")
        self.assertIn("iat-file", log)

    def test_command_line_wins_over_the_config(self):
        args, log = self._apply(BASE + '[shattering]\nthreshold_file = "other.cdf"\n',
                                args=_Args(iat_file="mine.cdf"), argv=["--iat-file", "mine.cdf"])
        self.assertEqual(args.iat_file, "mine.cdf")
        self.assertIn("command line wins", log)

    def test_diode_masks_are_registered_and_logged(self):
        toml = BASE + '[masking]\ndiodes = { base160910124240 = [95, 96] }\n'
        args, log = self._apply(toml, args=_Args(diode_corrected=True))
        self.assertEqual(run_flight.SHADOW_DIODE_OVERRIDES["base160910124240"], [95, 96])
        self.assertIn("diode mask", log)

    def test_a_config_cannot_silently_enable_masking(self):
        toml = BASE + '[masking]\ndiodes = { base160910071623 = [77] }\n'
        args, log = self._apply(toml)                       # --diode-corrected not given
        self.assertFalse(args.diode_corrected)
        self.assertIn("stay unused", log)

    def test_another_profile_actually_switches_the_driver(self):
        """Until 2026-09-10 this raised SystemExit(2) --
        'this driver only runs ORACLES_PRODUCTION'. A10's own whole-file
        measurement needed a non-production profile through this same driver
        and could not get one, which is why it was 'never free'. Every stage
        call site now reads the live PROFILE global instead of the literal
        ORACLES_PRODUCTION -- see run_flight.PROFILE's docstring."""
        real_profile = run_flight.PROFILE
        try:
            args, log = self._apply('[fidelity]\nprofile = "STOCK_V314"\n')
            from arrayprobe.profiles import STOCK_V314
            self.assertIs(run_flight.PROFILE, STOCK_V314)
            self.assertIn("profile switched", log)
        finally:
            run_flight.PROFILE = real_profile

    def test_the_default_profile_is_unchanged_and_not_logged_as_a_switch(self):
        args, log = self._apply(BASE)
        self.assertIs(run_flight.PROFILE, run_flight.ORACLES_PRODUCTION)
        self.assertNotIn("switched", log)

    def test_enhancement_switches_are_reported_not_applied_without_the_flag(self):
        """Renamed and re-aimed 2026-09-20. It used to assert the log said ``port
        only`` -- the wording of a driver that could not apply an enhancement at all. It now
        asserts the property that actually matters and did not change: **a config file cannot
        switch on a behaviour change by itself.** ``--enhancements`` must be given too, exactly
        as ``[masking]`` needs ``--diode-corrected`` (see
        ``test_a_config_cannot_silently_enable_masking`` above, the same rule)."""
        _, log = self._apply(BASE + '[enhancements]\ntas_grid_fix = true\n')
        self.assertIn("tas_grid_fix", log)
        self.assertIn("NOT applied", log)
        self.assertIn("--enhancements", log)

    def test_the_flag_makes_the_config_s_enhancements_live(self):
        """The other half: with ``--enhancements`` the same file is honoured, and says so."""
        _, log = self._apply(BASE + '[enhancements]\ntas_grid_fix = true\n',
                             args=_Args(enhancements=True))
        self.assertIn("tas_grid_fix", log)
        self.assertIn("they are applied", log)


class AuthorDefaultsStamp(unittest.TestCase):
    """``[fidelity].authordefaults`` reaches the driver's own
    ``AUTHORDEFAULTS_STAMP`` global and, from there, every ``config_label`` (proc/sd ``.call``)."""

    def setUp(self):
        self._stamp = run_flight.AUTHORDEFAULTS_STAMP
        self._profile = run_flight.PROFILE

    def tearDown(self):
        run_flight.AUTHORDEFAULTS_STAMP = self._stamp
        run_flight.PROFILE = self._profile

    def _apply(self, toml_text, args=None, argv=()):
        args = args or _Args()
        args.config = _toml(toml_text)
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_flight._apply_config(args, None, list(argv))
        return out, buf.getvalue()

    def test_absent_key_leaves_the_stamp_none_and_the_label_unchanged(self):
        before = run_flight.config_label()
        self._apply(BASE)
        self.assertIsNone(run_flight.AUTHORDEFAULTS_STAMP)
        self.assertEqual(run_flight.config_label(), before)

    def test_present_key_sets_the_global_and_reaches_config_label(self):
        from arrayprobe.authordefaults import expected_filename

        body = ('[fidelity]\nbase_profile = "STOCK_V314"\n\n'
                '[thresholds.rej_hollow]\nvalue = false\ncitation = "test"\n')
        d = Path(tempfile.mkdtemp())
        ad_path = d / expected_filename(body.encode("utf-8"))
        ad_path.write_bytes(body.encode("utf-8"))
        toml = f'[fidelity]\nauthordefaults = "{ad_path.name}"\n'
        run_toml = d / "run.toml"
        run_toml.write_text(toml, encoding="utf-8")
        args = _Args()
        args.config = run_toml
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_flight._apply_config(args, None, [])
        self.assertIsNotNone(run_flight.AUTHORDEFAULTS_STAMP)
        self.assertTrue(run_flight.AUTHORDEFAULTS_STAMP.startswith("authordefaults:"))
        label = run_flight.config_label()
        self.assertIn(run_flight.AUTHORDEFAULTS_STAMP, label)


if __name__ == "__main__":
    unittest.main()
