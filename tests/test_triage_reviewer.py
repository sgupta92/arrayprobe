# SPDX-License-Identifier: BSD-3-Clause
"""Reviewer identity on triage verdicts, and agreement between two reviewers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arrayprobe import review_agreement as ra
from arrayprobe import triage_server as ts

X, Y = sorted(ts.VALID_VERDICTS)[:2]
FLIGHT = "base000000000000.H"


class TestReviewerStored(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reviewer_is_stored_in_the_record(self):
        data = ts._save_verdict(self.d, FLIGHT, 7, X, source="human", reviewer="alice")
        self.assertEqual(data["7"]["reviewer"], "alice")
        on_disk = ts._load_verdicts(self.d, FLIGHT)
        self.assertEqual(on_disk["7"]["reviewer"], "alice")

    def test_a_label_without_a_reviewer_is_refused(self):
        # Must-fire: the store refuses an anonymous label rather than guessing one.
        with self.assertRaises(ValueError):
            ts._save_verdict(self.d, FLIGHT, 7, X, source="human", reviewer=None)

    def test_an_old_sidecar_without_reviewer_loads_unchanged(self):
        old = {"3": {"verdict": X, "note": "", "source": "human",
                     "at": "2026-09-01T00:00:00+00:00", "tool": "0.1.0"}}
        ts._verdicts_path(self.d, FLIGHT).write_text(json.dumps(old), encoding="utf-8")
        self.assertEqual(ts._load_verdicts(self.d, FLIGHT), old)
        # and a reviewer-less record matches no reviewer
        self.assertEqual(ra.reviewer_labels(old, "alice"), {})

    def test_two_reviewers_verdicts_are_both_kept(self):
        ts._save_verdict(self.d, FLIGHT, 5, X, source="human", reviewer="alice")
        data = ts._save_verdict(self.d, FLIGHT, 5, Y, source="human", reviewer="bob")
        rec = data["5"]
        self.assertEqual((rec["reviewer"], rec["verdict"]), ("bob", Y))
        self.assertEqual([(h["reviewer"], h["verdict"]) for h in rec["history"]],
                         [("alice", X)])
        self.assertEqual(ra.reviewer_labels(data, "alice"), {"5": X})
        self.assertEqual(ra.reviewer_labels(data, "bob"), {"5": Y})


class TestReviewerAgreement(unittest.TestCase):
    def test_hand_computed_kappa_between_two_sidecars(self):
        # Four particles. alice: X X Y Y ; bob: X Y Y Y.
        # p_o = 3/4. Marginals alice X .5, Y .5; bob X .25, Y .75.
        # p_e = .5*.25 + .5*.75 = 0.5. kappa = (0.75 - 0.5) / (1 - 0.5) = 0.5.
        def side(who, labels):
            return {str(i): {"verdict": v, "source": "human", "reviewer": who}
                    for i, v in enumerate(labels)}
        a = side("alice", [X, X, Y, Y])
        b = side("bob", [X, Y, Y, Y])
        got = ra.reviewer_agreement(a, b, "alice", "bob")
        self.assertEqual(got.n, 4)
        self.assertAlmostEqual(got.observed, 0.75)
        self.assertAlmostEqual(got.expected, 0.5)
        self.assertAlmostEqual(got.kappa, 0.5)

    def test_one_store_labelled_by_both_is_paired_through_history(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            for i, (va, vb) in enumerate([(X, X), (X, Y), (Y, Y), (Y, Y)]):
                ts._save_verdict(d, FLIGHT, i, va, source="human", reviewer="alice")
                ts._save_verdict(d, FLIGHT, i, vb, source="human", reviewer="bob")
            store = ts._load_verdicts(d, FLIGHT)
            got = ra.reviewer_agreement(store, store, "alice", "bob")
        self.assertEqual(got.n, 4)
        self.assertAlmostEqual(got.kappa, 0.5)

    def test_must_fire_wrong_reviewer_pairs_nothing(self):
        a = {"0": {"verdict": X, "source": "human", "reviewer": "alice"}}
        self.assertEqual(ra.reviewer_agreement(a, a, "alice", "carol").n, 0)
        # A non-human (bulk/model) label is never counted as a reviewer's.
        b = {"0": {"verdict": X, "source": "model", "reviewer": "alice"}}
        self.assertEqual(ra.reviewer_labels(b, "alice"), {})


if __name__ == "__main__":
    unittest.main()
