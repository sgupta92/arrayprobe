# SPDX-License-Identifier: BSD-3-Clause
"""A review queue's labels are summarised where its progress is shown.

The author: *"once labeled, the main review queue page should provide a summary of the
labeling (number of real, artifact, etc)."* The front page's queue panel, the queue list
(``/queue``) and each queue's own index show a stacked bar of the verdict counts (real,
artifact, two particles, unsure, left, in that order, in the verdict colours) and the same
counts in words, with the phase counts after them. Before, each showed only ``labelled / n``.

The pages are built on a stand-in with only the attributes the queue views read (as
``test_triage_recheck_stays_blind`` does), over a temporary verdict store: five items, of
which two are real (one ice), one artifact, one two particles and one unlabelled.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from arrayprobe.triage_server import (
    RECHECK_PREFIX,
    STYLE,
    TriageServer,
    _queue_summary,
    _save_verdict,
)

FLIGHT = "base180215125340"
QUEUE = "iop2-cold"
RECHECK = f"{RECHECK_PREFIX}cold"
TEXT = ("2 real · 1 artifact · 1 two particles · 0 unsure · 1 left; "
        "phase 1 ice · 0 drizzle · 0 phase unsure · 4 not set")


class _Pages:
    """The attributes the queue views read, and the real methods under test."""

    _queue_verdicts = TriageServer._queue_verdicts
    _queue_progress = TriageServer._queue_progress
    _summary = TriageServer._summary
    _queue_progress_panel = TriageServer._queue_progress_panel
    _render_queue_list = TriageServer._render_queue_list
    _render_queue_index = TriageServer._render_queue_index

    def __init__(self, decoded_dir: Path, queues: dict[str, list[dict]]):
        self.decoded_dir = decoded_dir
        self.queues = queues

    def _flights(self) -> dict[str, dict]:
        return {FLIGHT: {"probe": "2DS"}}


def _segments(page: str) -> list[tuple[str, str, str]]:
    """``(verdict key, width, title)`` of every bar segment, in page order."""
    return re.findall(r"<span class='s-(\w+)' style='width:([\d.]+)%' title='([^']*)'>", page)


class QueueSummary(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        # The queue names the explicit channel, as draw scripts write it.
        items = [{"flight": f"{FLIGHT}.H", "particle_index": i} for i in range(5)]
        self.pages = _Pages(self.dir, {QUEUE: items, RECHECK: items})
        for i, verdict in enumerate(("real", "real", "artifact", "mixed")):
            _save_verdict(self.dir, FLIGHT, i, verdict, source="human", queue=QUEUE,
                          phase="ice" if i == 0 else None, reviewer="test")

    def test_the_counts_come_from_the_queue_lookup(self):
        s = _queue_summary(QUEUE, self.pages.queues[QUEUE], self.pages._flights(),
                           self.pages._queue_verdicts)
        self.assertEqual(s["n"], 5)
        self.assertEqual(s["labelled"], 4)
        self.assertEqual(s["verdicts"], {"real": 2, "artifact": 1, "mixed": 1, "unsure": 0,
                                         "other": 0, "left": 1})
        self.assertEqual(s["phases"], {"ice": 1, "drizzle": 0, "unsure": 0, "not_set": 4})

    def test_the_front_page_panel_shows_the_summary(self):
        page = self.pages._queue_progress_panel()
        self.assertIn(TEXT, page)
        self.assertIn("4 / 5", page)

    def test_the_queue_list_shows_the_summary(self):
        page = self.pages._render_queue_list().decode("utf-8")
        self.assertIn(TEXT, page)
        self.assertIn("4 / 5 labeled", page)

    def test_the_queue_index_opens_with_the_summary(self):
        page = self.pages._render_queue_index(QUEUE).decode("utf-8")
        self.assertIn(TEXT, page)
        self.assertLess(page.index(TEXT), page.index("<table class=\"flights\">"),
                        "the summary belongs above the queue's table")

    def test_the_bar_widths_are_the_shares_in_verdict_order(self):
        page = self.pages._render_queue_index(QUEUE).decode("utf-8")  # one queue, one bar
        segs = _segments(page)
        self.assertEqual([(k, w) for k, w, _ in segs],
                         [("real", "40.00"), ("artifact", "20.00"), ("mixed", "20.00"),
                          ("left", "20.00")])
        self.assertEqual(segs[0][2], "2 real (40.0% of 5)")
        self.assertEqual(segs[2][2], "1 two particles (20.0% of 5)")

    def test_words_never_the_stored_tokens(self):
        for page in (self.pages._queue_progress_panel(),
                     self.pages._render_queue_list().decode("utf-8")):
            text = re.sub(r"<[^>]*>", " ", page)
            self.assertNotRegex(text, r"\b\d+ mixed\b")
            self.assertNotIn("not_set", text)

    def test_each_segment_colour_is_a_verdict_colour_token(self):
        for key, token in (("real", "--accent"), ("artifact", "--bad"),
                           ("mixed", "--muted"), ("unsure", "--amber"), ("left", "--line")):
            self.assertRegex(STYLE, rf"\.sbar \.s-{key} \{{ background:var\({token}\); \}}")
        # The tokens are redefined for dark mode, so the bar follows the theme.
        dark = STYLE[STYLE.index("prefers-color-scheme: dark"):]
        for token in ("--accent:", "--bad:", "--muted:", "--amber:", "--line:"):
            self.assertIn(token, dark)

    def test_a_recheck_queue_summary_counts_only_its_own_labels(self):
        _save_verdict(self.dir, FLIGHT, 4, "unsure", source="human", queue=RECHECK, reviewer="test")
        page = self.pages._render_queue_index(RECHECK).decode("utf-8")
        self.assertIn("0 real · 0 artifact · 0 two particles · 1 unsure · 4 left", page)
        self.assertNotIn(TEXT, page)


if __name__ == "__main__":
    unittest.main()
