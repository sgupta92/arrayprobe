# SPDX-License-Identifier: BSD-3-Clause
"""``soda2_process_2d.pro`` ``round()`` -- ``arrayprobe_soda2.process_2d._idl_round``.

IDL ``ROUND`` is round-half-away-from-zero returning LONG; the port wrote it
as ``sign(x) * floor(|x| + 0.5)`` until pass 6. Measured under GDL (pass 5, item 4):
``round(2.5d) = 3``, ``round(-2.5d) = -3``, ``round(0.5d) = 1``,
``round(-0.5d) = -1`` -- the port agrees -- and ``round(0.49999999999999994d)
= 0``, where ``|x| + 0.5`` rounds up to 1.0 in double and the old form
returned 1. That input is one ULP below one half; no particle time reaches it
(``data_time`` is seconds from midnight at buffer resolution), but the port
now equals GDL there too, through the exact ``trunc``-based form (pass 6).
"""

from __future__ import annotations

import unittest

import numpy as np

from arrayprobe_soda2.process_2d import _idl_round


class TestIdlRoundHalfAway(unittest.TestCase):
    def test_exact_halves_round_away_from_zero(self):
        x = np.array([2.5, -2.5, 0.5, -0.5, 1.5, -1.5])
        self.assertEqual(_idl_round(x).tolist(), [3.0, -3.0, 1.0, -1.0, 2.0, -2.0])

    def test_numpy_round_would_disagree_on_halves(self):
        # The reason the helper exists: numpy rounds half to even.
        self.assertEqual(np.round(2.5), 2.0)

    def test_integers_and_negative_zero_survive(self):
        x = np.array([3.0, -3.0, 0.0, -0.0])
        self.assertEqual(_idl_round(x).tolist(), [3.0, -3.0, 0.0, 0.0])

    def test_one_ulp_below_a_half_rounds_down_like_gdl(self):
        # GDL: round(0.49999999999999994d) = 0; floor(x + 0.5) gives 1.
        self.assertEqual(float(_idl_round(np.array([0.49999999999999994]))[0]), 0.0)

    def test_the_carry_class_matches_gdl_on_both_signs(self):
        # GDL: round(-0.49999999999999994d) = 0, round(1.4999999999999998d) = 1.
        x = np.array([-0.49999999999999994, 1.4999999999999998])
        self.assertEqual(_idl_round(x).tolist(), [0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
