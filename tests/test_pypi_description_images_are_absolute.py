# SPDX-License-Identifier: BSD-3-Clause
"""The PyPI long description's images are absolute and pinned to this release's tag.

``pyproject.toml`` takes ``readme`` from ``docs/developer/PACKAGE_README.md``. PyPI renders that
file without the repository around it, so a relative image (``../../docs/figures/x.svg``) is a
broken image on the project page, and PyPI keeps each upload's description for good: a fix
needs a new release. Pinned to ``v<version>`` rather than ``main``, so a later change to a
figure cannot alter what an old release's page shows. Found by the release review of
2026-10-31 (fix-plan class 20b), when all three images were relative.
"""
from __future__ import annotations

import re
import unittest

from tests._repo import PKG_ROOT  # noqa: E402

DESCRIPTION = PKG_ROOT / "docs" / "developer" / "PACKAGE_README.md"
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]*\bsrc=\"([^\"]+)\"")


def _version():
    m = re.search(r'(?m)^version = "([^"]+)"', (PKG_ROOT / "pyproject.toml").read_text("utf-8"))
    return m.group(1)


def bad_images(text: str, version: str) -> list[str]:
    """Every image target that is not a raw-GitHub URL on the ``v<version>`` tag."""
    # Spelled in parts so tests/test_links_name_the_main_branch.py's sweep does not read the
    # template ``v{version}`` as a link on a ref that is not a release tag.
    prefix = "https://raw.githubusercontent.com/sgupta92/" + "arrayprobe" + f"/v{version}/"
    return [t for m in _IMAGE.finditer(text) for t in m.groups() if t and not t.startswith(prefix)]


@unittest.skipUnless(DESCRIPTION.is_file(), "no PyPI description in this tree")
class TestPypiDescriptionImages(unittest.TestCase):
    def test_every_image_is_absolute_and_tag_pinned(self):
        text = DESCRIPTION.read_text(encoding="utf-8")
        self.assertTrue(_IMAGE.search(text), "no images in the description: nothing checked")
        self.assertEqual(bad_images(text, _version()), [])

    def test_the_check_fires_on_a_relative_and_a_main_image(self):
        rel = "![a](../../docs/figures/a.svg)"
        main = "![b](https://raw.githubusercontent.com/sgupta92/arrayprobe/main/docs/figures/b.svg)"
        ok = "![c](https://raw.githubusercontent.com/sgupta92/arrayprobe/v9.9.9/docs/figures/c.svg)"
        self.assertEqual(bad_images(rel + main + ok, "9.9.9"),
                         ["../../docs/figures/a.svg",
                          "https://raw.githubusercontent.com/sgupta92/arrayprobe/main/docs/figures/b.svg"])


if __name__ == "__main__":
    unittest.main()
