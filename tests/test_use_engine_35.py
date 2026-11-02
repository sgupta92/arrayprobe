# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.use_engine_35`` sets what the v3.5 notebooks set by hand."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from tests import _run_flight_state

_SPEC = importlib.util.spec_from_file_location(
    "run_flight", Path(__file__).resolve().parent.parent / "scripts" / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)


class UseEngine35(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)

    def test_sets_engine_profile_and_a_readable_tas_file(self):
        import netCDF4

        from arrayprobe.profiles import STOCK_V35
        with tempfile.TemporaryDirectory() as d:
            got = run_flight.use_engine_35(d, tas_mps=120.0)
            self.assertEqual(run_flight.ENGINE, "3.5")
            self.assertIs(run_flight.PROFILE, STOCK_V35)
            self.assertEqual(run_flight.TAS_FILE, got)
            with netCDF4.Dataset(got) as ds:
                self.assertEqual(ds["Time"][0], 0.0)
                self.assertEqual(ds["Time"][-1], 235959.0)
                self.assertEqual(float(ds["TAS"][:].min()), 120.0)

    def test_a_given_tas_file_is_used_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            run_flight.use_engine_35(d, tas_file="x.cdf")
            self.assertEqual(run_flight.TAS_FILE, "x.cdf")
            self.assertFalse((Path(d) / "aircraft.cdf").exists())

    def test_the_module_defaults_are_unchanged(self):
        self.assertEqual(run_flight.ENGINE, "3.1.4")


if __name__ == "__main__":
    unittest.main()
