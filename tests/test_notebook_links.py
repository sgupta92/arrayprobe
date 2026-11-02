# SPDX-License-Identifier: BSD-3-Clause
"""Every relative link in an example notebook's markdown resolves, anchor included.

**The defect this was written after.** The seven-track renumbering of
``examples/`` (``01_artifact_gallery`` became ``5_data_quality/12_particle_gallery``
and so on) left about two dozen markdown links in the notebooks pointing at names
that no longer existed, and several at paths relative to the wrong directory
(``start_here/`` from inside ``1_getting_started/``). ``test_markdown_links`` reads
``*.md`` files only, so nothing read a notebook's markdown cells; the author found
the dead links by clicking them (2026-10-15, "check for all dead links").

The check reads every markdown cell of every tracked ``examples/**/*.ipynb`` and the
example READMEs, resolves each relative ``[text](target)``, ``![alt](target)``,
``<a href>`` and ``<img src>`` against the notebook's own directory in the committed
tree (case-sensitively, as GitHub does), and, where the target is a ``.md`` file or a
notebook, checks a ``#fragment`` against that file's heading slugs.
"""
from __future__ import annotations

import json
import posixpath
import re
import unittest
from pathlib import Path
from urllib.parse import unquote

from tests._hygiene import hygiene
from tests._markdown_links import (
    _FENCE,
    MD_LINK,
    MD_RAW_HTML,
    MD_REF_DEF,
    ROOT,
    _is_relative,
    _strip_code,
    _tracked,
)
from tests._repo import repo_only

#: Markdown whose links and anchors are checked with the notebooks: the example READMEs
#: and the pages a reader reaches from them on GitHub.
EXAMPLE_MARKDOWN_GLOBS = (
    "examples/README.md", "examples/*/README.md",
    "README.md", "docs/*.md", "docs/developer/PACKAGE_README.md",
)

_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t#]*$", re.M)
_HTML_ANCHOR = re.compile(r"""<a\b[^>]*\b(?:id|name)\s*=\s*["']([^"']+)["']""", re.I)


def github_slug(heading: str) -> str:
    """GitHub's heading anchor: markup and punctuation dropped, lowercase, spaces to hyphens."""
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").replace("*", "")
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return text.replace(" ", "-")


def _markdown_of(path: Path, text: str | None = None) -> str:
    """The markdown a reader sees: a notebook's markdown cells, or the file itself."""
    if text is None:
        text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix != ".ipynb":
        return text
    nb = json.loads(text)
    return "\n\n".join("".join(c.get("source", "")) for c in nb.get("cells", [])
                       if c.get("cell_type") == "markdown")


def heading_slugs(markdown: str) -> set[str]:
    # Fenced blocks only: a code span inside a heading is part of its anchor.
    body = _FENCE.sub("", markdown)
    slugs: set[str] = set()
    counts: dict[str, int] = {}
    for m in _HEADING.finditer(body):
        s = github_slug(m.group(2))
        n = counts.get(s, 0)
        slugs.add(s if n == 0 else f"{s}-{n}")
        counts[s] = n + 1
    slugs.update(a.lower() for a in _HTML_ANCHOR.findall(body))
    return slugs


def broken_links(path: Path, text: str | None = None, root: Path = ROOT,
                 tree: frozenset[str] | None = None) -> list[str]:
    """Each relative link in ``path``'s markdown whose file or ``#anchor`` is not there.

    With ``tree`` a target resolves only if committed under exactly that case; without
    it, the disk. A fragment is checked when the target is ``.md`` or ``.ipynb``, and a
    bare ``#fragment`` against the file's own headings.
    """
    body = _strip_code(_markdown_of(path, text))
    targets = [m.group(1) for rx in (MD_LINK, MD_REF_DEF, MD_RAW_HTML)
               for m in rx.finditer(body)]
    here = path.parent.relative_to(root).as_posix()
    out = []
    for target in targets:
        if target.startswith("#"):
            frag = unquote(target[1:])
            if frag and frag.lower() not in heading_slugs(_markdown_of(path, text)):
                out.append(target + "  (no such heading)")
            continue
        if not _is_relative(target):
            continue
        rel, _, frag = target.split("?", 1)[0].partition("#")
        if not rel:
            continue
        res = posixpath.normpath(posixpath.join(here, unquote(rel))).rstrip("/")
        ok = res in tree if tree is not None else (root / res).exists()
        if not ok:
            out.append(target)
            continue
        if frag and res.endswith((".md", ".ipynb")) and (root / res).is_file():
            if unquote(frag).lower() not in heading_slugs(_markdown_of(root / res)):
                out.append(target + "  (no such heading)")
    return out


