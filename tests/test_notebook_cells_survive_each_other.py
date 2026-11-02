# SPDX-License-Identifier: BSD-3-Clause
"""A notebook cell must not delete what a later cell reads, and a slow cell must say so.

WHAT THIS PROTECTS, and what it cost to learn it. The 2026-09-16 cold-start dry run
ran
``03_validate_against_a_product.ipynb`` and got, after **1508 s** of real work::

    File "03_validate_against_a_product.ipynb#cell7", line 6, in <module>
      ...
    FileNotFoundError: [Errno 2] No such file or directory:
      '...\\Temp\\tmp7h8fzyou\\sd.base160101000000.H.nc'

Cell 1 had bound ``tmp = tempfile.TemporaryDirectory()`` and every later cell read files
under it. Cell 5 then wrote ``with tempfile.TemporaryDirectory() as tmp:``, so at the end
of that ``with`` block the name ``tmp`` was rebound to a string, cell 1's object lost its
last reference, and its ``__del__`` deleted the directory cell 7 was about to open. The
notebook ran twenty-five minutes and then failed on a file that had existed the whole time
until an unrelated cell took its name away.

TWO CHECKS, both static -- they read the notebooks' ASTs and execute nothing, so they cost
milliseconds where ``test_examples_execute`` costs minutes, and they fire in a checkout
where the example-data gate is closed and that cell never runs at all:

1. :func:`shadowed_across_cells` -- (a) a later cell rebinds the name that holds an
   earlier cell's temporary directory or file, so that object is collected and everything
   under it is deleted, whether or not the name is ever mentioned again (the defect
   above: cell 7 opened a path *derived* from ``tmp``, not ``tmp``); and (b) a later
   cell's ``with ... as`` shadows an earlier name that a cell after the block reads.
2. :func:`expensive_cell_problems` -- a cell that starts minutes of real work must print
   before it starts, and its notebook must say in markdown what that costs. Notebook 03
   stubs ``run_flight.log`` silent by design, so without this the reader watches a blank
   screen for a quarter of an hour with nothing saying why.

THIS GUARD IS EXECUTED, NOT READ (the project's guard doctrine):
:class:`TheShadowCheckFires` reinstates the real historical defect in an in-memory copy of
the real notebook -- renaming ``year_tmp`` back to ``tmp`` -- and asserts the checker names
it. Four checks in this repository matched nothing while reading fine.
"""
from __future__ import annotations

import ast
import json
import re
import time
import unittest
from pathlib import Path

from tests._repo import repo_only

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"

#: Calls whose cost is minutes of real decoding, not seconds. A cell that makes one of
#: these must announce itself first. Add to this as slow entry points appear.
EXPENSIVE_CALLS = ("check_oracles_subset",)

#: What a notebook carrying an expensive cell must say somewhere in its markdown.
_COST_WORDS = ("minute", "minutes")


def notebooks() -> list[Path]:
    return (
        sorted(p for p in EXAMPLES.rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts)
        if EXAMPLES.is_dir() else []
    )


# ``%matplotlib``, ``%%time``, ``!cmd``; not a continuation line such as ``% (a, b)``.
_MAGIC = re.compile(r"\s*(%%?\w|!)")


def code_cells(nb: dict) -> list[str]:
    # IPython magics (``%matplotlib inline``, ``!pip``) are not Python: blank those lines.
    return ["\n".join("" if _MAGIC.match(ln) else ln
                      for ln in "".join(c["source"]).splitlines())
            for c in nb["cells"] if c["cell_type"] == "code"]


def markdown(nb: dict) -> str:
    return "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")


