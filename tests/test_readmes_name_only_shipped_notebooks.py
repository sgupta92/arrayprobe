# SPDX-License-Identifier: BSD-3-Clause
"""A shipped README or page names no notebook the release carves out.

``scripts/release_allowlist.txt`` holds some example notebooks back with ``!examples/...ipynb``
rows. ``tests/test_notebook_names_are_current`` only accepts an ``NN_name.ipynb`` token that
exists in the development tree, where the held-back notebook does, and the release builder's
notebook rule only matches the ``.ipynb`` form; a README that names the notebook by its stem
(``01_another_probe`` in a code span or a table cell) passed both and promised a reader a
notebook the public tree lacks.

The two sides come from different places: the carved-out stems are read from the allow-list,
the mentions from the shipped files. ``TestTheCheckFires`` plants a bad README in a temporary
tree so a check that matches nothing cannot pass silently.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"
PREFIX = "!examples/"


def carved_stems(allowlist_text: str) -> dict[str, str]:
    """{stem: path under examples/} for every ``!examples/**/NN_name.ipynb`` row."""
    out: dict[str, str] = {}
    for line in allowlist_text.splitlines():
        glob = line.split("\t", 1)[0].strip()
        if glob.startswith(PREFIX) and glob.endswith(".ipynb"):
            rel = glob[len(PREFIX):]
            out[Path(rel).stem] = rel
    return out


def _texts(root: Path, held_back: set[str]):
    """(relative path, text) of every shipped surface that can promise a notebook."""
    files = [*root.glob("examples/**/README.md"), root / "README.md",
             *root.glob("docs/*.md"), root / "docs" / "developer" / "PACKAGE_README.md"]
    for p in files:
        if p.is_file():
            yield p.relative_to(root).as_posix(), p.read_text(encoding="utf-8")
    import json
    for p in root.glob("examples/**/*.ipynb"):
        if p.relative_to(root / "examples").as_posix() in held_back:
            continue  # itself not shipped
        nb = json.loads(p.read_text(encoding="utf-8"))
        text = "\n".join("".join(c.get("source", [])) for c in nb.get("cells", []))
        yield p.relative_to(root).as_posix(), text


def promises(root: Path, allowlist_text: str) -> list[str]:
    """``path:line: stem`` for each mention of a carved-out notebook by name."""
    carved = carved_stems(allowlist_text)
    pats = {s: re.compile(r"(?<![\w-])" + re.escape(s) + r"(?![\w-])") for s in carved}
    found = []
    for rel, text in _texts(root, set(carved.values())):
        for n, line in enumerate(text.splitlines(), 1):
            for stem, rx in pats.items():
                if rx.search(line):
                    found.append(f"{rel}:{n}: {stem}")
    return found


@unittest.skipUnless(ALLOWLIST.is_file(), "the allow-list is a development file")
class ShippedPagesNameOnlyShippedNotebooks(unittest.TestCase):
    def test_the_allowlist_carves_out_some_notebooks(self):
        self.assertGreaterEqual(len(carved_stems(ALLOWLIST.read_text(encoding="utf-8"))), 1)

    def test_no_shipped_page_names_a_carved_out_notebook(self):
        found = promises(ROOT, ALLOWLIST.read_text(encoding="utf-8"))
        self.assertEqual(found, [], "shipped pages naming a notebook the release holds back "
                         "(drop the row or reword):\n  " + "\n  ".join(found))


class TestTheCheckFires(unittest.TestCase):
    ALLOW = ("examples/**\tnotebooks\n"
             "!examples/2_processing/07_planted_probe.ipynb\theld back\n")

    def test_a_planted_bad_readme_is_found_and_a_good_one_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "examples" / "2_processing").mkdir(parents=True)
            readme = root / "examples" / "2_processing" / "README.md"
            readme.write_text("1. `07_planted_probe`: a DMT PIP\n2. `03_whole_campaign`: many\n",
                              encoding="utf-8")
            self.assertEqual(promises(root, self.ALLOW),
                             ["examples/2_processing/README.md:1: 07_planted_probe"])
            readme.write_text("1. `03_whole_campaign`: many\n", encoding="utf-8")
            self.assertEqual(promises(root, self.ALLOW), [])

    def test_the_stem_is_read_from_the_allowlist(self):
        self.assertEqual(carved_stems(self.ALLOW),
                         {"07_planted_probe": "2_processing/07_planted_probe.ipynb"})


if __name__ == "__main__":
    unittest.main()
