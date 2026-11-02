# SPDX-License-Identifier: BSD-3-Clause
"""The user-facing pages keep the wording the author's review of the public tree settled.

Each class below was fixed once by hand and found half-done a day later (2026-10-31: two
"reproduces" sentences and a dozen "UIOPS" spellings had survived a one-pass edit), so each
now fails when it reappears. The pages scanned are the ones a user reads: ``docs/*.md`` at the
top level and the package README source. Developer pages (``docs/developer/``) are maintainer
material and are not scanned, except the README source, which ships as the public README.

UIOOPS is the software's name; its repository is spelled UIOPS. Identifiers, upstream tree names
and that one explanatory phrase keep the repository spelling.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _user_pages() -> list[Path]:
    pages = sorted(DOCS.glob("*.md"))
    # A page with a ``.public.md`` twin does not ship; the builder publishes the twin in its place.
    pages = [p for p in pages if not p.with_name(p.stem + ".public.md").is_file()]
    readme_src = DOCS / "developer" / "PACKAGE_README.md"
    if readme_src.is_file():
        pages.append(readme_src)
    return pages


def _hits(pattern: re.Pattern[str], keep=lambda line: False) -> list[str]:
    found = []
    for page in _user_pages():
        for n, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not keep(line):
                found.append(f"{page.relative_to(ROOT).as_posix()}:{n}: {line.strip()[:120]}")
    return found


# An engine or the package is a translation; "reproduces" is kept for a measured reproduction.
_REPRODUCES = re.compile(r"\b(This package|An engine|the package) reproduces\b")

# "UIOPS" naming the software. Kept: upstream tree and repository names, the sentence that
# explains the spelling, and package/import identifiers (lower case, so never matched).
_UIOPS = re.compile(r"\bUIOPS\b(?!-v3)")


def _uiops_is_an_identifier(line: str) -> bool:
    return ("joefinlon/UIOPS" in line or "joefinlon-UIOPS" in line or "spelled UIOPS" in line
            or "github.com/" in line and "/UIOPS" in line)


_PORT_VALIDATION = re.compile(r"--engine 3\.1\.4|--port-validation")

# The campaign's name in prose (class 16b). Profile and preset identifiers (ORACLES_2016,
# ORACLES_REJECT, ...), the case-study page's name and a quoted or backticked value are code
# and stay; a generic statement names no campaign.
_CAMPAIGN_IDENTIFIER = re.compile(r"ORACLES_[0-9A-Z_]+")
_CAMPAIGN_AS_VALUE = re.compile(r"['\"`]ORACLES['\"`]|^def ")


def _campaign_prose(line: str) -> bool:
    return "ORACLES" in _CAMPAIGN_IDENTIFIER.sub("", line) and not _CAMPAIGN_AS_VALUE.search(line)


def _campaign_pages() -> list[Path]:
    # The generated API pages and the README source. Other user pages carry their campaign
    # wording in the deferred 0.1.1 pass (class 16a) and join this list when it lands.
    pages = sorted(DOCS.glob("*-api-*.md"))
    readme_src = DOCS / "developer" / "PACKAGE_README.md"
    return pages + ([readme_src] if readme_src.is_file() else [])


# An internal decision credited in user-visible text: "(author, 2026-09-23)", "the author's choice".
_DECISION_NOTE = re.compile(r"\(author[,']|\bauthor's\b|\bthe author\b(?!-)|author-requested"
                            r"|fix-plan|bug-for-bug ledger"
                            # a ruling credited without "the" (fresh-eyes of build_aadb733: "Author
                            # decision 2026-09-24" and "author-confirmed" in run_flight's --help)
                            r"|\bauthor[- ](decision|directed|instruction|ruling|confirmed)", re.I)


def _credits_line(line: str) -> bool:
    # The AI-use acknowledgement and the attestation note speak of the package's author by right.
    return "is responsible for the result" in line or "who the author is" in line


def _cli_string_hits() -> list[str]:
    """String literals other than docstrings in the shipped packages (help texts, messages and
    attribute values a user reads); docstrings that reach a page are caught by the page scan."""
    import ast
    found = []
    roots = [ROOT / "src", ROOT / "enhancements_uiops" / "src", ROOT / "enhancements_soda2" / "src"]
    for py in sorted(p for r in roots if r.is_dir() for p in r.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.body and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
                    and _DECISION_NOTE.search(n.value)):
                where = f"{py.relative_to(ROOT).as_posix()}:{n.lineno}"
                found.append(f"{where}: {n.value.strip()[:100]}")
    return found


class TheUserPagesKeepTheReviewedWording(unittest.TestCase):

    def test_pages_were_found(self):
        self.assertGreater(len(_user_pages()), 10,
                           "the scan found almost no pages; it would pass vacuously")

    def test_an_engine_is_described_as_a_translation(self):
        self.assertEqual(_hits(_REPRODUCES), [],
                         "describe an engine or the package as translating its original; keep "
                         "'reproduces' for a measured reproduction (author's review, class 10)")

    def test_the_software_is_spelled_uioops_in_prose(self):
        self.assertEqual(_hits(_UIOPS, _uiops_is_an_identifier), [],
                         "prose naming the software writes UIOOPS; UIOPS is only the repository's "
                         "spelling (author's review, class 9)")

    def test_no_user_page_offers_the_validation_engine(self):
        self.assertEqual(_hits(_PORT_VALIDATION), [],
                         "the v3.1.4 validation engine is hidden from the public surface (D8)")

    def test_the_api_pages_and_readme_name_no_campaign_in_prose(self):
        pages = _campaign_pages()
        self.assertGreater(len(pages), 5, "the campaign scan found almost no pages")
        found = [f"{p.relative_to(ROOT).as_posix()}:{n}: {line.strip()[:120]}"
                 for p in pages
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if _campaign_prose(line)]
        self.assertEqual(found, [], "a generic statement drops the campaign's name; identifiers "
                                    "stay (author's review, class 16b)")

    def test_no_user_page_or_cli_string_carries_a_decision_note(self):
        # Release review 2026-11-01: "(author, 2026-09-23)" sat in `run_flight --engine`'s help and
        # "the author's choice" in `make-tas-file --help`; an API page carries a docstring verbatim.
        found = _hits(_DECISION_NOTE, _credits_line) + _cli_string_hits()
        self.assertEqual(found, [], "a user-visible page, help text or message names no internal "
                                    "decision or its date; state the behaviour instead")

    def test_page_numbers_are_unique(self):
        prefixes: dict[str, list[str]] = {}
        for page in sorted(DOCS.glob("[0-9][0-9]-*.md")):
            stem = page.name
            if stem.endswith(".public.md"):
                continue
            prefixes.setdefault(stem[:2], []).append(stem)
        dupes = {k: v for k, v in prefixes.items() if len(v) > 1}
        self.assertEqual(dupes, {}, "two user pages share a number (author's review, class 17)")


class TheGuardsFire(unittest.TestCase):
    """Each pattern matches the text it exists to refuse, so none of them can pass vacuously."""

    def test_each_pattern_matches_a_planted_line(self):
        self.assertTrue(_REPRODUCES.search("This package reproduces two chains"))
        self.assertTrue(_REPRODUCES.search("An engine reproduces its original:"))
        self.assertFalse(_REPRODUCES.search("the port reproduces three whole-program Octave runs"))
        self.assertTrue(_UIOPS.search("UIOPS writes only one of the three"))
        self.assertFalse(_UIOPS.search("vendored at UIOPS-v3.5/"))
        self.assertTrue(_uiops_is_an_identifier("UIOOPS (its repository is spelled UIOPS)"))
        self.assertTrue(_PORT_VALIDATION.search("run with --engine 3.1.4 --port-validation"))
        self.assertTrue(_campaign_prose("This is the ORACLES-tuned pair"))
        self.assertTrue(_DECISION_NOTE.search("REQUIRED, no default (author, 2026-09-23): a run"))
        self.assertTrue(_DECISION_NOTE.search("default 'nearest', the author's choice"))
        self.assertFalse(_DECISION_NOTE.search("the package's sole author is credited"))
        self.assertTrue(_DECISION_NOTE.search("Re-run the stage, or have the author say which"))
        self.assertTrue(_DECISION_NOTE.search("Measured on the author's 441 labels"))
        self.assertTrue(_DECISION_NOTE.search("correction (author-requested; default off)"))
        self.assertTrue(_DECISION_NOTE.search("stamped as tas_series. Author decision 2026-09-24."))
        self.assertTrue(_DECISION_NOTE.search("the largest UIOPS tas_max, author-confirmed)"))
        self.assertFalse(_campaign_prose("``ORACLES_REJECT`` (area_ratio_z 0.5)"))
        self.assertFalse(_campaign_prose("Default to ``\"ORACLES\"``/``\"2DS\"``"))


# A repository sweep: run before every full suite by the pre-suite gate
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True


if __name__ == "__main__":
    unittest.main()
