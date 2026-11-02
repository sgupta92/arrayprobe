# SPDX-License-Identifier: BSD-3-Clause
"""No shipped file names the AI models or agent arrangements used in development.

WHY. The release carries no development-process context. A survey of the built
public tree on 2026-10-13 found 37 lines naming models and agent counts, most of
them not in the source at all: the release build replaces each ledger id
with a plain gloss, and 54 glosses
described working-practice rules in those terms. This guard therefore scans each
shipped file *after* the same strip the release builder applies, so a gloss that
leaks fails here, not only text written directly.

WHAT COUNTS. A capitalised model name (the three model-family names below, or the
coding-assistant product name), and an agent count or arrangement ("twenty
parallel agents", "agents overnight"). Lowercase words are not matched: "opus"
is a musical work and "sonnet" a poem, and neither has appeared as a model name in
lowercase here. The words are assembled at run time so this file passes its own scan.

ALLOWED. README's "Generative AI" disclosure section, which names the tool on
purpose.
"""
from __future__ import annotations

import re
import sys
import unittest

from tests._hygiene import hygiene
from tests._repo import repo_only

try:
    from tests.test_no_personal_paths import ROOT, _shipped, _tracked_files
except ImportError:  # the release tree ships without that dev-only sweep
    raise unittest.SkipTest("tests/test_no_personal_paths.py is not in this tree") from None

_MODELS = "|".join(["Fa" + "ble", "Op" + "us", "Son" + "net", "Claude" + " Code"])
_COUNT = "ten|twenty|thirty|five|two|three|four|twelve"
PATTERN = re.compile(
    rf"\b({_MODELS})\b"
    rf"|\b(parallel|overnight|planning) agents\b"
    rf"|\bagents? overnight\b"
    rf"|\b({_COUNT}) ((?:{_MODELS}|parallel) )?agents\b"
    # Internal work labels: a work lane ("lane S2"), a numbered plan proposal and a
    # parenthesised work-slice label ("(Z21)", "(Z21, 2026-09-14)"); "[1-9]" spares IDL's
    # "(Z08)" format code. The comma form omits W, which may name a SODA-2 writer item.
    r"|\b[Ll]ane [A-Z]\d+\b"
    r"|\bplan proposal \**P\d"
    r"|\((?:W|Z|Y|GL)[1-9]\d?\)"
    r"|\((?:X|Y|Z)[1-9]\d?, "
    # A bare work-slice label stamped with its date ("W6, 2026-09-14", "Z21 2026-09-14")
    # or joined to a ledger id by a slash; a writer item or finding id carries neither.
    r"|\b(?:W|X|Y|Z|GL)[1-9]\d?,? \(?20\d\d-\d\d-\d\d"
    r"|\b(?:W|X|Y|Z|GL)[1-9]\d?/I-\d"
    # A numbered work stage ("W5 stage 10"); a writer item is never followed by "stage <n>".
    r"|\bW[1-9]\d? stage \d")

#: README's disclosure section: from its heading to the next level-2 heading.
_GENAI = re.compile(r"^## Generative AI$.*?(?=^## |\Z)", re.M | re.S)


def find_dev_process_names(text: str) -> list[str]:
    return [m.group(0) for m in PATTERN.finditer(text)]


def _strip_tools():
    tools = ROOT / "scripts"
    if not (tools / "strip_dev_ids.py").is_file():
        return None, None
    sys.path.insert(0, str(tools))
    try:
        import strip_dev_ids as strip
    finally:
        sys.path.remove(str(tools))
    return strip, strip.load_glossary()


