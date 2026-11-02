# SPDX-License-Identifier: BSD-3-Clause
"""No tracked text file in the edited trees mixes CRLF and bare LF line endings.

A file with both endings breaks scripted edits: an anchor copied from one line
carries the wrong terminator for the next, so the edit fails to match. On
2026-10-03 five agent slices lost their time this way. The survey and the
one-pass normalisation were
done; this guard keeps the
class closed. A second case shows the check firing on a synthetic mixed file.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
#: The trees normalised in one pass; vendored upstream trees are out of scope
#: (they are ``-text`` and frozen byte for byte).
SCOPE = (
    "src/", "tests/", "scripts/",
    "enhancements", "docs/_build/", "project/pages/",
)
#: Data fixtures and notebooks keep whatever bytes they were written with.
EXCLUDED_PREFIXES = ("tests/data/",)
EXCLUDED_SUFFIXES = (".ipynb", ".svg")


def is_mixed(data: bytes) -> bool:
    """True when ``data`` is text holding both CRLF and a bare LF."""
    if b"\0" in data[:8192]:
        return False
    crlf = data.count(b"\r\n")
    return crlf > 0 and data.count(b"\n") > crlf


def mixed_files(root: Path) -> list[str]:
    """Tracked files under SCOPE in ``root`` whose working copy is mixed."""
    out = subprocess.run(["git", "ls-files", "-z", "--", *SCOPE], cwd=root,
                         capture_output=True, check=True).stdout
    bad = []
    for rel in out.decode("utf-8").split("\0"):
        if (not rel or rel.startswith(EXCLUDED_PREFIXES)
                or rel.endswith(EXCLUDED_SUFFIXES)):
            continue
        path = root / rel
        if path.is_file() and is_mixed(path.read_bytes()):
            bad.append(rel)
    return bad


@hygiene
@repo_only
class NoMixedLineEndings(unittest.TestCase):
    def test_no_tracked_file_in_scope_mixes_crlf_and_lf(self):
        self.assertEqual([], mixed_files(ROOT),
                         "normalise each file to its dominant line ending")


@hygiene
@repo_only
class GuardFires(unittest.TestCase):
    def test_a_synthetic_mixed_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo, check=True)
            target = repo / "src" / "mixed.py"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"a = 1\r\nb = 2\n")
            clean = repo / "src" / "clean.py"
            clean.write_bytes(b"a = 1\r\nb = 2\r\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            self.assertEqual(["src/mixed.py"], mixed_files(repo))

    def test_is_mixed_classifies(self):
        self.assertTrue(is_mixed(b"x\r\ny\n"))
        self.assertFalse(is_mixed(b"x\r\ny\r\n"))
        self.assertFalse(is_mixed(b"x\ny\n"))


if __name__ == "__main__":
    unittest.main()
