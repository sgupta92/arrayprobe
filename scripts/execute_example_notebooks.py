# SPDX-License-Identifier: BSD-3-Clause
"""Execute ``examples/*.ipynb`` and write each cell's real output into the file.

WHY THIS EXISTS. The author's instruction: *"the example notebooks should have some
output plots or results in them, not just cells without output."* Every tracked
notebook shipped with ``"outputs": []`` on every code cell, so a reader who
opened one on GitHub saw the code and nothing it produces.

WHY NOT ``nbconvert --execute``. ``jupyter``, ``nbconvert``, ``nbclient`` and
``ipykernel`` are none of them installed in ``.venv`` and none of
them is a project dependency -- ``examples/README.md`` says so deliberately.
Rather than add ~20 packages to a pinned venv so that five small notebooks can
be run, this reuses the *same* execution mechanism
``tests/test_examples_execute.py`` already trusts: read the notebook's JSON,
``exec`` each code cell in one shared namespace, with the repository root as the
working directory (the notebooks do ``sys.path.insert(0, "scripts")``).

WHAT IT CAPTURES, and what it does not. Anything a cell prints (stdout), any
matplotlib figure the cell leaves open, and the repr of a trailing bare
expression -- plus that value's ``_repr_html_()`` when it has one (a pandas
table or an xarray Dataset), so GitHub renders it as a table. It does **not**
emulate a kernel beyond that: no ``display()`` hook, no stderr stream, no ANSI traceback capture --
a raising cell aborts the notebook and this script exits non-zero rather than
committing a traceback as if it were output. That is the intended trade: every
byte written here is output the real code really produced -- with ONE rewrite.

LOCAL PATHS ARE SCRUBBED (2026-09-15). The CLI and the report
objects echo full output paths, so the saved notebooks carried a user's temp
directory (``C:/Users/<name>/AppData/Local/Temp/tmp...``) and the interpreter's
own path into a public file. :func:`scrub_local_paths` rewrites, in captured
text only, this interpreter to ``python``, a temporary directory to ``<tmp>``,
the repository to ``<repo>`` and the home directory to ``~``; nothing else is
touched and images are never rewritten. ``--scrub-only`` applies the same
rewrite to the outputs a notebook already carries, without executing it.
``tests/test_no_personal_paths.py`` fails on any such path left in a tracked
file, notebook outputs included.

EVERY RUN IS TIMED (2026-09-17). A cell slower than :data:`SLOW_CELL_SECONDS`
prints its number and its cost as it finishes, a raising cell prints how long it
had already run, and each notebook's summary line carries its total and its
slowest cell. Notebook 03's gated section 2d spent 1508 s in silence before a
later cell raised in the 2026-09-16 cold-start dry run; nothing on screen said
which cell was spending it.

Usage, from the repository root::

    .venv/Scripts/python.exe scripts/execute_example_notebooks.py            # all
    .venv/Scripts/python.exe scripts/execute_example_notebooks.py 01_quickstart
    .venv/Scripts/python.exe scripts/execute_example_notebooks.py --check    # dry run
    .venv/Scripts/python.exe scripts/execute_example_notebooks.py --scrub-only
    .venv/Scripts/python.exe scripts/execute_example_notebooks.py --skip-tag v314-only

SKIPPING TAGGED CELLS (2026-10-29). ``--skip-tag TAG`` (repeatable) leaves every
code cell whose ``metadata.tags`` contains TAG unexecuted, with its saved outputs
and ``execution_count`` untouched, and counts it on the summary line. It exists
so the notebooks can be run as a public install runs them: cells tagged
``v314-only`` need the v3.1.4 engine the release does not ship, and the release
builder strips them. With no ``--skip-tag`` the run is unchanged.
"""
from __future__ import annotations

import argparse
import ast
import base64
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
PORT_ROOT = REPO_ROOT  # the package sits at the repository root


if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrub_paths import _GENERIC_TMP, _MKDTEMP_CHILD, _spellings  # noqa: E402,F401

#: A home directory spelled out when it is not this process's own (a notebook
#: saved on another machine). The user name is the component after
#: ``Users``/``home``; ``tests/test_no_personal_paths.py`` detects the same shape.
_GENERIC_HOME = re.compile(
    r"(?:\b[A-Za-z]:[\\/]+Users|(?<![\w.])/[a-z]/Users|(?<![\w.])/(?:home|Users))"
    r"[\\/]+[^\\/\s\"'<>:*?|]+", re.IGNORECASE)


def scrub_local_paths(text: str) -> str:
    """Rewrite machine-local absolute paths in captured output (module docstring).

    Order matters: the interpreter and the temporary directory usually sit
    inside the home directory, and the repository may too, so the most
    specific spellings go first.
    """
    for s in _spellings(sys.executable):
        text = text.replace(s, "python")
    for s in _spellings(tempfile.gettempdir()):
        # ``(?!\w)``: a spelling of the temp dir must end at a path boundary.
        # On POSIX ``gettempdir()`` is ``/tmp``, whose backslash spelling
        # ``\tmp`` is otherwise a prefix of every ``\tmpXXXX`` mkdtemp child
        # in a Windows-shaped path, leaving ``<tmp><tmp>XXXX``.
        text = re.sub(re.escape(s) + r"(?!\w)" + _MKDTEMP_CHILD, "<tmp>", text)
    for s in _spellings(REPO_ROOT):
        text = text.replace(s, "<repo>")
    for s in _spellings(Path.home()):
        text = text.replace(s, "~")
    text = _GENERIC_HOME.sub("~", text)
    return _GENERIC_TMP.sub("<tmp>", text)


