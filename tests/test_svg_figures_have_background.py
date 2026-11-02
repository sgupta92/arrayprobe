# SPDX-License-Identifier: BSD-3-Clause
"""Every tracked SVG figure under ``docs/`` and ``examples/`` paints its own background.

An SVG with no background is transparent: on GitHub's dark theme its dark ink sits on a
near-black page and the figure reads as blank or broken. Five hand-drawn figures in
``docs/figures/`` shipped that way until the author's review of 2026-10-31. A figure passes
when its first drawn element is a rectangle at the origin that covers the whole ``viewBox``
and is filled, either by a ``fill`` attribute that is not ``none`` or ``transparent``, or by a
class whose stylesheet rule sets ``fill`` (``evidence_ladder.svg`` does this and switches the
colour for dark mode). A second class shows the check firing on synthetic SVGs.
"""

from __future__ import annotations

import re
import unittest
import xml.dom.minidom
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import git_checkout_only
from tests.test_svg_figures_are_valid_xml import tracked_svgs

ROOT = Path(__file__).resolve().parents[1]
_DRAWN = {"rect", "circle", "ellipse", "line", "path", "polygon", "polyline", "text", "g", "use",
          "image"}


def _num(value: str) -> float:
    return float(value.strip().rstrip("px") or 0) if value.strip() not in ("", "100%") else -1.0


def background_problem(text: str) -> str | None:
    """Why this SVG lacks a full-size filled background, or None when it has one."""
    doc = xml.dom.minidom.parseString(text.encode("utf-8"))
    svg = doc.documentElement
    box = svg.getAttribute("viewBox").split()
    if len(box) != 4:
        return "no four-number viewBox"
    x0, y0, w, h = (float(v) for v in box)
    first = next((n for n in svg.childNodes
                  if n.nodeType == n.ELEMENT_NODE and n.tagName in _DRAWN), None)
    if first is None or first.tagName != "rect":
        return "the first drawn element is not a background rectangle"
    rx, ry = _num(first.getAttribute("x") or "0"), _num(first.getAttribute("y") or "0")
    rw, rh = first.getAttribute("width"), first.getAttribute("height")
    full = ("100%" in (rw, rh) and rw == rh == "100%") or (
        rw and rh and float(rw) >= w and float(rh) >= h)
    if (rx, ry) != (x0, y0) or not full:
        return "the first rectangle does not cover the viewBox"
    fill = first.getAttribute("fill").strip().lower()
    if fill:
        return None if fill not in ("none", "transparent") else f"the background fill is {fill!r}"
    for cls in first.getAttribute("class").split():
        if re.search(r"\." + re.escape(cls) + r"\s*\{[^}]*\bfill\s*:\s*(?!none|transparent)", text):
            return None
    return "the background rectangle has no fill"


@hygiene
@git_checkout_only
class TrackedSvgsHaveBackgrounds(unittest.TestCase):
    def test_every_tracked_svg_paints_a_background(self):
        svgs = tracked_svgs(ROOT)
        self.assertTrue(svgs, "no tracked SVG found; the background guard tests nothing")
        bad = []
        for rel in svgs:
            path = ROOT / rel
            if path.is_file():
                problem = background_problem(path.read_text(encoding="utf-8"))
                if problem:
                    bad.append(f"{rel}: {problem}")
        self.assertEqual([], bad, "a figure without a background is unreadable on a dark theme")


@hygiene
class GuardFires(unittest.TestCase):
    HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><title>t</title>'

    def test_a_white_background_passes(self):
        svg = (self.HEAD + '<rect x="0" y="0" width="100" height="50" fill="#ffffff"/>'
               "<text>a</text></svg>")
        self.assertIsNone(background_problem(svg))

    def test_a_styled_background_passes(self):
        svg = (self.HEAD + "<style>.bg{fill:#fff}</style>"
               '<rect class="bg" x="0" y="0" width="100" height="50"/></svg>')
        self.assertIsNone(background_problem(svg))

    def test_no_background_is_reported(self):
        svg = self.HEAD + '<rect x="10" y="10" width="20" height="20" fill="#eee"/></svg>'
        self.assertEqual(background_problem(svg), "the first rectangle does not cover the viewBox")

    def test_text_first_is_reported(self):
        svg = self.HEAD + "<text>a</text></svg>"
        self.assertEqual(background_problem(svg),
                         "the first drawn element is not a background rectangle")

    def test_a_transparent_fill_is_reported(self):
        svg = self.HEAD + '<rect x="0" y="0" width="100" height="50" fill="none"/></svg>'
        self.assertEqual(background_problem(svg), "the background fill is 'none'")
