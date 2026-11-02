# SPDX-License-Identifier: BSD-3-Clause
"""``docs/developer/HISTORY.md`` stays Keep-a-Changelog shaped: this is a repository test --
it reads ``docs/developer/HISTORY.md`` and ``CITATION.cff``, neither of which ships
in the source distribution (see ``MANIFEST.in``'s exclude list) -- so a
tarball install has nothing for it to check.

The top heading
is ``[Unreleased]``, every other ``## [x.y.z]`` heading names a real git tag
(so the changelog can never claim a release that was not cut), and
``CITATION.cff``'s ``title:`` equals ``pyproject.toml``'s ``name`` -- checked
by value, not assumed, so a rename of either does not silently orphan the
citation record.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import PKG_ROOT, repo_only  # noqa: E402

try:
    import tomllib
except ImportError:  # pragma: no cover -- Python < 3.11, not this project's floor
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
CHANGES = ROOT / "docs/developer/HISTORY.md"
CITATION = ROOT / "CITATION.cff"
PYPROJECT = PKG_ROOT / "pyproject.toml"

HEADING = re.compile(r"^## \[([^\]]+)\]", re.M)


def untagged(released: list[str], tags: set[str], current: str) -> list[str]:
    """Release headings with no ``v<version>`` or ``<version>`` tag, except ``current``.

    ``release.py`` stamps the heading of the version being released before its tag can
    exist: the tag is pushed last, on the public repository, and that push is what uploads
    the release, so every CI run before it (and every checkout without tags) sees the
    heading untagged. The heading equal to the package's own version is that release in
    progress; every older heading must have its tag.
    """
    return [h for h in released if h != current and f"v{h}" not in tags and h not in tags]


@repo_only
@hygiene
class TheFilesTheseClassesReadArePresent(unittest.TestCase):
    """Both classes below skip when their file is absent, so a moved or renamed
    ``docs/developer/HISTORY.md`` or ``CITATION.cff`` would silently remove every check here
    (guard audit). In a checkout, under the gate, absence is a failure."""

    def test_changes_and_citation_are_present(self) -> None:
        for path in (CHANGES, CITATION):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(),
                                f"{path} is missing: the changelog/citation checks "
                                "would all skip -- update the path")

    def test_the_presence_check_fires_on_a_missing_file(self) -> None:
        import sys
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            gone = Path(d) / "docs/developer/HISTORY.md"
            with mock.patch.object(sys.modules[__name__], "CHANGES", gone):
                probe = TheFilesTheseClassesReadArePresent(
                    "test_changes_and_citation_are_present")
                result = unittest.TestResult()
                probe.run(result)
                self.assertTrue(result.failures,
                                "the presence check passed with docs/developer/HISTORY.md missing")


@hygiene
class ChangelogIsKeepAChangelogShaped(unittest.TestCase):
    def setUp(self):
        if not CHANGES.is_file():
            self.skipTest(f"{CHANGES} not present -- nothing to check")
        self.text = CHANGES.read_text(encoding="utf-8")
        self.headings = HEADING.findall(self.text)

    def test_the_file_has_at_least_one_release_heading(self):
        self.assertTrue(self.headings,
                        "docs/developer/HISTORY.md has no '## [...]' headings at all")

    def test_the_top_heading_is_unreleased(self):
        self.assertEqual(
            self.headings[0], "Unreleased",
            "the first '## [...]' heading must be '[Unreleased]' -- accumulating "
            "changes go there until release.py rolls them into a tagged section")

    def test_every_non_unreleased_heading_is_a_real_tag(self):
        """A changelog entry for a version nobody tagged is a claim the
        repository cannot back up -- exactly the shape of drift this
        project's own doctrine builds a check for rather than a rule."""
        released = [h for h in self.headings if h != "Unreleased"]
        if not released:
            self.skipTest("no releases cut yet -- nothing to check against tags")
        r = subprocess.run(["git", "tag", "-l"], cwd=ROOT, capture_output=True, text=True)
        tags = set(r.stdout.split())
        current = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
        missing = untagged(released, tags, current)
        self.assertEqual(
            missing, [],
            f"docs/developer/HISTORY.md names version(s) with no matching git tag: {missing} "
            f"(looked for 'v<version>' and '<version>' among {sorted(tags)})")

    def test_an_untagged_older_release_is_still_reported(self):
        self.assertEqual(untagged(["0.1.1", "0.1.0"], set(), "0.1.1"), ["0.1.0"])
        self.assertEqual(untagged(["0.1.1", "0.1.0"], {"v0.1.0"}, "0.1.1"), [])

    def test_the_release_in_progress_may_be_untagged(self):
        self.assertEqual(untagged(["0.1.0"], set(), "0.1.0"), [])

    def test_no_heading_repeats(self):
        dupes = sorted({h for h in self.headings if self.headings.count(h) > 1})
        self.assertEqual(dupes, [], f"duplicate changelog headings: {dupes}")


@hygiene
class CitationTitleMatchesThePackageName(unittest.TestCase):
    def test_title_equals_the_pyproject_name(self):
        if not CITATION.is_file():
            self.skipTest(f"{CITATION} not present -- nothing to check")
        citation_text = CITATION.read_text(encoding="utf-8")
        m = re.search(r"^title:\s*(\S+)\s*$", citation_text, re.M)
        self.assertIsNotNone(m, "CITATION.cff has no 'title:' line")
        with open(PYPROJECT, "rb") as fh:
            name = tomllib.load(fh)["project"]["name"]
        self.assertEqual(
            m.group(1), name,
            "CITATION.cff's title and pyproject.toml's name have drifted -- "
            "a rename of either orphans the citation record from the package "
            "it is supposed to describe")


if __name__ == "__main__":
    unittest.main()
