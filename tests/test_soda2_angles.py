# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.angles`` against GDL running SODA-2's own `.pro` files.

The golden is real output from `find_angle.pro` and `find_angle_array.pro` run
unmodified under GDL (`gdl_oracle/run_soda2_angles_bank.py`), so the two sides of
every assertion come from different places.
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.angles import NotDoublePrecision, find_angle, find_angle_array

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_angles_golden.json"


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it this "
                "suite would silently stop checking the port against IDL.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_the_bank_reaches_the_degeneracies_and_the_divergence(self):
        names = {c["name"] for c in self.cases}
        for needed in ("coincident_p2", "coincident_p3", "all_three_same",
                       "very_thin", "straight_through", "formulas_diverge"):
            self.assertIn(needed, names)

    def test_find_angle_matches_idl(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                got = find_angle(case["p1"], case["p2"], case["p3"])
                want = case["FA"]
                if math.isnan(want):
                    self.assertTrue(math.isnan(got))
                else:
                    self.assertAlmostEqual(got, want, places=12)
            checked += 1
        self.assertGreaterEqual(checked, 11)

    def test_find_angle_array_matches_idl(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                (x1, y1), (x2, y2), (x3, y3) = case["p1"], case["p2"], case["p3"]
                got = find_angle_array(float(x1), float(y1), float(x2), float(y2),
                                       float(x3), float(y3))
                want = case["FAA"]
                if math.isnan(want):
                    self.assertTrue(math.isnan(got))
                else:
                    self.assertAlmostEqual(got, want, places=12)
            checked += 1
        self.assertGreaterEqual(checked, 11)


class TheTwoFormulasAreNotInterchangeable(unittest.TestCase):
    """`min_circle_fast` takes one angle from each and subtracts both from pi.
    Collapsing them onto one helper would be a tidy-up that changes which
    circle SODA-2 returns, so the difference is pinned rather than left to a
    comment."""

    def test_they_disagree_on_an_ordinary_triangle(self):
        p1 = (-0.10457498994259659, -0.045437730029078215)
        p2 = (-1.3877245648047183, -0.397665430905442)
        p3 = (0.2694708846309524, 0.057239101479313256)
        a = find_angle(p1, p2, p3)
        b = find_angle_array(p1[0], p1[1], p2[0], p2[1], p3[0], p3[1])
        self.assertNotEqual(a, b, "the two formulas should differ here")
        self.assertLess(abs(a - b), 1e-8, "but only in the last bits")

    def test_they_agree_on_exactly_representable_geometry(self):
        """The reason a hand-picked case list misses the divergence: right
        angles, equilaterals and collinear sets agree bit-for-bit."""
        for p1, p2, p3 in (((0, 0), (1, 0), (0, 1)),
                           ((0, 0), (1, 0), (2, 0)),
                           ((0, 0), (1, 0), (-1, 0))):
            with self.subTest(p3=p3):
                a = find_angle(p1, p2, p3)
                b = find_angle_array(float(p1[0]), float(p1[1]), float(p2[0]),
                                     float(p2[1]), float(p3[0]), float(p3[1]))
                self.assertEqual(a, b)


class DegeneraciesAreReproducedNotGuarded(unittest.TestCase):
    def test_a_thin_angle_collapses_to_exactly_zero(self):
        """True angle ~1e-9 rad; `acos` cannot resolve below ~1.5e-8, so both
        routines return exactly 0. SODA-2's answers depend on this, so the port
        must not 'improve' it with atan2."""
        self.assertEqual(find_angle((0, 0), (1, 0), (1, 1e-9)), 0.0)
        self.assertEqual(find_angle_array(0.0, 0.0, 1.0, 0.0, 1.0, 1e-9), 0.0)

    def test_coincident_points_give_nan(self):
        self.assertTrue(math.isnan(find_angle((0, 0), (0, 0), (1, 0))))
        self.assertTrue(math.isnan(find_angle_array(0.0, 0.0, 0.0, 0.0, 1.0, 0.0)))

    def test_no_numpy_warning_escapes(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            find_angle((0, 0), (0, 0), (1, 0))
            find_angle_array(0.0, 0.0, 0.0, 0.0, 1.0, 0.0)


class TheTypeGuardIsReproduced(unittest.TestCase):
    def test_integer_input_is_refused(self):
        """`typename(x1) ne 'DOUBLE'` -> `stop`. Promoting silently would answer
        a question the original refuses to answer."""
        with self.assertRaises(NotDoublePrecision):
            find_angle_array(0, 0, 1, 0, 0, 1)

    def test_float_input_is_accepted(self):
        self.assertAlmostEqual(
            find_angle_array(0.0, 0.0, 1.0, 0.0, 0.0, 1.0), math.pi / 2, places=12)

    def test_the_vertex_may_be_an_array(self):
        """`x1 and y1 can be an array of points`, per the source's own comment --
        which is how `min_circle_fast` calls it, once per candidate R."""
        x1 = np.array([0.0, 0.0])
        y1 = np.array([0.0, 1.0])
        out = find_angle_array(x1, y1, 1.0, 0.0, 0.0, 1.0)
        self.assertEqual(np.shape(out), (2,))
        self.assertAlmostEqual(float(out[0]), math.pi / 2, places=12)


class AspectRatioPathIsFloat(unittest.TestCase):
    """aspect_ratio.pro:35-38 calls find_angle on FLOAT points. Expected
    values measured under GDL 2026-10-04 (a GDL probe script): angP=angQ=
    0.000976562500, angR=3.139579534531, vertex 0 (float64 picks 1)."""

    def test_float32_angles_and_vertex_match_gdl(self) -> None:
        from arrayprobe_soda2.angles import find_angle_f32
        x, y = [109, 101, 105], np.float32([10, 99, 54])
        p, q, r = (np.array([x[i], y[i]], np.float32) for i in range(3))
        angs = [find_angle_f32(p, r, q), find_angle_f32(q, r, p), find_angle_f32(r, q, p)]
        bits = [int(np.float32(a).view(np.uint32)) for a in angs]
        self.assertEqual(bits, [int(np.float32(0.0009765625).view(np.uint32))] * 2
                         + [int(np.float32(3.139579534531).view(np.uint32))])
        self.assertEqual(int(np.argmin(angs)), 0)


if __name__ == "__main__":
    unittest.main()
