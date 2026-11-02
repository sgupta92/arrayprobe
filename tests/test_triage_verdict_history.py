# SPDX-License-Identifier: BSD-3-Clause
"""Triage labels are appended, never replaced: every label is saved and used.

A save keeps the label it supersedes in the record's ``history``, oldest first; the
top-level fields stay the current label, so every reader of the sidecar is unchanged.
A sidecar written before ``history`` existed loads as it did, and its record moves into
``history`` verbatim on the next save. An unreadable sidecar is still refused, never
overwritten. Labelling changes no computed number.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arrayprobe.triage_server import (  # noqa: E402
    RECHECK_PREFIX,
    VerdictStoreError,
    _load_second_verdicts,
    _load_verdicts,
    _save_comment,
    _save_parts,
    _save_phase,
    _save_second_verdict,
    _save_verdict,
    _save_verdicts_bulk,
    _verdicts_path,
)

FLIGHT = "base160906064017.H"


class VerdictHistory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_second_verdict_appends_and_the_latest_is_current(self):
        _save_verdict(self.d, FLIGHT, 7, "real", source="human", reviewer="a")
        data = _save_verdict(self.d, FLIGHT, 7, "artifact", source="human", reviewer="b")
        rec = data["7"]
        self.assertEqual(rec["verdict"], "artifact")
        self.assertEqual([h["verdict"] for h in rec["history"]], ["real"])
        self.assertEqual(_load_verdicts(self.d, FLIGHT)["7"], rec)

    def test_a_first_label_has_no_history_key(self):
        data = _save_verdict(self.d, FLIGHT, 1, "real", source="human", reviewer="a")
        self.assertNotIn("history", data["1"])

    def test_history_entries_keep_reviewer_label_and_time(self):
        first = _save_verdict(self.d, FLIGHT, 3, "unsure", "n1", source="human",
                              reviewer="alice")["3"]
        rec = _save_verdict(self.d, FLIGHT, 3, "real", source="human", reviewer="bob")["3"]
        self.assertEqual(rec["history"], [first])
        self.assertEqual(rec["history"][0]["reviewer"], "alice")
        self.assertIn("at", rec["history"][0])

    def test_a_legacy_record_moves_into_history_unchanged(self):
        legacy = {"verdict": "real", "note": "old sidecar, no source/reviewer/at"}
        p = _verdicts_path(self.d, FLIGHT)
        p.write_text(json.dumps({"5": legacy, "6": "artifact"}), encoding="utf-8")
        self.assertEqual(_load_verdicts(self.d, FLIGHT)["5"], legacy)  # old sidecar loads
        rec = _save_verdict(self.d, FLIGHT, 5, "artifact", source="human", reviewer="r")["5"]
        self.assertEqual(rec["history"], [legacy])
        rec6 = _save_verdict(self.d, FLIGHT, 6, "real", source="human", reviewer="r")["6"]
        self.assertEqual(rec6["history"], [{"legacy_value": "artifact"}])

    def test_bulk_relabel_appends_per_index(self):
        _save_verdict(self.d, FLIGHT, 1, "real", source="human", reviewer="a")
        data = _save_verdicts_bulk(self.d, FLIGHT, [1, 2], "artifact", reviewer="a")
        self.assertEqual([h["verdict"] for h in data["1"]["history"]], ["real"])
        self.assertNotIn("history", data["2"])
        data = _save_verdicts_bulk(self.d, FLIGHT, [1, 2], "unsure", reviewer="a")
        self.assertEqual([h["verdict"] for h in data["1"]["history"]], ["real", "artifact"])
        self.assertEqual([h["verdict"] for h in data["2"]["history"]], ["artifact"])

    def test_phase_comment_and_parts_edits_keep_a_snapshot(self):
        _save_verdict(self.d, FLIGHT, 4, "mixed", source="human", reviewer="a")
        _save_phase(self.d, FLIGHT, 4, "ice")
        _save_comment(self.d, FLIGHT, 4, "two drops")
        rec = _save_parts(self.d, FLIGHT, 4, 1, None)["4"]
        self.assertEqual(rec["phase"], "ice")
        self.assertEqual(rec["comment"], "two drops")
        self.assertEqual(rec["two_real"], 1)
        hist = rec["history"]
        self.assertEqual(len(hist), 3)
        self.assertNotIn("phase", hist[0])
        self.assertEqual(hist[1]["phase"], "ice")
        self.assertNotIn("comment", hist[1])
        self.assertNotIn("two_real", hist[2])
        self.assertTrue(all("history" not in h for h in hist))

    def test_no_label_is_lost_over_n_saves(self):
        labels = ["real", "artifact", "unsure", "mixed", "real", "artifact", "real"]
        for i, v in enumerate(labels):
            rec = _save_verdict(self.d, FLIGHT, 9, v, source="human", reviewer=f"r{i}")["9"]
        self.assertEqual(len(rec["history"]) + 1, len(labels))
        self.assertEqual([h["verdict"] for h in rec["history"]] + [rec["verdict"]], labels)
        self.assertEqual([h["reviewer"] for h in rec["history"]],
                         [f"r{i}" for i in range(len(labels) - 1)])

    def test_recheck_store_keeps_history(self):
        q = RECHECK_PREFIX + "blind"
        _save_verdict(self.d, FLIGHT, 2, "real", source="human", reviewer="a", queue=q)
        rec = _save_verdict(self.d, FLIGHT, 2, "artifact", source="human", reviewer="a",
                            queue=q)["2"]
        self.assertEqual([h["verdict"] for h in rec["history"]], ["real"])
        self.assertEqual(_load_verdicts(self.d, FLIGHT, recheck=True)["2"], rec)
        self.assertNotIn("2", _load_verdicts(self.d, FLIGHT))

    def test_per_second_labels_keep_history(self):
        _save_second_verdict(self.d, FLIGHT, 3600, "real", reviewer="a")
        data = _save_second_verdict(self.d, FLIGHT, 3600, "artifact", reviewer="b")
        self.assertEqual([h["verdict"] for h in data["3600"]["history"]], ["real"])
        self.assertEqual(_load_second_verdicts(self.d, FLIGHT), data)

    def test_an_unreadable_sidecar_still_refuses(self):
        p = _verdicts_path(self.d, FLIGHT)
        p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(VerdictStoreError):
            _save_verdict(self.d, FLIGHT, 1, "real", source="human", reviewer="a")
        self.assertEqual(p.read_text(encoding="utf-8"), "{not json")


if __name__ == "__main__":
    unittest.main()
