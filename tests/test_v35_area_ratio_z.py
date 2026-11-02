# SPDX-License-Identifier: BSD-3-Clause
"""The opt-in ``area_ratio_z`` keyword of ``arrayprobe_uiops.sizedist.run`` (the ``.2`` at
v3.5 ``sizeDist.m:1162``): default bit-identical, the gate acts, ``0`` is off, bad values refused.

Inputs are the tracked probetype-1 fixture and its bank's aircraft state
(``tests/data/v35_area_ratio_z/cases.json``). The oracle half is
``tests/test_v35_area_ratio_z_oracle.py``.

"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

from arrayprobe_uiops import sizedist as v35s

DATA = Path(__file__).resolve().parent / "data"
CASES = DATA / "v35_area_ratio_z" / "cases.json"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/30 00:00:00"
Z_COLUMN = v35s.REJECT_CRITERION_CODES.index("z")


class _Base(unittest.TestCase):
    def setUp(self):
        if not CASES.is_file():
            self.skipTest("The reference output of v35_area_ratio_z is not distributed with the "
                          "package")
        self.cases = json.loads(CASES.read_text(encoding="utf-8"))
        inp = self.cases["_inputs"]
        self.infile = DATA.parent.parent / inp["input"]
        if not self.infile.is_file():
            self.skipTest("the input is a real-data fixture that is not distributed")
        self.times = np.asarray(inp["times"], dtype=float)
        self.tas = np.asarray(inp["tas"], dtype=float)
        self.pres = np.full(self.times.size, inp["pres"])
        self.temp = np.full(self.times.size, inp["temp"])
        self.ddate = inp["ddate"]
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._n = 0

    def run_sd(self, **kw):
        """Run the port; returns (returned dict, {variable: array}, global attributes)."""
        self._n += 1
        got = Path(self._tmp.name) / f"sd{self._n}.nc"
        out = v35s.run(str(self.infile), str(got), self.tas, self.times, "CIP", 6, 0,
                       self.pres, self.temp, 0, 0, 1, 1, "TEST", self.ddate,
                       software=SOFTWARE, creation_time=CREATION_TIME, **kw)
        with netCDF4.Dataset(got) as d:
            variables = {k: np.asarray(v[:]) for k, v in d.variables.items()}
            attrs = {a: d.getncattr(a) for a in d.ncattrs()}
        return out, variables, attrs

    def assert_same_variables(self, a, b, msg=""):
        self.assertEqual(set(a), set(b), msg)
        for k in sorted(a):
            va, vb = np.ma.filled(a[k].astype(float), np.nan), np.ma.filled(b[k].astype(float),
                                                                            np.nan)
            self.assertTrue(np.array_equal(va, vb, equal_nan=True), f"{msg} {k}")


class TestDefaultIsBitIdentical(_Base):
    def test_unset_equals_none_and_the_explicit_stock_value(self):
        _, v0, a0 = self.run_sd()
        _, v_none, a_none = self.run_sd(area_ratio_z=None)
        _, v_stock, a_stock = self.run_sd(area_ratio_z=0.2)
        self.assert_same_variables(v0, v_none, "unset vs None")
        self.assertEqual(a0, a_none)
        self.assert_same_variables(v0, v_stock, "unset vs explicit 0.2")
        self.assertNotIn("arrayprobe_area_ratio_z", a0)
        self.assertEqual({k: v for k, v in a_stock.items() if k != "arrayprobe_area_ratio_z"}, a0)
        self.assertEqual(a_stock["arrayprobe_area_ratio_z"], 0.2)

    def test_the_returned_reject_table_is_identical_too(self):
        o0, _, _ = self.run_sd()
        o1, _, _ = self.run_sd(area_ratio_z=0.2)
        self.assertTrue(np.array_equal(o0["_reject_by_criterion"], o1["_reject_by_criterion"],
                                       equal_nan=True))


class TestTheGateActs(_Base):
    def test_a_higher_threshold_rejects_more_as_z(self):
        o_stock, _, _ = self.run_sd()
        o_high, _, attrs = self.run_sd(area_ratio_z=0.5)
        z_stock = np.nansum(o_stock["_reject_by_criterion"][:, Z_COLUMN])
        z_high = np.nansum(o_high["_reject_by_criterion"][:, Z_COLUMN])
        self.assertGreater(z_high, z_stock)
        self.assertEqual(attrs["arrayprobe_area_ratio_z"], 0.5)
        # The Octave bank found the same fixture moves the gate (U5 of the plan).
        self.assertIn("Reject_ratio", self.cases["_checks"]["z05_differs_from_z02_in"])


class TestOffIsOff(_Base):
    def test_zero_leaves_no_z_and_equals_a_minus_infinity_threshold(self):
        o_off, v_off, _ = self.run_sd(area_ratio_z=0.0)
        self.assertEqual(np.nansum(o_off["_reject_by_criterion"][:, Z_COLUMN]), 0.0)
        with mock.patch.object(v35s, "AREA_RATIO_Z", float("-inf")):
            _, v_ninf, _ = self.run_sd()
        self.assert_same_variables(v_off, v_ninf, "0.0 vs -inf through the private path")


class TestValidation(_Base):
    def test_out_of_range_and_non_finite_values_raise(self):
        for bad in (-0.1, 1.5, float("nan"), float("inf"), float("-inf"), True, "0.5"):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as cm:
                self.run_sd(area_ratio_z=bad)
            self.assertIn("sizeDist.m:1162", str(cm.exception))

    def test_the_bounds_are_admitted(self):
        for value in (0.0, 1):
            with self.subTest(area_ratio_z=value):
                _, variables, _ = self.run_sd(area_ratio_z=value)
                self.assertTrue(variables,
                                "an admitted bound must still write the size distribution")


if __name__ == "__main__":
    unittest.main()
