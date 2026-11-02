# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``sizeDist`` on probetypes 0 (2DC) and 3 (Fast2DC), against Octave.

The four branches that separate these probes from probetypes 1 and 2 -- ``parent_rec_num`` and
record-start dead time (``:945-947``, ``:1111-1113``), the SEA-convention overload zeroing
(``:964-966``), no ``Particle_number_all`` read (``:969-973``), probetype 0's absolute
``int_arr`` with its ``2^24`` rollback (``:984-985``, ``:1027-1028``) -- asserted variable for
variable against the vendored v3.5 ``sizeDist.m`` running unmodified under GNU Octave on the
same synthetic inputs (``octave_oracle/run_v35_probetype03_sizedist_bank.py``). Layer 2 only,
and synthetic: the held real files (a 1995 ACE-1 2DC/2DP RAF file, reader checked only; a
CAESAR 2024 Fast-2DC file) have not been run through this stage in a validated way.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from tests._repo import repo_only

from arrayprobe_uiops import sizedist as v35s

DIR = Path(__file__).resolve().parent / "data" / "v35_probetype03_sizedist"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/23 20:00:00"


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: v35_probetype03_sizedist/f2dc_socrates.sd.nc is excluded from the release;
# only test_f2dc_socrates needs it, the other inputs here are synthetic.
_SOCRATES = (_P(__file__).resolve().parent / "data"
             / "v35_probetype03_sizedist/f2dc_socrates.sd.nc").exists()


def _cases() -> dict:
    return json.loads((DIR / "cases.json").read_text(encoding="utf-8"))


class TestProbetype03AgainstOctave(unittest.TestCase):
    def setUp(self):
        if not (DIR / "cases.json").is_file():
            self.skipTest("run octave_oracle/run_v35_probetype03_sizedist_bank.py")
        self.cases = _cases()
        inp = self.cases["_inputs"]
        self.times = np.asarray(inp["times"], dtype=float)
        self.tas = np.asarray(inp["tas"], dtype=float)
        self.pres = np.full(self.times.size, inp["pres"])
        self.temp = np.full(self.times.size, inp["temp"])
        self.ddate = inp["ddate"]
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _run(self, name: str) -> Path:
        c = self.cases[name]
        out = Path(self._tmp.name) / f"{name}.nc"
        v35s.run(str(DIR / f"{name}.proc.nc"), str(out), self.tas, self.times, c["probe"], 6, 0,
                 self.pres, self.temp, c["ia_thresh_type"], 0, 1, 1, c["project"], self.ddate,
                 software=SOFTWARE, creation_time=CREATION_TIME)
        return out

    def _compare(self, name: str, got: Path):
        with netCDF4.Dataset(DIR / f"{name}.sd.nc") as a, netCDF4.Dataset(got) as b:
            self.assertEqual(set(a.variables), set(b.variables), f"{name}: variable set differs")
            for var in sorted(a.variables):
                va, vb = np.asarray(a.variables[var][:]), np.asarray(b.variables[var][:])
                self.assertEqual(va.shape, vb.shape, f"{name}:{var} shape differs")
                with np.errstate(invalid="ignore"):
                    ok = np.allclose(va, vb, rtol=1e-9, atol=1e-9, equal_nan=True)
                self.assertTrue(ok, f"{name}:{var} values differ")

    def test_every_case_ran_as_the_bank_recorded(self):
        # The bank's own record: three cases ran, the type-2 case died in MATLAB.
        states = {k: v["status"] for k, v in self.cases.items() if not k.startswith("_")}
        self.assertEqual(states["2dc_main"], "OK")
        self.assertEqual(states["2dc_sea"], "OK")
        self.assertEqual(states["f2dc_socrates"], "OK")
        self.assertEqual(states["f2dc_otherwise"], "OK")

    def test_2dc_main(self):
        self._compare("2dc_main", self._run("2dc_main"))

    def test_2dc_sea_convention_zeroing(self):
        self._compare("2dc_sea", self._run("2dc_sea"))

    def test_f2dc_socrates(self):
        if not _SOCRATES:
            self.skipTest("v35_probetype03_sizedist/f2dc_socrates.sd.nc is real-data derived, "
                          "not shipped in the release")
        self._compare("f2dc_socrates", self._run("f2dc_socrates"))

    def test_f2dc_otherwise(self):
        self._compare("f2dc_otherwise", self._run("f2dc_otherwise"))

    def test_2dc_type2_dies_where_matlab_dies(self):
        c = self.cases["2dc_type2"]
        if c["status"] == "OK":
            self._compare("2dc_type2", self._run("2dc_type2"))
            return
        self.assertIn("int_arr", c["message"])
        with self.assertRaises(NotImplementedError):
            self._run("2dc_type2")


