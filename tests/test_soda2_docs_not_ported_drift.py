# SPDX-License-Identifier: BSD-3-Clause
"""Detects drift between the public SODA-2 documentation and the
``arrayprobe_soda2`` package itself.

The defect this guards: ``docs/10-known-gaps.md`` asserted, for
several sessions, "Not ported: the buffer decoders (`soda2_processbuffer.pro`
...), the accumulation and merge stages, and the writers" -- naming things
that had in fact been ported and driver-wired rounds earlier. Nothing failed
when that page and ``docs/21-api-soda2.md``
disagreed about what SODA-2 work exists, because no check compared either
side against anything.

**The two sides, drawn from different places** (a project rule: "a check
must draw its two sides from different places, or it is testing nothing"):

- Side A: the *documentation prose* -- every Markdown page under
  ``docs/`` plus ``README.md``, scanned for a "not ported"
  assertion that names something in backticks.
- Side B: the *actual ``arrayprobe_soda2`` package*, introspected at import
  time -- its own submodule names, and every top-level function genuinely
  defined (not merely re-exported) in one of those submodules. Exception
  and refusal classes (``PbpImagesNotPorted``, ``UnsupportedSpecSubformat``,
  ...) are deliberately excluded: those exist precisely to mark something as
  NOT ported, so including them would make the check contradict itself.

If a documentation paragraph that mentions SODA-2 and says something is
"not ported" names (in backticks) a module or function side B actually
ships, that is exactly the class of drift this test exists to catch.

Fast: no subprocess, no GDL/Octave, no notebook execution -- pure introspection
and regex over already-checked-out text. Does not need ``ARRAYPROBE_SLOW``.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import unittest
from pathlib import Path

from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
DOCS_PAGES_DIR = ROOT / "docs"
README = ROOT / "README.md"

_NOT_PORTED_RE = re.compile(r"not ported", re.IGNORECASE)
_SODA2_RE = re.compile(r"soda-?2", re.IGNORECASE)
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Split on sentence-ending punctuation followed by whitespace and a capital
# letter, digit, backtick or bold marker -- a real sentence boundary, not a
# period inside a dotted identifier (`soda2_processbuffer.pro`, `v3.5`,
# `process_2d.py:16`), none of which are followed by a space there.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`*])")

# Extension/generic tokens that regularly show up inside backticks next to a
# real identifier (`soda2_processbuffer.pro` splits into "soda2_processbuffer"
# and "pro") and must never be treated as a name in their own right.
_NON_NAMES = {"pro", "py", "m", "idl", "cpp", "sav", "dat", "csv", "nc", "txt"}

# A backtick span shaped like `some_file.pro:286-306` or `process_2d.py:16` is
# a location citation -- WHERE a refusal is coded, not a claim that the named
# file/routine itself is unported (a "not ported" sentence routinely cites
# the ported driver's own file:line as evidence of where it raises). Skip
# these spans entirely rather than extracting a name from them.
_LOCATION_CITATION_RE = re.compile(r"^[\w./]+:\d+(-\d+)?$")


def _ported_soda2_names() -> set[str]:
    """Names the ``arrayprobe_soda2`` package itself proves are ported:
    every importable submodule, and every function actually defined (its
    own ``__module__``, not imported from elsewhere) in one of them.

    Deliberately excludes classes: this package's own convention is to
    name an unported code path with an exception class
    (``...NotPorted``, ``Unsupported...``, ``...Halt``), so a class being
    importable is not evidence the routine it guards is ported -- often
    the opposite.
    """
    import arrayprobe_soda2 as pkg

    names: set[str] = set()
    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"arrayprobe_soda2.{info.name}")
        names.add(info.name.lower())
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            obj = getattr(mod, attr_name)
            if inspect.isfunction(obj) and getattr(obj, "__module__", None) == mod.__name__:
                names.add(attr_name.lower())
    return names


def _soda2_not_ported_sentences(text: str) -> list[str]:
    """Sentences, from paragraphs that mention SODA-2, that themselves
    assert something is "not ported" -- the scope this check owns.

    Sentence granularity (not paragraph) matters: a paragraph legitimately
    both names what IS ported and, elsewhere, what genuinely is not --
    exactly what a correct rewrite of this doctrine's own defect looks
    like. Extracting at paragraph level would flag a paragraph's own
    ported-module list merely for sharing a paragraph with an unrelated
    "not ported" sentence; extracting at sentence level does not.
    """
    paragraphs = re.split(r"\n\s*\n", text)
    soda2_paragraphs = [p for p in paragraphs if _SODA2_RE.search(p)]
    sentences: list[str] = []
    for para in soda2_paragraphs:
        for sent in _SENTENCE_SPLIT_RE.split(para):
            if _NOT_PORTED_RE.search(sent):
                sentences.append(sent)
    return sentences


def _candidate_names_in(sentence: str) -> set[str]:
    """Every identifier-shaped token inside a backtick span of this
    sentence, lower-cased, extension/format tokens and file:line location
    citations dropped."""
    candidates: set[str] = set()
    for raw in _BACKTICK_RE.findall(sentence):
        if _LOCATION_CITATION_RE.match(raw.strip()):
            continue
        for token in _IDENT_RE.findall(raw):
            token = token.lower()
            if token and token not in _NON_NAMES:
                candidates.add(token)
    return candidates


def find_false_not_ported_claims(text: str, ported: set[str]) -> list[tuple[str, str]]:
    """Returns (name, sentence) for every backtick-quoted identifier in a
    SODA-2 "not ported" sentence of ``text`` that ``ported`` proves is, in
    fact, shipped by the package."""
    findings: list[tuple[str, str]] = []
    for sent in _soda2_not_ported_sentences(text):
        for name in _candidate_names_in(sent) & ported:
            findings.append((name, sent.strip()))
    return findings


def _doc_paths() -> list[Path]:
    paths = sorted(DOCS_PAGES_DIR.glob("*.md"))
    if README.exists():
        paths.append(README)
    return paths


class SodaTwoDocsNotPortedDriftTest(unittest.TestCase):
    """Side A (docs prose) vs. side B (the real package) must agree on what
    is "not ported"."""

    @repo_only
    def test_no_documented_module_is_falsely_claimed_not_ported(self) -> None:
        ported = _ported_soda2_names()
        self.assertTrue(ported, "extraction from arrayprobe_soda2 produced nothing -- broken probe")

        all_findings: list[str] = []
        for path in _doc_paths():
            text = path.read_text(encoding="utf-8")
            for name, sent in find_false_not_ported_claims(text, ported):
                snippet = sent if len(sent) <= 400 else sent[:400] + " ..."
                all_findings.append(
                    f"{path.relative_to(ROOT)}: claims '{name}' is not ported, but "
                    f"arrayprobe_soda2 ships a module or function named '{name}'.\n"
                    f"    sentence: {snippet!r}"
                )

        if all_findings:
            self.fail(
                "SODA-2 documentation contradicts the arrayprobe_soda2 package -- "
                "a name claimed 'not ported' is one this package actually ships:\n\n"
                + "\n\n".join(all_findings)
            )

    def test_detector_fires_on_a_synthetic_false_claim(self) -> None:
        """Proof the mechanism actually detects this class of drift, rather
        than reading fine and matching nothing (this project has shipped
        four such guards before). ``particlesort`` is a real, currently
        ported module -- asserting it is "not ported" must be flagged."""
        ported = _ported_soda2_names()
        self.assertIn("particlesort", ported, "fixture assumption stale: reselect a real module")

        fixture_text = (
            "SODA-2's particle path is real.\n\n"
            "**Not ported**: the accumulation stage (`particlesort`) and the "
            "writers. SODA-2 remains a third chain for comparison.\n"
        )
        findings = find_false_not_ported_claims(fixture_text, ported)
        self.assertTrue(findings, "detector did not fire on a known-false synthetic claim")
        self.assertIn("particlesort", {name for name, _ in findings})

    def test_true_not_ported_claims_are_not_flagged(self) -> None:
        """A currently-accurate refusal (naming something genuinely absent
        from the package) must not be flagged -- otherwise the check would
        eventually be silenced as "always red"."""
        ported = _ported_soda2_names()
        fixture_text = (
            "SODA-2's particle path is real.\n\n"
            "**Not ported**: reprocessing from an existing PBP file (`fn_pbp`) "
            "and particle-image output (`ncdfparticlefile` 2). SODA-2 remains a "
            "third chain for comparison.\n"
        )
        findings = find_false_not_ported_claims(fixture_text, ported)
        self.assertEqual(findings, [], f"false positive(s) on a true refusal: {findings}")


if __name__ == "__main__":
    unittest.main()
