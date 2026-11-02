# SPDX-License-Identifier: BSD-3-Clause
"""SPEED.md's stated cell counts are its tables' cells, recounted.

Tables A (probe x engine) and C (dataset x engine.probe) each end with a line
stating how many cells they hold and how many of each mark (measured, testable,
no data, refused). Those totals were typed, and nothing recounted them: on
2026-10-20 a row was removed from the release copy's Table C and the page went
on claiming 54 counted cells where the table held 48, with two "rows N-M"
references pointing one row off; on 2026-10-24 the dev copy was recounted by
hand twice in one morning. This recounts every cell by its leading mark and
compares the stated totals, so the next edit to a table fails here instead.
"""
from __future__ import annotations

import re
import unittest
from collections import Counter

from tests._hygiene import hygiene
from tests._repo import PKG_ROOT  # noqa: E402

_SPEED_MD = PKG_ROOT / "docs" / "developer" / "SPEED.md"

MARKS = ("⬤", "○", "▽", "✕")
XREF = "*cross-reference*"
_A_HEAD = "| Probe (probetype)"
_C_HEAD = "| Dataset | v3.1.4"
_A_LINE = re.compile(r"\*\*Table A: (\d+) cells — ⬤ (\d+) · ○ (\d+) · ▽ (\d+) · ✕ (\d+)\.\*\*")
_C_LINE = re.compile(r"\*\*Table C: (\d+) counted cells — "
                     r"⬤ (\d+) · ○ (\d+) · ▽ (\d+) · ✕ (\d+)\*\* "
                     r"\(plus (\d+) uncounted cross-references\)")
_C_INTRO = re.compile(r"\*\*(\d+) counted cells\.\*\*")
_BOTH = re.compile(r"\*\*(\d+) counted cells across Tables A and C\.")


def _table(lines: list[str], head: str) -> tuple[int, list[list[str]]]:
    i = next(k for k, line in enumerate(lines) if line.startswith(head))
    rows = []
    for line in lines[i + 2:]:
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip().strip("|").split("|")][1:])
    return i, rows


def _tally(rows: list[list[str]]) -> tuple[Counter, int, list[str]]:
    marks: Counter = Counter()
    xref = 0
    odd = []
    for row in rows:
        for cell in row:
            if cell.startswith(XREF):
                xref += 1
            elif cell[:1] in MARKS:
                marks[cell[:1]] += 1
            else:
                odd.append(cell[:40])
    return marks, xref, odd


def count_problems(text: str) -> list[str]:
    """Every disagreement between a stated total and the cells, as one line each."""
    lines = text.splitlines()
    problems = []
    _, a_rows = _table(lines, _A_HEAD)
    c_at, c_rows = _table(lines, _C_HEAD)
    a, _, a_odd = _tally(a_rows)
    c, c_xref, c_odd = _tally(c_rows)
    problems += [f"Table A cell without a mark: {o!r}" for o in a_odd]
    problems += [f"Table C cell without a mark: {o!r}" for o in c_odd]
    for name, line_re, tally, extra in (("A", _A_LINE, a, None), ("C", _C_LINE, c, c_xref)):
        m = line_re.search(text)
        if not m:
            problems.append(f"Table {name}'s count line not found")
            continue
        stated = [int(g) for g in m.groups()]
        held = [sum(tally.values())] + [tally[k] for k in MARKS]
        if extra is not None:
            held.append(extra)
        if stated != held:
            problems.append(f"Table {name} states {stated}, holds {held} (total, ⬤, ○, ▽, ✕"
                            + (", cross-references)" if extra is not None else ")"))
    intro = _C_INTRO.search("\n".join(lines[max(0, c_at - 6):c_at]))
    if not intro:
        problems.append("Table C's introductory count not found")
    elif int(intro.group(1)) != sum(c.values()):
        problems.append(f"Table C's introduction states {intro.group(1)}, holds {sum(c.values())}")
    both = _BOTH.search(text)
    if not both:
        problems.append("the across-both-tables count not found")
    elif int(both.group(1)) != sum(a.values()) + sum(c.values()):
        problems.append(f"across both tables: states {both.group(1)}, "
                        f"holds {sum(a.values()) + sum(c.values())}")
    return problems


@hygiene
class TheStatedCountsAreTheCells(unittest.TestCase):
    def test_speed_md_counts_match_its_tables(self):
        self.assertEqual([], count_problems(_SPEED_MD.read_text(encoding="utf-8")))

    def test_a_stale_count_is_named(self):
        """Must fire: the release copy's 2026-10-20 state, a row gone and the total left at 54."""
        page = (
            "| Probe (probetype) | v3.1.4 |\n|---|---|\n| **2D-S** | ⬤ x |\n| **CIP** | ✕ y |\n\n"
            "**Table A: 2 cells — ⬤ 1 · ○ 0 · ▽ 0 · ✕ 1.**\n\n"
            "Only the columns. **54 counted cells.**\n\n"
            "| Dataset | v3.1.4 · 2D-S |\n|---|---|\n| **ORACLES 2016** | ○ |\n"
            "| `otherwise` arm | *cross-reference* |\n\n"
            "**Table C: 54 counted cells — ⬤ 0 · ○ 1 · ▽ 0 · ✕ 0** "
            "(plus 1 uncounted cross-references).\n\n"
            "**56 counted cells across Tables A and C.**\n")
        problems = count_problems(page)
        self.assertEqual(3, len(problems), problems)
        self.assertTrue(any(p.startswith("Table C states [54") for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
