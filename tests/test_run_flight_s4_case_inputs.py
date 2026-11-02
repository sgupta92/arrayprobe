# SPDX-License-Identifier: BSD-3-Clause
"""``--tas-max`` / ``--pecan-params`` and ``[thresholds].tas_max`` / ``.pecan_params`` in the batch
driver: each reaches ``sizedist.run`` on both engines only when set, is written to the sd
``.call`` stamp only when set, and a case that needs one the run lacks is refused at preflight."""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402
from tests.test_engine_flag_parity import _demo_root, _v35_toml

from arrayprobe.driver import run_flight as rf
from arrayprobe.profiles import ORACLES_PRODUCTION, STOCK_V35

_GLOBALS = ("ENGINE", "PROFILE", "TAS_FILE", "TAS_CHAIN", "AUTHORDEFAULTS_STAMP", "REGIME_NAME",
            "AREA_RATIO_Z_OVERRIDE", "DEFAULT_IAT_OVERRIDE", "AREA_RATIO_Z_SOURCE",
            "DEFAULT_IAT_SOURCE", "PROBE_CASE", "TAS_MAX", "PECAN_PARAMS", "PROJECT", "PROBE",
            "TREE", "PROFILE_MODULE", "ACTIVE", "ORIENTATION", "D_CHOICE", "SA_METHOD",
            "PRES_PA", "TEMP_C", "JIT", "PORT_VALIDATION", "LIBM_POW",
            "STRAY_PIXEL", "PROTECTIVE_MODE")
_FIXTURE = Path(__file__).resolve().parent / "data" / "demo_flight_v35_sd.call"


#: What this driver appends to that stamp since engine 3.5's default-on corrections (2026-10-04):
#: the 2D-S ladder in place of the otherwise branch's HVPS table and the time-grid /
#: zero-sample-volume marker. The tracked sidecar was written by a run made before both existed,
#: so it is kept byte-for-byte as that run's record and the two tokens are added here, exactly.
_HVPS_TABLE_FIX_TOKENS = " bins=2ds-ladder(V11-fix) time_sv_fix=on"


def _fixture() -> str:
    """The tracked sd stamp as this driver now writes it for the configuration that made it: the
    tracked text (which already carries the default-on stray-pixel correction,
    ``stray_pixel=on:g8,n2,m9`` just before ``sizedist=``) plus :data:`_HVPS_TABLE_FIX_TOKENS`."""
    text = _FIXTURE.read_text(encoding="utf-8").strip()
    assert text.count(" stray_pixel=on:g8,n2,m9 sizedist=(") == 1, text
    # Regenerated 2026-10-05 under the default corrections, the sidecar now carries the two
    # tokens itself, plus what the run measured (time/sample-volume counts, the plausibility
    # verdict), which a configured label never carries and the driver strips before comparing.
    text = rf._strip_plausibility(rf._strip_time_sv_counts(text))
    assert text.endswith(_HVPS_TABLE_FIX_TOKENS), text
    return text


class _Isolated(unittest.TestCase):
    def setUp(self):
        for name in _GLOBALS:
            self.addCleanup(setattr, rf, name, getattr(rf, name))
        rf.ENGINE, rf.PROFILE = "3.5", STOCK_V35
        rf.TAS_FILE = "somewhere/demo_flight_v35_aircraft.cdf"
        rf.TAS_CHAIN, rf.AUTHORDEFAULTS_STAMP = None, None
        rf.REGIME_NAME = rf.AREA_RATIO_Z_OVERRIDE = rf.DEFAULT_IAT_OVERRIDE = None
        rf.PROBE_CASE = rf.TAS_MAX = rf.PECAN_PARAMS = None
        # The tracked fixture was made with the correction on; pin the switch to that state rather
        # than inherit whatever an earlier test's main() left in the module global.
        rf.STRAY_PIXEL = True
        # Likewise the default-on corrections: the default protective mode.
        rf.PROTECTIVE_MODE = "auto"


class CaseInputsReachSizedist(_Isolated):
    def _v35_kwargs(self) -> dict:
        fake_sd = mock.Mock()
        engine = mock.Mock()
        engine.module.return_value = fake_sd
        # The default-on time-grid fix runs on this engine: fix_time_grid returns
        # (axis, n_moved) and run's result dict carries the zero-sample-volume count.
        fake_sd.fix_time_grid.side_effect = lambda t: (t, 0)
        fake_sd.count_duplicate_seconds.return_value = 0
        fake_sd.run.return_value = {"_zero_sv_seconds": 0}
        # The HVPS-bin-table detection reads the real engine's tables; take its answer before the
        # engine is replaced by the stub, so the stub does not change which ladder is chosen.
        bins_on_2ds = rf._v35_otherwise_hvps_bins_on_2ds()
        with mock.patch.object(rf, "_v35", return_value=engine), \
                mock.patch.object(rf, "_v35_otherwise_hvps_bins_on_2ds", return_value=bins_on_2ds):
            rf._sizedist_call(Path("proc.nc"), Path("sd.nc"), "base160101000000",
                              np.array([60640.0]), np.array([85.0]), None)
        return fake_sd.run.call_args.kwargs

    def _v314_kwargs(self) -> dict:
        rf.ENGINE, rf.PROFILE = "3.1.4", ORACLES_PRODUCTION
        with mock.patch.object(rf.sizedist, "run") as run:
            rf._sizedist_call(Path("proc.nc"), Path("sd.nc"), "base160101000000",
                              np.array([60640.0]), np.array([85.0]), None)
        return run.call_args.kwargs

    @needs_v314_engine
    def test_unset_passes_neither_keyword_on_either_engine(self):
        for kw in (self._v35_kwargs(), self._v314_kwargs()):
            self.assertNotIn("tas_max", kw)
            self.assertNotIn("pecan_params", kw)

    @needs_v314_engine
    def test_set_passes_both_on_either_engine(self):
        rf.TAS_MAX, rf.PECAN_PARAMS = 140.0, "spirals.csv"
        for kw in (self._v35_kwargs(), self._v314_kwargs()):
            self.assertEqual(kw["tas_max"], 140.0)
            self.assertEqual(kw["pecan_params"], "spirals.csv")


