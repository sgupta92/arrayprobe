# SPDX-License-Identifier: BSD-3-Clause
"""The triage pages put what the reviewer needs on one screen.

The author, 2026-10-01: *"field guide should be at the top of the page. on the particle page,
the buttons and properties should be next to the particle image and not below it - so the
user can see both all buttons and the image together in one screen."*

Three checks:

1. **The queue page** shows the field guide (the Holroyd habit words) above the table, open.
2. **Both particle pages** (the queue item page and the plain ``/particle/`` page) put the
   verdict controls and the properties in one column beside the image, controls first.
3. **The stylesheet** makes ``.detail`` a two-column grid on a desktop-width window, falling
   back to one column below 900 px. The image's true-aspect rules are checked separately, by
   ``test_triage_image_true_aspect``.

The fixture is the habit-order test's: three flights, ten items in a mixed draw.
"""

from __future__ import annotations

import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path

from tests import test_triage_habit_order as hab
from tests.test_triage_server import HAVE_MPL, netCDF4

from arrayprobe import triage_server as ts

if HAVE_MPL and netCDF4 is not None:
    from http.server import ThreadingHTTPServer

    from arrayprobe.triage_server import TriageServer

QUEUE = "layout"


def _css_rule(selector: str, css: str) -> str:
    """The first rule for ``selector`` in ``css``, whitespace removed."""
    m = re.search(r"(?<![\w-])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no CSS rule for {selector!r}"
    return re.sub(r"\s+", "", m.group(1))


def _top_level_tracks(value: str) -> list[str]:
    """A ``grid-template-columns`` value split into its tracks, parentheses kept whole."""
    tracks, depth, cur = [], 0, ""
    for ch in value.strip():
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                tracks.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        tracks.append(cur)
    return tracks


class TheStylesheetPutsTheControlsBesideTheImage(unittest.TestCase):

    def test_detail_is_a_two_column_grid_at_desktop_width(self):
        m = re.search(r"(?<![\w-])\.detail\s*\{([^}]*)\}", ts.STYLE)
        self.assertIsNotNone(m, "no .detail rule")
        rule = m.group(1)
        self.assertRegex(rule, r"display\s*:\s*grid")
        cols = re.search(r"grid-template-columns\s*:\s*([^;]+);", rule)
        self.assertIsNotNone(cols, ".detail declares no grid-template-columns")
        self.assertEqual(len(_top_level_tracks(cols.group(1))), 2, cols.group(1))

    def test_a_narrow_window_falls_back_to_one_column(self):
        m = re.search(r"@media\s*\(\s*max-width\s*:\s*(\d+)px\s*\)\s*\{(.*?\})\s*\}",
                      ts.STYLE, re.S)
        self.assertIsNotNone(m, "no max-width media query")
        self.assertLessEqual(int(m.group(1)), 900)
        inner = _css_rule(".detail", m.group(2))
        cols = re.search(r"grid-template-columns:([^;]+)", inner)
        self.assertIsNotNone(cols)
        self.assertEqual(len(_top_level_tracks(cols.group(1))), 1, cols.group(1))

    def test_the_rest_sits_under_the_image_in_the_left_column(self):
        """``.detail-more`` takes the cell under the image; the controls span both rows."""
        areas = re.search(r'grid-template-areas:([^;]+)', _css_rule(".detail", ts.STYLE))
        self.assertIsNotNone(areas)
        self.assertEqual(areas.group(1), '"figside""moreside"')
        self.assertIn("grid-area:more", _css_rule(".detail-more", ts.STYLE))

    def test_the_text_above_the_image_wraps_to_the_image_width(self):
        """Author, 2026-10-06: the text above the particle image wraps within the image's
        width, so the figure does not widen and the controls stay in one frame. Every
        non-image child of ``.pimg`` (the properties block is one) contributes no width of
        its own and breaks long words."""
        rule = _css_rule(".pimg > :not(img)", ts.STYLE)
        self.assertIn("contain:inline-size", rule)
        self.assertIn("overflow-wrap:anywhere", rule)
        self.assertRegex(ts.STYLE, r"\.pimg\s*\{[^}]*min-width:0")

    def test_the_figure_is_as_wide_as_its_image_not_its_column(self):
        """The left column also holds .detail-more, which can widen it to 640px; the figure
        must shrink to its image (fit-content, not stretched) so the text wraps to the image."""
        self.assertRegex(ts.STYLE, r"\.pimg\s*\{[^}]*\swidth:fit-content[^}]*justify-self:start")

    def test_a_tall_particle_puts_what_was_under_the_figure_beside_it(self):
        """Author, 2026-10-06: when the particle image is tall, the content below the figure
        goes to the side, so the page is no taller than the figure. At desktop width the
        figure spans both rows and .detail-more takes the right-hand column's lower cell."""
        m = re.search(r"@media\s*\(\s*min-width\s*:\s*(\d+)px\s*\)\s*\{(.*?\})\s*\}",
                      ts.STYLE, re.S)
        self.assertIsNotNone(m, "no min-width media query for the tall layout")
        self.assertGreater(int(m.group(1)), 900)
        areas = re.search(r"grid-template-areas:([^;]+)", _css_rule(".detail.tall", m.group(2)))
        self.assertIsNotNone(areas)
        self.assertEqual(areas.group(1), '"figside""figmore"')

    def test_tall_means_more_slices_than_diodes(self):
        self.assertTrue(ts.is_tall_particle({"image_length": 256, "image_width": 89}))
        self.assertFalse(ts.is_tall_particle({"image_length": 40, "image_width": 89}))
        self.assertFalse(ts.is_tall_particle({"image_length": 256}))
        self.assertFalse(ts.is_tall_particle({"image_length": "x", "image_width": 0}))


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class ThePagesPutWhatTheReviewerNeedsOnOneScreen(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        for flight, letters in hab.HABITS.items():
            hab._make_flight(cls.dir, flight, letters)
        cls.items = [{"flight": f, "particle_index": i} for f, i in hab.DRAW]
        TriageServer.decoded_dir = cls.dir
        TriageServer.queues = {QUEUE: cls.items}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TriageServer)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()
        TriageServer.queues = {}

    def _get(self, path: str) -> str:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200, body[:400])
        return body

    # -- the queue page ---------------------------------------------------------------------

    def test_the_field_guide_is_above_the_table_and_open(self):
        page = self._get(f"/queue/{QUEUE}")
        guide = page.find("id='field-guide'")
        table = page.find('<table class="flights">')
        self.assertGreaterEqual(guide, 0, "no field guide on the queue page")
        self.assertGreaterEqual(table, 0, "no table on the queue page")
        self.assertLess(guide, table, "the field guide is below the table")
        self.assertRegex(page[guide - 40:guide + 40], r"<details[^>]*\bopen\b")

    # -- the particle pages -----------------------------------------------------------------

    def _side(self, page: str) -> tuple[str, str]:
        """``(before, side)``: the ``.detail`` block up to its right-hand column, and the
        column itself up to the page's script."""
        d = page.find('<div class="detail')
        self.assertGreaterEqual(d, 0, "no .detail block")
        s = page.find('class="detail-side"', d)
        self.assertGreaterEqual(s, 0, "no right-hand column in .detail")
        end = page.find("<script>", s)
        return page[d:s], page[s:end]

    def _assert_controls_beside_image(self, page: str, *, skip: bool) -> None:
        before, side = self._side(page)
        self.assertIn("class=\"pimg\"", before, "the image is not left of the column")
        button = side.find("<button class='verdict")
        kv = side.find('class="kv"')
        self.assertGreaterEqual(button, 0, "the verdict buttons are not in the column")
        self.assertGreaterEqual(kv, 0, "the properties are not in the column")
        self.assertLess(button, kv, "the properties come before the buttons")
        self.assertIn("<button class='phase", side)
        self.assertIn("id='comment'", side)
        if skip:
            self.assertIn('id="skip"', side)
        # Author, 2026-10-02: from the size-distribution note down, the properties
        # sit under the image in the left column, after the controls in the page's order.
        more = side.find('class="detail-more"')
        self.assertGreater(more, kv, "no block under the image after the column")
        self.assertLess(side.find("Automatic reject code"), more)
        self.assertGreater(side.find("What the reject code did"), more)
        self.assertGreater(side.find("size distribution"), more)
        self.assertGreater(side.find("Separate pieces of shadow"), more)

    def test_the_queue_item_page_puts_buttons_then_properties_beside_the_image(self):
        self._assert_controls_beside_image(self._get(f"/queue/{QUEUE}/0"), skip=True)

    def test_the_plain_particle_page_does_the_same(self):
        self._assert_controls_beside_image(self._get("/particle/fA/1"), skip=False)

    def _assert_gap_row_placement(self, path: str) -> None:
        """A tall particle's gap choice sits in the right-hand column, after the verdict
        buttons; a short one's stays under the image, in the figure."""
        saved = ts.TALL_ASPECT
        try:
            ts.TALL_ASPECT = 0.0        # every fixture particle is tall
            page = self._get(path)
            before, side = self._side(page)
            self.assertIn('<div class="detail tall">', page)
            self.assertNotIn("id='gap-row'", before, "the gap choice is still under the image")
            g = side.find("id='gap-row'")
            self.assertGreaterEqual(g, 0, "the gap choice is not in the side column")
            self.assertGreater(g, side.find("<button class='verdict"))
            self.assertIn("id='gap-row'", side[:side.find('class="detail-more"')])
            ts.TALL_ASPECT = 1e9        # no fixture particle is tall
            page = self._get(path)
            before, side = self._side(page)
            self.assertIn('<div class="detail">', page)
            self.assertIn("id='gap-row'", before)
            self.assertNotIn("id='gap-row'", side)
        finally:
            ts.TALL_ASPECT = saved

    def test_a_tall_particle_has_its_gap_choice_beside_the_image(self):
        self._assert_gap_row_placement("/particle/fA/1")

    def test_a_tall_queue_item_has_its_gap_choice_beside_the_image(self):
        self._assert_gap_row_placement(f"/queue/{QUEUE}/0")


if __name__ == "__main__":
    unittest.main()
