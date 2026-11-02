# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.spec_decompress`` against GDL running SODA-2's own `.pro`.

The golden is real output from `spec_decompress.pro` run unmodified under GDL
(`gdl_oracle/run_soda2_spec_decompress_bank.py`), 16 cases -- the two sides of
the check come from different places: GDL executing NCAR's own IDL, and this
Python translation, never a fixture compared with itself.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.spec_decompress import spec_decompress

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_spec_decompress_golden.json"


def _rows(bitimage: np.ndarray) -> list[str]:
    return ["".join(str(int(v)) for v in row) for row in bitimage]


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking the port against IDL.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_every_case_matches_idl_exactly(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                got = spec_decompress(case["words"], case["overload"],
                                      version=case["version"])
                self.assertEqual(got.dtype, np.uint8)
                self.assertEqual(got.shape, (case["NSLICES"], 128))
                self.assertEqual(_rows(got), case["SLICES"],
                                 f"{case['name']}: {case['note']}")
            checked += 1
        self.assertGreaterEqual(checked, 12)

    def test_the_bank_reaches_every_branch(self):
        """A bank that never drove the overload skip, the version=1 block, a
        timing word, the clear-line value or the solid-line value would not
        be the bank this stage's plan specified."""
        overloads = {c["overload"] for c in self.cases}
        versions = {c["version"] for c in self.cases}
        has_timeslice_bit = any(
            any((w & 0x8000) for w in c["words"]) for c in self.cases)
        has_clear_line = any(0x7FFF in c["words"] for c in self.cases)
        has_solid_line = any(0x4000 in c["words"] for c in self.cases)
        self.assertIn(1, overloads, "no case drives the overload skip")
        self.assertIn(1, versions, "no case drives the version=1 branch")
        self.assertTrue(has_timeslice_bit, "no word in the bank has bit 15 set")
        self.assertTrue(has_clear_line, "no case drives the 0x7fff clear line")
        self.assertTrue(has_solid_line, "no case drives the 0x4000 solid line")


class TheOverAllocation(unittest.TestCase):
    """Finding S4-a: `numslices = total(startslice) + 3`, and `islice` is
    incremented before any word's data can be written to it -- so slice 0
    is always blank, and every case here comes back with three more rows
    than the number of startslice-bearing words would otherwise suggest."""

    def test_line_14_adds_three_blank_slices(self):
        bi = spec_decompress([0x4280], overload=0, version=0)  # w(1,0,5)
        self.assertEqual(bi.shape, (1 + 3, 128), "1 startslice word + 3")
        self.assertTrue((bi[0] == 0).all(), "slice 0 must stay blank")
        self.assertTrue((bi[2] == 0).all())
        self.assertTrue((bi[3] == 0).all())
        self.assertEqual(list(bi[1, :5]), [1, 1, 1, 1, 1])

    def test_slice_zero_is_blank_across_every_golden_case(self):
        cases = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for case in cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                self.assertEqual(case["SLICES"][0], "0" * 128)


class TheOverflowGuardDoesNotAdvanceIdiode(unittest.TestCase):
    """Finding S4-c, `:46`. The check is written as an isolated unit test
    (not only via the golden) so a future edit that "repairs" the overflow
    guard by rolling `idiode` forward anyway fails here by name."""

    def test_line_46_overflow_drops_the_word_without_advancing_idiode(self):
        # w(1,120,10) then w(0,0,3): the first run would end at diode 129
        # and is dropped whole; idiode stays at 120 (the startslice reset),
        # so the second run lands at [120,123), not [130,133).
        words = [(1 << 14) | (10 << 7) | 120, (3 << 7) | 0]
        bi = spec_decompress(words, overload=0, version=0)
        self.assertEqual(bi.shape, (1 + 3, 128))
        row = bi[1]
        self.assertEqual(int(row.sum()), 3, "only the second run was written")
        self.assertTrue((row[120:123] == 1).all())
        self.assertTrue((row[:120] == 0).all())
        self.assertTrue((row[123:] == 0).all())


class TheOverloadSkipsTheLastTwoWords(unittest.TestCase):
    """`:23`: `skip=overload*2`, `FOR i=0,n-1-skip`. Isolated from the golden
    because it is the one branch a fixed-range Python `for` would get right
    by accident (no counter mutation involved) but a caller could still
    silently drop by mis-porting `skip` as `overload` alone."""

    def test_line_23_overload_skips_two_words(self):
        # w(1,0,5), w(0,3,4), w(1,0,3), w(0,0,2); overload=1 -> skip=2, loop
        # bound = n-1-skip = 1, so only indices 0-1 are processed. Words 2-3
        # still count toward numslices via total(startslice) over the WHOLE
        # array (2 startslice words total, seen or not), giving 2+3=5 rows.
        w1, w2, w3, w4 = 17024, 515, 16768, 256
        bi = spec_decompress([w1, w2, w3, w4], overload=1, version=0)
        self.assertEqual(bi.shape, (2 + 3, 128),
                         "both startslice words count even though w3 is skipped")
        # Only slice 1 (from w1/w2) is ever touched; w3/w4 (indices 2,3) were
        # never processed, so no second slice's worth of content appears.
        self.assertTrue((bi[0] == 0).all())
        self.assertTrue((bi[2] == 0).all())
        self.assertTrue((bi[3] == 0).all())
        self.assertTrue((bi[4] == 0).all())
        self.assertEqual(int(bi[1].sum()), 5 + 4, "the two processed runs, 5+4 diodes")


if __name__ == "__main__":
    unittest.main()
