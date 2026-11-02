# SPDX-License-Identifier: BSD-3-Clause
"""A figure shown from a notebook's markdown is embedded, not linked by path.

GitHub's notebook viewer, in a private repository, cannot load an image that a
markdown cell references by a relative path (``![..](../figures/x.png)``): the
reader sees "this does not load in the notebook" (author review, 2026-10-16).
Images made by code cells are stored in the notebook and display fine. A
markdown figure therefore travels as a cell attachment
(``![..](attachment:x.png)`` with the bytes under the cell's ``attachments``).
This guard reads every markdown cell of every example notebook and fails on an
image reference whose target is a local path; http(s), ``data:`` and
``attachment:`` targets pass, and an attachment name must exist in the cell.
It has no allowances.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
HTML_IMAGE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
EMBEDDED = re.compile(r"(https?:|data:|attachment:)", re.IGNORECASE)


def unembedded_images(notebook: dict) -> list[tuple[int, str]]:
    """(cell index, target) for each markdown image that is not embedded or remote.

    An ``attachment:`` target also counts when the cell carries no attachment
    of that name.
    """
    hits: list[tuple[int, str]] = []
    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "markdown":
            continue
        source = cell.get("source", "")
        text = "".join(source) if isinstance(source, list) else source
        attached = cell.get("attachments") or {}
        targets = MD_IMAGE.findall(text) + HTML_IMAGE.findall(text)
        for target in targets:
            if target.lower().startswith("attachment:"):
                if target[len("attachment:"):] not in attached:
                    hits.append((index, target))
            elif not EMBEDDED.match(target):
                hits.append((index, target))
    return hits


def _notebook(source: str, attachments: dict | None = None) -> dict:
    cell: dict = {"cell_type": "markdown", "metadata": {}, "source": [source]}
    if attachments is not None:
        cell["attachments"] = attachments
    return {"cells": [cell]}


class TestGuardFires(unittest.TestCase):
    def test_a_relative_markdown_image_is_caught(self):
        self.assertEqual(
            unembedded_images(_notebook("![alt](../figures/x.png)")),
            [(0, "../figures/x.png")])

    def test_a_plain_and_a_html_image_path_are_caught(self):
        for source in ("![alt](x.png)", '<img src="figs/x.png" width="300">'):
            with self.subTest(source=source):
                self.assertTrue(unembedded_images(_notebook(source)))

    def test_an_attachment_name_missing_from_the_cell_is_caught(self):
        self.assertTrue(unembedded_images(_notebook("![alt](attachment:x.png)", {})))


class TestGuardPasses(unittest.TestCase):
    def test_an_attachment_with_its_bytes_passes(self):
        nb = _notebook("![alt](attachment:x.png)", {"x.png": {"image/png": "AAAA"}})
        self.assertEqual(unembedded_images(nb), [])

    def test_a_remote_image_and_a_link_pass(self):
        source = "![alt](https://example.org/x.png) and [a page](../notes/x.md)"
        self.assertEqual(unembedded_images(_notebook(source)), [])


@repo_only
class TestShippedNotebooks(unittest.TestCase):
    def test_every_markdown_figure_is_embedded(self):
        notebooks = sorted(EXAMPLES.rglob("*.ipynb"))
        self.assertTrue(notebooks, "no example notebooks found")
        found = []
        for path in notebooks:
            if ".ipynb_checkpoints" in path.parts:
                continue
            nb = json.loads(path.read_text(encoding="utf-8"))
            for index, target in unembedded_images(nb):
                found.append(f"{path.relative_to(ROOT)} cell {index}: {target}")
        self.assertEqual(found, [], "\n".join(found))


if __name__ == "__main__":
    unittest.main()


# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
