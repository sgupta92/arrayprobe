# SPDX-License-Identifier: BSD-3-Clause
"""A reviewer's comment is saved on its own, shown again on revisit, and never lost.

Comments were lost two ways. The box was sent only inside the verdict POST and the queue page
moved on half a second after a verdict, so text typed after the click was never sent; and a
verdict re-clicked on a revisited particle built a fresh record from an empty box, erasing the
stored comment. These tests hold the fix: ``POST /comment`` writes the comment of a labelled
particle and nothing else; a verdict sent without a comment (``null``) keeps the stored one and
an empty string clears it; the page pre-fills the box from the store and says whether it is
saved; and the queue never moves on while the box holds unsaved text.
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

from tests.test_triage_server import HAVE_MPL, _make_fixture, netCDF4

from arrayprobe.triage_server import (
    TriageServer,
    _load_verdicts,
    _save_comment,
    _save_verdict,
    _verdicts_path,
)


def widget(**kw) -> tuple[str, str]:
    """The shared verdict widget; it reads no instance attribute, so ``None`` is ``self``."""
    kw.setdefault("flight_raw", "f")
    kw.setdefault("idx", 1)
    kw.setdefault("current", None)
    return TriageServer._verdict_widget(None, **kw)  # type: ignore[arg-type]


def unbrace(script: str) -> str:
    return script.replace("{{", "{").replace("}}", "}")


class TestCommentStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_a_comment_saved_on_its_own_changes_nothing_else(self):
        _save_verdict(self.dir, "f", 4, "real", source="human", reviewer="sg",
                      queue="q1", phase="ice")
        before = dict(_load_verdicts(self.dir, "f")["4"])
        _save_comment(self.dir, "f", 4, "  two lobes  ", queue="q1")
        after = _load_verdicts(self.dir, "f")["4"]
        self.assertEqual(after, {**before, "comment": "two lobes", "history": [before]})

    def test_an_empty_comment_clears_and_nothing_else_moves(self):
        _save_verdict(self.dir, "f", 4, "real", source="human", comment="old", reviewer="test")
        before = dict(_load_verdicts(self.dir, "f")["4"])
        _save_comment(self.dir, "f", 4, "")
        after = _load_verdicts(self.dir, "f")["4"]
        self.assertEqual(after, {**{k: v for k, v in before.items() if k != "comment"},
                                 "history": [before]})

    def test_a_comment_without_a_verdict_is_refused_and_writes_nothing(self):
        with self.assertRaises(LookupError):
            _save_comment(self.dir, "f", 4, "held until the verdict")
        self.assertFalse(_verdicts_path(self.dir, "f").exists())

    def test_a_verdict_without_a_comment_keeps_the_stored_one(self):
        _save_verdict(self.dir, "f", 4, "real", source="human", comment="touching pair",
                      reviewer="test")
        _save_verdict(self.dir, "f", 4, "mixed", source="human", reviewer="test")
        rec = _load_verdicts(self.dir, "f")["4"]
        self.assertEqual((rec["verdict"], rec["comment"]), ("mixed", "touching pair"))

    def test_a_verdict_with_an_empty_comment_clears_it(self):
        _save_verdict(self.dir, "f", 4, "real", source="human", comment="touching pair",
                      reviewer="test")
        _save_verdict(self.dir, "f", 4, "real", source="human", comment="", reviewer="test")
        self.assertNotIn("comment", _load_verdicts(self.dir, "f")["4"])

    def test_a_record_written_before_the_route_existed_reads_unchanged(self):
        old = {"9": {"verdict": "artifact", "note": "", "source": "human",
                     "at": "2026-09-16T10:00:00+00:00", "tool": "0.9.0"}}
        p = _verdicts_path(self.dir, "f")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(old), encoding="utf-8")
        self.assertEqual(_load_verdicts(self.dir, "f"), old)
        _save_comment(self.dir, "f", 9, "streak")
        self.assertEqual(_load_verdicts(self.dir, "f")["9"],
                         {**old["9"], "comment": "streak", "history": [old["9"]]})


class TestWidget(unittest.TestCase):
    def test_the_box_is_prefilled_from_the_store_and_escaped(self):
        stored = "a < b & 'c'"
        actions, _ = widget(current="real", current_comment=stored,
                            current_at="2026-10-01T14:02:11+00:00")
        self.assertIn(f">{html.escape(stored)}</textarea>", actions)
        self.assertIn("Comment saved 14:02:11", actions)

    def test_an_empty_store_shows_an_empty_box_and_no_saved_claim(self):
        actions, _ = widget()
        self.assertRegex(actions, r"<textarea[^>]*></textarea>")
        self.assertNotIn("Comment saved", actions)

    def test_a_save_button_and_ctrl_enter_post_to_the_comment_route(self):
        actions, script = widget(current="real")
        self.assertIn("id='comment-save'", actions)
        self.assertIn("Save comment", actions)
        script = unbrace(script)
        self.assertIn("'/comment'", script)
        self.assertIn("e.key === 'Enter'", script)
        # Still one save path: post() holds the only fetch.
        self.assertEqual(1, len(re.findall(r"fetch\(", script)))

    def test_the_advance_is_refused_while_the_comment_is_unsaved(self):
        _, script = widget(on_saved_js="goWhenIdle('/queue/q/1');")
        script = unbrace(script)
        m = re.search(r"function afterSave\(\) \{(.*?)\n\}", script, re.S)
        self.assertIsNotNone(m, "afterSave() not found")
        body = m.group(1)
        guard = body.find("if (commentDirty)")
        self.assertGreaterEqual(guard, 0, "afterSave has no commentDirty guard")
        self.assertLess(guard, body.find("goWhenIdle('/queue/q/1')"))
        self.assertIn("return;", body[guard:body.find("goWhenIdle('/queue/q/1')")])
        self.assertIn("Ctrl+Enter saves it, then the queue moves on", script)

    def test_a_stored_comment_cannot_break_out_of_the_page(self):
        actions, script = widget(current="real", current_comment="</textarea><script>x()</script>",
                                 current_at="</script>")
        self.assertNotIn("<script>x()", actions)
        self.assertNotIn("</script>", script)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class TestHttp(unittest.TestCase):
    """The routes and pages a browser uses, against a real server on an ephemeral port."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer

        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightC")
        # Class state other test modules also set: kept here and put back afterwards.
        cls._saved = {k: TriageServer.__dict__[k] for k in ("decoded_dir", "queues")
                      if k in TriageServer.__dict__}
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
        TriageServer.queues = {"qc": [{"flight": "flightC", "particle_index": 0},
                                      {"flight": "flightC", "particle_index": 1}]}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TriageServer)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        for k in ("decoded_dir", "queues"):
            if k in cls._saved:
                setattr(TriageServer, k, cls._saved[k])
            else:
                delattr(TriageServer, k)
        cls._tmp.cleanup()

    def _request(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        body = json.dumps(payload).encode() if payload is not None else None
        conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        out = resp.read()
        conn.close()
        return resp.status, out

    def test_post_comment_stores_on_an_existing_record(self):
        status, _ = self._request("POST", "/verdict", {
            "flight": "flightC", "particle_index": 1, "verdict": "real", "queue": "qc",
            "phase": "ice"})
        self.assertEqual(status, 200)
        before = dict(_load_verdicts(self.dir, "flightC")["1"])
        status, out = self._request("POST", "/comment", {
            "flight": "flightC", "particle_index": 1, "comment": "rimed plate", "queue": "qc"})
        self.assertEqual(status, 200, out)
        self.assertTrue(json.loads(out)["ok"])
        after = _load_verdicts(self.dir, "flightC")["1"]
        self.assertEqual(after, {**before, "comment": "rimed plate", "history": [before]})

    def test_post_comment_before_any_verdict_is_409_and_writes_nothing(self):
        status, _ = self._request("POST", "/comment", {
            "flight": "flightC", "particle_index": 7, "comment": "no verdict yet"})
        self.assertEqual(status, 409)
        self.assertNotIn("7", _load_verdicts(self.dir, "flightC"))
        status, _ = self._request("POST", "/comment", {"flight": "flightC", "particle_index": 7})
        self.assertEqual(status, 400)

    def test_verdict_with_comment_null_keeps_the_stored_comment(self):
        self._request("POST", "/verdict", {
            "flight": "flightC", "particle_index": 2, "verdict": "real",
            "comment": "fat drop"})
        status, _ = self._request("POST", "/verdict", {
            "flight": "flightC", "particle_index": 2, "verdict": "unsure", "comment": None})
        self.assertEqual(status, 200)
        rec = _load_verdicts(self.dir, "flightC")["2"]
        self.assertEqual((rec["verdict"], rec["comment"]), ("unsure", "fat drop"))
        status, _ = self._request("POST", "/verdict", {
            "flight": "flightC", "particle_index": 2, "verdict": "unsure", "comment": ""})
        self.assertEqual(status, 200)
        self.assertNotIn("comment", _load_verdicts(self.dir, "flightC")["2"])

    def test_the_queue_item_page_prefills_the_stored_comment(self):
        self._request("POST", "/verdict", {
            "flight": "flightC", "particle_index": 0, "verdict": "artifact", "queue": "qc",
            "comment": "streak across the array"})
        status, page = self._request("GET", "/queue/qc/0")
        self.assertEqual(status, 200)
        text = page.decode("utf-8")
        self.assertIn(">streak across the array</textarea>", text)
        self.assertIn("Comment saved", text)
        # The queue's first item still has no back-link, and no text naming one.
        self.assertNotIn("previous", text)


if __name__ == "__main__":
    unittest.main()
