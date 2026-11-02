# SPDX-License-Identifier: BSD-3-Clause
"""Tests for overload_accounting_fix.py (the upstream no-accept second overwrite)."""

from __future__ import annotations

import glob
import os
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements.overload_accounting_fix import (
    MissingSizeDistVariables,
    affected_seconds,
    apply_overload_accounting,
    overload_time_per_second,
)

_DEC = Path(__file__).resolve().parents[2] / "_decoded"
_DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
_V35_PROC = _DATA / "demo_flight_v35_proc.nc"
_V35_SD = _DATA / "demo_flight_v35_sd.nc"
_V35_AIRCRAFT = _DATA / "demo_flight_v35_aircraft.cdf"


class PerSecondOverloadTime(unittest.TestCase):
    def test_sum_over_flagged_particles_with_previous_particle_gap(self):
        times = np.array([1, 1, 2, 2, 2])
        tis = np.array([0.0, 0.5, 1.0, 1.2, 1.5])
        dof = np.array([0, 0, 1, 0, 1])
        t72, n = overload_time_per_second(times, tis, dof, second=2, res=10, tas_max=170)
        # particle 3's gap is measured against particle 2 (previous in file): 0.5
        self.assertEqual(n, 3)
        self.assertAlmostEqual(t72, 0.5 + 0.3)

    def test_first_particle_of_file_has_zero_gap(self):
        t72, _ = overload_time_per_second([5, 5], [3.0, 3.4], [1, 0], second=5, res=10,
                                          tas_max=170)
        self.assertEqual(t72, 0.0)

    def test_rollback_corrects_large_negative_gap(self):
        res, tas_max = 10, 170
        tis = np.array([100.0, 100.0 - 50.0])  # a -50 s gap: clock rolled back
        t72, _ = overload_time_per_second([7, 7], tis, [0, 1], second=7, res=res,
                                          tas_max=tas_max)
        self.assertAlmostEqual(t72, -50.0 + (2 ** 32 - 1) * (res / 1e6 / tas_max))

    def test_small_negative_gap_clips_to_zero(self):
        t72, _ = overload_time_per_second([7, 7], [1.0, 0.999], [0, 1], second=7, res=10,
                                          tas_max=170)
        self.assertEqual(t72, 0.0)

    def test_probetype_0_has_no_overload_flag(self):
        t72, _ = overload_time_per_second([1, 1], [0.0, 0.2], [1, 1], second=1, res=25,
                                          tas_max=125, probetype=0)
        self.assertEqual(t72, 0.0)


class AffectedSeconds(unittest.TestCase):
    def test_particles_present_none_accepted_and_reset(self):
        sd_time = np.array([1.0, 2.0, 3.0, 4.0])
        count = np.array([[1, 0, 0, 0], [0, 0, 0, 0]]).T  # seconds 2,3,4 accept nothing
        sum_intarr = np.array([0.8, 1.0, 1.0, 0.9])
        proc_times = np.array([1, 2, 2, 3])                # second 4 has no particles at all
        np.testing.assert_array_equal(affected_seconds(sd_time, count, sum_intarr, proc_times),
                                      [1, 2])


@unittest.skipUnless(_V35_PROC.exists() and _V35_SD.exists(),
                     "Tracked v3.5 demo fixtures are not distributed with the package; this "
                     "test runs in the development repository")
