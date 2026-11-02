# SPDX-License-Identifier: BSD-3-Clause
"""Regime slice 3:
the driver reads its S3 reject set through ``run_flight._resolve_reject()``.

Three things are pinned here:

* the ``.call`` labels of a no-regime run and of a shipped-regime run (all six reject slots
  INHERIT) are byte-identical to the labels the driver wrote before the slice -- the goldens below
  were rendered from the pre-slice code at commit 089bc06, and the no-regime proc golden is also
  cross-checked against the tracked fixture ``tests/data/demo_flight_v314_proc.call``;
* a registered regime that cites one reject slot changes exactly that value, in the computation's
  profile and in the stamp, and adds the two additive keys ``regime=`` and ``reject_sources=``;
* no read of ``reject_thresholds`` in the driver bypasses the helper (AST sweep).
"""

from __future__ import annotations

import ast
import dataclasses
import types
import unittest
from pathlib import Path

import arrayprobe
from arrayprobe import regimes
from arrayprobe.driver import run_flight as rf

HERE = Path(__file__).resolve().parent
DRIVER = Path(rf.__file__)

# Rendered from the pre-slice driver (commit 089bc06) with ENGINE="3.1.4", PORT_VALIDATION=True,
# PROFILE=oracles-production and the module's default preset globals.
_REJECT = ("reject=(rej_zero_area=True,rej_split=True,rej_hollow=False,shadowed_area=25,"
           "max_edge_img_ar=4,max_comp_img_ar=4)")
_PROC_GOLDEN = (f"engine=3.1.4 port_validation=on profile=oracles-production {_REJECT} "
                "shadow_diode=none")
_SD_PREFIX = ("engine=3.1.4 port_validation=on iat_file=2DS_intArrThreshold_MISSING.cdf "
              f"profile=oracles-production {_REJECT} shadow_diode=none tree=production ")
_SD_GOLDEN = {
    None: _SD_PREFIX + "area_ratio_z=0.5 (default) default_int_arr_thresh=6e-06 (default)",
    "liquid-warm": _SD_PREFIX + ("area_ratio_z=0.5 (regime:liquid-warm) "
                                 "default_int_arr_thresh=6e-06 (regime:liquid-warm)"),
    "ice": _SD_PREFIX + "area_ratio_z=0.2 (regime:ice) default_int_arr_thresh=4e-06 (regime:ice)",
}
_IAT = "2DS_intArrThreshold_MISSING.cdf"
_FORK = "test-slice3-one-reject-slot"


class _DriverStateIsolated(unittest.TestCase):
    def setUp(self):
        for name in ("PROFILE", "ENGINE", "PORT_VALIDATION", "REGIME_NAME",
                     "AREA_RATIO_Z_OVERRIDE", "DEFAULT_IAT_OVERRIDE", "TAS_FILE", "TAS_CHAIN",
                     "TAS_FROM_PROBE", "AUTHORDEFAULTS_STAMP", "LIBM_POW"):
            self.addCleanup(setattr, rf, name, getattr(rf, name))
        rf.ENGINE = "3.1.4"
        rf.PORT_VALIDATION = True
        rf.PROFILE = arrayprobe.profile("oracles-production")
        rf.REGIME_NAME = None
        rf.AREA_RATIO_Z_OVERRIDE = None
        rf.DEFAULT_IAT_OVERRIDE = None
        rf.TAS_FILE = None
        rf.TAS_CHAIN = None
        rf.TAS_FROM_PROBE = False
        rf.AUTHORDEFAULTS_STAMP = None
        rf.LIBM_POW = False


class NoRegimeAndShippedRegimeStampsAreByteIdentical(_DriverStateIsolated):
    def test_no_regime_labels_equal_the_pre_slice_goldens(self):
        self.assertEqual(rf.proc_call_label(), _PROC_GOLDEN)
        self.assertEqual(rf.sd_call_label(_IAT), _SD_GOLDEN[None])

    def test_the_no_regime_proc_golden_matches_the_tracked_fixture(self):
        fixture = (HERE / "data" / "demo_flight_v314_proc.call").read_text(encoding="utf-8")
        # The fixture predates port_validation=on (R4, 2026-09-30); everything else is the same.
        self.assertEqual(rf.proc_call_label().replace("port_validation=on ", ""), fixture.strip())

    def test_every_shipped_regime_writes_the_pre_slice_labels(self):
        for name in sorted(regimes.REGIMES):
            if name not in _SD_GOLDEN:
                continue  # a registered fork from another test module, not a shipped regime
            with self.subTest(regime=name):
                rf.REGIME_NAME = name
                self.assertEqual(rf.proc_call_label(), _PROC_GOLDEN)
                self.assertEqual(rf.sd_call_label(_IAT), _SD_GOLDEN[name])
                self.assertEqual(rf._reject_sources_stamp(), "")

    def test_no_slot_set_passes_the_profile_object_itself(self):
        for name in (None, "liquid-warm", "ice", "mixed"):
            with self.subTest(regime=name):
                rf.REGIME_NAME = name
                self.assertIs(rf._resolve_reject(), rf.PROFILE.reject_thresholds)
                self.assertIs(rf._profile_with_resolved_reject(), rf.PROFILE)


