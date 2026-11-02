# SPDX-License-Identifier: BSD-3-Clause
"""A hand-drawn docs figure quotes only numbers its declared source page states.

The figures under ``docs/figures/`` are drawn by hand, and each names the page its content
comes from in a ``<!-- source: <path> ... -->`` comment. No count or ratio check read them
(found 2026-09-27, when ``hvps_ratio.svg`` still drew 1.4625 and ``evidence_ladder.svg`` still
drew 44 cross-checked cells). This takes every number with two or more decimal places drawn in a
figure's ``<text>`` or written in its ``<desc>`` (a quoted value, not an axis tick) and requires it
in the declared source.

**What it cannot catch**: a figure quoting a value the source still states as superseded. The
known-gaps page keeps 1.4625 beside 1.2402, labelled superseded, so the old HVPS figure passes
this check; a figure whose value must be the headline one needs its own test, as the evidence
ladder has in ``test_evidence_ladder_counts.py``.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "docs" / "figures"
SOURCE = re.compile(r"<!--\s*source:\s*(\S+?)[,\s]")
DRAWN = re.compile(r"<(?:text|desc)\b[^>]*>(.*?)</(?:text|desc)>", re.S)
DECIMAL = re.compile(r"(?<![\w.])\d+\.\d{2,}(?![\w.])")  # a quoted value, not an axis tick


def _checked_figures() -> list[tuple[Path, Path]]:
    out = []
    for svg in sorted(FIGURES.glob("*.svg")):
        m = SOURCE.search(svg.read_text(encoding="utf-8"))
        if m and (ROOT / m.group(1)).is_file():
            out.append((svg, ROOT / m.group(1)))
    return out


@repo_only
@hygiene
class EveryDrawnDecimalIsInTheSource(unittest.TestCase):
    def test_at_least_one_figure_is_checked(self) -> None:
        self.assertTrue(_checked_figures(), "no figure declares a readable source page")

    def test_drawn_decimals_appear_in_the_source(self) -> None:
        # Own floor (guard audit): the sweep must reach figures and decimals, so it cannot pass
        # on an empty or moved figures directory without a sibling's help. Measured 2026-10-06:
        # 4 figures, 6 drawn decimals.
        figures = _checked_figures()
        self.assertGreaterEqual(len(figures), 2, "the sweep reached fewer than 2 figures")
        checked = 0
        for svg, src in figures:
            drawn = " ".join(DRAWN.findall(svg.read_text(encoding="utf-8")))
            source_text = src.read_text(encoding="utf-8")
            decimals = DECIMAL.findall(drawn)
            checked += len(decimals)
            with self.subTest(figure=svg.name, source=src.name):
                missing = sorted({n for n in decimals if n not in source_text})
                self.assertEqual(missing, [], f"{svg.name} draws numbers {src.name} does not state")
        self.assertGreaterEqual(checked, 3, "the sweep checked fewer than 3 drawn decimals")



@repo_only
@hygiene
class TheCheckFires(unittest.TestCase):
    """The comparison reports a drawn value its source does not state."""

    def test_a_value_missing_from_the_source_is_reported(self) -> None:
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs" / "figures").mkdir(parents=True)
            (root / "page.md").write_text("The ratio is 1.2402.", encoding="utf-8")
            (root / "docs" / "figures" / "f.svg").write_text(
                '<svg><!-- source: page.md, row --><text>1.4625</text></svg>', encoding="utf-8")
            with mock.patch(__name__ + ".ROOT", root), \
                    mock.patch(__name__ + ".FIGURES", root / "docs" / "figures"):
                figs = _checked_figures()
                self.assertEqual(len(figs), 1)
                drawn = " ".join(DRAWN.findall(figs[0][0].read_text(encoding="utf-8")))
                missing = [n for n in DECIMAL.findall(drawn)
                           if n not in figs[0][1].read_text(encoding="utf-8")]
                self.assertEqual(missing, ["1.4625"])

    def test_the_sweep_fails_on_an_empty_figures_directory(self) -> None:
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            with mock.patch(__name__ + ".ROOT", Path(d)), \
                    mock.patch(__name__ + ".FIGURES", Path(d) / "missing"):
                sweep = EveryDrawnDecimalIsInTheSource("test_drawn_decimals_appear_in_the_source")
                with self.assertRaises(AssertionError):
                    sweep.test_drawn_decimals_appear_in_the_source()

if __name__ == "__main__":
    unittest.main()
