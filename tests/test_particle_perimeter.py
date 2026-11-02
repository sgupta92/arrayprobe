# SPDX-License-Identifier: BSD-3-Clause
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from particle_perimeter import (
    BACKGROUND,
    SHADOWED,
    particle_perimeter,
    particle_perimeter_from_mask,
    particle_perimeter_setbased,
)


class TestParticlePerimeterHandTraced(unittest.TestCase):
    def test_single_isolated_pixel(self):
        img = [[SHADOWED]]
        self.assertEqual(particle_perimeter(img), 1)

    def test_2x2_all_shadowed_block(self):
        # Every pixel in a 2x2 block touches the background pad on at
        # least one side (no pixel has all 4 neighbors shadowed), so
        # all 4 pixels count as boundary.
        img = [[SHADOWED, SHADOWED], [SHADOWED, SHADOWED]]
        self.assertEqual(particle_perimeter(img), 4)

    def test_3x3_all_shadowed_block_has_one_interior_pixel(self):
        # Hand trace: the center pixel's 4 neighbors are all shadowed
        # (interior, not boundary); the other 8 pixels each touch
        # background on at least one side (boundary). Perimeter = 8.
        img = [[SHADOWED] * 3 for _ in range(3)]
        self.assertEqual(particle_perimeter(img), 8)

    def test_no_shadowed_pixels(self):
        img = [[BACKGROUND, BACKGROUND], [BACKGROUND, BACKGROUND]]
        self.assertEqual(particle_perimeter(img), 0)

    def test_single_row_line(self):
        # A 1x3 line: every pixel touches background above/below, so
        # all 3 count.
        img = [[SHADOWED, SHADOWED, SHADOWED]]
        self.assertEqual(particle_perimeter(img), 3)


class TestParticlePerimeterCrossValidation(unittest.TestCase):
    """Cross-check two independently-written implementations against
    each other -- the strongest available signal of correctness given
    no MATLAB reference output is available to diff against.
    """

    def test_hand_traced_cases_agree(self):
        cases = [
            [[SHADOWED]],
            [[SHADOWED, SHADOWED], [SHADOWED, SHADOWED]],
            [[SHADOWED] * 3 for _ in range(3)],
            [[BACKGROUND, BACKGROUND], [BACKGROUND, BACKGROUND]],
            [[SHADOWED, SHADOWED, SHADOWED]],
        ]
        for img in cases:
            self.assertEqual(
                particle_perimeter(img), particle_perimeter_setbased(img), msg=img
            )

    def test_l_shape(self):
        img = [
            [SHADOWED, BACKGROUND, BACKGROUND],
            [SHADOWED, BACKGROUND, BACKGROUND],
            [SHADOWED, SHADOWED, SHADOWED],
        ]
        self.assertEqual(particle_perimeter(img), particle_perimeter_setbased(img))

    def test_random_images_agree(self):
        rng = random.Random(42)
        for _ in range(200):
            rows = rng.randint(1, 8)
            cols = rng.randint(1, 8)
            img = [
                [SHADOWED if rng.random() < 0.5 else BACKGROUND for _ in range(cols)]
                for _ in range(rows)
            ]
            self.assertEqual(
                particle_perimeter(img),
                particle_perimeter_setbased(img),
                msg=img,
            )

    def test_5x5_solid_block_interior_count(self):
        # 5x5 solid block: 3x3 interior (9 pixels) all-shadowed neighbors
        # -> not boundary; remaining 16 perimeter pixels are boundary.
        img = [[SHADOWED] * 5 for _ in range(5)]
        self.assertEqual(particle_perimeter(img), 16)
        self.assertEqual(particle_perimeter_setbased(img), 16)


class TestParticlePerimeterFromMask(unittest.TestCase):
    def test_matches_direct_call(self):
        mask = [[True, False], [True, True]]
        img = [[SHADOWED, BACKGROUND], [SHADOWED, SHADOWED]]
        self.assertEqual(particle_perimeter_from_mask(mask), particle_perimeter(img))


if __name__ == "__main__":
    unittest.main()
