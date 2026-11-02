# SPDX-License-Identifier: BSD-3-Clause
"""The default-on corrections are listed once, in docs/27-choosing-an-engine.md.

Pages that once restated the list ("five upstream defects", "the two default-on
keys") disagreed with the code and with each other; each now links to the one
block. This test keeps it that way.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "27-choosing-an-engine.md"
BEGIN = "<!-- default-on:begin -->"
END = "<!-- default-on:end -->"
DRIVER_KEYS = ("stray_pixel_fix", "ncar_2dc_timing_fix", "bin_table_fix")

_NUM = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
RESTATEMENT = re.compile(
    rf"\b{_NUM}\s+(?:upstream\s+defects|default-on\s+(?:keys|corrections))\b",
    re.IGNORECASE,
)


def restatements(text):
    """Return each phrase in ``text`` that counts the default-on corrections."""
    return [m.group(0) for m in RESTATEMENT.finditer(text)]


def _block():
    text = PAGE.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        return None
    return text.split(BEGIN, 1)[1].split(END, 1)[0]


class TestBlockNamesEveryCorrection(unittest.TestCase):
    def test_block_exists_once(self):
        self.assertIsNotNone(_block(), f"{PAGE.name} must carry exactly one default-on block")

    def test_driver_keys_named(self):
        block = _block() or ""
        for key in DRIVER_KEYS:
            self.assertIn(f"`{key}`", block)

    def test_uiops_registry_keys_named(self):
        try:
            from arrayprobe_enhancements.registry import PROTECTIVE
        except ImportError:
            self.skipTest("arrayprobe_enhancements not importable")
        block = _block() or ""
        for key in PROTECTIVE:
            self.assertIn(f"`{key}`", block)

    def test_soda2_registry_keys_named(self):
        try:
            from arrayprobe_soda2_enhancements.registry import PROTECTIVE
        except ImportError:
            self.skipTest("arrayprobe_soda2_enhancements not importable")
        block = _block() or ""
        for key in PROTECTIVE:
            self.assertIn(f"`{key}`", block)


class TestNoPageRestatesTheList(unittest.TestCase):
    def test_no_count_phrase_outside_the_block(self):
        pages = sorted((ROOT / "docs").glob("*.md")) + [ROOT / "README.md"]
        found = {}
        for page in pages:
            hits = restatements(page.read_text(encoding="utf-8"))
            if hits:
                found[page.name] = hits
        self.assertEqual(
            found, {}, "link to the default-on block in 27-choosing-an-engine.md instead"
        )

    def test_checker_fires(self):
        text = "A batch run on engine 3.5 corrects five upstream\ndefects that destroy data."
        self.assertEqual(len(restatements(text)), 1)
        self.assertEqual(len(restatements("The two default-on keys")), 1)
        self.assertEqual(restatements("a stray pixel is removed"), [])


if __name__ == "__main__":
    unittest.main()
