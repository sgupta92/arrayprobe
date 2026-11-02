# SPDX-License-Identifier: BSD-3-Clause
"""Every way to ask for the v3.1.4 engine says it is not part of this package."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

import arrayprobe
from arrayprobe import _v314_lazy, cli

_ARGV = {
    "read-binary": ["read-binary", "--format", "spec", "--engine", "3.1.4", "in", "out"],
    "imgproc": ["imgproc", "--profile", "STOCK_V314", "--engine", "3.1.4",
                "a", "b", "P", "1", "1", "x"],
    "sizedist": ["sizedist", "--tas-csv", "t.csv", "--tree", "stock", "--engine", "3.1.4",
                 "a", "b", "P", "6", "1", "1", "1", "x", "20160101"],
    "combine": ["combine", "--flight-date", "20160101", "--summary-time", "1",
                "--engine", "3.1.4", "a", "b"],
}


class TestAbsentEngineNamesDevelopmentRepository(unittest.TestCase):
    def test_every_staged_subcommand_names_it_and_exits_2(self):
        for name, argv in _ARGV.items():
            with self.subTest(command=name), mock.patch.object(
                    cli, "_v314_engine_present", return_value=False):
                err = io.StringIO()
                with redirect_stderr(err):
                    rc = cli.main(argv)
                self.assertEqual(rc, 2)
                self.assertIn("not part of this package", err.getvalue())
                self.assertNotIn("Traceback", err.getvalue())

    def test_run_with_a_3_1_4_config_names_it_with_and_without_port_validation(self):
        import os
        import tempfile
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "examples" / "start_here" / "run.toml"
        if not src.exists():
            self.skipTest("Examples/start_here/run.toml not in this tree is not distributed "
                          "with the package")
        text = src.read_text(encoding="utf-8")
        text = text.replace('profile = "stock-v3.5"', 'profile = "oracles-production"')
        text = text.replace('engine = "3.5"', 'engine = "3.1.4"')
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "run.toml")
            Path(cfg).write_text(text, encoding="utf-8")
            for extra in ([], ["--port-validation"]):
                with self.subTest(extra=extra), mock.patch.object(
                        cli, "_v314_engine_present", return_value=False):
                    err = io.StringIO()
                    with redirect_stderr(err):
                        rc = cli.main(["run", cfg, *extra])
                    self.assertEqual(rc, 2)
                    self.assertEqual(err.getvalue().count("not part of this package"), 1)
                    self.assertNotIn("Traceback", err.getvalue())

    def test_run_flight_entry_names_it(self):
        from tests import _run_flight_state

        from arrayprobe.driver import run_flight
        _run_flight_state.preserve(self, run_flight)
        with mock.patch.object(run_flight, "_v314_engine_present", return_value=False):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = run_flight.main(["x.2DS", "--preset", "DEMO_2DS_H", "--engine", "3.1.4",
                                      "--port-validation"])
        self.assertEqual(rc, 2)
        self.assertIn("not part of this package", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_the_project_selector_names_it_rather_than_returning_the_bare_package(self):
        with mock.patch.object(_v314_lazy, "engine_present", return_value=False):
            with self.assertRaises(_v314_lazy.V314EngineAbsent) as caught:
                arrayprobe.engine("3.1.4").load()
        self.assertIn("not part of this package", str(caught.exception))
        with mock.patch.object(_v314_lazy, "engine_present", return_value=False):
            self.assertEqual(arrayprobe.engine("3.5").load().__name__, "arrayprobe_uiops")

    def test_the_uiops_selector_names_it_for_a_missing_v314_module(self):
        import uiops

        def missing(dotted):
            raise ModuleNotFoundError(f"No module named {dotted!r}", name=dotted)
        with mock.patch.object(uiops.importlib, "import_module", side_effect=missing):
            with self.assertRaises(_v314_lazy.V314EngineAbsent):
                uiops.engine("3.1.4").module("imgproc")
            with self.assertRaises(ModuleNotFoundError) as other:
                uiops.engine("3.5").module("imgproc")
        self.assertNotIsInstance(other.exception, _v314_lazy.V314EngineAbsent)

    def test_shared_messages_name_it(self):
        self.assertIn("not part of this package", _v314_lazy.ABSENT_MESSAGE)
        self.assertIn("not part of this package", arrayprobe._V314_ABSENT)


if __name__ == "__main__":
    unittest.main()
