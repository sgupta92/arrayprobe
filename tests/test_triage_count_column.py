# SPDX-License-Identifier: BSD-3-Clause
"""Particle-count class on the queue index: the one / two / three-or-more class shows as a
"Particles" column and ``?count=`` narrows the rows. Display only; no computed number reads it.

Built on ``test_triage_landing``'s stand-in, with the per-item classes patched in, so the
server-rendered HTML is asserted without a decoded flight.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_triage_landing import _Pages

from arrayprobe import triage_server as ts

FLIGHT = "base180215125340"
NAME = "count-check"
CLASSES = ["one", "two", "three_or_more", None]


class CountFilterUnits(unittest.TestCase):
    def test_count_filter_accepts_only_the_three_classes(self):
        self.assertEqual(ts.count_filter({"count": ["two"]}), "two")
        self.assertEqual(ts.count_filter({"count": ["three_or_more"]}), "three_or_more")
        self.assertIsNone(ts.count_filter({"count": ["2"]}))
        self.assertIsNone(ts.count_filter({}))

    def test_keep_by_count(self):
        view = [0, 1, 2, 3]
        self.assertEqual(ts.keep_by_count(view, CLASSES, None), view)
        self.assertEqual(ts.keep_by_count(view, CLASSES, "two"), [1])
        self.assertEqual(ts.keep_by_count(view, CLASSES, "three_or_more"), [2])

    def test_class_html_and_bar(self):
        self.assertIn(">3+<", ts.count_class_html("three_or_more"))
        self.assertIn("three or more particles", ts.count_class_html("three_or_more"))
        bar = ts.count_filter_bar("/queue/x", "one")
        self.assertIn("<b>one particle</b>", bar)
        self.assertIn("/queue/x?count=two", bar)
        self.assertIn("&count=two", ts.count_filter_bar("/queue/x?order=file", None))


class QueueIndexColumn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        items = [{"flight": FLIGHT, "particle_index": i, "note": ""} for i in range(4)]
        self.qf = self.dir / "q.json"
        self.qf.write_text(json.dumps({NAME: items}), encoding="utf-8")
        patch = mock.patch.object(ts, "_queue_count_classes", return_value=list(CLASSES))
        patch.start()
        self.addCleanup(patch.stop)

    def _render(self, want=None) -> str:
        return _Pages(self.dir, self.qf)._render_queue_index(
            NAME, "file", None, want).decode()

    def test_the_index_shows_a_particles_column_with_each_class(self):
        page = self._render()
        self.assertIn("<th>Particles</th>", page)
        for short in (">1<", ">2<", ">3+<"):
            self.assertIn(short, page)
        self.assertIn("?count=three_or_more", page)

    def test_count_narrows_the_rows(self):
        page = self._render("two")
        self.assertIn(f"{FLIGHT} #1</a>", page)
        for i in (0, 2, 3):
            self.assertNotIn(f"{FLIGHT} #{i}</a>", page)
        self.assertIn("<b>two particles</b>", page)


if __name__ == "__main__":
    unittest.main()