class ConditionalOnV35(unittest.TestCase):
    """A default v3.5 ``sd`` has neither ``sum_IntArr`` nor ``sample_vol``
    (measured: ``sizeDist.m:2363``'s ``iSaveIntArrSV`` gate; ``run_flight.py``'s
    ``V35_CALL`` pins it to 0), so this module refuses by name rather than applying
    vacuously; and it DOES apply once a run is made with ``i_save_int_arr_sv=1``."""

    def test_the_refusal_names_iSaveIntArrSV_on_the_tracked_demo_sd(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a8.nc")
            with self.assertRaises(MissingSizeDistVariables) as ctx:
                apply_overload_accounting(str(_V35_PROC), str(_V35_SD), out)
            self.assertIn("iSaveIntArrSV", str(ctx.exception))
            self.assertFalse(os.path.exists(out), "must refuse before writing anything")

    def test_equivalence_on_a_v35_sd_built_with_i_save_int_arr_sv_1(self):
        """Flip the one V35_CALL switch (the V35_SIZEDIST_SWITCHES set) and the
        module applies: every reset second on this file recomputes t72 == 0.0
        (nothing is flagged DMT_DOF_SPEC_OVERLOAD in this tiny demo), so the
        recomputation reproduces exactly what the port itself wrote -- the copy
        is byte-identical to the freshly-built sd."""
        from arrayprobe_uiops.sizedist import run as v35_run

        with netCDF4.Dataset(_V35_AIRCRAFT) as a:
            timehhmmss = np.floor(np.asarray(a.variables["Time"][:], float))
            tas = np.asarray(a.variables["TAS"][:], float)
        with tempfile.TemporaryDirectory() as tmp:
            sd_path = os.path.join(tmp, "sd_with_int_arr.nc")
            v35_run(
                str(_V35_PROC), sd_path, tas, timehhmmss, "2DS", 6, 0,
                np.full_like(tas, 9e5), np.full_like(tas, 15.0),
                0, 0, 0, 1,  # ia_thresh_type, i_create_aspect_ratio, i_create_bad,
                             # i_save_int_arr_sv -- the one flag flipped from V35_CALL's 0
                "DEMO", "20160101 000000",
                software="UIOOPS_v3.5",
            )
            with netCDF4.Dataset(sd_path) as d:
                self.assertIn("sum_IntArr", d.variables)
                self.assertIn("sample_vol", d.variables)
                before_sum = np.asarray(d.variables["sum_IntArr"][:], float).copy()
                before_svol = np.asarray(d.variables["sample_vol"][:], float).copy()

            out = os.path.join(tmp, "a8.nc")
            report = apply_overload_accounting(str(_V35_PROC), sd_path, out)
            # This tiny demo has one particle per second and none flagged
            # DMT_DOF_SPEC_OVERLOAD, so every second the port reset is a
            # legitimate "nothing overloaded" second: t72 recomputes to 0.0
            # for all of them, which is what the file already held -- the
            # recomputation is idempotent, not a no-op because nothing was
            # affected.
            self.assertGreater(len(report), 0, "this demo file has resettable seconds")
            for _sec, n, t72, new in report:
                self.assertGreater(n, 0)
                self.assertEqual(t72, 0.0)
                self.assertEqual(new, 1.0)
            with netCDF4.Dataset(out) as d:
                np.testing.assert_array_equal(np.asarray(d.variables["sum_IntArr"][:], float),
                                              before_sum)
                np.testing.assert_array_equal(np.asarray(d.variables["sample_vol"][:], float),
                                              before_svol)


@unittest.skipUnless(_DEC.exists() and glob.glob(str(_DEC / "sd.base160906064403.H*.nc")),
                     "Real decoded 064403 is not distributed with the package; this test runs "
                     "in the development repository")
class RealPair(unittest.TestCase):
    def test_recomputation_reproduces_the_port_where_no_reset_happened(self):
        sd_path = sorted(glob.glob(str(_DEC / "sd.base160906064403.H*.nc")))[0]
        proc_path = str(_DEC / ("proc.base160906064403.H.stockreject.nc"
                                if "stockreject" in sd_path else "proc.base160906064403.H.nc"))
        with netCDF4.Dataset(proc_path) as p, netCDF4.Dataset(sd_path) as d:
            times = np.asarray(p.variables["Time"][:], float)
            tis = np.asarray(p.variables["Time_in_seconds"][:], float)
            dof = np.asarray(p.variables["DMT_DOF_SPEC_OVERLOAD"][:])
            sd_time = np.asarray(d.variables["time"][:], float)
            sum_intarr = np.asarray(d.variables["sum_IntArr"][:], float)
        # oracle: seconds the port did NOT reset carry sum_IntArr = 1 - t72 from :813
        checked = 0
        for i in np.flatnonzero((sum_intarr != 1.0) & np.isfinite(sum_intarr))[:200]:
            t72, n = overload_time_per_second(times, tis, dof, second=sd_time[i], res=10,
                                              tas_max=170)
            if n:
                self.assertAlmostEqual(1.0 - t72, sum_intarr[i], places=12)
                checked += 1
        self.assertGreater(checked, 10)

    def test_apply_writes_a_copy_and_leaves_the_source_alone(self):
        sd_path = sorted(glob.glob(str(_DEC / "sd.base160906064403.H*.nc")))[0]
        proc_path = str(_DEC / ("proc.base160906064403.H.stockreject.nc"
                                if "stockreject" in sd_path else "proc.base160906064403.H.nc"))
        before = os.path.getmtime(sd_path)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a8.nc")
            report = apply_overload_accounting(proc_path, sd_path, out)
            self.assertGreater(len(report), 0)
            with netCDF4.Dataset(out) as d:
                s = np.asarray(d.variables["sum_IntArr"][:], float)
                t = np.asarray(d.variables["time"][:], float)
            for sec, n, t72, new in report:
                self.assertGreater(n, 0)
                self.assertLessEqual(new, 1.0)
                self.assertEqual(s[np.flatnonzero(t == sec)[0]], new)
        self.assertEqual(os.path.getmtime(sd_path), before)


if __name__ == "__main__":
    unittest.main()
