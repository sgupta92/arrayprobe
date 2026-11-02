# SPDX-License-Identifier: BSD-3-Clause
"""No new internal work label reaches a shipped file.

WHY. A sweep of the built public tree on 2026-10-25 found porting-stage, decision,
plan, gap, ledger and work-slice labels that the release strip does not catch.
They name how the work was organised, not what the code does. The hits present
today are a ratchet: each family's count may only fall, and a new one fails here.

WHAT COUNTS. Eight families (``FAMILIES``), matched after the same strip the
release builder applies. Upstream finding ids are not in this guard. Public tokens
that share a shape (SODA-2 register keys, ARM standard sections, appendix figure
numbers, a frozen fixture title, a few frozen data keys and lint rule codes) are
blanked first (``_ALLOW``). Every literal is assembled at run time so this file passes its own
scan and adds nothing to the dev-id ratchet.
"""
from __future__ import annotations

import re
import unittest

from tests._hygiene import hygiene
from tests._repo import repo_only

try:
    from tests.test_no_personal_paths import ROOT, _shipped, _tracked_files
except ImportError:  # the release tree ships without that dev-only sweep
    raise unittest.SkipTest("tests/test_no_personal_paths.py is not in this tree") from None

from tests.test_no_dev_process_names_shipped import _strip_tools

_D = "[0-9]"
FAMILIES: dict[str, re.Pattern[str]] = {
    "v35_stage": re.compile(
        r"\b(?:stage|doctrine|oracle) " + "V" + _D + r"+[a-z]?\b"
        r"|\b" + "V" + _D + r"[ab]\b|\b" + "V" + _D + r"+[a-z]'s\b"),
    "decision": re.compile(
        r"\b(?:decision|discriminator|seam) [A-Z]" + _D + r"+\b"
        r"|\(opt-in, [A-Z]" + _D + r"+\)|" + "settled by " + "the author"),
    "plan": re.compile(
        r"\b" + "R" + _D + r"+-" + _D + r"+\b|\b" + "S" + _D + r"+ D-row\b"
        r"|\b" + "P" + "3" + r"(?:-registry)?\b"
        # O1 and D2 only in the label contexts measured on 0da084a, so a public token
        # of the same shape (a size bin, a figure panel) is never counted; "discriminator D2"
        # is the decision family's, so it is not counted twice.
        r"|\(" + "O" + "1" + r"[,)]"
        r"|\b(?:[Dd]esign|lane) " + "D" + "2" + r"\b|\b" + "D" + "2" + r" report\b"
        r'|"""' + "D" + "2" + r":|, " + "D" + "2" + r'"'
        r"|" + "04_" + "EVALUATE"),
    "porting_stage": re.compile(r"\b" + "S" + r"(?:1[abc]|[5-9]|1" + _D + r")\b"),
    "gap": re.compile(r"\b" + "G" + _D + r"\b"),
    "ledger_hyphenless": re.compile(r"\b" + "I" + _D + r"{2,4}\b"),
    "work_label": re.compile(
        r"\b" + "sl" + r"ice [A-Z]" + _D + r"+\b|\b" + "W" + _D + " " + "S" + _D + r"+\b"
        r"|\bby " + "Cla" + r"ude\b"),
    # Bare S1-S4, the SODA-2 port's stages. The same names are public UIOPS pipeline
    # stages, so this family counts only in SODA-2 files (``_SCOPE``).
    "soda2_stage": re.compile(r"\b" + "S" + r"[1-4]\b(?!-[a-z]|\.\d|c)"),
}

#: Families counted only in the files their pattern matches; every other family counts
#: everywhere.
_SCOPE: dict[str, re.Pattern[str]] = {
    "soda2_stage": re.compile(
        r"^(?:src/arrayprobe_soda2/|enhancements_soda2/|scripts/validation/gdl/"
        r"|tests/test_(?:soda2_|cli_soda2|gdl_soda2_))"),
}
#: 11, the UIOPS S2 reader's fixture named from a SODA-2 file (``s2_spec_raw_fixture``,
#: "the S2 fixture", the BACKLOG row beside it), and any line that names UIOPS, where
#: S1-S4 are the public UIOPS stages.
_ALLOW_S2_FIXTURE = re.compile(
    r"\b" + "S" + r"2(?= fixture| and frame fixture| \+ frame fixture)"
    r"|^\| " + "S" + r"2 \| (?:un)?equal \(")
