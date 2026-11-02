# SPDX-License-Identifier: BSD-3-Clause
"""``[shattering].ia_thresh_type = 2``: the opt-in way a run selects v3.5's type-2 shattering test.

Engine 3.5 runs ``sizeDist`` with ``iaThreshType`` 1 when a threshold file is named and 0
otherwise, and type 0 runs no shattering test whatever the probe case's gate says. Type 2
(``sizeDist.m:1346``) compares each inter-arrival time against the probe case's
``defaultIntArrThresh``, so a gate-on case such as ``arm-ena-2ds-cold`` acts only under it.

Pinned here: the config accepts only 2 and refuses it beside a threshold file; the driver refuses
it under engine 3.1.4 (whose call takes no ``iaThreshType``); with nothing chosen the driver's call
and its ``.call`` stamp are unchanged; choosing 2 is stamped and, on a synthetic fixture whose
inter-arrival gaps straddle the cold case's threshold, changes the output under the cold case.
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np
from tests import _run_flight_state
from tests.test_run_flight_config import _Args, _toml, run_flight

from arrayprobe.config import ConfigError, load_config

BASE = '[fidelity]\nprofile = "ORACLES_PRODUCTION"\n'

PROC = Path(__file__).resolve().parent / "data" / "demo_flight_v35_proc.nc"

#: Gaps either side of the cold case's 1e-6 s threshold, both under 4e-6 s. One short gap in
#: four, so some particles have only 2e-6 s gaps on both sides: kept at 1e-6, cut at 4e-6.
COLD_GAPS = (5e-7, 2e-6, 2e-6, 2e-6)


def _straddling_proc(td: str) -> Path:
    """The demo proc with ``Time_in_seconds`` gaps cycling through COLD_GAPS; nothing else."""
    out = Path(td) / "straddling_proc.nc"
    shutil.copyfile(PROC, out)
    with netCDF4.Dataset(str(out), "r+") as ds:
        v = ds.variables["Time_in_seconds"]
        gaps = np.resize(np.array(COLD_GAPS), v.shape[0])
        gaps[0] = 0.0
        v[:] = 100.0 + np.cumsum(gaps)
    return out


def _same(a: dict, b: dict) -> bool:
    return set(a) == set(b) and all(np.array_equal(a[k], b[k], equal_nan=True) for k in a)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


#: The ARM ENA registration modules are development-only: a distribution may
#: ship without them, and the test that runs the cold case skips there.
_needs_arm_ena = unittest.skipUnless(
    _has_module("arrayprobe_uiops.register_arm_ena_2ds_cold"),
    "arrayprobe_uiops.register_arm_ena_2ds_cold: the ARM ENA registration module is not in "
    "this distribution",
)


class TheConfigKey(unittest.TestCase):
    def test_absent_is_none(self):
        self.assertIsNone(load_config(_toml(BASE)).shattering_ia_thresh_type)

    def test_two_is_accepted_without_a_threshold_file(self):
        cfg = load_config(_toml(BASE + "[shattering]\nia_thresh_type = 2\n"))
        self.assertEqual(cfg.shattering_ia_thresh_type, 2)
        self.assertIsNone(cfg.shattering_threshold_file)

    def test_other_values_are_refused(self):
        for bad in ("0", "1", "3", "true", '"2"'):
            with self.subTest(value=bad), self.assertRaises(ConfigError):
                load_config(_toml(BASE + f"[shattering]\nia_thresh_type = {bad}\n"))

    def test_beside_a_threshold_file_is_refused(self):
        with self.assertRaises(ConfigError):
            load_config(_toml(BASE + '[shattering]\nia_thresh_type = 2\n'
                                     'threshold_file = "x.cdf"\n'))


class TheDriver(unittest.TestCase):
    def setUp(self):
        self._masks = dict(run_flight.SHADOW_DIODE_OVERRIDES)
        _run_flight_state.preserve(self, run_flight)

    def tearDown(self):
        run_flight.SHADOW_DIODE_OVERRIDES.clear()
        run_flight.SHADOW_DIODE_OVERRIDES.update(self._masks)

    def _apply(self, text: str, engine: str, **kw):
        args = _Args(engine=engine, **kw)
        args.config = _toml(text)
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_flight._apply_config(args, None, [])
        return out, buf.getvalue()

    def test_engine_35_selects_type_2(self):
        out, log = self._apply(BASE + "[shattering]\nia_thresh_type = 2\n", "3.5")
        self.assertIsNotNone(out, log)
        self.assertEqual(run_flight.IA_THRESH_TYPE, 2)

    def test_engine_35_without_the_key_leaves_it_unset(self):
        out, log = self._apply(BASE, "3.5")
        self.assertIsNotNone(out, log)
        self.assertIsNone(run_flight.IA_THRESH_TYPE)

    def test_engine_314_refuses_it(self):
        out, log = self._apply(BASE + "[shattering]\nia_thresh_type = 2\n", "3.1.4")
        self.assertIsNone(out)
        self.assertIn("engine 3.5 only", log)
        self.assertIsNone(run_flight.IA_THRESH_TYPE)


class TheStamp(unittest.TestCase):
    def test_default_stamp_is_unchanged(self):
        call = run_flight.V35_CALL
        self.assertEqual(call.sizedist_stamp(""), call.sizedist_stamp("", None))
        self.assertIn("sizedist=(iaThreshType=0,", call.sizedist_stamp(""))
        self.assertIn("sizedist=(iaThreshType=1,", call.sizedist_stamp("f.cdf"))

    def test_sd_label_names_type_2_only_when_chosen(self):
        with mock.patch.multiple(run_flight, ENGINE="3.5", IA_THRESH_TYPE=None):
            plain = run_flight.sd_call_label("")
        with mock.patch.multiple(run_flight, ENGINE="3.5", IA_THRESH_TYPE=2):
            chosen = run_flight.sd_call_label("")
        self.assertIn("iaThreshType=0,", plain)
        self.assertEqual(chosen, plain.replace("iaThreshType=0,", "iaThreshType=2,"))


class TheGolden(unittest.TestCase):
    def test_the_demo_proc_golden_is_tracked(self):
        """TheOutput skips without this fixture; its absence fails here instead."""
        self.assertTrue(PROC.is_file(), f"{PROC} missing")


@_needs_arm_ena
@unittest.skipUnless(PROC.is_file(), f"{PROC} is not distributed with the package")
class TheOutput(unittest.TestCase):
    """The driver's own ``_sizedist_call`` on the straddling fixture, cold case."""

    @classmethod
    def setUpClass(cls):
        from arrayprobe_uiops import register_arm_ena_2ds_cold as arm_ena_2ds_cold

        arm_ena_2ds_cold.register_arm_ena_2ds_cold()

    def _call(self, td: str, tag: str, ia_thresh_type: int | None) -> dict[str, np.ndarray]:
        proc = _straddling_proc(td)
        with netCDF4.Dataset(str(proc)) as ds:
            t = np.asarray(ds.variables["Time"][:], dtype=np.float64).reshape(-1)
        timehhmmss = np.unique(np.floor(t))
        tas = np.full_like(timehhmmss, 100.0)
        out = Path(td) / f"{tag}.nc"
        with mock.patch.multiple(
                run_flight, ENGINE="3.5", IA_THRESH_TYPE=ia_thresh_type, PROBE="2DS",
                D_CHOICE=6, SA_METHOD=2, PRES_PA=85000.0, TEMP_C=-5.0, PROJECT="ARM_ENA",
                PROBE_CASE="arm-ena-2ds-cold", AREA_RATIO_Z_OVERRIDE=None,
                PROFILE=types.SimpleNamespace(name="STOCK_V35")):
            run_flight._sizedist_call(proc, out, "base170707000000", timehhmmss, tas, "")
        with netCDF4.Dataset(str(out)) as ds:
            return {k: np.ma.filled(np.asarray(v[:]).astype(float), np.nan)
                    for k, v in ds.variables.items() if k != "Creation Time"}

    def test_default_is_the_type_0_call_and_type_2_changes_the_output(self):
        with tempfile.TemporaryDirectory() as td:
            default = self._call(td, "default", None)
            type0 = self._call(td, "type0", 0)
            type2 = self._call(td, "type2", 2)
        self.assertTrue(_same(default, type0))
        self.assertFalse(_same(default, type2),
                         "type 2 under the cold case changed no variable")


if __name__ == "__main__":
    unittest.main()
