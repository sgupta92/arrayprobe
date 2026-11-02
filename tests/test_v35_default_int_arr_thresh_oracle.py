# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.sizedist.run(..., default_int_arr_thresh=v)`` against Octave running the
vendored v3.5 ``sizeDist.m`` with ``SOCRATES``/``2DS``'s ``defaultIntArrThresh`` literal (``:313``)
changed through a shadowing copy
(``scripts/validation/octave/run_v35_default_int_arr_thresh_bank.py``;
goldens in ``tests/data/v35_default_int_arr_thresh/``).

``iaThreshType`` 2, so the shattering block (``:1308-1338``) reads ``intar_threshold`` (``:318``).
Same tolerance and comparison as ``test_v35_area_ratio_z_oracle.py`` (``rtol = atol = 1e-9``, NaN
equal). The ``stock`` case is the unmodified tree, run by the port without the keyword. Layer 2
for the override; the default is bit-identical (``TestDefaultIsBitIdentical`` in
``test_v35_default_int_arr_thresh.py``).
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
DIR = DATA / "v35_default_int_arr_thresh"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/10/01 00:00:00"


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


class TestDefaultIntArrThreshAgainstOctave(unittest.TestCase):
    def setUp(self):
        if not (DIR / "cases.json").is_file():
            self.skipTest("run scripts/validation/octave/run_v35_default_int_arr_thresh_bank.py")
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

    def _run(self, tag: str, value) -> Path:
        c = self.cases[tag]
        got = Path(self._tmp.name) / f"{tag}_{value}.nc"
        kw = {} if value is None else {"default_int_arr_thresh": value}
        v35s.run(str(self.infile), str(got), self.tas, self.times, c["probe"], 6, 0,
                 self.pres, self.temp, c["ia_thresh_type"], 0, 1, 1, c["project"], self.ddate,
                 software=SOFTWARE, creation_time=CREATION_TIME, **kw)
        return got

    @staticmethod
    def _differing(a_path: Path, b_path: Path, exact: bool) -> list[str]:
        bad = []
        with netCDF4.Dataset(a_path) as a, netCDF4.Dataset(b_path) as b:
            if set(a.variables) != set(b.variables):
                return ["<variable set>"]
            for var in sorted(a.variables):
                va = np.ma.filled(np.asarray(a.variables[var][:]).astype(float), np.nan)
                vb = np.ma.filled(np.asarray(b.variables[var][:]).astype(float), np.nan)
                if va.shape != vb.shape:
                    bad.append(f"{var}: shape {va.shape} vs {vb.shape}")
                    continue
                with np.errstate(invalid="ignore"):
                    same = (np.array_equal(va, vb, equal_nan=True) if exact else
                            np.allclose(va, vb, rtol=1e-9, atol=1e-9, equal_nan=True))
                if not same:
                    bad.append(var)
        return bad

    def _check(self, tag: str):
        c = self.cases[tag]
        self.assertEqual(c["status"], "OK")
        got = self._run(tag, c["port_default_int_arr_thresh"])
        self.assertEqual(self._differing(DIR / f"{tag}.sd.nc", got, exact=False), [],
                         f"{tag}: variables differ from Octave")

    def test_unmodified_tree_without_the_keyword(self):
        self.assertIsNone(self.cases["stock"]["matlab_literal"])
        self.assertIsNone(self.cases["stock"]["port_default_int_arr_thresh"])
        self._check("stock")

    def test_stock_value_through_the_copy(self):
        self._check("t1em6")

    def test_one_e_minus_five(self):
        self._check("t1em5")

    def test_one_e_minus_three(self):
        self._check("t1em3")

    def test_the_stock_value_equals_the_run_without_the_keyword(self):
        bare = self._run("stock", None)
        given = self._run("t1em6", 1e-6)
        self.assertEqual(self._differing(bare, given, exact=True), [])

    def test_the_bank_proved_its_own_preconditions(self):
        chk = self.cases["_checks"]
        self.assertTrue(chk["t1em6_equals_unmodified_tree"])
        self.assertTrue(chk["t1em3_differs_from_stock_in"])

    @repo_only
    def test_the_vendored_tree_still_holds_the_cited_lines(self):
        inp = self.cases["_inputs"]
        src = (_upstream.source("uiops35")
               / "sizeDist.m")
        if not src.is_file():
            self.skipTest("Vendored v3.5 tree is not distributed with the package")
        lines = src.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[inp["anchor_line"] - 1].strip(), inp["anchor"])
        self.assertEqual(lines[inp["apply_line"] - 1].strip(), inp["apply_text"])
        self.assertEqual(lines[inp["assign_line"] - 1].strip(), inp["assign_text"])


if __name__ == "__main__":
    unittest.main()
