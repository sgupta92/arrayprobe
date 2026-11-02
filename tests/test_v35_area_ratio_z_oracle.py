# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.sizedist.run(..., area_ratio_z=v)`` against Octave running the vendored v3.5
``sizeDist.m`` with the one literal at ``:1162`` changed through a shadowing copy
(``octave_oracle/run_v35_area_ratio_z_bank.py``; goldens in ``tests/data/v35_area_ratio_z/``).

Same input, tolerance and comparison as ``test_v35_sizedist_probetype1_whole_file.py``
(``rtol = atol = 1e-9``, NaN equal). The bank's ``zninf`` case (``-Inf``) maps to the port's
``0.0``, since the port refuses ``-inf`` by design. Layer 2 for the override; stock v3.5 is
unchanged (``TestDefaultIsBitIdentical`` in ``test_v35_area_ratio_z.py``).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe_uiops import sizedist as v35s

DATA = Path(__file__).resolve().parent / "data"
DIR = DATA / "v35_area_ratio_z"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/30 00:00:00"


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


class TestAreaRatioZAgainstOctave(unittest.TestCase):
    def setUp(self):
        if not (DIR / "cases.json").is_file():
            self.skipTest("The reference output of v35_area_ratio_z is not distributed with the "
                          "package")
        if not (DIR / "z0.sd.nc").is_file():
            self.skipTest("the v35_area_ratio_z goldens are real-data fixtures, not distributed")
        self.cases = json.loads((DIR / "cases.json").read_text(encoding="utf-8"))
        inp = self.cases["_inputs"]
        self.infile = DATA.parent.parent / inp["input"]
        self.times = np.asarray(inp["times"], dtype=float)
        self.tas = np.asarray(inp["tas"], dtype=float)
        self.pres = np.full(self.times.size, inp["pres"])
        self.temp = np.full(self.times.size, inp["temp"])
        self.ddate = inp["ddate"]
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _check(self, tag: str):
        c = self.cases[tag]
        self.assertEqual(c["status"], "OK")
        got = Path(self._tmp.name) / f"{tag}.nc"
        v35s.run(str(self.infile), str(got), self.tas, self.times, c["probe"], 6, 0,
                 self.pres, self.temp, c["ia_thresh_type"], 0, 1, 1, c["project"], self.ddate,
                 software=SOFTWARE, creation_time=CREATION_TIME,
                 area_ratio_z=c["port_area_ratio_z"])
        bad = []
        with netCDF4.Dataset(DIR / f"{tag}.sd.nc") as a, netCDF4.Dataset(got) as b:
            self.assertEqual(set(a.variables), set(b.variables), f"{tag}: variable set differs")
            for var in sorted(a.variables):
                va, vb = np.asarray(a.variables[var][:]), np.asarray(b.variables[var][:])
                if va.shape != vb.shape:
                    bad.append(f"{var}: shape {va.shape} vs {vb.shape}")
                    continue
                with np.errstate(invalid="ignore"):
                    if not np.allclose(va, vb, rtol=1e-9, atol=1e-9, equal_nan=True):
                        bad.append(var)
        self.assertEqual(bad, [], f"{tag}: variables differ from Octave")

    def test_stock_value_through_the_copy(self):
        self._check("z02")

    def test_point_five(self):
        self._check("z05")

    def test_zero_is_off(self):
        self._check("z0")

    def test_minus_infinity_is_the_ports_zero(self):
        self.assertEqual(self.cases["zninf"]["matlab_literal"], "-Inf")
        self.assertEqual(self.cases["zninf"]["port_area_ratio_z"], 0.0)
        self._check("zninf")

    def test_the_bank_proved_its_own_preconditions(self):
        chk = self.cases["_checks"]
        self.assertTrue(chk["z02_equals_unmodified_tree_golden"])
        self.assertTrue(chk["z0_equals_zninf"])
        self.assertTrue(chk["z05_differs_from_z02_in"])

    @repo_only
    def test_the_vendored_tree_still_holds_the_one_literal(self):
        inp = self.cases["_inputs"]
        src = (_upstream.source("uiops35")
               / "sizeDist.m")
        if not src.is_file():
            self.skipTest("Vendored v3.5 tree is not distributed with the package")
        lines = src.read_text(encoding="utf-8").splitlines()
        self.assertIn(inp["anchor"], lines[inp["anchor_line"] - 1])


if __name__ == "__main__":
    unittest.main()
