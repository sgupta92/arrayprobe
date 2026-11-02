# SPDX-License-Identifier: BSD-3-Clause
"""Without the v3.1.4 engine, the command line and the selectors never offer it.

Each check runs in a subprocess with ``ARRAYPROBE_FORCE_V314_ABSENT=1`` (the test hook
``arrayprobe._v314_lazy.engine_present`` honours), so the help texts are the ones a distribution
without the engine prints. The same checks with the hook unset prove the engine branch still
prints them, so one file tests both sides.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

_FORBIDDEN = ("3.1.4", "port-validation", "uiops-version", "libm-pow", "validation engine",
              "arrayprobe imgproc", "arrayprobe sizedist", "arrayprobe read-binary")
# combine is not here: it runs on v3.5 too (--borrowed-combine), as the user guide shows.
_V314_SUBCOMMANDS = ("imgproc", "sizedist", "read-binary")

_COLLECT = r"""
import argparse, contextlib, io, json, sys
from arrayprobe import cli

def helptext(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            cli.main(argv)
        except SystemExit:
            pass
    return out.getvalue()

parser = cli.build_parser()
subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)][0]
names = sorted(subs.choices)
texts = {"": helptext(["--help"])}
for name in names:
    texts[name] = helptext([name, "--help"])

def raises(call):
    try:
        call()
    except ImportError:
        return True
    return False

import arrayprobe, uiops
json.dump({"names": names, "texts": texts,
           "uiops_raises": raises(lambda: uiops.engine("3.1.4")),
           "project_raises": raises(lambda: arrayprobe.engine("3.1.4"))}, sys.stdout)
"""


def _collect(absent: bool) -> dict:
    env = dict(os.environ)
    env.pop("ARRAYPROBE_FORCE_V314_ABSENT", None)
    if absent:
        env["ARRAYPROBE_FORCE_V314_ABSENT"] = "1"
    proc = subprocess.run([sys.executable, "-c", _COLLECT], env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=300)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:])
    return json.loads(proc.stdout)


def _engine_installed() -> bool:
    from arrayprobe._v314_lazy import engine_present
    return engine_present()


class TestAbsentSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.absent = _collect(absent=True)

    def test_the_hook_makes_the_engine_absent(self):
        env = dict(os.environ, ARRAYPROBE_FORCE_V314_ABSENT="1")
        proc = subprocess.run(
            [sys.executable, "-c",
             "from arrayprobe._v314_lazy import engine_present; print(engine_present())"],
            env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.stdout.strip(), "False", proc.stderr[-2000:])

    def test_an_unknown_engine_refusal_names_no_absent_spelling(self):
        # The refusal once listed every alias, '3.1.4', 'oracles' and 'v3.1.4' among them, on an
        # install where none of them works.
        env = dict(os.environ, ARRAYPROBE_FORCE_V314_ABSENT="1")
        code = ("import arrayprobe\n"
                "try:\n    arrayprobe.engine('nope')\n"
                "except Exception as e:\n    print(e)\n")
        proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=120)
        self.assertIn("unknown engine", proc.stdout, proc.stderr[-2000:])
        for spelling in ("3.1.4", "oracles"):
            with self.subTest(spelling=spelling):
                self.assertNotIn(spelling, proc.stdout)

    def test_every_subcommand_help_was_collected(self):
        self.assertIn("", self.absent["texts"])
        self.assertIn("run", self.absent["names"])
        self.assertEqual(set(self.absent["texts"]) - {""}, set(self.absent["names"]))
        for command, text in self.absent["texts"].items():
            with self.subTest(command=command or "arrayprobe"):
                self.assertIn("usage: arrayprobe", text)

    def test_no_v314_only_subcommand_is_registered(self):
        for name in _V314_SUBCOMMANDS:
            with self.subTest(command=name):
                self.assertNotIn(name, self.absent["names"])

    def test_no_help_text_names_the_engine_or_its_flags(self):
        for command, text in self.absent["texts"].items():
            for word in _FORBIDDEN:
                with self.subTest(command=command or "arrayprobe", word=word):
                    self.assertNotIn(word, text)

    def test_run_help_names_nothing_of_the_engine(self):
        for word in _FORBIDDEN:
            with self.subTest(word=word):
                self.assertNotIn(word, self.absent["texts"]["run"])

    def test_per_stage_subcommands_exit_2_with_the_absent_message(self):
        env = dict(os.environ, ARRAYPROBE_FORCE_V314_ABSENT="1")
        from arrayprobe._v314_lazy import ABSENT_MESSAGE
        for name in _V314_SUBCOMMANDS:
            with self.subTest(command=name):
                proc = subprocess.run([sys.executable, "-m", "arrayprobe", name, "--help"],
                                      env=env, capture_output=True, text=True,
                                      encoding="utf-8", timeout=120)
                self.assertEqual(proc.returncode, 2, proc.stderr[-2000:])
                self.assertIn(ABSENT_MESSAGE.strip(), proc.stderr)
                self.assertNotIn("3.1.4", proc.stdout)

    def test_uiops_selector_refuses_v314_at_selection(self):
        self.assertTrue(self.absent["uiops_raises"])

    def test_project_selector_refuses_v314_at_selection(self):
        self.assertTrue(self.absent["project_raises"])


@unittest.skipUnless(_engine_installed(), "the v3.1.4 engine is not installed here")
class TestPresentSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.present = _collect(absent=False)

    def test_the_per_stage_subcommands_are_registered(self):
        for name in _V314_SUBCOMMANDS:
            with self.subTest(command=name):
                self.assertIn(name, self.present["names"])

    def test_run_help_offers_the_engine_and_its_flags(self):
        text = self.present["texts"]["run"]
        for word in ("3.1.4", "port-validation"):
            with self.subTest(word=word):
                self.assertIn(word, text)

    def test_selectors_return_a_handle(self):
        self.assertFalse(self.present["uiops_raises"])
        self.assertFalse(self.present["project_raises"])


if __name__ == "__main__":
    unittest.main()
