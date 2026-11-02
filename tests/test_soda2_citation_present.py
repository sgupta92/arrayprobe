# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2 carries its author's citation, verbatim (standing rule since 2026-10-06).

Aaron Bansemer provided the citation SODA-2 is to be given; every surface that
describes or credits the SODA-2 engine carries it exactly as he wrote it. This
checks the string byte for byte on the surfaces a user reads first, and fires on a
temporary copy from which it has been removed.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import REPO_ROOT, repo_only

CITATION = (
    "Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) "
    "[Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418"
)

SURFACES = (
    "README.md",
    "NOTICE.md",
    "docs/developer/HISTORY.md",
    "docs/08-reference.md",
    "docs/29-migrating-from-soda2.md",
)


def missing(root: Path) -> list[str]:
    """Return the surfaces under ``root`` that do not carry the citation verbatim."""
    out = [s for s in SURFACES if CITATION not in (root / s).read_text(encoding="utf-8")]
    cff = (root / "CITATION.cff").read_text(encoding="utf-8")
    refs = cff.split("\nreferences:", 1)[1] if "\nreferences:" in cff else ""
    if CITATION not in refs or "doi: 10.5281/zenodo.18331418" not in refs:
        out.append("CITATION.cff")
    return out


@hygiene
@repo_only
class SodaCitationPresent(unittest.TestCase):
    def test_every_surface_carries_the_citation_verbatim(self):
        self.assertEqual(missing(REPO_ROOT), [])

    def test_fires_when_the_readme_loses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in (*SURFACES, "CITATION.cff"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(REPO_ROOT / rel, root / rel)
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8").replace(CITATION, ""), encoding="utf-8"
            )
            self.assertEqual(missing(root), ["README.md"])


if __name__ == "__main__":
    unittest.main()
