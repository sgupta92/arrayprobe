# SPDX-License-Identifier: BSD-3-Clause
"""S4-t (``poisson_spot_correct.pro:26-28``) -- ``poisson_fill_guard.guarded_poisson_spot_correct``.

The equivalence side is the whole point of this module: there is no input on which the guard
changes a written value (``correction``, ``zd``), and the test says so by sweeping, not by
assertion. The A/B side is the route, which is all S4-t's suggested edit changes.
"""
from __future__ import annotations

import unittest

import numpy as np
from arrayprobe_soda2.poisson_spot_correct import DEDGE_D0, ZEED, poisson_spot_correct

from arrayprobe_soda2_enhancements.poisson_fill_guard import guarded_poisson_spot_correct
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve

#: The GDL bank's three NaN-driving cases (run_soda2_poisson_spot_correct_bank.py),
#: (img_orig, img_fill), plus its untaken-branch case.
_BANK_DEGENERATE = {"fill_zero_orig_zero": (0, 0), "fill_zero_orig_positive": (5, 0),
                    "filled_smaller_than_orig": (100, 90), "orig_negative": (-1, 10)}


class Equivalence(unittest.TestCase):
    """The no-input case: guarded and port agree on correction and zd everywhere."""

    def test_every_integer_area_pair_up_to_120_gives_the_ports_values(self):
        n = 0
        for orig in range(0, 121):
            for fill in range(0, 121):
                p = poisson_spot_correct(orig, fill)
                g = guarded_poisson_spot_correct(orig, fill)
                self.assertEqual((p.correction, p.zd), (g.correction, g.zd), (orig, fill))
                self.assertEqual((type(p.correction), type(p.zd)),
                                 (type(g.correction), type(g.zd)))
                n += 1
        self.assertEqual(n, 121 * 121)

    def test_the_bank_degenerate_cases_give_the_ports_values(self):
        for case, (orig, fill) in _BANK_DEGENERATE.items():
            p = poisson_spot_correct(orig, fill)
            g = guarded_poisson_spot_correct(orig, fill)
            self.assertEqual((p.correction, p.zd), (g.correction, g.zd), case)

    def test_the_clamped_index_0_is_the_no_spot_default(self):
        """Why the values cannot differ: the clamp's landing entry IS :24-25's default."""
        self.assertEqual(DEDGE_D0[0], np.float32(1.0))
        self.assertEqual(ZEED[0], np.float32(0.0))

    def test_a_real_spot_is_the_ports_own_call(self):
        p = poisson_spot_correct(80, 100)
        g = guarded_poisson_spot_correct(80, 100)
        self.assertEqual((p.correction, p.zd, p.ip), (g.correction, g.zd, g.ip))
        self.assertGreater(p.ip, 0)


class ABConsequence(unittest.TestCase):
    """The route: a degenerate area no longer passes through 0/0 or sqrt(negative) and the
    clamp; the port-tooling ``ip`` says so (-1, branch not taken) where the port says 0."""

    def test_degenerate_area_takes_the_explicit_branch(self):
        for case in ("fill_zero_orig_zero", "fill_zero_orig_positive",
                     "filled_smaller_than_orig"):
            orig, fill = _BANK_DEGENERATE[case]
            self.assertEqual(poisson_spot_correct(orig, fill).ip, 0, case)
            self.assertEqual(guarded_poisson_spot_correct(orig, fill).ip, -1, case)

    def test_no_invalid_arithmetic_is_evaluated(self):
        with np.errstate(all="raise"):
            for orig, fill in _BANK_DEGENERATE.values():
                guarded_poisson_spot_correct(orig, fill)


class Registration(unittest.TestCase):
    def test_registered_opt_in_a14(self):
        spec = REGISTRY["poisson_fill_guard"]
        self.assertEqual(spec.finding, "S4-t")
        self.assertFalse(spec.default_on)
        self.assertFalse(resolve({})["poisson_fill_guard"])
        self.assertTrue(resolve({"poisson_fill_guard": True})["poisson_fill_guard"])
        self.assertFalse(resolve({"poisson_fill_guard": False})["poisson_fill_guard"])


if __name__ == "__main__":
    unittest.main()
