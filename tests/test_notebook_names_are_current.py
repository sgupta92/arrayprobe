# SPDX-License-Identifier: BSD-3-Clause
"""Every ``NN_name.ipynb`` named in prose names a notebook that exists under ``examples/``.

**The defect this was written after.** ``test_notebook_links`` resolves links, so a
stale notebook name written as plain text or a code span survives it: after the
seven-track renumbering, ``6_science/01_microphysics_moments.ipynb`` still sent the
reader to ``22_check_the_phase_assumption.ipynb`` and
``21_clock_offset_between_products.ipynb`` in five places, none of them links
(2026-10-15).

The check reads the same files the link check reads (every markdown cell of every
``examples/**/*.ipynb``, the example READMEs, ``README.md``, ``docs/*.md`` and
``docs/developer/PACKAGE_README.md``), finds every token of the form
``NN_name.ipynb``, linked or not, and requires its basename to be the basename of a
notebook under ``examples/``. There are no allowances.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._markdown_links import ROOT
from tests._repo import repo_only
from tests.test_notebook_links import _checked_files, _markdown_of

#: A numbered notebook name, with or without a directory in front of it.
NOTEBOOK_NAME = re.compile(r"(?<![\w-])(\d+_[\w-]+\.ipynb)\b")


def current_notebooks(root: Path = ROOT) -> frozenset[str]:
    return frozenset(p.name for p in (root / "examples").rglob("*.ipynb")
                     if ".ipynb_checkpoints" not in p.parts)


def stale_names(markdown: str, names: frozenset[str]) -> list[str]:
    """Each ``NN_name.ipynb`` token in ``markdown`` whose basename is not in ``names``."""
    return [m.group(1) for m in NOTEBOOK_NAME.finditer(markdown) if m.group(1) not in names]


@hygiene
@repo_only
class NotebookNamesAreCurrent(unittest.TestCase):
    def test_the_walk_finds_the_notebooks(self):
        self.assertGreater(len(current_notebooks()), 30,
                           "examples/**/*.ipynb not found -- the walk is wrong")

    def test_every_named_notebook_exists(self):
        names = current_notebooks()
        offenders = [f"{p.relative_to(ROOT).as_posix()}: {n}"
                     for p in _checked_files() for n in stale_names(_markdown_of(p), names)]
        self.assertEqual(
            offenders, [],
            "notebook names in prose that match no notebook under examples/ (renamed or "
            "renumbered; name the current notebook, as a link):\n  " + "\n  ".join(offenders))


@hygiene
class TheNameCheckFires(unittest.TestCase):
    def test_a_stale_name_is_reported_linked_or_not(self):
        names = frozenset({"10_check_the_phase_assumption.ipynb", "03_clock_offsets.ipynb"})
        text = ("The check is in `22_check_the_phase_assumption.ipynb`, section 7; see\n"
                "[03_clock_offsets.ipynb](../5_data_quality/03_clock_offsets.ipynb) and\n"
                "../5_data_quality/21_clock_offset_between_products.ipynb, and\n"
                "[10_check_the_phase_assumption.ipynb](10_check_the_phase_assumption.ipynb).")
        self.assertEqual(stale_names(text, names), [
            "22_check_the_phase_assumption.ipynb",
            "21_clock_offset_between_products.ipynb",
        ])

    def test_a_notebook_cell_is_read(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "01_here.ipynb"
            p.write_text(json.dumps({"cells": [
                {"cell_type": "markdown", "source": ["See `09_gone.ipynb`.\n"]},
                {"cell_type": "code", "source": ["# 08_in_code.ipynb\n"], "outputs": []},
            ]}), encoding="utf-8")
            self.assertEqual(stale_names(_markdown_of(p), frozenset()), ["09_gone.ipynb"])


if __name__ == "__main__":
    unittest.main()
