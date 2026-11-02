# SPDX-License-Identifier: BSD-3-Clause
"""On engine 3.5, by default, S4 derives a raw probe clock's offset from the proc and applies it.

A CIP proc's ``particle_time`` on the raw probe clock (+24,570 s off UTC on 2016-09-06) makes
sizeDist write an all-empty sd. Where the guard (test_run_flight_s4_particle_clock_guard) would
refuse, engine 3.5 derives the offset as the mode of ``Time - particle_time`` and applies it only
if >= 99 % of particles then land on the TAS axis; ``--protective off`` and engine 3.1.4 refuse.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from tests import _run_flight_state

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_flight", _ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = sys.modules.setdefault(_spec.name, importlib.util.module_from_spec(_spec))
if not hasattr(run_flight, "stage4"):
    _spec.loader.exec_module(run_flight)


def _hhmmss(insec: np.ndarray) -> np.ndarray:
    insec = np.mod(insec, 86400)
    return (insec // 3600) * 10000 + (insec % 3600) // 60 * 100 + insec % 60


def _proc(pt_insec: np.ndarray, rec_insec: np.ndarray) -> Path:
    path = Path(tempfile.mkdtemp()) / "proc.cdf"
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
        nc.createDimension("pos", pt_insec.size)
        nc.createVariable("particle_time", "f8", ("pos",))[:] = _hhmmss(pt_insec) + 0.25
        nc.createVariable("Time", "f8", ("pos",))[:] = _hhmmss(rec_insec) + 0.0
    return path


_AXIS_INSEC = np.arange(8 * 3600, 9 * 3600)
_AXIS = _hhmmss(_AXIS_INSEC).astype(np.float64)
_ON = np.repeat(_AXIS_INSEC[::3], 5)
_OFF = _ON - 24_570


class ParticleClockFix(unittest.TestCase):

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        run_flight.TIME_OFFSET = None
        run_flight.PROBE = "CIP"
        run_flight.ENGINE = "3.5"
        run_flight.PROTECTIVE_MODE = "auto"

    def test_offset_is_derived_and_lands_the_particles_on_the_axis(self):
        proc = _proc(_OFF, _ON)
        self.assertIsNotNone(run_flight._s4_particle_clock_problem(proc, _AXIS))
        fix = run_flight._s4_derive_particle_clock_fix(proc, _AXIS)
        self.assertIsNotNone(fix)
        seconds, evidence = fix
        self.assertEqual(seconds, 24_570)
        self.assertIn("100.00 % on the TAS axis", evidence)
        run_flight.TIME_OFFSET = (seconds, evidence, "aircraft")
        self.assertIsNone(run_flight._s4_particle_clock_problem(proc, _AXIS))

    def test_ambiguous_offset_is_refused(self):
        rng = np.random.default_rng(0)
        noisy = _ON + rng.integers(-4000, 4000, _ON.size)   # no single offset dominates
        self.assertIsNone(run_flight._s4_derive_particle_clock_fix(_proc(_OFF, noisy), _AXIS))

    def test_offset_that_misses_the_axis_is_refused(self):
        # A consistent mode, but Time itself is off the axis: shifting still misses it.
        self.assertIsNone(
            run_flight._s4_derive_particle_clock_fix(_proc(_OFF, _ON + 7200), _AXIS))

    def test_opt_out_and_engine_314_keep_refusing(self):
        self.assertTrue(run_flight._particle_clock_fix_allowed())
        run_flight.PROTECTIVE_MODE = "off"
        self.assertFalse(run_flight._particle_clock_fix_allowed())
        run_flight.PROTECTIVE_MODE = "auto"
        run_flight.ENGINE = "3.1.4"
        self.assertFalse(run_flight._particle_clock_fix_allowed())

    def test_probetype_2_derives_nothing(self):
        run_flight.PROBE = "2DS"
        self.assertIsNone(run_flight._s4_derive_particle_clock_fix(_proc(_OFF, _ON), _AXIS))

    def test_on_axis_proc_needs_no_fix_and_stamp_strip_is_exact(self):
        self.assertIsNone(run_flight._s4_particle_clock_problem(_proc(_ON, _ON), _AXIS))
        stamp = "engine=3.5 iat_file=x protective=off"
        self.assertEqual(
            run_flight._strip_particle_clock_fix(stamp + " particle_clock_fix=+24570s"), stamp)
        self.assertEqual(run_flight._strip_particle_clock_fix(stamp), stamp)

    def test_stage4_wires_the_fix_through_the_time_offset_path(self):
        src = inspect.getsource(run_flight.stage4)
        self.assertIn("_s4_derive_particle_clock_fix(", src)
        self.assertIn("_particle_clock_fix_allowed()", src)
        self.assertIn("PARTICLE_CLOCK_FIX_KEY", src)
        self.assertIn("TIME_OFFSET = saved_offset", src)



class Stage4AppliesTheFix(unittest.TestCase):
    """stage4 end to end, sizeDist stubbed: the offset reaches the call and the stamp."""

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        run_flight.TIME_OFFSET = None
        run_flight.PROBE = "CIP"
        run_flight.ENGINE = "3.5"
        run_flight.PROTECTIVE_MODE = "auto"
        self.seen: list = []

        def fake_sizedist(proc_file, out_file, *args, **kwargs):
            self.seen.append(run_flight.TIME_OFFSET)
            Path(out_file).write_bytes(b"sd")
            return ""  # _sizedist_call returns the stamp's count fragment

        for name, value in (("_sizedist_call", fake_sizedist),
                            ("load_tas_info", lambda _csv: (_AXIS, np.full(_AXIS.size, 100.0))),
                            ("tas_grid_fix_on", lambda: False),
                            ("_store_tas_qc", lambda *a, **k: None),
                            # The fake sd is not a netCDF, so the post-S4 plausibility gate
                            # (tested in test_s4_plausibility_gate) passes the stamp through.
                            ("_s4_plausibility_gate", lambda _t, _p, want: (want, None)),
                            ("log", lambda *a, **k: None)):
            self._patch(name, value)

    def _patch(self, name, value):
        old = getattr(run_flight, name)
        setattr(run_flight, name, value)
        self.addCleanup(setattr, run_flight, name, old)

    def _run(self, pt, rec):
        out = Path(tempfile.mkdtemp())
        proc = out / "proc.base1.nc"
        _proc(pt, rec).replace(proc)
        run_flight.write_stamp(proc, run_flight.proc_call_label())
        (out / "base1.tas.csv").write_text("x")
        sd = run_flight.stage4(proc, "base1", out, iat_file=None)
        return sd, run_flight.read_stamp(sd)

    def test_offset_is_applied_for_the_call_and_stamped(self):
        sd, stamp = self._run(_OFF, _ON)
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.seen[0][0], 24_570)
        self.assertEqual(self.seen[0][2], "aircraft")
        self.assertIsNone(run_flight.TIME_OFFSET)          # restored after the call
        self.assertIn("particle_clock_fix=+24570s", stamp)
        # A re-run finds the stamped sd current rather than redoing it.
        self.seen.clear()
        run_flight.stage4(sd.with_name("proc.base1.nc"), "base1", sd.parent, iat_file=None)
        self.assertEqual(self.seen, [])

    def test_ambiguous_offset_refuses(self):
        rng = np.random.default_rng(0)
        with self.assertRaises(run_flight.ParticleClockOffAxis):
            self._run(_OFF, _ON + rng.integers(-4000, 4000, _ON.size))
        self.assertEqual(self.seen, [])

    def test_protective_off_refuses(self):
        run_flight.PROTECTIVE_MODE = "off"
        with self.assertRaises(run_flight.ParticleClockOffAxis):
            self._run(_OFF, _ON)
        self.assertEqual(self.seen, [])

    def test_engine_314_refuses_unchanged(self):
        run_flight.ENGINE = "3.1.4"
        with self.assertRaises(run_flight.ParticleClockOffAxis):
            self._run(_OFF, _ON)
        self.assertEqual(self.seen, [])

    def test_on_axis_proc_is_unchanged(self):
        _sd, stamp = self._run(_ON, _ON)
        self.assertEqual(self.seen, [None])
        self.assertNotIn("particle_clock_fix", stamp)
        self.assertEqual(stamp, run_flight.sd_call_label(None))


if __name__ == "__main__":
    unittest.main()


class TheClockFixDoesNotMakeItsOwnSdStale(unittest.TestCase):
    """2026-10-05 00:09, CIP 2016-09-06: S4 applied +24570 s, wrote a non-empty sd, then its own
    post-write currency check called the sd not current and the run FAILED, because the written
    stamp carries ``particle_clock_fix=`` and the configured want cannot."""

    def test_a_stamp_differing_only_by_the_derived_offset_is_equivalent(self):
        from arrayprobe.driver import run_flight
        want = "engine=3.5 iat_file=<none> profile=oracles-production-v3.5 time_sv_fix=on"
        got = want + " particle_clock_fix=+24570s"
        self.assertTrue(run_flight._stamps_equivalent(got, want))

    def test_a_different_configuration_is_still_not_equivalent(self):
        from arrayprobe.driver import run_flight
        want = "engine=3.5 iat_file=<none> profile=oracles-production-v3.5 time_sv_fix=on"
        got = ("engine=3.5 iat_file=<none> profile=stock-v3.5 time_sv_fix=on"
               " particle_clock_fix=+24570s")
        self.assertFalse(run_flight._stamps_equivalent(got, want))
