# SPDX-License-Identifier: BSD-3-Clause
"""The TAS source chain (``arrayprobe.tools.tas_sources``): merge -> aircraft -> probe.

Synthetic netCDF fixtures only, written into a tempdir per test -- never the Box archive or
the local reference-data tree. Cases (i)-(viii) follow.

"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.tools import tas_sources
from arrayprobe.tools.make_tas_file import TasPolicy
from arrayprobe_soda2.pth_readers import read_pth_ascii


def _write_merge(path, sod, tas_kts, units="kts"):
    """``mrg1_P3_<yyyymmdd>_R*.nc``: ``Start_UTC`` (seconds of day) / ``True_Air_Speed`` (kts)."""
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", len(sod))
        t = ds.createVariable("Start_UTC", "f8", ("time",))
        t[:] = np.asarray(sod, dtype=np.float64)
        v = ds.createVariable("True_Air_Speed", "f8", ("time",))
        v[:] = np.asarray(tas_kts, dtype=np.float64)
        if units is not None:
            v.units = units


def _write_arm(path, seconds_since_base, tas_mps, base_time=1499299200, units="m/s"):
    """``enaaafmergedF1.c1.<date>.*.nc``: ``true_airspeed`` (m/s) on ``time`` + ``base_time``."""
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", len(seconds_since_base))
        t = ds.createVariable("time", "f8", ("time",))
        t[:] = np.asarray(seconds_since_base, dtype=np.float64)
        v = ds.createVariable("true_airspeed", "f4", ("time",))
        v[:] = np.asarray(tas_mps, dtype=np.float64)
        if units is not None:
            v.units = units
        ds.createVariable("base_time", "i4")[...] = base_time


def _write_probe_csv(path, rows):
    Path(path).write_text("".join(f"{t},{v}\n" for t, v in rows), encoding="ascii")


class MergeFileIsReadAndFillValuesSubstituted(unittest.TestCase):
    """(i) A merge-like file with one fill (9.969e36) and one missing (-9999) row."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def test_kts_converted_and_fill_values_substituted(self):
        path = self.d / "mrg1_P3_20170812_R28.nc"
        sod = [28800, 28801, 28802, 28803, 28804]  # 08:00:00..08:00:04
        kts = [200.0, 200.0, 9.969e36, -9999.0, 200.0]
        _write_merge(path, sod, kts)

        series = tas_sources.read_aircraft(path)
        expected = 200.0 * (1852.0 / 3600.0)
        np.testing.assert_allclose(series.tas_mps[0], expected)
        np.testing.assert_allclose(series.time_hhmmss, [80000.0, 80001.0, 80002.0, 80003.0,
                                                         80004.0])

        res = tas_sources.resolve_chain("merge", yyyymmdd=None, explicit={"merge": path})
        self.assertEqual(res.tier, "merge")
        self.assertEqual(res.source, "oracles-p3-merge")
        subs = dict(res.substituted)
        self.assertEqual(subs.get(80002), "above-cutoff")
        self.assertEqual(subs.get(80003), "non-positive")
        by_time = dict(zip(res.time.tolist(), res.tas.tolist(), strict=True))
        self.assertEqual(by_time[80002.0], 170.0)
        self.assertEqual(by_time[80003.0], 170.0)
        np.testing.assert_allclose(by_time[80000.0], expected)


