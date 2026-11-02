# SPDX-License-Identifier: BSD-3-Clause
"""Engine 3.5 warns, and stamps ``bins=v35-otherwise-hvps``, when a 2D-S falls to stock
``sizeDist.m``'s otherwise branch and is sized on the HVPS bin table
(v3.5 ``sizeDist.m:497``, ``:502-505``). Stock behaviour stays reachable: nothing is refused."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_flight", _ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = sys.modules.get("run_flight") or importlib.util.module_from_spec(_spec)
if "run_flight" not in sys.modules:
    sys.modules["run_flight"] = run_flight
    _spec.loader.exec_module(run_flight)

from tests import _run_flight_state  # noqa: E402


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


#: The ARM ENA registration modules are development-only: a distribution may
#: ship without them, and the tests that exercise those cases skip there.
_needs_arm_ena = unittest.skipUnless(
    _has_module("arrayprobe_uiops.register_arm_ena_2ds"),
    "arrayprobe_uiops.register_arm_ena_2ds: the ARM ENA registration module is not in "
    "this distribution",
)


class TestV11OtherwiseBinsWarning(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        run_flight.ENGINE = "3.5"
        run_flight.PROJECT = "ORACLES"
        run_flight.PROBE = "2DS"
        run_flight.PROBE_CASE = None
        run_flight.TAS_FILE = None
        run_flight.PROTECTIVE_MODE = "off"  # these are the opt-out (stock HVPS-table) tests

    def test_fires_for_oracles_2ds_engine_35_no_case(self):
        self.assertTrue(run_flight._v35_otherwise_hvps_bins_on_2ds())
        self.assertIn("upstream bin-table defect", run_flight.V11_BINS_WARNING)
        self.assertIn("0.2-30 mm", run_flight.V11_BINS_WARNING)
        self.assertIn("--probe-case", run_flight.V11_BINS_WARNING)
        self.assertIn(" bins=v35-otherwise-hvps", run_flight.sd_call_label(None))

    def test_silent_with_a_registered_2ds_case(self):
        run_flight.PROBE_CASE = "arm-ena-2ds"
        self.assertFalse(run_flight._v35_otherwise_hvps_bins_on_2ds())
        self.assertNotIn("bins=", run_flight.sd_call_label(None))

    def test_silent_for_hvps(self):
        run_flight.PROBE = "HVPS"
        self.assertFalse(run_flight._v35_otherwise_hvps_bins_on_2ds())
        self.assertNotIn("bins=", run_flight.sd_call_label(None))

    def test_silent_on_engine_314(self):
        run_flight.ENGINE = "3.1.4"
        self.assertFalse(run_flight._v35_otherwise_hvps_bins_on_2ds())

    def test_silent_stamp_is_byte_identical_to_the_label_without_the_key(self):
        # When the check is false, the stamp is exactly what sd_call_label wrote before
        # the key existed: removing the key from a firing label gives the HVPS-case shape.
        run_flight.PROBE = "HVPS"
        silent = run_flight.sd_call_label(None)
        orig = run_flight._v35_otherwise_hvps_bins_on_2ds
        run_flight._v35_otherwise_hvps_bins_on_2ds = lambda: True
        try:
            loud = run_flight.sd_call_label(None)
        finally:
            run_flight._v35_otherwise_hvps_bins_on_2ds = orig
        self.assertEqual(loud.replace(" bins=v35-otherwise-hvps", ""), silent)

    def test_the_warning_is_logged_and_nothing_is_refused(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            if run_flight._v35_otherwise_hvps_bins_on_2ds():
                run_flight.log(run_flight.V11_BINS_WARNING)
        self.assertIn("WARNING (upstream bin-table defect)", buf.getvalue())




def _bin_edges(case_name):
    """The bin edges (mm, ``kk``) S4 sizes on for ``case_name``, or v3.5's own switch for None."""
    v35 = run_flight._v35().module("sizedist")
    cfg = (v35.resolve_probe_case(case_name).defaults if case_name is not None
           else v35.probe_defaults(run_flight.PROJECT, run_flight.PROBE, version="3.5"))
    return [float(x) for x in cfg.kk()]


