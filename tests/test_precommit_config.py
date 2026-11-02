# SPDX-License-Identifier: BSD-3-Clause
"""The pre-commit hook and CI must lint with the same ruff.

WHY THIS TEST EXISTS. ``.pre-commit-config.yaml`` pins ruff by a git tag
(``rev: v0.14.4``); ``requirements-dev.txt`` pins it by a version specifier
(``ruff==0.14.4``); CI installs the second and a developer's commit runs the
first. Nothing connects them. Ruff adds and changes rules between releases, so
a drift between the two pins produces the worst possible outcome for a hook
whose entire purpose is to move a finding earlier: a lint that passes at the
commit and fails in CI, which is strictly worse than having no hook, because it
teaches the developer to distrust the local result.

The two sides come from different files in different formats, which is the
property this project requires of a check -- its guard doctrine states it
as "a check must draw its two sides from different places, or it is testing
nothing".

No YAML parser is used. ``pyyaml`` is not a dependency of this package and the
core deliberately holds only numpy and netCDF4, so the fields are read with
regular expressions over a file whose shape is fixed and tiny.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._pins import pinned_version  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PRECOMMIT = _REPO_ROOT / ".pre-commit-config.yaml"


class PrecommitConfigTests(unittest.TestCase):
    def test_config_exists(self) -> None:
        self.assertTrue(_PRECOMMIT.is_file(), f"missing {_PRECOMMIT}")

    def test_ruff_pin_matches_requirements(self) -> None:
        config = _PRECOMMIT.read_text(encoding="utf-8")

        # The config pins more than one repository, so the `rev` compared here
        # is the one directly under the ruff repository, never the first found.
        rev = re.search(
            r"astral-sh/ruff-pre-commit\s*\n\s*rev:\s*v?([0-9][0-9.]*)\s*$",
            config,
            re.MULTILINE,
        )
        self.assertIsNotNone(rev, "no `rev:` under the ruff repo in .pre-commit-config.yaml")

        # requirements-dev.txt in the development repository, pyproject.toml's
        # [pinned] extra in the public tree (tests/_pins.py).
        pin = pinned_version("ruff", "requirements-dev.txt")
        self.assertIsNotNone(pin, "no `ruff==` pin in requirements-dev.txt or the [pinned] extra")

        assert rev is not None and pin is not None  # for the type checker
        self.assertEqual(
            rev.group(1),
            pin,
            "the pre-commit ruff `rev` and the `ruff==` pin "
            "disagree, so the commit hook and CI can reach different verdicts",
        )

    def test_hook_scope_is_the_documented_lint_scope(self) -> None:
        """The hook must cover every directory the documented command does.

        CI's Lint step is the scope; ``tests/test_lint_scope.py`` derives a
        sample per directory from it. These named paths are the ones whose
        joining the scope was each a fix for never having been linted at all;
        a hook that silently dropped any of them would reopen that gap.
        """
        config = _PRECOMMIT.read_text(encoding="utf-8")
        files = re.search(r"^\s*files:\s*(\S+)\s*$", config, re.MULTILINE)
        self.assertIsNotNone(files, "no `files:` scope on the ruff hook")
        assert files is not None
        pattern = re.compile(files.group(1))
        for path in (
            "src/arrayprobe_uiops/reject.py",
            "tests/test_reject.py",
            "scripts/run_flight.py",
            "paper/build_paper.py",
            "paper/figures/fig1_agreement_by_bin.py",
            "scripts/validation/gdl/locate.py",
            "scripts/validation/octave/dewrap.py",
            "scripts/validation/cgal/run_comparison.py",
            "docs/_build/build.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(pattern.search(path), f"hook does not cover {path}")

    def test_the_hook_does_not_run_the_suite(self) -> None:
        """A commit hook that runs 1253 tests would not survive contact.

        Recorded as a decision rather than left to taste: the suite is 70-140 s
        and belongs in CI. If someone adds it here, this test says why not.
        """
        config = _PRECOMMIT.read_text(encoding="utf-8")
        for forbidden in ("unittest", "pytest"):
            self.assertNotIn(
                forbidden,
                config.split("repos:", 1)[1],
                f"the pre-commit config runs {forbidden}; the suite belongs in CI",
            )


if __name__ == "__main__":
    unittest.main()
