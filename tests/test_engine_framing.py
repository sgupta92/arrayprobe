# SPDX-License-Identifier: BSD-3-Clause
"""Outward prose frames the engines as the author ruled.

Two errors recur in README.md, docs/*.md and the example notebooks' markdown cells:

1. SODA-2 presented as secondary to UIOOPS (a "cross-check" for a UIOOPS run) rather than an
   engine on equal footing with UIOOPS v3.5.
2. v3.1.4 presented as a user choice rather than the ORACLES port-validation anchor, reached
   only with ``--engine 3.1.4 --port-validation``.

Each pattern below was derived from an instance found in prose. A legitimate use goes in
ALLOWED as (relative path, line number, reason); the self-tests make every pattern fire.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (name, regex, what it encodes)
PATTERNS = [
    ("soda2-cross-check-rather-than",
     re.compile(r"cross-check\s+rather\s+than", re.I),
     "SODA-2 as a cross-check rather than an engine (docs/21-api-soda2.md)"),
    ("soda2-cross-check-for-uiops",
     re.compile(r"cross-check\*{0,2}\s+(for|of)\s+a\s+UIOPS\s+(run|product)", re.I),
     "SODA-2 product as a cross-check for a UIOPS run (docs/29-migrating-from-soda2.md)"),
    ("soda2-secondary",
     re.compile(r"SODA-2\b[^.\n]{0,60}\bsecondary\b", re.I),
     "SODA-2 as the secondary engine"),
    ("v314-engine-call-as-choice",
     re.compile(r"engine\(\s*\\?[\"']3\.1\.4\\?[\"']\s*\)"),
     "engine(\"3.1.4\") offered as a call, with no port-validation/absence context on the line"),
    ("v314-choose",
     re.compile(r"\b(choose|pick|select)\b[^.\n]{0,40}\bv?3\.1\.4\b", re.I),
     "v3.1.4 offered as a user choice"),
]

# A v3.1.4 line is legitimate when it says the engine is absent or names --port-validation.
V314_CONTEXT = re.compile(r"port-validation|V314EngineAbsent|validation anchor", re.I)

# (relative path, 1-based line, reason)
ALLOWED = []


def _hits(text):
    out = []
    for name, rx, _ in PATTERNS:
        if not rx.search(text):
            continue
        if name.startswith("v314-") and V314_CONTEXT.search(text):
            continue
        out.append(name)
    return out


def _surfaces():
    files = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))
    for p in files:
        if p.is_file():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                yield p, i, line
    for nb in sorted((ROOT / "examples").rglob("*.ipynb")):
        if ".ipynb_checkpoints" in nb.parts:
            continue
        cells = json.loads(nb.read_text(encoding="utf-8")).get("cells", [])
        for c_idx, cell in enumerate(cells):
            if cell.get("cell_type") != "markdown":
                continue
            src = cell.get("source", "")
            src = "".join(src) if isinstance(src, list) else src
            for i, line in enumerate(src.splitlines(), 1):
                # line numbers in notebooks are cell*10000 + line, stable enough to allow-list
                yield nb, c_idx * 10000 + i, line


class EngineFramingTest(unittest.TestCase):
    def test_outward_prose_frames_engines_as_ruled(self):
        allowed = {(p, n) for p, n, _ in ALLOWED}
        bad = []
        for path, n, line in _surfaces():
            rel = path.relative_to(ROOT).as_posix()
            for name in _hits(line):
                if (rel, n) not in allowed:
                    bad.append(f"{rel}:{n} [{name}] {line.strip()[:160]}")
        self.assertEqual(bad, [], "engine framing (SODA-2 equal footing; v3.1.4 port "
                         "validation only) -- fix the prose, or allow-list with a reason:\n"
                         + "\n".join(bad))

    def test_allow_list_entries_still_match(self):
        lines = {(p.relative_to(ROOT).as_posix(), n): line for p, n, line in _surfaces()}
        for rel, n, reason in ALLOWED:
            self.assertTrue(reason.strip(), f"{rel}:{n} has no reason")
            self.assertIn((rel, n), lines, f"stale allow-list entry {rel}:{n}")
            self.assertTrue(_hits(lines[(rel, n)]), f"allow-list entry {rel}:{n} no longer fires")


class PatternsFireTest(unittest.TestCase):
    SAMPLES = {
        "soda2-cross-check-rather-than":
            "NCAR's chain, and a cross-check rather than a bit-fidelity target.",
        "soda2-cross-check-for-uiops":
            "a SODA-2 product is an **independent cross-check** for a UIOPS run",
        "soda2-secondary": "SODA-2 is offered as a secondary engine.",
        "v314-engine-call-as-choice": 'and `uiops.engine("3.1.4")` the other one',
        "v314-choose": "Users may choose the v3.1.4 engine for new data.",
    }

    def test_every_pattern_has_a_sample(self):
        self.assertEqual(set(self.SAMPLES), {n for n, _, _ in PATTERNS})

    def test_each_pattern_fires(self):
        for name, sample in self.SAMPLES.items():
            with self.subTest(name=name):
                self.assertIn(name, _hits(sample))

    def test_v314_context_suppresses(self):
        self.assertEqual(_hits('`arrayprobe.engine("3.1.4")` raises `V314EngineAbsent`'), [])
        self.assertEqual(_hits("choose 3.1.4 only with --engine 3.1.4 --port-validation"), [])

    def test_equal_footing_wording_is_clean(self):
        self.assertEqual(_hits("SODA-2 and UIOPS v3.5 are engines on equal footing."), [])


if __name__ == "__main__":
    unittest.main()