class TestV11BinTableFixDefaultOn(unittest.TestCase):
    """The HVPS-bin-table correction is on by default on engine 3.5, off under the opt-out,
    and absent from every run it does not reach (a named case, HVPS, engine 3.1.4)."""

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        run_flight.ENGINE = "3.5"
        run_flight.PROJECT = "ORACLES"
        run_flight.PROBE = "2DS"
        run_flight.PROBE_CASE = None
        run_flight.TAS_FILE = None
        run_flight.PROTECTIVE_MODE = "auto"
        run_flight.ENHANCEMENTS_DECLARED_OFF = ()

    # (a) the default
    def test_default_engine_35_oracles_2ds_sizes_on_the_128_bin_ladder(self):
        self.assertTrue(run_flight.bin_table_fix_on())
        case = run_flight._s4_probe_case()
        self.assertEqual(case, "v35-2ds-ladder-fix")
        edges = _bin_edges(case)
        self.assertEqual(len(edges) - 1, 128)
        self.assertEqual(run_flight.resolve_protective(), (run_flight.BIN_TABLE_FIX,))
        label = run_flight.sd_call_label(None)
        self.assertIn(" bins=2ds-ladder(V11-fix)", label)
        self.assertNotIn("bins=v35-otherwise-hvps", label)

    @_needs_arm_ena
    def test_the_fix_case_sizes_identically_to_arm_ena_2ds(self):
        from arrayprobe_uiops import register_arm_ena_2ds as _arm_ena_2ds

        self.assertEqual(_bin_edges(run_flight._s4_probe_case()),
                         _bin_edges(_arm_ena_2ds.register_arm_ena_2ds().name))

    # (b) the opt-out, both routes
    def _assert_stock(self):
        self.assertFalse(run_flight.bin_table_fix_on())
        self.assertIsNone(run_flight._s4_probe_case())
        edges = _bin_edges(None)
        self.assertEqual(len(edges) - 1, 28)
        self.assertEqual(edges[0], 0.2)
        self.assertEqual(run_flight.resolve_protective(), ())
        self.assertIn(" bins=v35-otherwise-hvps", run_flight.sd_call_label(None))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            if run_flight._v35_otherwise_hvps_bins_on_2ds() and not run_flight.bin_table_fix_on():
                run_flight.log(run_flight.V11_BINS_WARNING)
        self.assertIn("WARNING (upstream bin-table defect)", buf.getvalue())

    def test_protective_off_keeps_the_28_stock_bins_with_warning_and_stamp(self):
        run_flight.PROTECTIVE_MODE = "off"
        self._assert_stock()

    def test_config_declared_off_keeps_the_28_stock_bins(self):
        run_flight.ENHANCEMENTS_DECLARED_OFF = (run_flight.BIN_TABLE_FIX,)
        self._assert_stock()

    # (c) a named 2D-S case
    @_needs_arm_ena
    def test_arm_ena_2ds_case_is_unchanged(self):
        from arrayprobe_uiops import register_arm_ena_2ds as _arm_ena_2ds

        _arm_ena_2ds.register_arm_ena_2ds()
        run_flight.PROBE_CASE = "arm-ena-2ds"
        self.assertFalse(run_flight.bin_table_fix_on())
        self.assertEqual(run_flight._s4_probe_case(), "arm-ena-2ds")
        self.assertEqual(run_flight.resolve_protective(), ())
        label = run_flight.sd_call_label(None)
        self.assertIn(" probe_case=arm-ena-2ds", label)
        self.assertNotIn("bins=", label)

    # (d) HVPS
    def test_hvps_is_unchanged(self):
        run_flight.PROBE = "HVPS"
        self.assertFalse(run_flight.bin_table_fix_on())
        self.assertIsNone(run_flight._s4_probe_case())
        self.assertEqual(run_flight.resolve_protective(), ())
        self.assertNotIn("bins=", run_flight.sd_call_label(None))

    # (e) engine 3.1.4
    def test_engine_314_stamp_and_bins_do_not_depend_on_the_protective_mode(self):
        run_flight.ENGINE = "3.1.4"
        labels = {}
        for mode in ("auto", "on", "off"):
            run_flight.PROTECTIVE_MODE = mode
            self.assertFalse(run_flight.bin_table_fix_on())
            self.assertIsNone(run_flight._s4_probe_case())
            self.assertEqual(run_flight.resolve_protective(), ())
            labels[mode] = run_flight.sd_call_label(None)
        self.assertEqual(len(set(labels.values())), 1, labels)
        self.assertNotIn("bins=", labels["auto"])
        self.assertNotIn("V11", labels["auto"])


if __name__ == "__main__":
    unittest.main()