_S2_FIXTURE_LINE = re.compile(r"s2_spec|UIO+PS")

#: S1's allowlist, items 1-8. A span that matches is blanked before the families run.
_ALLOW_ANY = re.compile(
    r"\bS\d{1,2}-[a-z]\b"                                   # 1 SODA-2 register key
    r"|\bS\d+(?:\.\d+)+\b"                                  # 2 ARM standard section
    r"|\b(?:Fig\.|Figure)\s+[A-Z]\d+\b"                     # 3 appendix figure
    r"|facility_id\s*=\s*\"[A-Z]\d+\""                      # 5 ARM facility code
    r"|format='\([^']*\bF\d+\.\d+"                          # 6 IDL format code
    r"|" + "S6 " + "synthetic PTH")                         # 8 frozen fixture title
_ALLOW_PROBEID = re.compile(r"""(['"])A0\1""")              # 4, in files naming probeid
_ALLOW_FACILITY_LINE = re.compile(r"`F\d`")                 # 5, on a line naming Facility
_ALLOW_GDL = re.compile(r'"family":\s*"[ABF]\d+"|Case\("[^"]+",\s*"[ABF]\d+"')  # 7
_ALLOW_GDL_GOLDEN = re.compile(r'"[A-Z]\d+"')             # 7, golden keys and values
_GDL_GOLDEN = re.compile(r"(?:^|/)gdl_soda2_[^/]*golden\.json$")
#: 9, notebooks: the base64 ``image/png`` output, or any base64 run of 200+ characters.
_ALLOW_NB_IMAGE = re.compile(r'"image/png":\s*"[^"]*"|[A-Za-z0-9+/]{200,}=*')
#: 10, lint rule codes: the code list after ``noqa:``, and a ruff/flake8 code named in
#: prose on a line that also names ruff, noqa, lint or isort. A bare code elsewhere still
#: counts, so the ledger family keeps firing on a hyphenless id in ordinary prose.
_ALLOW_NOQA = re.compile(r"(?i)(?<=noqa:)[ \t]*[A-Z]+\d+(?:[ \t]*,[ \t]*[A-Z]+\d+)*")
_LINT_CONTEXT = re.compile(r"(?i)\b(?:ruff|noqa|lint|isort)")
_ALLOW_LINT_CODE = re.compile(r"\b[A-Z]{1,3}\d{3,4}\b")
_GDL_FILES = re.compile(r"(?:^|/)gdl_soda2_[^/]*golden\.json$"
                        r"|^scripts/validation/gdl/run_soda2_[^/]*_bank\.py$")


def _blank(m: re.Match[str]) -> str:
    return " " * len(m.group(0))


def allowed_text(text: str, rel: str = "") -> str:
    """``text`` with every allowlisted span replaced by spaces (offsets kept)."""
    if rel.endswith(".ipynb"):
        text = _ALLOW_NB_IMAGE.sub(_blank, text)
    text = _ALLOW_ANY.sub(_blank, text)
    if "probeid" in text:
        text = _ALLOW_PROBEID.sub(_blank, text)
    if _GDL_FILES.search(rel):
        text = _ALLOW_GDL.sub(_blank, text)
    if _GDL_GOLDEN.search(rel):
        text = _ALLOW_GDL_GOLDEN.sub(_blank, text)
    return "\n".join(_allowed_line(ln) for ln in text.split("\n"))


def _allowed_line(ln: str) -> str:
    if "Facility" in ln:
        ln = _ALLOW_FACILITY_LINE.sub(_blank, ln)
    ln = _ALLOW_NOQA.sub(_blank, ln)
    if _LINT_CONTEXT.search(ln):
        ln = _ALLOW_LINT_CODE.sub(_blank, ln)
    return ln


def find_work_labels(text: str, rel: str = "") -> dict[str, list[str]]:
    text = allowed_text(text, rel)
    found = {name: [m.group(0) for m in pat.finditer(text)] for name, pat in FAMILIES.items()}
    for name, scope in _SCOPE.items():
        if not scope.search(rel):
            found[name] = []
    found["soda2_stage"] = [h for ln in text.split("\n") if not _S2_FIXTURE_LINE.search(ln)
                            for h in FAMILIES["soda2_stage"].findall(
                                _ALLOW_S2_FIXTURE.sub(_blank, ln))] if found["soda2_stage"] else []
    return found


