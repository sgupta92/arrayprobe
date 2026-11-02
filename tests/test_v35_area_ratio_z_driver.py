# SPDX-License-Identifier: BSD-3-Clause
"""The driver half of the v3.5 area-ratio override: ``run_flight.py``'s ``--area-ratio-z``.

The engine keyword is tested in ``test_v35_area_ratio_z.py`` (bit-identical when unset, the gate
acting, off meaning off) and against Octave in ``test_v35_area_ratio_z_oracle.py``. This file
pins what the driver does with it under ``--engine 3.5``, in both states:

* unset, the sd ``.call`` stamp is byte-identical to what every earlier v3.5 run wrote, so every
  existing sd stays current, and ``sizedist.run`` runs with ``area_ratio_z=None``: since regime
  slice 4 (8ac64a1) the driver leaves the keyword out and the engine's default, ``None``, stands;
* set, the value is in the stamp (an sd built without it then reads as stale) and reaches
  ``sizedist.run``.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from tests import _run_flight_state
from tests._repo import needs_v314_engine  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_flight", _ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)


class _V35DriverState(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        run_flight.ENGINE = "3.5"
        run_flight.TAS_FILE = None
        run_flight.AREA_RATIO_Z_OVERRIDE = None


class TestTheStamp(_V35DriverState):

    def test_unset_writes_no_area_ratio_z_key(self):
        self.assertNotIn("area_ratio_z", run_flight.sd_call_label(None))

    def test_set_records_the_value_only(self):
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.5
        label = run_flight.sd_call_label(None)
        self.assertIn(" area_ratio_z=0.5", label)
        self.assertNotIn("user:", label)

    def test_the_source_does_not_change_the_stamp(self):
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.5
        run_flight.AREA_RATIO_Z_SOURCE = "cli"
        from_cli = run_flight.sd_call_label(None)
        run_flight.AREA_RATIO_Z_SOURCE = "some/run.toml"
        self.assertEqual(from_cli, run_flight.sd_call_label(None))

    def test_zero_is_recorded_not_dropped(self):
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.0
        self.assertIn(" area_ratio_z=0.0", run_flight.sd_call_label(None))

    def test_an_unset_stamp_is_the_stamp_every_earlier_run_wrote(self):
        """The label built with the override unset is a prefix-free superset of nothing: setting
        the override only appends one fragment, so removing it gives back the unset label."""
        unset = run_flight.sd_call_label(None)
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.5
        with_z = run_flight.sd_call_label(None)
        self.assertEqual(with_z.replace(" area_ratio_z=0.5", "", 1), unset)
        self.assertTrue(run_flight._stamps_equivalent(unset, unset))

    def test_an_unset_sd_reads_stale_against_a_set_run_and_the_reverse(self):
        unset = run_flight.sd_call_label(None)
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.5
        with_z = run_flight.sd_call_label(None)
        self.assertFalse(run_flight._stamps_equivalent(unset, with_z))
        self.assertFalse(run_flight._stamps_equivalent(with_z, unset))
        self.assertTrue(run_flight._stamps_equivalent(with_z, with_z))

    def test_engine_314_stamp_is_unchanged_by_the_v35_fragment(self):
        run_flight.ENGINE = "3.1.4"
        before = run_flight.sd_call_label(None)
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.5
        after = run_flight.sd_call_label(None)
        # v3.1.4 already stamps area_ratio_z through thresholds_stamp(), tagged with its source;
        # no untagged v3.5 fragment is added on top of that.
        self.assertNotIn(" area_ratio_z=0.5 area_ratio_z=", after)
        self.assertEqual(after.count("area_ratio_z="), 1)
        self.assertEqual(before.count("area_ratio_z="), 1)


class TestTheCallReachesTheEngine(_V35DriverState):

    def _call(self):
        fake = mock.MagicMock()
        with mock.patch.object(run_flight, "_v35") as v35:
            v35.return_value.module.return_value.run = fake
            # The default-on time-grid fix: fix_time_grid returns (axis, n_moved).
            v35.return_value.module.return_value.fix_time_grid.side_effect = (
                lambda t: (t, 0))
            tas = np.full(3, 85.0)
            run_flight._sizedist_call(Path("proc.nc"), Path("sd.nc"), "base160906075333",
                                      np.array([60640.0, 60641.0, 60642.0]), tas, None)
        self.assertEqual(fake.call_count, 1)
        return fake.call_args.kwargs

    def test_unset_passes_none(self):
        # Absent from the call (regime slice 4), so the engine's own default applies: it must be
        # None, or an unset run would stop being the stock v3.5 path.
        import inspect

        from arrayprobe_uiops import sizedist
        self.assertIsNone(self._call().get("area_ratio_z"))
        self.assertIsNone(inspect.signature(sizedist.run).parameters["area_ratio_z"].default)

    def test_set_passes_the_value(self):
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.5
        self.assertEqual(self._call()["area_ratio_z"], 0.5)

    def test_zero_passes_zero_not_none(self):
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.0
        self.assertEqual(self._call()["area_ratio_z"], 0.0)
        self.assertIsNotNone(self._call()["area_ratio_z"])

    @needs_v314_engine
    def test_engine_314_does_not_receive_the_keyword(self):
        run_flight.ENGINE = "3.1.4"
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.5
        fake = mock.MagicMock()
        with mock.patch.object(run_flight.sizedist, "run", fake):
            run_flight._sizedist_call(Path("proc.nc"), Path("sd.nc"), "base160906075333",
                                      np.array([60640.0, 60641.0, 60642.0]),
                                      np.full(3, 85.0), None)
        self.assertNotIn("area_ratio_z", fake.call_args.kwargs)
        self.assertEqual(fake.call_args.kwargs["reject"].area_ratio_z, 0.5)


if __name__ == "__main__":
    unittest.main()
