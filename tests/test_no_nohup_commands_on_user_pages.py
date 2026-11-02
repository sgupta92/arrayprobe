# SPDX-License-Identifier: BSD-3-Clause
"""The pages a user reads give no ``nohup`` command to run.

``nohup`` is a POSIX utility, not a given in a Windows shell, so a page that tells a reader to
launch a run as ``nohup <command> &`` hands part of its audience a command that fails. A long
run is described instead as running in the background with its output written to a log, and
the command shown is the plain one. Twice in one night a rewrite introduced such a command
into a shipped page while replacing a development launcher; this guard refuses the next.

It matches the command form only -- ``nohup`` followed by a command -- so a sentence about the
mechanism ("``nohup`` redirects stdin") passes. Prose that claims runs go "under ``nohup``" is
not caught; that wording is a review matter.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SURFACES = ("README.md", "enhancements_uiops/README.md", "enhancements_soda2/README.md",
            "docs/[0-9]*.md", "docs/developer/*.md", "examples/**/*.ipynb", "examples/**/*.md",
            "enhancements_uiops/docs/*.md", "enhancements_soda2/docs/*.md")
#: ``nohup`` followed by whitespace and then something other than a closing quote or backtick:
#: the start of a command, not the name of the utility in a sentence.
NOHUP_COMMAND = re.compile(r"\bnohup[ \t]+(?![`'\"])\S")


def offenders(text: str) -> list[str]:
    return [m.group(0) for m in NOHUP_COMMAND.finditer(text)]


def surfaces() -> list[Path]:
    return sorted(p for pat in SURFACES for p in ROOT.glob(pat) if p.is_file())


class NoNohupCommandsOnUserPages(unittest.TestCase):
    def test_no_user_page_gives_a_nohup_command(self):
        bad = [f"{p.relative_to(ROOT).as_posix()}: {hit!r}" for p in surfaces()
               for hit in offenders(p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_check_fires_on_a_command(self):
        self.assertTrue(offenders("nohup .venv/Scripts/python.exe -m arrayprobe run x.toml &"))
        self.assertTrue(offenders("detached (for example `nohup <command> > run.log 2>&1 &`)"))

    def test_the_check_passes_a_sentence_about_the_mechanism(self):
        self.assertEqual(offenders("there is nobody to ask: ``nohup`` redirects stdin"), [])
        self.assertEqual(offenders("a detached run (under `nohup`), CI, or a script"), [])


if __name__ == "__main__":
    unittest.main()
