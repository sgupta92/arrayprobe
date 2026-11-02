# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py`` runs any registered profile end to end.

Until 2026-09-10, ``--config`` naming anything but ``ORACLES_PRODUCTION`` raised
``SystemExit(2)`` from :func:`run_flight._apply_config` -- "this driver only runs
ORACLES_PRODUCTION; use arrayprobe.cli or the library instead." That is why A10's
whole-file measurement on a non-production profile "was never free": the one driver
fifteen validated flights came out of could not run it.

This is the integration-level proof, through the real CLI entry point
(``run_flight.main``), that a different profile now reaches every stage -- not just
that ``_apply_config`` stops raising (``tests/test_run_flight_config.py`` already
covers that unit) -- and that the default (no ``--config``) path is completely
unaffected: same commands, same synthetic demo flight, same S2/S3/S4 stage
functions ``tests/test_end_to_end.py`` already pins the computed values of.

**Uses ``ORACLES_2016``, not ``STOCK_V314``, as the "different profile."**
``STOCK_V314.time_in_seconds_from_tas`` is ``True``, which ``imgProc_sm`` then
requires a TAS file (``varargin{1}``) for -- and ``run_flight.py`` has never
threaded a ``tas_file`` argument through :func:`run_flight._imgproc_sm_chunk` for
ANY profile, because the two profiles the driver has ever run (``oracles-2016``,
``oracles-production``) both have it ``False``. Discovered running this exact
test against ``STOCK_V314`` first: ``imgproc_sm`` raised
``ValueError: profile.time_in_seconds_from_tas is set, so imgProc_sm.m:183-185
needs the aircraft file as varargin{1}; pass tas_file=``, which is the port
correctly refusing to guess rather than a bug in this generalisation. **This is
real, known, and NOT fixed here**: threading a ``tas_file`` argument through S3
is a separate, larger change (the driver has no per-profile TAS convention today)
and out of this pass's scope. ``ORACLES_2016`` proves the generalisation
mechanism itself -- profile propagation to S2/S3/S4 and the provenance
stamp -- without also needing that unrelated plumbing.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests._repo import needs_v314_engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"

_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules["make_demo_flight"] = make_demo_flight
_DEMO_SPEC.loader.exec_module(make_demo_flight)

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
assert _RF_SPEC is not None and _RF_SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_RF_SPEC)
sys.modules.setdefault(_RF_SPEC.name, run_flight)
_RF_SPEC.loader.exec_module(run_flight)


def _toml(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "run.toml"
    path.write_text(text, encoding="utf-8")
    return path


class AnyRegisteredProfileRunsEndToEnd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.raw = self.out / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(self.raw, n_seconds=3)
        self._real_profile = run_flight.PROFILE
        self.addCleanup(setattr, run_flight, "PROFILE", self._real_profile)

    def _run(self, extra_argv):
        # --yes: these runs state no threshold policy, so the confirmation gate applies, and a
        # test process has no terminal to answer at. This subject is the profile, not the gate;
        # `tests/test_run_flight_confirm.py` is where the gate itself is asserted.
        argv = ["--engine", "3.1.4", "--port-validation", "--preset", "DEMO_2DS_H",
                "--stages", "234", "--yes",
                "--out", str(self.out), *extra_argv, str(self.raw)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main(argv)
        return rc, buf.getvalue()

    def _proc_stamp(self) -> str:
        proc = self.out / f"proc.{self.raw.stem}.H.nc"
        self.assertTrue(proc.exists(), "S3 must have run")
        return run_flight.read_stamp(proc)

    @needs_v314_engine
    def test_default_path_is_unaffected_and_stamps_oracles_production(self):
        rc, log = self._run([])
        self.assertEqual(rc, 0, log)
        self.assertIs(run_flight.PROFILE, run_flight.ORACLES_PRODUCTION)
        self.assertIn("profile=oracles-production", self._proc_stamp())

    @needs_v314_engine
    def test_a_different_registered_profile_reaches_every_stage(self):
        """The regression this generalisation exists to fix: naming
        ORACLES_2016 in --config used to raise SystemExit(2) before a single
        raw byte was read. Now it reaches S2, S3 and S4, and the proc file's
        own provenance stamp -- not just a log line -- records it, proving
        the profile actually reached imgproc_sm's reject-threshold call
        rather than only the label function."""
        cfg = _toml('[fidelity]\nprofile = "ORACLES_2016"\n')
        rc, log = self._run(["--config", str(cfg)])
        self.assertEqual(rc, 0, log)
        self.assertIn("profile switched", log)
        from arrayprobe.profiles import ORACLES_2016
        self.assertIs(run_flight.PROFILE, ORACLES_2016)
        stamp = self._proc_stamp()
        self.assertIn("profile=oracles-2016", stamp)
        # The two profiles' reject_thresholds genuinely differ (oracles-2016
        # uses DEFAULT_REJECT_CONFIG, oracles-production its own measured
        # thresholds) -- the stamp must show a different configuration, not
        # just a different name for the same one.
        default_stamp = run_flight.config_label(run_flight.ORACLES_PRODUCTION)
        self.assertNotEqual(stamp.split(" ", 1)[1], default_stamp.split(" ", 1)[1])


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
