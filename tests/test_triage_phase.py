# SPDX-License-Identifier: BSD-3-Clause
"""The phase label beside the verdict: ice, drizzle or unsure, chosen per particle by the reviewer.

The rule these tests hold: every label is saved and none can be lost. So each path that writes
a phase is followed by a reload from disk; a verdict change must not drop a phase already
stored; setting a phase must not drop the verdict or comment already stored; and a verdict file
written before the field existed must read, and take new labels, exactly as before.
"""
from __future__ import annotations

import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from tests.test_triage_server import HAVE_MPL, _make_fixture, netCDF4

from arrayprobe.triage_server import (
    _PHASE_KEYS,
    _VERDICT_KEYS,
    VALID_PHASES,
    TriageServer,
    _load_verdicts,
    _save_phase,
    _save_verdict,
    _verdicts_path,
)


def widget(**kw) -> tuple[str, str]:
    """The shared verdict widget; it reads no instance attribute, so ``None`` is ``self``."""
    kw.setdefault("flight_raw", "f")
    kw.setdefault("idx", 1)
    kw.setdefault("current", None)
    return TriageServer._verdict_widget(None, **kw)  # type: ignore[arg-type]


class TestPhaseStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_the_vocabulary_is_the_author_s_three(self):
        self.assertEqual(VALID_PHASES, frozenset({"ice", "drizzle", "unsure"}))

    def test_a_phase_saved_with_the_verdict_reloads(self):
        _save_verdict(self.dir, "f", 7, "real", source="human", phase="ice", comment="plate",
                      reviewer="test")
        rec = _load_verdicts(self.dir, "f")["7"]
        self.assertEqual((rec["verdict"], rec["phase"], rec["comment"]),
                         ("real", "ice", "plate"))

    def test_a_verdict_without_a_phase_writes_no_phase_key(self):
        _save_verdict(self.dir, "f", 7, "real", source="human", reviewer="test")
        self.assertNotIn("phase", _load_verdicts(self.dir, "f")["7"])

    def test_a_verdict_change_keeps_the_stored_phase(self):
        _save_verdict(self.dir, "f", 7, "real", source="human", phase="drizzle", reviewer="test")
        _save_verdict(self.dir, "f", 7, "unsure", source="human", reviewer="test")
        rec = _load_verdicts(self.dir, "f")["7"]
        self.assertEqual((rec["verdict"], rec["phase"]), ("unsure", "drizzle"))

    def test_a_new_phase_replaces_the_old_one(self):
        _save_verdict(self.dir, "f", 7, "real", source="human", phase="drizzle", reviewer="test")
        _save_verdict(self.dir, "f", 7, "real", source="human", phase="ice", reviewer="test")
        self.assertEqual(_load_verdicts(self.dir, "f")["7"]["phase"], "ice")

    def test_setting_a_phase_keeps_verdict_comment_and_provenance(self):
        _save_verdict(self.dir, "f", 3, "real", source="human", reviewer="sg",
                      queue="q1", comment="two lobes")
        before = dict(_load_verdicts(self.dir, "f")["3"])
        _save_phase(self.dir, "f", 3, "ice", queue="q1")
        after = _load_verdicts(self.dir, "f")["3"]
        self.assertEqual(after, {**before, "phase": "ice", "history": [before]})

    def test_a_phase_without_a_verdict_is_refused_and_writes_nothing(self):
        with self.assertRaises(LookupError):
            _save_phase(self.dir, "f", 3, "ice")
        self.assertFalse(_verdicts_path(self.dir, "f").exists())

    def test_an_unknown_phase_is_refused_on_both_paths(self):
        with self.assertRaises(ValueError):
            _save_verdict(self.dir, "f", 1, "real", source="human", phase="liquid", reviewer="test")
        self.assertFalse(_verdicts_path(self.dir, "f").exists())
        _save_verdict(self.dir, "f", 1, "real", source="human", reviewer="test")
        with self.assertRaises(ValueError):
            _save_phase(self.dir, "f", 1, "snow")
        self.assertNotIn("phase", _load_verdicts(self.dir, "f")["1"])

    def test_a_recheck_queue_writes_its_own_store(self):
        _save_verdict(self.dir, "f", 2, "real", source="human", queue="recheck-a", reviewer="test")
        _save_phase(self.dir, "f", 2, "drizzle", queue="recheck-a")
        self.assertEqual(_load_verdicts(self.dir, "f", recheck=True)["2"]["phase"], "drizzle")
        self.assertEqual(_load_verdicts(self.dir, "f"), {})


class TestOldFilesWithoutThePhaseField(unittest.TestCase):
    #: The shape every verdict file had before the phase field: no ``phase`` key anywhere.
    OLD = {
        "4": {"verdict": "real", "note": "", "source": "human",
              "at": "2026-09-16T10:00:00+00:00", "tool": "0.9.0", "comment": "old"},
        "5": {"verdict": "artifact", "note": "", "source": None,
              "at": "2026-08-27T10:00:00+00:00", "tool": "0.1.0"},
    }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        p = _verdicts_path(self.dir, "f")
        p.write_text(json.dumps(self.OLD, indent=1, sort_keys=True), encoding="utf-8")

    def test_it_reads_unchanged(self):
        self.assertEqual(_load_verdicts(self.dir, "f"), self.OLD)

    def test_labelling_another_particle_leaves_the_old_records_untouched(self):
        _save_verdict(self.dir, "f", 9, "real", source="human", phase="ice", reviewer="test")
        data = _load_verdicts(self.dir, "f")
        self.assertEqual({k: data[k] for k in self.OLD}, self.OLD)
        self.assertEqual(data["9"]["phase"], "ice")

    def test_relabelling_an_old_record_adds_no_phase(self):
        _save_verdict(self.dir, "f", 5, "real", source="human", reviewer="test")
        self.assertNotIn("phase", _load_verdicts(self.dir, "f")["5"])

    def test_a_phase_can_be_added_to_an_old_record(self):
        _save_phase(self.dir, "f", 4, "drizzle")
        rec = _load_verdicts(self.dir, "f")["4"]
        self.assertEqual(rec, {**self.OLD["4"], "phase": "drizzle", "history": [self.OLD["4"]]})


