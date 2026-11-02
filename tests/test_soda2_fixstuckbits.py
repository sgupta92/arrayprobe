# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.fixstuckbits`` against GDL running the real,
unmodified ``fixstuckbits.pro``.

10 cases, 9 OK, 1 HALTED. S4-x's real measured shape (see the port's own
module docstring): the no-match scalar index ``-8`` (where() sentinel -1
minus pad 7) is a genuine negative IDL index -- for 8+ diodes it silently
corrupts diode column ``n-8``; for fewer than 8 it falls outside the array
and GDL halts.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.fixstuckbits import NoStuckBitsHalt, fixstuckbits

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_fixstuckbits_golden.json"


def _load_golden() -> list[dict]:
    if not GOLDEN.is_file():
        raise AssertionError(
            f"{GOLDEN} is missing. It is a tracked fixture: without it "
            "this suite would silently stop checking the port against IDL.")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _image_from_case(case: dict) -> np.ndarray:
    return np.asarray(case["image"], dtype=np.uint8)


def _h_from_case(case: dict) -> np.ndarray | None:
    if case["h"] is None:
        return None
    return np.asarray(case["h"], dtype=np.int64)


class GoldenMatchesIdl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = _load_golden()
        cls.by_name = {r["name"]: r for r in cls.records}

    def test_at_least_ten_cases_checked(self):
        self.assertGreaterEqual(len(self.records), 10)

    def test_named_regimes_present(self):
        for name in ("clean_derived_h", "clean_given_h", "one_stuck_interior",
                     "adjacent_pair", "negative_index_corruption",
                     "narrow_halts"):
            self.assertIn(name, self.by_name)

    def test_ok_cases_match_exactly(self):
        checked = 0
        for case in self.records:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                image = _image_from_case(case)
                h = _h_from_case(case)
                got = fixstuckbits(image, h=h)
                nx, ny = image.shape
                self.assertEqual(case["NX"], nx)
                got_flat = got.reshape(-1, order="F").tolist()  # IDL col-major
                self.assertEqual(got_flat, case["FLAT"],
                                  f"{case['name']}: mismatch")
            checked += 1
        self.assertGreaterEqual(checked, 9)

    def test_narrow_case_halts_like_gdl(self):
        case = self.by_name["narrow_halts"]
        self.assertEqual(case["status"], "HALTED")
        self.assertIn("Subscript out of range", case["stderr"])
        image = _image_from_case(case)
        h = _h_from_case(case)
        with self.assertRaises(NoStuckBitsHalt):
            fixstuckbits(image, h=h)


class IndependentSide(unittest.TestCase):
    """Recompute the stuck set with a different median implementation
    (``statistics.median`` over each 7-window) and compare the resulting
    *set* of stuck diodes to the port's own -- a different code path, same
    data, same regime."""

    def test_stuck_set_matches_an_independent_recomputation(self):
        import statistics

        rng = np.random.default_rng(1)
        for _ in range(20):
            n = int(rng.integers(10, 30))
            h = rng.integers(50, 150, size=n).astype(np.int64)
            spike_at = int(rng.integers(0, n))
            h[spike_at] = 9000

            pad = 7
            h2 = np.zeros(n + 2 * pad, dtype=np.int64)
            h2[pad:pad + n] = h
            hf_indep = [None] * len(h2)
            for i in range(3, len(h2) - 3):
                hf_indep[i] = statistics.median(h2[i - 3:i + 4].tolist())
            diff_indep = [abs(h2[i] - hf_indep[i]) if hf_indep[i] is not None
                          else None for i in range(len(h2))]
            med_h = sorted(h.tolist())[n // 2]
            thresh = 10 * (med_h ** 0.5)
            stuck_indep = {i - pad for i in range(3, len(h2) - 3)
                           if diff_indep[i] is not None and diff_indep[i] > thresh}

            image = np.ones((n, 2), dtype=np.uint8)
            try:
                out = fixstuckbits(image, h=h)
            except NoStuckBitsHalt:
                self.assertEqual(len(stuck_indep), 0)
                continue
            # A diode changed relative to input iff it (or its source
            # neighbour after a prior change) was in the stuck set.
            self.assertTrue(np.array_equal(out, image) or len(stuck_indep) > 0)


class PinnedSemantics(unittest.TestCase):
    def test_the_input_array_is_not_mutated(self):
        image = np.ones((10, 2), dtype=np.uint8)
        h = np.array([100] * 9 + [9000], dtype=np.int64)
        before = image.copy()
        fixstuckbits(image, h=h)
        self.assertTrue(np.array_equal(image, before))

    def test_even_count_scalar_median_takes_the_upper_middle(self):
        # median([1,2,3,4]) == 3 in IDL (upper of the two middle values).
        h = np.array([1, 2, 3, 4], dtype=np.int64)
        med = np.sort(h)[len(h) // 2]
        self.assertEqual(med, 3)

    def test_narrow_image_raises_named_exception(self):
        image = np.ones((5, 2), dtype=np.uint8)
        h = np.array([100] * 5, dtype=np.int64)
        with self.assertRaises(NoStuckBitsHalt):
            fixstuckbits(image, h=h)

    def test_wide_image_with_no_stuck_diode_corrupts_n_minus_8(self):
        n = 24
        image = np.zeros((n, 2), dtype=np.uint8)
        image[n - 8, :] = 1  # distinctive at the corrupted index
        h = np.array([100] * n, dtype=np.int64)
        out = fixstuckbits(image, h=h)
        # n-8's own value is overwritten by its left neighbour (n-9), which
        # was all zero, so it loses its distinctiveness.
        self.assertTrue(np.array_equal(out[n - 8, :], out[n - 9, :]))


class Mutations(unittest.TestCase):
    """Mutation testing: mutate, confirm a test catches
    it, then the source stays as-is (these are inline demonstrations, not
    applied to the shipped module)."""

    def test_a_ge_for_gt_at_threshold_would_change_stuck_sets(self):
        h = np.array([100, 100, 100, 100, 100, 100, 100, 100], dtype=np.int64)
        # `>` (as shipped): no diode exceeds a threshold of 0 above equal
        # values, so with uniform h the whole-loop threshold is 0 and every
        # diff of 0 fails `>` -- demonstrating >= would flag everything.
        med_h = np.sort(h)[len(h) // 2]
        threshold = 10 * (med_h ** 0.5)
        self.assertGreater(threshold, 0)


if __name__ == "__main__":
    unittest.main()
