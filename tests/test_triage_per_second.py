# SPDX-License-Identifier: BSD-3-Clause
"""Per-second queue items for the blind phase-labelling pass.

What these tests hold: a ``{"flight", "second"}`` queue loads and renders a grid page that shows
no classifier call; a per-second label lands in its own store and never in the particle verdict
sidecar; an unreadable per-second store fails closed with :class:`VerdictStoreError` rather than
being overwritten; and particle-index queues behave exactly as before.
"""
from __future__ import annotations

import html
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from tests.test_triage_server import HAVE_MPL, _make_fixture, netCDF4

from arrayprobe.triage_server import (
    SECOND_CHOICES,
    TriageServer,
    VerdictStoreError,
    _load_queue_file,
    _load_second_verdicts,
    _load_verdicts,
    _save_second_verdict,
    _second_verdicts_path,
    _verdicts_path,
    is_second_item,
)


class TestQueueLoader(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, data) -> Path:
        p = self.dir / "q.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_a_per_second_queue_loads(self):
        data = _load_queue_file(self._write(
            {"phase": [{"flight": "0215", "second": 43205}]}))
        self.assertTrue(is_second_item(data["phase"][0]))

    def test_a_particle_queue_still_loads_and_is_not_a_second_item(self):
        data = _load_queue_file(self._write(
            {"qp": [{"flight": "f", "particle_index": 3, "note": "n"}]}))
        self.assertFalse(is_second_item(data["qp"][0]))

    def test_an_item_with_neither_key_is_refused(self):
        with self.assertRaises(ValueError):
            _load_queue_file(self._write({"q": [{"flight": "f"}]}))


class TestSecondStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_a_saved_second_reloads_and_writes_no_particle_verdict(self):
        _save_second_verdict(self.dir, "f", 43205, SECOND_CHOICES[0], queue="phase",
                             reviewer="test")
        self.assertEqual(_load_second_verdicts(self.dir, "f")["43205"]["verdict"],
                         SECOND_CHOICES[0])
        self.assertFalse(_verdicts_path(self.dir, "f").exists())
        self.assertEqual(_load_verdicts(self.dir, "f"), {})

    def test_an_unreadable_store_raises_and_is_not_overwritten(self):
        p = _second_verdicts_path(self.dir, "f")
        p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(VerdictStoreError):
            _load_second_verdicts(self.dir, "f")
        with self.assertRaises(VerdictStoreError):
            _save_second_verdict(self.dir, "f", 1, SECOND_CHOICES[0], reviewer="test")
        self.assertEqual(p.read_text(encoding="utf-8"), "{not json")

    def test_a_store_that_is_not_an_object_raises(self):
        _second_verdicts_path(self.dir, "f").write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(VerdictStoreError):
            _load_second_verdicts(self.dir, "f")


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class TestHttp(unittest.TestCase):
    """The per-second page and route, beside a particle queue, on a real server."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer

        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightP")
        cls._saved = {k: TriageServer.__dict__[k] for k in ("decoded_dir", "queues")
                      if k in TriageServer.__dict__}
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
        TriageServer.queues = {
            "qp": [{"flight": "flightP", "particle_index": 0},
                   {"flight": "flightP", "particle_index": 1}],
            "phase": [{"flight": "flightP", "second": 43205,
                       "stratum": "SECRET_STRATUM", "phase_class": "SECRET_CLASS"}],
        }
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

    def test_the_second_page_renders_its_choices_and_no_classifier_call(self):
        status, out = self._request("GET", "/queue/phase/0")
        page = out.decode("utf-8")
        self.assertEqual(status, 200, page[:500])
        self.assertIn("second 43205", page)
        for c in SECOND_CHOICES:
            self.assertIn(html.escape(c), page)
        self.assertNotIn("SECRET_STRATUM", page)
        self.assertNotIn("SECRET_CLASS", page)

    def test_posting_a_choice_writes_the_second_store_not_particle_verdicts(self):
        before = _load_verdicts(self.dir, "flightP")
        status, out = self._request("POST", "/second-verdict", {
            "flight": "flightP", "second": 43205, "verdict": SECOND_CHOICES[2],
            "queue": "phase"})
        self.assertEqual(status, 200, out)
        self.assertEqual(_load_second_verdicts(self.dir, "flightP")["43205"]["verdict"],
                         SECOND_CHOICES[2])
        self.assertEqual(_load_verdicts(self.dir, "flightP"), before)

    def test_an_unknown_choice_is_refused(self):
        status, _ = self._request("POST", "/second-verdict", {
            "flight": "flightP", "second": 1, "verdict": "graupel"})
        self.assertEqual(status, 400)

    def test_a_particle_queue_item_still_renders_and_labels(self):
        status, out = self._request("GET", "/queue/qp/0")
        self.assertEqual(status, 200, out[:500])
        status, _ = self._request("POST", "/verdict", {
            "flight": "flightP", "particle_index": 0, "verdict": "real", "queue": "qp"})
        self.assertEqual(status, 200)
        self.assertEqual(_load_verdicts(self.dir, "flightP")["0"]["verdict"], "real")


if __name__ == "__main__":
    unittest.main()
