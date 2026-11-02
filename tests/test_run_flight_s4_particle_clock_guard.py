# SPDX-License-Identifier: BSD-3-Clause
"""S4 refuses a proc whose particle clock misses the TAS time axis.

2026-10-04: the batch
driver ran S4 on a CIP proc whose ``particle_time`` was still on the raw probe clock (never
shifted +24,570 s to UTC), and sizeDist wrote an all-empty sd with exit 0. The driver now checks
before S4 and refuses, naming the probable cause and the fix. Pins: the check fires on a proc
whose times miss the axis, stays silent on one whose times land on it, honours the run's
``--time-offset-s`` the way the engine applies it, and reads ``particle_time`` for probetype 1
and ``Time`` otherwise. Driver-level only: it computes nothing sizeDist uses.
"""

from __future__ import annotations

import importlib.util
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


def _proc(name: str, insec: np.ndarray) -> Path:
    """A minimal proc: one particle-time variable, HHMMSS with a sub-second fraction."""
    path = Path(tempfile.mkdtemp()) / "proc.cdf"
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
        nc.createDimension("pos", insec.size)
        v = nc.createVariable(name, "f8", ("pos",))
        v[:] = _hhmmss(insec).astype(np.float64) + 0.25
    return path


# A UTC axis of 08:00:00-08:59:59 and particles on the raw probe clock, 24,570 s behind it.
_AXIS_INSEC = np.arange(8 * 3600, 9 * 3600)
_AXIS = _hhmmss(_AXIS_INSEC).astype(np.float64)
_ON = np.repeat(_AXIS_INSEC[::3], 5)
_OFF = _ON - 24_570


class ParticleClockGuard(unittest.TestCase):

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        run_flight.TIME_OFFSET = None

    def test_fires_when_particle_times_miss_the_axis(self):
        run_flight.PROBE = "CIP"
        why = run_flight._s4_particle_clock_problem(_proc("particle_time", _OFF), _AXIS)
        self.assertIsNotNone(why)
        self.assertIn("0 of", why)
        self.assertIn("never shifted", why)
        self.assertIn("--time-offset-s", why)

    def test_silent_when_particle_times_land_on_the_axis(self):
        run_flight.PROBE = "CIP"
        self.assertIsNone(
            run_flight._s4_particle_clock_problem(_proc("particle_time", _ON), _AXIS))

    def test_the_runs_time_offset_is_applied_as_the_engine_applies_it(self):
        run_flight.PROBE = "CIP"
        run_flight.TIME_OFFSET = (24_570, "measured lag", "aircraft")
        self.assertIsNone(
            run_flight._s4_particle_clock_problem(_proc("particle_time", _OFF), _AXIS))

    def test_probetype_2_reads_Time(self):
        run_flight.PROBE = "2DS"
        self.assertIsNotNone(run_flight._s4_particle_clock_problem(_proc("Time", _OFF), _AXIS))
        self.assertIsNone(run_flight._s4_particle_clock_problem(_proc("Time", _ON), _AXIS))
        # The probetype-1 variable is not what a probetype-2 run reads: left to sizeDist.
        self.assertIsNone(
            run_flight._s4_particle_clock_problem(_proc("particle_time", _OFF), _AXIS))

    def test_a_proc_with_no_particles_is_left_to_sizedist(self):
        run_flight.PROBE = "CIP"
        empty = np.array([], dtype=np.int64)
        self.assertIsNone(
            run_flight._s4_particle_clock_problem(_proc("particle_time", empty), _AXIS))

    def test_the_refusal_is_an_unverifiable_provenance_raised_by_stage4(self):
        self.assertTrue(issubclass(run_flight.ParticleClockOffAxis,
                                   run_flight.UnverifiableProvenance))
        import inspect
        src = inspect.getsource(run_flight.stage4)
        self.assertIn("_s4_particle_clock_problem(", src)
        self.assertIn("raise ParticleClockOffAxis(", src)


if __name__ == "__main__":
    unittest.main()
