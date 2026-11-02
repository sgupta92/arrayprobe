# SPDX-License-Identifier: BSD-3-Clause
"""The pages a user reads carry no internal plan references.

Ids such as ``plan 4H.16``, ``plan row 12``, ``queue row 13`` or ``W9 row Q-1`` point into the
development project's planning records, which a reader of the package cannot open. They were
reworded out of the READMEs, the numbered documentation pages (several generated from
docstrings) and the example notebooks; this guard refuses the next one. Developer pages,
enhancement design records and
the docstrings and comments in src, tests and tools were cleaned too, as was the one runtime
string, the demo preset's provenance in ``run_flight.py``.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SURFACES = ("README.md", "enhancements_uiops/README.md", "enhancements_soda2/README.md",
            "docs/[0-9]*.md", "examples/**/*.ipynb", "docs/developer/*.md",
            "enhancements_uiops/docs/*.md", "enhancements_soda2/docs/*.md")
PLAN_REF = re.compile(r"plan (?:item |row )?\d+[A-Z]?\.?\d*\b|queue row \d+|W\d+ row [A-Z]-\d+"
                      r"|\bS?4[A-Z]\.\d+\b|cached-lantern")


def offenders(text: str) -> list[str]:
    return [m.group(0) for m in PLAN_REF.finditer(text)]


def surfaces() -> list[Path]:
    return sorted(p for pat in SURFACES for p in ROOT.glob(pat) if p.is_file())


class NoPlanRefsOnUserPages(unittest.TestCase):
    def test_no_user_page_cites_the_development_plan(self):
        bad = [f"{p.relative_to(ROOT).as_posix()}: {hit}" for p in surfaces()
               for hit in offenders(p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_check_fires(self):
        for s in ("(plan 4H.16 / queue row 13, W9 row Q-1)", "plan row 12", "cached-lantern §4H.5"):
            self.assertTrue(offenders(s), s)
        self.assertEqual(offenders("the plan in Section 4 and row 12 of Table 2"), [])

    def test_the_sweep_reads_pages(self):
        # A sweep that reads nothing passes vacuously.
        self.assertGreaterEqual(len(surfaces()), 20)


if __name__ == "__main__":
    unittest.main()
