# SPDX-License-Identifier: BSD-3-Clause
"""A review queue is shown grouped by habit, as a view over its file order.

The requirement is *"similar habits classified together and shown in sequence once randomly
selected"*. The queue file's order is the random draw and stays the record: grouping only
changes the order the index lists and the order previous/next walk. Each item keeps its file
position, so its URL ``/queue/<name>/<pos>`` and its stored label do not move. Each habit is
read from the flight's own product (``holroyd_habit``), once per flight, and a particle with
no habit falls in the last group, "No shape". ``?order=file`` restores the file order.

The fixture is three flights, ten items, drawn in a deliberately mixed order.
"""

from __future__ import annotations

import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from tests.test_triage_server import (
    HAVE_MPL,
    _make_image_file,
    _make_proc_file,
    netCDF4,
)

if HAVE_MPL and netCDF4 is not None:
    from http.server import ThreadingHTTPServer

    from arrayprobe import triage_server
    from arrayprobe.triage_server import (
        HABIT_GROUPS,
        TriageServer,
        _discover_flights,
        _queue_habits,
        _queue_order,
    )

QUEUE = "habit-order"
#: Each flight's particles' habit letters, by particle index; "\x00" is a stored 0 (no habit).
HABITS = {"fA": ["a", "s", "l"], "fB": ["i", "t", "M"], "fC": ["d", "s", "o", "\x00"]}
#: The queue in file order (the random draw), as (flight, particle_index).
DRAW = [("fB", 0), ("fA", 1), ("fC", 2), ("fA", 0), ("fB", 1),
        ("fC", 0), ("fB", 2), ("fA", 2), ("fC", 1), ("fC", 3)]
#: Habit order: group 1 (s, t) at positions 1, 4, 8; group 2 (l, o) at 2, 7; group 3 (h, d)
#: at 5; group 4 (a, g) at 3; group 5 (i) at 0; group 6 (M, C, missing) at 6, 9.
HABIT_VIEW = [1, 4, 8, 2, 7, 5, 3, 0, 6, 9]


def _make_flight(decoded_dir: Path, flight: str, letters: list[str]) -> None:
    block = np.zeros((1700, 8), dtype=np.uint16)
    block[0:3, :] = 65535
    _make_image_file(decoded_dir / f"{flight}.H.cdf", [block])
    _make_proc_file(
        decoded_dir / f"proc.{flight}.H.nc",
        [{"parent_rec_num": 0, "start": 0, "end": 2, "width": 8, "length": 3,
          "habit": letter, "particle_num": k + 1} for k, letter in enumerate(letters)],
    )


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class HabitOrderTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        for flight, letters in HABITS.items():
            _make_flight(cls.dir, flight, letters)
        cls.items = [{"flight": f, "particle_index": i} for f, i in DRAW]
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

    def _row_positions(self, page: str) -> list[int]:
        return [int(p) for p in re.findall(rf"<td><a href='/queue/{QUEUE}/(\d+)", page)]

    def _nav(self, page: str, which: str) -> str | None:
        m = re.search(rf"data-nav='{which}' href='([^']*)'", page)
        return m.group(1) if m else None

    def test_index_lists_groups_in_order_and_file_order_inside_each(self):
        page = self._get(f"/queue/{QUEUE}")
        self.assertEqual(self._row_positions(page), HABIT_VIEW)
        heads = [page.index(f"{group} <span") for group, _ in HABIT_GROUPS]
        self.assertEqual(heads, sorted(heads), "group headings out of order")
        self.assertIn("Round and tiny <span class='muted'>(3)</span>", page)
        self.assertIn("No shape <span class='muted'>(2)</span>", page)

    def test_order_file_is_the_file_order_and_has_no_group_headings(self):
        page = self._get(f"/queue/{QUEUE}?order=file")
        self.assertEqual(self._row_positions(page), list(range(len(DRAW))))
        self.assertNotIn("habit-group", page)
        self.assertIn(f"href='/queue/{QUEUE}/4?order=file'", page)

    def test_an_unknown_order_falls_back_to_habit_order(self):
        page = self._get(f"/queue/{QUEUE}?order=nonsense")
        self.assertEqual(self._row_positions(page), HABIT_VIEW)

    def test_habit_column_shows_the_word_with_the_letter_small(self):
        page = self._get(f"/queue/{QUEUE}")
        self.assertIn("sphere</span> <small class='muted'>s</small>", page)
        self.assertIn("linear</span> <small class='muted'>l</small>", page)

    def test_positions_and_urls_are_unchanged(self):
        # Position 4 is still fB #1 (the file's fifth item), whatever the view; the
        # header counts in the walked order, so it is the second page of the grouped walk.
        for suffix, header in (("", "Item 2 of 10"), ("?order=file", "Item 5 of 10")):
            page = self._get(f"/queue/{QUEUE}/4{suffix}")
            self.assertIn("/image/fB/1.png", page)
            self.assertIn(header, page)
        page = self._get(f"/queue/{QUEUE}")
        self.assertRegex(page, rf"<td>4</td><td><a href='/queue/{QUEUE}/4'>fB #1</a>")

    def test_prev_next_follow_the_habit_order(self):
        page = self._get(f"/queue/{QUEUE}/4")
        self.assertEqual(self._nav(page, "prev"), f"/queue/{QUEUE}/1")
        self.assertEqual(self._nav(page, "next"), f"/queue/{QUEUE}/8")
        page = self._get(f"/queue/{QUEUE}/8")     # last of group 1, next crosses into group 2
        self.assertEqual(self._nav(page, "next"), f"/queue/{QUEUE}/2")
        page = self._get(f"/queue/{QUEUE}/1")     # first in the view
        self.assertIsNone(self._nav(page, "prev"))
        page = self._get(f"/queue/{QUEUE}/9")     # last in the view
        self.assertIsNone(self._nav(page, "next"))
        self.assertEqual(self._nav(page, "prev"), f"/queue/{QUEUE}/6")

    def test_prev_next_follow_the_file_order_when_asked(self):
        page = self._get(f"/queue/{QUEUE}/4?order=file")
        self.assertEqual(self._nav(page, "prev"), f"/queue/{QUEUE}/3?order=file")
        self.assertEqual(self._nav(page, "next"), f"/queue/{QUEUE}/5?order=file")
        page = self._get(f"/queue/{QUEUE}/9?order=file")
        self.assertIsNone(self._nav(page, "next"))

    def test_habits_are_read_from_the_product_once_per_flight_and_cached(self):
        flights = _discover_flights(self.dir)
        items = [dict(it) for it in self.items]          # a fresh list: no cached entry
        real = netCDF4.Dataset
        with mock.patch.object(triage_server.netCDF4, "Dataset",
                               side_effect=lambda *a, **k: real(*a, **k)) as opened:
            habits = _queue_habits("fresh", items, flights)
            # Per flight: one open for the file's letters, and the proc and image files once
            # each for the shape test re-run on the images -- never one per item.
            first = opened.call_count
            self.assertGreaterEqual(first, len(HABITS))
            self.assertLessEqual(first, 3 * len(HABITS))
            self.assertEqual(_queue_habits("fresh", items, flights), habits)
            self.assertEqual(opened.call_count, first, "second call reopened a file")
        expected = [HABITS[f][i] for f, i in DRAW]
        expected = [c if c != "\x00" else "" for c in expected]
        self.assertEqual(habits, expected)
        self.assertEqual(_queue_order(habits, "habit"), HABIT_VIEW)


if __name__ == "__main__":
    unittest.main()
