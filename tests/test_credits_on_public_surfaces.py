# SPDX-License-Identifier: BSD-3-Clause
"""Credits and the SODA-2 citation on the surfaces a public user reads (pre-release check C13).

Three claims, each checked on the files themselves: the SODA-2 citation, exactly as its
author provided it and on one line, is on every shipped surface that describes or credits the
SODA-2 engine; the
credits (sole author, advisors and collaborators, data providers) are on the README, the
package README and CITATION.cff; and each of those asks users to cite UIOOPS alongside this
package. The citation check fires on a temporary copy from which it has been removed.

The surface set is derived, not listed. A shipped surface is a tracked ``.md`` or ``.ipynb``
that the release builder ships (its ``allowed`` and not ``never_ship``). It *describes or
credits the SODA-2 engine* when either (a) its title -- the first level-1 heading, for a
notebook in its joined markdown cells -- names SODA-2 (``SODA-2`` or ``SODA2``, any case), or
(b) one line names both ``Bansemer`` and ``SODA-2``/``SODA2``. ``CITATION_SURFACES`` stays as a
floor that must carry it whatever the definition finds. A notebook's text is its cells' joined
sources, so the citation must sit on one source line of one cell; whitespace is never
collapsed, because the rule says "exactly".
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import REPO_ROOT, repo_only

CITATION = (
    "Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) "
    "[Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418"
)

CITATION_SURFACES = (
    "README.md",
    "NOTICE.md",
    "docs/developer/HISTORY.md",
    "CONTRIBUTING.md",
    "docs/developer/PACKAGE_README.md",
    "docs/00-index.md",
    "docs/08-reference.md",
    "docs/27-choosing-an-engine.md",
    "docs/29-migrating-from-soda2.md",
    "docs/30-from-a-soda2-batch-script.md",
    "enhancements_soda2/README.md",
    "enhancements_soda2/NOTICE.md",
    "enhancements_uiops/NOTICE.md",
    "examples/README.md",
    # Named by pre-release check C13; they describe SODA-2 in body text, not by title.
    "docs/04-validation.md",
    "docs/developer/TWO_ENGINES.md",
    "enhancements_uiops/README.md",
    "examples/1_getting_started/03_choosing_an_engine.ipynb",
)

_TITLE = re.compile(r"^\s{0,3}#\s+(.*)$", re.M)
_SODA2 = re.compile(r"SODA-?2", re.I)


def surface_text(path: Path) -> str:
    """The file's text; for a notebook, its cells' sources joined (one cell per block)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".ipynb":
        cells = json.loads(text)["cells"]
        return "\n".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"] for c in cells
        )
    return text


def describes_soda2(text: str) -> bool:
    title = _TITLE.search(text)
    if title and _SODA2.search(title.group(1)):
        return True
    return any("Bansemer" in line and _SODA2.search(line) for line in text.splitlines())


def shipped_docs(root: Path) -> list[str]:
    """Tracked .md/.ipynb files the release builder ships."""
    spec = importlib.util.spec_from_file_location(
        "_credits_builder", root / "scripts" / "build_release_tree.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod      # before exec: the builder defines dataclasses
    spec.loader.exec_module(mod)
    rules = mod.parse_allowlist(
        (root / "scripts" / "release_allowlist.txt").read_text(encoding="utf-8"))
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.md", "*.ipynb"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.split("\0") if p
                  and mod.allowed(p, rules) is not None and mod.never_ship(p) is None)


def derived_surfaces(root: Path) -> list[str]:
    return [p for p in shipped_docs(root) if describes_soda2(surface_text(root / p))]

CREDIT_SURFACES = ("README.md", "docs/developer/PACKAGE_README.md", "CITATION.cff")
CREDITED = (
    "Gupta",
    "O'Brien",
    "Jackson",
    "McFarquhar",
    "Huang",
    "Bansemer",
    "Brechner",
    "Patil",
)


def missing(root: Path) -> list[str]:
    return [
        s for s in CITATION_SURFACES if CITATION not in surface_text(root / s)
    ]


@hygiene
@repo_only
class CreditsOnPublicSurfaces(unittest.TestCase):
    def test_every_soda2_surface_carries_the_citation_verbatim(self):
        for rel in CITATION_SURFACES:
            with self.subTest(surface=rel):
                text = surface_text(REPO_ROOT / rel)
                self.assertIn(CITATION, text, f"{rel} lacks the SODA-2 citation")

    @unittest.skipUnless((REPO_ROOT / "scripts" / "build_release_tree.py").is_file(),
                         "derives the surfaces from the release builder, which the release does"
                         " not ship; CITATION_SURFACES is checked there instead")
    def test_every_derived_soda2_surface_carries_the_citation_verbatim(self):
        found = derived_surfaces(REPO_ROOT)
        self.assertGreaterEqual(len(found), 10, "the definition found almost nothing")
        lacking = [p for p in found if CITATION not in surface_text(REPO_ROOT / p)]
        self.assertEqual(lacking, [], "shipped SODA-2 surfaces lacking the citation verbatim")

    def test_definition_catches_title_and_credit_and_ignores_the_rest(self):
        self.assertTrue(describes_soda2("# SODA-2 end to end\n\ntext"))
        self.assertTrue(describes_soda2("# Notes\n\nSODA-2 is by Aaron Bansemer (NCAR)."))
        self.assertFalse(describes_soda2("# Notes\n\n## SODA-2\n\nBansemer et al. 2019."))
        wrapped = CITATION.replace(" [Computer software]", "\n[Computer software]")
        self.assertNotIn(CITATION, wrapped)

    def test_citation_check_fires_when_a_surface_loses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in CITATION_SURFACES:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(REPO_ROOT / rel, root / rel)
            p = root / "examples/README.md"
            p.write_text(p.read_text(encoding="utf-8").replace(CITATION, ""), encoding="utf-8")
            self.assertEqual(missing(root), ["examples/README.md"])

    def test_credits_are_on_readme_package_readme_and_citation_cff(self):
        for rel in CREDIT_SURFACES:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for name in CREDITED:
                self.assertIn(name, text, f"{name} not credited in {rel}")

    def test_users_are_asked_to_cite_uiops_alongside(self):
        for rel in ("README.md", "docs/developer/PACKAGE_README.md", "docs/00-index.md"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8").lower()
            self.assertIn("cite uioops alongside", text, rel)


if __name__ == "__main__":
    unittest.main()
