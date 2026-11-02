# SPDX-License-Identifier: BSD-3-Clause
"""Particle-count class on the flight page: ``?count=`` narrows the page to one of the one / two /
three-or-more classes and labels each card with its class. Display only; no computed
number reads it.

The flight's files are patched out, so the server-rendered HTML is asserted without a
decoded flight.
"""
from __future__ import annotations

import unittest
from unittest import mock

from arrayprobe import triage_server as ts

FLIGHT = "base180215125340"
CLASSES = {0: "one", 1: "two", 2: "three_or_more"}


class _FlightPage:
    _render_flight = ts.TriageServer._render_flight
    decoded_dir = "unused"

    def _flights(self) -> dict[str, dict]:
        return {FLIGHT: {"image": "img", "proc": "proc", "probe": "2DS"}}


class FlightPageCountFilter(unittest.TestCase):
    def setUp(self):
        self.counted = []

        def fake_classes(paths, indices):
            self.counted.append(list(indices))
            return {i: CLASSES[i] for i in indices if i in CLASSES}

        for name, value in (("_load_verdicts", mock.Mock(return_value={})),
                            ("_selected_particles", mock.Mock(return_value=[0, 1, 2, 3])),
                            ("_flight_index", mock.Mock(return_value=None)),
                            ("_flight_overview_html", mock.Mock(return_value="")),
                            ("_count_classes", fake_classes)):
            patch = mock.patch.object(ts, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def _render(self, want=None) -> str:
        return _FlightPage()._render_flight(FLIGHT, "accepted", 1, want_count=want).decode()

    def test_default_page_counts_nothing_and_offers_the_filter(self):
        page = self._render()
        self.assertEqual(self.counted, [])
        for i in range(4):
            self.assertIn(f"<div>#{i}</div>", page)
        self.assertIn(f"/flight/{FLIGHT}?group=accepted&amp;page=1&count=two".replace(
            "&amp;", "&"), page)
        self.assertIn("count=three_or_more", page)

    def test_count_narrows_the_page_and_labels_each_card(self):
        page = self._render("two")
        self.assertEqual(self.counted, [[0, 1, 2, 3]])
        self.assertIn("<div>#1</div>", page)
        for i in (0, 2, 3):
            self.assertNotIn(f"<div>#{i}</div>", page)
        self.assertIn("<b>two particles</b>", page)
        self.assertIn("<span class='count-class'", page)
        self.assertIn(">2</span>", page)

    def test_the_route_passes_count_through(self):
        self.assertEqual(ts.count_filter({"count": ["three_or_more"]}), "three_or_more")
        page = self._render("three_or_more")
        self.assertIn("<div>#2</div>", page)
        self.assertIn(">3+</span>", page)


if __name__ == "__main__":
    unittest.main()
