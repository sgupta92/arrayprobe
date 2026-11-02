# SPDX-License-Identifier: BSD-3-Clause
"""Every run must say which engine it means: `--engine` has no default.

History. the engine-scope rule (the author, 2026-09-20): v3.5 with enhancements is what
*default* means, and a v3.1.4 number may be quoted only for ORACLES 2D-S/HVPS. `--engine`
defaulted to `3.1.4`, so on
2026-09-21 a non-ORACLES run without it began to be refused, and ORACLES and DEMO stayed
exempt. **On 2026-09-23 the author removed the exemption:
`--engine` is required for every preset**, like `--preset` since 2026-09-15.

**The default is removed, not flipped**: flipping it would change what every existing command
line means, including archived run logs that reproduce published figures. Refusing makes each
of them fail loudly instead. `--engine 3.1.4` spelled out works on any campaign; what is refused
is not saying.

Scope, measured rather than assumed: `load_presets` runs in `main`'s pre-parse pass and writes
declared presets into `PRESETS`, so a user's own `--presets` campaign is covered as well as the
built-in ORACLES and DEMO presets.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from tests._repo import needs_v314_engine  # noqa: E402

import run_flight  # noqa: E402

ARM_PRESETS = """
[[campaign]]
name = "TESTCAMP_2DS_H"
probe = "2DS"
orientation = "H"
project = "TESTCAMP"
d_choice = 6
sa_method = 0
pres_pa = 86470.0
temp_c = 14.5
provenance = "synthetic preset for tests/test_engine_default_refused_off_oracles.py"
"""


class ANonOraclesPresetWithNoEngineIsRefused(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.presets = self.tmp / "campaigns.toml"
        self.presets.write_text(ARM_PRESETS, encoding="utf-8")
        self._saved = dict(run_flight.PRESETS)
        self.addCleanup(lambda: (run_flight.PRESETS.clear(),
                                 run_flight.PRESETS.update(self._saved)))
        # `main()` assigns module-level configuration globals (PROFILE, ENGINE, PROBE_CASE, the
        # threshold overrides ...) and does not restore them -- it is a process entry point, so
        # it has never needed to. Calling it from a test therefore LEAKS that state into every
        # test that runs afterwards in the same process.
        #
        # Found the hard way on 2026-09-21: the `--profile stock-v3.5` runs below left PROFILE
        # set, and two tests in test_engine_flag_parity.py then failed on a DEMO preset they had
        # never touched, reporting `profile=stock-v3.5`. The failures looked like defects in the
        # new refusal and were pollution from this file.
        #
        # Snapshotting every UPPER_CASE module global is deliberately blunter than naming the
        # ones main() happens to set today: the next flag to add a global would otherwise
        # reintroduce exactly this, silently, in whichever unrelated test ran next.
        self._globals = {k: v for k, v in vars(run_flight).items()
                         if k.isupper() and not k.startswith("_")}
        self.addCleanup(lambda: [setattr(run_flight, k, v)
                                 for k, v in self._globals.items()])

    #: The first words of this guard's own refusal. Tests below assert on THIS, not on the exit
    #: code alone, because a non-ORACLES run legitimately meets several other refusals before it
    #: gets anywhere -- engine 3.5 needs a v3.5-cited profile, and `stock-v3.5` needs a TAS file.
    #: Each is a real guard working. Chasing them by adding flags until rc stops being 2 makes
    #: the test a description of today's flag set; asking "did MY refusal fire" does not.
    MY_REFUSAL = "no --engine was given"

    def _run(self, *extra):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = run_flight.main([
                "--presets", str(self.presets), "--preset", "TESTCAMP_2DS_H",
                "--dry-run", "--yes", *extra, str(self.tmp / "x.2DS"),
            ])
        return rc, buf.getvalue()

    def test_no_engine_flag_is_refused_with_exit_2(self):
        rc, out = self._run()
        self.assertEqual(
            rc, 2,
            "a TESTCAMP run with no --engine was accepted; it would have run on 3.1.4 and "
            "produced a number the engine-scope rule forbids quoting")
        self.assertIn(self.MY_REFUSAL, out, "refused, but not by this guard")

    def test_engine_3_5_spelled_out_is_not_refused_here(self):
        """It may still fail later for other reasons; it must not fail for THIS one.

        `--profile stock-v3.5` is passed with it because engine 3.5 independently refuses a
        profile whose citations are to the v3.1.4 tree, and the argparse default is
        `oracles-production`. That refusal is correct and predates this guard -- measured while
        writing this test, which is why the flag is here rather than the assertion being
        loosened to hide it.
        """
        _rc, out = self._run("--engine", "3.5", "--profile", "stock-v3.5")
        self.assertNotIn(
            self.MY_REFUSAL, out,
            "--engine 3.5 was given explicitly and this guard still refused it; it is firing "
            "on a case the author has decided")

    @needs_v314_engine
    def test_engine_3_1_4_spelled_out_is_allowed(self):
        """The author may deliberately reproduce a pre-v3.3 product on a non-ORACLES campaign.

        Refusing that would make the guard a policy rather than a check on ambiguity -- it
        exists because the command line did not SAY, not because 3.1.4 is forbidden.
        """
        _rc, out = self._run("--engine", "3.1.4", "--port-validation")
        self.assertNotIn(self.MY_REFUSAL, out,
                         "an explicit --engine 3.1.4 must be honoured, not refused")

    def test_the_equals_spelling_counts_as_explicit(self):
        """`--engine=3.5` is the same choice as `--engine 3.5`.

        Written because the detection reads argv, and a check that recognised only the
        space-separated form would refuse a command line that had in fact said which engine
        it meant.
        """
        _rc, out = self._run("--engine=3.5", "--profile", "stock-v3.5")
        self.assertNotIn(self.MY_REFUSAL, out,
                         "--engine=3.5 was not recognised as an explicit choice")


class NoPresetIsExemptAnyMore(unittest.TestCase):
    """(2026-09-23) the ORACLES and DEMO exemption is gone; every preset must name an
    engine. These run built-in presets, so they bite without a user campaign file."""

    MY_REFUSAL = ANonOraclesPresetWithNoEngineIsRefused.MY_REFUSAL

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        saved = {k: v for k, v in vars(run_flight).items() if k.isupper() and not k.startswith("_")}
        self.addCleanup(lambda: [setattr(run_flight, k, v) for k, v in saved.items()])

    def _run(self, preset, *extra):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = run_flight.main(["--preset", preset, "--dry-run", "--yes", *extra,
                                  str(self.tmp / "x.2DS")])
        return rc, buf.getvalue()

    def test_the_exemption_constant_is_gone(self):
        self.assertFalse(hasattr(run_flight, "ENGINE_DEFAULT_OK_PROJECTS"),
                         "the ORACLES/DEMO exemption from --engine was removed")

    def test_every_builtin_preset_without_engine_is_refused(self):
        for preset in sorted(run_flight.PRESETS):
            with self.subTest(preset=preset):
                rc, out = self._run(preset)
                self.assertEqual(rc, 2, out)
                self.assertIn(self.MY_REFUSAL, out)

    @needs_v314_engine
    def test_an_oracles_preset_with_engine_3_1_4_is_not_refused_here(self):
        _rc, out = self._run("ORACLES_2016_2DS_H", "--engine", "3.1.4", "--port-validation")
        self.assertNotIn(self.MY_REFUSAL, out)


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
