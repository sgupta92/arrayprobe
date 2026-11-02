# SPDX-License-Identifier: BSD-3-Clause
"""What a first-time user reads in ``arrayprobe --help`` points them at the engine to use.

Three things a cold-user review found,
each pinned here against the real parser:

* The per-stage commands run the validation engine (UIOOPS v3.1.4). The top-level help, the
  stage commands' own help and the refusal for another version say so in plain words and name
  ``arrayprobe run``, the route to the default engine (v3.5), rather than only refusing.
* ``arrayprobe run``'s three parallelism flags carry help in plain words, with no internal
  stage label in the prose.
* ``read-binary --profile`` is required for ``--format spec`` and meaningless for the others.
  argparse cannot express that, so ``main`` enforces it with argparse's own error path (usage
  line, exit status 2) and the message lists the profile names, which the help lists too.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import re
import unittest
from unittest import mock

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import cli
from arrayprobe.profiles import PROFILES


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def _subparser(name: str) -> argparse.ArgumentParser:
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return sub.choices[name]


@needs_v314_engine
class ThePerStageCommandsSayTheyAreTheValidationEngine(unittest.TestCase):

    def test_the_top_level_help_points_at_run_for_processing(self):
        text = " ".join(cli.build_parser().format_help().split())
        self.assertIn("arrayprobe run", text)
        self.assertIn("the v3.1.4 validation engine", text)
        self.assertIn("v3.5", text)
        self.assertNotIn("THE PER-STAGE", text)

    def test_each_stage_command_says_so_in_its_own_help(self):
        for name in ("read-binary", "imgproc", "sizedist"):
            with self.subTest(command=name):
                text = " ".join(_subparser(name).format_help().split())
                self.assertIn("validation engine", text)
                self.assertIn("arrayprobe run", text)

    def test_the_refusal_tells_the_user_what_to_run_instead(self):
        code, _out, err = _run(["--uiops-version", "3.5", "sizedist", "p.nc", "o.nc",
                                "--tas-csv", "t.csv", "CIP", "6", "0", "9e5", "15", "X",
                                "20160906 064017", "--tree", "stock", "--engine", "3.5"])
        # --engine is required on sizedist (2026-09-26), so the refusal is sizedist's own
        # "not wired on 3.5" message rather than the generic per-stage one.
        self.assertEqual(code, 2)
        self.assertIn("arrayprobe run <config", err)
        self.assertIn('engine = "3.5"', err)
        self.assertIn('stages = "4"', err)


_IMGPROC = ["imgproc", "in.nc", "out.nc", "PIP", "1", "1", "X",
            "--profile", "stock-v3.1.4"]
_SIZEDIST = ["sizedist", "p.nc", "o.nc", "--tas-csv", "t.csv", "CIP", "6", "0", "9e5", "15",
             "X", "20160906 064017", "--tree", "stock"]


class TheStageVerbsAreNotACircle(unittest.TestCase):
    """imgproc and sizedist are v3.1.4 validation verbs. Where the engine is absent, and where
    3.5 is asked for, each refusal names the working route (`arrayprobe run` with
    [run].stages), never the other refusal. The route was measured working by
    test_run_flight_forwarding_and_stamps (v3.5 `--stages 3` alone on a stage-2 decode)."""

    def test_absent_engine_names_the_stage_route_not_engine_3_5(self):
        for argv, stage in ((_IMGPROC, "3"), (_SIZEDIST, "4")):
            with self.subTest(command=argv[0]):
                with mock.patch.object(cli, "_v314_engine_present", return_value=False):
                    code, _out, err = _run([*argv, "--engine", "3.1.4"])
                self.assertEqual(code, 2)
                self.assertIn("arrayprobe run", err)
                self.assertIn(f'stages = "{stage}"', err)
                self.assertNotIn("use --engine 3.5", err)

    def test_engine_3_5_refusal_names_the_stage(self):
        for argv, stage in ((_IMGPROC, "3"), (_SIZEDIST, "4")):
            with self.subTest(command=argv[0]):
                code, _out, err = _run([*argv, "--engine", "3.5"])
                self.assertEqual(code, 2)
                self.assertIn(f'stages = "{stage}"', err)
                self.assertIn('engine = "3.5"', err)


class TheRunParallelismFlagsAreExplained(unittest.TestCase):

    def test_each_flag_has_help_in_plain_words(self):
        actions = {opt: a for a in _subparser("run")._actions for opt in a.option_strings}
        for flag in ("--jobs", "--s2-jobs", "--chunks"):
            with self.subTest(flag=flag):
                text = actions[flag].help or ""
                self.assertGreater(len(text), 60)
                prose = text.replace("--s2-jobs", "").replace("--jobs", "")
                self.assertIsNone(re.search(r"\b[sS][1-4]c?\b", prose),
                                  f"{flag} help names an internal stage label: {text!r}")


@needs_v314_engine
class ReadBinaryProfileIsEnforcedAndListed(unittest.TestCase):

    def test_the_help_lists_every_profile_name(self):
        text = " ".join(_subparser("read-binary").format_help().split())
        # argparse's textwrap breaks at hyphens, so at a narrow terminal (a detached run's
        # COLUMNS) "arm-ena-stock-v3.5" prints as "arm-ena-" / "stock-v3.5"; rejoin those.
        text = re.sub(r"-\s+", "-", text)
        for name in PROFILES:
            with self.subTest(profile=name):
                self.assertIn(name, text)

    @needs_v314_engine
    def test_spec_without_a_profile_exits_2_and_lists_the_names(self):
        code, _out, err = _run(["read-binary", "in.raw", "out", "--format", "spec",
                                "--engine", "3.1.4"])
        self.assertEqual(code, 2)
        self.assertIn("needs --profile", err)
        for name in PROFILES:
            self.assertIn(name, err)

    def test_a_profile_on_a_format_that_reads_none_is_refused(self):
        code, _out, err = _run(["read-binary", "in.raw", "out", "--format", "sea",
                                "--profile", "stock-v3.5", "--engine", "3.5"])
        self.assertEqual(code, 2)
        self.assertIn("takes no --profile", err)

    @needs_v314_engine
    def test_an_unknown_profile_is_refused_before_anything_is_read(self):
        code, _out, err = _run(["read-binary", "absent.raw", "out", "--format", "spec",
                                "--profile", "STOCK_V35", "--engine", "3.1.4"])
        self.assertEqual(code, 2)
        self.assertIn("unknown --profile 'STOCK_V35'", err)
        self.assertIn("stock-v3.5", err)


class TheUiopsVersionHelpIsTrueInThisTree(unittest.TestCase):
    """``--uiops-version`` says it runs 3.1.4 only where v3.1.4 ships."""

    def _help(self, present):
        with mock.patch.object(cli, "_v314_engine_present", return_value=present):
            return " ".join(cli._uiops_version_help().split())

    def test_development_tree_keeps_the_validation_engine_text(self):
        self.assertIn("They run 3.1.4, the validation engine, only", self._help(True))

    def test_release_tree_does_not_claim_to_run_3_1_4(self):
        # A distribution without the v3.1.4 engine hides
        # --uiops-version from the public CLI rather than explaining that the engine is absent,
        # so the help is suppressed and --help names neither the flag nor the engine. The
        # purpose is unchanged: the help never claims to run an engine that is not there.
        with mock.patch.object(cli, "_v314_engine_present", return_value=False):
            self.assertIs(cli._uiops_version_help(), argparse.SUPPRESS)
            code, out, _err = _run(["--help"])
        self.assertEqual(code, 0)
        self.assertNotIn("uiops-version", out)
        self.assertNotIn("3.1.4", out)
        self.assertIn("arrayprobe run", out)


if __name__ == "__main__":
    unittest.main()
