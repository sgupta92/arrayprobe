# SPDX-License-Identifier: BSD-3-Clause
"""The particle page's piece-gap choice, its shared button style and the reject code and air
temperature above the image (the gap-choice ruling)."""
from __future__ import annotations

import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
from tests.test_triage_server import (
    HAVE_MPL,
    _make_image_file,
    _make_proc_file,
    netCDF4,
)

if HAVE_MPL and netCDF4 is not None:
    from http.server import ThreadingHTTPServer

    from arrayprobe import triage_server as ts
    from arrayprobe.triage_server import TriageServer

QUEUE = "gapq"
FLIGHT = "fG"


def _make_two_droplet_flight(decoded_dir: Path) -> None:
    """One particle: two blobs 4 diodes apart across the array (word 0 all shadow, word 1
    0x0FF0), so the default gap of 8 joins them and gap 0 or 2 splits them."""
    block = np.zeros((1700, 8), dtype=np.uint16)
    block[0:3, 0] = 0xFFFF
    block[0:3, 1] = 0x0FF0
    _make_image_file(decoded_dir / f"{FLIGHT}.H.cdf", [block])
    _make_proc_file(decoded_dir / f"proc.{FLIGHT}.H.nc",
                    [{"parent_rec_num": 1, "start": 1, "end": 3, "width": 28, "length": 3,
                      "particle_num": 1}])


