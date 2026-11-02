# SPDX-License-Identifier: BSD-3-Clause
"""Every enhanced output file the pipeline writes is explained to the user.

The enhancements pipeline writes ``<stem>.enh.<kind>.nc`` files (``proc``, ``sd``, ``arco``,
``arm``, ``cf``) beside the port's own files. A user who finds them needs to know what
each adds over the port's file and what it is for. This test reads the suffixes from the
pipeline source (one side) and requires each to be explained in the "Which enhanced file to
read" section of ``enhancements/docs/CORRECTIONS.md`` (the other side).
"""
import re
import unittest
from pathlib import Path

from tests._repo import repo_only

_REPO = Path(__file__).resolve().parents[1]
_PIPELINE = _REPO / "enhancements_uiops" / "src" / "arrayprobe_enhancements" / "pipeline.py"
_DOC = _REPO / "enhancements_uiops" / "docs" / "CORRECTIONS.md"
_HEADING = "## Which enhanced file to read"


def _suffixes_in_pipeline():
    text = _PIPELINE.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\.enh\.([a-z]+)\.nc", text)))


def _section():
    text = _DOC.read_text(encoding="utf-8")
    start = text.find(_HEADING)
    if start < 0:
        return ""
    end = text.find("\n---", start)
    return text[start:end if end > 0 else len(text)]


# Reads the enhancements package's source and docs, which an unpacked sdist does not have.
@repo_only
class TestEnhancedOutputsDocumented(unittest.TestCase):
    def test_pipeline_writes_the_three_known_outputs(self):
        # Pinned so a new output is noticed here, and so the regex cannot silently match nothing.
        self.assertEqual(_suffixes_in_pipeline(), ["arco", "arm", "cf", "proc", "sd"])

    def test_every_enhanced_output_is_explained(self):
        section = _section()
        self.assertTrue(section, f"{_DOC.name} has no '{_HEADING}' section")
        for suffix in _suffixes_in_pipeline():
            with self.subTest(suffix=suffix):
                self.assertIn(f"enh.{suffix}.nc", section)

    def test_each_entry_says_what_it_adds_and_what_it_is_for(self):
        section = _section()
        for suffix in _suffixes_in_pipeline():
            rows = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("|")]
            row = next((r for r in rows
                        if r.strip("|").split("|")[0].strip() == f"`<stem>.enh.{suffix}.nc`"), "")
            with self.subTest(suffix=suffix):
                self.assertTrue(row, f"no table row whose File cell is <stem>.enh.{suffix}.nc")
                cells = [c.strip() for c in row.strip("|").split("|")]
                self.assertGreaterEqual(len(cells), 3, row)
                self.assertTrue(all(cells[:3]), row)


if __name__ == "__main__":
    unittest.main()
