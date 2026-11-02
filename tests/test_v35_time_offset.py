# SPDX-License-Identifier: BSD-3-Clause
"""The opt-in probe-clock offset of ``arrayprobe_uiops.sizedist.run`` (``time_offset_s``).

A whole number of seconds added to every particle time where ``sizeDist`` reads it, for a probe
whose own clock is measured off aircraft time. Default: the path that always ran, file bytes
included. With ``time_offset_tas_clock="probe"`` the per-second rows move with the particles
(every per-second value unchanged, only ``time`` moves, across midnight too); with
``"aircraft"`` they stay and the particles land ``k`` rows later.

Inputs are the tracked probetype-1 fixture and aircraft state of
``tests/data/v35_area_ratio_z/cases.json`` (six seconds, 06:13:37-06:13:42, TAS 95 m/s).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_uiops import sizedist as v35s

DATA = Path(__file__).resolve().parent / "data"
CASES = DATA / "v35_area_ratio_z" / "cases.json"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/10/02 00:00:00"
EVIDENCE = "test: raw clock measured 2 s behind aircraft time"
OFFSET_ATTRS = ("arrayprobe_time_offset_s", "arrayprobe_time_offset_evidence",
                "arrayprobe_time_offset_tas_clock")


class _Base(unittest.TestCase):
    def setUp(self):
        if not CASES.is_file():
            self.skipTest("The reference output of v35_area_ratio_z is not distributed with the "
                          "package")
        inp = json.loads(CASES.read_text(encoding="utf-8"))["_inputs"]
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

    def run_sd(self, times=None, **kw):
        """Run the port; returns (returned dict, {variable: array}, attributes, file sha256)."""
        self._n += 1
        got = Path(self._tmp.name) / f"sd{self._n}.nc"
        t = self.times if times is None else np.asarray(times, dtype=float)
        out = v35s.run(str(self.infile), str(got), self.tas, t, "CIP", 6, 0,
                       self.pres, self.temp, 0, 0, 1, 1, "TEST", self.ddate,
                       software=SOFTWARE, creation_time=CREATION_TIME, **kw)
        with netCDF4.Dataset(got) as d:
            variables = {k: np.ma.filled(np.asarray(v[:], dtype=float), np.nan)
                         for k, v in d.variables.items()}
            attrs = {a: d.getncattr(a) for a in d.ncattrs()}
        return out, variables, attrs, hashlib.sha256(got.read_bytes()).hexdigest()

    def offset(self, k, clock):
        return dict(time_offset_s=k, time_offset_evidence=EVIDENCE, time_offset_tas_clock=clock)


class TestShiftHhmmss(unittest.TestCase):
    def test_arithmetic_and_midnight_wrap(self):
        got = v35s.shift_hhmmss(np.array([120000, 235959, 10, 235950, 61337]), 1)
        np.testing.assert_array_equal(got, [120001, 0, 11, 235951, 61338])
        np.testing.assert_array_equal(v35s.shift_hhmmss(np.array([10, 59, 5959]), -20),
                                      [235950, 39, 5939])
        np.testing.assert_array_equal(v35s.shift_hhmmss(np.array([235950]), 100), [130])
        np.testing.assert_array_equal(v35s.shift_hhmmss(np.array([95959]), 3601), [110000])


class TestDefaultIsBitIdentical(_Base):
    def test_unset_and_none_write_the_same_bytes(self):
        o0, v0, a0, h0 = self.run_sd()
        o1, v1, a1, h1 = self.run_sd(time_offset_s=None, time_offset_evidence=None,
                                     time_offset_tas_clock=None)
        self.assertEqual(h0, h1)
        self.assertEqual(set(v0), set(v1))
        for k in v0:
            self.assertTrue(np.array_equal(v0[k], v1[k], equal_nan=True), k)
        self.assertTrue(np.array_equal(o0["_total_one_sec_locs"], o1["_total_one_sec_locs"]))
        for name in OFFSET_ATTRS:
            self.assertNotIn(name, a0)


class TestProbeClock(_Base):
    """Rows from the probe's own record share its clock: everything moves together."""

    def assert_moved_together(self, k):
        _o0, v0, _a0, _ = self.run_sd()
        _o1, v1, a1, _ = self.run_sd(**self.offset(k, "probe"))
        self.assertGreater(np.nansum(v0["count"]), 0)
        for name in v0:
            if name == "time":
                continue
            self.assertTrue(np.array_equal(v0[name], v1[name], equal_nan=True), name)
        self.assertEqual(a1["arrayprobe_time_offset_s"], float(k))
        self.assertEqual(a1["arrayprobe_time_offset_evidence"], EVIDENCE)
        self.assertEqual(a1["arrayprobe_time_offset_tas_clock"], "probe")
        return v1["time"]

    def test_values_unchanged_time_moved(self):
        t = self.assert_moved_together(100)
        np.testing.assert_array_equal(t, v35s.shift_hhmmss(self.times, 100))

    def test_across_midnight(self):
        # 06:13:37 + 63981 s = 23:59:58: the rows cross midnight and the particles (06:13:39-40)
        # land at 00:00:00-01, after it, so the engine's own flight-day carryover
        # (apply_flight_day_carryover) files them on the next day exactly as for a real clock.
        t = self.assert_moved_together(63981)
        np.testing.assert_array_equal(t, [235958, 235959, 240000, 240001, 240002, 240003])

    def test_shifted_particle_times_straddling_midnight_read_as_one_crossing(self):
        x = v35s.shift_hhmmss(np.array([235957.0, 235958, 235959, 0, 1, 2]), 1)
        fixed, crossed = v35s.fix_multiday_particle_times(x)
        self.assertTrue(crossed)
        np.testing.assert_array_equal(fixed, [235958, 235959, 240000, 240001, 240002, 240003])

    def test_negative_offset(self):
        t = self.assert_moved_together(-78)
        np.testing.assert_array_equal(t, v35s.shift_hhmmss(self.times, -78))