def _bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(names bound to last for the cell's life, names bound only for a ``with`` block)."""
    durable: set[str] = set()
    scoped: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                for name in _target_names(item.optional_vars):
                    scoped.add(name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                durable |= _target_names(target)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
            durable |= _target_names(node.target)
        elif isinstance(node, ast.For | ast.AsyncFor):
            durable |= _target_names(node.target)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            durable.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                durable.add(alias.asname or alias.name.split(".")[0])
    return durable - scoped, scoped


def _target_names(target) -> set[str]:
    if target is None:
        return set()
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _loads(tree: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


#: Calls that return an object which owns files on disk for as long as it is referenced.
#: Rebinding the only name holding one deletes what it owns -- which is how notebook 03's
#: cell 1 directory vanished while cells 3-7 were still reading paths derived from it.
RESOURCE_FACTORIES = ("TemporaryDirectory", "NamedTemporaryFile", "TemporaryFile")


def _resource_owners(tree: ast.AST) -> set[str]:
    """Names this cell assigns a :data:`RESOURCE_FACTORIES` call to."""
    owners: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _call_name(node.value) in RESOURCE_FACTORIES:
                for target in node.targets:
                    owners |= _target_names(target)
    return owners


def shadowed_across_cells(sources: list[str]) -> list[str]:
    """Rebindings by which one cell destroys what a later cell needs.

    ``sources`` are the notebook's code cells in order. Two findings, each a real
    mechanism:

    (a) **the owner is rebound.** An earlier cell held a temporary directory or file in
        ``N``; a later cell binds ``N`` to something else. The earlier object loses its
        last reference and deletes itself -- taking with it every path derived from it,
        whether or not any later cell mentions ``N`` again. This is the 1508-second
        defect: cell 7 read ``sd``, a path under the directory cell 1 had held in ``tmp``.

    (b) **a released name is read.** A later cell's ``with ... as N`` shadows an earlier
        durable ``N``, and a cell after the block reads ``N`` -- which by then is whatever
        the context manager yielded, released.

    Empty means neither is present.
    """
    trees = [ast.parse(src) for src in sources]
    durable = [_bindings(t)[0] for t in trees]
    scoped = [_bindings(t)[1] for t in trees]
    loads = [_loads(t) for t in trees]
    owners = [_resource_owners(t) for t in trees]

    findings = []
    for j in range(len(sources)):
        rebound = durable[j] | scoped[j]
        for name in sorted(rebound):
            owned_earlier = [i + 1 for i in range(j) if name in owners[i]]
            if owned_earlier:
                findings.append(
                    f"{name!r} holds a temporary directory/file created in cell(s) "
                    f"{owned_earlier}; cell {j + 1} rebinds it, so that object is collected "
                    f"and everything it owns is deleted -- including paths later cells "
                    f"derived from it")
        for name in sorted(scoped[j]):
            bound_earlier = [i + 1 for i in range(j) if name in durable[i]]
            read_later = [k + 1 for k in range(j + 1, len(sources)) if name in loads[k]]
            if bound_earlier and read_later and not [i + 1 for i in range(j)
                                                    if name in owners[i]]:
                findings.append(
                    f"{name!r} is bound in cell(s) {bound_earlier}, rebound by "
                    f"`with ... as {name}` in cell {j + 1} (which releases it at the end of "
                    f"the block), and read again in cell(s) {read_later}")
    return findings


def _first_lineno(tree: ast.AST, predicate) -> int | None:
    linenos = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call) and predicate(n) and hasattr(n, "lineno")]
    return min(linenos) if linenos else None


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def expensive_cell_problems(sources: list[str], md: str) -> list[str]:
    """Every cell that starts minutes of work must announce itself, and the notebook must say so."""
    problems = []
    for i, src in enumerate(sources, start=1):
        tree = ast.parse(src)
        slow_at = _first_lineno(tree, lambda n: _call_name(n) in EXPENSIVE_CALLS)
        if slow_at is None:
            continue
        print_at = _first_lineno(tree, lambda n: _call_name(n) == "print")
        if print_at is None or print_at > slow_at:
            problems.append(
                f"cell {i} calls {'/'.join(EXPENSIVE_CALLS)} at line {slow_at} with no print "
                f"before it: a reader watching a stubbed-silent run sees a blank screen")
        if not any(word in md.lower() for word in _COST_WORDS):
            problems.append(
                f"cell {i} costs minutes of real decoding and no markdown cell says so")
    return problems


# The notebooks live in the repository's examples/, above the packaged tree.
@repo_only
class NoCellDeletesWhatALaterCellReads(unittest.TestCase):
    def test_at_least_one_notebook_is_present(self) -> None:
        """The empty-glob failure this project keeps finding, guarded here too."""
        self.assertTrue(notebooks(), f"no *.ipynb files found under {EXAMPLES}")

    def test_no_notebook_shadows_a_live_name_with_a_context_manager(self) -> None:
        failures = []
        for path in notebooks():
            nb = json.loads(path.read_text(encoding="utf-8"))
            failures += [f"{path.name}: {f}" for f in shadowed_across_cells(code_cells(nb))]
        self.assertEqual([], failures, "notebook cell(s) release a name a later cell reads:\n  "
                         + "\n  ".join(failures))

    def test_every_expensive_cell_announces_itself(self) -> None:
        failures = []
        for path in notebooks():
            nb = json.loads(path.read_text(encoding="utf-8"))
            failures += [f"{path.name}: {p}"
                         for p in expensive_cell_problems(code_cells(nb), markdown(nb))]
        self.assertEqual([], failures, "slow notebook cell(s) run in silence:\n  "
                         + "\n  ".join(failures))


class TheShadowCheckFires(unittest.TestCase):
    """The guard is executed, not read: reinstate the real defect and see it caught."""

    NOTEBOOK = EXAMPLES / "3_validation/01_validate_against_a_product.ipynb"

    @repo_only
    def test_the_historical_defect_in_notebook_03_is_reported(self) -> None:
        """Rename ``year_tmp`` back to ``tmp`` -- the source that failed after 1508 s."""
        nb = json.loads(self.NOTEBOOK.read_text(encoding="utf-8"))
        sources = code_cells(nb)
        self.assertEqual([], shadowed_across_cells(sources), "the fixed notebook is clean")
        mutated = [src.replace("year_tmp", "tmp") for src in sources]
        self.assertNotEqual(sources, mutated, "no 'year_tmp' left in notebook 03 to mutate; "
                            "this test no longer reconstructs the 2026-09-16 defect")
        findings = shadowed_across_cells(mutated)
        self.assertTrue(findings, "the checker did not report the defect that cost 1508 s")
        self.assertIn("'tmp'", findings[0])

    def test_a_clean_sequence_is_not_reported(self) -> None:
        clean = ["tmp = TemporaryDirectory()\nout = tmp.name",
                 "with TemporaryDirectory() as other:\n    work(other)",
                 "read(out)"]
        self.assertEqual([], shadowed_across_cells(clean))

    def test_a_shadow_nothing_reads_afterwards_is_not_reported(self) -> None:
        """Precision: shadowing an ordinary finished name is not this defect."""
        reused = ["label = 'first pass'\nprint(label)",
                  "with open('f') as label:\n    work(label)"]
        self.assertEqual([], shadowed_across_cells(reused))

    def test_rebinding_a_temporary_directory_owner_is_reported_on_its_own(self) -> None:
        """Mechanism (a): no later cell need mention the name for the files to vanish."""
        findings = shadowed_across_cells(
            ["tmp = TemporaryDirectory()\nout = Path(tmp.name)",
             "tmp = TemporaryDirectory()",
             "read(out / 'sd.nc')"])
        self.assertEqual(1, len(findings), findings)
        self.assertIn("everything it owns is deleted", findings[0])


@repo_only
class TheClosedGateCostsNothing(unittest.TestCase):
    """What a fresh clone runs: no subsets, so section 2d must skip, in milliseconds.

    ``test_examples_execute`` exercises this too, but only as part of a run that costs
    minutes where the gate is open. This one is the stranger's path on its own, and it
    asserts what they are *told* -- a bare `pass` would satisfy "it did not raise".
    """

    NOTEBOOK = EXAMPLES / "3_validation/01_validate_against_a_product.ipynb"

    def test_the_gated_cell_skips_and_says_how_to_regenerate(self) -> None:
        import contextlib
        import io
        import os
        import tempfile

        nb = json.loads(self.NOTEBOOK.read_text(encoding="utf-8"))
        gated = [src for src in code_cells(nb) if "oracles_subsets" in src]
        self.assertEqual(1, len(gated), "expected exactly one gated section-2d cell")

        with tempfile.TemporaryDirectory() as fresh_clone:
            (Path(fresh_clone) / "tests" / "data" / "oracles_subsets").mkdir(parents=True)
            here = Path.cwd()
            buf = io.StringIO()
            try:
                os.chdir(fresh_clone)
                started = time.monotonic()
                with contextlib.redirect_stdout(buf):
                    exec(compile(gated[0], "<03 gated cell>", "exec"), {"__name__": "__main__"})
                elapsed = time.monotonic() - started
            finally:
                os.chdir(here)

        printed = buf.getvalue()
        self.assertIn("gate is closed", printed)
        # One message in every tree since 1c1a152: the cutter script does not ship, so the cell
        # says what the reader supplies instead of naming a command only this repository has.
        self.assertIn("archived product of your own", printed)
        self.assertNotIn("cut_oracles_subset", printed)
        self.assertLess(elapsed, 5.0, f"the closed gate should cost nothing, took {elapsed:.1f}s")


class TheAnnouncementCheckFires(unittest.TestCase):
    def test_a_silent_expensive_cell_is_reported(self) -> None:
        silent = ["results = {}\nfor year in (2016, 2017):\n"
                  "    results[year] = make_demo_reference.check_oracles_subset(year, d)"]
        problems = expensive_cell_problems(silent, "## a heading with no cost stated")
        self.assertEqual(2, len(problems), problems)
        self.assertIn("no print before it", problems[0])
        self.assertIn("no markdown cell says so", problems[1])

    def test_an_announced_expensive_cell_is_accepted(self) -> None:
        announced = ["print('minutes, not seconds')\n"
                     "results = check_oracles_subset(2016, d)"]
        self.assertEqual([], expensive_cell_problems(announced, "costs a few minutes"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

# A repository sweep: run before every full suite.
#
PRESUITE_GUARD = True
