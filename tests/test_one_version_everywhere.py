# SPDX-License-Identifier: BSD-3-Clause
"""One version everywhere (release checklist C12).

The main package's ``pyproject.toml`` is the source of record. Every shipped
package's ``__version__``, ``CITATION.cff`` and ``docs/developer/HISTORY.md``'s release summary
must agree with it. (The API page no longer prints a constant's value, so it states no version
to check.) The two enhancement
suites carry their own deliberate ``.dev0`` line and are checked against the
same ``major.minor.patch``.
"""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CFF_KEYS = ("cff-version", "message", "title", "authors")


def _pyproject_version(path: Path) -> str:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]


def _dunder_versions() -> dict[str, str]:
    out = {}
    for init in sorted((ROOT / "src").glob("*/__init__.py")):
        m = re.search(r'^__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"), re.M)
        if m:
            out[str(init.relative_to(ROOT)).replace("\\", "/")] = m.group(1)
    return out


def _cff_version(text: str) -> str:
    m = re.search(r"^version:\s*['\"]?([^\s'\"]+)", text, re.M)
    assert m, "CITATION.cff has no top-level version"
    return m.group(1)


def _changes_version(text: str) -> str:
    m = re.search(r"^### Release summary .*?\*\*(\d+\.\d+\.\d+[^\s*]*)", text, re.M)
    assert m, "docs/developer/HISTORY.md has no '### Release summary -- **X.Y.Z**' line"
    return m.group(1)


def disagreements(source: str, found: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in found.items() if v != source}


# reads CITATION.cff, docs/developer/HISTORY.md and docs_site, none of which the sdist ships
@repo_only
class OneVersionEverywhere(unittest.TestCase):
    def _found(self) -> tuple[str, dict[str, str]]:
        source = _pyproject_version(ROOT / "pyproject.toml")
        found = dict(_dunder_versions())
        found["CITATION.cff"] = _cff_version((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
        found["docs/developer/HISTORY.md"] = _changes_version(
            (ROOT / "docs/developer/HISTORY.md").read_text(encoding="utf-8"))
        return source, found

    def test_every_place_agrees_with_pyproject(self):
        source, found = self._found()
        self.assertGreaterEqual(len(found), 5, f"too few version sites found: {found}")
        self.assertEqual(disagreements(source, found), {})

    def test_citation_cff_is_the_only_citation_metadata(self):
        """Zenodo's GitHub integration reads CITATION.cff when no .zenodo.json exists, so a
        second metadata file would only be a copy that can drift from it."""
        self.assertFalse((ROOT / ".zenodo.json").exists(),
                         ".zenodo.json is back; carry its fields in CITATION.cff instead")

    def test_the_guard_fires_on_a_substituted_value(self):
        source, found = self._found()
        found["CITATION.cff"] = "9.9.9"
        self.assertEqual(disagreements(source, found), {"CITATION.cff": "9.9.9"})

    def test_enhancement_suites_sit_on_the_same_release_line(self):
        source = _pyproject_version(ROOT / "pyproject.toml")
        for sub in ("enhancements_uiops", "enhancements_soda2"):
            p = ROOT / sub / "pyproject.toml"
            if p.is_file():
                v = _pyproject_version(p)
                self.assertTrue(v == source or v.startswith(source + "."),
                                f"{sub} is {v}, main package is {source}")

    def test_citation_cff_has_the_required_keys(self):
        text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        for key in REQUIRED_CFF_KEYS:
            self.assertRegex(text, rf"(?m)^{re.escape(key)}:", key)
        self.assertRegex(text, r"(?m)^cff-version:\s*1\.2\.0\s*$")
        try:
            import yaml
        except ImportError:
            return
        data = yaml.safe_load(text)
        for key in REQUIRED_CFF_KEYS:
            self.assertIn(key, data)


if __name__ == "__main__":
    unittest.main()
