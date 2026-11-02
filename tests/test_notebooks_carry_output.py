# SPDX-License-Identifier: BSD-3-Clause
"""Every shipped example notebook carries the output its code really produced.

WHAT THIS PROTECTS. Author instruction, 2026-09-11: *"the example notebooks
should have some output plots or results in them, not just cells without
output."* Measured that day, all five tracked notebooks under ``examples/``
had ``"outputs": []`` on every one of their 24 code cells -- a reader opening
one on GitHub saw the code and nothing it produces. ``test_examples_execute``
already proves they *run*; nothing proved the shipped file shows what running
them gives you, and a notebook re-saved from a fresh kernel silently loses it
again.

HOW IT DECIDES. A code cell must carry output unless it *cannot* produce any:
no ``print``, no ``matplotlib`` call, no ``display``, and no trailing bare
expression (checked on the cell's AST, not by eye). That exemption is derived
from the source, not from a hand-kept list of cell indices that would rot on
the next edit. Two notebooks are additionally required to carry a rendered
image, because their whole point is the plot.

REGENERATE with, from the repository root::

    .venv/Scripts/python.exe scripts/execute_example_notebooks.py

THIS GUARD IS EXECUTED, NOT READ. ``test_the_check_fires_on_a_stripped_copy``
strips the outputs from a real notebook in memory and asserts the checker
reports it -- four checks in this repository matched nothing while reading
fine.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import repo_only

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"

# Every notebook under examples/ is a shipped, executed example. There are no
# exclusions today; a notebook that legitimately cannot be executed here (one
# needing the 67 GB ORACLES archive, say) is added below with its reason, and
# examples/README.md's "each one executes end to end" claim is amended in the
# same commit.
NOT_EXECUTED: dict[str, str] = {}

# Notebooks whose stated purpose includes showing a plot, so a text-only
# rendering is a regression even if every cell has a stream output.
MUST_CARRY_AN_IMAGE = {
    "1_getting_started/01_start_here.ipynb",  # "Output 1-4": shadows, size distribution, total
    "1_getting_started/02_quickstart.ipynb",        # "5. Plot the size distribution"
    "3_validation/01_validate_against_a_product.ipynb",  # "Plot the residuals over time"
}


def _notebooks() -> list[Path]:
    if not EXAMPLES.is_dir():
        return []
    return sorted(p for p in EXAMPLES.rglob("*.ipynb")
                  if p.relative_to(EXAMPLES).as_posix() not in NOT_EXECUTED
                  and ".ipynb_checkpoints" not in p.parts)


_MAGIC = re.compile(r"^\s*(?:%%?\w|!)")
_DRAWS = ("print", "display", "show", "imshow", "plot", "figure", "subplots", "savefig")


def _runs_at_top_level(node: ast.AST) -> list[ast.AST]:
    """The nodes that execute when the cell runs: function and class bodies do not."""
    out, stack = [], [node]
    while stack:
        n = stack.pop()
        out.append(n)
        for child in ast.iter_child_nodes(n):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef, ast.Lambda)):
                stack.append(child)
    return out


def _could_produce_output(source: str) -> bool:
    """Would running this cell print, draw or echo anything at all?

    A call to print/display or a matplotlib drawing call that runs when the cell runs, or a
    trailing bare expression. A call inside a function the cell only defines does not run,
    so a setup cell that imports pyplot and defines drawing helpers is not asked for output.
    """
    code = "\n".join("" if _MAGIC.match(ln) else ln for ln in source.splitlines())
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return True  # cannot tell -- demand output rather than excuse the cell
    for n in _runs_at_top_level(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in _DRAWS:
                return True
    return bool(tree.body) and isinstance(tree.body[-1], ast.Expr)


def _has_image(cell: dict) -> bool:
    return any(
        any(key.startswith("image/") for key in output.get("data", {}))
        for output in cell.get("outputs", [])
    )


def check_notebook(nb: dict, name: str) -> list[str]:
    """Return one complaint per problem found. Empty list means the file is fine."""
    problems: list[str] = []
    # A cell tagged v314-only needs the v3.1.4 engine, which the public package does not ship:
    # the release builder drops it, and the outputs are written without that engine, so it
    # carries none.
    code = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"
            and "v314-only" not in c.get("metadata", {}).get("tags", [])]
    if not code:
        return [f"{name}: no code cells at all"]

    with_output = [c for c in code if c.get("outputs")]
    if not with_output:
        problems.append(
            f"{name}: none of its {len(code)} code cells carries any output"
        )

    for i, cell in enumerate(code, start=1):
        if cell.get("outputs"):
            continue
        source = "".join(cell.get("source", []))
        if _could_produce_output(source):
            first = next((ln for ln in source.splitlines() if ln.strip()), "")
            problems.append(
                f"{name} code cell {i} prints or draws but carries no output "
                f"(starts {first.strip()[:60]!r})"
            )

    if name in MUST_CARRY_AN_IMAGE and not any(_has_image(c) for c in code):
        problems.append(f"{name}: declared a plotting example but carries no image output")

    return problems


@repo_only
@hygiene
class ExampleNotebooksCarryOutput(unittest.TestCase):
    def test_every_declared_exclusion_names_a_real_notebook(self) -> None:
        for name in NOT_EXECUTED:
            self.assertTrue((EXAMPLES / name).is_file(),
                            f"NOT_EXECUTED names {name!r}, which does not exist")

    def test_every_must_plot_notebook_exists(self) -> None:
        for name in MUST_CARRY_AN_IMAGE:
            self.assertTrue((EXAMPLES / name).is_file(),
                            f"MUST_CARRY_AN_IMAGE names {name!r}, which does not exist")

    def test_every_shipped_notebook_carries_its_output(self) -> None:
        problems: list[str] = []
        for notebook in _notebooks():
            nb = json.loads(notebook.read_text(encoding="utf-8"))
            problems.extend(check_notebook(nb, notebook.relative_to(EXAMPLES).as_posix()))
        self.assertEqual(
            [], problems,
            "example notebook(s) shipped without output -- regenerate with\n"
            "  .venv/Scripts/python.exe scripts/execute_example_notebooks.py\n"
            + "\n  ".join(problems),
        )

    def test_the_check_fires_on_a_stripped_copy(self) -> None:
        """Mutation test: strip the outputs and the checker must complain."""
        notebooks = _notebooks()
        self.assertTrue(notebooks)
        notebook = notebooks[0]
        name = notebook.relative_to(EXAMPLES).as_posix()
        nb = json.loads(notebook.read_text(encoding="utf-8"))
        self.assertEqual([], check_notebook(nb, name),
                         "precondition: the real notebook passes")

        stripped = copy.deepcopy(nb)
        for cell in stripped["cells"]:
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
        problems = check_notebook(stripped, name)
        self.assertTrue(problems, "stripping every output did not make the check fire")
        self.assertTrue(any("carries any output" in p for p in problems), problems)

    def test_the_check_fires_when_only_the_plot_is_missing(self) -> None:
        """A notebook with text but no figure is still a regression."""
        name = sorted(MUST_CARRY_AN_IMAGE)[0]
        nb = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
        self.assertEqual([], check_notebook(nb, name), "precondition: it passes as shipped")
        for cell in nb["cells"]:
            if cell.get("cell_type") != "code":
                continue
            cell["outputs"] = [o for o in cell.get("outputs", [])
                               if not any(k.startswith("image/") for k in o.get("data", {}))]
        problems = check_notebook(nb, name)
        self.assertTrue(any("no image output" in p for p in problems), problems)


@hygiene
@repo_only
class TheOutputRuleReadsWhatRuns(unittest.TestCase):
    """Both ways, on planted sources: a call that runs needs output; one only defined does not."""

    def test_a_definition_only_setup_cell_needs_no_output(self) -> None:
        src = ("%matplotlib inline\nimport matplotlib.pyplot as plt\n\n"
               "def draw(ax):\n    ax.imshow([[0]])\n    plt.show()\n")
        self.assertFalse(_could_produce_output(src))

    def test_a_drawing_call_that_runs_needs_output(self) -> None:
        self.assertTrue(_could_produce_output(
            "import matplotlib.pyplot as plt\nplt.plot([1])\nx = 1\n"))
        self.assertTrue(_could_produce_output("for i in range(2):\n    print(i)\n"))
        self.assertTrue(_could_produce_output("x = 1\nx\n"))

    def test_the_must_plot_list_is_matched_by_path(self) -> None:
        """Every MUST_CARRY_AN_IMAGE entry is a notebook the main test reaches by that key."""
        keys = {p.relative_to(EXAMPLES).as_posix() for p in _notebooks()}
        self.assertTrue(MUST_CARRY_AN_IMAGE <= keys, sorted(MUST_CARRY_AN_IMAGE - keys))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
