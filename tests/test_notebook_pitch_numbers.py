# SPDX-License-Identifier: BSD-3-Clause
"""Every number an example notebook's opening pitch quotes is one its outputs print.

Added 2026-10-03 (repository-defects slot). The example notebooks' first markdown
cell gained an elevator pitch quoting results typed by hand from the executed
outputs; nothing tied them to the code, so a re-execution that moves a result
would leave a stale claim. This guard takes the numbers in the FIRST markdown
cell -- decimals with at least two significant digits, percentages and dB values
-- and asserts each one appears in that notebook's stored code-cell outputs
(``text/plain`` or stream text), allowing rounding to the printed precision and
the fraction/percent conversion. Years, dates, version and section numbers,
``file:line`` citations and micrometre sizes are ignored.

A notebook whose pitch could not be fixed in the pass that built this guard is
named in ``ALLOWED_UNTIED`` with its date: the debt is visible, and the guard
fires on every other notebook.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import repo_only

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"

#: notebook stem -> date it was allow-listed. Each entry is owed a fix:
#: reword the pitch to a printed number, or print the number and re-execute.
ALLOWED_UNTIED: dict[str, str] = {}

_NUM = re.compile(
    r"(?<![\w.§:/#-])([-+−]?\d+(?:\.\d+)?)(\s*%|\s*dB\b)?(?![\w.]*\d)(?!\s*(?:µm|um|μm|mm\b))"
)
_SKIP_BEFORE = re.compile(
    r"(?:\bv|engine\s|UIOPS\s|§|Section\s|section\s|notebook\s|Notebook\s"
    r"|Eq\.\s*|Fig\.\s*|S-|I-)$"
)


def _strip(md: str) -> str:
    md = re.sub(r"\]\([^)]*\)", "]", md)          # link targets
    md = re.sub(r"`[^`]*`", " ", md)              # code spans
    md = re.sub(r"https?://\S+", " ", md)
    md = re.sub(r"\$[^$]*\$", " ", md)            # inline maths
    return md


def pitch_numbers(md: str) -> list[tuple[str, float, int, str]]:
    """(token, value, decimals, kind) for each quotable number in ``md``."""
    out = []
    text = _strip(md)
    for m in _NUM.finditer(text):
        tok, unit = m.group(1), (m.group(2) or "").strip()
        if _SKIP_BEFORE.search(text[: m.start()]):
            continue
        tok_n = tok.replace("−", "-")
        decimals = len(tok_n.split(".")[1]) if "." in tok_n else 0
        kind = "pct" if unit == "%" else ("db" if unit == "dB" else "num")
        if kind == "num":
            if decimals == 0:
                continue                           # integers: counts, years, ids
            digits = tok_n.lstrip("+-").replace(".", "").lstrip("0")
            if len(digits) < 2:
                continue
        out.append((tok, float(tok_n), decimals, kind))
    return out


def output_text(nb: dict) -> str:
    parts = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        for o in cell.get("outputs", []):
            if "text" in o:
                t = o["text"]
                parts.append("".join(t) if isinstance(t, list) else t)
            data = o.get("data", {})
            for key in ("text/plain", "text/markdown", "text/html"):
                if key in data:
                    t = data[key]
                    parts.append("".join(t) if isinstance(t, list) else t)
    return "\n".join(parts)


_OUT_NUM = re.compile(r"[-+−]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _matches(value: float, decimals: int, kind: str, printed: list[float]) -> bool:
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    targets = {abs(value)}
    if kind == "pct":
        targets.add(abs(value) / 100.0)
    for v in printed:
        for t in targets:
            if abs(abs(v) - t) <= tol or (t != abs(value) and abs(abs(v) - t) <= tol / 100):
                return True
    return False


def untied_numbers(nb: dict) -> list[str]:
    md_cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "markdown"]
    if not md_cells:
        return []
    src = md_cells[0].get("source", "")
    src = "".join(src) if isinstance(src, list) else src
    printed = [float(s.replace("−", "-")) for s in _OUT_NUM.findall(output_text(nb))]
    return [tok + ("%" if k == "pct" else " dB" if k == "db" else "")
            for tok, v, d, k in pitch_numbers(src) if not _matches(v, d, k, printed)]


def _nb(md: str, out: str) -> dict:
    return {"cells": [
        {"cell_type": "markdown", "source": md},
        {"cell_type": "code", "source": "", "outputs": [{"output_type": "stream", "text": out}]},
    ]}


@hygiene
class TestGuardFires(unittest.TestCase):
    def test_a_stale_pitch_number_is_named(self):
        nb = _nb("Ratio 1.46 and a +7.4 dB gap; 12.5% rejected.", "ratio 1.4612\ngap 7.43\n")
        self.assertEqual(["12.5%"], untied_numbers(nb))

    def test_rounding_and_percent_conversion_pass(self):
        nb = _nb("Ratio 0.91, 12.5% rejected, in 2026 per v3.5.", "0.9132 0.125\n")
        self.assertEqual([], untied_numbers(nb))

    def test_versions_dates_sizes_and_integers_are_ignored(self):
        nb = _nb("UIOPS v3.1.4, 2026-10-03, bins of 12.5 µm, §3.2, 42 particles.", "")
        self.assertEqual([], untied_numbers(nb))


#: Floor measured 2026-10-05 (guard audit, 36 notebooks). A sweep that finds
#: fewer has lost its input, not passed.
MIN_NOTEBOOKS = 30


def sweep(tc: unittest.TestCase, examples: Path) -> list[str]:
    """Stale pitch numbers per notebook; asserts the swept set is not empty."""
    stale, checked = [], 0
    paths = sorted(p for p in examples.rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts)
    tc.assertGreaterEqual(len(paths), MIN_NOTEBOOKS, f"only {len(paths)} notebooks in {examples}")
    for path in paths:
        if path.stem in ALLOWED_UNTIED:
            continue
        nb = json.loads(path.read_text(encoding="utf-8"))
        md = [c for c in nb.get("cells", []) if c.get("cell_type") == "markdown"]
        if md:
            src = md[0].get("source", "")
            checked += len(pitch_numbers("".join(src) if isinstance(src, list) else src))
        bad = untied_numbers(nb)
        if bad:
            stale.append(f"{path.name}: {', '.join(bad)}")
    tc.assertGreater(checked, 0, "no pitch numbers were checked")
    return stale


@hygiene
@repo_only
class TestExamplePitchesQuotePrintedNumbers(unittest.TestCase):
    def test_every_pitch_number_is_printed_by_its_notebook(self):
        stale = sweep(self, EXAMPLES)
        self.assertEqual([], stale, "pitch numbers no output prints:\n" + "\n".join(stale))

    def test_the_sweep_refuses_an_empty_examples_dir(self):
        # Every guard must be able to fail: an empty or moved examples/ once
        # passed this sweep with nothing checked.
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                sweep(self, Path(tmp))
            with self.assertRaises(AssertionError):
                sweep(self, Path(tmp) / "missing")

    def test_allow_list_names_only_existing_notebooks(self):
        missing = [s for s in ALLOWED_UNTIED if not any(EXAMPLES.rglob(f"{s}.ipynb"))]
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
