# SPDX-License-Identifier: BSD-3-Clause
"""``scripts/execute_example_notebooks.py --skip-tag`` leaves tagged cells alone.

The notebooks are executed as a public install runs them, with the v3.1.4
engine absent; cells that need it are tagged ``v314-only`` and must not run.
A skipped cell keeps its saved outputs and ``execution_count``, untagged cells
run, and without the option the tagged cell runs (and raises) as before.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import execute_example_notebooks as ex

_STORED = [{"output_type": "stream", "name": "stdout", "text": ["stored v3.1.4 output\n"]}]


def _notebook() -> dict:
    def code(src, tags=None, outputs=None, count=None):
        cell = {"cell_type": "code", "metadata": {}, "source": [src],
                "outputs": outputs or [], "execution_count": count}
        if tags is not None:
            cell["metadata"]["tags"] = tags
        return cell
    return {
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": ["# tiny"]},
            code("x = 2\nprint('first', x)"),
            code("raise RuntimeError('needs the v3.1.4 engine')", tags=["v314-only"],
                 outputs=_STORED, count=7),
            code("print('third', x * 3)"),
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    }


class SkipTag(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.examples = self.root / "examples" / "1_folder"
        self.examples.mkdir(parents=True)
        self.nb = self.examples / "01_tiny.ipynb"
        self.nb.write_text(json.dumps(_notebook(), indent=1) + "\n", encoding="utf-8")

    def test_tagged_cell_is_skipped_and_keeps_its_output(self):
        skipped: list[int] = []
        with contextlib.redirect_stdout(io.StringIO()):
            n_code, n_out, seconds = ex.execute(self.nb, write=True,
                                                skip_tags=frozenset({"v314-only"}),
                                                skipped=skipped)
        self.assertEqual((n_code, n_out, len(seconds)), (3, 3, 3))
        self.assertEqual(skipped, [2])
        cells = [c for c in json.loads(self.nb.read_text(encoding="utf-8"))["cells"]
                 if c["cell_type"] == "code"]
        self.assertEqual(cells[1]["outputs"], _STORED)
        self.assertEqual(cells[1]["execution_count"], 7)
        self.assertEqual(cells[0]["outputs"][0]["text"], ["first 2\n"])
        self.assertEqual(cells[2]["outputs"][0]["text"], ["third 6\n"])
        self.assertEqual([c["execution_count"] for c in (cells[0], cells[2])], [1, 3])

    def test_without_the_option_the_tagged_cell_raises(self):
        before = self.nb.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaisesRegex(RuntimeError, "v3.1.4 engine"):
            ex.execute(self.nb, write=True)
        self.assertEqual(self.nb.read_bytes(), before)

    def test_an_unmatched_tag_skips_nothing(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            ex.execute(self.nb, write=False, skip_tags=frozenset({"other"}))

    def _main(self, *argv):
        out = io.StringIO()
        with mock.patch.object(ex, "EXAMPLES", self.root / "examples"), \
                mock.patch.object(ex, "PORT_ROOT", self.root), \
                contextlib.redirect_stdout(out):
            rc = ex.main(list(argv))
        return rc, out.getvalue()

    def test_cli_counts_skipped_cells_on_the_summary_line(self):
        rc, out = self._main("01_tiny", "--check", "--skip-tag", "v314-only",
                             "--skip-tag", "unused")
        self.assertEqual(rc, 0, out)
        self.assertIn("ok   01_tiny.ipynb: 3/3 code cells checked with output", out)
        self.assertIn(", 1 skipped by tag", out)

    def test_cli_default_is_unchanged_and_fails_on_the_tagged_cell(self):
        rc, out = self._main("01_tiny", "--check")
        self.assertEqual(rc, 1)
        self.assertIn("cell 2 RAISED", out)
        self.assertIn("FAIL 01_tiny.ipynb: RuntimeError", out)
        self.assertNotIn("skipped by tag", out)


if __name__ == "__main__":
    unittest.main()
