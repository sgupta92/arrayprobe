# SPDX-License-Identifier: BSD-3-Clause
"""Speed work names its space, and a byte-identical claim is a test, not a sentence.

"Speed work is the one category that lives in BOTH spaces" (author-directed
2026-09-04), sets three obligations. Two are checkable from the documents; this module executes
them (a rule addressed to attention is not a control):

1. **Every speed claim names its space.** A *speed claim* is a paragraph on an outward surface
   that states a measured multiplier (``1.48×``, ``1.7-1.9×``), or says ``speedup``/``speed-up``/
   ``faster``, while talking about one of the speed mechanisms (``--s2-jobs``, ``--chunks``,
   ``--jobs``, ``read_binary_SPEC_parallel``, ``parallel``, ``chunked``). The *section* holding
   that paragraph (the nearest Markdown heading above it, down to the next heading) must name
   the space: ``port``, ``this package``, ``pyuiops`` or ``enhancements``.

2. **A byte-identical claim is a test, not a sentence.** A paragraph that says
   ``byte-identical``/``bit-identical``/``bit for bit``/``identical output`` about a speed
   mechanism is backed only if the test module that owns that mechanism exists, is collectible,
   and carries a test whose name or docstring speaks of identity. The mapping
   mechanism -> test module is BACKING below; the claim (side one, the document) and the
   assertion (side two, the test source) come from different places.

The checks are plain functions over text so the last class can feed them a mutated document and
assert they FIRE -- a guard must be executed, not read.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import (
    PKG_ROOT,  # noqa: E402
    repo_only,
)

REPO = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent

# The surfaces tests/test_outward_language_leads_with_findings.py calls outward.
SURFACES: list[Path] = [
    REPO / "README.md",
    PKG_ROOT / "README.md",
    PKG_ROOT / "docs" / "developer" / "TWO_ENGINES.md",
    REPO / "enhancements_uiops" / "README.md",
    *sorted((REPO / "docs").glob("*.md")),
]

MECHANISM = re.compile(
    r"--s2-jobs|--chunks|--jobs|read_binary_SPEC_parallel|\bparallel\b|\bchunked\b", re.I
)
MEASURED = re.compile(
    r"\d(?:\.\d+)?\s*(?:[–-]\s*\d+(?:\.\d+)?\s*)?[×x](?!\w)|speed-?up|\bfaster\b", re.I
)
SPACE = re.compile(r"\bport\b|\bthis package\b|\bpyuiops\b|\benhancements?\b", re.I)
IDENTITY = re.compile(r"byte-identical|bit-identical|bit for bit|identical\b", re.I)

# Mechanism -> the test modules whose job is to assert the identity, v3.1.4 engine first, then
# v3.5. Both sides must exist: a claim is backed by the first module present, so a distribution
# carrying only the v3.5 engine still checks its claims.
BACKING: dict[str, tuple[str, ...]] = {
    "--s2-jobs": ("test_spec_parallel.py", "test_v35_spec_parallel.py"),
    "read_binary_SPEC_parallel": ("test_spec_parallel.py", "test_v35_spec_parallel.py"),
    "--chunks": ("test_imgproc_merge_chunks.py", "test_v35_imgproc_merge_chunks.py"),
    "--jit": ("test_imgproc_jit_identity.py", "test_v35_imgproc_jit_identity.py"),
    "jit=True": ("test_imgproc_jit_identity.py", "test_v35_imgproc_jit_identity.py"),
}


def backing_module(mech: str, tests_dir: Path) -> Path:
    """The first of ``mech``'s backing modules present in ``tests_dir``, else the first named."""
    names = BACKING[mech]
    return next((tests_dir / n for n in names if (tests_dir / n).is_file()), tests_dir / names[0])
HEADING = re.compile(r"^#{1,6}\s")
FENCE = re.compile(r"^(```|~~~)")


def sections(text: str) -> list[tuple[str, list[str]]]:
    """Split Markdown into (heading, paragraphs); fenced code is dropped."""
    out: list[tuple[str, list[str]]] = [("(top)", [])]
    para: list[str] = []
    in_fence = False

    def flush() -> None:
        if para:
            out[-1][1].append(" ".join(para))
            para.clear()

    for line in text.splitlines():
        if FENCE.match(line.strip()):
            in_fence = not in_fence
            flush()
            continue
        if in_fence:
            continue
        if HEADING.match(line):
            flush()
            out.append((line.strip("# ").strip(), []))
        elif line.strip():
            para.append(line.strip())
        else:
            flush()
    flush()
    return out


