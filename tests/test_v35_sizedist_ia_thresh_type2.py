# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``sizeDist``, ``iaThreshType = 2``, on probe cases that never assign ``intar_threshold``.

``GPM``/``2DS`` and ``IMPACTS``/``2DS`` set ``applyIntArrThresh = 1`` but never run
``intar_threshold = ones(size(tas_time))*defaultIntArrThresh``. Under Octave the unmodified v3.5
``sizeDist.m`` dies at ``:1320`` with ``'intar_threshold' undefined`` on both
(``octave_oracle/run_v35_ia_thresh_type2_bank.py``), so the port refuses at the same read site
rather than applying ``defaultIntArrThresh``. ``GPM``/``CIP`` sets ``applyIntArrThresh = 0``, so
MATLAB completes, and the port is pinned to its product.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_uiops import sizedist as v35s
from arrayprobe_uiops.sizedist_tables import (
    BinLadder,
    InterarrivalThresholdSpec,
    ProbeDefaults,
    probe_defaults,
)

DATA = Path(__file__).resolve().parent / "data"
DIR = DATA / "v35_ia_thresh_type2"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/28 07:00:00"


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: v35_ia_thresh_type2/gpm_cip.sd.nc is excluded from the release; only
# the Octave-golden class needs it, TestReadSite builds its inputs in memory.
_REAL_INPUT = (
    _P(__file__).resolve().parent / "data" / "v35_ia_thresh_type2/gpm_cip.sd.nc"
).exists()


def _load_cases() -> dict:
    return json.loads((DIR / "cases.json").read_text(encoding="utf-8"))


def _run(case: dict, outfile: Path) -> None:
    n = len(case["times"])
    v35s.run(str(DATA.parent.parent / case["input"]), str(outfile),
             np.asarray(case["tas"], dtype=float), np.asarray(case["times"], dtype=float),
             case["probe"], 6, 0, np.full(n, case["pres"]), np.full(n, case["temp"]),
             case["ia_thresh_type"], 0, 1, 1, case["project"], case["ddate"],
             software=SOFTWARE, creation_time=CREATION_TIME)


class TestWholeRunAgainstOctave(unittest.TestCase):
    def setUp(self):
        if not _REAL_INPUT:
            self.skipTest("v35_ia_thresh_type2/gpm_cip.sd.nc is real-data derived, "
                          "not shipped in the release")
        if not (DIR / "cases.json").is_file():
            self.skipTest("run octave_oracle/run_v35_ia_thresh_type2_bank.py")
        self.cases = _load_cases()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _check_dies(self, name: str):
        case = self.cases[name]
        self.assertEqual(case["status"], "ERROR")
        self.assertIn("'intar_threshold' undefined", case["message"])
        with self.assertRaises(NotImplementedError) as ctx:
            _run(case, Path(self._tmp.name) / f"{name}.nc")
        msg = str(ctx.exception)
        self.assertIn(f"sizeDist.m:{case['line']} ", msg)
        self.assertIn("'intar_threshold' undefined", msg)

    def test_gpm_2ds_dies_where_matlab_dies(self):
        self._check_dies("gpm_2ds")

    def test_impacts_2ds_dies_where_matlab_dies(self):
        self._check_dies("impacts_2ds")

    def test_gpm_cip_completes_and_matches_octave(self):
        case = self.cases["gpm_cip"]
        self.assertEqual(case["status"], "OK")
        got = Path(self._tmp.name) / "gpm_cip.nc"
        _run(case, got)
        bad = []
        with netCDF4.Dataset(DIR / case["golden"]) as a, netCDF4.Dataset(got) as b:
            self.assertEqual(set(a.variables), set(b.variables))
            for var in sorted(a.variables):
                va, vb = np.asarray(a.variables[var][:]), np.asarray(b.variables[var][:])
                if va.shape != vb.shape:
                    bad.append(f"{var}: shape {va.shape} vs {vb.shape}")
                    continue
                with np.errstate(invalid="ignore"):
                    if not np.allclose(va, vb, rtol=1e-9, atol=1e-9, equal_nan=True):
                        bad.append(var)
        self.assertEqual(bad, [])


class TestReadSite(unittest.TestCase):
    """The block reads ``intar_threshold(i)`` first at ``:1312`` when ``int_arr2`` is non-empty,
    else at ``:1317`` when the second holds one particle, else at ``:1320``."""

    def _cfg(self, *, defaulted: bool, apply: int = 1, reaccpt: int = 1) -> ProbeDefaults:
        return ProbeDefaults(
            num_diodes=128, diodesize=0.010, armdst=63.0, num_bins=22, bins=BinLadder(),
            probetype=2, tasMax=170.0, applyIntArrThresh=apply, defaultIntArrThresh=1e-6,
            reaccptShatrs=reaccpt, reaccptD=0.5, reaccptMaxIA=1e-6,
            intar_threshold_defaulted=defaulted)

    def _shatter(self, cfg, int_arr, int_arr2):
        n = len(int_arr)
        return v35s.apply_shattering(
            ia_thresh_type=2, cfg=cfg, spec=InterarrivalThresholdSpec(None, None, False), i=0,
            auto_reject=np.full(n, ord("0"), dtype=np.int8),
            int_arr=np.asarray(int_arr, dtype=float),
            int_arr2=None if int_arr2 is None else np.asarray(int_arr2, dtype=float),
            int_arr3=np.asarray(int_arr, dtype=float), particle_diameter_minR=np.ones(n),
            start=0, count=n)

    def _line(self, int_arr, int_arr2) -> str:
        with self.assertRaises(NotImplementedError) as ctx:
            self._shatter(self._cfg(defaulted=False), int_arr, int_arr2)
        return str(ctx.exception)

    def test_int_arr2_non_empty_reads_at_1312(self):
        self.assertIn("sizeDist.m:1312 ", self._line([1e-3, 1e-3], [1e-3]))

    def test_one_particle_reads_at_1317(self):
        self.assertIn("sizeDist.m:1317 ", self._line([1e-3], []))
        self.assertIn("sizeDist.m:1317 ", self._line([1e-3], None))

    def test_several_particles_read_at_1320(self):
        self.assertIn("sizeDist.m:1320 ", self._line([1e-3, 1e-3], []))

    def test_an_assigned_threshold_is_applied(self):
        out = self._shatter(self._cfg(defaulted=True, reaccpt=0), [1e-3, 1e-7], [])
        self.assertEqual(out.tolist(), [ord("S"), ord("S")])

    def test_gate_off_reads_nothing(self):
        out = self._shatter(self._cfg(defaulted=False, apply=0), [1e-3, 1e-7], [1e-7])
        self.assertEqual(out.tolist(), [ord("0"), ord("0")])

    def test_the_shipped_tables_name_the_affected_cases(self):
        for project, probe in (("GPM", "2DS"), ("IMPACTS", "2DS")):
            cfg = probe_defaults(project, probe)
            self.assertTrue(cfg.applyIntArrThresh)
            self.assertFalse(cfg.intar_threshold_defaulted)


if __name__ == "__main__":
    unittest.main()
