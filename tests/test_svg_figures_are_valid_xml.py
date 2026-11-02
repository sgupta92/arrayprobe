# SPDX-License-Identifier: BSD-3-Clause
"""Every tracked SVG figure under ``docs/`` and ``examples/`` is well-formed XML.

A browser or GitHub's renderer refuses an SVG that is not well-formed, and shows
nothing in its place. ``docs/figures/evidence_ladder.svg`` failed this way: an XML
comment held ``--``, which XML forbids inside a comment, so the figure did not
render on GitHub. This guard parses each tracked SVG with ``xml.dom.minidom`` and
checks every comment for ``--``; a second case shows it firing on a synthetic bad
SVG string.
"""

from __future__ import annotations

import re
import subprocess
import unittest
import xml.dom.minidom
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import git_checkout_only

ROOT = Path(__file__).resolve().parents[1]
#: The trees whose figures a reader sees.
SCOPE = ("docs/", "examples/")
#: An XML comment and its body; the body may not contain ``--``.
_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)


def svg_problems(text: str) -> list[str]:
    """What is wrong with one SVG's text, as messages; empty when it is valid."""
    problems = []
    for body in _COMMENT.findall(text):
        if "--" in body or body.endswith("-"):
            problems.append(f"XML comment contains '--': {body.strip()[:60]!r}")
    try:
        xml.dom.minidom.parseString(text.encode("utf-8"))
    except Exception as exc:  # expat raises ExpatError; any failure is a finding
        problems.append(f"does not parse as XML: {exc}")
    return problems


def tracked_svgs(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--", *(s + "*.svg" for s in SCOPE)],
                         cwd=root, capture_output=True, check=True).stdout
    return sorted(p for p in out.decode("utf-8").split("\0") if p)


def invalid_svgs(root: Path) -> list[str]:
    bad = []
    for rel in tracked_svgs(root):
        path = root / rel
        if not path.is_file():
            continue
        for problem in svg_problems(path.read_text(encoding="utf-8")):
            bad.append(f"{rel}: {problem}")
    return bad


@hygiene
@git_checkout_only
class TrackedSvgsAreValid(unittest.TestCase):
    def test_some_svgs_are_in_scope(self):
        self.assertTrue(tracked_svgs(ROOT), "no tracked SVG found; the guard tests nothing")

    def test_every_tracked_svg_parses_and_has_no_double_dash_comment(self):
        self.assertEqual([], invalid_svgs(ROOT))


@hygiene
class GuardFires(unittest.TestCase):
    GOOD = ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            '<!-- a plain comment --><rect width="1" height="1"/></svg>')

    def test_a_valid_svg_passes(self):
        self.assertEqual([], svg_problems(self.GOOD))

    def test_a_double_dash_comment_is_reported(self):
        bad = self.GOOD.replace("a plain comment", "stage 1 -- stage 2")
        problems = svg_problems(bad)
        self.assertTrue(any("'--'" in p for p in problems), problems)
        self.assertTrue(any("does not parse" in p for p in problems), problems)

    def test_an_unclosed_element_is_reported(self):
        problems = svg_problems(self.GOOD.replace("</svg>", ""))
        self.assertTrue(any("does not parse" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
