# SPDX-License-Identifier: BSD-3-Clause
"""Engine 3.5 writes the airspeed data-quality record into the sd file by default.

The record (:func:`arrayprobe.tools.tas_sources.qc_record`) names the seconds sized with a
substituted or default TAS. Engine 3.5 already writes ``arrayprobe_engine`` and
``arrayprobe_profile`` unconditionally, so the record joins them as ``arrayprobe_tas_*`` global
attributes whenever the run named a TAS source; v3.1.4 keeps it opt-in
(``test_sizedist_provenance_attribute.py``) so archived reproductions stay byte-faithful.

Both states are held here:

* engine: ``tas_qc=None`` writes no ``arrayprobe_tas_*`` attribute, and a record changes no
  variable -- only attributes are added;
* driver: a chain run's sd file carries the same record as its ``.tasqc.json`` sidecar; a run
  that named no TAS source carries none.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.tools import tas_sources
from arrayprobe.tools.make_tas_file import TasPolicy
from arrayprobe_uiops import sizedist as v35s

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data"
BASE = DATA / "v35_div_synthetic_base_proc.nc"   # synthetic: particles in 16:41:29 and 16:41:30
STEM = "base151205164128"

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
run_flight = None


def setUpModule():
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)


def _tas_attrs(path: Path) -> dict:
    with netCDF4.Dataset(path) as d:
        return {k: d.getncattr(k) for k in d.ncattrs() if k.startswith("arrayprobe_tas_")}


def _chain(seconds) -> tas_sources.ChainResult:
    t = np.asarray(seconds, dtype=float)
    return tas_sources.ChainResult(
        mode="aircraft", tier="aircraft", source="arm-aaf-merged", path="aircraft.nc",
        time=t, tas=np.full(t.size, 95.0), policy=TasPolicy(), steps=[], substituted=[],
        lines=[], provenance={})


class EngineWritesTheRecordOnlyWhenGiven(unittest.TestCase):

    def _run(self, tas_qc):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "sd.nc"
        grid = np.array([164128.0, 164129.0, 164130.0])
        v35s.run(str(BASE), str(out), np.full(3, 95.0), grid, "2DS", 6, 0,
                 np.full(3, 9e5), np.full(3, 15.0), 0, 0, 1, 1, "TEST", "20151205 164129",
                 software="test", octave_colon=True, creation_time="x", tas_qc=tas_qc)
        return out

    def test_none_writes_no_tas_attribute(self):
        self.assertEqual(_tas_attrs(self._run(None)), {})

    def test_a_record_adds_attributes_and_changes_no_variable(self):
        rec = tas_sources.qc_record(_chain([164128, 164129]), TasPolicy(),
                                    [164128.0, 164129.0, 164130.0], [164130])
        plain, stamped = self._run(None), self._run(rec)
        got = _tas_attrs(stamped)
        self.assertEqual(set(got), {f"arrayprobe_{k}" for k in rec})
        for key, value in rec.items():
            self.assertEqual(np.asarray(got[f"arrayprobe_{key}"]).tolist(),
                             np.asarray(value).tolist(), key)
        with netCDF4.Dataset(plain) as a, netCDF4.Dataset(stamped) as b:
            a.set_auto_mask(False)
            b.set_auto_mask(False)
            self.assertEqual(list(a.variables), list(b.variables))
            for name in a.variables:
                np.testing.assert_array_equal(a.variables[name][:], b.variables[name][:], name)
            extra = set(b.ncattrs()) - set(a.ncattrs())
            self.assertEqual(extra, set(got))


class DriverStage4UnderEngine35(unittest.TestCase):
    GLOBALS = ("TAS_SOURCE", "TAS_SEARCH", "TAS_CHAIN", "TAS_FILE", "TAS_POLICY", "TAS_GRID",
               "PROFILE", "ENGINE")

    def setUp(self):
        snap = {name: getattr(run_flight, name) for name in self.GLOBALS}
        self.addCleanup(lambda: [setattr(run_flight, k, v) for k, v in snap.items()])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        self.proc = self.out / f"proc.{STEM}.H.nc"
        self.proc.write_bytes(BASE.read_bytes())
        (self.out / f"{STEM}.tas.csv").write_text(
            "164128.500000, 95.0\n164129.500000, 95.0\n164130.500000, 95.0\n")
        from arrayprobe.profiles import PROFILES
        run_flight.ENGINE = "3.5"
        run_flight.PROFILE = PROFILES["stock-v3.5"]
        run_flight.TAS_GRID = "probe"
        run_flight.TAS_FILE = None

    def _stage4(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            target = run_flight.stage4(self.proc, STEM, self.out, None, accept_unstamped=True)
        self.assertTrue(target.exists(), buf.getvalue())
        return target

    def test_a_chain_run_carries_its_sidecar_record_in_file(self):
        chain = _chain([164128, 164129])     # 16:41:30 absent: sized with the default
        run_flight.TAS_CHAIN = chain
        run_flight.TAS_POLICY = chain.policy
        target = self._stage4()
        sidecar = json.loads(tas_sources.qc_sidecar_path(target).read_text())
        got = _tas_attrs(target)
        self.assertEqual(set(got), {f"arrayprobe_{k}" for k in sidecar})
        for key, value in sidecar.items():
            self.assertEqual(np.asarray(got[f"arrayprobe_{key}"]).tolist(),
                             np.asarray(value).tolist(), key)
        self.assertEqual(sidecar["tas_chain_used"], "aircraft:arm-aaf-merged")

    def test_a_run_naming_no_tas_source_carries_none(self):
        run_flight.TAS_CHAIN = None
        target = self._stage4()
        self.assertEqual(_tas_attrs(target), {})
        self.assertFalse(tas_sources.qc_sidecar_path(target).exists())

if __name__ == "__main__":
    unittest.main()
