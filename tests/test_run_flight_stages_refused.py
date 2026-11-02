# SPDX-License-Identifier: BSD-3-Clause
"""``--stages`` / ``[run].stages`` naming no stage is refused, exit 2, before anything runs.

Found 2026-09-26 by a cold-user walk: every stage test in ``main`` is ``"<n>" in args.stages``,
so ``--stages 9`` (or ``S34``, or an empty string, or a TOML ``stages = "9"``) matched none of
them and the run printed ``ALL DONE``, exit 0, having decoded, framed and sized nothing. A
caller scripting on the exit code could not tell that from a finished run.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests._driver import driver_source

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from tests._repo import needs_v314_engine  # noqa: E402

import _run_flight_state  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault(_SPEC.name, run_flight)
run_flight = sys.modules[_SPEC.name]
if not hasattr(run_flight, "main"):
    _SPEC.loader.exec_module(run_flight)


class StagesNamingNothingAreRefused(unittest.TestCase):

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.raw = self.root / "base160101000000.2DS"
        self.raw.write_bytes(b"")      # never opened: the refusal comes first
        self.lines: list[str] = []
        real_log = run_flight.log
        run_flight.log = lambda msg, *a, **k: self.lines.append(str(msg))
        self.addCleanup(setattr, run_flight, "log", real_log)

    def _main(self, *argv) -> int:
        with redirect_stdout(io.StringIO()):
            return run_flight.main(["--preset", "DEMO_2DS_H", "--engine", "3.1.4",
                                    "--port-validation", "--yes",
                                    "--out", str(self.root / "out"), *argv, str(self.raw)])

    @needs_v314_engine
    def test_unknown_stage_characters_exit_2_naming_them(self):
        for stages in ("9", "S34", "1234", "23x"):
            with self.subTest(stages=stages):
                self.lines.clear()
                self.assertEqual(self._main("--stages", stages), 2)
                text = "\n".join(self.lines)
                self.assertIn("names no stage", text)
                self.assertIn("Nothing was run", text)
                self.assertFalse((self.root / "out").exists(), "a refused run wrote output")

    @needs_v314_engine
    def test_an_empty_stage_string_exits_2(self):
        self.assertEqual(self._main("--stages", ""), 2)
        self.assertIn("names no stage", "\n".join(self.lines))

    @needs_v314_engine
    def test_a_config_stages_value_is_checked_the_same_way(self):
        cfg = self.root / "run.toml"
        cfg.write_text('[fidelity]\nprofile = "oracles-production"\n'
                       '[run]\nengine = "3.1.4"\nstages = "9"\n', encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            rc = run_flight.main(["--preset", "DEMO_2DS_H", "--engine", "3.1.4",
                                  "--port-validation", "--yes",
                                  "--config", str(cfg), "--stages", "9",
                                  "--out", str(self.root / "out"), str(self.raw)])
        self.assertEqual(rc, 2)

    @needs_v314_engine
    def test_a_flag_whose_stage_is_not_run_is_named(self):
        """``--borrowed-combine --stages 234`` wrote no combined product and said ALL DONE;
        ``--chunks``/``--s2-jobs`` outside their stage likewise did nothing, unremarked."""
        for flags, stages, needle in ((["--borrowed-combine"], "234",
                                       "--borrowed-combine has no effect"),
                                      (["--chunks", "4"], "2", "--chunks has no effect"),
                                      (["--s2-jobs", "3"], "34", "--s2-jobs has no effect")):
            with self.subTest(flags=flags):
                self.lines.clear()
                self._main("--stages", stages, *flags, "--dry-run")
                self.assertTrue(any(needle in m for m in self.lines), self.lines[-5:])
        self.lines.clear()
        self._main("--stages", "234", "--dry-run")
        self.assertFalse(any("has no effect" in m for m in self.lines))

    def test_the_valid_codes_are_exactly_those_main_tests_for(self):
        src = driver_source("run_flight.py").read_text(encoding="utf-8")
        for code in run_flight.STAGE_CODES:
            self.assertIn(f'"{code}" in args.stages', src)


if __name__ == "__main__":
    unittest.main()
