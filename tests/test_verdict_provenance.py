# SPDX-License-Identifier: BSD-3-Clause
"""Verdict provenance, and the fourth label.

**What the plan asked for, and why.** *"A verdict provenance schema: `source ∈
{human, bulk-cluster, model}`, reviewer id, timestamp, tool version, queue name;
human and bulk verdicts stop sharing a namespace (the 149-177 MB bulk sidecars
beside 57-300-byte human ones is the symptom)."* The stated control is one
sentence: **a verdict without `source` is refused.**

The symptom is worth restating, because it is what makes this a correctness
issue rather than bookkeeping. A cluster's bulk label and a person's judgement
were written into the same file in the same shape. Any accuracy number computed
from such a file is computed partly against the clustering it was meant to
evaluate -- the labels grade their own homework, and nothing in the data says
which rows did.

**And the fourth label.** ``ml_accept_reject_design.md:109`` records that the
taxonomy has no way to say *two particles in one image*. A reviewer who met one
had to choose ``"unsure"``, which merges a real, identifiable category into the
"I could not tell" bucket -- degrading both, since ``"unsure"`` is the bucket a
trainer drops. ``"mixed"`` now exists, and ``TRAINING_EXCLUDED`` names the two
labels no trainer should take as ground truth.

**What is deliberately NOT done: no provenance is invented.** Verdicts written
before this schema carry no ``source``, and they are round-tripped unchanged
rather than being stamped ``"human"`` on the grounds that a person probably
wrote them. A guessed provenance is worse than a missing one, because it
survives review.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from arrayprobe import triage_server  # noqa: E402
from arrayprobe.triage_server import (  # noqa: E402
    LEGACY_SOURCE,
    REVIEWER_ENV,
    TRAINING_EXCLUDED,
    VALID_SOURCES,
    VALID_VERDICTS,
    TriageServer,
    _clean_label,
    _load_verdicts,
    _recordable_queue,
    _save_second_verdict,
    _save_verdict,
    _save_verdicts_bulk,
    _verdict_record,
    _verdicts_path,
)

try:
    import netCDF4
except ImportError:  # the HTTP test needs a real proc file to discover a flight
    netCDF4 = None

try:
    # The fixture builder already exists; a second copy would drift from the
    # real proc/image shapes the server reads.
    from test_triage_server import _make_fixture  # noqa: E402
except Exception:  # pragma: no cover - only when netCDF4/matplotlib are absent
    _make_fixture = None


class ASourceIsRequired(unittest.TestCase):
    """The control, stated exactly as the plan states it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_saving_without_a_source_is_a_TypeError(self):
        """Keyword-only and no default: the call does not compile, so to speak.

        A default would have been a guess about who labelled the particle,
        written into the file as though it were known.
        """
        with self.assertRaises(TypeError):
            _save_verdict(self.dir, "f", 1, "real", "note", reviewer="test")

    def test_an_unknown_source_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            _save_verdict(self.dir, "f", 1, "real", "", source="whoever", reviewer="test")
        self.assertIn("whoever", str(caught.exception))

    def test_a_verdict_outside_the_vocabulary_is_refused_by_the_store(self):
        """The HTTP route already refused e.g. "accept"; a script importing the
        module could still store it, and example notebook 04 once taught exactly
        that. Both routes into the store now hold the same vocabulary."""
        for bad in ("accept", "reject", ""):
            with self.subTest(verdict=bad):
                with self.assertRaises(ValueError):
                    _save_verdict(self.dir, "f", 1, bad, "", source="human", reviewer="test")
                with self.assertRaises(ValueError):
                    _save_verdicts_bulk(self.dir, "f", [1, 2], bad, "", reviewer="test")
        self.assertEqual(_load_verdicts(self.dir, "f"), {})

    def test_each_valid_source_is_accepted_and_stored(self):
        for i, source in enumerate(sorted(VALID_SOURCES)):
            _save_verdict(self.dir, "f", i, "real", "", source=source, reviewer="test")
        stored = _load_verdicts(self.dir, "f")
        self.assertEqual({r["source"] for r in stored.values()}, set(VALID_SOURCES))

    def test_the_record_carries_time_and_tool_version(self):
        _save_verdict(self.dir, "f", 1, "real", "", source="human",
                      reviewer="sid", queue="cluster-review")
        record = _load_verdicts(self.dir, "f")["1"]
        self.assertEqual(record["source"], "human")
        self.assertEqual(record["reviewer"], "sid")
        self.assertEqual(record["queue"], "cluster-review")
        self.assertRegex(record["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertTrue(record["tool"], "the tool version must be recorded")

    def test_an_absent_queue_is_omitted_not_empty(self):
        """A key that is present and empty reads as "no queue, and we asked"."""
        _save_verdict(self.dir, "f", 1, "real", "", source="model", reviewer="test")
        record = _load_verdicts(self.dir, "f")["1"]
        self.assertNotIn("queue", record)

    def test_a_save_without_a_reviewer_is_refused_and_the_sidecar_is_unchanged(self):
        """Every new label names who made it; a missing or empty id writes nothing."""
        _save_verdict(self.dir, "f", 1, "real", "", source="human", reviewer="test")
        _save_second_verdict(self.dir, "f", 5, "ice", reviewer="test")
        files = sorted(self.dir.glob("triage_*verdicts/*.json"))
        before = {f: f.read_bytes() for f in files}
        for missing in (None, ""):
            with self.subTest(reviewer=missing):
                with self.assertRaises(ValueError):
                    _save_verdict(self.dir, "f", 2, "artifact", "", source="human",
                                  reviewer=missing)
                with self.assertRaises(ValueError):
                    _save_verdicts_bulk(self.dir, "f", [3, 4], "artifact", "",
                                        reviewer=missing)
                with self.assertRaises(ValueError):
                    _save_second_verdict(self.dir, "f", 6, "ice", reviewer=missing)
                with self.assertRaises(ValueError):
                    _verdict_record("real", "", "human", reviewer=missing)
        self.assertEqual(sorted(self.dir.glob("triage_*verdicts/*.json")), files)
        for f, data in before.items():
            self.assertEqual(f.read_bytes(), data, f"{f.name} changed")

    def test_a_stored_record_without_a_reviewer_still_loads(self):
        """Labels saved before the requirement are kept and read."""
        store = self.dir / "triage_verdicts"
        store.mkdir(exist_ok=True)
        legacy = {"7": {"verdict": "real", "note": "", "source": "human",
                        "at": "2026-09-01T00:00:00+00:00", "tool": "0"}}
        (store / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")
        self.assertEqual(_load_verdicts(self.dir, "legacy"), legacy)
        # A new save beside it needs a reviewer, and keeps the legacy record.
        _save_verdict(self.dir, "legacy", 8, "artifact", "", source="human",
                      reviewer="test")
        loaded = _load_verdicts(self.dir, "legacy")
        self.assertEqual(loaded["7"], legacy["7"])
        self.assertEqual(loaded["8"]["reviewer"], "test")


class BulkAndHumanNoLongerShareANamespace(unittest.TestCase):
    """The symptom the plan named, as a test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_a_bulk_label_says_it_is_a_bulk_label(self):
        _save_verdicts_bulk(self.dir, "f", [1, 2, 3], "real", "cluster 0", reviewer="test")
        stored = _load_verdicts(self.dir, "f")
        self.assertEqual({r["source"] for r in stored.values()}, {"bulk-cluster"})

    def test_the_two_are_distinguishable_in_one_file(self):
        """The file that could not be split before.

        Both kinds land in one sidecar, as they always did -- what changed is
        that a reader can now separate them, which is what an accuracy number
        needs.
        """
        _save_verdicts_bulk(self.dir, "f", [1, 2, 3], "real", "cluster 0", reviewer="test")
        _save_verdict(self.dir, "f", 2, "artifact", "looked again",
                      source="human", reviewer="sid")
        stored = _load_verdicts(self.dir, "f")
        human = {k for k, r in stored.items() if r["source"] == "human"}
        bulk = {k for k, r in stored.items() if r["source"] == "bulk-cluster"}
        self.assertEqual(human, {"2"})
        self.assertEqual(bulk, {"1", "3"})
        self.assertEqual(stored["2"]["verdict"], "artifact",
                         "a human re-label must win over the bulk one it replaced")

    def test_a_bulk_write_does_not_alias_one_record_across_every_index(self):
        """Each index gets its own dict.

        Storing the same object under every key would make a later per-particle
        edit silently rewrite the whole cluster -- the labels-lost failure this
        store already exists to prevent, in a new shape.
        """
        data = _save_verdicts_bulk(self.dir, "f", [1, 2], "real", "", reviewer="test")
        data["1"]["verdict"] = "artifact"
        self.assertEqual(data["2"]["verdict"], "real")


class LegacyVerdictsKeepTheirSilence(unittest.TestCase):
    """No provenance is invented for records written before the schema."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.legacy = {"7": {"verdict": "real", "note": "from 2026-09"}}
        _verdicts_path(self.dir, "f").write_text(
            json.dumps(self.legacy), encoding="utf-8")

    def test_a_legacy_record_is_read_unchanged(self):
        self.assertEqual(_load_verdicts(self.dir, "f"), self.legacy)

    def test_a_legacy_record_survives_a_later_save(self):
        _save_verdict(self.dir, "f", 8, "artifact", "", source="human", reviewer="test")
        stored = _load_verdicts(self.dir, "f")
        self.assertEqual(stored["7"], self.legacy["7"])
        self.assertEqual(stored["8"]["source"], "human")

    def test_an_unattributed_record_is_identifiable_as_such(self):
        stored = _load_verdicts(self.dir, "f")
        self.assertEqual(stored["7"].get("source", LEGACY_SOURCE), LEGACY_SOURCE)
        self.assertIsNone(LEGACY_SOURCE,
                          "LEGACY_SOURCE must not be a real source value")

    def test_legacy_is_not_one_of_the_valid_sources(self):
        self.assertNotIn(LEGACY_SOURCE, VALID_SOURCES)


class TheFourthLabel(unittest.TestCase):
    """`mixed`: two particles in one image, which was being recorded as `unsure`."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_mixed_is_a_verdict_the_store_accepts(self):
        self.assertIn("mixed", VALID_VERDICTS)
        _save_verdict(self.dir, "f", 1, "mixed", "two of them", source="human", reviewer="test")
        self.assertEqual(_load_verdicts(self.dir, "f")["1"]["verdict"], "mixed")

    def test_both_uncertain_labels_are_excluded_from_training(self):
        self.assertEqual(TRAINING_EXCLUDED, {"unsure", "mixed"})

    def test_the_decidable_labels_are_not_excluded(self):
        """The other half: the exclusion must not quietly grow to cover the
        labels a classifier is supposed to learn."""
        self.assertEqual(VALID_VERDICTS - TRAINING_EXCLUDED, {"artifact", "real"})


class TheProvenanceTravelsFromTheBrowser(unittest.TestCase):
    """The gap `LABELLING_PROTOCOL.md` §4 measured, closed and held closed.

    The store accepted ``reviewer`` and ``queue`` from the day they were added,
    and both are ``null`` on all 466 existing labels anyway -- because the
    rendered verdict button posted only ``{flight, particle_index, verdict}``.
    A unit test on :func:`_save_verdict` could not see that, so these tests go
    through the two surfaces that actually failed: the emitted JavaScript, and
    a POST to a running server.

    Both states are asserted, because the whole point is that a missing
    reviewer stays missing: a test that only proved "sid" gets recorded would
    pass just as well against a server that filled the field in from the OS
    username.
    """

    def _widget(self, reviewer, queue):
        """The buttons + script the page emits, with no HTTP and no netCDF.

        ``_verdict_widget`` reads no instance state, so a bare object stands in
        for the handler; going through ``TriageServer`` unbound keeps the test
        pointed at the real method rather than a copy of its formatting.
        """
        server = type("_Stub", (), {"reviewer": reviewer})()
        return TriageServer._verdict_widget(server, "flightA", 7, None, "", queue=queue)

    def test_a_queue_page_button_posts_the_queue_name(self):
        _, script = self._widget("sid", "U-z__S-accepted")
        self.assertIn('queue: "U-z__S-accepted"', script)

    def test_a_browsing_page_button_posts_queue_null(self):
        """Not an omitted field: §4's rule is that a label made while browsing
        is not part of a sample, and the record should say so."""
        _, script = self._widget("sid", None)
        self.assertIn("queue: null", script)

    def test_the_page_never_carries_the_reviewer_id(self):
        """The identity is server state. If it round-tripped through the page,
        page state -- or anything that can POST -- would decide whose label it
        is."""
        _, script = self._widget("sid", "U-z__S-accepted")
        self.assertNotIn("sid", script)

    def test_a_queue_name_the_store_cannot_hold_becomes_null_not_an_error(self):
        """A queue name comes from a queue file, not from this module's
        vocabulary. Refusing it would 500 every save in that queue and stop the
        pass; ``run`` prints the affected names at startup instead."""
        self.assertIsNone(_recordable_queue("cell: a/b+c"))
        _, script = self._widget("sid", "cell: a/b+c")
        self.assertIn("queue: null", script)


@unittest.skipUnless(netCDF4 is not None and _make_fixture is not None,
                     "netCDF4 not installed")
class TheServerRecordsWhoLabelled(unittest.TestCase):
    """End to end: a real server, a real POST, the sidecar read back."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightA")
        TriageServer.decoded_dir = cls.dir
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TriageServer)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        TriageServer.reviewer = None   # class attribute: do not leak to other classes
        cls._tmp.cleanup()

    def _post(self, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("POST", "/verdict", body=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status

    def test_with_a_reviewer_configured_the_label_records_it(self):
        TriageServer.reviewer = "sid"
        self.addCleanup(setattr, TriageServer, "reviewer", None)
        status = self._post({"flight": "flightA", "particle_index": 0,
                             "verdict": "real", "queue": "U-z__S-accepted"})
        self.assertEqual(status, 200)
        record = _load_verdicts(self.dir, "flightA")["0"]
        self.assertEqual(record["reviewer"], "sid")
        self.assertEqual(record["queue"], "U-z__S-accepted")

    def test_with_no_reviewer_configured_the_save_is_refused_with_400(self):
        """The other state, and the one that matters: nothing is invented, nothing saved."""
        TriageServer.reviewer = None
        p = self.dir / "triage_verdicts" / "flightA.json"
        before = p.read_bytes() if p.exists() else None
        status = self._post({"flight": "flightA", "particle_index": 1,
                             "verdict": "artifact"})
        self.assertEqual(status, 400)
        self.assertEqual(p.read_bytes() if p.exists() else None, before)
        # And specifically not the OS username, which is the guess on offer.
        if before is not None:
            self.assertNotIn(os.environ.get("USERNAME", "<no USERNAME set>"), before.decode())


class TheReviewerIsNeverGuessed(unittest.TestCase):
    """``--reviewer``/``ARRAYPROBE_REVIEWER`` on both entry points, no default."""

    def _reviewer_main_passes(self, argv, env):
        """What ``python -m arrayprobe.triage_server`` hands ``run``.

        Patched at ``run`` rather than at the parser, so the flag reaching the
        server -- not merely being parsed -- is what is asserted.
        """
        seen = {}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(triage_server, "run",
                                  lambda *a, **k: seen.setdefault("args", a)):
            triage_server.main(argv)
        return seen["args"][3]

    def test_the_module_form_defaults_the_reviewer_to_the_environment_only(self):
        self.assertEqual(
            self._reviewer_main_passes(["--decoded-dir", "."],
                                       {REVIEWER_ENV: "ena-labeller"}),
            "ena-labeller")
        self.assertIsNone(self._reviewer_main_passes(["--decoded-dir", "."], {}))
        self.assertEqual(
            self._reviewer_main_passes(["--decoded-dir", ".", "--reviewer", "sid"], {}),
            "sid")

    def test_the_cli_form_takes_the_flag_and_the_environment(self):
        from arrayprobe import cli
        with mock.patch.dict(os.environ, {}, clear=True):
            args = cli.build_parser().parse_args(
                ["triage", "--decoded-dir", ".", "--reviewer", "sid"])
            self.assertEqual(args.reviewer, "sid")
            args = cli.build_parser().parse_args(["triage", "--decoded-dir", "."])
            self.assertIsNone(args.reviewer)

    def test_a_malformed_reviewer_id_is_refused_rather_than_trimmed(self):
        with self.assertRaises(ValueError):
            _clean_label("sid; DROP", "reviewer")


if __name__ == "__main__":
    unittest.main()
