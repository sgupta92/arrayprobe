# SPDX-License-Identifier: BSD-3-Clause
"""``docs/_build/build.py --refresh-docs`` refreshes the committed built pages and nothing else.

``docs/`` holds both the page sources (``*.md``) and the built pages committed beside them
(``*.html``, ``search-index.js``). ``build()`` refuses to write into the sources directory,
so the command ``test_docs_site``'s staleness check names must be one that works: this pins
that it updates a stale page, adds a missing one, removes an orphan, and leaves every
``.md`` source and every subdirectory byte-identical.

A release tree ships the sources and the builder but holds the built pages back
(``scripts/release_allowlist.txt``, ``!docs/**/*.html``). Where ``docs/`` holds no built page,
the copy is seeded with a fresh build's outputs, so the same steps have pages to act on;
where the allow-list is present (the development tree) the committed pages must exist."""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

from tests._repo import REPO_PRESENT, repo_only

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
BUILD = DOCS / "_build" / "build.py"
#: Present in the development repository, absent from a release tree (it does not ship).
ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"


def _load_build():
    # docs/_build/ is repository tooling, not in the sdist
    if not REPO_PRESENT:
        return None
    spec = importlib.util.spec_from_file_location("docs_build_refresh", BUILD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


build = _load_build()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def seed_built_pages(target: Path, fresh: dict[str, bytes], *, docs: Path | None = None,
                     allowlist: Path | None = None) -> bool:
    """Write ``fresh``'s built outputs into ``target`` where ``docs`` holds no built page.

    Returns whether it seeded. A development tree (``allowlist`` present) without its built
    pages fails, because it commits them; a release tree holds them back, and is seeded."""
    docs = DOCS if docs is None else docs
    allowlist = ALLOWLIST if allowlist is None else allowlist
    if any(docs.glob("*.html")):
        return False
    if allowlist.is_file():
        raise AssertionError(f"{docs} holds no built page, but {allowlist} is present: "
                             "the development tree commits its built pages")
    for name, data in fresh.items():
        (target / name).write_bytes(data)
    return True


@repo_only
class RefreshDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        fresh = Path(cls._tmp.name) / "fresh"
        build.build(fresh)
        cls.fresh = {n: (fresh / n).read_bytes() for n in build._built_outputs(fresh)}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _copy_of_docs(self) -> Path:
        # Top-level files of docs/ (sources and built pages) plus a stand-in subdirectory;
        # the real subdirectories are large and refresh_docs must not read them anyway.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name) / "docs"
        target.mkdir()
        for p in DOCS.iterdir():
            if p.is_file():
                shutil.copyfile(p, target / p.name)
        seed_built_pages(target, self.fresh)
        (target / "developer").mkdir()
        (target / "developer" / "notes.html").write_bytes(b"hand-written, not ours\n")
        return target

    def test_a_stale_page_is_refreshed_and_sources_are_untouched(self):
        target = self._copy_of_docs()
        stale, missing = "index.html", "installation.html"
        self.assertIn(stale, self.fresh)
        self.assertIn(missing, self.fresh)
        (target / stale).write_bytes(b"<html>stale</html>\n")
        (target / missing).unlink()
        (target / "orphan-page.html").write_bytes(b"<html>no source</html>\n")
        (target / "search-index.js").write_bytes(b"window.__SEARCH__ = [];\n")
        # Everything except the top-level built outputs: sources, other files, subdirectories.
        before = {n: b for n, b in _snapshot(target).items()
                  if "/" in n or not (n.endswith(".html") or n == "search-index.js")}
        self.assertTrue(any(n.endswith(".md") for n in before), "no .md sources copied")

        changed = build.refresh_docs(target)

        self.assertIn(f"updated {stale}", changed)
        self.assertIn(f"added {missing}", changed)
        self.assertIn("removed orphan-page.html", changed)
        self.assertIn("updated search-index.js", changed)
        built = {n: (target / n).read_bytes() for n in build._built_outputs(target)}
        self.assertEqual(sorted(built), sorted(self.fresh))
        self.assertEqual([n for n in built if built[n] != self.fresh[n]], [],
                         "the comparison is not clean after --refresh-docs")
        after = _snapshot(target)
        self.assertEqual({n: after.get(n) for n in before}, before,
                         "a .md source or a subdirectory file changed")
        # A second run finds nothing to do.
        self.assertEqual(build.refresh_docs(target), [])

    def test_a_development_tree_without_its_built_pages_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs, target = Path(tmp) / "docs", Path(tmp) / "target"
            docs.mkdir()
            target.mkdir()
            allowlist = Path(tmp) / "release_allowlist.txt"
            allowlist.write_text("docs/**\n", encoding="utf-8")
            with self.assertRaises(AssertionError):
                seed_built_pages(target, self.fresh, docs=docs, allowlist=allowlist)
            self.assertEqual(list(target.iterdir()), [], "a development tree was seeded")

    def test_a_release_tree_is_seeded_with_every_built_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs, target = Path(tmp) / "docs", Path(tmp) / "target"
            docs.mkdir()
            target.mkdir()
            self.assertTrue(seed_built_pages(target, self.fresh, docs=docs,
                                             allowlist=Path(tmp) / "absent.txt"))
            self.assertEqual(sorted(build._built_outputs(target)), sorted(self.fresh))

    def test_the_cli_flag_reaches_the_real_docs_directory_only(self):
        with unittest.mock.patch.object(build, "refresh_docs", return_value=[]) as fake, \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build.main(["--refresh-docs"]), 0)
        fake.assert_called_once_with()
        self.assertIn("already current", out.getvalue())

    def test_building_into_the_sources_directory_is_still_refused(self):
        for out in (DOCS, DOCS / "sub"):
            with self.assertRaises(SystemExit) as caught:
                build.build(out)
            self.assertIn("--refresh-docs", str(caught.exception))
        self.assertFalse((DOCS / "sub").exists())


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