class UnitsAreReadNotAssumed(unittest.TestCase):
    """(ii) An unknown or missing ``units`` attribute is refused, not guessed."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def test_unknown_units_raise(self):
        path = self.d / "mrg1_P3_20170812_R28.nc"
        _write_merge(path, [28800], [200.0], units="furlongs")
        with self.assertRaises(ValueError) as caught:
            tas_sources.read_aircraft(path)
        self.assertIn("refused rather than guessed", str(caught.exception))

    def test_missing_units_raise(self):
        path = self.d / "mrg1_P3_20170812_R29.nc"
        _write_merge(path, [28800], [200.0], units=None)
        with self.assertRaises(ValueError) as caught:
            tas_sources.read_aircraft(path)
        self.assertIn("carries no units attribute", str(caught.exception))

    def test_non_finite_time_is_refused_as_such(self):
        """A masked Start_UTC used to become an arbitrary negative HHMMSS, refused downstream
        as "seconds since some epoch"; the refusal now names the real cause."""
        path = self.d / "mrg1_P3_20170812_R30.nc"
        _write_merge(path, [28800, np.nan], [200.0, 200.0])
        with self.assertRaises(ValueError) as caught:
            tas_sources.read_aircraft(path)
        self.assertIn("'Start_UTC' has 1 masked or non-finite value", str(caught.exception))

    def test_a_non_finite_arm_time_is_refused_as_such(self):
        """The ARM seconds-since-base_time branch had no finite check, so a NaN ``time`` was cast
        to an arbitrary integer and refused downstream as "seconds since some epoch"."""
        path = self.d / "enaaafmergedF1.c1.20170707.000000.nc"
        _write_arm(path, [0.0, np.nan, 2.0], [100.0, 100.0, 100.0])
        with self.assertRaises(ValueError) as caught:
            tas_sources.read_aircraft(path)
        msg = str(caught.exception)
        self.assertIn("'time' has 1 masked or non-finite value", msg)
        self.assertNotIn("epoch", msg)

    def test_a_masked_arm_time_is_refused_not_read_as_a_clock_second(self):
        """A fill-value ``time`` came back from ``np.asarray`` as the fill itself, -9999, which
        the base_time conversion turned into 21:13:21 -- a real-looking second carrying that
        row's airspeed, accepted without a word."""
        path = self.d / "enaaafmergedF1.c1.20170707.000001.nc"
        with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
            ds.createDimension("time", 3)
            t = ds.createVariable("time", "f8", ("time",), fill_value=-9999.0)
            t[:] = np.ma.masked_array([0.0, 1.0, 2.0], mask=[False, True, False])
            v = ds.createVariable("true_airspeed", "f4", ("time",))
            v[:] = [100.0, 100.0, 100.0]
            v.units = "m/s"
            ds.createVariable("base_time", "i4")[...] = 1499299200
        with self.assertRaises(ValueError) as caught:
            tas_sources.read_aircraft(path)
        self.assertIn("'time' has 1 masked or non-finite value", str(caught.exception))

    def test_a_masked_merge_time_is_refused_not_read_as_a_clock_second(self):
        """The seconds-of-day branch's finite check never saw a fill-value time either: -9999
        seconds of day is 21:13:21."""
        path = self.d / "mrg1_P3_20170812_R31.nc"
        with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
            ds.createDimension("time", 2)
            t = ds.createVariable("Start_UTC", "f8", ("time",), fill_value=-9999.0)
            t[:] = np.ma.masked_array([28800.0, 28801.0], mask=[False, True])
            v = ds.createVariable("True_Air_Speed", "f8", ("time",))
            v[:] = [200.0, 200.0]
            v.units = "kts"
        with self.assertRaises(ValueError) as caught:
            tas_sources.read_aircraft(path)
        self.assertIn("'Start_UTC' has 1 masked or non-finite value", str(caught.exception))


class ChainFallsBackStepByStep(unittest.TestCase):
    """(iii) ``auto`` tries merge, then aircraft, then probe, and lists every skip."""

    def test_no_merge_file_falls_to_aircraft(self):
        d = Path(tempfile.mkdtemp())
        _write_arm(d / "enaaafmergedF1.c1.20170706.000000.nc", [0, 1, 2, 3, 4],
                   [90.0, 91.0, 92.0, 93.0, 94.0])
        res = tas_sources.resolve_chain("auto", yyyymmdd="20170706", search_dirs=[d])
        self.assertEqual(res.tier, "aircraft")
        self.assertEqual(res.source, "arm-aaf-merged")
        self.assertIn("merge/oracles-p3-merge: skipped (not available",
                       res.provenance["tas_chain_steps"])

    def test_no_aircraft_file_either_falls_to_probe_and_lists_both_skips(self):
        d = Path(tempfile.mkdtemp())
        csv = d / "base170812080701.tas.csv"
        _write_probe_csv(csv, [(80000.0, 150.0), (80001.0, 151.0), (80002.0, 152.0)])
        res = tas_sources.resolve_chain("auto", yyyymmdd="20170812", search_dirs=[d],
                                        probe_csv=csv)
        self.assertEqual(res.tier, "probe")
        outcomes = {tier: outcome for tier, _, outcome, _ in res.steps}
        self.assertEqual(outcomes["merge"], "skipped")
        self.assertEqual(outcomes["aircraft"], "skipped")

    def test_nothing_at_all_raises_naming_every_step(self):
        d = Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError) as caught:
            tas_sources.resolve_chain("auto", yyyymmdd="20170812", search_dirs=[d])
        msg = str(caught.exception)
        self.assertIn("merge/oracles-p3-merge", msg)
        self.assertIn("aircraft/arm-aaf-merged", msg)
        self.assertIn("probe/probe-tas-csv", msg)


