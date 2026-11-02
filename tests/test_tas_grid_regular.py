# SPDX-License-Identifier: BSD-3-Clause
"""``--tas-grid regular``: the size-distribution stage on a regular one-second time vector.

**The loss.** ``sizeDist`` walks its time vector one row at a time and consumes one particle
block per row (v3.5 ``sizeDist.m:913-927``; v3.1.4 ``:741-754``). A second the vector repeats
gets an empty window on its first copy and no block on its second; a second the vector skips
has its block stepped over. Either way that second's particles are counted nowhere. Unmodified
v3.5 ``sizeDist.m`` does this under Octave on the tracked two-block fixture:
5 particles binned at
16:41:29 on ``[164128; 164129; 164130]``, none on ``[164128; 164130]`` or
``[164129; 164129; 164130]``; the port agrees row for row. The same fixture is the engine
test below.

**Where the driver meets it.** Under a TAS source chain, S4 keeps the probe's own
``<stem>.tas.csv`` seconds and swaps only the values; that axis repeats and skips seconds
(ARM 2017-07-04: 132 repeats, 117 two-second steps), so 4.4-8.5 % of particles on the five ARM
2017 flights are never counted. ``--tas-grid regular`` hands ``sizeDist`` every second of the
probe's span once instead, valued from the chain. Off by default; these tests hold both states:

* off: the stamp, the vector and the sd file are what they were, and the loss is there;
* on: the vector is regular, the stamp says ``tas_grid=regular``, and the loss is gone.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np
from tests import _run_flight_state
from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe.tools import tas_sources
from arrayprobe.tools.make_tas_file import TasPolicy
from arrayprobe_uiops import sizedist as v35s

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
DATA = Path(__file__).resolve().parent / "data"
BASE = DATA / "stock_div_base_proc.nc"   # 16 particles at 16:41:29, 83 at 16:41:30

_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules.setdefault("make_demo_flight", make_demo_flight)
_DEMO_SPEC.loader.exec_module(make_demo_flight)

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
run_flight = None


def setUpModule():
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)


def _row_counts(path: Path) -> list:
    """Each time row's binned count, ``None`` for an all-NaN row."""
    with netCDF4.Dataset(path) as d:
        d.set_auto_mask(False)
        c = np.asarray(d.variables["count"][:], float)
        n = np.asarray(d.variables["time"][:]).size
    if c.shape[0] != n:
        c = c.T
    return [None if np.isnan(r).all() else int(np.nansum(r)) for r in c]


class RegularGrid(unittest.TestCase):
    """:func:`tas_sources.regular_grid_hhmmss`: every second of the span, once."""

    def test_repeats_and_skips_become_one_row_per_second(self):
        probe = np.array([91808.2, 91809.0, 91809.7, 91811.1, 91812.0, 91814.5])
        np.testing.assert_array_equal(
            tas_sources.regular_grid_hhmmss(probe),
            [91808, 91809, 91810, 91811, 91812, 91813, 91814])

    def test_minute_and_hour_boundaries(self):
        np.testing.assert_array_equal(tas_sources.regular_grid_hhmmss([95958, 100001]),
                                      [95958, 95959, 100000, 100001])

    def test_midnight_is_unwrapped_then_wrapped_back(self):
        np.testing.assert_array_equal(tas_sources.regular_grid_hhmmss([235958, 0, 2]),
                                      [235958, 235959, 0, 1, 2])

    def test_a_regular_axis_is_returned_unchanged(self):
        probe = np.array([120000.0, 120001.0, 120002.0])
        np.testing.assert_array_equal(tas_sources.regular_grid_hhmmss(probe), probe)

    def test_values_come_from_the_aircraft_series_and_a_gap_takes_the_default(self):
        policy = TasPolicy()
        t, tas, missing = tas_sources.regular_series_for_sizedist(
            [80000.0, 80000.4, 80003.0], np.array([80000, 80001, 80003]),
            np.array([100.0, 101.0, 103.0]), policy)
        np.testing.assert_array_equal(t, [80000, 80001, 80002, 80003])
        np.testing.assert_allclose(tas, [100.0, 101.0, policy.default_mps, 103.0])
        self.assertEqual(missing, [80002])


@unittest.skipUnless(BASE.is_file(), "Fixture stock_div_base_proc.nc is not distributed with "
                                     "the package; the test needs files that are not part of this "
                                     "release")
