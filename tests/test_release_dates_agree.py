# SPDX-License-Identifier: BSD-3-Clause
"""The release date is one date: the three ``CITATION.cff`` ``date-released`` fields and the
current version's ``HISTORY.md`` heading agree, and ``scripts/set_release_date.py`` moves
all four together or none.

Built 2026-10-31, when the release slipped a second day and the four dates had twice been
moved by hand with nothing checking that they still matched. The script runs as a subprocess
against a throwaway copy of the four files at the right relative depth, never the real tree
(the same reasoning as ``tests/test_release.py``).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT, repo_only  # noqa: E402

SCRIPT = PKG_ROOT / "scripts" / "set_release_date.py"
PY = Path(sys.executable)
FILES = ("pyproject.toml", "CITATION.cff", "enhancements_uiops/CITATION.cff",
         "enhancements_soda2/CITATION.cff", "docs/developer/HISTORY.md")


def _run(root, *args):
    return subprocess.run([str(PY), str(root / "scripts" / "set_release_date.py"), *args],
                          capture_output=True, text=True, timeout=120)


@repo_only  # the enhancement packages' CITATION.cff files and scripts/ are not in the sdist
class TestReleaseDatesAgree(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for rel in FILES + ("scripts/set_release_date.py",):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PKG_ROOT / rel, self.tmp / rel)

    def test_the_four_dates_agree_in_this_tree(self):
        r = subprocess.run([str(PY), str(SCRIPT), "--check"], capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_fires_on_one_disagreeing_date(self):
        p = self.tmp / "enhancements_soda2" / "CITATION.cff"
        b = p.read_bytes()
        i = b.index(b"date-released: '") + len(b"date-released: '")
        p.write_bytes(b[:i] + b"1999-01-01" + b[i + 10:])
        r = _run(self.tmp, "--check")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("disagree", r.stdout)

    def test_check_today_fires_on_a_past_date(self):
        self.assertEqual(_run(self.tmp, "--date", "2000-01-01").returncode, 0)
        r = _run(self.tmp, "--check", "--today")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not today", r.stdout)

    def test_set_moves_all_four_and_keeps_every_other_byte(self):
        before = {rel: (self.tmp / rel).read_bytes() for rel in FILES[1:]}
        r = _run(self.tmp, "--date", "2031-02-03")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(_run(self.tmp, "--check").returncode, 0)
        for rel, old in before.items():
            new = (self.tmp / rel).read_bytes()
            self.assertIn(b"2031-02-03", new, rel)
            self.assertEqual(len(new), len(old), rel)  # one date swapped, nothing else moved
            self.assertEqual(sum(a != b for a, b in zip(old, new, strict=True)) <= 10, True, rel)

    def test_a_missing_site_refuses_and_writes_nothing(self):
        h = self.tmp / "docs" / "developer" / "HISTORY.md"
        ver = re.search(rb'(?m)^version = "([^"]+)"', (self.tmp / "pyproject.toml").read_bytes())
        heading = b"## [" + ver.group(1) + b"] - "
        self.assertIn(heading, h.read_bytes())  # the site this test removes is really there
        h.write_bytes(h.read_bytes().replace(heading, b"## (removed) - ", 1))
        before = {rel: (self.tmp / rel).read_bytes() for rel in FILES[1:]}
        r = _run(self.tmp, "--date", "2031-02-03")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused", r.stdout + r.stderr)
        for rel, old in before.items():
            self.assertEqual((self.tmp / rel).read_bytes(), old, rel)


if __name__ == "__main__":
    unittest.main()