def _checked_files() -> list[Path]:
    files = sorted((ROOT / "examples").rglob("*.ipynb"))
    files = [p for p in files if ".ipynb_checkpoints" not in p.parts]
    for pattern in EXAMPLE_MARKDOWN_GLOBS:
        files += sorted(ROOT.glob(pattern))
    return files


@hygiene
@repo_only
class NotebookLinksResolve(unittest.TestCase):
    def test_the_walk_finds_the_notebooks(self):
        nbs = [p for p in _checked_files() if p.suffix == ".ipynb"]
        self.assertGreater(len(nbs), 30, "examples/**/*.ipynb not found -- the walk is wrong")

    def test_every_notebook_and_example_readme_link_resolves(self):
        tree = _tracked()
        tracked = [p for p in _checked_files()
                   if tree is None or p.relative_to(ROOT).as_posix() in tree]
        offenders = [f"{p.relative_to(ROOT).as_posix()} -> {t}"
                     for p in tracked for t in broken_links(p, tree=tree)]
        self.assertEqual(
            offenders, [],
            "dead links in example notebooks or READMEs (resolved against the file's own "
            "directory, in the committed tree; a #fragment against the target's "
            "headings):\n  " + "\n  ".join(offenders))


@hygiene
class TheNotebookLinkCheckFires(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "track").mkdir()
        (self.root / "guide.md").write_text("# Preserved bugs\n\n## Step one\n",
                                            encoding="utf-8")
        (self.root / "track" / "02_next.ipynb").write_text(
            json.dumps({"cells": [{"cell_type": "markdown", "source": ["# Next\n"]}]}),
            encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _nb(self, *markdown: str, code: str = "") -> Path:
        cells = [{"cell_type": "markdown", "source": [m]} for m in markdown]
        cells.append({"cell_type": "code", "source": [code], "outputs": []})
        p = self.root / "track" / "01_here.ipynb"
        p.write_text(json.dumps({"cells": cells}), encoding="utf-8")
        return p

    def test_a_dead_file_and_a_dead_anchor_in_a_notebook_are_reported(self):
        nb = self._nb(
            "## Local\n[ok](02_next.ipynb#next) [gone](01_artifact_gallery.ipynb) "
            "[up](../guide.md#preserved-bugs) [anchor](../guide.md#no-such) "
            '![img](figures/x.png) <img src="../guide.md"> [self](#local) [bad](#nowhere) '
            "[web](https://example.org/x)",
            code="# [not markdown](missing_in_code.md)")
        self.assertEqual(broken_links(nb, root=self.root), [
            "01_artifact_gallery.ipynb",
            "../guide.md#no-such  (no such heading)",
            "figures/x.png",
            "#nowhere  (no such heading)",
        ])

    def test_the_committed_tree_adjudicates(self):
        nb = self._nb("[case](02_Next.ipynb) [ok](02_next.ipynb)")
        tree = frozenset({"track", "track/01_here.ipynb", "track/02_next.ipynb"})
        self.assertEqual(broken_links(nb, root=self.root, tree=tree), ["02_Next.ipynb"])

    def test_github_slugs(self):
        self.assertEqual(github_slug("Preserved bugs"), "preserved-bugs")
        self.assertEqual(github_slug("3. The `.call` stamp (v3.5)"), "3-the-call-stamp-v35")


if __name__ == "__main__":
    unittest.main()