class EngineLosesTheSecondOnAnIrregularVectorOnly(unittest.TestCase):
    """The v3.5 engine on the fixture Octave ran: the per-row counts are Octave's own
    (``time_grid_octave_repro.py``, all four vectors agreeing with the port)."""

    def _run(self, grid):
        out = Path(tempfile.mkdtemp()) / "sd.nc"
        n = len(grid)
        v35s.run(str(BASE), str(out), np.full(n, 95.0), np.asarray(grid, float), "2DS", 6, 0,
                 np.full(n, 9e5), np.full(n, 15.0), 0, 0, 1, 1, "TEST", "20151205 164129",
                 software="test", octave_colon=True, creation_time="x")
        return _row_counts(out)

    def test_skipped_second_is_lost(self):
        self.assertEqual(self._run([164128, 164130]), [None, 47])

    def test_repeated_second_is_lost(self):
        self.assertEqual(self._run([164129, 164129, 164130]), [0, None, 47])

    def test_the_regular_grid_of_either_counts_it(self):
        for probe in ([164128, 164130], [164129, 164129, 164130]):
            grid, _tas, _m = tas_sources.regular_series_for_sizedist(
                probe, np.array([164128, 164129, 164130]), np.full(3, 95.0), TasPolicy())
            got = self._run(list(grid))
            self.assertEqual(got[-2:], [5, 47], f"probe axis {probe}")