def _scrub_outputs(nb: dict) -> int:
    """Scrub every text output of ``nb`` in place; return how many lines changed."""
    changed = 0
    for cell in nb.get("cells", []):
        for output in cell.get("outputs", []):
            slots = []
            if "text" in output:
                slots.append((output, "text"))
            if "text/plain" in output.get("data", {}):
                slots.append((output["data"], "text/plain"))
            for holder, key in slots:
                value = holder[key]
                lines = value if isinstance(value, list) else [value]
                new = [scrub_local_paths(line) for line in lines]
                changed += sum(a != b for a, b in zip(lines, new, strict=True))
                holder[key] = new if isinstance(value, list) else new[0]
    return changed


def scrub_only(notebook: Path, *, write: bool) -> int:
    """Scrub a notebook's saved outputs without executing it; return lines changed."""
    nb = json.loads(notebook.read_text(encoding="utf-8"))
    changed = _scrub_outputs(nb)
    if write and changed:
        notebook.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    return changed


def _split_trailing_expression(source: str, filename: str):
    """Return (body_code, expr_code_or_None) so a bare trailing expression echoes."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return compile(source, filename, "exec"), None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = tree.body.pop()
        body = compile(tree, filename, "exec")
        expr = compile(ast.Expression(last.value), filename, "eval")
        return body, expr
    return compile(tree, filename, "exec"), None


def _figure_outputs() -> list[dict]:
    """Every matplotlib figure still open, as a display_data PNG. Closes them."""
    import matplotlib.pyplot as plt

    outputs = []
    for num in plt.get_fignums():
        fig = plt.figure(num)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        png = base64.b64encode(buf.getvalue()).decode("ascii")
        outputs.append({
            "output_type": "display_data",
            "data": {
                "image/png": png,
                "text/plain": [f"<Figure size {fig.get_size_inches()[0]:.0f}"
                               f"x{fig.get_size_inches()[1]:.0f} with "
                               f"{len(fig.axes)} Axes>"],
            },
            "metadata": {},
        })
        plt.close(fig)
    return outputs


def _as_lines(text: str) -> list[str]:
    """nbformat stores multi-line text as a list of lines, each keeping its \n."""
    return text.splitlines(keepends=True)


#: A cell slower than this gets its own line as it finishes, so a long run names
#: where the time is going while it is still going. Notebook 03's gated section
#: 2d ran 1508 s before raising in a later cell (2026-09-16 dry run) and the only
#: thing on screen was silence.
SLOW_CELL_SECONDS = 20.0

TOOLS = (PORT_ROOT / "scripts").resolve()


def _tool_modules() -> dict:
    """Every loaded module whose file lives in ``scripts/`` (``run_flight``, ...)."""
    found = {}
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if path and Path(path).resolve().parent == TOOLS:
            found[name] = mod
    return found


@contextlib.contextmanager
def _fresh_process_state():
    """Give one notebook the process state a fresh kernel would, then restore it.

    Every notebook runs in this one process, so module-level state a notebook
    sets on a ``scripts/`` script leaked into the next: 05 leaves
    ``run_flight.ENGINE = "3.5"`` set, and 09 then failed (``--diode-corrected
    is refused under engine 3.5``) when run after it, though it runs clean
    alone. The ``scripts/`` modules are detached so the notebook imports fresh
    copies, as ``tests/test_examples_execute.py`` does; ``sys.path``,
    ``os.environ`` and the working directory are restored as well.
    """
    saved_modules = _tool_modules()
    for name in saved_modules:
        del sys.modules[name]
    saved_path = list(sys.path)
    saved_env = dict(os.environ)
    saved_cwd = Path.cwd()
    try:
        yield
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)
        sys.path[:] = saved_path
        for name in _tool_modules():
            del sys.modules[name]
        sys.modules.update(saved_modules)


_MAGIC = re.compile(r"\s*(%%?\w|!)")


def _cell_tags(cell: dict) -> set[str]:
    """The cell's ``metadata.tags`` as a set (empty when absent)."""
    tags = cell.get("metadata", {}).get("tags", [])
    return set(tags) if isinstance(tags, list) else set()


