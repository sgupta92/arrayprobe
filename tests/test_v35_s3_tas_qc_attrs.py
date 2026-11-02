# SPDX-License-Identifier: BSD-3-Clause
"""The v3.5 proc file records which image records S3 timed at the fallback airspeed.

``imgProc_sm.m:727`` looks each record's HHMMSS up in the aircraft series by exact equality; a
record with no sample times its particles at 170 m/s (``:730-733``, ``:763``) and says so
nowhere. The driver computes those records once, before S3 (``run_flight._s3_tas_qc_v35``), and
the engine writes them as ``arrayprobe_tas_s3_*`` globals beside the engine attributes.

* engine: ``tas_qc=None`` writes no ``arrayprobe_tas`` attribute, and a record changes no
  variable -- only attributes are added;
* driver: a record second absent from the series is counted and ranged; a run with no
  aircraft series gets no record.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from tests.test_v35_imgproc import _header, _record, _run, _square

ROOT = Path(__file__).resolve().parents[1]
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


def _tas_attrs(got: dict) -> dict:
    return {k: v for k, v in got["attrs"].items() if k.startswith("arrayprobe_tas")}


class EngineWritesTheRecordOnlyWhenGiven(unittest.TestCase):
    RECORDS = staticmethod(lambda: [_record([_square(0, 60, 4)], [1000])])

    def test_none_writes_no_tas_attribute(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, got = _run(tmp, self.RECORDS(), [_header()])
        self.assertEqual(_tas_attrs(got), {})

    def test_a_record_adds_attributes_and_changes_no_variable(self):
        rec = {"tas_s3_source": "aircraft.cdf", "tas_s3_records_total": 1,
               "tas_s3_fallback_records": 0, "tas_s3_fallback_seconds": "none",
               "tas_s3_uncertainty": "every image record matched an aircraft TAS sample"}
        with tempfile.TemporaryDirectory() as tmp:
            _, plain = _run(tmp, self.RECORDS(), [_header()])
        with tempfile.TemporaryDirectory() as tmp:
            _, stamped = _run(tmp, self.RECORDS(), [_header()], tas_qc=rec)
        self.assertEqual({k: (int(v) if isinstance(v, np.integer) else v)
                          for k, v in _tas_attrs(stamped).items()},
                         {f"arrayprobe_{k}": v for k, v in rec.items()})
        self.assertEqual(plain["order"], stamped["order"])
        for name in plain["vars"]:
            np.testing.assert_array_equal(plain["vars"][name], stamped["vars"][name], name)
        self.assertEqual(set(stamped["attrs"]) - set(plain["attrs"]),
                         {f"arrayprobe_{k}" for k in rec})


class DriverCountsTheFallbackRecords(unittest.TestCase):
    def _image(self, tmp, seconds):
        path = Path(tmp) / "img.H.cdf"
        with netCDF4.Dataset(path, "w") as ds:
            ds.createDimension("t", len(seconds))
            for name, vals in (("hour", [6] * len(seconds)), ("minute", [6] * len(seconds)),
                               ("second", seconds)):
                ds.createVariable(name, "f8", ("t",))[:] = np.asarray(vals, dtype=float)
        return path

    def test_a_second_missing_from_the_series_is_counted_and_ranged(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = self._image(tmp, [0, 1, 1, 5, 6])
            rec = run_flight._s3_tas_qc_v35(img, np.array([60600.0, 60601.0, 60606.0]),
                                            np.array([120.0, 121.0, np.nan]))
        self.assertEqual(rec["tas_s3_records_total"], 5)
        self.assertEqual(rec["tas_s3_fallback_records"], 2)      # 060605, and 060606 is NaN
        self.assertEqual(rec["tas_s3_fallback_seconds"], "060605-060606")
        self.assertIn("170 m/s", rec["tas_s3_uncertainty"])

    def test_an_infinite_sample_is_used_not_a_fallback(self):
        """``imgProc_sm.m:1136`` falls back only on empty or NaN: ``isnan(Inf)`` is false,
        so an infinite sample is divided by, never replaced by 170 m/s."""
        with tempfile.TemporaryDirectory() as tmp:
            img = self._image(tmp, [0, 1])
            rec = run_flight._s3_tas_qc_v35(img, np.array([60600.0, 60601.0]),
                                            np.array([120.0, np.inf]))
        self.assertEqual(rec["tas_s3_fallback_records"], 0)

    def test_no_aircraft_series_gives_no_record(self):
        self.assertIsNone(run_flight._s3_tas_qc_v35("unused", None, None))


if __name__ == "__main__":
    unittest.main()
