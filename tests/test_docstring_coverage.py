# SPDX-License-Identifier: BSD-3-Clause
"""The port's public surface stays documented, because a number that was raised
once drifts back down otherwise.

Public docstring coverage was measured at 81 % on
2026-08-30. The gap was closed on 2026-09-01, and this is the check that keeps
it closed -- the project's standing rule being that a recurring mechanical
obligation gets a control rather than a reminder
(the project's guard doctrine). Without it the next module
lands with three undocumented entry points and nobody re-measures.

**What counts as "public" here**, deliberately narrower than "every ``def``
without an underscore":

* module-level functions and classes whose own name does not start with ``_``;
* public methods and properties of those public classes.

Nested helpers and the methods of private classes are excluded -- they are
implementation, and requiring a docstring on every closure buys boilerplate
rather than documentation. The port's convention for "this is internal" is the
underscore prefix, so that is what this test reads.

There is a second assertion, and it is the one that gives the first any force:
a docstring must be long enough to say something. Ten characters of "TODO" or
"Returns the result" would satisfy a presence check while leaving the reader
exactly where they were, and a coverage number that can be reached that way
measures nothing.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests._repo import needs_source

SRC = Path(__file__).resolve().parent.parent / "src" / "arrayprobe"

#: Below this, a docstring is not a description. Chosen from the shortest real
#: one in the package rather than picked round: several genuinely need only a
#: line ("``:209-212`` -- ``'%f, %d\\n'``." is complete and checkable), so the
#: bar has to sit under those while still rejecting a placeholder.
MIN_DOCSTRING_CHARS = 20


def _public_definitions() -> list[tuple[str, int, str, str | None]]:
    """Every public definition in the package, as ``(file, line, name, doc)``."""
    found: list[tuple[str, int, str, str | None]] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(SRC)).replace("\\", "/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name.startswith("_"):
                continue
            found.append((rel, node.lineno, node.name, ast.get_docstring(node)))
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and not sub.name.startswith("_")):
                        found.append((rel, sub.lineno, f"{node.name}.{sub.name}",
                                      ast.get_docstring(sub)))
    return found


@needs_source
class PublicSurfaceIsDocumented(unittest.TestCase):
    def test_the_package_has_a_public_surface_to_check(self):
        """Guards the guard: a broken walker would report zero missing on zero
        definitions, and pass forever while checking nothing."""
        self.assertGreater(len(_public_definitions()), 150)

    def test_every_public_definition_has_a_docstring(self):
        missing = [f"{f}:{ln} {name}" for f, ln, name, doc in _public_definitions()
                   if doc is None]
        self.assertEqual(
            missing, [],
            "public definitions with no docstring. Write one saying what it does "
            "and, where the behaviour comes from the MATLAB, which file:line it "
            f"reproduces -- or rename it with a leading underscore if it is "
            f"genuinely internal: {missing}")

    def test_no_docstring_is_a_placeholder(self):
        stubs = [f"{f}:{ln} {name}" for f, ln, name, doc in _public_definitions()
                 if doc is not None and len(doc.strip()) < MIN_DOCSTRING_CHARS]
        self.assertEqual(
            stubs, [],
            f"docstrings under {MIN_DOCSTRING_CHARS} characters -- a presence "
            f"check is only worth having if it cannot be satisfied by a "
            f"placeholder: {stubs}")


if __name__ == "__main__":
    unittest.main()
