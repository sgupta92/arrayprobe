# SPDX-License-Identifier: BSD-3-Clause
"""The driver half of the v3.5 probe-clock offset: ``run_flight.py``'s ``--time-offset-s``,
``--time-offset-evidence`` and ``--time-offset-tas-clock``.

The engine keyword is tested in ``test_v35_time_offset.py``. This file pins what the driver does
with it: refused (exit 2) under any engine but 3.5; passed to ``sizedist.run`` under 3.5 only
when set; the sd ``.call`` stamp unchanged when unset and carrying the offset, its TAS clock and
its evidence when set.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
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

_SET = (-100, "SPEC clock vs aircraft TAS cross-correlation, 2017-07-08", "probe")


class _V35DriverState(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        run_flight.ENGINE = "3.5"
        run_flight.TAS_FILE = None
        run_flight.TIME_OFFSET = None


class TestTheStamp(_V35DriverState):

    def test_unset_stamp_is_unchanged(self):
        unset = run_flight.sd_call_label(None)
        self.assertNotIn("time_offset", unset)
        run_flight.TIME_OFFSET = _SET
        with_offset = run_flight.sd_call_label(None)
        # Setting it only appends one fragment, so every default stamp stays byte-identical.
        fragment = (" time_offset_s=-100 time_offset_tas_clock=probe"
                    f" time_offset_evidence={json.dumps(_SET[1])}")
        self.assertIn(fragment, with_offset)
        self.assertEqual(with_offset.replace(fragment, "", 1), unset)

    def test_set_stamp_carries_offset_and_evidence(self):
        run_flight.TIME_OFFSET = (78, "line one\nline two", "aircraft")
        label = run_flight.sd_call_label(None)
        self.assertIn(" time_offset_s=78 ", label)
        self.assertIn(" time_offset_tas_clock=aircraft", label)
        self.assertIn('time_offset_evidence="line one\\nline two"', label)
        self.assertNotIn("\n", label)

    def test_set_and_unset_read_stale_against_each_other(self):
        unset = run_flight.sd_call_label(None)
        run_flight.TIME_OFFSET = _SET
        with_offset = run_flight.sd_call_label(None)
        self.assertFalse(run_flight._stamps_equivalent(unset, with_offset))
        self.assertFalse(run_flight._stamps_equivalent(with_offset, unset))


class TestTheCallReachesTheEngine(_V35DriverState):

    def _call(self):
        fake = mock.MagicMock()
        with mock.patch.object(run_flight, "_v35") as v35:
            v35.return_value.module.return_value.run = fake
            # Engine 3.5's default-on time-grid fix runs before `run`; give the mocked module the
            # real helpers so that path executes rather than unpacking a MagicMock.
            from arrayprobe_uiops import sizedist as _real_sd
            v35.return_value.module.return_value.fix_time_grid = _real_sd.fix_time_grid
            v35.return_value.module.return_value.count_duplicate_seconds = (
                _real_sd.count_duplicate_seconds)
            run_flight._sizedist_call(Path("proc.nc"), Path("sd.nc"), "base160906075333",
                                      np.array([60640.0, 60641.0, 60642.0]),
                                      np.full(3, 85.0), None)
        self.assertEqual(fake.call_count, 1)
        return fake.call_args.kwargs

    def test_unset_passes_no_keyword(self):
        kwargs = self._call()
        for name in ("time_offset_s", "time_offset_evidence", "time_offset_tas_clock"):
            self.assertNotIn(name, kwargs)

    def test_set_passes_all_three(self):
        run_flight.TIME_OFFSET = _SET
        kwargs = self._call()
        self.assertEqual(kwargs["time_offset_s"], -100)
        self.assertEqual(kwargs["time_offset_evidence"], _SET[1])
        self.assertEqual(kwargs["time_offset_tas_clock"], "probe")


class TestMainRefusesAndAccepts(unittest.TestCase):

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)

    def _main(self, engine_args, extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main([*engine_args, "--preset", "ORACLES_2016_2DS_H", *extra,
                                  "nosuch-raw.2DS"])
        return rc, buf.getvalue()

    _V35 = ("--engine", "3.5", "--profile", "stock-v3.5")
    _OPTS = ("--time-offset-s", "-100", "--time-offset-evidence", "measured",
             "--time-offset-tas-clock", "probe")

    @needs_v314_engine
    def test_refused_under_engine_314(self):
        rc, out = self._main(("--engine", "3.1.4", "--port-validation"), self._OPTS)
        self.assertEqual(rc, 2)
        self.assertIn("engine 3.5 only", out)

    @needs_v314_engine
    def test_each_option_alone_is_refused_under_engine_314(self):
        for opt, val in zip(self._OPTS[::2], self._OPTS[1::2], strict=True):
            with self.subTest(opt=opt):
                rc, out = self._main(("--engine", "3.1.4", "--port-validation"), (opt, val))
                self.assertEqual(rc, 2)
                self.assertIn("engine 3.5 only", out)

    def test_soda2_is_not_a_driver_engine(self):
        # SODA-2 runs through `arrayprobe soda2 run`; argparse refuses it here, exit 2.
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            self._main(("--engine", "soda2"), self._OPTS)
        self.assertEqual(cm.exception.code, 2)

    def test_accepted_under_engine_35_and_set(self):
        _rc, out = self._main(self._V35, self._OPTS)
        self.assertNotIn("engine 3.5 only", out)
        self.assertNotIn("--time-offset-s refused", out)
        self.assertEqual(run_flight.TIME_OFFSET, (-100, "measured", "probe"))

    def test_invalid_values_exit_2_before_any_decode(self):
        for extra in (("--time-offset-s", "1.5", "--time-offset-evidence", "m",
                       "--time-offset-tas-clock", "probe"),
                      ("--time-offset-s", "5", "--time-offset-tas-clock", "probe"),
                      ("--time-offset-s", "5", "--time-offset-evidence", "m",
                       "--time-offset-tas-clock", "gps"),
                      ("--time-offset-evidence", "m")):
            with self.subTest(extra=extra):
                rc, out = self._main(self._V35, extra)
                self.assertEqual(rc, 2, out)
                self.assertNotIn("S2 start", out)


class TestJobsWorkersGetIt(unittest.TestCase):

    def _cmd(self, **kw):
        ns = types.SimpleNamespace(
            stages="234", out=Path("."), chunks=1, s2_jobs=1, iat_file="",
            preset="ORACLES_2016_2DS_H", tas_file=None, presets=None, config=None,
            allow_mixed_config=False, accept_unstamped=False, diode_corrected=False,
            engine="3.5", worker_stall_min=30.0, profile="stock-v3.5", **kw)
        with mock.patch.object(run_flight.subprocess, "Popen", return_value=mock.Mock()) as popen, \
                mock.patch("builtins.open", mock.mock_open()):
            run_flight._spawn_worker([Path("a.2DS")], ns, Path("worker.log"))
        return popen.call_args.args[0]

    def test_forwarded_when_set(self):
        cmd = self._cmd(time_offset_s=-100.0, time_offset_evidence="measured",
                        time_offset_tas_clock="probe")
        i = cmd.index("--time-offset-s")
        self.assertEqual(cmd[i:i + 6], ["--time-offset-s", "-100.0", "--time-offset-evidence",
                                        "measured", "--time-offset-tas-clock", "probe"])

    def test_absent_when_unset(self):
        self.assertNotIn("--time-offset-s", self._cmd())


if __name__ == "__main__":
    unittest.main()
