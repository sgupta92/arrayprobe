# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight._aircraft_series`` refuses an aircraft axis the exact-match lookup cannot use.

Added 2026-09-23. ARM's merged file carries ``time`` as seconds since ``base_time``;
passed through unchanged it never equals a record's HHMMSS at ``imgProc_sm.m:727``, and every
particle of the ARM ENA v3.5 product silently ran at the 170 m/s fallback (measured).
These tests make the reader
convert that axis, drop the author's excluded speeds, and fail closed on anything else.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_flight  # noqa: E402


def _arm_file(path: Path, base: float, t, tas) -> Path:
    with netCDF4.Dataset(str(path), "w") as ds:
        ds.createDimension("time", len(t))
        ds.createVariable("base_time", "f8")[...] = base
        ds.createVariable("time", "f8", ("time",))[:] = t
        v = ds.createVariable("true_airspeed", "f4", ("time",))
        v.units = "m/s"      # as the real ARM file carries it (read 2026-09-23)
        v[:] = tas
    return path


def _uiops_file(path: Path, t, tas) -> Path:
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", len(t))
        ds.createVariable("Time", "f8", ("time",))[:] = t
        ds.createVariable("TAS", "f8", ("time",))[:] = tas
    return path


class TheArmAxisIsConvertedAndChecked(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self._saved = run_flight.TAS_FILE

    def tearDown(self):
        run_flight.TAS_FILE = self._saved

    def _read(self, path):
        run_flight.TAS_FILE = str(path)
        return run_flight._aircraft_series()

    def test_seconds_since_base_time_become_utc_hhmmss(self):
        # 2017-07-06 08:23:13 UTC is base_time 1499329393 (the 07-06 ARM file's first sample).
        base = 1499329393.0
        t, tas = self._read(_arm_file(self.d / "a.nc", base, [0.0, 1.0, 47.0], [95.0, 95.5, 96.0]))
        np.testing.assert_array_equal(t, [82313.0, 82314.0, 82400.0])
        np.testing.assert_allclose(tas, [95.0, 95.5, 96.0])

    def test_nonpositive_and_out_of_range_speeds_take_the_default_never_dropped(self):
        """ORACLES merged airspeed: every second kept; values fall to TAS_POLICY.default_mps."""
        base = 1499329393.0
        path = _arm_file(self.d / "b.nc", base, [0.0, 1.0, 2.0, 3.0], [-999.0, 95.0, 400.0, 0.0])
        t, tas = self._read(path)
        np.testing.assert_array_equal(t, [82313.0, 82314.0, 82315.0, 82316.0])
        np.testing.assert_allclose(tas, [170.0, 95.0, 170.0, 170.0])
        saved = run_flight.TAS_POLICY
        try:
            run_flight.TAS_POLICY = run_flight._mtf.TasPolicy(350.0, 120.0)
            _, tas = self._read(path)
            np.testing.assert_allclose(tas, [120.0, 95.0, 120.0, 120.0])
        finally:
            run_flight.TAS_POLICY = saved

    def test_an_arm_time_axis_without_base_time_is_refused_clearly(self):
        with netCDF4.Dataset(str(self.d / "nb.nc"), "w") as ds:
            ds.createDimension("time", 2)
            ds.createVariable("time", "f8", ("time",))[:] = [0.0, 1.0]
            v = ds.createVariable("true_airspeed", "f4", ("time",))
            v.units = "m/s"
            v[:] = [95.0, 96.0]
        with self.assertRaises(ValueError) as caught:
            self._read(self.d / "nb.nc")
        self.assertIn("no base_time", str(caught.exception))

    def test_a_uiops_file_with_fractional_time_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._read(_uiops_file(self.d / "c.cdf", [124834.999, 124835.999], [139.9, 139.4]))
        self.assertIn("not whole seconds", str(caught.exception))

    def test_a_uiops_file_whose_axis_is_not_a_clock_is_refused(self):
        # 12888 s since take-off reads as 01:28:88 -- not a clock time.
        with self.assertRaises(ValueError) as caught:
            self._read(_uiops_file(self.d / "d.cdf", [12887.0, 12888.0], [95.0, 95.0]))
        self.assertIn("not a clock time HHMMSS", str(caught.exception))

    def test_a_whole_second_uiops_file_passes_unchanged(self):
        t, tas = self._read(_uiops_file(self.d / "e.cdf", [60638.0, 60639.0], [130.0, 131.0]))
        np.testing.assert_array_equal(t, [60638.0, 60639.0])
        np.testing.assert_allclose(tas, [130.0, 131.0])


if __name__ == "__main__":
    unittest.main()
