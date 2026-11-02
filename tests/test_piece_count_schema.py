# SPDX-License-Identifier: BSD-3-Clause
"""The triage particle-count schema: one / two / three-or-more pieces, size-scaled gap.

Author ruling 2026-10-05 ("follow recs"). The gap is G = 8 diodes, size-scaled
(capped at the larger piece's extent). Checked at two probe resolutions, a 128-diode 10 um
frame (2D-S) and a 64-diode 25 um frame (CIP): the gap is counted in diodes, so the class is
the same at both while its physical width differs.
"""
import unittest

import numpy as np

from arrayprobe.triage_context import (
    PIECE_COUNT_CLASSES,
    PIECE_COUNT_WORDS,
    PIECE_GAP_DIODES,
    count_class,
    piece_count_class,
)

#: (diodes across the frame, diode size in um)
PROBES = {"2D-S": (128, 10.0), "CIP": (64, 25.0)}


def frame(diodes, boxes, slices=60):
    c = np.zeros((slices, diodes), dtype=bool)
    for r0, c0, h, w in boxes:
        c[r0:r0 + h, c0:c0 + w] = True
    return c


class Schema(unittest.TestCase):
    def test_three_classes_in_order_with_words(self):
        self.assertEqual(PIECE_COUNT_CLASSES, ("one", "two", "three_or_more"))
        self.assertEqual(set(PIECE_COUNT_WORDS), set(PIECE_COUNT_CLASSES))

    def test_count_class_buckets(self):
        self.assertIsNone(count_class(0))
        self.assertEqual([count_class(n) for n in (1, 2, 3, 4, 9)],
                         ["one", "two", "three_or_more", "three_or_more", "three_or_more"])

    def test_gap_is_i687s_eight(self):
        self.assertEqual(PIECE_GAP_DIODES, 8)


class AtTwoResolutions(unittest.TestCase):
    def check(self, boxes, want):
        for name, (diodes, _um) in PROBES.items():
            with self.subTest(probe=name):
                self.assertEqual(piece_count_class(frame(diodes, boxes)), want)

    def test_empty_is_none(self):
        for diodes, _ in PROBES.values():
            self.assertIsNone(piece_count_class(frame(diodes, [])))

    def test_one(self):
        self.check([(10, 10, 6, 6)], "one")

    def test_fragmented_crystal_within_the_scaled_gap_is_one(self):
        # two 10-diode fragments 5 empty diodes apart: 5 <= min(8, 10)
        self.check([(10, 10, 10, 10), (10, 25, 10, 10)], "one")

    def test_two_far_apart(self):
        self.check([(10, 5, 6, 6), (10, 40, 6, 6)], "two")

    def test_small_specks_closer_than_g_but_wider_than_their_extent_stay_two(self):
        # 2-diode specks 5 empty diodes apart: under the scaled gap min(8, 2) = 2 < 5, two;
        # the constant G = 8 would have joined them.
        boxes = [(10, 10, 2, 2), (10, 17, 2, 2)]
        self.check(boxes, "two")
        for diodes, _ in PROBES.values():
            self.assertEqual(piece_count_class(frame(diodes, boxes), scale="constant"), "one")

    def test_cap_is_g_for_large_pieces(self):
        # 20-diode pieces: the gap is capped at G = 8, so 8 empty joins and 9 empty does not.
        self.check([(5, 2, 20, 20), (5, 30, 20, 20)], "one")
        self.check([(5, 2, 20, 20), (5, 31, 20, 20)], "two")

    def test_three_or_more(self):
        self.check([(5, 2, 4, 4), (5, 25, 4, 4), (5, 50, 4, 4)], "three_or_more")
        self.check([(5, 2, 3, 3), (5, 20, 3, 3), (5, 38, 3, 3), (30, 2, 3, 3)],
                   "three_or_more")

    def test_physical_gap_scales_with_diode_size(self):
        widths = {name: PIECE_GAP_DIODES * um for name, (_d, um) in PROBES.items()}
        self.assertEqual(widths, {"2D-S": 80.0, "CIP": 200.0})


if __name__ == "__main__":
    unittest.main()
