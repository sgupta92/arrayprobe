# SPDX-License-Identifier: BSD-3-Clause
"""A tracked fixture that vanishes must fail the suite, not quietly skip it.

WHY THIS EXISTS. Many oracle tests are guarded like this::

    @unittest.skipUnless(GOLDEN.is_file(), "Octave golden not present")

which is right for a fixture that genuinely may be absent — a 38 GB campaign
archive, a raw probe file nobody clones. It is wrong for a fixture the
repository *tracks*. Delete or rename one of those and the guard reads it as
"this machine does not have the data", so the differential-oracle comparison it
protects stops running and the suite still reports OK.

That is not hypothetical here. Two skips found on
2026-09-05 had messages that claimed the machine lacked data while the data sat one
directory away, and the lesson written down then was: **a skip whose message is
a statement about the machine must actually be about the machine.** A source
audit on 2026-09-06 found fourteen more modules guarding on tracked fixtures the
same way.

Rewriting fourteen guards would mean fourteen chances to get one wrong. This
asserts the invariant they all depend on instead: everything git tracks under
``tests/data`` is on disk. If a fixture is deleted, this fails loudly and names
it, and the oracle tests that would have silently skipped are the ones whose
absence the failure explains.

WHAT IT DOES NOT DO. It cannot tell whether a *present* fixture is still
correct, and it says nothing about untracked data. Those are different problems.

**The other direction, added 2026-09-09.** Everything above assumes a
fixture is tracked and asks whether it is on disk. Five Octave goldens were the
opposite failure for as long as this project has existed: physically present
on the author's machine, referenced by name in test source, and *silently
gitignored* by ``.gitignore``'s blanket ``*.cdf`` (no negation existed for
them, unlike the ``.nc`` rule two lines below it) -- so every local run passed
while a fresh clone would have hit ``skipUnless`` guards or, in one case
(``test_sizedist_reacceptance.py``), a default that happened to equal the
missing fixture's own value, masking the gap completely. ``EveryReferencedFixtureIsTracked``
closes that direction: every filename a test literally names under
``tests/data/`` must be tracked by git, unless it is explicitly named as a
legitimate side-effect byproduct below.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT, repo_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = "tests/data"
DATA_DIR = ROOT / DATA

#: Files that legitimately sit in tests/data/ without being tracked: byproducts
#: a real ``sizeDist`` run writes as a side effect (``sizeDist.m:1651``,
#: ``<outfile>withShatters.mat`` / ``noShatters.mat``) when a test exercises
#: that path with ``save_workspace_mat=True``, not fixtures anything compares
#: against. Named here, not pattern-matched, so a *new* untracked file this
#: rule was not written for still fails loudly.
KNOWN_BYPRODUCTS = {
    "reacceptance_sizedist_octave_goldennoShatters.mat",
    "s4_aspectratio_octave_goldenwithShatters.mat",
}

#: A filename pattern good enough to find "tests/data/<name>" mentions in test
#: source without needing to fully parse every f-string or Path(...) join --
#: those are covered by the tests already reading the literal each individual
#: test's constant is built from.
_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*\.(?:cdf|nc|mat|csv|json|txt)")


def _tracked() -> list[str]:
    """Paths git tracks under the fixture directory, or [] if git cannot run.

    A source tarball with no ``.git`` is a legitimate way to receive this
    repository, so an absent git is a skip. A git that runs and returns nothing
    is NOT — that is the empty-glob failure this file exists to prevent.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", DATA],
            capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


#: Fixtures that are empty on purpose, each with the file that reads it and why.
DELIBERATELY_EMPTY = {
    "tests/data/soda2_pth_empty.txt": (
        "scripts/validation/gdl/run_soda2_pth_readers_bank.py",
        "the txt_empty case: IDL's PTH ASCII reader on a zero-byte file"),
}