class GapOverrideParsing(unittest.TestCase):
    @unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
    def test_only_a_whole_number_in_range_overrides(self):
        self.assertEqual(ts.gap_override({"gap": ["2"]}), 2)
        self.assertEqual(ts.gap_override({"gap": ["0"]}), 0)
        for bad in (["x"], ["-1"], ["999"], [""]):
            self.assertIsNone(ts.gap_override({"gap": bad}), bad)
        self.assertIsNone(ts.gap_override({}))

    @unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
    def test_choice_links_keep_the_other_query_parameters(self):
        row = ts.gap_choice_html("/queue/q/3", {"order": ["file"], "gap": ["8"]}, 4)
        for g in ts.GAP_CHOICES:
            self.assertIn(f"order=file&amp;gap={g}", row)
        self.assertIn("class='gapchoice sel pbtn' href='/queue/q/3?order=file&amp;gap=4'", row)
        self.assertEqual(row.count(" sel "), 1)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class TheParticlePageOffersTheGap(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_two_droplet_flight(cls.dir)
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
        TriageServer.queues = {QUEUE: [{"flight": FLIGHT, "particle_index": 0}]}
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

    def setUp(self):
        self._clear_store()

    def _clear_store(self):
        store = self.dir / "triage_verdicts" / f"{FLIGHT}.json"
        if store.exists():
            store.write_text("{}", encoding="utf-8")

    def _get(self, path: str) -> str:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200, body[:400])
        return body

    def _pages(self, query: str = ""):
        return (self._get(f"/particle/{FLIGHT}/0{query}"),
                self._get(f"/queue/{QUEUE}/0{query}"))

    @staticmethod
    def _piece_buttons(page: str) -> int:
        return len(re.findall(r"<button type='button' class='two-p ", page))

    def test_the_gap_override_changes_the_number_of_piece_buttons(self):
        for page in self._pages():
            self.assertEqual(self._piece_buttons(page), 0, "gap 8 should join the two blobs")
        for page in self._pages("?gap=2"):
            self.assertEqual(self._piece_buttons(page), 2)
            self.assertIn(".png?gap=2&amp;crop=0", page)
            self.assertIn("parts_gap: 2,", page)

    def test_the_default_is_the_saved_gap_else_the_page_constant(self):
        for page in self._pages():
            self.assertIn(f".png?gap={ts.PIECE_GAP_DIODES}&amp;crop=0", page)
        store = self.dir / "triage_verdicts"
        store.mkdir(exist_ok=True)
        (store / f"{FLIGHT}.json").write_text(json.dumps(
            {"0": {"verdict": "mixed", "two_real": 1, "real_parts": [2], "parts_gap": 0}}),
            encoding="utf-8")
        try:
            for page in self._pages():
                self.assertIn(".png?gap=0&amp;crop=0", page)
                self.assertEqual(self._piece_buttons(page), 2)
                self.assertRegex(page, r"class='gapchoice sel pbtn' href='[^']*gap=0'")
            # an explicit ?gap= still wins over the saved one
            for page in self._pages("?gap=8"):
                self.assertIn(".png?gap=8&amp;crop=0", page)
        finally:
            self._clear_store()

    def test_the_queue_page_keeps_its_order_in_the_gap_links(self):
        page = self._get(f"/queue/{QUEUE}/0?order=file")
        self.assertIn(f"href='/queue/{QUEUE}/0?order=file&amp;gap=2'", page)

    def test_reject_code_and_temperature_precede_the_image(self):
        for page in self._pages():
            meta = page.find("id='pmeta'")
            img = page.find("<img src=\"/image/")
            self.assertGreaterEqual(meta, 0, "no reject/temperature strip")
            self.assertGreaterEqual(img, 0)
            self.assertLess(meta, img)
            strip = page[meta:img]
            self.assertIn("Reject code", strip)
            self.assertIn("Air temperature", strip)
            # the record line (viewer-survey item 1) sits in the same strip on both routes
            self.assertIn("id='prec'", strip)
            self.assertIn("Record time", strip)

    def test_every_button_kind_carries_the_shared_class(self):
        for page in self._pages("?gap=2"):
            for kind in ("verdict", "phase", "two-n", "two-p", "comment-save", "gapchoice"):
                tags = re.findall(rf"<(?:button|a)\b[^>]*class='{kind}\b[^']*'", page)
                self.assertTrue(tags, f"no {kind} control")
                for t in tags:
                    self.assertIn("pbtn", t, t)
            self.assertIn("button.pbtn, a.pbtn", page)

    def _post(self, path: str, payload: dict) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("POST", path, body=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status

    def test_a_piece_picked_at_gap_2_is_saved_with_its_gap_and_never_lost(self):
        """The click path end to end: label the particle "two particles", save one real piece at
        the gap the page numbered it at, read it back, and re-click the verdict without losing it
        (no label may be lost)."""
        page = self._get(f"/particle/{FLIGHT}/0?gap=2")
        self.assertEqual(self._piece_buttons(page), 2)
        self.assertIn("parts_gap: 2,", page)  # what the page's click sends
        base = {"flight": FLIGHT, "particle_index": 0}
        self.assertEqual(self._post("/verdict", {**base, "verdict": "mixed"}), 200)
        self.assertEqual(self._post("/parts", {**base, "two_real": 1, "real_parts": [2],
                                               "parts_gap": 2}), 200)
        store = self.dir / "triage_verdicts" / f"{FLIGHT}.json"
        rec = json.loads(store.read_text(encoding="utf-8"))["0"]
        self.assertEqual((rec["two_real"], rec["real_parts"], rec["parts_gap"]), (1, [2], 2))
        self.assertEqual(self._post("/verdict", {**base, "verdict": "mixed"}), 200)
        rec = json.loads(store.read_text(encoding="utf-8"))["0"]
        self.assertEqual((rec["two_real"], rec["real_parts"], rec["parts_gap"]), (1, [2], 2))
        # reopened with no ?gap=, the page numbers at the saved gap and shows piece 2 chosen
        for page in self._pages():
            self.assertIn(".png?gap=2&amp;crop=0", page)
            self.assertEqual(self._piece_buttons(page), 2)
            self.assertIn("class='two-p sel pbtn'", page)

    def test_every_button_and_classed_link_on_the_page_is_one_style(self):
        for page in self._pages("?gap=2"):
            buttons = re.findall(r"<button\b[^>]*>", page)
            self.assertTrue(buttons)
            for b in buttons:
                self.assertRegex(b, r"class='[^']*\bpbtn\b", b)
            for a in re.findall(r"<a\b[^>]*\bclass='[^']*'[^>]*>", page):
                self.assertRegex(a, r"class='[^']*\bpbtn\b", a)

    def test_the_strip_opens_the_figure_with_only_the_record_line_before_the_image(self):
        for page in self._pages():
            fig = page.find("<figure class=\"pimg\">")
            img = page.find("<img src=\"/image/")
            self.assertGreaterEqual(fig, 0)
            head = page[fig + len("<figure class=\"pimg\">"):img].lstrip()
            self.assertTrue(head.startswith("<div class='pmeta' id='pmeta'>"), head[:80])
            rest = head[head.find("</div>") + len("</div>"):].strip()
            self.assertTrue(rest.startswith("<div class='prec' id='prec'>"), rest[:80])

    def test_a_piece_before_the_count_says_so(self):
        page = self._get(f"/particle/{FLIGHT}/0?gap=2")
        self.assertIn("First say how many are real.", page)


if __name__ == "__main__":
    unittest.main()
