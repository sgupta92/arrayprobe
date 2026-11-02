# SPDX-License-Identifier: BSD-3-Clause
"""A blind re-check queue's index, progress and resume link read re-check labels, not the first.

The particle page of a re-check queue shows only the re-check store
(``<flight>.recheck.json``), so the reviewer labels each particle again without seeing the
first verdict. Until 2026-10-01 three other views read the FIRST store instead: the queue index
printed each particle's original verdict beside it (the blinding undone one click away), the
progress counter showed every item labelled before the re-check began, and the resume link used
the unresolved ``.H`` flight name, so it opened no file and always went to item 0. They now share
``TriageServer._queue_verdicts`` with the particle page; these tests build the pages on a
stand-in with only the attributes those methods read, so no server or image file is needed.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe.triage_server import RECHECK_PREFIX, TriageServer, _save_verdict

FLIGHT = "base180215125340"
RECHECK = f"{RECHECK_PREFIX}cold"
FIRST = "iop2-cold"
#: How the index marks a stored "artifact" verdict in an item's row (the page's fixed markup
#: names the verdicts too, so the bare word is not evidence).
ARTIFACT_MARK = "<b style='color:var(--bad)'>artifact</b>"


class _Pages:
    """The attributes the queue views read, and the real methods under test."""

    _queue_verdicts = TriageServer._queue_verdicts
    _queue_progress = TriageServer._queue_progress
    _render_queue_index = TriageServer._render_queue_index

    def __init__(self, decoded_dir: Path, queues: dict[str, list[dict]]):
        self.decoded_dir = decoded_dir
        self.queues = queues

    def _flights(self) -> dict[str, dict]:
        # The probe is what lets the queue's explicit ".H" name resolve to the bare stem.
        return {FLIGHT: {"probe": "2DS"}}


class TheRecheckQueueStaysBlind(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        # The queue names the explicit channel, as draw scripts write it.
        items = [{"flight": f"{FLIGHT}.H", "particle_index": i} for i in (11, 12, 13)]
        self.pages = _Pages(self.dir, {RECHECK: items, FIRST: items})
        for i in (11, 12, 13):  # the first pass labelled everything "artifact"
            _save_verdict(self.dir, FLIGHT, i, "artifact", source="human", queue=FIRST,
                          reviewer="test")
        # the re-check has labelled one particle so far
        _save_verdict(self.dir, FLIGHT, 11, "real", source="human", queue=RECHECK, reviewer="test")

    def test_the_index_shows_no_first_pass_verdict(self):
        page = self.pages._render_queue_index(RECHECK).decode("utf-8")
        self.assertNotIn(ARTIFACT_MARK, page)
        self.assertIn("<b style='color:var(--accent)'>real</b>", page)

    def test_progress_counts_only_re_check_labels(self):
        self.assertEqual(self.pages._queue_progress(RECHECK, self.pages.queues[RECHECK]), (1, 3))

    def test_resume_goes_to_the_first_item_the_re_check_has_not_labelled(self):
        page = self.pages._render_queue_index(RECHECK).decode("utf-8")
        self.assertIn(f'href="/queue/{RECHECK}/1"', page)

    def test_the_first_pass_queue_still_reads_the_first_store(self):
        self.assertEqual(self.pages._queue_progress(FIRST, self.pages.queues[FIRST]), (3, 3))
        page = self.pages._render_queue_index(FIRST).decode("utf-8")
        self.assertEqual(page.count(ARTIFACT_MARK), 3)


if __name__ == "__main__":
    unittest.main()
