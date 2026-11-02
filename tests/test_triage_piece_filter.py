# SPDX-License-Identifier: BSD-3-Clause
"""The queue page's piece-count column and ``?pieces=`` filter (display only)."""
import unittest

from arrayprobe.triage_server import (
    keep_by_pieces,
    keep_page_by_pieces,
    piece_agreement_html,
    piece_label_agreement,
    pieces_filter,
)


class TestPiecesFilter(unittest.TestCase):
    def test_absent_or_bad_value_is_no_filter(self):
        self.assertIsNone(pieces_filter({}))
        self.assertIsNone(pieces_filter({"pieces": ["x"]}))
        self.assertIsNone(pieces_filter({"pieces": ["0"]}))
        self.assertEqual(pieces_filter({"pieces": ["2"]}), 2)

    def test_two_keeps_two_or_more_and_one_keeps_exactly_one(self):
        pieces = [1, 2, None, 3, 1]
        view = [4, 3, 2, 1, 0]
        self.assertEqual(keep_by_pieces(view, pieces, None), view)
        self.assertEqual(keep_by_pieces(view, pieces, 2), [3, 1])
        self.assertEqual(keep_by_pieces(view, pieces, 1), [4, 0])


class TestFlightPageFilter(unittest.TestCase):
    def test_page_indices_narrow_by_their_counts(self):
        counts = {10: 1, 11: 3, 12: 2}
        page = [12, 11, 10, 13]
        self.assertEqual(keep_page_by_pieces(page, counts, None), page)
        self.assertEqual(keep_page_by_pieces(page, counts, 2), [12, 11])
        self.assertEqual(keep_page_by_pieces(page, counts, 1), [10])


class TestPieceLabelAgreement(unittest.TestCase):
    def test_counts_on_a_small_case(self):
        verdicts = {"1": {"verdict": "mixed"}, "2": {"verdict": "mixed"},
                    "3": {"verdict": "real"}, "4": {"verdict": "artifact"},
                    "5": {"verdict": "bogus"}}
        counts = {1: 2, 2: 1, 3: 3, 4: 1, 5: 4}
        a = piece_label_agreement(verdicts, counts)
        self.assertEqual(a, {"labelled": 4, "multi": 2, "multi_two": 1,
                             "two": 2, "two_multi": 1})
        line = piece_agreement_html(a)
        self.assertIn("of 4 labelled", line)
        self.assertIn("1 of 2 two-particle", line)

    def test_no_labels_says_so(self):
        a = piece_label_agreement({}, {})
        self.assertEqual(a["labelled"], 0)
        self.assertIn("no labelled particles", piece_agreement_html(a))


if __name__ == "__main__":
    unittest.main()