class _Driver(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)

    def _flight(self):
        """A four-second demo flight through S2-S3, then its ``.tas.csv`` rewritten so
        06:06:40 appears twice and 06:06:41 not at all -- the two shapes ARM's axis has."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        raw = out / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=4)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main(["--engine", "3.1.4", "--port-validation",
                                  "--preset", "DEMO_2DS_H", "--stages",
                                  "23", "--yes", "--out", str(out), str(raw)])
        self.assertEqual(rc, 0, buf.getvalue())
        csv = out / f"{raw.stem}.tas.csv"
        rows = [r for r in csv.read_text().splitlines() if r.strip()]
        self.assertTrue(rows[0].startswith("60640.") and rows[2].startswith("60642."), rows)
        csv.write_text("\n".join([rows[0], rows[0].replace("60640.25", "60640.75"), rows[2]])
                       + "\n")
        proc = out / f"proc.{raw.stem}.H.nc"
        chain = tas_sources.ChainResult(
            mode="aircraft", tier="aircraft", source="arm-aaf-merged",
            path=str(out / "aircraft.nc"), time=np.array([60639.0, 60640.0, 60641.0, 60642.0,
                                                          60643.0]),
            tas=np.full(5, 130.0), policy=TasPolicy(), steps=[], substituted=[], lines=[],
            provenance={})
        return out, raw, proc, chain

    def _stage4(self, out, raw, proc, chain, grid, mocked=False):
        run_flight.TAS_CHAIN = chain
        run_flight.TAS_POLICY = chain.policy
        run_flight.TAS_GRID = grid
        buf = io.StringIO()
        if mocked:
            with mock.patch.object(run_flight.sizedist, "run") as m, redirect_stdout(buf):
                m.side_effect = lambda *a, **kw: Path(a[1]).write_bytes(b"")
                run_flight.stage4(proc, raw.stem, out, run_flight.IAT_FILE)
            return m.call_args, buf.getvalue()
        with redirect_stdout(buf):
            target = run_flight.stage4(proc, raw.stem, out, run_flight.IAT_FILE)
        return target, buf.getvalue()


class DriverOffKeepsTheProbeAxisAndTheLoss(_Driver):

    @needs_v314_engine
    def test_default_is_probe_and_the_stamp_has_no_grid_key(self):
        self.assertEqual(run_flight.TAS_GRID, "probe")
        out, raw, proc, chain = self._flight()
        run_flight.TAS_CHAIN = chain
        self.assertNotIn("tas_grid", run_flight.sd_call_label(run_flight.IAT_FILE))

    @needs_v314_engine
    def test_sizedist_gets_the_probe_axis(self):
        out, raw, proc, chain = self._flight()
        call, _log = self._stage4(out, raw, proc, chain, "probe", mocked=True)
        np.testing.assert_array_equal(call.args[3], [60640, 60640, 60642])

    @needs_v314_engine
    def test_the_repeated_and_skipped_seconds_are_not_counted(self):
        out, raw, proc, chain = self._flight()
        target, log = self._stage4(out, raw, proc, chain, "probe")
        self.assertTrue(target.exists(), log)
        counts = _row_counts(target)
        self.assertEqual(len(counts), 3)
        self.assertEqual(counts[:2], [0, None], counts)


class DriverOnRegularisesTheAxis(_Driver):

    @needs_v314_engine
    def test_sizedist_gets_every_second_once(self):
        out, raw, proc, chain = self._flight()
        call, log = self._stage4(out, raw, proc, chain, "regular", mocked=True)
        np.testing.assert_array_equal(call.args[3], [60640, 60641, 60642])
        np.testing.assert_array_equal(call.args[2], [130.0, 130.0, 130.0])
        self.assertIn("1 repeated, 1 absent", log)

    @needs_v314_engine
    def test_the_stamp_names_the_grid(self):
        out, raw, proc, chain = self._flight()
        run_flight.TAS_CHAIN = chain
        run_flight.TAS_GRID = "regular"
        self.assertIn(" tas_grid=regular", run_flight.sd_call_label(run_flight.IAT_FILE))

    @needs_v314_engine
    def test_no_row_is_left_empty_or_nan(self):
        out, raw, proc, chain = self._flight()
        on, log = self._stage4(out, raw, proc, chain, "regular")
        self.assertTrue(on.exists(), log)
        on_counts = _row_counts(on)
        self.assertEqual(len(on_counts), 3)
        self.assertNotIn(None, on_counts)


@unittest.skipUnless(BASE.is_file(), "Fixture stock_div_base_proc.nc is not distributed with "
                                     "the package; the test needs files that are not part of this "
                                     "release")
class DriverStage4OnTheOctaveFixture(_Driver):
    """``stage4`` under engine 3.5 on the fixture Octave ran, its ``.tas.csv`` skipping 16:41:29:
    off, that second's particles are counted nowhere; on, they are binned in their own row.
    (The demo flight above has particles, but ``sizeDist`` accepts none of them, so its
    counts cannot show a particle recovered.)"""

    def _setup(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        stem = "base151205164128"
        proc = out / f"proc.{stem}.H.nc"
        proc.write_bytes(BASE.read_bytes())
        (out / f"{stem}.tas.csv").write_text("164128.500000, 95.0\n164130.500000, 95.0\n")
        chain = tas_sources.ChainResult(
            mode="aircraft", tier="aircraft", source="arm-aaf-merged",
            path=str(out / "aircraft.nc"), time=np.array([164128.0, 164129.0, 164130.0]),
            tas=np.full(3, 95.0), policy=TasPolicy(), steps=[], substituted=[], lines=[],
            provenance={})
        from arrayprobe.profiles import PROFILES
        run_flight.ENGINE = "3.5"
        run_flight.PROFILE = PROFILES["stock-v3.5"]
        return out, stem, proc, chain

    def _sd(self, out, stem, proc, chain, grid):
        run_flight.TAS_CHAIN = chain
        run_flight.TAS_POLICY = chain.policy
        run_flight.TAS_GRID = grid
        buf = io.StringIO()
        with redirect_stdout(buf):
            target = run_flight.stage4(proc, stem, out, None, accept_unstamped=True)
        self.assertTrue(target.exists(), buf.getvalue())
        with netCDF4.Dataset(target) as d:
            t = np.asarray(d.variables["time"][:]).astype(int).tolist()
        return dict(zip(t, _row_counts(target), strict=True)), buf.getvalue()

    def test_off_loses_the_skipped_second_on_counts_it(self):
        out, stem, proc, chain = self._setup()
        off, _ = self._sd(out, stem, proc, chain, "probe")
        self.assertNotIn(164129, off)
        on, log = self._sd(out, stem, proc, chain, "regular")
        self.assertIn("S4 redo", log)   # the stamp changed, so the probe-grid sd is rebuilt
        self.assertEqual(sorted(on), [164128, 164129, 164130])
        self.assertGreater(on[164129], 0)
        self.assertEqual(on[164130], off[164130])

    @needs_v314_engine
    def test_enhanced_sizedist_gets_the_same_vector(self):
        out, raw, proc, chain = self._flight()
        run_flight.TAS_CHAIN = chain
        run_flight.TAS_POLICY = chain.policy
        run_flight.TAS_GRID = "regular"
        stages = run_flight.EnhancedStages(out, run_flight.IAT_FILE)
        with mock.patch.object(run_flight.sizedist, "run") as m, redirect_stdout(io.StringIO()):
            m.side_effect = lambda *a, **kw: Path(a[1]).write_bytes(b"")
            stages.sizedist(proc, raw.stem, out / f"{raw.stem}.enh.sd.nc")
        np.testing.assert_array_equal(m.call_args.args[3], [60640, 60641, 60642])


class DriverRefusesRegularWithoutAChain(_Driver):

    @needs_v314_engine
    def test_exit_2_without_tas_source(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "base160101000000.2DS"
            make_demo_flight.build_demo_flight(raw, n_seconds=2)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_flight.main(["--engine", "3.1.4", "--port-validation",
                                      "--preset", "DEMO_2DS_H", "--stages",
                                      "4", "--yes", "--tas-grid", "regular", "--out", d,
                                      str(raw)])
        self.assertEqual(rc, 2, buf.getvalue())
        self.assertIn("--tas-grid regular needs --tas-source", buf.getvalue())

# _release_fixture_guard: real-data derived fixtures are excluded from the release
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402

_RFG_EXCLUDED = ('stock_div_base_proc.nc',)
if not all((_rfg_pathlib.Path(__file__).resolve().parent / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "needs the archived UIOPS v3.1.4 engine and sample files from real field-campaign "
        "data, which this release does not include")

if __name__ == "__main__":
    unittest.main()
