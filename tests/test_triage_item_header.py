# SPDX-License-Identifier: BSD-3-Clause
"""A queue item page says where the reviewer is, what is already stored, and how to move on.

The header reads "Item 4 of 10 · 2 labelled · group 2 of 6: Columns and needles", counted in
the order the page is walked: habit groups by default, the file order under ``?order=file``
(which names no group). A particle that already has a label opens with the status line
saying so in words, "Labelled real · ice · 14:02:11 UTC", the time being the record's own.
"Skip (leave unlabelled)" goes to the next item in the walked order without saving, and the
particle's record strip is one link away, as on the plain particle page.

The fixture is the habit-order test's: three flights, ten items in a mixed draw.
"""

from __future__ import annotations

import html
import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from tests import test_triage_habit_order as hab
from tests.test_triage_server import HAVE_MPL, netCDF4

if HAVE_MPL and netCDF4 is not None:
    from http.server import ThreadingHTTPServer

    from arrayprobe.triage_server import (
        TriageServer,
        _labelled_text,
        _with_labelled_status,
    )

QUEUE = "item-header"
#: Two stored labels: fA #1 is file position 1 (first in the habit view), fA #0 is
#: position 3 (habit "a", seventh in the habit view).
STORED = {
    "1": {"verdict": "real", "phase": "ice", "at": "2026-10-01T14:02:11+00:00"},
    "0": {"verdict": "mixed", "at": "2026-10-01T09:15:00+00:00"},
}


def _text(fragment: str) -> str:
    """A page fragment as a reader sees it: tags dropped, entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class ItemHeaderTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        for flight, letters in hab.HABITS.items():
            hab._make_flight(cls.dir, flight, letters)
        store = cls.dir / "triage_verdicts"
        store.mkdir()
        (store / "fA.json").write_text(json.dumps(STORED), encoding="utf-8")
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

    def _header(self, page: str) -> str:
        m = re.search(r'id="item-header">(.*?)</p>', page, re.S)
        self.assertIsNotNone(m, "no item header on the page")
        return _text(m.group(1))

    def _status(self, page: str) -> str:
        m = re.search(r"id='status'[^>]*>(.*?)</div>", page, re.S)
        self.assertIsNotNone(m, "no status line on the page")
        return _text(m.group(1))

    def _skip(self, page: str) -> str | None:
        m = re.search(r'<a id="skip" data-skip href="([^"]*)">Skip \(leave unlabelled\)</a>',
                      page)
        return m.group(1) if m else None

    # -- header ---------------------------------------------------------------------------

    def test_header_counts_in_the_habit_order_and_names_the_group(self):
        self.assertEqual(self._header(self._get(f"/queue/{QUEUE}/1")),
                         "Item 1 of 10 · 2 labelled · group 1 of 6: Round and tiny")
        # Position 2 (habit "l") is the fourth page of the grouped walk.
        self.assertEqual(self._header(self._get(f"/queue/{QUEUE}/2")),
                         "Item 4 of 10 · 2 labelled · group 2 of 6: Columns and needles")
        # Position 9 has no habit: the last group, the last page.
        self.assertEqual(self._header(self._get(f"/queue/{QUEUE}/9")),
                         "Item 10 of 10 · 2 labelled · group 6 of 6: No shape")

    def test_header_counts_in_the_file_order_when_asked_and_names_no_group(self):
        self.assertEqual(self._header(self._get(f"/queue/{QUEUE}/4?order=file")),
                         "Item 5 of 10 · 2 labelled")

    # -- the stored label, on load --------------------------------------------------------

    def test_a_labelled_particle_opens_saying_so_in_words(self):
        self.assertEqual(self._status(self._get(f"/queue/{QUEUE}/1")),
                         "Labelled real · ice · 14:02:11 UTC")
        self.assertEqual(self._status(self._get(f"/queue/{QUEUE}/3")),
                         "Labelled two particles · phase not set · 09:15:00 UTC")

    def test_an_unlabelled_particle_opens_with_an_empty_status_line(self):
        page = self._get(f"/queue/{QUEUE}/4")
        self.assertEqual(self._status(page), "")
        self.assertNotIn("Labelled ", page)

    def test_the_plain_particle_page_shows_the_stored_label_too(self):
        self.assertEqual(self._status(self._get("/particle/fA/1")),
                         "Labelled real · ice · 14:02:11 UTC")

    # -- skip, the record strip, the keys ---------------------------------------------------

    def test_skip_goes_to_the_next_item_in_the_walked_order(self):
        page = self._get(f"/queue/{QUEUE}/1")
        self.assertEqual(self._skip(page), f"/queue/{QUEUE}/4")
        self.assertEqual(self._skip(self._get(f"/queue/{QUEUE}/1?order=file")),
                         f"/queue/{QUEUE}/2?order=file")
        # The last page of the walk has no next item: skip returns to the index.
        self.assertEqual(self._skip(self._get(f"/queue/{QUEUE}/9")), f"/queue/{QUEUE}")

    def test_skip_saves_nothing_and_is_not_a_keyboard_nav_link(self):
        page = self._get(f"/queue/{QUEUE}/9")
        self.assertNotIn("data-nav='next'", page)    # the last item still has no next link
        skip = re.search(r'<a id="skip"[^>]*>', page).group(0)
        self.assertNotIn("data-nav", skip)
        self.assertNotIn("onclick", skip)

    def test_the_queue_item_page_links_the_particles_record_strip(self):
        page = self._get(f"/queue/{QUEUE}/1")
        self.assertIn("href='/strip/fA?rec=0'", page)

    def test_the_first_item_keeps_every_key_and_says_no_previous(self):
        page = self._get(f"/queue/{QUEUE}/1")
        self.assertNotIn("previous", page)
        for key in "artuidq":
            self.assertIn(f"data-key='{key}'", page)
        self.assertIn("<kbd>n</kbd> next", page)
        self.assertIn("<kbd>p</kbd> prev", page)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class LabelledTextTests(unittest.TestCase):

    def test_no_verdict_says_nothing(self):
        self.assertEqual(_labelled_text(None), "")
        self.assertEqual(_labelled_text({"phase": "ice"}), "")

    def test_words_not_tokens_and_no_time_when_the_record_has_none(self):
        self.assertEqual(_labelled_text({"verdict": "unsure", "phase": "unsure"}),
                         "Labelled unsure · phase unsure")

    def test_a_widget_without_the_status_line_still_shows_the_label(self):
        out = _with_labelled_status("<div>buttons</div>", {"verdict": "artifact"})
        self.assertIn("Labelled artifact · phase not set", out)
        self.assertTrue(out.endswith("<div>buttons</div>"))


if __name__ == "__main__":
    unittest.main()