class EveryTrackedFixtureIsOnDisk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tracked = _tracked()

    def test_git_reported_a_fixture_list(self):
        """An empty list would make the real assertion vacuous."""
        if not self.tracked:
            self.skipTest("git unavailable or this is not a git checkout")
        self.assertGreater(
            len(self.tracked), 30,
            f"git tracks only {len(self.tracked)} files under {DATA}; that is "
            "far fewer than expected and suggests the listing, not the tree, "
            "is wrong")

    @repo_only
    def test_no_tracked_fixture_is_missing(self):
        if not self.tracked:
            self.skipTest("git unavailable or this is not a git checkout")
        missing = [p for p in self.tracked if not (ROOT / p).is_file()]
        self.assertEqual(
            missing, [],
            "these fixtures are tracked by git and absent from the working "
            "tree. Every oracle test guarded on one of them is skipping right "
            f"now, and the suite will still report OK: {missing}")

    @repo_only
    def test_no_tracked_fixture_is_empty(self):
        """A zero-byte fixture passes an ``is_file()`` guard and then compares
        nothing — the same silent pass in a different disguise."""
        if not self.tracked:
            self.skipTest("git unavailable or this is not a git checkout")
        empty = [p for p in self.tracked
                 if (ROOT / p).is_file() and (ROOT / p).stat().st_size == 0
                 and p not in DELIBERATELY_EMPTY]
        self.assertEqual(empty, [], f"tracked fixtures with no content: {empty}")

    @repo_only
    def test_each_deliberately_empty_fixture_is_still_used(self):
        """An exemption must name a fixture that exists, is empty, and is still
        read by the code its reason names -- else the exemption hides a stray."""
        # Fixture and reader both resolve from the repository root.
        for rel, (user, _why) in DELIBERATELY_EMPTY.items():
            with self.subTest(fixture=rel):
                fixture = ROOT / rel
                reader = ROOT / user
                self.assertTrue(fixture.is_file(), rel)
                self.assertEqual(fixture.stat().st_size, 0, rel)
                self.assertIn(Path(rel).name, reader.read_text(encoding="utf-8"),
                              f"{user} no longer uses {rel}; drop the exemption")


def _names_mentioned_in_tests() -> set[str]:
    """Every bare filename any test source file mentions, regardless of how
    it is embedded (plain string, f-string, comment) -- deliberately loose,
    because the failure this guards is a name silently NOT reaching the
    fixture it names, and a regex over raw text cannot miss that the way an
    AST walk restricted to plain ``ast.Constant`` string literals would."""
    names: set[str] = set()
    for p in (PKG_ROOT / "tests").glob("test_*.py"):
        names |= set(_NAME_RE.findall(p.read_text(encoding="utf-8", errors="replace")))
    return names


class EveryReferencedFixtureIsTracked(unittest.TestCase):
    """The direction ``EveryTrackedFixtureIsOnDisk`` above does not check:
    a file physically present under ``tests/data/`` and named by a test, but
    gitignored rather than tracked. See this module's docstring for the five
    Octave goldens this caught in 2026-09-09.
    """

    @classmethod
    def setUpClass(cls):
        cls.mentioned = _names_mentioned_in_tests()
        cls.tracked_names = {Path(p).name for p in _tracked()}

    @repo_only
    def test_data_dir_holds_more_than_the_two_known_byproducts(self):
        """The empty-glob failure this file exists to prevent, on the other
        side: if DATA_DIR resolved to nothing, the assertion below would pass
        having examined zero files."""
        if not DATA_DIR.is_dir():
            self.skipTest(f"{DATA_DIR} does not exist in this checkout")
        on_disk = {p.name for p in DATA_DIR.iterdir() if p.is_file()}
        self.assertGreater(
            len(on_disk - KNOWN_BYPRODUCTS), 30,
            f"only {len(on_disk)} file(s) on disk under {DATA_DIR}; expected "
            "far more, which suggests the directory or this check is wrong")

    @repo_only
    def test_every_mentioned_fixture_present_on_disk_is_tracked(self):
        if not DATA_DIR.is_dir():
            self.skipTest(f"{DATA_DIR} does not exist in this checkout")
        if not self.tracked_names:
            self.skipTest("git unavailable or this is not a git checkout")
        untracked = sorted(
            name for name in self.mentioned
            if (DATA_DIR / name).is_file()
            and name not in KNOWN_BYPRODUCTS
            and name not in self.tracked_names
        )
        self.assertEqual(
            untracked, [],
            "these files are named by a test, present under tests/data/ on "
            "this machine, and NOT tracked by git -- exactly the five Octave "
            "goldens found gitignored by accident 2026-09-09. A fresh clone "
            "will not have them, and the test that names one either skips "
            "(if it guards on presence) or silently exercises a fallback "
            f"(if it does not): {untracked}")

    def test_the_known_byproducts_list_names_only_untracked_files(self):
        """If a byproduct's name were ever tracked (a golden actually
        committed under that exact name), keeping it in KNOWN_BYPRODUCTS
        would hide that -- the allowlist must not grow stale in the direction
        that defeats the check above."""
        wrongly_listed = sorted(KNOWN_BYPRODUCTS & self.tracked_names)
        self.assertEqual(
            wrongly_listed, [],
            f"these are tracked by git but still listed in KNOWN_BYPRODUCTS "
            f"as though they were not: {wrongly_listed}")


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite.
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
