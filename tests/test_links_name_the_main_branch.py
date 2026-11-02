# SPDX-License-Identifier: BSD-3-Clause
"""Links into the public repository name its default branch, ``main``.

The public repository is created with ``git init -b main`` on release day, and no
``master`` branch will exist there. On 2026-10-25 a check of the built tree found
546 repository links naming a ``master`` branch in six
pages and the two generators behind ``docs/41-all-on-sets.md`` and the stage
pages, beside README links already on ``main``: every one of them would have
answered 404 once the repository went public. This sweeps every text file the
tree holds outside ``archive/`` for a ``blob``, ``tree`` or ``raw`` link on any
branch other than ``main``.

A release tag (``v0.1.0``) is also allowed, since 2026-10-31: the PyPI description's images
are pinned to the release's tag (``tests/test_pypi_description_images_are_absolute.py``), so
that a later figure change cannot alter an old release's page.
"""
from __future__ import annotations

import re
import unittest

from tests._hygiene import hygiene
from tests._repo import PKG_ROOT  # noqa: E402

_LINK = re.compile(
    r"(?:github\.com/sgupta92/arrayprobe/(?:blob|tree|raw)|"
    r"raw\.githubusercontent\.com/sgupta92/arrayprobe)/([^/\s)\"'<>]+)/")
_SUFFIXES = {".md", ".py", ".ipynb", ".toml", ".cff", ".html", ".js", ".txt", ".yml", ".yaml",
             ".cfg"}
_SKIP_DIRS = {"archive", ".git", ".venv", "venv", "__pycache__", "run_logs", "_site", "build",
              "dist", ".claude", "node_modules"}


_OLD = "mas" + "ter"  # spelled in two parts so this file does not trip its own sweep
_TAG = re.compile(r"v\d+\.\d+\.\d+")


def wrong_branch_links(text: str) -> list[str]:
    """Every repository link in ``text`` whose ref is neither ``main`` nor a release tag."""
    return [m.group(0) for m in _LINK.finditer(text)
            if m.group(1) != "main" and not _TAG.fullmatch(m.group(1))]


def _text_files():
    for path in PKG_ROOT.rglob("*"):
        rel = path.relative_to(PKG_ROOT)
        if rel.parts and rel.parts[0] in _SKIP_DIRS:
            continue
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.suffix.lower() in _SUFFIXES and path.is_file():
            yield rel, path


@hygiene
class LinksNameTheMainBranch(unittest.TestCase):
    def test_the_check_fires_on_a_master_link_and_passes_main(self):
        # The repository names are spelled in parts so this file does not trip its own sweep.
        gh = "github.com/sgupta92/" + "arrayprobe"
        raw = "raw.githubusercontent.com/sgupta92/" + "arrayprobe"
        self.assertEqual(
            wrong_branch_links(f"[a](https://{gh}/blob/{_OLD}/docs/x.md) [b](https://{gh}/tree/main/examples)"),
            [f"{gh}/blob/{_OLD}/"])
        self.assertEqual(wrong_branch_links(f"https://{raw}/{_OLD}/a.png"), [f"{raw}/{_OLD}/"])
        self.assertEqual(wrong_branch_links(f"https://{gh}/raw/main/a.png"), [])
        self.assertEqual(wrong_branch_links(f"https://{raw}/v0.1.0/docs/figures/a.svg"), [])
        self.assertEqual(wrong_branch_links(f"https://{raw}/v0.1/a.svg"), [f"{raw}/v0.1/"])

    def test_no_file_links_a_branch_other_than_main(self):
        found = []
        for rel, path in _text_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                for link in wrong_branch_links(line):
                    found.append(f"{rel.as_posix()}:{n}: {link}")
        self.assertEqual(found, [], "\n".join(found[:20]))


if __name__ == "__main__":
    unittest.main()
