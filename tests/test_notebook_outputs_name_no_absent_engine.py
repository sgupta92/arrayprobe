# SPDX-License-Identifier: BSD-3-Clause
"""No saved output of a shipped notebook names the v3.1.4 engine outside a ``v314-only`` cell.

The public release does not carry the v3.1.4 validation engine. The release builder drops every
cell tagged ``v314-only``, but an untagged cell whose *output* was saved on a machine where that
engine was importable still prints its name, its profiles or its presets, contradicting the
shipped code. This guard reads every saved output (the reader is
``tests/test_notebook_outputs_carry_no_local_paths.py``'s, imported rather than copied) of every
shipped notebook and fails on any such name outside a ``v314-only`` cell. Which notebooks ship is
decided by the release builder's own matcher over ``scripts/release_allowlist.txt`` where those
are present (a development checkout); in a release tree, every notebook present has shipped.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

from tests._repo import repo_only
from tests.test_notebook_outputs_carry_no_local_paths import _output_texts

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
TOOLS = ROOT / "scripts"
ALLOWLIST = TOOLS / "release_allowlist.txt"
BUILDER = TOOLS / "build_release_tree.py"

#: The tag whose cells the release builder drops; its outputs may name the engine.
V314_TAG = "v314-only"

#: Names of the absent engine, its profiles and its ORACLES presets.
ABSENT_ENGINE = re.compile(
    r"3\.1\.4|v314|stock-v3\.1\.4|STOCK_V314|oracles-production|oracles-2016",
    re.IGNORECASE,
)


def _tags(cell: dict) -> list:
    tags = (cell.get("metadata") or {}).get("tags") or []
    return tags if isinstance(tags, list) else []


def absent_engine_hits(notebook: dict) -> list[tuple[int, str]]:
    """(cell index, matched text) for every absent-engine name in an untagged cell's outputs."""
    hits: list[tuple[int, str]] = []
    for index, cell in enumerate(notebook.get("cells", [])):
        if V314_TAG in _tags(cell):
            continue
        for output in cell.get("outputs", []) or []:
            for text in _output_texts(output):
                for match in ABSENT_ENGINE.finditer(text):
                    hits.append((index, text[max(0, match.start() - 30):match.end() + 30]))
    return hits


def shipped_notebooks() -> list[Path]:
    """Every example notebook the release carries."""
    notebooks = sorted(p for p in EXAMPLES.rglob("*.ipynb")
                       if ".ipynb_checkpoints" not in p.parts)
    if not (ALLOWLIST.is_file() and BUILDER.is_file()):
        return notebooks  # a release tree: what is here has shipped
    sys.path.insert(0, str(TOOLS))
    try:
        import build_release_tree as brt
    finally:
        sys.path.remove(str(TOOLS))
    rules = brt.parse_allowlist(ALLOWLIST.read_text(encoding="utf-8"))
    kept = []
    for path in notebooks:
        rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
        if brt.allowed(rel, rules) and brt.never_ship(rel) is None:
            kept.append(path)
    return kept


def _notebook(text: str, tags: list[str] | None = None) -> dict:
    cell = {"cell_type": "code", "source": [], "metadata": {}, "outputs": [
        {"output_type": "stream", "name": "stdout", "text": [text]}]}
    if tags is not None:
        cell["metadata"]["tags"] = tags
    return {"cells": [cell]}


class TestGuardFires(unittest.TestCase):
    def test_an_untagged_output_naming_the_engine_is_caught(self):
        for text in ("the v3.1.4 validation engine is installed",
                     "shipped: ['oracles-2016', 'oracles-production', 'stock-v3.5']",
                     "profile STOCK_V314", "ENGINES = ('3.1.4', '3.5')", "engine v314"):
            with self.subTest(text=text):
                self.assertTrue(absent_engine_hits(_notebook(text)))

    def test_the_same_output_in_a_v314_only_cell_passes(self):
        text = "the v3.1.4 validation engine is installed"
        self.assertEqual(absent_engine_hits(_notebook(text, tags=[V314_TAG])), [])
        self.assertTrue(absent_engine_hits(_notebook(text, tags=["other"])))

    def test_html_and_traceback_outputs_are_read(self):
        nb = {"cells": [{"cell_type": "code", "source": [], "outputs": [
            {"output_type": "execute_result", "data": {"text/html": ["<td>oracles-2016</td>"]}},
            {"output_type": "error", "traceback": ["ValueError: engine '3.1.4' is absent"]}]}]}
        self.assertEqual(len(absent_engine_hits(nb)), 2)

    def test_a_v35_output_is_clean(self):
        self.assertEqual(absent_engine_hits(_notebook("engine 3.5, profile stock-v3.5")), [])

    def test_the_hit_names_its_cell(self):
        nb = {"cells": [_notebook("clean")["cells"][0], _notebook("v3.1.4")["cells"][0]]}
        self.assertEqual([i for i, _ in absent_engine_hits(nb)], [1])


@repo_only
class TestShippedNotebooks(unittest.TestCase):
    def test_no_untagged_output_names_the_absent_engine(self):
        notebooks = shipped_notebooks()
        self.assertTrue(notebooks, "no shipped example notebooks found")
        found = []
        for path in notebooks:
            nb = json.loads(path.read_text(encoding="utf-8"))
            for index, snippet in absent_engine_hits(nb):
                found.append(f"{path.relative_to(ROOT).as_posix()}:cell {index}: {snippet!r}")
        self.assertEqual(found, [], f"{len(found)} hit(s):\n" + "\n".join(found))

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True


if __name__ == "__main__":
    unittest.main()