def execute(notebook: Path, *, write: bool, skip_tags: frozenset[str] = frozenset(),
            skipped: list[int] | None = None) -> tuple[int, int, list[float]]:
    """Run one notebook. Returns (code_cells, cells_that_produced_output, seconds_per_cell).

    A code cell carrying any tag in ``skip_tags`` is not executed and keeps its
    saved outputs and ``execution_count``; its 1-based number is appended to
    ``skipped`` when given, and it costs 0.0 s in ``seconds_per_cell`` so later
    cells keep their numbers.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    nb = json.loads(notebook.read_text(encoding="utf-8"))
    namespace: dict = {"__name__": "__main__"}
    n_code = 0
    n_with_output = 0
    seconds: list[float] = []

    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        n_code += 1
        if skip_tags and _cell_tags(cell) & skip_tags:
            if skipped is not None:
                skipped.append(n_code)
            seconds.append(0.0)
            if cell.get("outputs"):
                n_with_output += 1
            continue
        # IPython magics (``%matplotlib inline``) are not Python; the Agg backend is set above.
        source = "\n".join("" if _MAGIC.match(ln) else ln
                           for ln in "".join(cell["source"]).splitlines())
        where = f"<{notebook.name} cell {n_code}>"
        plt.close("all")
        buf = io.StringIO()
        body, expr = _split_trailing_expression(source, where)
        started = time.monotonic()
        try:
            with contextlib.redirect_stdout(buf):
                exec(body, namespace)  # noqa: S102 -- executing the notebook is the job
                value = eval(expr, namespace) if expr is not None else None  # noqa: S307
        except BaseException:
            # Name the cell and what it had already cost: main() catches this and
            # reports the notebook, but only the cell number says where to look.
            print(f"     cell {n_code} RAISED after {time.monotonic() - started:.1f}s",
                  flush=True)
            raise
        elapsed = time.monotonic() - started
        seconds.append(elapsed)
        if elapsed >= SLOW_CELL_SECONDS:
            print(f"     cell {n_code}: {elapsed:.1f}s", flush=True)

        outputs: list[dict] = []
        printed = scrub_local_paths(buf.getvalue())
        if printed:
            outputs.append({"output_type": "stream", "name": "stdout",
                            "text": _as_lines(printed)})
        outputs.extend(_figure_outputs())
        if value is not None:
            data = {"text/plain": _as_lines(scrub_local_paths(repr(value)))}
            # A table or Dataset also stores the formatted view a kernel would show, so the
            # notebook renders it as a table on GitHub rather than as a monospaced dump.
            html = getattr(value, "_repr_html_", None)
            if callable(html):
                rendered = html()
                if isinstance(rendered, str) and rendered:
                    data = {"text/html": _as_lines(scrub_local_paths(rendered)), **data}
            outputs.append({
                "output_type": "execute_result",
                "execution_count": n_code,
                "data": data,
                "metadata": {},
            })

        cell["outputs"] = outputs
        cell["execution_count"] = n_code
        if outputs:
            n_with_output += 1

    if write:
        notebook.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    return n_code, n_with_output, seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*",
                        help="notebook stems to run (default: all under examples/)")
    parser.add_argument("--check", action="store_true",
                        help="execute but do not write the outputs back")
    parser.add_argument("--scrub-only", action="store_true",
                        help="do not execute; rewrite local paths in the saved outputs")
    parser.add_argument("--skip-tag", action="append", default=[], metavar="TAG",
                        help="do not execute code cells whose metadata.tags contain TAG;"
                             " they keep their saved outputs (repeatable)")
    args = parser.parse_args(argv)
    skip_tags = frozenset(args.skip_tag)

    notebooks = sorted(p for p in EXAMPLES.rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts)
    if args.names:
        wanted = {n.removesuffix(".ipynb") for n in args.names}
        notebooks = [p for p in notebooks if p.stem in wanted]
    if not notebooks:
        print(f"no notebooks matched under {EXAMPLES}", file=sys.stderr)
        return 2

    if args.scrub_only:
        for notebook in notebooks:
            n = scrub_only(notebook, write=not args.check)
            print(f"ok   {notebook.name}: {n} output line(s) scrubbed")
        return 0

    original_cwd = Path.cwd()
    failures = []
    try:
        os.chdir(PORT_ROOT)
        for notebook in notebooks:
            print(f"run  {notebook.name}", flush=True)
            skipped: list[int] = []
            try:
                with _fresh_process_state():
                    n_code, n_out, seconds = execute(notebook, write=not args.check,
                                                     skip_tags=skip_tags, skipped=skipped)
            except Exception as exc:  # noqa: BLE001 -- name the notebook, do not hide it
                failures.append(f"{notebook.name}: {type(exc).__name__}: {exc}")
                print(f"FAIL {notebook.name}: {type(exc).__name__}: {exc}", flush=True)
                continue
            verb = "checked" if args.check else "wrote"
            total = sum(seconds)
            slowest = 1 + max(range(len(seconds)), key=seconds.__getitem__) if seconds else 0
            print(f"ok   {notebook.name}: {n_out}/{n_code} code cells {verb} with output"
                  f" in {total:.1f}s"
                  + (f" (slowest cell {slowest}: {max(seconds):.1f}s)" if seconds else "")
                  + (f", {len(skipped)} skipped by tag" if skip_tags else ""),
                  flush=True)
    finally:
        os.chdir(original_cwd)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