class ARegimeWithOneCitedRejectSlot(_DriverStateIsolated):
    def setUp(self):
        super().setUp()
        fork = dataclasses.replace(
            regimes.REGIMES["ice"], name=_FORK, max_edge_img_ar=6,
            max_edge_img_ar_justification="UIOPS-v3.1.4 calculate_reject_unified.m:76 (test)")
        regimes.register_regime(fork)
        self.addCleanup(regimes._REGIMES.pop, _FORK, None)
        rf.REGIME_NAME = _FORK

    def test_exactly_that_value_changes(self):
        base = rf.PROFILE.reject_thresholds
        got = rf._resolve_reject()
        for f in dataclasses.fields(base):
            with self.subTest(field=f.name):
                want = 6 if f.name == "max_edge_img_ar" else getattr(base, f.name)
                self.assertEqual(getattr(got, f.name), want)

    def test_the_v314_s3_call_gets_the_resolved_reject_set(self):
        p = rf._profile_with_resolved_reject()
        self.assertIsNot(p, rf.PROFILE)
        self.assertEqual(p.reject_thresholds, rf._resolve_reject())
        self.assertEqual(dataclasses.replace(p, reject_thresholds=rf.PROFILE.reject_thresholds),
                         rf.PROFILE)

    def test_the_stamp_gains_the_two_keys_and_the_new_value(self):
        new_reject = _REJECT.replace("max_edge_img_ar=4", "max_edge_img_ar=6")
        keys = f" regime={_FORK} reject_sources=(max_edge_img_ar=regime:{_FORK})"
        self.assertEqual(rf.proc_call_label(),
                         _PROC_GOLDEN.replace(_REJECT, new_reject) + keys)
        sd = rf.sd_call_label(_IAT)
        self.assertEqual(
            sd,
            _SD_GOLDEN["ice"].replace(_REJECT, new_reject)
            .replace("shadow_diode=none", "shadow_diode=none" + keys)
            .replace("(regime:ice)", f"(regime:{_FORK})"))
        self.assertFalse(rf._stamps_equivalent(_PROC_GOLDEN, rf.proc_call_label()))

    def test_the_confirmation_panel_says_where_each_reject_value_came_from(self):
        args = types.SimpleNamespace(preset="ORACLES_2016_2DS_H", stages="23", enhancements=False)
        lines = rf.confirmation_lines(args, rf._resolve_thresholds())
        src = [ln for ln in lines if ln.startswith("  S3 reject sources")]
        self.assertEqual(len(src), 1)
        self.assertIn(f"max_edge_img_ar=regime:{_FORK}", src[0])
        self.assertIn("max_comp_img_ar=profile:oracles-production", src[0])
        rf.REGIME_NAME = "ice"
        lines = rf.confirmation_lines(args, rf._resolve_thresholds())
        self.assertFalse([ln for ln in lines if ln.startswith("  S3 reject sources")])


class EveryRejectReadGoesThroughTheHelper(unittest.TestCase):
    _HELPERS = {"_resolve_reject", "_profile_with_resolved_reject"}

    def setUp(self):
        self.tree = ast.parse(DRIVER.read_text(encoding="utf-8"))

    def test_no_reject_thresholds_read_outside_the_helpers(self):
        bad = []
        for fn in ast.walk(self.tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name in self._HELPERS:
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) and node.attr == "reject_thresholds":
                    bad.append(f"{fn.name}:{node.lineno}")
        # module-level code too (outside any function)
        top = [n for n in ast.walk(self.tree)
               if isinstance(n, ast.Attribute) and n.attr == "reject_thresholds"]
        in_fns = {id(n) for fn in ast.walk(self.tree)
                  if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                  for n in ast.walk(fn)}
        bad += [f"<module>:{n.lineno}" for n in top if id(n) not in in_fns]
        self.assertEqual(bad, [], "read the reject set through _resolve_reject()")

    def test_the_helpers_are_used_at_the_four_design_sites_and_the_v314_s3_call(self):
        def kw_call(callee: str, kw: str) -> list[str]:
            out = []
            for node in ast.walk(self.tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if name != callee:
                    continue
                for k in node.keywords:
                    if k.arg == kw and isinstance(k.value, ast.Call):
                        out.append(getattr(k.value.func, "id", "?"))
            return out
        self.assertEqual(kw_call("imgproc_sm_v35", "reject_config"), ["_resolve_reject"])
        self.assertEqual(kw_call("imgproc_sm", "profile"), ["_profile_with_resolved_reject"])
        calls = [n.func.id for n in ast.walk(self.tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_resolve_reject"]
        # confirmation panel, config_label, S3 v3.5 call, startup print, and the helper's own use.
        self.assertGreaterEqual(len(calls), 5)


if __name__ == "__main__":
    unittest.main()
