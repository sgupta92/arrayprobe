# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.fixraking`` (SODA-2 ``fixraking.pro``), read-derived
behaviours. The GDL golden bank (``gdl_oracle/run_soda2_fixraking_bank.py``)
is the next slice. Not wired into
``processbuffer_tail`` yet, so ``rakefix > 0`` is still refused there."""
from __future__ import annotations

import unittest

import numpy as np

from arrayprobe_soda2.fixraking import FixrakingUndefinedKernel, fixraking


def _rand(shape, seed):
    return np.random.default_rng(seed).integers(0, 2, shape).astype(np.uint8)


class ReadDerivedBehaviour(unittest.TestCase):
    def test_fixraking_10_mode0_is_identity(self):
        img = _rand((8, 6), 1)
        out = fixraking(img, 0)
        np.testing.assert_array_equal(out, img)
        self.assertIsNot(out, img)              # IDL value semantics: a copy

    def test_fixraking_37_copy_odd_from_even(self):
        img = _rand((8, 6), 2)
        out = fixraking(img, 1)
        np.testing.assert_array_equal(out[1::2], img[0::2])
        np.testing.assert_array_equal(out[0::2], img[0::2])
        self.assertEqual(out.dtype, img.dtype)

    def test_fixraking_19_odd_diode_count_leaves_last_diode(self):
        img = _rand((7, 5), 3)
        out = fixraking(img, 1)
        np.testing.assert_array_equal(out[6], img[6])
        np.testing.assert_array_equal(out[1:6:2], img[0:6:2])

    def test_fixraking_43_modetype_7_halts_undefined_kernel(self):
        with self.assertRaises(FixrakingUndefinedKernel):
            fixraking(_rand((8, 4), 4), 7)

    def test_fixraking_59_mode1_only_adds_on_odd_diodes(self):
        img = np.zeros((16, 10), np.uint8)
        img[4:12, 3:8] = 1
        img[1::2] = 0  # raked
        out = fixraking(img, 3)
        np.testing.assert_array_equal(out[0::2], img[0::2])
        self.assertTrue((out >= img).all())
        self.assertGreater(int(out[5:11:2, 3:8].sum()), 0)

    def test_fixraking_62_nothing_crosses_sets_last_element(self):
        img = np.zeros((8, 4), np.uint8)
        out = fixraking(img, 3)
        self.assertEqual(int(out.sum()), 1)
        self.assertEqual(int(out[-1, -1]), 1)


class PreservedDefects(unittest.TestCase):
    def test_fixraking_12_even_modetype_never_fixes_even_diodes(self):
        img = _rand((8, 6), 5)
        # copy mode 2: :38 dead, image unchanged
        np.testing.assert_array_equal(fixraking(img, 2), img)
        # convolution 4/6: no mask, even diodes may change too (:60 dead)
        img2 = np.zeros((16, 10), np.uint8)
        img2[4:12, 3:8] = 1
        img2[4:12:2, 5] = 0  # holes on even diodes
        for m in (4, 6):
            out = fixraking(img2, m)
            self.assertTrue((out[4:12:2, 5] == 1).any(), m)


if __name__ == "__main__":
    unittest.main()
