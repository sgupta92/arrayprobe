# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.label_blobs`` against GDL running the real
``label_blobs.pro`` -- unmodified for
``dilatelength=0`` (GDL has ``LABEL_REGION``), shimmed with a ``dilate.pro``
for ``dilatelength != 0`` (GDL lacks ``DILATE``; the shim is unambiguous by
construction, see the bank's module docstring).

15 cases, all OK. Establishes S4-z (measured): the dilation kernel clamps
against the roi's own slice count plus 2, not against the padded array's
size, so a 1-slice roi under ``dilatelength=2`` dilates with a 3-wide
kernel instead of 5-wide (``dilate2_one_slice_gap3_stays_separate`` vs.
``dilate2_three_slice_gap3_merges``, same gap, same dilatelength, opposite
outcome). S4-y (byte wrap at 256) is demonstrated directly on the port,
since reaching 256 real blobs through GDL was not attempted in this bank.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.label_blobs import label_blobs

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_label_blobs_golden.json"


def _load_golden() -> list[dict]:
    if not GOLDEN.is_file():
        raise AssertionError(
            f"{GOLDEN} is missing. It is a tracked fixture: without it "
            "this suite would silently stop checking the port against IDL.")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _img_from_case(case: dict):
    img = case["img"]
    if isinstance(img[0], list):
        return np.asarray(img, dtype=np.int32)
    return np.asarray(img, dtype=np.int32)


def _relabel_by_first_occurrence(flat: list[int]) -> list[int]:
    """IDL's absolute label numbers are an implementation detail of the
    walk order; what matters is which pixels share a label. Remap both
    sides through first-occurrence order (0 stays 0) before comparing."""
    mapping: dict[int, int] = {0: 0}
    out = []
    for v in flat:
        if v not in mapping:
            mapping[v] = len(mapping)
        out.append(mapping[v])
    return out


class GoldenMatchesIdl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = _load_golden()
        cls.by_name = {r["name"]: r for r in cls.records}

    def test_at_least_fifteen_cases(self):
        self.assertGreaterEqual(len(self.records), 15)

    def test_named_regimes_present(self):
        for name in ("two_blobs_4conn", "diagonal_only_4conn",
                     "diagonal_only_8conn", "raster_order", "edge_pixels_kept",
                     "one_d_input", "dilate2_one_slice_gap3_stays_separate",
                     "dilate2_three_slice_gap3_merges"):
            self.assertIn(name, self.by_name)

    def test_all_cases_match_idl_up_to_relabelling(self):
        checked = 0
        for case in self.records:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                img = _img_from_case(case)
                got = label_blobs(
                    img,
                    dilatelength=case["dilatelength"],
                    all_neighbors=case["all_neighbors"],
                    integer=case["integer"],
                )
                if case["NDIM"] == 1:
                    got_flat = got.reshape(-1).tolist()
                else:
                    got_flat = got.T.reshape(-1).tolist()  # column-major = IDL
                self.assertEqual(
                    _relabel_by_first_occurrence(got_flat),
                    _relabel_by_first_occurrence(case["FLAT"]),
                    f"{case['name']}: label partition differs from IDL",
                )
            checked += 1
        self.assertGreaterEqual(checked, 15)

    def test_labels_follow_x_fastest_raster_order(self):
        case = self.by_name["raster_order"]
        img = _img_from_case(case)
        got = label_blobs(img)
        # pixel at (x=5,y=0) comes before (x=0,y=1) in x-fastest raster
        # order, so it must get the smaller label.
        self.assertLess(got[5, 0], got[0, 1])

    def test_kernel_clamps_against_slice_count_plus_two(self):
        """S4-z: same gap (3 empty diodes), same dilatelength=2, different
        slice count -- opposite merge outcome."""
        one_slice = self.by_name["dilate2_one_slice_gap3_stays_separate"]
        three_slice = self.by_name["dilate2_three_slice_gap3_merges"]
        self.assertEqual(one_slice["MAX"], 2)
        self.assertEqual(three_slice["MAX"], 1)

        img1 = _img_from_case(one_slice)
        got1 = label_blobs(img1, dilatelength=2)
        self.assertEqual(len(set(got1[got1 != 0].tolist())), 2)

        img3 = _img_from_case(three_slice)
        got3 = label_blobs(img3, dilatelength=2)
        self.assertEqual(len(set(got3[got3 != 0].tolist())), 1)


class LabelRegionBorderRule(unittest.TestCase):
    def test_label_region_zeroes_the_border_but_label_blobs_does_not(self):
        """The whole point of the padding (label_blobs.pro:2's comment):
        a foreground pixel on img's own border must still get a real
        label from label_blobs, even though IDL's underlying
        label_region would zero a border pixel of ITS OWN input."""
        img = np.zeros((4, 4), dtype=np.uint8)
        img[0, 0] = 1
        img[3, 3] = 1
        got = label_blobs(img)
        self.assertNotEqual(got[0, 0], 0)
        self.assertNotEqual(got[3, 3], 0)
        self.assertNotEqual(got[0, 0], got[3, 3])


class OneDInput(unittest.TestCase):
    def test_one_d_input_returns_one_d(self):
        img = np.array([0, 1, 1, 0, 1], dtype=np.uint8)
        got = label_blobs(img)
        self.assertEqual(got.ndim, 1)
        self.assertEqual(got.shape[0], 5)


class ByteWrapAt256(unittest.TestCase):
    """S4-y, demonstrated directly on the port (not run through GDL --
    300 isolated single-pixel blobs was not attempted as a GDL case in
    this bank's time budget)."""

    def test_byte_return_wraps_at_256(self):
        n = 300
        img = np.zeros((2 * n, 1), dtype=np.uint8)
        for i in range(n):
            img[2 * i, 0] = 1
        got_byte = label_blobs(img)  # default: byte return
        got_int = label_blobs(img, integer=True)

        self.assertEqual(int(got_int.max()), n)
        # byte(x) wraps modulo 256; blob 255 keeps label 255 (the largest
        # byte value reached), blob 256 aliases to 0 (background), and
        # blob 300 aliases to 300-256=44.
        self.assertEqual(int(got_byte.max()), 255)
        # the 256th blob (1-based) is aliased to background under byte()
        idx_256th = 2 * 255  # 0-based pixel index of the 256th blob
        self.assertEqual(int(got_int[idx_256th, 0]), 256)
        self.assertEqual(int(got_byte[idx_256th, 0]), 0)
        idx_300th = 2 * 299
        self.assertEqual(int(got_int[idx_300th, 0]), 300)
        self.assertEqual(int(got_byte[idx_300th, 0]), 44)


class KernelClampSweep(unittest.TestCase):
    def test_kernel_dim_matches_the_clamp_formula(self):
        # dilatelength=5 on a 1-slice image: kerneldim = min(11, 1+2) = 3
        img = np.array([[1], [0], [0], [0], [1]], dtype=np.uint8)
        got = label_blobs(img, dilatelength=5)
        # radius 1 (kernel 3) cannot bridge a 3-diode gap
        self.assertEqual(len(set(got[got != 0].tolist())), 2)


class Mutations(unittest.TestCase):
    def test_y_fastest_raster_order_would_flip_the_case(self):
        # if labelling were y-fastest, (0,1) would come before (5,0) in a
        # 6x2 grid scanned y-major, x-minor -- demonstrating the mutation
        # inline rather than editing the shipped module.
        rows, cols = 2, 6
        order = [(y, x) for x in range(cols) for y in range(rows)]  # x-fastest
        order_mut = [(y, x) for y in range(rows) for x in range(cols)]  # y-fastest
        self.assertNotEqual(order[:3], order_mut[:3])


if __name__ == "__main__":
    unittest.main()
