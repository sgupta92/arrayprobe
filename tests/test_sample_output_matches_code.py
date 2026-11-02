# SPDX-License-Identifier: BSD-3-Clause
"""The tutorial's quoted ``--version`` output equals what the CLI prints.

A prose-only spelling pass over the docs must not reach program output quoted in them.
The comparison draws its two sides from different places: the tutorial source text, and
the string ``cli.build_parser()`` builds, captured in-process through argparse.
"""
from __future__ import annotations

import contextlib
import io
import re
import unittest
from pathlib import Path

from arrayprobe import cli

ROOT = Path(__file__).resolve().parents[1]
TUTORIAL = ROOT / "docs" / "02a-tutorial.md"


@contextlib.contextmanager
def _argparse_exit():
    try:
        yield
    except SystemExit as e:  # argparse's version action exits 0
        if e.code not in (0, None):
            raise


def _cli_version_line() -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), _argparse_exit():
        cli.build_parser().parse_args(["--version"])
    return buf.getvalue().strip()


@unittest.skipUnless(TUTORIAL.is_file(), "needs docs/02a-tutorial.md")
class TutorialVersionLineMatchesCli(unittest.TestCase):
    def test_quoted_version_text_is_what_the_cli_prints(self):
        text = TUTORIAL.read_bytes().decode("utf-8")
        quoted = re.findall(r"^arrayprobe \S+ \(UIOOPS v.*engine\)\s*$", text, re.M)
        self.assertEqual(len(quoted), 1, "tutorial must quote the --version line exactly once")
        # A checkout that also carries the v3.1.4 engine may print a different engine token;
        # everything else (the spelling above all) must match character for character.
        norm = re.compile(r" v(3\.5|3\.1\.4) engine\)$")
        q = quoted[0].strip()
        self.assertTrue(norm.search(q), q)
        self.assertEqual(norm.sub(" v* engine)", q), norm.sub(" v* engine)", _cli_version_line()))


if __name__ == "__main__":
    unittest.main()
