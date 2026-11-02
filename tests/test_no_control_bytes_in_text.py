# SPDX-License-Identifier: BSD-3-Clause
"""No tracked text file carries a stray control byte (0x01-0x08).

A backslash escape that passes through a shell heredoc can collapse into the byte it names:
``r"\\1"`` became 0x01 in the release builder's GitHub slug (link text in headings vanished, so
its link check passed anchors GitHub breaks) and ``D:\\arrayprobe`` became ``D:`` + BEL +
``rrayprobe`` in a quoted ledger row. Both read fine in most viewers. Found 2026-10-11.

Binary files (any NUL byte) are skipped, and so are the history and vendored trees, which are
never edited.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from tests._repo import git_checkout_only

REPO = Path(__file__).resolve().parents[1]
CONTROL = re.compile(rb"[\x01-\x08]")
SKIP = ("archive/", "UIOPS-v3.1.4/", "UIOPS-v3.5/", "SODA2/", "uioops_testing/")


def offenders(root: Path, files: list[str]) -> list[str]:
    out = []
    for f in files:
        if f.startswith(SKIP):
            continue
        p = root / f
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:
            continue
        m = CONTROL.search(data)
        if m:
            line = data.count(b"\n", 0, m.start()) + 1
            out.append(f"{f}:{line}: byte 0x{m.group()[0]:02x}")
    return out


@git_checkout_only
class NoControlBytes(unittest.TestCase):
    def test_tracked_text_has_none(self):
        files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                               check=True).stdout.splitlines()
        self.assertGreater(len(files), 1000)
        self.assertEqual(offenders(REPO, files), [])

    def test_the_check_fires_on_a_collapsed_escape(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_bytes(b'x = re.sub(r"(a)", r"\x01", s)\n')
            (root / "b.bin").write_bytes(b"\x00\x01")
            (root / "archive").mkdir()
            (root / "archive" / "c.md").write_bytes(b"\x07")
            self.assertEqual(offenders(root, ["a.py", "b.bin", "archive/c.md"]),
                             ["a.py:1: byte 0x01"])


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