class TestWidget(unittest.TestCase):
    def test_every_phase_has_a_key_that_no_verdict_or_navigation_uses(self):
        self.assertEqual(set(_PHASE_KEYS), set(VALID_PHASES))
        keys = list(_PHASE_KEYS.values())
        self.assertEqual(len(keys), len(set(keys)))
        self.assertFalse((set(_VERDICT_KEYS.values()) | {"n", "p"}) & set(keys))
        for key in keys:
            self.assertRegex(key, r"^[a-z]$")

    def test_every_phase_has_a_button_and_its_key_is_shown(self):
        actions, _ = widget()
        for phase, key in _PHASE_KEYS.items():
            with self.subTest(phase=phase):
                self.assertIn(f"data-p='{phase}' data-key='{key}'", actions)
                self.assertIn(f"<kbd>{key}</kbd>", actions)

    def test_the_stored_phase_is_shown_selected_and_seeds_the_script(self):
        actions, script = widget(current="real", current_phase="ice")
        self.assertIn("class='phase sel pbtn' data-p='ice'", actions)
        self.assertEqual(actions.count("phase sel"), 1)
        self.assertIn('var phase = "ice";', script)
        actions, script = widget()
        self.assertNotIn("phase sel", actions)
        self.assertIn("var phase = null;", script)

    def test_a_stored_value_outside_the_vocabulary_is_not_echoed_into_the_script(self):
        _, script = widget(current_phase="</script>")
        self.assertIn("var phase = null;", script)

    def test_the_phase_rides_the_verdict_and_has_its_own_route(self):
        _, script = widget()
        self.assertIn("phase: sent", script)
        self.assertIn("'/phase'", script)
        # One save path: the only fetch is inside post(), so the keys still click buttons.
        self.assertEqual(1, len(re.findall(r"fetch\(", script)))
        self.assertIn("button.phase[data-key=", script)

    def test_leaving_the_page_waits_for_saves_in_flight(self):
        """A phase picked while the verdict was on its way is saved before the page moves on."""
        _, script = widget(on_saved_js="goWhenIdle('/next');")
        self.assertIn("if (phase !== sent) { savePhase(then); } else { then(); }",
                      script.replace("{{", "{").replace("}}", "}"))
        self.assertIn("goWhenIdle(a.getAttribute('href'))", script)
        self.assertNotIn("window.location = a.getAttribute", script)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class TestHttp(unittest.TestCase):
    """The routes and pages a browser uses, against a real server on an ephemeral port."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer

        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightP")
        # Class state other test modules also set: kept here and put back afterwards.
        cls._saved = {k: TriageServer.__dict__[k] for k in ("decoded_dir", "queues")
                      if k in TriageServer.__dict__}
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
        TriageServer.queues = {"qp": [{"flight": "flightP", "particle_index": 0},
                                      {"flight": "flightP", "particle_index": 1}]}
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

    def test_verdict_with_phase_then_phase_change_both_persist_and_reload(self):
        status, _ = self._request("POST", "/verdict", {
            "flight": "flightP", "particle_index": 1, "verdict": "real", "phase": "drizzle",
            "comment": "fat drop"})
        self.assertEqual(status, 200)
        self.assertEqual(_load_verdicts(self.dir, "flightP")["1"]["phase"], "drizzle")
        status, _ = self._request("POST", "/phase", {
            "flight": "flightP", "particle_index": 1, "phase": "ice"})
        self.assertEqual(status, 200)
        rec = _load_verdicts(self.dir, "flightP")["1"]
        self.assertEqual((rec["verdict"], rec["phase"], rec["comment"]),
                         ("real", "ice", "fat drop"))
        # The page read back from disk shows the stored phase selected.
        status, page = self._request("GET", "/particle/flightP/1")
        self.assertEqual(status, 200)
        self.assertIn(b"class='phase sel pbtn' data-p='ice'", page)

    def test_bad_phase_is_400_and_phase_before_verdict_is_409(self):
        status, _ = self._request("POST", "/verdict", {
            "flight": "flightP", "particle_index": 0, "verdict": "real", "phase": "hail"})
        self.assertEqual(status, 400)
        status, _ = self._request("POST", "/phase", {
            "flight": "flightP", "particle_index": 0, "phase": "ice"})
        self.assertEqual(status, 409)
        status, _ = self._request("POST", "/phase", {"flight": "flightP", "particle_index": 0})
        self.assertEqual(status, 400)
        self.assertNotIn("0", _load_verdicts(self.dir, "flightP"))

    def test_the_queue_page_moves_on_only_when_no_save_is_in_flight(self):
        status, page = self._request("GET", "/queue/qp/0")
        self.assertEqual(status, 200)
        self.assertIn(b"goWhenIdle('/queue/qp/1')", page)
        self.assertIn(b"data-p='drizzle'", page)


if __name__ == "__main__":
    unittest.main()