@hygiene
class ThePatternFiresAndSparesProse(unittest.TestCase):
    CAUGHT = [
        "(" + "ten " + "Op" + "us agents on pressing tasks, lane " + "D2)",
        "(Z2, twenty parallel " + "agents overnight)",
        "agent-1 " + "Fa" + "ble plan",
        "the " + "Son" + "net follow-up section",
        "the one " + "Claude" + " Code runs hooks with",
        "five " + "agents",
        "(" + "lane" + " S2, I-" + "165)",
        "This is plan " + "proposal **P2**.",
        "measured null (" + "Z21): the demo",
        "2026-09-14 (" + "W4). Code:",
        "@slow  # real workers (" + "W6, 2026-09-14: ~9s)",
        "(589 s, " + "W6 2026-09-14)",
        "I-" + "176 " + "Y2 (2026-09-14): the six",
        "# " + "Y1/I-" + "176: the export",
        "``soda2`` (" + "W5 stage" + " 10) is its own engine",
        "golden (" + "W5 stage" + " 9b) caught it",
    ]
    PASSED = [
        "Beethoven's opus 131 and a sonnet by Shakespeare",
        "a fable about the diode table",
        "an oxidising agent; user agents; the agent-based model",
        "Claude Shannon's entropy",
        "two agencies, five agendas",
        "format='(Z08)'",
        "a traffic lane and the S2 stage",
        "proposal P2 of the plan",
        "writer item W4 of the SODA-2 port",
        "the W4 ASCII export, stage 2 of the run",
        "finding V" + "43 (2026-09-14) and Z-score 2026",
    ]

    def test_fires(self):
        for text in self.CAUGHT:
            with self.subTest(text=text):
                self.assertTrue(find_dev_process_names(text), text)

    def test_spares(self):
        for text in self.PASSED:
            with self.subTest(text=text):
                self.assertEqual([], find_dev_process_names(text), text)

    def test_readme_section_is_carved_out(self):
        text = "# x\n\n## Generative AI\n\nBuilt with " + "Claude" + " Code.\n\n## Next\n\nok\n"
        self.assertEqual([], find_dev_process_names(_GENAI.sub("", text)))
        self.assertTrue(find_dev_process_names(text))


@repo_only
@hygiene
class ShippedFilesNameNoDevProcess(unittest.TestCase):
    def test_glossary_names_no_model_or_agent_arrangement(self):
        strip, glossary = _strip_tools()
        if strip is None:
            self.skipTest("released tree: no strip tool")
        bad = {k: v for k, v in glossary.items() if find_dev_process_names(v)}
        self.assertEqual({}, bad, "a strip gloss would print a model or agent arrangement "
                         "into the public tree; reword it in scripts/strip_dev_ids_glossary.json")

    def test_no_shipped_file_names_dev_process_after_strip(self):
        files = _tracked_files()
        if files is None:
            self.skipTest("not a git checkout; this guard reads `git ls-files`")
        shipped = _shipped(files)
        self.assertGreater(len(shipped), 300, "the shipped set is empty or moved")
        strip, glossary = _strip_tools()
        me = "tests/test_no_dev_process_names_shipped.py"
        problems = []
        for rel in shipped:
            path = ROOT / rel
            if rel == me or not path.is_file():
                continue
            data = path.read_bytes()
            if b"\0" in data[:8192]:
                continue
            text = data.decode("utf-8", "replace")
            if strip is not None:
                text = strip.rewrite(text, strip.plan_text(rel, text, glossary))
            if rel == "README.md":
                text = _GENAI.sub("", text)
            for lineno, line in enumerate(text.splitlines(), 1):
                for hit in find_dev_process_names(line):
                    problems.append(f"{rel}:{lineno}: {hit!r}")
        self.assertEqual(
            [], problems,
            "a shipped file (after the release strip) names a development model or agent "
            "arrangement -- delete the process clause and keep the technical fact:\n  "
            + "\n  ".join(problems))


#: Shipped lines that cite a dated session report under the archive, which does not ship.
#: Measured 2026-10-14 after the release strip; a ratchet, so the count may only fall.
_ARCHIVED_REPORT_DIR = "archive/" + "session_" + "reports/"
SESSION_REPORT_CITATIONS_BASELINE = 80


@repo_only
@hygiene
class ShippedCitationsOfSessionReportsDoNotGrow(unittest.TestCase):
    def test_count_does_not_exceed_baseline(self):
        files = _tracked_files()
        if files is None:
            self.skipTest("not a git checkout; this guard reads `git ls-files`")
        strip, glossary = _strip_tools()
        hits = []
        for rel in _shipped(files):
            path = ROOT / rel
            if not path.is_file():
                continue
            data = path.read_bytes()
            if b"\0" in data[:8192]:
                continue
            text = data.decode("utf-8", "replace")
            if strip is not None:
                text = strip.rewrite(text, strip.plan_text(rel, text, glossary))
            hits += [f"{rel}:{n}" for n, line in enumerate(text.splitlines(), 1)
                     if _ARCHIVED_REPORT_DIR in line]
        self.assertLessEqual(
            len(hits), SESSION_REPORT_CITATIONS_BASELINE,
            "a shipped line cites a dated session report, which does not ship; name what it "
            "established in plain words instead:\n  " + "\n  ".join(hits))

    def test_the_ratchet_fires_on_a_planted_citation(self):
        self.assertIn(_ARCHIVED_REPORT_DIR, "see `" + _ARCHIVED_REPORT_DIR + "2026-09-17_cip/X.md`")
        self.assertNotIn(_ARCHIVED_REPORT_DIR, "see archive/" + "design_records/S2.md")


if __name__ == "__main__":
    unittest.main()
