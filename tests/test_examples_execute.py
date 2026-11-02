# SPDX-License-Identifier: BSD-3-Clause
"""Every notebook under ``examples/`` actually runs, end to end.

WHAT THIS PROTECTS. ``examples/README.md`` claims "each one executes end to
end with no campaign data" -- until 2026-09-10 nothing checked
that claim mechanically, so a notebook could bit-rot (an API it calls
renamed, a file it reads moved) and the README would go on asserting
otherwise. ``jupyter``/``nbconvert`` are deliberately not project
dependencies (see ``examples/README.md``), so this reads each notebook's own
JSON and executes its code cells directly with ``exec``, in one shared
namespace per notebook (matching how a person clicking through cells top to
bottom actually runs it) -- no new dependency, no subprocess, no notebook
server.

**What this does not check**: that a cell's *output* is sensible, only that
it runs without raising. A notebook that executes but silently computes
nonsense would pass this and should be caught by whatever assertions the
notebook's own cells choose to print or assert.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path

from tests._optional import OPTIONAL_PACKAGES, importable
from tests._profile_registry_guard import module_hooks
from tests._repo import repo_only
from tests._slow import slow

#: Packages only the example notebooks need (examples/README.md), never the package: xarray
#: reads the output files there (the author's xarray-in-examples request). A notebook
#: importing one skips where it is absent.
EXAMPLE_ONLY_PACKAGES = ("xarray",)

# A notebook imports arrayprobe_uiops.register_image_assisted, which registers a profile for
# the rest of the process; found by a per-module registry trace under ARRAYPROBE_SLOW=1
# (2026-09-26). The guard restores the registry when this module ends.
setUpModule, tearDownModule = module_hooks()

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
PORT_ROOT = REPO_ROOT  # the package sits at the repository root
TOOLS = (PORT_ROOT / "scripts").resolve()


def _restore_dir(folder: Path, before: dict[Path, bytes]) -> None:
    """Put ``folder``'s files back to ``before``: rewrite changed ones, remove new ones."""
    if not folder.is_dir():
        return
    for path in folder.iterdir():
        if path.is_file() and path not in before:
            path.unlink()
    for path, data in before.items():
        if not path.is_file() or path.read_bytes() != data:
            path.write_bytes(data)


def _remove_new_root_outputs(before: set[Path]) -> None:
    """Delete ``proc_example*.nc`` files a notebook wrote into the working root that did not
    exist before the run (notebook 07 builds ``proc_example.nc`` and its ARCO exports there when
    the file is absent). A file that existed beforehand is left alone."""
    for path in PORT_ROOT.glob("proc_example*.nc"):
        if path not in before and path.is_file():
            path.unlink()


def _tool_modules() -> dict:
    """Every loaded module whose file lives in ``scripts/`` (``run_flight``,
    ``make_demo_flight``, ...)."""
    found = {}
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if path and Path(path).resolve().parent == TOOLS:
            found[name] = mod
    return found


def _detach_tool_modules() -> dict:
    """Give a notebook fresh copies of the ``scripts/`` scripts, as a real kernel would.

    Notebook 03 does ``import run_flight`` and then ``run_flight.log = lambda ...``. Run
    in-process against the suite's shared module object, that silenced ``run_flight`` for every
    later test module, and six ``arrayprobe run`` tests failed when this module ran first --
    masked in ``discover`` only because ``test_make_demo_flight`` happens to re-register a fresh
    copy in between (found 2026-09-13, pair L). Returns what was detached, for
    :func:`_reattach_tool_modules`.
    """
    saved = _tool_modules()
    for name in saved:
        del sys.modules[name]
    return saved


def _reattach_tool_modules(saved: dict) -> None:
    for name in _tool_modules():
        del sys.modules[name]
    sys.modules.update(saved)


def _notebooks() -> list[Path]:
    if not EXAMPLES.is_dir():
        return []
    return sorted(p for p in EXAMPLES.rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts)


_MAGIC = re.compile(r"\s*(%%?\w|!)")


def _code_cells(notebook: Path) -> list[str]:
    """Each code cell's source, with IPython magic lines (``%matplotlib inline``) blanked,
    as scripts/execute_example_notebooks.py does: they are not Python."""
    nb = json.loads(notebook.read_text(encoding="utf-8"))
    return ["\n".join("" if _MAGIC.match(ln) else ln for ln in "".join(cell["source"]).split("\n"))
            for cell in nb["cells"] if cell["cell_type"] == "code"]


def _unguarded_optional_import(notebook: Path) -> str | None:
    """The optional package a notebook imports at a cell's top level (unguarded), if any.

    Such a notebook needs the package installed; one that imports it inside a ``try`` runs
    either way and is not skipped."""
    for source in _code_cells(notebook):
        for line in source.splitlines():
            for pkg in OPTIONAL_PACKAGES + EXAMPLE_ONLY_PACKAGES:
                if line.startswith((f"from {pkg}", f"import {pkg}")):
                    return pkg
    return None