class CaseInputsInTheStamp(_Isolated):
    def test_the_unset_stamp_equals_the_tracked_fixture(self):
        self.assertEqual(rf.sd_call_label(None), _fixture())

    def test_tas_max_and_the_parameter_file_are_stamped_only_when_set(self):
        fixture = _fixture()
        rf.TAS_MAX = 140.0
        self.assertEqual(rf.sd_call_label(None), fixture + " tas_max=140.0")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "spirals.csv"
            p.write_text("start_s,end_s,intar_threshold_s\n0,10,2e-6\n", encoding="utf-8")
            rf.PECAN_PARAMS = str(p)
            first = rf.sd_call_label(None)
            self.assertRegex(
                first, r" tas_max=140\.0 pecan_params=spirals\.csv@sha256:[0-9a-f]{12}")
            p.write_text("start_s,end_s,intar_threshold_s\n0,10,3e-6\n", encoding="utf-8")
            self.assertNotEqual(rf.sd_call_label(None), first, "a changed file must read stale")


class PreflightRefusals(_Isolated):
    def test_a_2dp_without_tas_max_names_the_option_and_the_config_key(self):
        rf.PROJECT, rf.PROBE = "NOT_A_PROJECT", "2DP"
        for engine, tree in (("3.5", rf.TREE), ("3.1.4", "stock"), ("3.1.4", "production")):
            with self.subTest(engine=engine, tree=tree):
                rf.ENGINE, rf.TREE, rf.TAS_MAX = engine, tree, None
                msg = rf._s4_case_inputs_problem()
                self.assertIsNotNone(msg)
                self.assertIn("--tas-max", msg)
                self.assertIn("[thresholds].tas_max", msg)
                rf.TAS_MAX = 140.0
                self.assertIsNone(rf._s4_case_inputs_problem())

    def test_tas_max_on_a_case_with_its_own_and_pecan_params_off_pecan_are_refused(self):
        rf.PROJECT, rf.PROBE = "ORACLES", "2DS"
        rf.TAS_MAX = 140.0
        self.assertIn("assigns tasMax", rf._s4_case_inputs_problem())
        rf.TAS_MAX, rf.PECAN_PARAMS = None, "spirals.csv"
        self.assertIn("--pecan-params", rf._s4_case_inputs_problem())

    def test_a_pecan_case_without_parameters_is_refused(self):
        rf.PROJECT, rf.PROBE = "PECAN", "CIP"
        msg = rf._s4_case_inputs_problem()
        self.assertIn("--pecan-params", msg)
        self.assertIn("[thresholds].pecan_params", msg)


class MainExitsTwoAndMergesTheConfig(_Isolated):
    """Through ``main()`` on the synthetic DEMO_2DS_H flight, whose case assigns its own tasMax:
    a supplied one is refused (exit 2), from the command line or from ``[thresholds]``."""

    def _main(self, *extra, thresholds: str | None = None) -> tuple[int, str]:
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root, **({"t": thresholds} if thresholds else {}))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rf.main([str(raw), "--config", str(toml), "--engine", "3.5",
                          "--preset", "DEMO_2DS_H", "--out", str(root / "_decoded"),
                          "--dry-run", "--yes", *extra])
        return rc, buf.getvalue()

    def test_without_either_the_dry_run_passes(self):
        rc, out = self._main()
        self.assertEqual(rc, 0, out)

    def test_cli_tas_max_on_a_case_with_its_own_exits_2(self):
        rc, out = self._main("--tas-max", "140")
        self.assertEqual(rc, 2, out)
        self.assertIn("--tas-max supplies a tasMax", out)

    def test_config_tas_max_is_merged_and_refused_the_same_way(self):
        rc, out = self._main(thresholds="[thresholds]\ntas_max = 140.0")
        self.assertEqual(rc, 2, out)
        self.assertIn("config    tas_max (S4 tasMax): 140.0", out)
        self.assertEqual(rf.TAS_MAX, 140.0)

    def test_the_command_line_wins_over_the_config(self):
        rc, out = self._main("--tas-max", "150", thresholds="[thresholds]\ntas_max = 140.0")
        self.assertEqual(rc, 2, out)
        self.assertIn("command line's --tas-max 150.0 wins", out)
        self.assertEqual(rf.TAS_MAX, 150.0)


if __name__ == "__main__":
    unittest.main()