def speed_claims_without_space(text: str) -> list[tuple[str, str]]:
    """(heading, paragraph) for every measured speed claim whose section names no space."""
    bad: list[tuple[str, str]] = []
    for heading, paras in sections(text):
        section_text = heading + " " + " ".join(paras)
        names_space = bool(SPACE.search(section_text))
        for p in paras:
            if MECHANISM.search(p) and MEASURED.search(p) and not names_space:
                bad.append((heading, p[:160]))
    return bad


def byte_identity_claims(text: str) -> list[tuple[str, str]]:
    """(mechanism, paragraph) for every byte-identical claim about a backed mechanism."""
    found: list[tuple[str, str]] = []
    for _heading, paras in sections(text):
        for p in paras:
            if not IDENTITY.search(p):
                continue
            for mech in BACKING:
                if mech in p:
                    found.append((mech, p[:160]))
    return found


def backing_gaps(claims: list[tuple[str, str]], tests_dir: Path) -> list[str]:
    """Claims whose backing test module is missing or carries no identity-named test."""
    gaps: list[str] = []
    for mech, p in claims:
        module = backing_module(mech, tests_dir)
        if not module.is_file():
            gaps.append(f"{mech}: {module.name} missing -- {p}")
            continue
        src = module.read_text(encoding="utf-8")
        named = re.search(r"def test_\w*(identical|same|byte|serial)\w*\(", src)
        doc = re.search(r'"""[^"]*(identical|bit for bit|byte-for-byte|same bytes)', src, re.S)
        if not (named or doc):
            gaps.append(f"{mech}: {module.name} has no identity-named test -- {p}")
    return gaps


@hygiene
@repo_only
class SpeedClaimsNameTheirSpace(unittest.TestCase):
    def test_every_measured_speed_claim_sits_in_a_section_naming_port_or_enhancements(self):
        offenders = []
        for path in SURFACES:
            for heading, p in speed_claims_without_space(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(REPO)} [{heading}]: {p}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_check_is_exercised_by_a_real_claim(self):
        """README's 'Running it faster' section is a speed claim; the check must SEE it."""
        text = (REPO / "README.md").read_text(encoding="utf-8")
        seen = [
            p for _h, paras in sections(text) for p in paras
            if MECHANISM.search(p) and MEASURED.search(p)
        ]
        self.assertTrue(seen, "no measured speed claim found in README.md -- the check is blind")


@hygiene
@repo_only
class ByteIdenticalClaimsAreTests(unittest.TestCase):
    def test_every_byte_identical_speed_claim_resolves_to_an_identity_test(self):
        claims: list[tuple[str, str]] = []
        for path in SURFACES:
            claims.extend(byte_identity_claims(path.read_text(encoding="utf-8")))
        self.assertTrue(claims, "no byte-identical speed claim found on any surface -- blind")
        self.assertEqual(backing_gaps(claims, TESTS), [])

    def test_backing_modules_are_collectible(self):
        for name in {backing_module(m, TESTS).name for m in BACKING}:
            with self.subTest(name):
                suite = unittest.defaultTestLoader.loadTestsFromName(f"tests.{name[:-3]}")
                self.assertGreater(suite.countTestCases(), 0)


@hygiene
class TheGuardFires(unittest.TestCase):
    """Mutations that must be caught. A guard must be executed, not read."""

    def test_a_speed_claim_without_a_space_is_reported(self):
        doc = "# Faster\n\n`--chunks 5` gives 1.48× on five workers.\n"
        self.assertEqual(len(speed_claims_without_space(doc)), 1)
        doc_ok = doc + "\nThis lives in the port.\n"
        self.assertEqual(speed_claims_without_space(doc_ok), [])

    def test_a_byte_identical_claim_with_no_backing_test_is_reported(self):
        doc = "# Speed\n\n`--chunks` produces byte-identical output.\n"
        claims = byte_identity_claims(doc)
        self.assertEqual([m for m, _ in claims], ["--chunks"])
        empty = PKG_ROOT / "docs"  # a real directory holding no test modules
        self.assertEqual(len(backing_gaps(claims, empty)), 1)
        self.assertEqual(backing_gaps(claims, TESTS), [])


if __name__ == "__main__":
    unittest.main()
