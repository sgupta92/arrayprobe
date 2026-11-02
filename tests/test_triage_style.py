# SPDX-License-Identifier: BSD-3-Clause
"""The triage page's buttons are readable in both themes and say their state to assistive tools.

The author, 2026-10-01: *"the phase buttons dont work well in dark mode."* ``button.phase`` set a
background from the theme but no text colour, so the browser's default black text sat on the
dark surface. Every label button now takes its text colour from the theme, every control shows a
focus ring when reached by keyboard, verdict and phase buttons carry ``aria-pressed``, and the
status line is announced (``role=status``, ``aria-live``).
"""

from __future__ import annotations

import re
import unittest

from tests.test_triage_comment_save import widget

from arrayprobe import triage_server as ts


def rule(selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", ts.STYLE)
    assert m, f"no CSS rule for {selector!r}"
    return re.sub(r"\s+", "", m.group(1))


class TheButtonsAreReadableInBothThemes(unittest.TestCase):

    def test_phase_buttons_take_their_text_colour_from_the_theme(self):
        self.assertIn("color:var(--ink)", rule("button.phase "))

    def test_both_themes_define_the_ink_colour(self):
        light, dark = re.findall(r"--ink:(#[0-9a-fA-F]{6})", ts.STYLE)[:2]
        self.assertNotEqual(light, dark)

    def test_every_control_shows_a_keyboard_focus_ring(self):
        self.assertIn("outline:2pxsolidvar(--accent)",
                      rule("button:focus-visible, a:focus-visible, textarea:focus-visible"))


class TheButtonsSayTheirState(unittest.TestCase):

    def test_every_verdict_and_phase_button_carries_aria_pressed(self):
        html_, _script = widget(current="real", current_phase="ice")
        buttons = re.findall(r"<button class='(?:verdict|phase)[^>]*>", html_)
        self.assertGreaterEqual(len(buttons), 7)  # four verdicts, three phases
        for b in buttons:
            with self.subTest(button=b):
                self.assertRegex(b, r"aria-pressed='(true|false)'")
        pressed = [b for b in buttons if "aria-pressed='true'" in b]
        self.assertEqual(len(pressed), 2)  # the stored verdict and the stored phase

    def test_the_script_keeps_aria_pressed_in_step_with_the_selection(self):
        _html, script = widget()
        self.assertGreaterEqual(script.count("setAttribute('aria-pressed', 'true')"), 2)

    def test_the_status_line_is_announced(self):
        html_, _script = widget()
        self.assertIn("id='status' role='status' aria-live='polite'", html_)



def top_rule(selector: str) -> str:
    """The declarations of the rule whose selector list starts a line and is ``selector``."""
    m = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", ts.STYLE)
    assert m, f"no CSS rule for {selector!r}"
    return re.sub(r"\s+", "", m.group(1))


#: The two theme blocks, the only place a colour is written down.
THEME_BLOCKS = re.compile(r":root\s*\{[^}]*--bg:[^}]*\}")


class ThePagesShareOneVisualSystem(unittest.TestCase):
    """The author: *"make it look modern ... Make the website better looking in general too."*

    One set of spacing, radius, font and type-size tokens; a capped, centred page column; a
    header bar, a card and zebra-striped tables, all coloured from the two theme blocks; and a
    stylesheet that fetches nothing, because the tool runs on a laptop with no network.
    """

    TOKENS = ("--space-1", "--space-2", "--space-3", "--space-4", "--radius",
              "--font-ui", "--font-data", "--text-s", "--text-m", "--text-l")

    def test_root_defines_the_spacing_radius_font_and_size_tokens(self):
        roots = "".join(re.findall(r":root\s*\{([^}]*)\}", ts.STYLE))
        for token in self.TOKENS:
            with self.subTest(token=token):
                self.assertRegex(roots, re.escape(token) + r"\s*:")

    def test_the_body_text_uses_the_ui_font_at_the_middle_size(self):
        r = top_rule("body")
        self.assertIn("font-family:var(--font-ui)", r)
        self.assertIn("font-size:var(--text-m)", r)
        self.assertIn("font-size:var(--text-l)", top_rule("h1"))

    def test_data_is_set_in_the_data_font_never_a_named_face(self):
        outside_root = re.sub(r":root\s*\{[^}]*\}", "", ts.STYLE)
        self.assertNotIn("Consolas", outside_root)
        self.assertIn("font-family:var(--font-data)", rule(".kv "))

    def test_the_page_column_is_capped_and_centred(self):
        for sel in ("main", "body"):
            with self.subTest(sel=sel):
                r = top_rule(sel)
                self.assertIn("max-width:1180px", r)
                self.assertIn("margin:0auto", r)

    def test_the_header_bar_and_the_card_take_the_surface_and_line_colours(self):
        for sel in ("header", ".card"):
            with self.subTest(sel=sel):
                r = top_rule(sel)
                self.assertIn("background:var(--surface)", r)
                self.assertIn("var(--line)", r)
        self.assertIn("border-radius:var(--radius)", top_rule(".card"))

    def test_table_rows_are_zebra_striped_from_the_theme(self):
        self.assertIn("background:var(--surface-2)",
                      top_rule("table.flights tbody tr:nth-child(even)"))

    def test_no_colour_is_written_outside_the_two_theme_blocks(self):
        self.assertEqual(len(THEME_BLOCKS.findall(ts.STYLE)), 2)
        rest = THEME_BLOCKS.sub("", ts.STYLE)
        self.assertNotRegex(rest, r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla)\(")
        self.assertNotRegex(rest, r":\s*(?:white|black)\b")

    def test_the_stylesheet_fetches_nothing(self):
        lowered = ts.STYLE.lower()
        for needle in ("http://", "https://", "@import", "url(", "@font-face"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, lowered)


if __name__ == "__main__":
    unittest.main()
