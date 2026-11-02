# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.binary_dof`` against GDL running SODA-2's own `.pro`
(zero-ring embedded), plus an independent
coordinate-enumeration cross-check.

Golden: ``gdl_oracle/run_soda2_binary_dof_bank.py``. Float32 outputs are
compared as 8-hex-digit IEEE-754 bit patterns.
"""
from __future__ import annotations

import json
import struct
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

from arrayprobe_soda2.binary_dof import binary_dof

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_binary_dof_golden.json"


def _hex32(v) -> str:
    return f"{struct.unpack('<I', struct.pack('<f', float(v)))[0]:08X}"


def _image_from_pixels(pixels: list[list[int]], nslices: int) -> np.ndarray:
    img = np.zeros((nslices, 128), dtype=np.uint8)
    for d, s in pixels:
        img[s, d] = 1
    return img


def _exact_neighbor_count(pixels: set[tuple[int, int]]) -> Fraction:
    """Independent third side: explicit 8-neighbour coordinate enumeration
    in exact rational arithmetic (diagonal weight 7/10), not the port's
    shifted-array algorithm."""
    weights = {}
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 == dc:
                continue
            weights[(dr, dc)] = Fraction(7, 10) if dr != 0 and dc != 0 else Fraction(1)
    total = Fraction(0)
    for (d, s) in pixels:
        for (dd, ds), w in weights.items():
            if (d + dd, s + ds) in pixels:
                total += w
    return total


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking the port against GDL.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_the_bank_has_enough_cases(self):
        self.assertGreaterEqual(len(self.cases), 15)

    def test_the_bank_reaches_the_named_regimes(self):
        names = {c["name"] for c in self.cases}
        for needed in ("nine_3x3", "blank", "single_pixel", "two_diagonal"):
            self.assertIn(needed, names)

    def test_value_two_is_halted(self):
        case = next(c for c in self.cases if c["name"] == "value_two")
        self.assertEqual(case["status"], "HALTED")

    def test_every_ok_case_matches_gdl_exactly(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                img = _image_from_pixels(case["pixels"], case["nslices"])
                res = binary_dof(img)
                self.assertEqual(res.dof, int(case["DOF"]),
                                  f"dof mismatch for {case['name']}")
                self.assertEqual(_hex32(res.neighbor_count), case["NC"],
                                  f"neighbor_count mismatch for {case['name']}")
                self.assertEqual(float(res.area), float(case["AREA"]),
                                  f"area mismatch for {case['name']}")
            checked += 1
        self.assertGreaterEqual(checked, 15)


class IndependentCoordinateEnumeration(unittest.TestCase):
    """Third side: coordinate enumeration vs the port's shifted-array
    algorithm -- different algorithm, same answer."""

    def test_neighbor_count_matches_exact_enumeration(self):
        cases = json.loads(GOLDEN.read_text(encoding="utf-8"))
        checked = 0
        for case in cases:
            if case["status"] != "OK":
                continue
            pixels = {(d, s) for d, s in case["pixels"]}
            if not pixels:
                continue
            exact = _exact_neighbor_count(pixels)
            img = _image_from_pixels(case["pixels"], case["nslices"])
            res = binary_dof(img)
            self.assertAlmostEqual(float(res.neighbor_count), float(exact),
                                    places=4, msg=case["name"])
            # exact threshold decision must also agree, per case's area.
            area = len(pixels)
            thr = {1: None, 2: 2, 3: 5, 4: 8, 5: 11, 6: 17}.get(area, area * 3)
            expected_dof = 1 if area == 1 else int(thr is not None and exact >= thr)
            self.assertEqual(res.dof, expected_dof, case["name"])
            checked += 1
        self.assertGreaterEqual(checked, 10)


class PinnedSemantics(unittest.TestCase):
    def test_unpadded_and_zero_ring_embedded_images_agree(self):
        for nslices in (1, 2, 3):
            img = np.zeros((nslices, 128), dtype=np.uint8)
            img[0, 5] = 1
            if nslices > 1:
                img[nslices - 1, 6] = 1
            a = binary_dof(img)
            b = binary_dof(np.pad(img, 1))
            self.assertEqual(a.dof, b.dof)
            self.assertEqual(_hex32(a.neighbor_count), _hex32(b.neighbor_count))

    def test_a_blank_image_is_accepted(self):
        img = np.zeros((2, 128), dtype=np.uint8)
        res = binary_dof(img)
        self.assertEqual(res.dof, 1)
        self.assertEqual(res.area, 0)

    def test_a_value_above_one_raises(self):
        img = np.zeros((2, 128), dtype=np.uint8)
        img[0, 0] = 2
        with self.assertRaises(ValueError) as ctx:
            binary_dof(img)
        self.assertIn("binary_dof.pro:5", str(ctx.exception))

    def test_neighbor_count_is_float32(self):
        img = np.zeros((2, 128), dtype=np.uint8)
        img[0, 5] = 1
        img[1, 5] = 1
        res = binary_dof(img)
        self.assertEqual(res.neighbor_count.dtype, np.float32)

    def test_area_one_accepts_without_a_count(self):
        img = np.zeros((1, 128), dtype=np.uint8)
        img[0, 0] = 1
        res = binary_dof(img)
        self.assertEqual(res.dof, 1)


if __name__ == "__main__":
    unittest.main()
