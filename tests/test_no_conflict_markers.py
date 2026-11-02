# SPDX-License-Identifier: BSD-3-Clause
"""No tracked file carries a git merge-conflict marker.

On 2026-09-26 a merge commit landed with ``paper/paper_numbers.json`` still holding its
``<<<<<<<`` / ``=======`` / ``>>>>>>>`` block: the script that resolved the hunk matched ``\\n``
where the file has ``\\r\\n``, raised before writing, and the commit ran anyway. The pre-commit
hook checks only Python with ruff, and a JSON file with markers in it is not valid JSON but is
still an ordinary tracked file, so nothing else saw it. This sweep reads every tracked text file.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from tests._repo import git_checkout_only

ROOT = Path(__file__).resolve().parents[1]

# A marker line: seven of the character at the start of a line, then a space or the end of the
# line. "=======" alone is also a reStructuredText/Markdown underline, so it only counts when it
# sits between an opening and a closing marker.
_OPEN = re.compile(r"^<{7}(?: |$)", re.M)
_CLOSE = re.compile(r"^>{7}(?: |$)", re.M)

# Files that quote a conflict block on purpose.
_ALLOWED = {
    "tests/test_no_conflict_markers.py",
}


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def files_with_markers() -> list[str]:
    bad = []
    for rel in _tracked_files():
        if rel in _ALLOWED:
            continue
        path = ROOT / rel
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue  # binary
        text = data.decode("utf-8", "replace")
        if _OPEN.search(text) and _CLOSE.search(text):
            bad.append(rel)
    return bad


class NoConflictMarkers(unittest.TestCase):

    @git_checkout_only
    def test_no_tracked_file_carries_a_conflict_block(self):
        self.assertEqual(files_with_markers(), [],
                         "merge-conflict markers in tracked files: resolve them")

    def test_the_sweep_finds_a_planted_block(self):
        text = "a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> branch\n"
        self.assertTrue(_OPEN.search(text) and _CLOSE.search(text))
        crlf = text.replace("\n", "\r\n")
        self.assertTrue(_OPEN.search(crlf) and _CLOSE.search(crlf))


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