class TestAircraftClock(_Base):
    """Rows from an aircraft file are already aircraft time: only the particles move."""

    def test_particles_land_k_rows_later(self):
        k = 2
        o0, v0, _a0, _ = self.run_sd()
        o1, v1, a1, _ = self.run_sd(**self.offset(k, "aircraft"))
        np.testing.assert_array_equal(v1["time"], v0["time"])
        n0, n1 = o0["_total_one_sec_locs"], o1["_total_one_sec_locs"]
        self.assertGreater(n0[:-k].sum(), 0)
        np.testing.assert_array_equal(n1[k:], n0[:-k])
        np.testing.assert_array_equal(n1[:k], 0)
        # TAS is constant here, so the per-second distributions move row for row too.
        self.assertTrue(np.array_equal(v1["count"][k:], v0["count"][:-k], equal_nan=True))
        self.assertEqual(a1["arrayprobe_time_offset_tas_clock"], "aircraft")


class TestRefusals(_Base):
    def test_bad_arguments_are_refused(self):
        bad = [
            dict(time_offset_s=1.5, time_offset_evidence=EVIDENCE, time_offset_tas_clock="probe"),
            dict(time_offset_s=0, time_offset_evidence=EVIDENCE, time_offset_tas_clock="probe"),
            dict(time_offset_s=86400, time_offset_evidence=EVIDENCE,
                 time_offset_tas_clock="probe"),
            dict(time_offset_s=True, time_offset_evidence=EVIDENCE, time_offset_tas_clock="probe"),
            dict(time_offset_s=5, time_offset_tas_clock="probe"),
            dict(time_offset_s=5, time_offset_evidence="  ", time_offset_tas_clock="probe"),
            dict(time_offset_s=5, time_offset_evidence=EVIDENCE),
            dict(time_offset_s=5, time_offset_evidence=EVIDENCE, time_offset_tas_clock="gps"),
            dict(time_offset_evidence=EVIDENCE),
            dict(time_offset_tas_clock="probe"),
        ]
        for kw in bad:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.run_sd(**kw)

    def test_whole_float_is_accepted(self):
        _o, _v, a, _ = self.run_sd(**self.offset(2.0, "probe"))
        self.assertEqual(a["arrayprobe_time_offset_s"], 2.0)


if __name__ == "__main__":
    unittest.main()
