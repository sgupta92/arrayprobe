# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``ncar_2dc_timing.convert_record`` equals SODA-2's ``fix2dimage`` word for word.

The expected words were produced by ``arrayprobe_soda2.fix2dimage`` (GDL-exact on 16 synthetic
cases) on these synthetic records, so the two sides come from different code; the v3.5 package
never imports ``arrayprobe_soda2``. Cases cover the reconciliation (648 timing words against 555):
zero-count timing
words (``FF000000`` before ``FF000000``, ``fix2dimage.pro:13-15``), a timeline at index 0 (``:26``
subscript -1 clipped), no blank two back (``:17-18``), fewer than five candidates (``:10``) and
every ``:9`` candidate word. No raw data.
"""

from __future__ import annotations

import unittest

import numpy as np

from arrayprobe_uiops import ncar_2dc_timing

CASES = {
    "zero_count_timing": (
        [
            0xFFFFFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000123,
            0xFF000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000007,
            0xFF000000,
            0xFFBDFFFF,
            0xFFBDFFFF,
        ],
        [
            0xFFFFFFFF,
            0x55000000,
            0x55000000,
            0xFFBDFFFF,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0x55000000,
            0x55000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0x55000123,
            0x55000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000007,
            0xFF000000,
            0xFFBDFFFF,
            0xFFBDFFFF,
        ],
    ),
    "timeline_at_index0": (
        [
            0xFF000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000044,
            0xFF000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000009,
            0xFF800000,
            0xFFBDFFFF,
            0xFFBDFFFF,
        ],
        [
            0x55000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0x55000044,
            0x55000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0x55000000,
            0x55000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000009,
            0xFF800000,
            0xFFBDFFFF,
            0xFFBDFFFF,
        ],
    ),
    "no_blank_two_back": (
        [
            0xFFBDFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
            0xFFBDFFFF,
            0xFF000000,
            0xFFBDFFFF,
            0xFF000000,
            0xFFBDFFFF,
            0xFFBDFFFF,
            0xFF000000,
            0xFFBDFFFF,
        ],
        [
            0xFFBDFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
            0xFFBDFFFF,
            0xFF000000,
            0xFFBDFFFF,
            0xFF000000,
            0xFFBDFFFF,
            0xFFBDFFFF,
            0xFF000000,
            0xFFBDFFFF,
        ],
    ),
    "four_candidates": (
        [
            0xFFFFFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
        ],
        [
            0xFFFFFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000000,
            0xFF000000,
            0xFFBDFFFF,
        ],
    ),
    "mixed_words": (
        [
            0xFFFFFFFF,
            0xFF00000A,
            0x0,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF00000B,
            0x2A000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000000,
            0xFF800000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000001,
            0xFF000000,
            0xFFBDFFFF,
        ],
        [
            0xFFFFFFFF,
            0x5500000A,
            0x55000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0x5500000B,
            0x55000000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0x55000000,
            0x55800000,
            0xFFBDFFFF,
            0xFFFFFFFF,
            0xFF000001,
            0xFF000000,
            0xFFBDFFFF,
        ],
    ),
}


def _record(words: list[int]) -> np.ndarray:
    w = np.asarray(words, dtype=np.uint32)
    return np.stack([(w >> s) & 0xFF for s in (24, 16, 8, 0)], axis=1).astype(np.int32)


class TestEqualsSoda2Fix2dimage(unittest.TestCase):
    def test_every_word_matches_the_soda2_oracle(self) -> None:
        for name, (words_in, expected) in CASES.items():
            with self.subTest(case=name):
                out, _ = ncar_2dc_timing.convert_record(_record(words_in))
                b = np.asarray(out).astype(np.uint32)
                got = (b[:, 0] << 24) | (b[:, 1] << 16) | (b[:, 2] << 8) | b[:, 3]
                self.assertEqual([int(x) for x in got], expected)


if __name__ == "__main__":
    unittest.main()
