# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``sizeDist`` on probetype 1 (CIP/PIP), whole file, against Octave.

Every written variable of ``arrayprobe_uiops.sizedist.run`` asserted against the vendored v3.5
``sizeDist.m`` running unmodified under GNU Octave on the same synthetic PIP proc file
(``tests/data/s7a_pip_octave_golden.nc``)
(``octave_oracle/run_v35_probetype1_sizedist_bank.py``). Layer 2; the CIP cases apply CIP geometry
to PIP-decoded particles, so the input is a differential, not a claim about real CIP data.
Tolerance: ``rtol = atol = 1e-9`` with NaN equal, as the probetype-0/3 bank.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_uiops import sizedist as v35s

DATA = Path(__file__).resolve().parent / "data"
DIR = DATA / "v35_probetype1_sizedist"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/24 20:00:00"


class TestProbetype1WholeFileAgainstOctave(unittest.TestCase):
    def setUp(self):
        if not (DIR / "cases.json").is_file():
            self.skipTest("The reference output of v35_probetype1_sizedist is not distributed "
                          "with the package")
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

    def _check(self, name: str):
        c = self.cases[name]
        self.assertEqual(c["status"], "OK", c.get("message"))
        got = Path(self._tmp.name) / f"{name}.nc"
        infile = DATA.parent.parent / c.get("input", self.cases["_inputs"]["input"])
        v35s.run(str(infile), str(got), self.tas, self.times, c["probe"], 6, 0,
                 self.pres, self.temp, c["ia_thresh_type"], 0, 1, 1, c["project"], self.ddate,
                 software=SOFTWARE, creation_time=CREATION_TIME)
        bad = []
        with netCDF4.Dataset(DIR / f"{name}.sd.nc") as a, netCDF4.Dataset(got) as b:
            self.assertEqual(set(a.variables), set(b.variables), f"{name}: variable set differs")
            for var in sorted(a.variables):
                va, vb = np.asarray(a.variables[var][:]), np.asarray(b.variables[var][:])
                if va.shape != vb.shape:
                    bad.append(f"{var}: shape {va.shape} vs {vb.shape}")
                    continue
                with np.errstate(invalid="ignore"):
                    if not np.allclose(va, vb, rtol=1e-9, atol=1e-9, equal_nan=True):
                        bad.append(var)
        self.assertEqual(bad, [], f"{name}: variables differ from Octave")

    def test_gpm_cip(self):
        self._check("gpm_cip")

    def test_socrates_pip(self):
        self._check("socrates_pip")

    def test_test_cip(self):
        self._check("test_cip")

    def test_test_pip(self):
        self._check("test_pip")

    def test_test_pip_ia_thresh_type_1(self):
        self._check("test_pip_ia1")

    # Short inter-arrival twins (every second particle 1e-7 s after its predecessor). Octave
    # writes values equal to the real-input twins' (cases.json `differs_from_twin` is empty):
    # no non-PECAN probetype-1 arm applies the threshold or reacceptance, so these pin that the
    # port, too, writes nothing that depends on `Time_in_seconds` on these arms.
    def test_gpm_cip_short_ia(self):
        self._check("gpm_cip_short_ia")

    def test_socrates_pip_short_ia(self):
        self._check("socrates_pip_short_ia")

    def test_test_cip_short_ia(self):
        self._check("test_cip_short_ia")

    def test_test_pip_short_ia(self):
        self._check("test_pip_short_ia")


if __name__ == "__main__":
    unittest.main()
