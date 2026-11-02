# SPDX-License-Identifier: BSD-3-Clause
"""Every public page that writes the Windows venv path also gives the Linux/macOS one.

WHY. The R1 independent review (2026-09-14) read the install page as a
Linux/macOS user and found commands written only as ``.venv/Scripts/python.exe``
-- the Windows layout -- with no ``.venv/bin/python`` beside them. R2 (
2026-09-15) gave both forms on ``01-installation.md`` and a one-line note on
every other public page that uses the Windows form. This test is what keeps a
new page from shipping the Windows form alone.

SCOPE. The outward surfaces a user installs and runs from: ``README.md``, every
``docs/*.md``, ``examples/README.md`` and the two enhancement
packages' READMEs. ``docs/developer/`` (developer design records) is not in
scope. The installation page is held to more: each of its install and suite
commands carries the other form in the same code block.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "docs" / "01-installation.md"

WINDOWS = re.compile(r"\.venv[/\\]Scripts[/\\]python(?:\.exe)?")
POSIX = re.compile(r"\.venv/bin/python")


def public_pages() -> list[Path]:
    pages = [ROOT / "README.md", ROOT / "examples" / "README.md",
             ROOT / "enhancements_uiops" / "README.md", ROOT / "enhancements_soda2" / "README.md"]
    pages += sorted((ROOT / "docs").glob("*.md"))
    return [p for p in pages if p.is_file()]


def missing_posix_form(text: str) -> bool:
    """True when ``text`` writes the Windows venv path and never the POSIX one."""
    return bool(WINDOWS.search(text)) and not POSIX.search(text)


def _code_blocks(text: str) -> list[str]:
    return re.findall(r"```[a-z]*\n(.*?)```", text, re.S)


@repo_only
@hygiene
class PublicPagesGiveBothVenvForms(unittest.TestCase):
    def test_the_page_list_is_not_empty(self):
        pages = public_pages()
        self.assertGreater(len(pages), 10)
        self.assertIn(INSTALL, pages)

    def test_every_page_with_the_windows_form_gives_the_posix_one(self):
        offenders = [p.relative_to(ROOT).as_posix() for p in public_pages()
                     if missing_posix_form(p.read_text(encoding="utf-8"))]
        self.assertEqual(
            [], offenders,
            "these pages write `.venv/Scripts/python.exe` and never `.venv/bin/python`; "
            "add the Linux/macOS form (a one-line comment in the first code block will do)")

    def test_every_install_page_block_with_the_windows_form_gives_both(self):
        blocks = [b for b in _code_blocks(INSTALL.read_text(encoding="utf-8"))
                  if WINDOWS.search(b)]
        self.assertGreaterEqual(len(blocks), 1, "the call-by-path block is expected")
        for block in blocks:
            with self.subTest(block=block.splitlines()[0]):
                self.assertTrue(POSIX.search(block), block)

    def test_the_install_page_shows_python_dash_m_arrayprobe(self):
        # The first command a Python user tries (R1 row 2); it works since
        # __main__.py exists (tests/test_python_dash_m.py).
        self.assertIn("-m arrayprobe --help", INSTALL.read_text(encoding="utf-8"))

    def test_the_check_fires_when_the_posix_form_is_removed(self):
        """Mutation: strip every POSIX mention from a real page and it must fail."""
        text = INSTALL.read_text(encoding="utf-8")
        self.assertFalse(missing_posix_form(text), "precondition: the page passes")
        stripped = POSIX.sub(".venv/Scripts/python.exe", text)
        self.assertTrue(missing_posix_form(stripped))
        self.assertFalse(missing_posix_form("no venv path here at all"))


if __name__ == "__main__":
    unittest.main()