# Real notebook execution (this module execs the cells; it does not use nbconvert/nbclient --
# see the docstring). W6 measured ~17.4s on 2026-09-14, which holds only where notebook 03's
# example-data gate is CLOSED, as in CI and every fresh clone. Where the ORACLES subsets are
# present, section 2d decodes them for real: 03 alone measured 908.0s on 2026-09-17, 899.7s of
# it that one cell (python_port/nb03_write.launch.log). The cheap, gate-closed half of what
# this protects is also covered, in milliseconds, by test_notebook_cells_survive_each_other.
@repo_only
@slow
class EveryNotebookExecutesEndToEnd(unittest.TestCase):
    def test_at_least_one_notebook_is_present(self) -> None:
        """The empty-glob failure this project keeps finding, guarded here too."""
        self.assertTrue(_notebooks(), f"no *.ipynb files found under {EXAMPLES}")

    def test_every_notebook_runs_without_raising(self) -> None:
        # Headless: a notebook that calls plt.show() must not need a display.
        import matplotlib
        matplotlib.use("Agg")

        # A shared run_flight, as the rest of the suite leaves one: the notebooks must not touch it.
        shared = sys.modules.get("run_flight")
        if shared is None:
            spec = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
            assert spec is not None and spec.loader is not None
            shared = importlib.util.module_from_spec(spec)
            sys.modules["run_flight"] = shared
            spec.loader.exec_module(shared)
            self.addCleanup(sys.modules.pop, "run_flight", None)
        shared_log = shared.log

        failures = []
        original_cwd = Path.cwd()
        # Notebook 11 saves its figures beside itself (`examples/figures`) for the README
        # and the paper. Executing it here must leave the tracked figures as committed:
        # matplotlib's PNG bytes differ across machines and versions, so a suite run showed
        # them as modified. Snapshot every file there and put the tree back afterwards.
        fig_dir = EXAMPLES / "figures"
        fig_before = ({p: p.read_bytes() for p in fig_dir.iterdir() if p.is_file()}
                      if fig_dir.is_dir() else {})
        self.addCleanup(_restore_dir, fig_dir, fig_before)
        # Notebook 07 writes proc_example*.nc into the working root; leave none behind.
        root_before = set(PORT_ROOT.glob("proc_example*.nc"))
        self.addCleanup(_remove_new_root_outputs, root_before)
        try:
            os.chdir(PORT_ROOT)
            for notebook in _notebooks():
                pkg = _unguarded_optional_import(notebook)
                if pkg is not None and not importable(pkg):
                    with self.subTest(notebook=notebook.name):
                        self.skipTest(f"{notebook.name} imports {pkg}, which is not installed "
                                      "in this environment (tests/_optional.py)")
                    continue
                saved = _detach_tool_modules()
                try:
                    namespace: dict = {"__name__": "__main__"}
                    for i, source in enumerate(_code_cells(notebook)):
                        try:
                            exec(compile(source, f"<{notebook.name} cell {i}>", "exec"), namespace)
                        except Exception as exc:  # noqa: BLE001 -- report which notebook/cell, don't hide it
                            failures.append(
                                f"{notebook.name} cell {i}: {type(exc).__name__}: {exc}")
                            break
                finally:
                    _reattach_tool_modules(saved)
        finally:
            os.chdir(original_cwd)
        self.assertEqual([], failures, "notebook(s) failed to execute:\n  " + "\n  ".join(failures))
        self.assertIs(sys.modules.get("run_flight"), shared,
                      "a notebook replaced the suite's shared run_flight module")
        self.assertIs(shared.log, shared_log,
                      "a notebook changed the suite's shared run_flight.log (notebook 03 stubs it)")


@repo_only  # reads a repository-only file, not in the sdist
class EveryNotebookCarriesTheLaunchGuard(unittest.TestCase):
    """Every notebook under ``examples/`` opens (after its title cell) with the same
    working-directory guard, so a person who launches Jupyter from ``examples/`` --
    the folder the notebook actually lives in -- gets one clear error instead of a
    relative-path ``FileNotFoundError`` three cells later. On 2026-09-28 notebooks
    11 (``11_image_assisted_threshold.ipynb``) and the ARCO tour
    (``arco_export_tour.ipynb``) were found missing it -- found by grepping every other
    notebook, not by reading a list, so an added notebook that forgets the guard fails
    this test rather than going unnoticed."""

    GUARD_MARKER = "# Launch guard:"

    def test_every_notebook_has_the_launch_guard(self) -> None:
        notebooks = _notebooks()
        self.assertTrue(notebooks, f"no *.ipynb files found under {EXAMPLES}")
        missing = [nb.name for nb in notebooks
                   if not any(self.GUARD_MARKER in cell for cell in _code_cells(nb))]
        self.assertEqual(
            missing, [],
            f"notebook(s) with no launch guard cell: {missing}. Copy the guard cell "
            f"(the one starting '{self.GUARD_MARKER}') from any other notebook under "
            f"examples/, as the first or second cell.")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

# A repository sweep: run before every full suite by a tool that is not part of this package
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
