# SPDX-License-Identifier: BSD-3-Clause
"""A test module that imports a sibling must be runnable by its own name.

WHY THIS EXISTS, twice in one night (2026-09-21).

`tests/` is not a package on sys.path when a module is named in the dotted
form, so a bare

    from test_compare_cip_2ds import _Files

resolves under

    python -m unittest discover -s tests -p "test_*.py"

-- which inserts `tests/` as the top-level directory, so the module is
imported as `test_compare_cip_2ds` -- and raises `ModuleNotFoundError`
under

    python -m unittest tests.test_cip_figure_provenance

which imports it as `tests.test_cip_figure_provenance` with `tests/` nowhere
on the path. The documented suite command is the first form, so the full run
stays green and the defect is invisible until someone verifies one module by
name. That is exactly what happened: `tests/test_run_flight_enhancements.py`
earlier in the night, then `tests/test_cip_figure_provenance.py` an hour
later, the second found only because a commit had already been made with the
error showing.

Thirteen modules import a sibling. Eleven of them put their own directory on
`sys.path` first and were always fine; two did not. A rule addressed to
attention ("remember the path insert") is not a control, so this is the
control.

THE TWO SIDES COME FROM DIFFERENT PLACES. One is the source text -- which
modules contain a top-level bare sibling import, read with `ast` rather than
by regex, so a mention inside a docstring or a function body does not count.
The other is the interpreter, actually importing each of them by its dotted
name. Neither side can be satisfied by editing the other.

The import sweep runs in a SUBPROCESS. `discover` has already imported these
modules as `test_X`; importing them again as `tests.test_X` in this process
would create a second module object and re-run every module-level statement,
including the ones that write fixtures.

ONE SUBPROCESS PER MODULE, and the first version of this file got that wrong.
It imported all thirteen in a single interpreter, and passed while mutated:
`test_cip_figure_provenance` inserts `tests/` on `sys.path` at import, so every
module imported after it resolves its siblings whether or not it does its own
insert. The check was reading one module's path insert as evidence about
another's -- a guard passing for the wrong reason, which is the same way the
count-anchor check failed earlier the same night. A fresh interpreter per
module is what makes each answer its own question.
"""

import ast
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = HERE.parent


def _bare_sibling_imports(source: str) -> list[str]:
    """Names a module imports at top level as bare `test_*`, via `ast`.

    Only module-level statements count: an import inside a function or a
    `try` body that already handles `ImportError` is not this defect.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:  # the pre-commit hook's job, not this test's
        return []
    found = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.startswith("test_"):
                found.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("test_"):
                    found.append(alias.name)
    return found


def _modules_with_sibling_imports() -> dict[str, list[str]]:
    out = {}
    for path in sorted(HERE.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        names = _bare_sibling_imports(path.read_text(encoding="utf-8"))
        if names:
            out[path.stem] = names
    return out


class TestSiblingImportsResolveByDottedName(unittest.TestCase):
    def test_the_sweep_finds_the_modules_it_is_about(self):
        """If this reaches zero the test below is asserting nothing."""
        found = _modules_with_sibling_imports()
        self.assertGreater(
            len(found), 0,
            "no test module imports a sibling any more -- either the idiom is "
            "gone (delete this file) or _bare_sibling_imports has stopped "
            "matching, which would make the check below vacuous",
        )

    def test_every_such_module_imports_as_tests_dot_name(self):
        found = _modules_with_sibling_imports()
        script = (
            "import importlib, sys, unittest\n"
            "try:\n"
            "    importlib.import_module('tests.' + sys.argv[1])\n"
            # a module that skips itself at import (an absent upstream tree) resolved fine
            "except unittest.SkipTest:\n"
            "    pass\n"
            "except Exception as exc:\n"
            "    print('%s: %s' % (type(exc).__name__, exc))\n"
            "    raise SystemExit(3)\n"
        )
        broken = []
        for module in sorted(found):
            proc = subprocess.run(
                [sys.executable, "-c", script, module],
                cwd=str(PORT), capture_output=True, text=True, timeout=300,
            )
            if proc.returncode == 3:
                broken.append(f"{module}: {proc.stdout.strip().splitlines()[-1]}")
            elif proc.returncode != 0:
                self.fail(
                    f"the sweep itself failed on {module} (rc={proc.returncode}):\n"
                    f"{proc.stdout}\n{proc.stderr}"
                )
        self.assertEqual(
            broken, [],
            "these modules import a sibling but cannot be run by name "
            "(`python -m unittest tests.<name>`), so a verification run of one "
            "module errors while the full `discover` stays green:\n  "
            + "\n  ".join(broken)
            + "\n\nFix: add, before the sibling import,\n"
            "    sys.path.insert(0, str(Path(__file__).resolve().parent))",
        )


if __name__ == "__main__":
    unittest.main()
