# SPDX-License-Identifier: BSD-3-Clause
"""No saved notebook output shows a folder on the machine that executed it.

Displaying a whole xarray Dataset prints its global attributes, and a product's
``Image Source`` / ``Data_Source`` attribute records the absolute path of the
input the demo run read -- a temporary folder under the user's home. Five
example notebooks shipped that path in their saved outputs (2026-10-15). They
now display a copy whose path-valued attributes keep only the file name; this
guard reads every saved output (``text/plain``, ``text/html``, streams, error
tracebacks) and fails on a home or temporary-folder path. It has no allowances.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

#: Home and temporary-folder path shapes, on Windows, macOS and Linux.
LOCAL_PATH = re.compile(
    r"AppData"
    r"|[A-Za-z0-9]{1,6}~\d"  # 8.3 short names such as ABC~1
    r"|[\\/]Users[\\/]"
    r"|[A-Za-z]:[\\/]Users\b"
    r"|/home/[A-Za-z0-9_.-]+"
    r"|~[\\/]"
    r"|/tmp/[A-Za-z0-9_]{4,}"
    r"|[\\/]Temp[\\/]",
    re.IGNORECASE,
)


def _output_texts(output: dict) -> list[str]:
    texts: list[str] = []
    if "text" in output:
        text = output["text"]
        texts.append("".join(text) if isinstance(text, list) else text)
    for mime, value in (output.get("data") or {}).items():
        if mime.startswith("text/") or mime.endswith("json"):
            texts.append("".join(value) if isinstance(value, list) else str(value))
    if "traceback" in output:
        texts.append("\n".join(output["traceback"]))
    return texts


def local_path_hits(notebook: dict) -> list[tuple[int, str]]:
    """(cell index, matched text) for every local path in the saved outputs."""
    hits: list[tuple[int, str]] = []
    for index, cell in enumerate(notebook.get("cells", [])):
        for output in cell.get("outputs", []) or []:
            for text in _output_texts(output):
                for match in LOCAL_PATH.finditer(text):
                    hits.append((index, text[max(0, match.start() - 30):match.end() + 30]))
    return hits


def _notebook(text: str) -> dict:
    return {"cells": [{"cell_type": "code", "source": [], "outputs": [
        {"output_type": "stream", "name": "stdout", "text": [text]}]}]}


#: A placeholder user name, assembled so this file spells out no home path itself.
U = "some" + "one"


class TestGuardFires(unittest.TestCase):
    def test_each_path_shape_is_caught(self):
        for text in (
            r"Image Source: ~\AppData\Local\Temp\demo\raw.2DS",
            "C:\\Users\\" + U + "\\data\\raw.2DS",
            "/Users/" + U + "/data/raw.2DS",
            "/home/" + U + "/data/raw.2DS",
            "C:\\Users\\" + "ABC" + "~1.DEF\\x",
            "/tmp/tmpab12cd/raw.2DS",
        ):
            with self.subTest(text=text):
                self.assertTrue(local_path_hits(_notebook(text)))

    def test_html_output_is_read(self):
        nb = {"cells": [{"cell_type": "code", "source": [], "outputs": [
            {"output_type": "execute_result", "data": {
                "text/html": ["<dd>C:\\Users\\" + U + "\\x.2DS</dd>"]}}]}]}
        self.assertTrue(local_path_hits(nb))

    def test_a_base_name_is_clean(self):
        self.assertEqual(local_path_hits(_notebook("Image Source: raw.2DS\nunits: mm")), [])


@repo_only
class TestShippedNotebooks(unittest.TestCase):
    def test_no_saved_output_shows_a_local_path(self):
        notebooks = sorted(EXAMPLES.rglob("*.ipynb"))
        self.assertTrue(notebooks, "no example notebooks found")
        found = []
        for path in notebooks:
            if ".ipynb_checkpoints" in path.parts:
                continue
            nb = json.loads(path.read_text(encoding="utf-8"))
            for index, snippet in local_path_hits(nb):
                found.append(f"{path.relative_to(ROOT)} cell {index}: {snippet!r}")
        self.assertEqual(found, [], "\n".join(found))


if __name__ == "__main__":
    unittest.main()


# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