#: GPM/2DC's own defaults with ``reaccptShatrs`` switched on. No stock table row pairs a
#: probetype-0 probe with reacceptance, so the configuration is reachable only as a
#: registered probe case.
_REACCEPT_CASE_NAME = "test-gpm-2dc-reaccept-on"
_V35 = "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"


def _register_reaccept_case():
    import dataclasses

    from arrayprobe_uiops.probe_cases import ProbeCase, register_probe_case
    from arrayprobe_uiops.sizedist_tables import ProbeDefaults, probe_defaults

    stock = probe_defaults("GPM", "2DC", version="3.5")
    cites = {f: f"{_V35}:247-266 (GPM/2DC)" for f in ProbeDefaults.__dataclass_fields__}
    cites["reaccptShatrs"] = f"{_V35}:263, switched from 0 to 1 for this test"
    return register_probe_case(ProbeCase(
        name=_REACCEPT_CASE_NAME,
        description="GPM/2DC with reacceptance on (test only)",
        defaults=dataclasses.replace(stock, reaccptShatrs=1),
        citations=cites,
    ))


@repo_only
class TestProbetype0ReacceptanceDiesOnlyWhereMatlabReadsIntArr3(unittest.TestCase):
    """``int_arr3`` is built only for probetype ~= 0 (``sizeDist.m:1004-1018``), and read only
    inside the three shattering blocks (``:1204``, ``:1337``, ``:1403``), each gated on
    ``iaThreshType`` and ``applyIntArrThresh``. A probetype-0 run with ``reaccptShatrs = 1``
    therefore dies only when one of those blocks runs; otherwise it completes, and
    ``reaccptShatrs`` changes nothing but the ``Shattering Algorithm`` attribute.

    Measured under Octave 11.3 on the vendored v3.5 ``sizeDist.m`` with the single line
    ``:263`` (GPM/2DC ``reaccptShatrs``) switched to 1, on ``2dc_main``'s input: iaThreshType
    0, 1 (no threshold file) and 3 (no threshold array) all complete, every variable equal to
    ``2dc_main.sd.nc`` (the unmodified source's output) and ``Shattering Algorithm`` reading
    ``'Applied w/ reacceptance of particles'``; iaThreshType 3 with a 1-Hz threshold array
    dies with "'int_arr3' undefined near line 1403". The port refused every such run.
    """

    _compare = TestProbetype03AgainstOctave._compare

    def setUp(self):
        TestProbetype03AgainstOctave.setUp(self)
        from arrayprobe_uiops import probe_cases
        _register_reaccept_case()
        # The registry is process-wide; leave it as found for every other test.
        self.addCleanup(probe_cases._REGISTRY.pop, _REACCEPT_CASE_NAME, None)

    def _run_case(self, ia_thresh_type: int, *varargin) -> Path:
        out = Path(self._tmp.name) / f"reaccept_ia{ia_thresh_type}_{len(varargin)}.nc"
        v35s.run(str(DIR / "2dc_main.proc.nc"), str(out), self.tas, self.times, "2DC", 6, 0,
                 self.pres, self.temp, ia_thresh_type, 0, 1, 1, "GPM", self.ddate, *varargin,
                 software=SOFTWARE, creation_time=CREATION_TIME,
                 probe_case=_REACCEPT_CASE_NAME)
        return out

    def _assert_completes_as_matlab_does(self, ia_thresh_type: int):
        got = self._run_case(ia_thresh_type)
        self._compare("2dc_main", got)
        with netCDF4.Dataset(got) as ds:
            self.assertEqual(ds.getncattr("Shattering Algorithm"),
                             "Applied w/ reacceptance of particles")

    def test_no_shattering_block_runs_so_the_run_completes(self):
        self._assert_completes_as_matlab_does(0)

    def test_type1_without_a_threshold_file_completes(self):
        self._assert_completes_as_matlab_does(1)

    def test_type3_without_a_threshold_array_completes(self):
        self._assert_completes_as_matlab_does(3)

    def test_type3_with_a_threshold_array_dies_on_int_arr3(self):
        with self.assertRaises(NotImplementedError) as cm:
            self._run_case(3, 1e-5 * np.ones(self.tas.size))
        self.assertIn("int_arr3", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
