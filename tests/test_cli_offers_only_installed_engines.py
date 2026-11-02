# SPDX-License-Identifier: BSD-3-Clause
"""Without the v3.1.4 engine the CLI offers only 3.5, and naming 3.1.4 explains why (exit 2)."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from arrayprobe import cli
from arrayprobe_uiops.engine_absence import ABSENT_MESSAGE

_COMBINE = ["combine", "--flight-date", "20160101", "--summary-time", "1", "a", "b"]


def _engine_action(parser, command):
    import argparse
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return next(a for a in sub.choices[command]._actions if "--engine" in a.option_strings)


class TestAbsentEngineIsNotOffered(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(cli, "_v314_engine_present", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_offered_choices_are_3_5_only(self):
        self.assertEqual(set(cli._offered_engines()), {"3.5"})

    def test_the_per_stage_subcommands_are_not_registered(self):
        import argparse
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        for command in cli._V314_ONLY_SUBCOMMANDS:
            with self.subTest(command=command):
                self.assertNotIn(command, sub.choices)

    def test_default_engine_is_3_5(self):
        args = cli.build_parser().parse_args(["engines"])
        self.assertIsNone(args.engines_version)  # None resolves to the package default
        import uiops
        self.assertEqual(uiops.engine(args.engines_version).version, "3.5")

    def test_passing_3_1_4_exits_2_with_the_message(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli.main([*_COMBINE, "--engine", "3.1.4"])
        self.assertEqual(rc, 2)
        self.assertIn(ABSENT_MESSAGE, err.getvalue())
        self.assertNotIn("invalid choice", err.getvalue())

    def test_each_per_stage_subcommand_exits_2_with_the_message(self):
        # combine is not here: it runs on v3.5 (--borrowed-combine), and its 3.1.4 refusal is
        # test_passing_3_1_4_exits_2_with_the_message above.
        for command in ("read-binary", "sizedist", "imgproc"):
            for argv in ([command], [command, "--help"], [command, "--engine", "9.9"]):
                with self.subTest(argv=argv):
                    err = io.StringIO()
                    with redirect_stderr(err):
                        rc = cli.main(argv)
                    self.assertEqual(rc, 2)
                    self.assertIn(cli._V314_ABSENT_MESSAGE, err.getvalue())
                    self.assertNotIn("invalid choice", err.getvalue())


class TestPresentEngineIsOffered(unittest.TestCase):
    def test_offered_choices_include_3_1_4(self):
        with mock.patch.object(cli, "_v314_engine_present", return_value=True):
            self.assertEqual(set(cli._offered_engines()), {"3.1.4", "3.5"})
            action = _engine_action(cli.build_parser(), "combine")
            self.assertEqual(action.metavar, "{3.1.4,3.5}")

    def test_an_unknown_engine_is_still_refused_by_argparse(self):
        err = io.StringIO()
        present = mock.patch.object(cli, "_v314_engine_present", return_value=True)
        with present, redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            cli.main([*_COMBINE, "--engine", "9.9"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("9.9", err.getvalue())


if __name__ == "__main__":
    unittest.main()
