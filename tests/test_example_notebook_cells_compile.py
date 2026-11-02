# SPDX-License-Identifier: BSD-3-Clause
"""Every code cell of every example notebook must compile.

A notebook edit once committed cells whose string literal had been split across two
lines in the JSON; nothing short of executing the notebook noticed. This compiles
each code cell (IPython magics and ``!`` shell lines blanked) so a syntax error
fails here. The firing cases plant a temporary notebook, so the check is shown to
fail on a broken cell and pass on a valid one.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tests._repo import REPO_ROOT, repo_only

# ``%name``, ``%%name`` or ``!cmd``; a continuation line ``% (a, b)`` is Python modulo.
_MAGIC = re.compile(r"\s*(?:%{1,2}\w|!)")


def cell_source(cell: dict) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src


def blank_ipython(source: str) -> str:
    """Blank magic (``%``) and shell (``!``) lines, keeping line numbers."""
    return "\n".join("" if _MAGIC.match(line) else line for line in source.split("\n"))


def compile_problems(path: Path) -> list[str]:
    """One message per code cell of the notebook at ``path`` that does not compile."""
    nb = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        try:
            compile(blank_ipython(cell_source(cell)), f"{path.name}[cell {i}]", "exec")
        except SyntaxError as exc:
            problems.append(f"{path.name} cell {i}: {exc.msg} (line {exc.lineno})")
    return problems


def _write(directory: Path, cells: list[str]) -> Path:
    nb = {"cells": [{"cell_type": "code", "source": c, "metadata": {}, "outputs": [],
                     "execution_count": None} for c in cells],
          "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    path = directory / "planted.ipynb"
    path.write_text(json.dumps(nb), encoding="utf-8")
    return path


@repo_only
class TestExampleNotebooksCompile(unittest.TestCase):

    def test_every_code_cell_compiles(self):
        notebooks = sorted((REPO_ROOT / "examples").rglob("*.ipynb"))
        self.assertTrue(notebooks, "no example notebooks found")
        problems = [p for nb in notebooks if ".ipynb_checkpoints" not in nb.parts
                    for p in compile_problems(nb)]
        self.assertEqual(problems, [])


class TestCompileCheckFires(unittest.TestCase):

    def test_a_split_literal_fails_and_a_valid_cell_passes(self):
        with tempfile.TemporaryDirectory() as d:
            bad = _write(Path(d), ["x = 1\nprint('a\nb')"])
            self.assertEqual(len(compile_problems(bad)), 1)
            good = _write(Path(d), ["%matplotlib inline\n!pip list\nx = 1\n"
                                    "print('a\\nb')\ny = ('%d'\n     % 3)"])
            self.assertEqual(compile_problems(good), [])


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