class APinnedTierRefusesRatherThanFallingThrough(unittest.TestCase):
    """(iv) A pinned ``merge`` with no file raises and never tries the probe."""

    def test_pinned_merge_absent_does_not_use_probe(self):
        d = Path(tempfile.mkdtemp())
        csv = d / "base170812080701.tas.csv"
        _write_probe_csv(csv, [(80000.0, 150.0), (80001.0, 151.0)])
        with self.assertRaises(ValueError) as caught:
            tas_sources.resolve_chain("merge", yyyymmdd="20170812", search_dirs=[d],
                                      probe_csv=csv)
        self.assertNotIn("probe", str(caught.exception))


class TwoCandidatesFailTheTier(unittest.TestCase):
    """(v) More than one matching file is a failure, not a pick."""

    def test_two_merge_candidates_fail(self):
        d = Path(tempfile.mkdtemp())
        _write_merge(d / "mrg1_P3_20170812_R1.nc", [28800], [200.0])
        _write_merge(d / "mrg1_P3_20170812_R2.nc", [28800], [200.0])
        with self.assertRaises(ValueError) as caught:
            tas_sources.resolve_chain("merge", yyyymmdd="20170812", search_dirs=[d])
        msg = str(caught.exception)
        self.assertIn("2 candidate files", msg)
        self.assertIn("merge/oracles-p3-merge: failed", msg)


class AnAircraftSeriesMustShareASecondWithTheProbe(unittest.TestCase):
    """(vi) An aircraft file sharing no second with the probe clock is a failure."""

    def test_disjoint_clocks_fail(self):
        d = Path(tempfile.mkdtemp())
        _write_arm(d / "enaaafmergedF1.c1.20170706.000000.nc", [0, 1, 2, 3, 4],
                   [90.0, 91.0, 92.0, 93.0, 94.0])  # 08:00:00..08:00:04
        csv = d / "base170706000100.tas.csv"
        _write_probe_csv(csv, [(60.0, 150.0), (61.0, 151.0)])  # 00:01:00..00:01:01
        with self.assertRaises(ValueError) as caught:
            tas_sources.resolve_chain("aircraft", yyyymmdd="20170706", search_dirs=[d],
                                      probe_csv=csv)
        self.assertIn("shares no second", str(caught.exception))


class SeriesForSizedistKeepsTheProbeAxis(unittest.TestCase):
    """(vii) The S4 series keeps the probe's own time axis; a missing second takes the default."""

    def test_axis_is_the_probes_and_missing_seconds_take_the_default(self):
        policy = TasPolicy()
        probe_t = np.array([80000.5, 80001.2, 80002.9, 80004.0])
        aircraft_t = np.array([80000, 80001, 80002], dtype=np.int64)
        aircraft_v = np.array([100.0, 101.0, 999.0])  # 999 is above the default cutoff
        t, tas, missing = tas_sources.series_for_sizedist(probe_t, aircraft_t, aircraft_v, policy)
        np.testing.assert_array_equal(t, np.floor(probe_t))
        np.testing.assert_allclose(tas, [100.0, 101.0, 170.0, 170.0])
        self.assertEqual(missing, [80002, 80004])


class Soda2PthRoundTrips(unittest.TestCase):
    """(viii) ``write_soda2_pth_csv`` round-trips through ``read_pth_ascii``."""

    def test_round_trip(self):
        d = Path(tempfile.mkdtemp())
        path = d / "op.pth.csv"
        time_hhmmss = [80000.0, 80001.0, 80002.0, 80003.0, 80004.0]
        tas_mps = [100.0, 101.0, 102.0, 103.0, 104.5]
        tas_sources.write_soda2_pth_csv(path, time_hhmmss, tas_mps)
        starttime = 8 * 3600.0
        out = read_pth_ascii(path, starttime, 1.0, 5)
        np.testing.assert_allclose(out, np.asarray(tas_mps, dtype=np.float32), rtol=1e-5)


if __name__ == "__main__":
    unittest.main()
