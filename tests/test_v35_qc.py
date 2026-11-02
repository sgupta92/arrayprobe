# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.qc`` -- the ``iQC=1`` denoise pass (Part C).

Unit level, against the vendored file's own documented semantics
(``imgProc_sm.m:801-846``), pinned here because the existing Octave golden
fixture (``run_v35_imgproc_bank.py``) never produces a WRITTEN
``subparticle_num > 1`` -- every multi-component particle it contains merges
back to 1 under the ``:840-842`` ``dist_min < 5`` rule. These tests are the
only place the ``num_subparticles > 1`` branch (``:813-839``) and the
``:835`` order-statistic are exercised end to end.
"""

from __future__ import annotations

import unittest

import numpy as np

from arrayprobe_uiops import qc as qc_module
from arrayprobe_uiops.qc import qc_image


def _canvas(rows: int, cols: int) -> np.ndarray:
    return np.zeros((rows, cols), dtype=bool)


def _char(mask: np.ndarray) -> np.ndarray:
    """MATLAB's own convention: ``'0'`` (48) shadowed, ``'1'`` (49) lit --
    the same one :func:`arrayprobe.matlab_compat.dec2bin_concat` produces."""
    return np.where(mask, np.uint8(ord("0")), np.uint8(ord("1")))


class TestBranchTwoNoSurvivor(unittest.TestCase):
    def test_fewer_than_five_pixels_is_branch_two_and_c_is_untouched(self):
        """``:804-807``: a 4-pixel speck can never reach ``min(5, ...)``
        pixels, so ``bwareaopen`` empties it and ``c`` is returned unchanged
        (the ``continue`` at ``:805`` is commented out in the vendored file --
        the branch falls through to the SAME ``c``, not a rebuilt one)."""
        mask = _canvas(4, 10)
        mask[1:3, 1:3] = True  # a 2x2 = 4-pixel speck
        c = _char(mask)
        c_after, num_sub, dist_min = qc_image(c)
        self.assertEqual(num_sub, 0)
        self.assertEqual(dist_min, 0)
        np.testing.assert_array_equal(c_after, c)


class TestOneComponent(unittest.TestCase):
    def test_one_component_writes_one_and_zero(self):
        """``:809-810`` / ``:837``: a single surviving component writes
        ``num_subparticles=1``, ``dist_min=0``, and the rebuilt ``c`` is
        pixel-identical to the input (nothing was noise)."""
        mask = _canvas(5, 10)
        mask[1:4, 1:4] = True  # 3x3 = 9 pixels, survives P = max(5, floor(0.45)) = 5
        c = _char(mask)
        c_after, num_sub, dist_min = qc_image(c)
        self.assertEqual(num_sub, 1)
        self.assertEqual(dist_min, 0)
        np.testing.assert_array_equal(c_after, c)


def _two_blocks(gap: int, rows: int = 5, block: int = 3) -> np.ndarray:
    """Two ``block x block`` squares in the same rows, ``gap`` empty columns
    apart. ``imgProc_sm.m:833``'s chessboard ``min(darr_a+darr_b)-1`` reduces,
    for two axis-aligned same-row rectangles, to exactly the count of empty
    columns strictly between them -- derived from the identity
    ``min_p(d(p,A)+d(p,B)) = d(A,B)`` for a metric ``d`` (achieved at
    ``p`` = the nearer of the two closest points), so this helper's ``gap``
    IS the expected ``dist_min`` before any ``:840-842`` merge."""
    cols = block + gap + block + 4
    mask = _canvas(rows, cols)
    mask[1:1 + block, 0:block] = True
    mask[1:1 + block, block + gap:block + gap + block] = True
    return mask


class TestTwoComponents(unittest.TestCase):
    def test_two_squares_three_apart_merge_to_one_but_dist_min_stays_three(self):
        """``:840-842``: ``dist_min(=3) < 5`` folds ``num_subparticles`` back
        to 1, but ``dist_min`` itself is NOT reset -- the preserved quirk."""
        c = _char(_two_blocks(gap=3))
        c_after, num_sub, dist_min = qc_image(c)
        self.assertEqual(dist_min, 3)
        self.assertEqual(num_sub, 1)  # merged, even though two components existed
        # Both blocks survived bwareaopen untouched (neither is noise), so the
        # REBUILT c is pixel-identical to the input -- merging num_subparticles
        # to 1 changes what gets WRITTEN, not what bwareaopen kept.
        np.testing.assert_array_equal(c_after, c)

    def test_two_squares_six_apart_stay_two(self):
        """Six empty columns give ``dist_min=6 >= 5``: no merge."""
        c = _char(_two_blocks(gap=6))
        c_after, num_sub, dist_min = qc_image(c)
        self.assertEqual(dist_min, 6)
        self.assertEqual(num_sub, 2)
        np.testing.assert_array_equal(c_after, c)  # both components kept, c unchanged

    def test_component_discovery_order_does_not_change_dist_min(self):
        """``_label8`` discovers components in a column-major raster scan, so
        mirroring the image left-right swaps which component is found first.
        ``dist_min`` (a symmetric function of the pairwise distance set) must
        not move -- the module docstring's order-independence argument,
        checked rather than assumed."""
        mask = _two_blocks(gap=6)
        c = _char(mask)
        c_mirrored = _char(mask[:, ::-1])
        _, num_a, dist_a = qc_image(c)
        _, num_b, dist_b = qc_image(c_mirrored)
        self.assertEqual((num_a, dist_a), (num_b, dist_b))


def _three_blocks(g1: int, g2: int, rows: int = 5, block: int = 3) -> np.ndarray:
    cols = block * 3 + g1 + g2 + 4
    mask = _canvas(rows, cols)
    a0 = 0
    b0 = a0 + block + g1
    c0 = b0 + block + g2
    mask[1:1 + block, a0:a0 + block] = True
    mask[1:1 + block, b0:b0 + block] = True
    mask[1:1 + block, c0:c0 + block] = True
    return mask


class TestThreeComponents(unittest.TestCase):
    def test_three_components_dist_min_is_second_smallest(self):
        """``:835``: ``max(mink(dist_arr, n-1))`` is the ``(n-1)``-th smallest
        of the ``nchoosek(n,2)`` pairwise distances, NOT the plain minimum.
        Three blocks with pairwise distances {AB=3, BC=6, AC=12}: the order
        statistic picks 6 (the middle value), never the true minimum 3."""
        c = _char(_three_blocks(g1=3, g2=6))
        c_after, num_sub, dist_min = qc_image(c)
        self.assertEqual(num_sub, 3)
        self.assertEqual(dist_min, 6)
        np.testing.assert_array_equal(c_after, c)


class TestBwareaopenThreshold(unittest.TestCase):
    def test_noise_below_threshold_is_removed_from_c(self):
        """``:803``: a 1-pixel speck is always below ``max(5, ...)`` and is
        removed by ``bwareaopen`` before ``bwconncomp`` ever sees it, so the
        written particle has exactly one subparticle -- the noise is gone,
        not a second one merged away."""
        mask = _canvas(15, 30)
        mask[1:11, 1:11] = True  # 10x10 = 100-pixel main particle
        mask[13, 20] = True  # an isolated 1-pixel speck, far from the block
        c = _char(mask)
        c_after, num_sub, dist_min = qc_image(c)
        self.assertEqual(num_sub, 1)
        self.assertEqual(dist_min, 0)
        self.assertEqual(int(c_after[13, 20]), ord("1"))  # the speck is erased
        np.testing.assert_array_equal(c_after[1:11, 1:11] == ord("0"), mask[1:11, 1:11])

    def test_threshold_is_five_percent_floored_and_at_least_five(self):
        """``:803``: ``P = max(5, floor(0.05 * n_shadowed))``. Held at
        ``n_shadowed = 200`` so ``P = 10`` exactly either way; a 9-pixel
        blob is removed, a 10-pixel blob of the same total survives --
        the boundary the floor puts at *this* fixture's own size, not a
        fixed count some other total would give."""
        for noise_size, survives in ((9, False), (10, True)):
            with self.subTest(noise_size=noise_size):
                main = 200 - noise_size
                mask = _canvas(10, 400)
                mask[0, 0:main] = True  # a straight line, exactly `main` pixels
                mask[5, 250:250 + noise_size] = True  # far from the main line
                c = _char(mask)
                c_after, _num_sub, _dist_min = qc_image(c)
                kept = c_after[5, 250] == ord("0")
                self.assertEqual(bool(kept), survives)


class TestReturnConvention(unittest.TestCase):
    def test_returns_the_ascii_convention_not_a_bare_boolean(self):
        """``c_after`` must stay in the same ``'0'``/``'1'`` ASCII form
        ``dec2bin_concat`` produces, so a caller cannot be surprised by a
        silently-widened boolean array."""
        mask = _canvas(5, 10)
        mask[1:4, 1:4] = True
        c = _char(mask)
        c_after, _, _ = qc_image(c)
        self.assertEqual(c_after.dtype, np.uint8)
        self.assertEqual(set(np.unique(c_after).tolist()), {ord("0"), ord("1")})


class TestInternalHelpers(unittest.TestCase):
    def test_label8_counts_diagonal_touch_as_one_component(self):
        """MATLAB's 2-D default connectivity is 8: two runs that touch only
        at a shared corner -- (1,3) and (2,4) are diagonal neighbours -- must
        be ONE ``bwconncomp`` component, not two. Under 4-connectivity they
        would be two; this is the residual named in the plan's own ranked
        uncertainty #3, pinned directly against ``_label8`` rather than
        through ``qc_image``'s ``P`` threshold."""
        mask = _canvas(6, 8)
        mask[1, 1:4] = True  # a 3-pixel horizontal run, cols 1-3
        mask[2, 4:7] = True  # a 3-pixel run, cols 4-6 -- (2,4) touches (1,3) diagonally
        components = qc_module._label8(mask)
        self.assertEqual(len(components), 1)


if __name__ == "__main__":
    unittest.main()
