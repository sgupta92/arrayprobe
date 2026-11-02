# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py --profile``: the default engine, reachable from one command line.

Found by the cold-user end-to-end walk.

``--engine 3.5`` is the project's default engine, and it requires a profile whose
citations are to the v3.5 tree (``profiles.is_v35_flavoured``). ``DEMO_2DS_H`` is the
only zero-data demo preset, a :class:`CampaignPreset` carries no profile field, and
until 2026-09-20 this driver had no ``--profile`` flag -- so
``--preset DEMO_2DS_H --engine 3.5`` was **unreachable from any command line**, and the
only route to the default engine was hand-writing a TOML file naming
``profile = "stock-v3.5"`` and ``[combine].borrowed = true``. A new user following the
published quickstart was shown the *non-default* engine.

WHAT THIS PINS.

1. One command line runs the demo flight under the default engine
   (``TheDefaultEngineIsReachableFromOneCommandLine``), and the same command line
   without ``--profile`` is still refused -- the control that says the flag is what
   changed, not something else.
2. Both spellings of a profile name work here, exactly as in a config file: one name
   space, resolved through ``arrayprobe.config.PROFILES``.
3. An unknown name is refused with exit 2 and the list of what would have worked.
4. ``--jobs`` workers are given the flag. Five flags have gone missing from
   ``_spawn_worker``'s list by accident, each producing silent wrong output; this one
   would stamp every worker's products with a profile the parent never ran.
5. ``--enhancements`` without ``--config`` exits **2**, before any stage runs. It was
   the one configuration refusal in this driver that came out as exit 1 -- the code a
   failed flight uses -- and it came out only after every stage had already run
   (§4.3 of the same report). The convention it now keeps: **2 = the command line or
   config was refused and nothing ran; 1 = something ran and failed.**

No stage is executed: every case is a ``--dry-run`` or a refusal, so the whole module
is a fraction of a second and touches no real data.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
assert spec is not None and spec.loader is not None
run_flight = importlib.util.module_from_spec(spec)
sys.modules.setdefault(spec.name, run_flight)
spec.loader.exec_module(run_flight)

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import profiles  # noqa: E402 -- after the sys.path insert above

#: The v3.1.4 validation engine ships in the development layout only; the public tree
#: runs the engine-independent cases on v3.5 instead.
_HAS_V314 = importlib.util.find_spec("arrayprobe.reject") is not None

#: The refusal the v3.5 engine gives a profile that does not cite the v3.5 tree.
V35_REFUSAL = "--engine 3.5 needs a v3.5 profile"


class _Run(unittest.TestCase):
    """Runs ``main`` on a synthetic, never-decoded file and restores every global.

    ``main`` rebinds module-level state (``ACTIVE``/``PROBE``/``PROFILE``/``ENGINE``),
    which is the documented way a preset and a profile take effect; a test that left
    it rebound would steer every later test in the same interpreter.
    """

    def setUp(self):
        self._saved = {n: getattr(run_flight, n) for n in
                       ("ACTIVE", "PROBE", "ORIENTATION", "PROJECT", "D_CHOICE",
                        "SA_METHOD", "PRES_PA", "TEMP_C", "PROFILE", "PROFILE_MODULE",
                        "ENGINE", "TAS_FILE", "PORT_VALIDATION", "LIBM_POW")}
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.raw = self.tmp / "base160101000000.2DS"
        self.raw.write_bytes(b"\x00" * 4096)
        self.tas = self.tmp / "aircraft.cdf"
        self.tas.write_bytes(b"x")
        self.out = self.tmp / "out"

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(run_flight, name, value)

    def run_main(self, *extra: str) -> tuple[int, str]:
        # The default is engine 3.1.4 with --port-validation; a caller that names its own
        # engine (v35_argv) runs that engine, which refuses the flag. Where the v3.1.4
        # engine is absent (the public tree) the default is v3.5 with the demo profile.
        if "--engine" in extra:
            engine = ()
        elif _HAS_V314:
            engine = ("--engine", "3.1.4", "--port-validation")
        else:
            engine = self.v35_argv("--profile", "stock-v3.5")
        argv = [str(self.raw), *engine,
                "--preset", "DEMO_2DS_H", "--out", str(self.out),
                "--dry-run", "--yes", *extra]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main(argv)
        return rc, buf.getvalue()

    def _engine_argv(self) -> tuple[str, ...]:
        if _HAS_V314:
            return ("--engine", "3.1.4", "--port-validation")
        return self.v35_argv("--profile", "stock-v3.5")

    def v35_argv(self, *extra: str) -> tuple[str, ...]:
        """The demo flight under the default engine -- everything but the profile."""
        return ("--engine", "3.5", "--borrowed-combine", "--stages", "234c",
                "--tas-file", str(self.tas), *extra)


