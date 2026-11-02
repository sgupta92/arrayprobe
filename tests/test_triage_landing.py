# SPDX-License-Identifier: BSD-3-Clause
"""The landing page says what the tool is, and each queue says what its labels decide.

The author: *"At the top of the landing page, have the name of the package and one line of
explanation of what this part of the work is for and does. Then for the specific review being
done in that instance - the importance and potential impact of the labeling."*

Every page is wrapped in a header naming the tool (linking home), a ``<main>`` and a footer
saying where labels are stored; the landing page's header adds the one-line purpose. A queue
file may carry an optional top-level ``_purpose`` (queue name -> text), shown under that
queue's title on ``/``, ``/queue``, its index and its item pages; a queue without an entry
shows nothing, and a file without the block loads exactly as before.

The pages are built on a stand-in with only the attributes the views read (as
``test_triage_queue_summary`` does), over temporary queue files.
"""
from __future__ import annotations

import html
import json
import re
import tempfile
import unittest
from pathlib import Path

from arrayprobe.triage_server import (
    PACKAGE_PURPOSE,
    TriageServer,
    _load_queue_file,
    _page,
    _queue_purposes,
    _review_queues,
)

FLIGHT = "base180215125340"
WITH = "iop2-cold"
WITHOUT = "iop2-plain"
PURPOSE = "Your labels decide whether the test fixture's ice is counted."
SHOWN = html.escape(PURPOSE)  # the apostrophe is escaped on the page


class _Pages:
    """The attributes the landing and queue views read, and the real methods under test."""

    _queue_verdicts = TriageServer._queue_verdicts
    _queue_progress = TriageServer._queue_progress
    _summary = TriageServer._summary
    _queue_progress_panel = TriageServer._queue_progress_panel
    _render_queue_list = TriageServer._render_queue_list
    _render_queue_index = TriageServer._render_queue_index
    _render_index = TriageServer._render_index
    _refused_panel = TriageServer._refused_panel
    _state_file_panel = TriageServer._state_file_panel
    accept_unstamped = False
    met = None

    def __init__(self, decoded_dir: Path, queue_file: Path):
        data = _load_queue_file(queue_file)
        self.decoded_dir = decoded_dir
        self.queues = _review_queues(data)
        self.purposes = _queue_purposes(data)

    def _flights(self) -> dict[str, dict]:
        return {}


def _main(page: str) -> str:
    m = re.search(r"<body>.*?<main>(.*)</main>", page, re.S)  # the CSS names <main> too
    assert m, "no <main> on the page"
    return m.group(1)


class Landing(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        items = [{"flight": f"{FLIGHT}.H", "particle_index": i} for i in range(3)]
        self.with_purpose = self.dir / "with.json"
        self.with_purpose.write_text(json.dumps(
            {"_purpose": {WITH: PURPOSE}, "_coverage": {"note": "metadata"},
             WITH: items, WITHOUT: items}), encoding="utf-8")
        self.old_style = self.dir / "old.json"
        self.old_style.write_text(json.dumps({WITH: items}), encoding="utf-8")

    def test_the_landing_page_links_the_run_page(self):
        main = _main(_Pages(self.dir, self.with_purpose)._render_index().decode())
        self.assertIn('<a href="/run">Run a flight</a>', main)

    def test_the_landing_page_opens_with_the_package_name_and_purpose_line(self):
        page = _Pages(self.dir, self.with_purpose)._render_index().decode()
        body = page.split("<body>", 1)[1]
        self.assertTrue(body.startswith("<header>"), body[:80])
        header = body.split("</header>", 1)[0]
        self.assertIn("arrayprobe", header)
        self.assertIn("<a href='/'>", header)
        self.assertIn(PACKAGE_PURPOSE, header)
        self.assertEqual(PACKAGE_PURPOSE,
                         "Look at individual optical-array-probe images and record whether "
                         "each is a real particle or an artefact, and its phase; labels are "
                         "stored beside the data and never change a processed number.")

    def test_every_page_has_header_main_and_the_storage_footer(self):
        page = _page("<p>x</p>", "t", decoded_dir=self.dir).decode()
        self.assertRegex(page, r"<body><header>.*</header><main><p>x</p></main><footer>")
        footer = page.split("<footer>", 1)[1]
        self.assertIn("never the port's own output", footer)
        self.assertIn("triage_verdicts", footer)
        # The purpose line is the landing page's, not every page's.
        self.assertNotIn(PACKAGE_PURPOSE, page)

    def test_the_storage_sentence_moved_out_of_the_landing_body(self):
        page = _Pages(self.dir, self.with_purpose)._render_index().decode()
        self.assertNotIn("never the port's own output", _main(page))
        self.assertIn("never the port's own output", page.split("</main>", 1)[1])

    def test_the_style_caps_main_not_a_wrapped_body(self):
        page = _page("", decoded_dir=self.dir).decode()
        self.assertIn("main { max-width:1180px;", page)
        self.assertIn("body:has(> main) { max-width:none;", page)

    def test_a_queue_purpose_shows_on_the_landing_page_and_queue_list(self):
        pages = _Pages(self.dir, self.with_purpose)
        for page in (pages._render_index().decode(), pages._render_queue_list().decode()):
            self.assertEqual(_main(page).count(SHOWN), 1)
            self.assertEqual(_main(page).count("class='purpose'"), 1)  # WITHOUT shows none

    def test_a_queue_purpose_shows_on_its_index_and_not_on_another(self):
        pages = _Pages(self.dir, self.with_purpose)
        self.assertIn(SHOWN, _main(pages._render_queue_index(WITH).decode()))
        page = _main(pages._render_queue_index(WITHOUT).decode())
        self.assertNotIn(SHOWN, page)
        self.assertNotIn("class='purpose'", page)

    def test_metadata_keys_are_never_queues(self):
        pages = _Pages(self.dir, self.with_purpose)
        self.assertEqual(sorted(pages.queues), sorted([WITH, WITHOUT]))

    def test_a_file_without_purpose_loads_unchanged_and_shows_none(self):
        data = _load_queue_file(self.old_style)
        self.assertEqual(data, json.loads(self.old_style.read_text(encoding="utf-8")))
        self.assertEqual(_queue_purposes(data), {})
        pages = _Pages(self.dir, self.old_style)
        self.assertNotIn("class='purpose'", _main(pages._render_index().decode()))

    def test_a_malformed_purpose_block_is_refused(self):
        bad = self.dir / "bad.json"
        bad.write_text(json.dumps({"_purpose": ["not", "a", "map"], WITH: []}),
                       encoding="utf-8")
        with self.assertRaises(ValueError):
            _load_queue_file(bad)


if __name__ == "__main__":
    unittest.main()
