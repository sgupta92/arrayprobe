# SPDX-License-Identifier: BSD-3-Clause
"""``make_demo_flight.py`` is the ten-minute-quickstart input.

**Why a dedicated test rather than trusting ``test_end_to_end.py``.** That
suite exercises the *builder function* through ``run_flight.py``'s low-level
stage functions, never the tool's own CLI, and never the combine step (S4c)
-- which is the one stage this tool's output needs a specific naming
convention to reach at all (found by actually running the CLI, not by
reading it: a file named ``demo.2DS`` reaches S2-S4 and then dies in
``combine_sizedist`` on ``int('')`` from an unparseable stem). This test
exercises the packaged CLI end-to-end, the way a stranger following the
quickstart actually will.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402
from tests._slow import slow

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "make_demo_flight.py"

_SPEC = importlib.util.spec_from_file_location("make_demo_flight", TOOL)
assert _SPEC is not None and _SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["make_demo_flight"] = make_demo_flight
_SPEC.loader.exec_module(make_demo_flight)


class BuildingTheFlight(unittest.TestCase):
    @needs_v314_engine
    def test_writes_the_declared_number_of_records(self):
        with tempfile.TemporaryDirectory() as td:
            path = make_demo_flight.build_demo_flight(
                Path(td) / "base160101000000.2DS", n_seconds=4)
            self.assertTrue(path.is_file())
            # RECORD_WORDS * 2 bytes/word * 2 records-per-second (image + HK).
            from arrayprobe.readers import spec
            self.assertEqual(path.stat().st_size, 4 * 2 * spec.RECORD_WORDS * 2)


class TheDemoPresetIsRegistered(unittest.TestCase):
    def test_demo_2ds_h_exists_and_says_it_is_synthetic(self):
        _RF_SPEC = importlib.util.spec_from_file_location(
            "run_flight", ROOT / "scripts" / "run_flight.py")
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules["run_flight"] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)
        preset = run_flight.PRESETS["DEMO_2DS_H"]
        self.assertIn("synthetic", preset.provenance.lower())
        self.assertEqual(preset.orientation, "H")


@slow  # real subprocess CLI, full quickstart pipeline (2026-09-14: ~9.0s measured)
class TheCliRunsEndToEnd(unittest.TestCase):
    """The actual acceptance bar: a stranger's copy-pasted two commands."""

    @needs_v314_engine
    def test_the_quickstart_commands_complete_and_write_a_combined_product(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            raw = tmp / "base160101000000.2DS"
            build = subprocess.run(
                [sys.executable, str(TOOL), str(raw), "--seconds", "3"],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertTrue(raw.is_file())

            out = tmp / "decoded"
            run = subprocess.run(
                # --yes is not optional here and its absence is not cosmetic:
                # since the confirm step (`622fecd`, "confirm-or-declare before a run
                # starts") the driver asks `proceed with this configuration?
                # [y/N]` and, given no stdin, logs "no answer; not starting"
                # and exits 2. This test predates that commit and was never
                # updated, so it had been asserting rc == 0 against a driver
                # that could no longer return it non-interactively. The
                # documented quickstart in docs/02-user-guide.md
                # already carries --yes; this brings the test onto the same
                # command the documentation gives a stranger.
                [sys.executable, str(ROOT / "scripts" / "run_flight.py"),
                 "--engine", "3.1.4", "--port-validation", "--preset", "DEMO_2DS_H",
                 "--stages", "234c", "--yes",
                 "--out", str(out), str(raw)],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("ALL DONE", run.stdout)
            combined = list(out.glob("*.combined.H.2DS_2.cdf"))
            self.assertEqual(len(combined), 1,
                             f"expected exactly one combined product, found {combined}")


@slow  # real subprocess CLI, two quickstart pipelines
class ThePrintedCommandsRunAsPrinted(unittest.TestCase):
    """The builder's printed "next" commands, pasted verbatim, complete.

    The engine-3.5 command needs the aircraft TAS file the builder now writes; before it, the
    default engine could not run the demo at all. Both commands name ``--engine``, which every
    preset requires -- the printed command lacked it and exited 2.
    """

    @needs_v314_engine
    def test_both_printed_commands_complete(self):
        import shlex
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            raw = tmp / "base160101000000.2DS"
            build = subprocess.run([sys.executable, str(TOOL), str(raw), "--seconds", "3"],
                                   cwd=tmp, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertTrue(make_demo_flight.demo_aircraft_path(raw).is_file())
            # The tool prints the interpreter as this platform spells it (make_demo_flight.py).
            py = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
            cmds = [ln.strip() for ln in build.stdout.splitlines()
                    if ln.strip().startswith(f"{py} scripts/run_flight.py")]
            # Without --with-config the engine-3.5 hint says how to get run.toml beside the flight.
            self.assertIn("re-run with --with-config", build.stdout)
            # Only the engine 3.1.4 command remains a run_flight.py route (dev checkouts).
            self.assertEqual(len(cmds), 1, build.stdout)
            for i, cmd in enumerate(cmds):
                argv = shlex.split(cmd, posix=False)[2:]  # drop the interpreter and script
                out = tmp / f"out{i}"
                run = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "run_flight.py"), *argv,
                     "--out", str(out)], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, cmd + "\n" + run.stdout + run.stderr)
                self.assertTrue(list(out.glob("sd.*")), f"{cmd}: no sd product")


class TheDemoAircraftFile(unittest.TestCase):
    def test_it_covers_every_record_second_with_realistic_values(self):
        from arrayprobe import ncio
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "base160101000000.2DS"
            path = make_demo_flight.write_demo_aircraft(raw, n_seconds=5)
            t = np.ravel(ncio.ncread(str(path), "Time"))
            v = np.ravel(ncio.ncread(str(path), "TAS"))
        for s in range(40, 45):
            self.assertIn(60600.0 + s, list(t))
        self.assertTrue(((v > 85) & (v < 110)).all())
        self.assertEqual(len(set(t.tolist())), len(t))


class TheQuickstartInputShipsWithTheInstalledPackage(unittest.TestCase):
    """Plan row 4's actual gap: ``scripts/`` is not installed.

    ``[tool.setuptools.packages.find] where = ["src"]`` ships ``src/arrayprobe``
    and nothing else, so for as long as the builder lived in ``scripts/`` the
    quickstart's own first step worked from a git clone and nowhere else --
    ``pip install arrayprobe`` gave you a console script that could not produce
    its own documented input. These tests pin the fix at the level the failure
    happened: *where the module resolves from*, not whether it runs.
    """

    def test_the_builder_resolves_from_inside_the_installed_package(self):
        import arrayprobe
        from arrayprobe.tools import make_demo_flight as packaged
        package_root = Path(arrayprobe.__file__).resolve().parent
        self.assertTrue(
            Path(packaged.__file__).resolve().is_relative_to(package_root),
            f"{packaged.__file__} is outside {package_root}: a pip install "
            "would not ship it, which is the defect this move fixed")

    def test_the_published_tools_path_is_the_same_object_not_a_copy(self):
        from arrayprobe.tools import make_demo_flight as packaged

        # The docs publish scripts/make_demo_flight.py and
        # test_quickstart_runs.py executes that path verbatim. A shim that
        # re-implemented rather than re-exported could drift from the package
        # silently, so assert identity rather than mere equality of behaviour.
        self.assertIs(make_demo_flight.build_demo_flight, packaged.build_demo_flight)
        self.assertIs(make_demo_flight.main, packaged.main)

    @needs_v314_engine
    def test_the_subcommand_writes_a_real_raw_file(self):
        from arrayprobe.cli import main as cli_main

        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "base160101000000.2DS"
            rc = cli_main(["make-demo-flight", str(raw), "--seconds", "3"])
            self.assertEqual(rc, 0)
            from arrayprobe.readers import spec
            self.assertEqual(raw.stat().st_size, 3 * 2 * spec.RECORD_WORDS * 2)

    def test_the_subcommand_and_the_tool_accept_the_same_flags(self):
        # The subcommand delegates to the tool's own main(), so a flag added to
        # one must reach the other. Compare the two parsers' option strings
        # rather than trusting the delegation to stay faithful.
        from arrayprobe.cli import build_parser

        sub = build_parser()._subparsers._group_actions[0].choices["make-demo-flight"]
        cli_flags = {o for a in sub._actions for o in a.option_strings}
        self.assertLessEqual({"--seconds", "--tas-mps"}, cli_flags)


if __name__ == "__main__":
    unittest.main()


class TestNextLinesNameOnlyInstalledEngines(unittest.TestCase):
    def test_no_engine_314_command_when_the_engine_is_absent(self):
        from unittest import mock

        from arrayprobe.tools import make_demo_flight as mdf

        real = importlib.util.find_spec

        def fake(name, *a, **k):
            return None if name == "arrayprobe.reject" else real(name, *a, **k)

        with mock.patch.object(mdf.importlib.util, "find_spec", fake):
            text = "\n".join(mdf.next_lines("f.2DS", "f.aircraft.cdf", "py"))
        self.assertNotIn("--engine 3.1.4", text)
        self.assertIn("arrayprobe run ./run.toml f.2DS --yes", text)
        self.assertIn("examples/start_here/run.toml", text)
        self.assertNotIn("scripts/run_flight.py --preset DEMO_2DS_H --engine 3.5", text)
        self.assertNotIn("3.1.4", text)

    def test_engine_314_command_when_present(self):
        from arrayprobe.tools import make_demo_flight as mdf

        if importlib.util.find_spec("arrayprobe.reject") is None:
            self.skipTest("engine 3.1.4 not installed")
        self.assertIn("--engine 3.1.4", "\n".join(mdf.next_lines("f.2DS", "a.cdf", "py")))
