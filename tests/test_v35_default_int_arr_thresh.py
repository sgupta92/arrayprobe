# SPDX-License-Identifier: BSD-3-Clause
"""The opt-in ``default_int_arr_thresh`` keyword of ``arrayprobe_uiops.sizedist.run``.

It replaces the case's ``defaultIntArrThresh = <literal>`` constant (v3.5 ``sizeDist.m:139-642``;
SOCRATES/2DS is ``:313``), which v3.5 reads only through ``intar_threshold =
ones(size(tas_time))*defaultIntArrThresh`` (``:318``) inside the ``iaThreshType == 2 &&
applyIntArrThresh`` block (``:1308-1338``). Default bit-identical, the gate acts, the attribute is
written only when set, bad values refused.


Inputs are the synthetic proc fixture ``tests/data/v35_sizedist_synthetic.proc.nc`` and the
aircraft state recorded in ``tests/data/v35_default_int_arr_thresh/cases.json``, run as
SOCRATES/2DS: the one 2D-S case that sets
``applyIntArrThresh = 1`` *and* assigns ``intar_threshold``, so the gate is on.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_uiops import sizedist as v35s
from arrayprobe_uiops.sizedist_tables import probe_defaults

DATA = Path(__file__).resolve().parent / "data"
CASES = DATA / "v35_default_int_arr_thresh" / "cases.json"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/10/01 00:00:00"
ATTR = "arrayprobe_default_int_arr_thresh"
S_COLUMN = v35s.REJECT_CRITERION_CODES.index("S")


class _Base(unittest.TestCase):
    project = "SOCRATES"
    probe = "2DS"

    def setUp(self):
        if not CASES.is_file():
            self.skipTest("run scripts/validation/octave/run_v35_default_int_arr_thresh_bank.py "
                          "to write the inputs record this test reads")
        case = json.loads(CASES.read_text(encoding="utf-8"))["_inputs"]
        self.infile = DATA.parent.parent / case["input"]
        self.times = np.asarray(case["times"], dtype=float)
        self.tas = np.asarray(case["tas"], dtype=float)
        self.pres = np.full(self.times.size, case["pres"])
        self.temp = np.full(self.times.size, case["temp"])
        self.ddate = case["ddate"]
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._n = 0

    def run_sd(self, ia_thresh_type=2, **kw):
        """Run the port; returns (returned dict, {variable: array}, global attributes)."""
        self._n += 1
        got = Path(self._tmp.name) / f"sd{self._n}.nc"
        out = v35s.run(str(self.infile), str(got), self.tas, self.times, self.probe, 6, 0,
                       self.pres, self.temp, ia_thresh_type, 0, 1, 1, self.project, self.ddate,
                       software=SOFTWARE, creation_time=CREATION_TIME, **kw)
        with netCDF4.Dataset(got) as d:
            variables = {k: np.asarray(v[:]) for k, v in d.variables.items()}
            attrs = {a: d.getncattr(a) for a in d.ncattrs()}
        return out, variables, attrs

    def assert_same_variables(self, a, b, msg=""):
        self.assertEqual(set(a), set(b), msg)
        for k in sorted(a):
            va = np.ma.filled(a[k].astype(float), np.nan)
            vb = np.ma.filled(b[k].astype(float), np.nan)
            self.assertTrue(np.array_equal(va, vb, equal_nan=True), f"{msg} {k}")

    def shattered(self, out):
        return float(np.nansum(out["_reject_by_criterion"][:, S_COLUMN]))


class TestTheFixtureReachesTheGate(_Base):
    def test_socrates_2ds_has_the_gate_on_and_assigns_intar_threshold(self):
        cfg = probe_defaults(self.project, self.probe, version="3.5")
        self.assertEqual(cfg.applyIntArrThresh, 1)
        self.assertTrue(cfg.intar_threshold_defaulted)
        self.assertEqual(cfg.defaultIntArrThresh, 1e-6)


class TestDefaultIsBitIdentical(_Base):
    def test_unset_equals_none(self):
        o0, v0, a0 = self.run_sd()
        o1, v1, a1 = self.run_sd(default_int_arr_thresh=None)
        self.assert_same_variables(v0, v1, "unset vs None")
        self.assertEqual(a0, a1)
        self.assertNotIn(ATTR, a0)
        self.assertTrue(np.array_equal(o0["_reject_by_criterion"], o1["_reject_by_criterion"],
                                       equal_nan=True))

    def test_the_case_constant_given_explicitly_changes_only_the_attribute(self):
        _, v0, a0 = self.run_sd()
        _, v1, a1 = self.run_sd(default_int_arr_thresh=1e-6)
        self.assert_same_variables(v0, v1, "unset vs the case's own 1e-6")
        self.assertEqual({k: v for k, v in a1.items() if k != ATTR}, a0)
        self.assertEqual(a1[ATTR], 1e-6)


class TestTheGateActs(_Base):
    def test_a_larger_threshold_flags_more_particles_as_shattered(self):
        o_stock, v_stock, _ = self.run_sd()
        o_high, v_high, attrs = self.run_sd(default_int_arr_thresh=1e-3)
        self.assertGreater(self.shattered(o_high), self.shattered(o_stock))
        self.assertEqual(attrs[ATTR], 1e-3)
        self.assertFalse(all(
            np.array_equal(np.ma.filled(v_stock[k].astype(float), np.nan),
                           np.ma.filled(v_high[k].astype(float), np.nan), equal_nan=True)
            for k in v_stock), "a changed threshold must change a written variable")

    def test_unused_when_ia_thresh_type_is_not_2_but_still_stamped(self):
        _, v0, a0 = self.run_sd(ia_thresh_type=0)
        _, v1, a1 = self.run_sd(ia_thresh_type=0, default_int_arr_thresh=1e-3)
        self.assert_same_variables(v0, v1, "iaThreshType 0 never reads intar_threshold")
        self.assertEqual({k: v for k, v in a1.items() if k != ATTR}, a0)
        self.assertEqual(a1[ATTR], 1e-3)


class TestACaseMatlabDiesOnStaysRefused(_Base):
    project = "GPM"  # GPM/2DS: applyIntArrThresh = 1, intar_threshold never assigned

    def test_a_value_does_not_invent_intar_threshold(self):
        with self.assertRaises(NotImplementedError) as cm:
            self.run_sd(default_int_arr_thresh=1e-3)
        self.assertIn("'intar_threshold' undefined", str(cm.exception))


class TestValidation(_Base):
    def test_negative_non_finite_and_non_numeric_values_raise(self):
        for bad in (-1e-6, float("nan"), float("inf"), True, "1e-6"):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as cm:
                self.run_sd(default_int_arr_thresh=bad)
            self.assertIn("defaultIntArrThresh", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
