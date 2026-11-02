# SPDX-License-Identifier: BSD-3-Clause
"""Regime slice 4: under engine 3.5 a regime's
area_ratio_z and default_int_arr_thresh reach ``arrayprobe_uiops.sizedist.run``; without a regime or
override no keyword is passed, and the no-regime sd stamp equals the tracked fixture."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe.driver import run_flight as rf
from arrayprobe.profiles import STOCK_V35

_GLOBALS = ("ENGINE", "PROFILE", "TAS_FILE", "TAS_CHAIN", "AUTHORDEFAULTS_STAMP", "REGIME_NAME",
            "AREA_RATIO_Z_OVERRIDE", "DEFAULT_IAT_OVERRIDE", "AREA_RATIO_Z_SOURCE",
            "DEFAULT_IAT_SOURCE", "PROBE_CASE", "STRAY_PIXEL")
_FIXTURE = Path(__file__).resolve().parent / "data" / "demo_flight_v35_sd.call"


def _fixture() -> str:
    """The tracked sd stamp as this driver writes it for the run that made it. That run predates
    the default-on stray-pixel correction, so its stamp already carries
    ``stray_pixel=on:g8,n2,m9`` just before ``sizedist=``."""
    text = _FIXTURE.read_text(encoding="utf-8").strip()
    assert text.count(" stray_pixel=on:g8,n2,m9 sizedist=(") == 1, text
    # The written stamp also records what the run measured (time/sample-volume counts, the
    # plausibility verdict); the configured label never carries them, and the driver strips
    # the same tokens before it compares two stamps (_stamps_equivalent).
    return rf._strip_plausibility(rf._strip_time_sv_counts(text))


def _with_before_time_sv(fixture: str, extra: str) -> str:
    """``fixture`` with ``extra`` where sd_call_label places regime/override tokens: before
    the default-on ``time_sv_fix=on`` token, which the label writes last."""
    tail = " time_sv_fix=on"
    if fixture.endswith(tail):
        return fixture[: -len(tail)] + extra + tail
    return fixture + extra


class RegimeReachesV35Sizedist(unittest.TestCase):
    def setUp(self):
        for name in _GLOBALS:
            self.addCleanup(setattr, rf, name, getattr(rf, name))
        rf.ENGINE, rf.PROFILE = "3.5", STOCK_V35
        rf.TAS_FILE = "somewhere/demo_flight_v35_aircraft.cdf"
        rf.TAS_CHAIN, rf.AUTHORDEFAULTS_STAMP = None, None
        rf.REGIME_NAME = rf.AREA_RATIO_Z_OVERRIDE = rf.DEFAULT_IAT_OVERRIDE = None
        rf.PROBE_CASE = None
        # The tracked fixture was made with the correction on; pin the switch to that state rather
        # than inherit whatever an earlier test's main() left in the module global.
        rf.STRAY_PIXEL = True

    def _kwargs(self) -> dict:
        fake_sd = mock.Mock()
        engine = mock.Mock()
        engine.module.return_value = fake_sd
        # The current call contract (engine-3.5 time/sample-volume correction): fix_time_grid
        # returns (axis, n_moved), count_duplicate_seconds an int, run a dict of counts; the
        # bin-table check reads the real probe table so the default-on ladder fix is exercised.
        fake_sd.fix_time_grid.side_effect = lambda t: (t, 0)
        fake_sd.count_duplicate_seconds.return_value = 0
        fake_sd.run.return_value = {}
        fake_sd.probe_defaults.side_effect = rf._v35().module("sizedist").probe_defaults
        with mock.patch.object(rf, "_v35", return_value=engine):
            rf._sizedist_call(Path("proc.nc"), Path("sd.nc"), "base160101000000",
                              np.array([60640.0]), np.array([85.0]), None)
        return fake_sd.run.call_args.kwargs

    def test_no_regime_passes_neither_keyword(self):
        kw = self._kwargs()
        self.assertNotIn("area_ratio_z", kw)
        self.assertNotIn("default_int_arr_thresh", kw)

    def test_a_regime_passes_both_of_its_values(self):
        rf.REGIME_NAME = "ice"
        kw = self._kwargs()
        self.assertEqual(kw["area_ratio_z"], 0.2)
        self.assertEqual(kw["default_int_arr_thresh"], 4e-6)

    def test_a_user_override_wins_over_the_regime_per_field(self):
        rf.REGIME_NAME, rf.DEFAULT_IAT_OVERRIDE = "ice", 1e-5
        kw = self._kwargs()
        self.assertEqual(kw["default_int_arr_thresh"], 1e-5)
        self.assertEqual(kw["area_ratio_z"], 0.2)

    def test_the_no_regime_sd_stamp_equals_the_tracked_fixture(self):
        fixture = _fixture()
        self.assertEqual(rf.sd_call_label(None), fixture)

    def test_a_user_area_ratio_z_stamp_is_unchanged(self):
        fixture = _fixture()
        rf.AREA_RATIO_Z_OVERRIDE = 0.5
        self.assertEqual(rf.sd_call_label(None), _with_before_time_sv(fixture, " area_ratio_z=0.5"))

    def test_a_regime_stamp_names_the_regime_and_an_unused_threshold(self):
        fixture = _fixture()
        rf.REGIME_NAME = "ice"
        with mock.patch.object(rf, "_v35_iat_unused_note",
                               return_value="unused, applyIntArrThresh=0"):
            self.assertEqual(
                rf.sd_call_label(None),
                _with_before_time_sv(
                    fixture, " area_ratio_z=0.2 (regime:ice) default_int_arr_thresh=4e-06 "
                             "(regime:ice; unused, applyIntArrThresh=0)"))


if __name__ == "__main__":
    unittest.main()
