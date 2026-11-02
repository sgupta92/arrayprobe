# SPDX-License-Identifier: BSD-3-Clause
"""A code example in a published page must still be the example its source holds.

**The failure this prevents, which happened on 2026-09-02 and was published.** A
sweep updating a stale test count across the repository replaced the digits
``1010`` wherever they appeared. One of the places they appeared was a MATLAB
string literal inside a code example in the developers' notes::

    >> c = ['0101';'1010']; c(:,[2 6]) = '1'; size(c)

which became ``['0101';'1,033']`` -- a nonsense snippet, in the one document
written to be checkable by people who will run it in their own MATLAB, on the
page whose entire value is that its evidence can be verified without trusting
this port.

**Why prose checks did not catch it.** `test_publish_ready.py` compares *counts*:
it asks whether the number a document quotes equals the number the repository
has. Both sides agreed -- the sweep had done exactly what it was told. Nothing
was watching the code blocks, because a code block is not a claim about the
project, it is a quotation from somewhere else.

**The two sides.** The published HTML on one side; the Markdown the HTML was
written from on the other. Neither is generated from the other -- the artifact
pages are hand-authored beside the Markdown -- so agreement between them is
evidence.

**What it cannot do.** It checks lines carrying comma-grouped numbers, which is
the signature this specific class of damage leaves. A sweep that replaced a bare
digit string with another bare digit string would slip past. Narrow and real
beats broad and unwritten; widen it when a second instance shows up.
"""
from __future__ import annotations

import html
import re
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT, repo_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = PKG_ROOT / "docs" / "developer"
#: The published-artifact pages moved out of DOCS to project/pages/ 2026-09-09.
PAGES = ROOT / "project" / "pages"

FENCED = re.compile(r"```[a-z]*\n(.*?)```", re.S)
HTML_CODE = re.compile(r"<pre><code>(.*?)</code></pre>", re.S)
#: 1,234 -- a thousands separator, which a MATLAB or shell example never wants.
GROUPED = re.compile(r"\b\d{1,3},\d{3}\b")


def _source_code_lines() -> set[str]:
    """Every line inside a fenced code block in any Markdown doc under docs/."""
    out: set[str] = set()
    for md in DOCS.glob("*.md"):
        for block in FENCED.findall(md.read_text(encoding="utf-8")):
            out.update(ln.strip() for ln in block.splitlines() if ln.strip())
    return out


@repo_only
class PublishedCodeExamplesAreNotSweptOver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _source_code_lines()

    def test_no_artifact_code_block_invents_a_grouped_number(self):
        offenders = []
        for page in sorted(PAGES.glob("artifact_*.html")):
            text = page.read_text(encoding="utf-8")
            for m in HTML_CODE.finditer(text):
                for raw in html.unescape(m.group(1)).splitlines():
                    line = raw.strip()
                    if not line or not GROUPED.search(line):
                        continue
                    if line not in self.source:
                        offenders.append(f"{page.name}: {line[:80]}")
        self.assertEqual(
            offenders, [],
            "a code example on a published page carries a thousands-separated "
            "number that no Markdown source has -- almost certainly a numeric "
            "sweep that matched digits inside a code literal: "
            + "; ".join(offenders))

    def test_the_matlab_char_matrix_example_is_intact(self):
        """The specific example that was damaged, pinned by name.

        The general check above would catch a repeat, but this one names the
        snippet so a failure says what broke rather than only that something did.
        """
        page = PAGES / "artifact_upstream_feedback.html"
        if not page.is_file():
            self.skipTest("Developers' notes page is not distributed with the package")
        text = html.unescape(page.read_text(encoding="utf-8"))
        self.assertIn(
            "c = ['0101';'1010']", text,
            "C4's char-matrix example is not the one the upstream findings hold; "
            "it demonstrates that widening a char matrix pads with NUL, and the "
            "literals have to be the source's own for that to be checkable")


if __name__ == "__main__":
    unittest.main()
