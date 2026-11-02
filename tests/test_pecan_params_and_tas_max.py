# SPDX-License-Identifier: BSD-3-Clause
"""Opt-in ``pecan_params`` (stand-in for ``getPECANparams``) and ``tas_max`` (2DP), both engines.

Without either keyword each engine refuses exactly where MATLAB dies; with them, the PECAN
loop (``sizeDist.m:164-172`` v3.5, ``:132-140`` v3.1.4) is reproduced as written.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402
from tests.test_v35_sizedist_probetype1 import _write_probetype1_proc

from arrayprobe_uiops.pecan_params import (
    PecanParams,
    load_pecan_params,
    pecan_intar_threshold,
)


def _matlab_loop(tas_time, start, end, thr, default):
    """``sizeDist.m:166-173`` transcribed loop for loop."""
    out = np.ones(len(tas_time)) * default
    for ix in range(len(tas_time)):
        for iz in range(len(start)):
            if tas_time[ix] >= start[iz] and tas_time[ix] < end[iz]:
                out[ix] = thr[iz]
    return out


class TestPecanLoop(unittest.TestCase):
    def test_matches_the_matlab_loop_including_overlap_and_half_open_end(self):
        t = np.arange(100.0, 130.0)
        start, end, thr = [105, 110, 120], [115, 112, 120], [2e-6, 3e-6, 9e-6]
        got = pecan_intar_threshold(t, PecanParams(start, end, thr), 1e-5)
        np.testing.assert_array_equal(got, _matlab_loop(t, start, end, thr, 1e-5))
        self.assertEqual(got[t == 115][0], 1e-5)   # end is exclusive
        self.assertEqual(got[t == 111][0], 3e-6)   # the later spiral wins

    def test_file_filters_on_date_and_probe(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pecan.csv"
            p.write_text("# spirals\ndate,probe,start_s,end_s,intar_threshold_s\n"
                         "20150706,CIP,10,20,2e-6\n20150706,PIP,10,20,4e-6\n"
                         "20150709,CIP,30,40,5e-6\n", encoding="utf-8")
            got = load_pecan_params(p, ddate="20150706 012345", probename="CIP")
            np.testing.assert_array_equal(got.startT, [10.0])
            np.testing.assert_array_equal(got.intar_threshold_spirals, [2e-6])
            with self.assertRaises(ValueError):
                load_pecan_params(p, ddate="20990101", probename="CIP")

    def test_missing_column_and_empty_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.csv"
            p.write_text("start_s,end_s\n1,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_pecan_params(p)
        with self.assertRaises(ValueError):
            PecanParams([], [], [])


class _Proc(unittest.TestCase):
    CLOCK = [120000.0, 120001.0, 120002.0, 120003.0, 120004.0]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.proc = str(self.dir / "proc.nc")
        _write_probetype1_proc(self.proc, self.CLOCK)
        self.t = np.asarray(self.CLOCK)
        self.n = self.t.size

    def params_file(self, thr):
        p = self.dir / "pecan.csv"
        p.write_text(f"start_s,end_s,intar_threshold_s\n0,200000,{thr!r}\n", encoding="utf-8")
        return str(p)


class TestV35(_Proc):
    def _run(self, project, probe, ia=2, **kw):
        from arrayprobe_uiops import sizedist as sd
        out = str(self.dir / f"sd_{len(list(self.dir.iterdir()))}.nc")
        sd.run(self.proc, out, np.full(self.n, 100.0), self.t.copy(), probe, 6, 0,
               np.full(self.n, 85000.0), np.full(self.n, 5.0), ia, 0, 0, 0, project,
               "20150706 120000", software="UIOOPS_v3.5", creation_time="x", **kw)
        return out

    def test_pecan_without_params_is_refused_naming_the_option(self):
        with self.assertRaisesRegex(NotImplementedError, "pecan_params"):
            self._run("PECAN", "CIP")

    def test_pecan_params_on_another_case_is_refused(self):
        with self.assertRaises(ValueError):
            self._run("UND2016", "CIP", ia=0, pecan_params=self.params_file(1e-5))

    def test_pecan_with_params_runs(self):
        import netCDF4
        out = self._run("PECAN", "CIP", pecan_params=self.params_file(1e-5))
        with netCDF4.Dataset(out) as ds:
            self.assertIn("conc_minR", ds.variables)

    def test_tas_max_refused_where_the_case_assigns_one_and_when_invalid(self):
        with self.assertRaises(ValueError):
            self._run("UND2016", "CIP", ia=0, tas_max=170.0)
        for bad in (0.0, -1.0, float("nan"), True):
            with self.assertRaises(ValueError):
                self._run("UND2016", "CIP", ia=0, tas_max=bad)


    def test_the_supplied_spiral_threshold_reaches_the_shattering_test(self):
        import netCDF4

        def accepted(thr):
            out = self._run("PECAN", "CIP", pecan_params=self.params_file(thr))
            with netCDF4.Dataset(out) as ds:
                return float(np.nansum(np.asarray(ds.variables["conc_minR"][:])))
        # A zero threshold flags nothing as shattered; a one-second threshold flags every
        # particle whose inter-arrival time is shorter, so the two cannot agree unless the
        # file's value is ignored.
        self.assertNotEqual(accepted(0.0), accepted(1.0))


_P03 = Path(__file__).resolve().parent / "data" / "v35_probetype03_sizedist"


class TestV35TasMax2DP(unittest.TestCase):
    """The 2DP row assigns no tasMax; a supplied one is used, none is refused."""

    def setUp(self):
        import json
        if not (_P03 / "cases.json").is_file():
            self.skipTest("The reference output of v35_probetype03_sizedist is not distributed "
                          "with the package")
        inp = json.loads((_P03 / "cases.json").read_text(encoding="utf-8"))["_inputs"]
        self.times = np.asarray(inp["times"], dtype=float)
        self.tas = np.asarray(inp["tas"], dtype=float)
        self.ddate = inp["ddate"]
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _run(self, **kw):
        from arrayprobe_uiops import sizedist as sd
        out = Path(self._tmp.name) / f"sd_{len(list(Path(self._tmp.name).iterdir()))}.nc"
        n = self.times.size
        sd.run(str(_P03 / "2dc_main.proc.nc"), str(out), self.tas, self.times.copy(), "2DP", 6,
               0, np.full(n, 85000.0), np.full(n, 5.0), 0, 0, 0, 0, "TEST", self.ddate,
               software="UIOOPS_v3.5", creation_time="x", **kw)
        return out

    def test_without_tas_max_is_refused_saying_why_no_default_exists(self):
        from arrayprobe_uiops.sizedist import TasMaxUndefined
        with self.assertRaisesRegex(TasMaxUndefined, "No default exists.*tas_max"):
            self._run()

    def test_with_tas_max_runs(self):
        import netCDF4
        with netCDF4.Dataset(self._run(tas_max=170.0)) as ds:
            self.assertIn("conc_minR", ds.variables)


class TestV314(_Proc):
    def _run(self, project, probe, **kw):
        from arrayprobe import sizedist
        out = str(self.dir / f"sd_{len(list(self.dir.iterdir()))}.nc")
        sizedist.run(self.proc, out, np.full(self.n, 100.0), self.t.copy(), probe, 6, 0,
                     np.full(self.n, 85000.0), np.full(self.n, 5.0), project,
                     "20150706 120000", tree="stock", ia_thresh_type=2, **kw)

    @needs_v314_engine
    def test_pecan_without_params_is_refused_naming_the_option(self):
        with self.assertRaisesRegex(NotImplementedError, "pecan_params"):
            self._run("PECAN", "CIP")

    @needs_v314_engine
    def test_tas_max_refused_where_the_case_assigns_one(self):
        with self.assertRaises(ValueError):
            self._run("PECAN", "CIP", pecan_params=self.params_file(1e-5), tas_max=170.0)

    def test_2dp_tasmax_message_names_the_option(self):
        from arrayprobe.constants import MatlabUndefinedVariable, sizedist_config
        with self.assertRaisesRegex(MatlabUndefinedVariable, "tas_max"):
            _ = sizedist_config("ORACLES", "2DP", "stock").tasMax


if __name__ == "__main__":
    unittest.main()
