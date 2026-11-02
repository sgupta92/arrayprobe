# SPDX-License-Identifier: BSD-3-Clause
"""Every file under ``tests/data`` is tracked, unless it is one of two deliberate exceptions.

``*.nc`` is ignored repository-wide, and ``tests/data`` carries its exceptions one directory at a
time. On 2026-09-24 the probetype-0/3 Octave bank's ``.proc.nc``/``.sd.nc`` fixtures were found
untracked since the commit that added them (ca5ba75): only ``cases.json`` was committed, so
``test_v35_sizedist_probetype03`` passed here and errored on every fresh clone. The same shape was
caught once before by hand (the ``v35_sizedist`` note in ``.gitignore``). This makes it a check.

Deliberate exceptions: ``oracles_subsets/`` (campaign data, not redistributable; its own test,
``test_oracles_subsets``, covers the ignore lines) and Octave's ``*.mat`` workspace by-products,
which no test reads.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ignored_fixtures() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard",
         "tests/data"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    return [p for p in out if p
            and "__pycache__" not in p
            and not p.endswith(".mat")
            and "/oracles_subsets/" not in p
            # Run output, not a fixture: the README's first v3.5 run
            # (tests/data/demo_flight_v35_run.toml, out = "_decoded") writes here, and a new
            # user's next suite run failed on it (cloud pass 8 cold-user run, 2026-09-27).
            and not p.startswith("tests/data/_decoded/")]


class EveryFixtureIsTracked(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None or not (ROOT / ".git").exists():
            self.skipTest("needs a git checkout")

    def test_no_fixture_is_silently_ignored(self):
        self.assertEqual(
            ignored_fixtures(), [],
            "a file under tests/data exists here but is ignored by git, so a fresh clone "
            "will not have it: add a `!` exception to .gitignore and commit it")


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
