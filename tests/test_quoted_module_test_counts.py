# SPDX-License-Identifier: BSD-3-Clause
"""A per-module test count quoted in a user-facing document matches the module.

User docs quote a module's size beside its name -- ``test_x.py`` (N tests),
``test_x.py``, N tests, or ``test_x`` (N tests) -- and those numbers drift as the
module grows. This guard reads every such quote in ``docs/*.md``,
``docs/developer/*.md``, ``README.md``, ``enhancements_uiops/README.md`` and
``enhancements_soda2/README.md``, resolves the module under ``tests/``,
``enhancements_uiops/tests/`` or ``enhancements_soda2/tests/``, counts its
``def test_`` methods with ``tools.sync_counts.count_tests_in`` (the counter the
repository's propagated totals use, imported, not copied), and fails naming every
``file:line`` whose number disagrees.

Exemption: a quote on a line that carries an ISO date (``YYYY-MM-DD``) is a dated
historical record -- a table row stating how large a module was when a stage
landed -- and is not checked. A quote naming no module that exists is reported
too, so a rename cannot leave a quote silently unchecked.
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import REPO_ROOT, repo_only

ROOT = REPO_ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.sync_counts import count_tests_in  # noqa: E402
except ImportError:  # the released tree ships without the repository's count tool
    raise unittest.SkipTest("the repository's count tool is not in this tree") from None

#: ``test_x.py`` (N tests) | ``test_x.py``, N tests | ``test_x`` (N tests),
#: backticks optional.
QUOTE_RE = re.compile(
    r"`?\b(test_\w+?)(?:\.py)?`?"
    r"(?:\s*\((\d[\d,]*)\s+tests?\)|,\s*(\d[\d,]*)\s+tests?\b)"
)
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

TEST_DIRS = (
    ROOT / "tests",
    ROOT / "enhancements_uiops" / "tests",
    ROOT / "enhancements_soda2" / "tests",
)


def user_docs() -> list[Path]:
    docs = sorted((ROOT / "docs").glob("*.md"))
    docs += sorted((ROOT / "docs" / "developer").glob("*.md"))
    docs += [ROOT / "README.md", ROOT / "enhancements_uiops" / "README.md",
             ROOT / "enhancements_soda2" / "README.md"]
    return [d for d in docs if d.is_file()]


def stale_quotes(text: str, label: str, test_dirs=TEST_DIRS) -> list[str]:
    """Every undated quote in ``text`` whose count disagrees with its module."""
    problems = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if ISO_DATE_RE.search(line):
            continue
        for m in QUOTE_RE.finditer(line):
            module = m.group(1)
            quoted = int((m.group(2) or m.group(3)).replace(",", ""))
            paths = [d / f"{module}.py" for d in test_dirs if (d / f"{module}.py").is_file()]
            if not paths:
                problems.append(f"{label}:{lineno}: {module} quoted as {quoted} tests, "
                                "but no such test module exists")
                continue
            actual = count_tests_in(paths[0])
            if actual != quoted:
                problems.append(f"{label}:{lineno}: {module} quoted as {quoted} tests, "
                                f"has {actual}")
    return problems


@hygiene
@repo_only
class TestQuotedModuleTestCounts(unittest.TestCase):
    def test_every_undated_quote_matches_its_module(self):
        problems = []
        for doc in user_docs():
            problems += stale_quotes(doc.read_text(encoding="utf-8", errors="replace"),
                                     doc.relative_to(ROOT).as_posix())
        self.assertEqual([], problems, "\n".join(problems))

    def test_the_scan_finds_quotes(self):
        # A pattern that matched nothing would pass the check above vacuously.
        found = sum(len(QUOTE_RE.findall(d.read_text(encoding="utf-8", errors="replace")))
                    for d in user_docs())
        self.assertGreater(found, 5)


@hygiene
@repo_only  # the counter it calls is repository tooling, not in the sdist
class TestTheGuardFiresAndSpares(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "test_planted.py").write_text(
            "class T:\n    def test_a(self): pass\n    def test_b(self): pass\n"
            "    def test_c(self): pass\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, text: str) -> list[str]:
        return stale_quotes(text, "doc.md", test_dirs=(self.dir,))

    def test_fires_on_each_form(self):
        for text in ("see `test_planted.py` (5 tests).",
                     "see `test_planted.py`, 5 tests.",
                     "see `test_planted` (5 tests)."):
            with self.subTest(text=text):
                problems = self.check(text)
                self.assertEqual(1, len(problems), problems)
                self.assertIn("doc.md:1: test_planted quoted as 5 tests, has 3", problems[0])

    def test_passes_a_correct_quote(self):
        self.assertEqual([], self.check("`tests/test_planted.py` (3 tests)"))

    def test_spares_a_dated_quote(self):
        self.assertEqual([], self.check("| Ported 2026-09-12 | `test_planted.py` (5 tests) |"))

    def test_fires_on_a_missing_module(self):
        problems = self.check("`test_gone.py` (2 tests)")
        self.assertEqual(1, len(problems))
        self.assertIn("no such test module", problems[0])


if __name__ == "__main__":
    unittest.main()
