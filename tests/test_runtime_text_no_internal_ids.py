# SPDX-License-Identifier: BSD-3-Clause
"""No text a user reads at runtime carries an internal project id.

**Why.** The triage particle page told a reader "No CNN classifier installed yet (task #27,
enhancements_uiops/ -- not built)": a task number from the project's own bookkeeping, meaningless to
anyone who has not seen it. ``test_tool_help_no_internal_ids`` pins ``--help`` on a fixed list
of tools; this module covers the class across the shipped source trees instead.

**What it scans.** Every string literal in the shipped packages (``python_port/src``,
``enhancements_uiops/src``, ``enhancements_soda2/src``) that can reach a reader while the code runs:
HTML the triage server and gallery emit, exception and log messages, ``--help`` text, attribute
text written into output files, catalogue notes. Bare string statements (docstrings and
attribute docstrings) are skipped, because only a developer reads them -- except a module
docstring in a file that passes ``description=__doc__`` to argparse, which ``--help`` prints.

**The ids.** Ledger and rule ids (a prefix such as ``I``, ``S``, ``D``, ``R``, ``PORT``, ``CMP``
or ``TT``, a hyphen and a number) and task numbers (``task #27``). An instance that must
stay names itself in :data:`ALLOWED` with the reason; there are none today.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT, repo_only

REPO = Path(__file__).resolve().parents[1]
ROOTS = [PKG_ROOT / "src", REPO / "enhancements_uiops" / "src",
         REPO / "enhancements_soda2" / "src"]

ID_PATTERN = re.compile(r"\b(?:I|S|D|PORT|CMP|TT|R)-[0-9]+[a-zA-Z]?\b|\btask #\d+")

#: ``(path relative to the repository, id)`` -> reason it may stay. Empty: every instance
#: found was replaced with plain words.
ALLOWED: dict[tuple[str, str], str] = {}


def runtime_strings(source: str) -> list[tuple[int, str]]:
    """``(line, text)`` for every string literal in ``source`` a reader can see at runtime."""
    tree = ast.parse(source)
    skipped = {id(node.value) for node in ast.walk(tree)
               if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
               and isinstance(node.value.value, str)}
    if "description=__doc__" in source and tree.body and isinstance(tree.body[0], ast.Expr):
        skipped.discard(id(tree.body[0].value))
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in skipped]


def leaks(source: str) -> list[tuple[int, str]]:
    """``(line, id)`` for every internal id in ``source``'s runtime strings."""
    return [(line, m.group(0)) for line, text in runtime_strings(source)
            for m in ID_PATTERN.finditer(text)]


class TheScannerFires(unittest.TestCase):
    """The guard is executed, not read: each case it must catch, caught."""

    def test_html_in_an_fstring_part(self):
        src = 'x = 1\nh = f"<div>No CNN installed yet (task #27, {x})</div>"\n'
        self.assertEqual(leaks(src), [(2, "task #27")])

    def test_exception_message(self):
        # Each fixture id is split across adjacent literals, so the scanned source holds
        # a real id while this file adds none to the development-id ratchet.
        self.assertEqual(leaks('raise ValueError("exists to prevent (I-' '295).")\n'),
                         [(1, "I-" "295")])

    def test_help_docstring_is_scanned_when_argparse_prints_it(self):
        src = ('"""Tool (I-' '352)."""\nimport argparse\n'
               'argparse.ArgumentParser(description=__doc__)\n')
        self.assertEqual(leaks(src), [(1, "I-" "352")])

    def test_plain_docstrings_and_comments_are_not_runtime_text(self):
        src = ('"""Module (I-' '1)."""\n# a comment (S-' '2)\n'
               'def f():\n    """Function (task #3)."""\n    return "plain"\n')
        self.assertEqual(leaks(src), [])

    def test_lookalikes_are_not_ids(self):
        self.assertEqual(leaks('x = "COVID-19, ISO-8601, 2D-S, H-1 rocket"\n'), [])


@repo_only  # scans enhancements_uiops/ and enhancements_soda2/, not in the sdist
class NoShippedSourceLeaksAnId(unittest.TestCase):

    def test_no_runtime_string_names_an_internal_id(self):
        found = []
        for root in ROOTS:
            for path in sorted(root.rglob("*.py")):
                rel = path.relative_to(REPO).as_posix()
                for line, ident in leaks(path.read_text(encoding="utf-8")):
                    if (rel, ident) not in ALLOWED:
                        found.append(f"{rel}:{line}: {ident}")
        self.assertEqual(found, [], "internal id(s) in text a user reads at runtime; "
                                    "replace each with plain words:\n" + "\n".join(found))

    def test_every_allowance_still_matches_something(self):
        for (rel, ident), reason in ALLOWED.items():
            with self.subTest(path=rel, id=ident):
                self.assertTrue(reason.strip())
                text = (REPO / rel).read_text(encoding="utf-8")
                self.assertIn(ident, [i for _, i in leaks(text)])


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
