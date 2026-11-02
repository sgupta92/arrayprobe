# SPDX-License-Identifier: BSD-3-Clause
"""No example notebook code cell may hold a collapsed line continuation.

A cell-split edit once joined a backslash-continued ``with`` statement into one line with a
run of spaces where the line break had been. It compiled and ran, so neither the compile check
nor ruff (which does not run on notebooks here) noticed. This tokenises each code cell and
fails on a gap of four or more spaces between two tokens on one line, other than before a
comment; strings and indentation are not tokens' gaps, so they never match. The firing case
plants a collapsed ``with`` and shows the check fails on it and passes on the repaired form.
"""

from __future__ import annotations

import io
import json
import tempfile
import tokenize
import unittest
from pathlib import Path

from tests._repo import REPO_ROOT, repo_only

_SKIP_BEFORE = (tokenize.COMMENT, tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER)
_SKIP_AFTER = (tokenize.INDENT, tokenize.DEDENT, tokenize.NL, tokenize.NEWLINE)


def collapsed_gaps(source: str) -> list[tuple[int, str]]:
    """(line number, line) for each run of 4+ spaces between two code tokens of one line."""
    lines = [("" if ln.lstrip().startswith(("%", "!")) else ln) for ln in source.split("\n")]
    found = []
    previous = None
    try:
        for tok in tokenize.generate_tokens(io.StringIO("\n".join(lines)).readline):
            if (previous is not None and tok.start[0] == previous.end[0]
                    and tok.type not in _SKIP_BEFORE and previous.type not in _SKIP_AFTER
                    and tok.start[1] - previous.end[1] >= 4):
                found.append((tok.start[0], tok.line.strip()[:100]))
            previous = tok
    except (tokenize.TokenError, IndentationError):
        pass  # a cell that does not tokenise is the compile check's finding, not this one's
    return found


def notebook_problems(path: Path) -> list[str]:
    nb = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        problems += [f"{path.name} cell {i} line {n}: {text}" for n, text in collapsed_gaps(src)]
    return problems


@repo_only
class TestNoCollapsedContinuations(unittest.TestCase):

    def test_no_example_notebook_cell_has_a_collapsed_line(self):
        notebooks = [p for p in sorted((REPO_ROOT / "examples").rglob("*.ipynb"))
                     if ".ipynb_checkpoints" not in p.parts]
        self.assertTrue(notebooks, "no example notebooks found")
        self.assertEqual([m for nb in notebooks for m in notebook_problems(nb)], [])


class TestCollapsedLineCheckFires(unittest.TestCase):

    def test_a_collapsed_with_fails_and_the_repaired_form_passes(self):
        bad = 'with open("a") as f,         open("b") as g:\n    pass\n'
        good = 'with (\n    open("a") as f,\n    open("b") as g,\n):\n    pass\n'
        keep = 'x = f(1)    # an aligned comment\nprint("a    b")\n%matplotlib inline\n'
        self.assertEqual(len(collapsed_gaps(bad)), 1)
        self.assertEqual(collapsed_gaps(good), [])
        self.assertEqual(collapsed_gaps(keep), [])
        with tempfile.TemporaryDirectory() as d:
            nb = {"cells": [{"cell_type": "code", "source": bad, "metadata": {}, "outputs": []}]}
            path = Path(d) / "planted.ipynb"
            path.write_text(json.dumps(nb), encoding="utf-8")
            self.assertEqual(len(notebook_problems(path)), 1)


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
