# SPDX-License-Identifier: BSD-3-Clause
"""``scripts/release.py`` rewrites the three version holders and the changelog
heading -- exercised against a throwaway copy of the tree, never the real one.

**Why a copy rather than mocking the module's path constants.** The script
computes ``ROOT``, ``INIT``, ``PYPROJECT``, ``CITATION`` and ``CHANGES`` from
``Path(__file__).resolve().parents[1]`` at import time, which is exactly the
shape that makes accidentally running a release script against the working
repository catastrophic if a test gets it wrong. A subprocess against a real
directory tree at the right relative depth is slower than monkeypatching four
module attributes, and that is the point: it is the same invocation a person
would type, so a bug in the path arithmetic shows up here rather than only
when someone runs it for real.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RELEASE_PY = PKG_ROOT / "scripts" / "release.py"
PY = Path(sys.executable)


def _build_tree(td: Path) -> None:
    """A minimal copy of the four files release.py touches, at the same
    relative depth (tmp/tools/release.py -> parents[1] == tmp)."""
    (td / "scripts").mkdir(parents=True)
    (td / "docs" / "developer").mkdir(parents=True)
    (td / "src" / "arrayprobe").mkdir(parents=True)
    shutil.copy(RELEASE_PY, td / "scripts" / "release.py")
    (td / "src" / "arrayprobe" / "__init__.py").write_text(
        '"""A throwaway package for this test."""\n\n'
        '__version__ = "1.0.0rc1"\n\n'
        '__all__ = ["__version__"]\n',
        encoding="utf-8")
    (td / "pyproject.toml").write_text(
        '[project]\n'
        'name = "arrayprobe"\n'
        'version = "1.0.0rc1"\n'
        'description = "test fixture"\n',
        encoding="utf-8")
    (td / "CITATION.cff").write_text(
        'cff-version: 1.2.0\n'
        'title: arrayprobe\n'
        'version: 1.0.0rc1\n'
        'authors:\n'
        '  - family-names: Test\n',
        encoding="utf-8")
    (td / "docs/developer/HISTORY.md").write_text(
        '# CHANGES\n\n'
        '## [Unreleased]\n\n'
        '### Added\n\n'
        '- something\n',
        encoding="utf-8")


def _run(td: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PY), str(td / "scripts" / "release.py"), *args],
        cwd=td, capture_output=True, text=True)


class ReleaseRewritesTheThreeHolders(unittest.TestCase):
    def test_a_clean_release_rewrites_all_four_files(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            _build_tree(td)

            r = _run(td, "--version", "1.0.0")
            self.assertEqual(r.returncode, 0, r.stderr)

            init = (td / "src" / "arrayprobe" / "__init__.py").read_text()
            self.assertIn('__version__ = "1.0.0"', init)
            self.assertNotIn("1.0.0rc1", init)

            pyproject = (td / "pyproject.toml").read_text()
            self.assertIn('version = "1.0.0"', pyproject)
            self.assertIn('name = "arrayprobe"', pyproject,
                          "the rewrite touched a line it should not have")

            citation = (td / "CITATION.cff").read_text()
            self.assertIn("version: 1.0.0\n", citation)
            self.assertIn("title: arrayprobe", citation,
                          "the rewrite touched a line it should not have")

            changes = (td / "docs/developer/HISTORY.md").read_text()
            self.assertRegex(
                changes, r"## \[Unreleased\]\s*\n\s*## \[1\.0\.0\] - \d{4}-\d{2}-\d{2}\s*\n",
                "the changelog heading was not rolled the Keep-a-Changelog way")
            # The prior content (the "### Added" block) must now sit UNDER the
            # new version heading, not have been dropped or duplicated.
            self.assertEqual(changes.count("- something"), 1)
            self.assertLess(
                changes.index("## [1.0.0]"), changes.index("### Added"),
                "the existing entries must follow the new version heading, "
                "not precede it")

    def test_the_real_repository_files_are_never_touched(self):
        """The whole reason this suite copies the tree: prove it did."""
        real_init = (PKG_ROOT / "src" / "arrayprobe" / "__init__.py").read_text(
            encoding="utf-8")
        real_pyproject = (PKG_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        real_citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        real_changes = (ROOT / "docs/developer/HISTORY.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            _build_tree(td)
            _run(td, "--version", "9.9.9")
        self.assertEqual(
            real_init,
            (PKG_ROOT / "src" / "arrayprobe" / "__init__.py").read_text(
                encoding="utf-8"))
        self.assertEqual(
            real_pyproject, (PKG_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(real_citation, (ROOT / "CITATION.cff").read_text(encoding="utf-8"))
        self.assertEqual(real_changes,
                         (ROOT / "docs/developer/HISTORY.md").read_text(encoding="utf-8"))

    def test_a_version_of_the_wrong_shape_is_refused_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            _build_tree(td)
            before = (td / "src" / "arrayprobe" / "__init__.py").read_text()

            r = _run(td, "--version", "not-a-version")
            self.assertNotEqual(r.returncode, 0)

            after = (td / "src" / "arrayprobe" / "__init__.py").read_text()
            self.assertEqual(before, after, "a rejected version must not have written anything")

    def test_a_second_run_refuses_a_changelog_with_no_unreleased_heading(self):
        """After one roll, [Unreleased] is empty of content but the heading
        itself is still there (a fresh one, ready for the next round of
        work) -- so a second cut on the same day must still succeed. This
        pins the ordering: [Unreleased] is re-created ABOVE the new version
        heading, not consumed by it."""
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            _build_tree(td)
            r1 = _run(td, "--version", "1.0.0")
            self.assertEqual(r1.returncode, 0, r1.stderr)

            r2 = _run(td, "--version", "1.0.1")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            changes = (td / "docs/developer/HISTORY.md").read_text()
            self.assertEqual(len(re.findall(r"^## \[Unreleased\]", changes, re.M)), 1)
            self.assertIn("## [1.0.0]", changes)
            self.assertIn("## [1.0.1]", changes)


_HOLDERS = {
    "src/arrayprobe/__init__.py": (b'"""A throwaway package."""', b"",
        b'__version__ = "1.0.0rc1"'),
    "pyproject.toml": (b"[project]", b'name = "arrayprobe"', b'version = "1.0.0rc1"',
        b'description = "test fixture"'),
    "CITATION.cff": (b"cff-version: 1.2.0", b"title: arrayprobe", b"version: 1.0.0rc1",
                     b"authors:", b"  - family-names: Test"),
    "docs/developer/HISTORY.md": (b"# CHANGES", b"", b"## [Unreleased]", b"",
        b"### Added", b"", b"- something"),
}
#: The one line release.py may change in each version holder, by index.
_NEW_LINES = {
    "src/arrayprobe/__init__.py": (2, b'__version__ = "1.0.0"'),
    "pyproject.toml": (2, b'version = "1.0.0"'),
    "CITATION.cff": (2, b"version: 1.0.0"),
}


def _cut_with(eol: bytes) -> tuple[dict[str, bytes], subprocess.CompletedProcess[str]]:
    """Write the four files as bytes, every line ended with *eol*, run
    ``release.py --version 1.0.0`` on them and return their bytes after."""
    with tempfile.TemporaryDirectory() as tds:
        td = Path(tds)
        (td / "scripts").mkdir()
        shutil.copy(RELEASE_PY, td / "scripts" / "release.py")
        for rel, lines in _HOLDERS.items():
            (td / rel).parent.mkdir(parents=True, exist_ok=True)
            (td / rel).write_bytes(eol.join(lines) + eol)
        r = _run(td, "--version", "1.0.0")
        return {rel: (td / rel).read_bytes() for rel in _HOLDERS}, r


class ReleaseKeepsEachFilesBytes(unittest.TestCase):
    """Only the version line changes, and LF stays LF while CRLF stays CRLF.

    Text-mode writing turned the LF ``CITATION.cff`` (``-text`` in
    ``.gitattributes``, byte-identical to its copies by
    ``tests/test_license_copies.py``) into CRLF on Windows: a whole-file diff.
    The fixtures are written as bytes so their line endings are the ones named
    here, not the platform's. Against text mode, the LF case fires on Windows
    (writing adds CR) and the CRLF case fires on Linux and macOS (universal-
    newline reading drops CR, writing does not put it back), so the pair fires
    on every platform CI runs."""

    def _check(self, eol: bytes) -> None:
        after, r = _cut_with(eol)
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel, blob in after.items():
            if eol == b"\n":
                self.assertNotIn(b"\r\n", blob, f"{rel}: LF was rewritten as CRLF")
            else:
                self.assertEqual(blob.count(b"\r\n"), blob.count(b"\n"),
                                 f"{rel}: CRLF was rewritten as LF")
        for rel, (i, line) in _NEW_LINES.items():
            expected = list(_HOLDERS[rel])
            expected[i] = line
            self.assertEqual(after[rel], eol.join(expected) + eol,
                             f"{rel}: a byte other than the version line changed")
        rolled = after["docs/developer/HISTORY.md"].split(eol)
        self.assertEqual(rolled[:4], [b"# CHANGES", b"", b"## [Unreleased]", b""])
        self.assertRegex(rolled[4], rb"^## \[1\.0\.0\] - \d{4}-\d{2}-\d{2}$")
        self.assertEqual(rolled[5:], [b"", b"### Added", b"", b"- something", b""])

    def test_an_lf_file_stays_lf(self):
        self._check(b"\n")

    def test_a_crlf_file_stays_crlf(self):
        self._check(b"\r\n")


class ReleaseHintsArePasteSafe(unittest.TestCase):
    def test_no_and_and_and_no_push_tags(self):
        """PowerShell 5.1 has no ``&&``, and ``git push --tags`` pushes every
        local tag; the hint pushes the one release tag by name."""
        _, r = _cut_with(b"\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("&&", r.stdout)
        self.assertNotIn("--tags", r.stdout)
        self.assertIn("git push origin v1.0.0", r.stdout)


if __name__ == "__main__":
    unittest.main()
