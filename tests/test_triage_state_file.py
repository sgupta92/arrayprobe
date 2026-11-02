# SPDX-License-Identifier: BSD-3-Clause
"""The triage page's state-variable file: chosen by content, refused when ambiguous."""
import tempfile
import unittest
from pathlib import Path

import netCDF4

from arrayprobe.triage_context import StateFile, StateFileError
from arrayprobe.triage_server import choose_met


def _write(path, temps: dict, time_units="seconds since 2018-01-24 00:00:00"):
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", 3)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = time_units
        t[:] = [3600.0, 3601.0, 3602.0]
        for name, (units, attrs, vals) in temps.items():
            v = ds.createVariable(name, "f8", ("time",))
            v.units = units
            for k, a in attrs.items():
                setattr(v, k, a)
            v[:] = vals


class TestStateFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_standard_name_wins_over_other_temperatures(self):
        p = self.d / "a.nc"
        _write(p, {"T_xyz": ("K", {"standard_name": "air_temperature"}, [270.15, 271.15, 272.15]),
                   "Dew_Point": ("degC", {}, [-10.0, -10.0, -10.0]),
                   "Total_Air_Temp": ("degC", {}, [5.0, 5.0, 5.0])})
        sf = StateFile(p)
        self.assertEqual(sf.VARIABLE, "T_xyz")
        deg, name = sf.temperature_at(20180124, 10001)
        self.assertAlmostEqual(deg, -2.0)
        self.assertEqual(name, "a.nc")
        self.assertIsNone(sf.temperature_at(20180125, 10001))

    def test_long_name_static_is_picked(self):
        p = self.d / "b.nc"
        _write(p, {"sat": ("C", {"long_name": "Static air temperature"}, [1.0, 2.0, 3.0]),
                   "Potential_Temp": ("K", {}, [300.0, 300.0, 300.0])})
        self.assertEqual(StateFile(p).VARIABLE, "sat")

    def test_ambiguous_file_is_refused_listing_candidates(self):
        p = self.d / "c.nc"
        _write(p, {"temp_a": ("degC", {}, [1.0, 2.0, 3.0]),
                   "temp_b": ("degC", {}, [1.0, 2.0, 3.0])})
        with self.assertRaises(StateFileError) as cm:
            StateFile(p)
        self.assertIn("temp_a", str(cm.exception))
        self.assertIn("temp_b", str(cm.exception))
        self.assertEqual(StateFile(p, "temp_b").VARIABLE, "temp_b")

    def test_flag_overrides_met_dir(self):
        p = self.d / "d.nc"
        _write(p, {"ambient_temp": ("degC", {}, [1.0, 2.0, 3.0])})
        self.assertIsInstance(choose_met(self.d, p, None), StateFile)
        self.assertNotIsInstance(choose_met(self.d, None, None), StateFile)
        self.assertIsNone(choose_met(None, None, None))
        with self.assertRaises(StateFileError):
            choose_met(None, None, "x")

    def test_index_names_the_loaded_file_and_variable(self):
        from arrayprobe.triage_server import TriageServer

        p = self.d / "e&f.nc"
        _write(p, {"ambient_temp": ("degC", {}, [1.0, 2.0, 3.0])})

        class _Page:
            _state_file_panel = TriageServer._state_file_panel
            met = None

        page = _Page()
        before = page._state_file_panel()
        self.assertNotIn("loaded:", before)
        self.assertIn("state-file-form", before)
        page.met = StateFile(p)
        after = page._state_file_panel()
        self.assertIn("State-variable file loaded: e&amp;f.nc, ambient_temp", after)
        self.assertNotIn("state-file-form", after)


if __name__ == "__main__":
    unittest.main()