class TheDefaultEngineIsReachableFromOneCommandLine(_Run):
    def test_the_demo_flight_runs_under_engine_3_5_in_one_command_line(self):
        rc, log = self.run_main(*self.v35_argv(), "--profile", "stock-v3.5")
        self.assertEqual(rc, 0, log)
        self.assertNotIn(V35_REFUSAL, log)
        self.assertIn("running   engine=3.5 profile=stock-v3.5 preset=DEMO_2DS_H", log)
        self.assertIn("fidelity profile       stock-v3.5", log)

    def test_the_same_command_line_without_the_flag_is_still_refused(self):
        """The control. Without ``--profile`` the run is refused for the reason the
        report named -- so the test above measures the flag and not the weather."""
        rc, log = self.run_main(*self.v35_argv())
        self.assertEqual(rc, 2)
        self.assertIn(V35_REFUSAL, log)

    def test_the_constant_spelling_reaches_the_same_profile(self):
        """``STOCK_V35`` is what ``profiles.py`` calls it. One name
        space for profiles: the flag resolves through ``arrayprobe.config.PROFILES``,
        so a spelling a config file accepts is a spelling this flag accepts."""
        rc, log = self.run_main(*self.v35_argv(), "--profile", "STOCK_V35")
        self.assertEqual(rc, 0, log)
        self.assertIn("-> stock-v3.5 (--profile)", log)

    def test_an_unknown_profile_is_refused_with_the_alternatives(self):
        rc, log = self.run_main("--profile", "stock-v3.6")
        self.assertEqual(rc, 2)
        self.assertIn("'stock-v3.6' is not a profile", log)
        for spelling in ("stock-v3.5", "STOCK_V35", "oracles-production"):
            self.assertIn(spelling, log)

    @needs_v314_engine
    def test_no_flag_leaves_the_default_profile_exactly_where_it_was(self):
        """Every run that does not pass ``--profile`` is what it was before the flag
        existed: the fifteen validated flights' path is untouched."""
        rc, log = self.run_main()
        self.assertEqual(rc, 0, log)
        self.assertIn("profile=oracles-production", log)
        self.assertNotIn("(--profile)", log)

    def test_the_command_line_wins_over_a_config_files_profile(self):
        config = self.tmp / "run.toml"
        config.write_text('[fidelity]\nprofile = "stock-v3.5"\n'
                          '[run]\nengine = "3.5"\npreset = "DEMO_2DS_H"\n'
                          "[combine]\nborrowed = true\n", encoding="utf-8")
        rc, log = self.run_main(*self.v35_argv(), "--config", str(config),
                                "--profile", "oracles-production-v3.5")
        self.assertEqual(rc, 0, log)
        self.assertIn("stock-v3.5 -> oracles-production-v3.5 (--profile)", log)
        self.assertIn("fidelity profile       oracles-production-v3.5", log)


