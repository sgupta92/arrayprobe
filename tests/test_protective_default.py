# SPDX-License-Identifier: BSD-3-Clause
"""Steps 1-3: protective corrections default ON off the ORACLES 2D-S/HVPS lineage.

Author ruling 2026-09-23: corrections for data-destroying upstream defects run
by default where no archived product exists, and never on probetype 2 (2D-S/HVPS), whatever the
engine, so ORACLES stamps and bytes do not change.
Steps 1-3 only: the table, the flag and
config key with the exit-2 refusal, and the stamp fragment. Applying the set after the stages
(plan step 4) is not wired yet.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)
run_flight = sys.modules[_spec.name]

try:
    from arrayprobe_enhancements import registry
except ImportError:                                   # pragma: no cover -- CI installs it
    registry = None

#: The ORACLES 2016 2D-S proc stamp before the default, typed from the pre-change driver output. The
#: protective switch must never change it, in any mode, on either side of the flag.
ORACLES_PROC_GOLDEN = (
    "engine=3.1.4 profile=oracles-production reject=(rej_zero_area=True,rej_split=True,"
    "rej_hollow=False,shadowed_area=25,max_edge_img_ar=4,max_comp_img_ar=4) shadow_diode=none")


class _Globals(unittest.TestCase):
    def setUp(self):
        self._saved = (run_flight.ACTIVE.name, run_flight.ENGINE, run_flight.PROTECTIVE_MODE,
                       run_flight.PROTECTIVE_ON)

    def tearDown(self):
        name, engine, mode, on = self._saved
        run_flight.use_preset(name)
        run_flight.ENGINE, run_flight.PROTECTIVE_MODE, run_flight.PROTECTIVE_ON = engine, mode, on


@unittest.skipIf(registry is None, "arrayprobe_enhancements not installed")
class ProtectiveTable(unittest.TestCase):
    def test_lineage_is_empty_on_both_engines(self):
        for engine in ("3.1.4", "3.5"):
            for probe in ("2DS", "HVPS"):
                self.assertEqual(registry.protective_set(engine, probe, 2), frozenset())

    def test_lineage_stays_empty_even_if_a_row_names_probetype_2(self):
        # The guard, not the table's current contents, keeps 2D-S/HVPS unprotected.
        widened = {**registry.PROTECTIVE, "tas_grid_fix": frozenset({0, 1, 2, 3})}
        with mock.patch.dict(registry.PROTECTIVE, widened):
            self.assertEqual(registry.protective_set("3.5", "2DS", 2), frozenset())

    def test_cip_on_v35_carries_the_glitch_fix(self):
        got = registry.protective_set("3.5", "CIP", 1)
        self.assertIn("particle_time_glitch_fix", got)
        self.assertIn("tas_grid_fix", got)
        self.assertNotIn("particle_time_int8_fix", got)

    def test_every_protective_name_is_registered_wired_and_applicable(self):
        for name in registry.PROTECTIVE:
            self.assertIn(name, registry.REGISTRY)
            spec = registry.REGISTRY[name]
            self.assertIsNotNone(spec.entry_point, name)
            self.assertIn(spec.stage, ("proc", "sd"), name)
            self.assertFalse(spec.default_on, name)
            self.assertNotIn(2, registry.PROTECTIVE[name], name)

    def test_glitch_fix_runs_with_drop_by_default(self):
        self.assertEqual(registry.PROTECTIVE_POLICY["particle_time_glitch_fix"],
                         {"policy": "drop"})


class DriverResolution(_Globals):
    def test_oracles_stamp_is_unchanged_in_every_mode(self):
        run_flight.use_preset("ORACLES_2016_2DS_H")
        # Engine 3.1.4 (port validation) is the lineage exception: nothing in any mode.
        run_flight.ENGINE = "3.1.4"
        for mode in ("auto", "on", "off"):
            run_flight.PROTECTIVE_MODE = mode
            run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
            self.assertEqual(run_flight.PROTECTIVE_ON, ())
            self.assertNotIn("protective", run_flight.proc_call_label())
            self.assertNotIn("protective", run_flight.sd_call_label(None))
        # Engine 3.5 corrects the HVPS-bin-table sizing by default: the 2D-S that would be
        # sized on the HVPS table gets bin_table_fix unless the protective set is off.
        run_flight.ENGINE = "3.5"
        for mode, want in (("auto", (run_flight.BIN_TABLE_FIX,)),
                           ("on", (run_flight.BIN_TABLE_FIX,)), ("off", ())):
            run_flight.PROTECTIVE_MODE = mode
            run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
            self.assertEqual(run_flight.PROTECTIVE_ON, want, mode)
        run_flight.ENGINE = "3.1.4"
        self.assertEqual(run_flight.proc_call_label(), ORACLES_PROC_GOLDEN)

    @unittest.skipIf(registry is None, "arrayprobe_enhancements not installed")
    def test_cip_auto_resolves_on_and_stamps_it(self):
        run_flight.use_preset("UND_2016_CIP")
        run_flight.ENGINE = "3.5"
        run_flight.PROTECTIVE_MODE = "auto"
        run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
        self.assertIn("particle_time_glitch_fix", run_flight.PROTECTIVE_ON)
        self.assertIn(" protective=on:", run_flight.proc_call_label())

    def test_off_gives_empty_set_and_off_stamp(self):
        run_flight.use_preset("UND_2016_CIP")
        run_flight.ENGINE = "3.5"
        run_flight.PROTECTIVE_MODE = "off"
        run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
        self.assertEqual(run_flight.PROTECTIVE_ON, ())
        self.assertTrue(run_flight.proc_call_label().endswith(" protective=off"))

    @unittest.skipIf(registry is None, "arrayprobe_enhancements not installed")
    def test_every_protective_name_is_applied_or_refused_by_name(self):
        # The silent drop (tas_grid_fix filtered out for want of a chain adapter) is impossible:
        # each PROTECTIVE name has a chain adapter or is driver-applied ...
        from arrayprobe_enhancements import pipeline
        for name in registry.PROTECTIVE:
            self.assertTrue(name in pipeline._APPLIERS or name in run_flight.DRIVER_PROTECTIVE,
                            name)
        # ... and a name with neither is refused, naming it, rather than left out.
        run_flight.use_preset("UND_2016_CIP")
        run_flight.ENGINE = "3.5"
        run_flight.PROTECTIVE_MODE = "auto"
        widened = {**registry.PROTECTIVE, "spot_edge_fix": frozenset({1})}
        with mock.patch.dict(registry.PROTECTIVE, widened), \
                mock.patch.object(registry.applicability, "applicable", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "spot_edge_fix"):
                run_flight.resolve_protective()

    @unittest.skipIf(registry is None, "arrayprobe_enhancements not installed")
    def test_tas_grid_fix_is_applied_on_cip_by_default_and_skipped_when_off(self):
        run_flight.use_preset("UND_2016_CIP")
        run_flight.ENGINE = "3.5"
        saved_chain = run_flight.TAS_CHAIN
        try:
            run_flight.TAS_CHAIN = None
            run_flight.PROTECTIVE_MODE = "auto"
            run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
            self.assertIn("tas_grid_fix", run_flight.PROTECTIVE_ON)
            self.assertTrue(run_flight.tas_grid_fix_on())
            # The chain never gets it (the driver applies it in S4); the stamp names it.
            self.assertNotIn("tas_grid_fix",
                             run_flight.pipeline_protective(run_flight.PROTECTIVE_ON))
            self.assertIn(" tas_grid=collapse", run_flight.sd_call_label(None))
            self.assertIn("tas_grid_fix", run_flight.proc_call_label())
            # With a TAS source chain, the regular grid is the default form of the fix.
            self.assertEqual(run_flight.default_tas_grid("aircraft"), "regular")
            self.assertEqual(run_flight.default_tas_grid(None), "probe")
            run_flight.PROTECTIVE_MODE = "off"
            run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
            self.assertFalse(run_flight.tas_grid_fix_on())
            self.assertNotIn("tas_grid=", run_flight.sd_call_label(None))
            self.assertEqual(run_flight.default_tas_grid("aircraft"), "probe")
        finally:
            run_flight.TAS_CHAIN = saved_chain

    def test_an_explicit_probe_grid_with_a_chain_drops_it_from_the_stamp(self):
        """--tas-grid probe with a --tas-source chain applies neither form, so the stamp must
        not claim tas_grid_fix (review F2); without a chain the collapse still runs."""
        run_flight.PROTECTIVE_ON = ("particle_time_glitch_fix", "tas_grid_fix")
        run_flight.drop_opted_out_tas_grid_fix("probe", None)
        self.assertIn("tas_grid_fix", run_flight.PROTECTIVE_ON)
        run_flight.drop_opted_out_tas_grid_fix("regular", "aircraft")
        self.assertIn("tas_grid_fix", run_flight.PROTECTIVE_ON)
        run_flight.drop_opted_out_tas_grid_fix("probe", "aircraft")
        self.assertEqual(run_flight.PROTECTIVE_ON, ("particle_time_glitch_fix",))
        self.assertNotIn("tas_grid_fix", run_flight.proc_call_label())

    def test_oracles_presets_never_get_tas_grid_fix(self):
        saved_chain = run_flight.TAS_CHAIN
        try:
            run_flight.TAS_CHAIN = None
            for preset in ("ORACLES_2016_2DS_H", "ORACLES_2016_HVPS"):
                if preset not in run_flight.PRESETS:
                    continue
                run_flight.use_preset(preset)
                for mode in ("auto", "on"):
                    run_flight.PROTECTIVE_MODE = mode
                    run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
                    self.assertFalse(run_flight.tas_grid_fix_on(), preset)
                    self.assertNotIn("tas_grid=", run_flight.sd_call_label(None), preset)
                    self.assertEqual(run_flight.default_tas_grid("aircraft"), "probe", preset)
        finally:
            run_flight.TAS_CHAIN = saved_chain

    @unittest.skipIf(registry is None, "arrayprobe_enhancements not installed")
    def test_a_config_false_takes_the_name_out_of_the_set_the_stamp_and_s4(self):
        """``[enhancements] <name> = false`` wins over the default-on set on every path, not
        only under --enhancements: the name is not applied, the ``protective=on:`` stamp does
        not name it, and for ``tas_grid_fix`` S4 does not collapse the grid."""
        import types

        sys.path.insert(0, str(ROOT / "tests"))
        import _run_flight_state
        _run_flight_state.preserve(self, run_flight)
        config = Path(self._tmp_dir()) / "cip.toml"
        config.write_text('[fidelity]\nprofile = "ORACLES_PRODUCTION"\n'
                          "[enhancements]\nparticle_time_glitch_fix = false\n"
                          "tas_grid_fix = false\n", encoding="utf-8")
        args = types.SimpleNamespace(config=config, iat_file=run_flight.IAT_FILE,
                                     diode_corrected=False, accept_unstamped=False,
                                     engine="3.1.4")
        self.assertIsNotNone(run_flight._apply_config(args, None, []))
        self.assertEqual(run_flight.ENHANCEMENTS_DECLARED_OFF,
                         ("particle_time_glitch_fix", "tas_grid_fix"))
        run_flight.use_preset("UND_2016_CIP")
        run_flight.ENGINE = "3.5"
        run_flight.PROTECTIVE_MODE = "auto"
        run_flight.TAS_CHAIN = None
        run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
        self.assertEqual(run_flight.PROTECTIVE_ON, ())
        self.assertFalse(run_flight.tas_grid_fix_on())
        self.assertNotIn("tas_grid=", run_flight.sd_call_label(None))
        self.assertTrue(run_flight.proc_call_label().endswith(" protective=off"))
        # One name off leaves the other on, and stamped.
        run_flight.ENHANCEMENTS_DECLARED_OFF = ("particle_time_glitch_fix",)
        run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
        self.assertEqual(run_flight.PROTECTIVE_ON, ("tas_grid_fix",))
        self.assertIn(" protective=on:tas_grid_fix", run_flight.proc_call_label())

    def _tmp_dir(self) -> str:
        import tempfile
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return d.name

    @unittest.skipIf(registry is None, "arrayprobe_enhancements not installed")
    def test_collapse_removes_repeated_seconds_before_sizedist(self):
        import numpy as np
        t = np.array([120000.0, 120000.5, 120001.0, 120002.0, 120002.2])
        tas = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
        got_t, got_tas = run_flight._collapse_probe_grid(t, tas, "test")
        np.testing.assert_array_equal(got_t, [120000.0, 120001.0, 120002.0])
        np.testing.assert_array_equal(got_tas, [100.0, 102.0, 103.0])

    def test_missing_package_raises_import_error_off_the_lineage_only(self):
        with mock.patch.dict(sys.modules, {"arrayprobe_enhancements": None}):
            run_flight.use_preset("UND_2016_CIP")
            run_flight.ENGINE = "3.5"
            run_flight.PROTECTIVE_MODE = "auto"
            with self.assertRaises(ImportError):
                run_flight.resolve_protective()
            run_flight.use_preset("ORACLES_2016_2DS_H")
            # The bin-table fix is applied by the driver, so it needs no enhancements package.
            self.assertEqual(run_flight.resolve_protective(), (run_flight.BIN_TABLE_FIX,))
            run_flight.ENGINE = "3.1.4"
            self.assertEqual(run_flight.resolve_protective(), ())

    def test_protective_fragment_never_makes_a_product_stale(self):
        base = "engine=3.5 probe=CIP channels=none"
        self.assertTrue(run_flight._stamps_equivalent(
            base + " protective=off", base + " protective=on:tas_grid_fix"))
        self.assertTrue(run_flight._stamps_equivalent(base, base + " protective=off"))
        self.assertFalse(run_flight._stamps_equivalent(base + " x=1", base + " protective=off"))


if __name__ == "__main__":
    unittest.main()
