# SPDX-License-Identifier: BSD-3-Clause
"""Every published speed figure must carry machine-load evidence.

WHY THIS EXISTS. Two speed figures were published and withdrawn within the
same day (2026-09-18): a 1.22x full-flight multiplier, then a
"sub-additivity" finding. Both had one cause: the timing runs were made on a
machine that was doing other work, and nothing recorded that. The
contaminated pair understated the flag by 31% -- and the lane had speculated
contention "could go either way", so guessing the direction was itself the
error. The clean re-measurement worked because two controls existed:
``wait_quiet.py`` (held the run until four consecutive 30s samples showed no
other session's python) and ``machine_load.txt`` (70 of 71 load samples
across the pair read other=0).

The principle: "A rule addressed to attention is not a control...
when a standing rule is found to have failed, build the check." This is that
check, for speed figures specifically -- the same family
``test_publish_ready.py`` and ``test_validation_results_propagate.py``
already build for counts and validation results.

WHAT IT ENFORCES. ``SPEED.md`` marks every headline multiplier with its own
bold convention (``**2.62x**``, ``**1.79x**``, ``**36.2x**``, ...). For each
one, its enclosing ``##`` section must name, somewhere in that section: a
machine, an input scope (file/records/particles/reps), and an explicit
contention statement (what else was running, or that the machine was
verified quiet and by what control). A section that instead carries
withdrawal/contamination/"not established" language is exempt -- the check
is about undeclared conditions, never about forbidding an honest caveat.

WHAT IT CANNOT DO. This is a keyword sweep over prose, the same shape
``test_publish_ready.py`` already uses for its own text surfaces -- it
proves presence, not that the words are attached to the right number. The
context window is the whole enclosing ``##`` section rather than the row
itself: SPEED.md sometimes states a figure's machine/input scope in an
adjacent table under the same section heading (the "two measured cells,
in full scope" table plus its separate "scope" table immediately below),
and checking only the row itself would false-fail exactly the two
best-documented figures in the document. The trade-off is real: a bare
figure sharing a large section with a well-documented one can ride on the
other's language. Tightening the window to a smaller, provably-correct unit
is future work, not a silent gap -- it is named here.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from tests._hygiene import hygiene
from tests._repo import PKG_ROOT  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
_SPEED_MD = PKG_ROOT / "docs" / "developer" / "SPEED.md"

#: A bold span containing at least one "<number>x"/"<number>X"/"<number>x"
#: token is SPEED.md's own convention for a headline figure worth quoting --
#: every measured, derived and withdrawn multiplier in the document is
#: written this way (``**2.62x**``, ``**1.79x**``, ``**36.2x**``,
#: ``**SODA-2's flood fill: 36.2x ... ~1.37x ...**``).
_BOLD_SPAN = re.compile(r"\*\*([^*\n]{1,220})\*\*")
_NUM_X = re.compile(r"\d+(?:\.\d+)?\s*[x×X](?!\w)")

#: A section carrying any of these anywhere is declaring the condition
#: honestly rather than hiding it -- exempt from the positive check.
_CAVEAT_MARKERS = (
    "withdrawn", "WITHDRAWN", "retracted", "retraction",
    "do not quote", "must not be quoted", "not be quoted",
    "not established", "not a measurement", "no ratio",
    "not measured", "contaminated", "derived", "DERIVED",
    "band, not a figure", "band, not a point",
    "not a claim", "not rank", "is not a finding",
)

#: Deliberately specific machine *identifiers*, not the bare word "machine"
#: -- a contention sentence ("the machine was verified quiet") also contains
#: that word, so using it here would let a row satisfy this marker purely
#: from its contention statement and never actually name a machine.
_MACHINE_MARKERS = (
    "laptop", "cores", "i7-", "i5-", "i9-", "CPU",
    "thread laptop", "logical cores",
)

_INPUT_MARKERS = (
    "records", "particles", "buffers", "reps", " MB", " GB",
    "flight", "file", "ROIs",
)

_CONTENTION_MARKERS = (
    "idle", "quiet", "otherwise running", "contention", "contended",
    "suite running", "load sampled", "verified quiet", "foreign workers",
    "Win32_Process", "was not quiet", "machine quiet", "overlapped",
    "alongside", "wait_quiet", "machine_load",
)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def _split_sections(text: str) -> list[str]:
    """Split on level-2 (``## ``) headings; each chunk keeps its heading."""
    parts = re.split(r"\n(?=## )", text)
    return [p for p in parts if p.strip()]


def _section_heading(section: str) -> str:
    m = re.match(r"##+ [^\n]*", section)
    return m.group(0) if m else "(preamble, before the first ## heading)"


def figure_spans(section: str) -> list[str]:
    """Every bold span in ``section`` that names a multiplier figure."""
    out = []
    for m in _BOLD_SPAN.finditer(section):
        content = m.group(1)
        if _NUM_X.search(content):
            out.append(m.group(0))
    return out


def evaluate_section(section_text: str) -> tuple[bool, list[str]]:
    """(ok, missing) for one section's undeclared-machine-load check.

    Exempt if the section carries caveat language anywhere (withdrawal,
    contamination, "not established", an explicit derivation). Otherwise it
    must name a machine, an input scope, and a contention statement
    somewhere in the same section.
    """
    if _has_any(section_text, _CAVEAT_MARKERS):
        return True, []
    missing = []
    if not _has_any(section_text, _MACHINE_MARKERS):
        missing.append("machine")
    if not _has_any(section_text, _INPUT_MARKERS):
        missing.append("input")
    if not _has_any(section_text, _CONTENTION_MARKERS):
        missing.append("contention")
    return (len(missing) == 0), missing


@hygiene
class SpeedFiguresCarryEvidence(unittest.TestCase):
    """Every headline multiplier SPEED.md prints must declare its conditions."""
    sections: Any  # assigned in setUpClass/setUp; see there for the value
    text: Any  # assigned in setUpClass/setUp; see there for the value

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _SPEED_MD.read_text(encoding="utf-8")
        cls.sections = _split_sections(cls.text)

    def test_speed_md_exists(self) -> None:
        self.assertTrue(_SPEED_MD.is_file(), f"missing {_SPEED_MD}")

    def test_the_document_still_uses_the_bold_multiplier_convention(self) -> None:
        # Guard the guard: if SPEED.md ever stops marking figures this way,
        # the sweep below would silently check zero rows and report "clean".
        total = sum(len(figure_spans(s)) for s in self.sections)
        self.assertGreater(
            total, 0,
            "no bold '**N.NNx**'-style figures found anywhere in SPEED.md -- "
            "either the document's convention changed or the regex has "
            "drifted from it; this sweep would otherwise pass by finding "
            "nothing to check")

    def test_every_headline_figure_declares_machine_load_conditions(self) -> None:
        failures = []
        seen: set[tuple[str, str]] = set()
        for section in self.sections:
            heading = _section_heading(section)
            for raw in figure_spans(section):
                key = (heading, raw)
                if key in seen:
                    continue
                seen.add(key)
                ok, missing = evaluate_section(section)
                if not ok:
                    failures.append(
                        f"{raw!r} under {heading!r} names no {'/'.join(missing)}")
        self.assertEqual(
            failures, [],
            "a speed figure in SPEED.md does not declare machine, input or "
            "contention conditions anywhere in its section -- undeclared "
            "contention is exactly how the 1.22x figure and the "
            "sub-additivity finding were both published and withdrawn on "
            "2026-09-18: " + "; ".join(failures))

    # -- Proof this guard can fail. Four checks here matched nothing while
    # reading fine (guards-must-be-executed); a mutation-style assertion on
    # constructed rows, the same shape as
    # test_validation_results_propagate.py::test_the_check_can_actually_fail,
    # is the standing antidote.

    def test_the_checker_rejects_a_row_missing_contention(self) -> None:
        row = ("## A new flag\n\nMeasured **1.30x** on the i7-1365U laptop, "
               "950 records / 82,028 particles.")
        ok, missing = evaluate_section(row)
        self.assertFalse(ok, "checker passed a row with no contention "
                              "statement at all -- it cannot fail, so it "
                              "guards nothing")
        self.assertEqual(missing, ["contention"])

    def test_the_checker_rejects_a_row_missing_machine(self) -> None:
        row = ("## A new flag\n\nMeasured **1.30x**, 950 records, the "
               "machine was verified quiet by wait_quiet.py.")
        ok, missing = evaluate_section(row)
        self.assertFalse(ok)
        self.assertEqual(missing, ["machine"])

    def test_the_checker_rejects_a_row_missing_input(self) -> None:
        row = ("## A new flag\n\nMeasured **1.30x** on the i7-1365U laptop, "
               "verified quiet by wait_quiet.py.")
        ok, missing = evaluate_section(row)
        self.assertFalse(ok)
        self.assertEqual(missing, ["input"])

    def test_the_checker_accepts_a_fully_declared_row(self) -> None:
        row = ("## A new flag\n\nMeasured **1.30x** on the i7-1365U laptop, "
               "950 records / 82,028 particles, machine verified quiet by "
               "wait_quiet.py (four consecutive quiet samples).")
        ok, missing = evaluate_section(row)
        self.assertTrue(ok, f"fully declared row rejected, missing={missing}")

    def test_the_checker_accepts_an_explicitly_withdrawn_row(self) -> None:
        row = ("## A new flag\n\nWITHDRAWN: **1.22x** stood here briefly and "
               "is retracted; the machine was not quiet.")
        ok, missing = evaluate_section(row)
        self.assertTrue(ok, "an explicitly withdrawn figure must pass -- "
                            "the check is about undeclared conditions, not "
                            "about forbidding honest caveats")

    def test_the_checker_accepts_a_row_marked_not_established(self) -> None:
        row = "## A new flag\n\n**1.30x** is *not established*; no run was made."
        ok, _missing = evaluate_section(row)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
