# SPDX-License-Identifier: BSD-3-Clause
"""``combine.combine_sizedist`` -- combine_sizedist.m, S4c's acceptance gate.

These tests pin the mechanisms of combine_sizedist.m
(the dedup rule, the time axis, the append-missing-steps ladder,
the summary-file sync) on small synthetic inputs, plus a pinning test that the
by-name reads in combine.py still resolve to the indices the MATLAB hard-codes
sizeDist.run(tree=...) writing sd files with. A real multi-file acceptance
check against the actual archived product lives in
scripts/validate_combine.py (needs real data, not run by the automated suite).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

import numpy as np

from arrayprobe import combine, ncio
from arrayprobe.matlab_compat import datenum
from arrayprobe_uiops import sizedist_core as sizedist


def _write_sd_fixture(path, time, bin_mid, conc_minR, conc_AreaR, n, reject_ratio,
                      count, mean_area_ratio):
    """A minimal sd-shaped file: only the 11 variables combine.py reads, at
    their real sizeDist.py indices (0,1,2,3,4,5,7,8,15,20,21), so the by-index
    contract combine_sizedist.m relies on is exercised even though this
    fixture skips the other 14 sd variables.
    """
    B = len(bin_mid)
    f = ncio.create(str(path), "clobber")
    t_dim = ncio.def_dim(f, "Time", len(time))
    b_dim = ncio.def_dim(f, "CIPcorrlen", B)
    names_in_order = [
        ("time", [t_dim], time.astype(np.float64)),
        ("bin_min", [b_dim], bin_mid - 0.005),
        ("bin_max", [b_dim], bin_mid + 0.005),
        ("bin_mid", [b_dim], bin_mid),
        ("bin_dD", [b_dim], np.full(B, 0.01)),
        ("conc_minR", [b_dim, t_dim], conc_minR),         # varid 5, MATLAB (bin,time)
        ("area", [b_dim, t_dim], np.zeros((B, len(time)))),  # varid 6, unread filler
        ("conc_AreaR", [b_dim, t_dim], conc_AreaR),        # varid 7
        ("n", [t_dim], n),                                  # varid 8
    ]
    for i in range(9, 15):  # varid 9-14, unread fillers
        names_in_order.append((f"_filler{i}", [t_dim], np.zeros(len(time))))
    names_in_order.append(("Reject_ratio", [t_dim], reject_ratio))  # varid 15
    for i in range(16, 20):  # varid 16-19, unread fillers
        names_in_order.append((f"_filler{i}", [b_dim, t_dim], np.zeros((B, len(time)))))
    names_in_order.append(("count", [b_dim, t_dim], count))               # varid 20
    names_in_order.append(("mean_area_ratio", [b_dim, t_dim], mean_area_ratio))  # varid 21

    varids = {}
    for name, dims, _ in names_in_order:
        varids[name] = ncio.def_var(f, name, "double", dims)
    ncio.end_def(f)
    for name, _, values in names_in_order:
        ncio.put_var(f, varids[name], values)
    ncio.close(f)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class VaridPinningTest(unittest.TestCase):
    """combine.py reads by NAME; this pins that the names still resolve to the
    indices combine_sizedist.m hard-codes, per the S4c design doc's decision 4."""

    def test_matlab_varid_matches_sizedist_write_order(self):
        defs = list(sizedist._VARS)  # i_create_aspect_ratio=False -> _VARS_TAIL follows directly
        defs += list(sizedist._VARS_TAIL)
        order = {name: i for i, (name, _, _) in enumerate(defs)}
        for name, expected_idx in combine.MATLAB_VARID.items():
            self.assertEqual(
                order[name], expected_idx,
                f"{name}: sizeDist writes it at index {order[name]}, "
                f"combine_sizedist.m reads index {expected_idx}",
            )


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class CombineSizedistTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _make_file(self, name, times, seed=0):
        rng = np.random.default_rng(seed)
        bin_mid = np.round(np.arange(0.005, 0.005 + 0.01 * 8, 0.01), 6)
        B, T = len(bin_mid), len(times)
        path = self.tmp / name
        _write_sd_fixture(
            path, np.asarray(times, dtype=np.float64), bin_mid,
            conc_minR=rng.random((B, T)),
            conc_AreaR=rng.random((B, T)),
            n=rng.random(T),
            reject_ratio=rng.random(T),
            count=rng.integers(0, 5, size=(B, T)).astype(np.float64),
            mean_area_ratio=rng.random((B, T)),
        )
        return path

    def test_single_file_round_trips_every_second(self):
        # No duplicates, no gaps: output should have exactly the input's
        # seconds, and Counts should equal the input's count array exactly
        # (transposed to (time, bin), no scaling applied to Counts anywhere
        # in combine_sizedist.m). summary_time matches the first row exactly
        # so no summary-sync padding is added (covered separately).
        times = [64403, 64404, 64405]
        f1 = self._make_file("sd1.nc", times)
        out = self.tmp / "combined.nc"
        combine.combine_sizedist(
            [f1], out, flight_date="20160906", summary_time="16_09_06_06_44_03",
        )
        with netCDF4.Dataset(out) as ds:
            self.assertEqual(len(ds.dimensions["time"]), 3)
            self.assertEqual(len(ds.dimensions["bin_count"]), 8)
            self.assertEqual(ds.dimensions["files_stitched"].size, 1)
            tv = np.asarray(ds.variables["Time Vector"][:])
            # 06:44:03, :04, :05 on 2016-09-06, seconds apart.
            self.assertAlmostEqual(float(tv[1] - tv[0]), 1.0 / 86400.0, places=9)
            self.assertAlmostEqual(float(tv[2] - tv[0]), 2.0 / 86400.0, places=9)

    def test_only_adjacent_duplicates_are_dropped(self):
        # :84-91 -- diff(time)==0 only fires on ADJACENT equal values. Real
        # SPEC time is monotonically non-decreasing, so a duplicate that
        # isn't adjacent would require intervening values equal to it too
        # (the "kept, non-adjacent repeat" rule itself is exercised on
        # non-monotonic synthetic data in validate_against_product's own
        # align() tests, which don't share this function's ladder-building
        # step). Here: two SEPARATE adjacent-duplicate pairs, both collapsed.
        times = [64403, 64403, 64404, 64404, 64405]
        f1 = self._make_file("sd1.nc", times)
        out = self.tmp / "combined.nc"
        combine.combine_sizedist(
            [f1], out, flight_date="20160906", summary_time="16_09_06_06_44_03",
        )
        with netCDF4.Dataset(out) as ds:
            # 64403, 64404, 64405 kept -- a 3-second span, no gaps to fill.
            self.assertEqual(len(ds.dimensions["time"]), 3)

    def test_two_files_concatenate_in_the_order_given(self):
        f1 = self._make_file("sd1.nc", [64403, 64404], seed=1)
        f2 = self._make_file("sd2.nc", [64500, 64501], seed=2)
        out = self.tmp / "combined.nc"
        # summary_time matches the first real row exactly, so no summary-sync
        # padding is added -- this test is isolating the append-missing-steps
        # ladder, not the summary sync (covered separately below).
        combine.combine_sizedist(
            [f1, f2], out, flight_date="20160906", summary_time="16_09_06_06_44_03",
        )
        with netCDF4.Dataset(out) as ds:
            self.assertEqual(ds.dimensions["files_stitched"].size, 2)
            tv = np.asarray(ds.variables["Time Vector"][:])
            # 64403 to 64501 inclusive, on a 1 Hz ladder: 59 seconds span + 1.
            self.assertEqual(len(tv), 59)
            nt = np.asarray(ds.variables["Number Concentration cm-3"][:])
            # Real rows are at offsets 0,1 (file 1) and 57,58 (file 2); the
            # rest are the appended-missing-steps NaN fill.
            self.assertTrue(np.isfinite(nt[0]))
            self.assertTrue(np.isfinite(nt[1]))
            self.assertTrue(np.isnan(nt[2]))
            self.assertTrue(np.isfinite(nt[57]))
            self.assertTrue(np.isfinite(nt[58]))

    def test_the_60_seconds_field_is_corrected_forward_a_minute(self):
        # :100-107.  A SPEC clock can emit HHMM60; the true instant is one
        # minute later at :00, not a malformed stamp.
        f1 = self._make_file("sd1.nc", [64459, 64460])  # bogus '60' at index 1
        out = self.tmp / "combined.nc"
        # summary_time matches the first real row exactly -- see the note in
        # test_two_files_concatenate_in_the_order_given.
        combine.combine_sizedist(
            [f1], out, flight_date="20160906", summary_time="16_09_06_06_44_59",
        )
        with netCDF4.Dataset(out) as ds:
            tv = np.asarray(ds.variables["Time Vector"][:])
            # 06:44:59 then 06:45:00 -- one second apart, not the same second
            # and not 59 seconds apart (which not fixing '60' would give).
            self.assertAlmostEqual(float(tv[-1] - tv[0]), 1.0 / 86400.0, places=9)

    def test_summary_time_before_data_prepends_nan_padding(self):
        f1 = self._make_file("sd1.nc", [64410])
        out = self.tmp / "combined.nc"
        combine.combine_sizedist(
            [f1], out, flight_date="20160906", summary_time="16_09_06_06_40_00",
        )
        with netCDF4.Dataset(out) as ds:
            tv = np.asarray(ds.variables["Time Vector"][:])
            nt = np.asarray(ds.variables["Number Concentration cm-3"][:])
            # Summary at 06:40:00, data at 06:44:10 -- 250 s of padding before
            # the one real row.
            self.assertEqual(len(tv), 251)
            self.assertTrue(np.all(np.isnan(nt[:-1])))
            self.assertTrue(np.isfinite(nt[-1]))
            self.assertAlmostEqual(float(tv[0]),
                                  float(datenum(2016, 9, 6, 6, 40, 0)), places=9)

    def test_summary_time_at_data_start_pads_nothing(self):
        f1 = self._make_file("sd1.nc", [64400])
        out = self.tmp / "combined.nc"
        combine.combine_sizedist(
            [f1], out, flight_date="20160906", summary_time="16_09_06_06_44_00",
        )
        with netCDF4.Dataset(out) as ds:
            self.assertEqual(len(ds.dimensions["time"]), 1)

    def test_current_year_override_matches_default_when_set_for_today(self):
        # current_year is "correct" only when it equals the 2-digit calendar
        # year this test actually runs in (upstream: nothing checks it,
        # and a wrong value silently shifts every timestamp by whole years --
        # exercised directly below). Set correctly, it must reproduce the
        # SAME axis the default (correct-by-construction) path computes,
        # since both are describing the same real instant.
        import datetime as _dt
        f1 = self._make_file("sd1.nc", [64403, 64404])
        out_default = self.tmp / "default.nc"
        out_replica = self.tmp / "replica.nc"
        combine.combine_sizedist(
            [f1], out_default, flight_date="20160906", summary_time="16_09_06_06_44_03",
        )
        combine.combine_sizedist(
            [f1], out_replica, flight_date="20160906", summary_time="16_09_06_06_44_03",
            current_year=_dt.date.today().year - 2000,
        )
        with netCDF4.Dataset(out_default) as a, netCDF4.Dataset(out_replica) as b:
            tv_a = np.asarray(a.variables["Time Vector"][:])
            tv_b = np.asarray(b.variables["Time Vector"][:])
            np.testing.assert_allclose(tv_a, tv_b, atol=1e-6)

    def test_wrong_current_year_refuses_rather_than_allocates_wildly(self):
        # The failure mode upstream describes: a current_year that does
        # NOT match the real run year makes the replica axis land years away
        # from the default axis, which the summary-sync step would otherwise
        # try to bridge with millions of NaN rows. combine_sizedist refuses
        # instead of silently allocating tens of gigabytes.
        f1 = self._make_file("sd1.nc", [64403, 64404])
        out = self.tmp / "combined.nc"
        with self.assertRaises(ValueError):
            combine.combine_sizedist(
                [f1], out, flight_date="20160906", summary_time="16_09_06_06_44_00",
                current_year=21,
            )

    def test_no_global_attributes_are_written(self):
        # :202-231 defines only variables; matching that is part of fidelity.
        f1 = self._make_file("sd1.nc", [64403])
        out = self.tmp / "combined.nc"
        combine.combine_sizedist(
            [f1], out, flight_date="20160906", summary_time="16_09_06_06_44_00",
        )
        with netCDF4.Dataset(out) as ds:
            self.assertEqual(len(ds.ncattrs()), 0)

    def test_variable_names_and_dims_match_the_matlab_source(self):
        f1 = self._make_file("sd1.nc", [64403, 64404])
        out = self.tmp / "combined.nc"
        combine.combine_sizedist(
            [f1], out, flight_date="20160906", summary_time="16_09_06_06_44_00",
        )
        with netCDF4.Dataset(out) as ds:
            # Dimension order confirmed against the real archived product
            # (old_oracles_data/2DS_H_current/base160906064017.combined.H.2DS_2.cdf):
            # the 2D variables are ('bin_count', 'time') on disk, not
            # ('time', 'bin_count') -- MATLAB's own defVar([dimid0 dimid1]) with
            # dimid0=time lists time FIRST/fastest in MATLAB order, which
            # ncio.def_var reverses for on-disk (C-order) storage.
            expected = {
                "Time Vector": ("time",),
                "Bin Minimum": ("bin_count",),
                "Bin Maximum": ("bin_count",),
                "Bin Midpoints": ("bin_count",),
                "Bin Width": ("bin_count",),
                "Mean Area Ratio": ("bin_count", "time"),
                "Counts": ("bin_count", "time"),
                "Size Distribution cm-3": ("bin_count", "time"),
                "Number Concentration cm-3": ("time",),
                "Reject Ratio": ("time",),
            }
            self.assertEqual(set(ds.variables), set(expected))
            for name, dims in expected.items():
                self.assertEqual(ds.variables[name].dimensions, dims, name)


class TimeOfDayHelper(unittest.TestCase):
    """``_time_of_day`` behind ``:101-107``: a ``:60`` seconds field is read as
    ``:00`` and flagged, so the caller adds the minute afterwards. Added
    2026-09-27 after ``is_60 = ss == 61`` left the whole module green -- no
    fixture carried a ``:60`` field."""

    def test_a_sixty_second_field_is_zeroed_and_flagged(self):
        tod, is_60 = combine._time_of_day(np.array([120060.0, 120059.0, 120000.0]))
        np.testing.assert_array_equal(is_60, [True, False, False])
        self.assertEqual(tod[0], 12 / 24.0)                       # ss read as 0
        self.assertEqual(tod[1], 12 / 24.0 + 59 / 86400.0)
        self.assertEqual(tod[2], 12 / 24.0)
        self.assertLess(tod[0], tod[1])                           # the minute comes later


if __name__ == "__main__":
    unittest.main()