class AJobsWorkerIsGivenTheProfile(unittest.TestCase):
    """``_spawn_worker``'s explicit forward list. Five flags have gone missing from it
    by accident (``--diode-corrected``, ``--accept-unstamped``, ``--s2-jobs``,
    ``--preset``, the three threshold flags), each producing output that was
    silently made under different settings than the operator asked for."""

    def test_spawn_worker_forwards_the_profile(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        ns = types.SimpleNamespace(
            stages="234", out=root, chunks=1, s2_jobs=1, iat_file="",
            preset="DEMO_2DS_H", tas_file=None, presets=None, config=None,
            allow_mixed_config=False, accept_unstamped=False, diode_corrected=False,
            engine="3.5", worker_stall_min=30.0, profile="stock-v3.5",
        )
        with mock.patch.object(run_flight.subprocess, "Popen",
                               return_value=mock.Mock()) as popen:
            _proc, log_f = run_flight._spawn_worker([root / "a.2DS"], ns,
                                                    root / "worker.log")
        log_f.close()   # _spawn_worker hands the open handle back to its caller
        cmd = popen.call_args.args[0]
        self.assertIn("--profile", cmd)
        self.assertEqual(cmd[cmd.index("--profile") + 1], "stock-v3.5")

    def test_a_worker_gets_no_profile_flag_when_the_parent_passed_none(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        ns = types.SimpleNamespace(
            stages="234", out=root, chunks=1, s2_jobs=1, iat_file="",
            preset="DEMO_2DS_H", tas_file=None, presets=None, config=None,
            allow_mixed_config=False, accept_unstamped=False, diode_corrected=False,
            engine="3.1.4", worker_stall_min=30.0, profile=None,
        )
        with mock.patch.object(run_flight.subprocess, "Popen",
                               return_value=mock.Mock()) as popen:
            _proc, log_f = run_flight._spawn_worker([root / "a.2DS"], ns,
                                                    root / "worker.log")
        log_f.close()
        self.assertNotIn("--profile", popen.call_args.args[0])


class AProfileIsSelectedAndNeverDescribed(unittest.TestCase):
    """Decision #10 is about description. The flag's whole vocabulary is the registry's
    own names, taken from ``arrayprobe.config`` rather than re-listed here, so a flag
    can never reach a profile a config file could not -- and neither can state a field.
    """

    def setUp(self):
        self._profile = run_flight.PROFILE

    def tearDown(self):
        run_flight.PROFILE = self._profile

    def test_every_name_the_flag_accepts_is_a_name_a_config_file_accepts(self):
        from arrayprobe import config

        for name in sorted(config.PROFILES):
            with self.subTest(name=name), redirect_stdout(io.StringIO()):
                self.assertEqual(run_flight._apply_profile_flag(name), 0)
                self.assertIs(run_flight.PROFILE, config.PROFILES[name])

    def test_the_shipped_v35_profiles_are_among_them(self):
        from arrayprobe import config

        self.assertIn(profiles.STOCK_V35.name, config.PROFILES)
        self.assertIn(profiles.ORACLES_PRODUCTION_V35.name, config.PROFILES)


class EnhancementsWithoutAConfigIsRefusedBeforeAnythingRuns(_Run):
    """Item 4 of the cold-user report. Exit 2, and before preflight -- the two halves
    of the convention: a refused command line is 2, and a refusal that arrives after
    the stages have run is not a refusal, it is a postscript."""

    def test_it_exits_2(self):
        rc, log = self.run_main("--enhancements")
        self.assertEqual(rc, 2, log)
        self.assertIn("--enhancements needs --config", log)

    def test_nothing_ran_first(self):
        _rc, log = self.run_main("--enhancements")
        self.assertNotIn("PREFLIGHT", log)
        self.assertIn("Nothing was run", log)

    def test_the_other_refusal_that_used_code_1_was_swept_with_it(self):
        """``--enhancements`` was not alone. A sweep of every ``return`` in ``main``
        found one other pre-run refusal answering with 1: ``--diode-corrected`` with
        ``--chunks > 1``, which fires before preflight and whose own test says so.
        Two found, two fixed -- the class, not the instance."""
        rc, log = self.run_main("--diode-corrected", "--chunks", "2")
        self.assertEqual(rc, 2)
        self.assertIn("does not support --chunks", log)
        self.assertNotIn("PREFLIGHT", log)

    def test_a_check_against_the_data_is_still_code_1(self):
        """The other half of the convention, so 2 means something. Preflight reads the
        files themselves; a run refused *there* did work before refusing, and stays 1.
        """
        missing = self.tmp / "nothing_here.2DS"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main([str(missing), *self._engine_argv(),
                                  "--preset", "DEMO_2DS_H",
                                  "--out", str(self.out), "--yes"])
        self.assertEqual(rc, 1)
        self.assertIn("PREFLIGHT", buf.getvalue())


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
