# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.find_radius`` against GDL running SODA-2's own `.pro`.

The golden is real output from `find_radius.pro` run unmodified under GDL
(`gdl_oracle/run_soda2_find_radius_bank.py`).
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from arrayprobe_soda2.find_radius import find_radius

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_find_radius_golden.json"


def _same(got: float, want: float) -> bool:
    if math.isnan(want):
        return math.isnan(got)
    if math.isinf(want):
        return math.isinf(got) and math.copysign(1, got) == math.copysign(1, want)
    return abs(got - want) <= 1e-9 * max(1.0, abs(want))


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it this "
                "suite would silently stop checking the port against IDL.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_the_bank_reaches_both_degenerate_regimes(self):
        """Collinear and coincident are NOT the same failure here -- one gives
        inf, the other nan -- so a bank reaching only one proves half of it."""
        names = {c["name"] for c in self.cases}
        for needed in ("collinear_x", "collinear_diag", "collinear_via_rounding",
                       "near_collinear_finite",
                       "two_coincident", "all_coincident"):
            self.assertIn(needed, names)

    def test_every_case_matches_idl(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                circ = find_radius(case["p1"], case["p2"], case["p3"])
                self.assertTrue(_same(circ.r, case["R"]),
                                f"r: got {circ.r!r}, want {case['R']!r}")
                self.assertTrue(_same(float(circ.center[0]), case["CX"]),
                                f"cx: got {circ.center[0]!r}, want {case['CX']!r}")
                self.assertTrue(_same(float(circ.center[1]), case["CY"]),
                                f"cy: got {circ.center[1]!r}, want {case['CY']!r}")
            checked += 1
        self.assertGreaterEqual(checked, 12)


class TheDegenerateValueTheCallerDependsOn(unittest.TestCase):
    """`min_circle_fast` branches on `finite(circ.r) eq 0`, so what this
    returns for a degenerate triangle IS its caller's branch condition."""

    def test_collinear_gives_positive_infinity_not_nan(self):
        """The caller's own comment says 'Radius will be NaN in this case'. It
        is +inf. `finite()` is false for both so the code is unaffected -- but a
        reader who trusted the comment and wrote a NaN-only guard would silently
        lose every collinear particle."""
        for p1, p2, p3 in (((0, 0), (1, 0), (2, 0)),
                           ((0, 0), (0, 1), (0, 2)),
                           ((0, 0), (1, 1), (2, 2))):
            with self.subTest(p3=p3):
                r = find_radius(p1, p2, p3).r
                self.assertTrue(math.isinf(r), f"want inf, got {r!r}")
                self.assertGreater(r, 0)
                self.assertFalse(math.isnan(r))

    def test_coincident_points_give_nan_instead(self):
        for p1, p2, p3 in (((0, 0), (0, 0), (1, 0)), ((3, 4), (3, 4), (3, 4))):
            with self.subTest(p1=p1):
                self.assertTrue(math.isnan(find_radius(p1, p2, p3).r))

    def test_a_collinear_by_rounding_triple_mixes_nan_and_inf_in_one_centre(self):
        """Centre comes back (nan, +inf), so a caller testing only `center[0]`
        concludes something different from one testing `center[1]`.

        Renamed 2026-09-12: this was called "nearly collinear", which it is not.
        At 1e-12 the third point contributes nothing -- d3 = 2 + 1e-24 rounds to
        2 -- so `c` is exactly 0 and this is the collinear regime reached by
        rounding. Mislabelling it hid the genuinely near-collinear case below."""
        circ = find_radius((0, 0), (1, 0), (2, 1e-12))
        self.assertTrue(math.isinf(circ.r))
        self.assertTrue(math.isnan(float(circ.center[0])))
        self.assertTrue(math.isinf(float(circ.center[1])))

    def test_a_genuinely_near_collinear_triple_returns_a_FINITE_absurd_radius(self):
        """The regime that matters, and that the mislabel above concealed.

        At 1e-6 the third point does contribute: `c` is non-zero, so the radius
        is **finite** -- and `min_circle_fast`'s `finite(circ.r) eq 0` fallback
        therefore never fires. It returns a circle of ~1e6 pixels for three
        points a micron apart, on a probe whose array is 128 diodes wide.

        Confirmed against GDL, not just computed here (`near_collinear_finite`
        in the golden: r = 999955.5527). Unreachable with integer pixel
        coordinates; reachable once `tas_adjust != 1` scales one axis, which is
        exactly how `aspect_ratio.pro` calls into this chain."""
        circ = find_radius((0, 0), (1, 0), (2, 1e-6))
        self.assertTrue(math.isfinite(circ.r), "this regime is finite, not inf")
        self.assertGreater(circ.r, 1e5)
        # ...and the fallback its caller relies on does NOT trigger here:
        self.assertTrue(math.isfinite(circ.r))

    def test_the_transition_between_the_two_regimes_is_a_rounding_boundary(self):
        """Not a smooth limit: 1e-9 is inf and 1e-6 is finite, because `c`
        goes from exactly-zero to non-zero. Pinned so the boundary cannot move
        unnoticed."""
        self.assertTrue(math.isinf(find_radius((0, 0), (1, 0), (2, 1e-9)).r))
        self.assertTrue(math.isfinite(find_radius((0, 0), (1, 0), (2, 1e-6)).r))

    def test_both_regimes_satisfy_the_callers_finite_test(self):
        """The property `min_circle_fast` actually relies on, asserted directly
        rather than inferred from the two cases above."""
        for pts in (((0, 0), (1, 0), (2, 0)), ((0, 0), (0, 0), (1, 0))):
            with self.subTest(pts=pts):
                self.assertFalse(math.isfinite(find_radius(*pts).r))


class WellConditionedGeometry(unittest.TestCase):
    def test_a_right_triangle_has_the_hypotenuse_as_diameter(self):
        circ = find_radius((0, 0), (1, 0), (0, 1))
        self.assertAlmostEqual(circ.r, math.sqrt(2) / 2, places=12)
        self.assertAlmostEqual(float(circ.center[0]), 0.5, places=12)
        self.assertAlmostEqual(float(circ.center[1]), 0.5, places=12)

    def test_it_is_translation_invariant(self):
        """The same triangle at the origin and at (10, 20) must give the same
        radius -- a property the golden covers with a matched pair."""
        a = find_radius((0, 0), (4, 0), (1, 0.5)).r
        b = find_radius((10, 20), (14, 20), (11, 20.5)).r
        self.assertAlmostEqual(a, b, places=9)

    def test_it_scales_linearly(self):
        big = find_radius((0, 0), (4, 0), (1, 0.5)).r
        small = find_radius((0, 0), (4e-6, 0), (1e-6, 0.5e-6)).r
        self.assertAlmostEqual(small * 1e6, big, places=6)

    def test_no_numpy_warning_escapes_on_a_degenerate_input(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            find_radius((0, 0), (1, 0), (2, 0))
            find_radius((0, 0), (0, 0), (1, 0))


if __name__ == "__main__":
    unittest.main()
