# SPDX-License-Identifier: BSD-3-Clause
"""The PyPI long description's links are absolute and pinned to this release's tag.

The companion of ``test_pypi_description_images_are_absolute.py``: PyPI renders
``docs/developer/PACKAGE_README.md`` without the repository around it, so a relative link
(``../../docs/00-index.md``) leads nowhere from the project page, and an upload's description
cannot be changed afterwards. Each link is a GitHub ``blob`` URL on ``v<version>``, and the file
it names exists in this tree. Found by the fresh-eyes read of 2026-10-31, when 15 links were
relative.
"""
from __future__ import annotations

import re
import unittest

from tests._repo import PKG_ROOT, repo_only  # noqa: E402

DESCRIPTION = PKG_ROOT / "docs" / "developer" / "PACKAGE_README.md"
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def _version():
    m = re.search(r'(?m)^version = "([^"]+)"', (PKG_ROOT / "pyproject.toml").read_text("utf-8"))
    return m.group(1)


def _prefix(version: str) -> str:
    # Spelled in parts so tests/test_links_name_the_main_branch.py's sweep does not read the
    # template ``v{version}`` as a link on a ref that is not a release tag.
    return "https://github.com/sgupta92/" + "arrayprobe" + f"/blob/v{version}/"


def bad_links(text: str, version: str) -> list[str]:
    """Every in-repository link that is not a ``blob`` URL on ``v<version>``."""
    out = []
    for target in _LINK.findall(text):
        if target.startswith(_prefix(version)):
            continue
        if re.match(r"https?://", target) and "sgupta92/" + "arrayprobe/" not in target:
            continue  # an outside link (a DOI, another project)
        out.append(target)
    return out


@unittest.skipUnless(DESCRIPTION.is_file(), "no PyPI description in this tree")
class TestPypiDescriptionLinks(unittest.TestCase):
    def test_every_link_is_absolute_and_tag_pinned(self):
        text = DESCRIPTION.read_text(encoding="utf-8")
        self.assertTrue(_LINK.search(text), "no links in the description: nothing checked")
        self.assertEqual(bad_links(text, _version()), [])

    @repo_only  # examples/ and CONTRIBUTING.md are repository files the sdist does not carry
    def test_every_pinned_link_names_a_file_in_this_tree(self):
        prefix = _prefix(_version())
        text = DESCRIPTION.read_text(encoding="utf-8")
        missing = [t for t in _LINK.findall(text) if t.startswith(prefix)
                   and not (PKG_ROOT / t[len(prefix):].partition("#")[0]).exists()]
        self.assertEqual(missing, [])

    def test_a_relative_link_is_caught(self):
        self.assertEqual(bad_links("[x](../../docs/00-index.md)", "0.1.0"),
                         ["../../docs/00-index.md"])
        self.assertEqual(bad_links("[x](https://doi.org/10.5281/zenodo.1)", "0.1.0"), [])


if __name__ == "__main__":
    unittest.main()
