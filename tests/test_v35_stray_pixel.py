# SPDX-License-Identifier: BSD-3-Clause
"""Step 1 of the stray-pixel correction: the pure function on synthetic images.


"""
import unittest

import numpy as np

from arrayprobe_uiops.stray_pixel import remove_stray_pixels


def disc(shape, centre, radius):
    rr, cc = np.ogrid[:shape[0], :shape[1]]
    return ((rr - centre[0]) ** 2 + (cc - centre[1]) ** 2 <= radius ** 2).astype(np.uint8)


def extent(c):
    rr, cc = np.nonzero(c)
    return max(rr.max() - rr.min() + 1, cc.max() - cc.min() + 1)


class TestDropPlusStrayPixel(unittest.TestCase):
    def test_far_stray_pixel_is_removed_and_the_drop_keeps_its_size(self):
        drop = disc((80, 128), (10, 30), 8)              # 17-px-wide drop
        c = drop.copy()
        c[70, 100] = 1                                   # one stray pixel, far away
        self.assertGreater(extent(c), 60)                # enclosing size is inflated
        cleaned, rec = remove_stray_pixels(c)
        np.testing.assert_array_equal(cleaned, drop)
        self.assertEqual(extent(cleaned), 17)
        self.assertEqual(rec["removed"], 1)
        self.assertEqual(rec["pieces"], 1)
        self.assertEqual(rec["positions"], [(70, 100)])
        self.assertEqual(c[70, 100], 1, "the input is not modified")

    def test_several_strays_of_up_to_two_pixels_are_all_removed(self):
        drop = disc((80, 128), (40, 60), 6)
        c = drop.copy()
        c[2, 2] = 1
        c[75, 120] = c[75, 121] = 1
        cleaned, rec = remove_stray_pixels(c)
        np.testing.assert_array_equal(cleaned, drop)
        self.assertEqual(rec["removed"], 3)
        self.assertEqual(rec["pieces"], 2)


class TestUntouched(unittest.TestCase):
    def assertUntouched(self, c, **kw):
        cleaned, rec = remove_stray_pixels(c, **kw)
        self.assertIs(cleaned, c)
        self.assertEqual(rec["removed"], 0)

    def test_two_real_drops_are_untouched(self):
        c = disc((80, 128), (15, 20), 6) | disc((80, 128), (60, 100), 5)
        self.assertUntouched(c)

    def test_a_speck_within_the_gap_of_the_drop_is_untouched(self):
        c = disc((80, 128), (20, 20), 6)
        c[20, 20 + 6 + 5] = 1                            # 4 empty diodes from the edge
        self.assertUntouched(c)

    def test_the_same_speck_is_removed_when_the_gap_is_smaller(self):
        c = disc((80, 128), (20, 20), 6)
        c[20, 31] = 1
        cleaned, rec = remove_stray_pixels(c, gap=3)
        self.assertEqual(rec["removed"], 1)

    def test_scattered_specks_with_no_main_piece_are_untouched(self):
        c = np.zeros((80, 128), dtype=np.uint8)
        c[5, 5] = c[40, 60] = 1
        c[70:72, 100:102] = 1                            # 4 px, below the main-piece floor
        self.assertUntouched(c)

    def test_a_single_piece_and_an_empty_image_are_untouched(self):
        self.assertUntouched(disc((40, 40), (20, 20), 5))
        self.assertUntouched(np.zeros((10, 10), dtype=np.uint8))

    def test_a_three_pixel_stray_is_not_a_stray_at_the_default(self):
        c = disc((80, 128), (20, 20), 6)
        c[70, 100:103] = 1
        self.assertUntouched(c)


class TestSameGroupingAsTheTriagePage(unittest.TestCase):
    def test_groups_equal_triage_context_piece_groups(self):
        from arrayprobe.triage_context import piece_groups
        from arrayprobe_uiops.stray_pixel import _groups

        rng = np.random.default_rng(699)
        for _ in range(40):
            c = rng.random((30, 32)) < 0.04
            for gap in (0, 3, 8, 12):
                ours = sorted(m.tobytes() for m in _groups(c, gap))
                theirs = sorted(m.tobytes() for m in piece_groups(c, gap))
                self.assertEqual(ours, theirs)


if __name__ == "__main__":
    unittest.main()
