# SPDX-License-Identifier: BSD-3-Clause
"""The v3.5 engine's default-on corrections for two data-destroying upstream defects --
zero sample volume and the duplicated or skipped S4 second."""
import unittest

import numpy as np

from arrayprobe_uiops import sizedist


class TestFixTimeGrid(unittest.TestCase):
    def test_duplicate_moves_into_the_skipped_second(self):
        fixed, n = sizedist.fix_time_grid([120000, 120001, 120001, 120003, 120004])
        np.testing.assert_array_equal(fixed, [120000, 120001, 120002, 120003, 120004])
        self.assertEqual(n, 1)

    def test_duplicate_moves_down_when_the_hole_is_before(self):
        fixed, n = sizedist.fix_time_grid([120000, 120002, 120002, 120003])
        np.testing.assert_array_equal(fixed, [120000, 120001, 120002, 120003])
        self.assertEqual(n, 1)

    def test_duplicate_without_a_hole_is_left(self):
        t = [120000, 120001, 120001, 120002]
        fixed, n = sizedist.fix_time_grid(t)
        np.testing.assert_array_equal(fixed, t)
        self.assertEqual(n, 0)

    def test_clean_grid_unchanged(self):
        t = np.array([235958, 235959, 0, 1], dtype=float)
        fixed, n = sizedist.fix_time_grid(t)
        np.testing.assert_array_equal(fixed, t)
        self.assertEqual(n, 0)

    def test_across_midnight(self):
        fixed, n = sizedist.fix_time_grid([235958, 235959, 235959, 1])
        np.testing.assert_array_equal(fixed, [235958, 235959, 0, 1])
        self.assertEqual(n, 1)


class TestZeroSvSignature(unittest.TestCase):
    def test_default_is_off(self):
        import inspect
        self.assertIs(inspect.signature(sizedist.run).parameters["zero_sv_nan"].default, False)


if __name__ == "__main__":
    unittest.main()
