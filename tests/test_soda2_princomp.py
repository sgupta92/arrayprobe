# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.princomp`` against GDL running SODA-2's own ``princomp.pro``.

The golden is real output from the vendored `.pro` run unmodified under GDL
(`gdl_oracle/run_soda2_princomp_bank.py`), so the two sides of every assertion
come from different places: this port's arithmetic, and IDL's.

The cases were chosen for `princomp`'s two unguarded divisions rather than for
happy-path coverage -- see the module docstring of the port for the four
distinct degenerate outcomes and why collapsing them would be wrong.
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.princomp import PrincompLengthMismatch, princomp

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_princomp_golden.json"


class AgainstTheGdlGolden(unittest.TestCase):
    """Tracked golden, so this runs on a fresh clone without GDL installed."""

    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture, not a local "
                "artefact: without it this suite would silently stop checking "
                "the port against IDL at all.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_the_bank_covers_the_degenerate_divisions(self):
        """A bank of well-conditioned fits would pass while proving nothing
        about the two divisions that actually differ between implementations."""
        names = {c["name"] for c in self.cases}
        for needed in ("horizontal", "vertical", "symmetric_cross",
                       "single_point", "negative_corr"):
            self.assertIn(needed, names)
        self.assertGreaterEqual(len(self.cases), 10)

    def test_every_case_matches_idl(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                c, corr = princomp(case["x"], case["y"])
                for got, want, label in ((c[0], case["C0"], "c0"),
                                         (c[1], case["C1"], "c1"),
                                         (corr, case["CORR"], "corr")):
                    if math.isnan(want):
                        self.assertTrue(math.isnan(got), f"{label}: want NaN, got {got}")
                    elif math.isinf(want):
                        self.assertEqual(math.copysign(1, got), math.copysign(1, want),
                                         f"{label}: infinity of the wrong sign")
                        self.assertTrue(math.isinf(got), f"{label}: want {want}, got {got}")
                    else:
                        self.assertAlmostEqual(got, want, places=9, msg=label)
            checked += 1
        self.assertGreaterEqual(checked, 10)


class TheDegenerateOutcomesAreDistinct(unittest.TestCase):
    """The four zero-``sxy`` cases do NOT share an answer, and that is the
    whole point of pinning them: an implementation that returned one
    'degenerate' result for all of them would be wrong about three."""

    def test_a_symmetric_cross_gives_nan_slope_but_zero_correlation(self):
        c, corr = princomp([-1, 1, 0, 0], [0, 0, -1, 1])
        self.assertTrue(math.isnan(c[1]), "xlam == sxx exactly, so 0/0")
        self.assertEqual(corr, 0.0, "sxy is 0 over a positive sqrt(sxx*syy)")

    def test_a_symmetric_parabola_gives_infinite_slope_and_zero_correlation(self):
        c, corr = princomp([-2, -1, 0, 1, 2], [4, 1, 0, 1, 4])
        self.assertEqual(c[1], math.inf, "xlam - sxx is positive over 0")
        self.assertTrue(math.isnan(c[0]), "ymean - inf*0 is NaN")
        self.assertEqual(corr, 0.0)

    def test_a_vertical_line_gives_a_signed_infinity(self):
        c, corr = princomp([3, 3, 3, 3], [1, 2, 3, 4])
        self.assertEqual(c[1], math.inf)
        self.assertEqual(c[0], -math.inf)
        self.assertTrue(math.isnan(corr), "0 / sqrt(0) is 0/0")

    def test_a_horizontal_line_is_nan_throughout(self):
        c, corr = princomp([1, 2, 3, 4], [5, 5, 5, 5])
        self.assertTrue(math.isnan(c[0]) and math.isnan(c[1]) and math.isnan(corr))


class RefusalsAndConventions(unittest.TestCase):
    def test_a_length_mismatch_raises_rather_than_returning(self):
        """`princomp.pro` prints and then `stop`s -- it produces no value on
        this path, so the port must not invent one."""
        with self.assertRaises(PrincompLengthMismatch):
            princomp([1, 2, 3], [1, 2])

    def test_it_does_not_emit_numpy_warnings_on_the_degenerate_cases(self):
        """A caller running under `-W error` must not have a zero division
        turned into an exception the original never raises."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            princomp([1, 2, 3, 4], [5, 5, 5, 5])
            princomp([3, 3, 3, 3], [1, 2, 3, 4])

    def test_the_fit_is_orthogonal_not_least_squares(self):
        """On a point set where the two differ, `princomp` must give the
        perpendicular answer. Reversing x and y must mirror the slope, which
        is the property an ordinary least-squares fit does NOT have."""
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.1, 0.9, 2.2, 2.8]
        c_fwd, _ = princomp(x, y)
        c_rev, _ = princomp(y, x)
        self.assertAlmostEqual(c_fwd[1] * c_rev[1], 1.0, places=9)
        ols = np.polyfit(np.asarray(x), np.asarray(y), 1)[0]
        self.assertNotAlmostEqual(c_fwd[1], ols, places=12)


if __name__ == "__main__":
    unittest.main()
