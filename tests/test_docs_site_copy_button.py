# SPDX-License-Identifier: BSD-3-Clause
"""Every code block on the documentation site has a "Copy" button.

``docs/_build/build.py`` inlines one ``<script id="copy-button">`` on each page that has a
``<pre>``; the script wraps every block and adds a real ``<button>``. This test reads the
committed ``docs/*.html`` pages, so a page built without the script (or with it twice)
fails, and it builds the site with the script removed or doubled to show the check fires.

A release tree ships the page sources and the builder but holds the built pages back
(``scripts/release_allowlist.txt``, ``!docs/**/*.html``). Where ``docs/`` holds no built page,
the same check runs on the site built into a temporary directory by the shipped builder;
where the allow-list is present (the development tree) the committed pages must exist.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "docs" / "_build" / "build.py"
DOCS = ROOT / "docs"
#: Present in the development repository, absent from a release tree (it does not ship).
ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"
build = None  # loaded by the gated class below



def _load_build():
    """Load ``docs/_build/build.py``, a repository-only file, as a module."""
    spec = importlib.util.spec_from_file_location("docs_build_copybtn", BUILD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def copy_button_problems(site: Path, marker: str) -> list[str]:
    """Pages with a <pre> that do not carry the copy-button script exactly once."""
    bad = []
    for page in sorted(site.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        if "<pre>" not in text:
            continue
        n = text.count(marker)
        if n != 1:
            bad.append(f"{page.name}: copy-button script appears {n} times")
    return bad


def site_to_check(docs: Path, out: Path, *, allowlist: Path | None = None) -> Path:
    """The built pages to read: the committed ``docs/*.html`` where they exist.

    Where ``docs`` holds no built page, a development tree (``allowlist`` present) fails,
    because it must commit them; a release tree, which holds them back, gets the site
    built into ``out`` by the shipped builder, and that is what is checked."""
    allowlist = ALLOWLIST if allowlist is None else allowlist
    if any(docs.glob("*.html")):
        return docs
    if allowlist.is_file():
        raise AssertionError(f"{docs} holds no built page, but {allowlist} is present: "
                             "the development tree commits its built pages")
    build.build(out)
    return out


@repo_only
class CopyButtonOnEveryCodeBlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global build
        build = _load_build()

    def test_every_built_page_with_code_carries_the_script_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = site_to_check(DOCS, Path(tmp) / "site")
            pages = [p for p in site.glob("*.html") if "<pre>" in p.read_text(encoding="utf-8")]
            self.assertTrue(pages, "no built page has a code block; the check would test nothing")
            self.assertEqual(copy_button_problems(site, build.COPY_MARKER), [])

    def test_a_development_tree_without_its_built_pages_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs, allowlist = Path(tmp) / "docs", Path(tmp) / "release_allowlist.txt"
            docs.mkdir()
            (docs / "00-index.md").write_text("# Index\n", encoding="utf-8")
            allowlist.write_text("docs/**\n", encoding="utf-8")
            with self.assertRaises(AssertionError):
                site_to_check(docs, Path(tmp) / "site", allowlist=allowlist)
            self.assertFalse((Path(tmp) / "site").exists(), "a development tree built a site")

    def test_a_release_tree_checks_the_site_it_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs, absent = Path(tmp) / "docs", Path(tmp) / "absent.txt"
            docs.mkdir()
            site = site_to_check(docs, Path(tmp) / "site", allowlist=absent)
            self.assertEqual(site, Path(tmp) / "site")
            self.assertTrue(any("<pre>" in p.read_text(encoding="utf-8")
                                for p in site.glob("*.html")))
            self.assertEqual(copy_button_problems(site, build.COPY_MARKER), [])
            # The same check fails on a release-view build made without the script.
            with unittest.mock.patch.object(build, "COPY_SCRIPT", ""):
                bare = site_to_check(docs, Path(tmp) / "bare", allowlist=absent)
            self.assertTrue(copy_button_problems(bare, build.COPY_MARKER))

    def test_the_script_is_accessible_and_has_a_fallback(self):
        js = build.COPY_JS
        for needle in ("navigator.clipboard.writeText", "execCommand('copy')",
                       "createElement('button')", "aria-label", "'Copied'", "1500"):
            self.assertIn(needle, js)
        self.assertNotIn("<script src=", build.COPY_SCRIPT)
        self.assertIn(".copybtn{", build.CSS)
        self.assertIn("var(--surface)", build.CSS.split(".copybtn{", 1)[1].split("}", 1)[0])

    def test_the_guard_fires_on_a_page_built_without_the_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            with unittest.mock.patch.object(build, "COPY_SCRIPT", ""):
                build.build(site)
            self.assertTrue(copy_button_problems(site, build.COPY_MARKER))

    def test_the_guard_fires_on_a_page_carrying_the_script_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            with unittest.mock.patch.object(build, "COPY_SCRIPT", build.COPY_SCRIPT * 2):
                build.build(site)
            self.assertTrue(copy_button_problems(site, build.COPY_MARKER))


if __name__ == "__main__":
    unittest.main()