#: Hits per family in the shipped files after the release strip, measured on 0da084a
#: (2026-10-26). A ratchet: a count may only fall, and a count that fell takes its
#: baseline down in the same commit (``falls``), or the slack lets new labels back in.
BASELINE = {
    "v35_stage": 0,
    "decision": 0,
    "plan": 0,
    "porting_stage": 1,
    "gap": 0,
    "ledger_hyphenless": 0,
    "work_label": 0,
    "soda2_stage": 4,
}


def rises(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    return [f"{name}: {n} > baseline {baseline[name]}"
            for name, n in sorted(counts.items()) if n > baseline[name]]


def falls(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    return [f"{name}: {n} < baseline {baseline[name]}; set BASELINE[{name!r}] = {n}"
            for name, n in sorted(counts.items()) if n < baseline[name]]


def shipped_hits() -> dict[str, list[str]] | None:
    files = _tracked_files()
    if files is None:
        return None
    strip, glossary = _strip_tools()
    me = "tests/test_no_work_labels_shipped.py"
    hits: dict[str, list[str]] = {name: [] for name in FAMILIES}
    for rel in _shipped(files):
        path = ROOT / rel
        if rel == me or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "replace")
        if strip is not None:
            text = strip.rewrite(text, strip.plan_text(rel, text, glossary))
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, found in find_work_labels(line, rel).items():
                hits[name] += [f"{rel}:{lineno}: {h!r}" for h in found]
    return hits


@hygiene
class TheFamiliesFireAndSparePublicTokens(unittest.TestCase):
    #: One synthetic line per family; each must hit its own family exactly once.
    CAUGHT = [
        ("v35_stage", "the " + "stage " + "V" + "8b" + " seam"),
        ("decision", "a flag " + "(opt-in, " + "A" + "14" + ")"),
        ("plan", "row " + "R" + "6-" + "6" + " of the plan"),
        ("plan", "measured " + "(O" + "1, 2026)"),
        ("plan", "the " + "lane " + "D" + "2" + " run"),
        ("ledger_hyphenless", "closes " + "I" + "287" + " too"),
        ("ledger_hyphenless", "the " + "I" + "287" + " R-value table"),
        ("work_label", "landed in " + "sl" + "ice " + "A" + "1"),
        ("work_label", "run " + "W" + "4 " + "S" + "1" + " again"),
        ("work_label", "written " + "by " + "Cla" + "ude"),
        ("porting_stage", "S" + "8" + "'s problem"),
        ("gap", "see " + "G" + "3" + " in prose"),
        ("porting_stage", "83 words. " + "S" + "6."),
    ]
    #: S1's allowlist cases; none may hit any family.
    SPARED = [
        ("", "the " + "S" + "6-i" + " key"),
        ("", "ARM " + "S" + "5.1" + " section"),
        ("", "Fig. " + "A" + "2" + " shows"),
        ("", "S" + "6 synthetic PTH"),
        ("", "probeid = '" + "A" + "0" + "'"),
        ("", 'facility_id = "' + "E" + '13"'),
        ("", "Facility `" + "F" + "1`"),
        ("", "format='(" + "F" + "10.1)'"),
        ("tests/data/gdl_soda2_x_golden.json", '"family": "' + "B" + '7"'),
        ("", "S" + "2 and " + "S" + "4c are documented conventions"),
        ("", "bin " + "D" + "2 and level " + "O" + "1 are public tokens"),
        ("", "S" + "6.1.2 of the standard, and " + "S" + "5.1"),
        ("tests/data/gdl_soda2_pbp_writer_golden.json",
         '"' + "P" + '3": 1, "k": "' + "I" + '23"'),
        ("nb/x.ipynb", '"image/png": "iVBOR+' + "S" + "8/" + "G" + '3+AA"'),
        ("", "import x  # " + "noqa: " + "F" + "401, " + "I" + "001"),
        ("", "ruff's " + "I" + "001" + " rule"),
        ("nb/x.ipynb", "Q" * 120 + "+" + "S" + "9/" + "I" + "287+" + "Q" * 120),
    ]

    #: The SODA-2 stage family: (path, text, hits).
    SODA2 = [
        ("src/arrayprobe_soda2/x.py", "S" + "3's first file", 1),
        ("src/arrayprobe_uiops/x.py", "S" + "3's first file", 0),
        ("src/arrayprobe_soda2/x.py", "run against the " + "S" + "2 fixture", 0),
        ("src/arrayprobe_soda2/x.py", "the " + "S" + "4-n key", 0),
        ("enhancements_soda2/B.md", "| " + "S" + "2 (`s2_spec_raw_fixture`) | equal", 0),
        ("enhancements_soda2/B.md", "| " + "S" + "2 | unequal (2.4) | 1 |", 0),
        ("src/arrayprobe_soda2/x.py", "rests on for UIO" + "PS " + "S" + "2.", 0),
        ("scripts/validation/gdl/run_soda2_x_bank.py", "S" + "1-" + "S" + "3, the core", 2),
        ("tests/test_soda2_x.py", "S" + "2-<letter> id, " + "S" + "4c, " + "S" + "3.1", 1),
    ]

    def test_the_soda2_stage_family_counts_only_in_soda2_files(self):
        for rel, text, n in self.SODA2:
            with self.subTest(rel=rel, text=text):
                found = find_work_labels(text, rel)
                self.assertEqual(n, len(found["soda2_stage"]), found)
                self.assertEqual(n, sum(len(v) for v in found.values()), found)

    def test_each_synthetic_line_hits_its_family_once(self):
        for family, text in self.CAUGHT:
            with self.subTest(text=text):
                found = find_work_labels(text)
                self.assertEqual(1, len(found[family]), found)
                self.assertEqual(1, sum(len(v) for v in found.values()), found)

    def test_the_allowlist_hits_nothing(self):
        for rel, text in self.SPARED:
            with self.subTest(text=text):
                found = find_work_labels(text, rel)
                self.assertEqual(0, sum(len(v) for v in found.values()), found)

    def test_baseline_names_every_family(self):
        self.assertEqual(set(FAMILIES), set(BASELINE))

    def test_a_count_below_its_baseline_fails_and_names_the_new_value(self):
        """Must fire: a sweep that removed labels without lowering BASELINE is refused."""
        stale = dict(BASELINE, plan=BASELINE["plan"] + 5)
        counts = dict(BASELINE)
        self.assertEqual(rises(counts, stale), [])
        self.assertEqual(falls(counts, stale),
                         [f"plan: {BASELINE['plan']} < baseline {BASELINE['plan'] + 5}; "
                          f"set BASELINE['plan'] = {BASELINE['plan']}"])
        self.assertEqual(falls(counts, BASELINE), [])

    def test_a_count_above_its_baseline_fails(self):
        over = dict(BASELINE, gap=BASELINE["gap"] + 1)
        self.assertEqual(rises(over, BASELINE),
                         [f"gap: {BASELINE['gap'] + 1} > baseline {BASELINE['gap']}"])


@repo_only
@hygiene
class ShippedWorkLabelsMatchTheirBaseline(unittest.TestCase):
    hits: dict[str, list[str]] | None = None

    @classmethod
    def setUpClass(cls):
        cls.hits = shipped_hits()  # one scan (about a minute) serves both directions

    def _counts(self) -> dict[str, int]:
        if self.hits is None:
            self.skipTest("not a git checkout; this guard reads `git ls-files`")
        return {name: len(found) for name, found in self.hits.items()}

    def test_no_family_exceeds_its_baseline(self):
        bad = rises(self._counts(), BASELINE)
        over = [line.split(":")[0] for line in bad]
        self.assertEqual(
            [], bad,
            "a shipped file (after the release strip) carries a new internal work label; "
            "delete the label and keep the fact:\n  "
            + "\n  ".join(h for name in over for h in self.hits[name]))

    def test_no_family_is_below_its_baseline(self):
        """The ratchet only tightens: lower BASELINE to the new count in the same commit."""
        stale = falls(self._counts(), BASELINE)
        self.assertEqual(stale, [], "work labels fell; lower BASELINE in this file "
                                    "in the same commit: " + "; ".join(stale))


if __name__ == "__main__":
    unittest.main()
