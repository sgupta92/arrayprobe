# SPDX-License-Identifier: BSD-3-Clause
"""SPEC's own artefact-removal criteria, boundary-exact, plus a real fixture
smoke test (2D-S PP manual Appendix B, pp. 42-45)."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements.spec_artefact_filter import (
    NoisyDiodeState,
    SpecLengths,
    bounding_box_at,
    is_center_on_bad_diode,
    is_line_or_dot_noise,
    is_round,
    is_splash,
    passes_noisy_diode_exception,
    spec_lengths,
    update_noisy_diode_state,
)

ROOT = Path(__file__).resolve().parents[2]


def _L(l1=0.0, l2=0.0, l4=0.0, l5=0.0, area_s=0.0, center=0.0) -> SpecLengths:
    return SpecLengths(l1=l1, l2=l2, l4=l4, l5=l5, area_s=area_s, center_diode=center)


class SpecLengthsFromAnImage(unittest.TestCase):
    def test_a_single_full_row_slice(self):
        # 3 slices, 5 diodes: slice 1 fully shaded diodes 2-4 (n_lite=3).
        image = np.zeros((3, 5), dtype=bool)
        image[1, 1:4] = True
        lengths = spec_lengths(image)
        self.assertEqual(lengths.l1, 1.0)   # one slice has any shading
        self.assertEqual(lengths.l2, 3.0)   # 3 shaded diodes in that slice
        self.assertEqual(lengths.l4, 3.0)   # diode range 2-4 inclusive = 3
        self.assertEqual(lengths.l5, 3.0)   # same range, only one slice shaded
        self.assertEqual(lengths.area_s, 3.0)
        self.assertAlmostEqual(lengths.center_diode, 3.0)  # midpoint of diodes 2-4 (1-based)

    def test_l4_differs_from_l5_when_the_widest_slice_is_not_the_extreme_one(self):
        # slice 0: diodes 1-2 shaded (n_lite=2); slice 1: diode 5 only (n_lite=1).
        # L2 (max n_lite) = 2, from slice 0, whose own range is diodes 1-2 (L4=2).
        # L5 (range across ALL slices) spans diode 1 to diode 5 = 5.
        image = np.zeros((2, 5), dtype=bool)
        image[0, 0:2] = True
        image[1, 4] = True
        lengths = spec_lengths(image)
        self.assertEqual(lengths.l2, 2.0)
        self.assertEqual(lengths.l4, 2.0)
        self.assertEqual(lengths.l5, 5.0)

    def test_an_empty_image_is_all_zero(self):
        image = np.zeros((3, 5), dtype=bool)
        lengths = spec_lengths(image)
        self.assertEqual(lengths, _L())


class BoundingBoxAt(unittest.TestCase):
    def test_is_l1_times_l5(self):
        self.assertEqual(bounding_box_at(_L(l1=4.0, l5=6.0)), 24.0)


class Roundness(unittest.TestCase):
    def test_a_square_ish_event_is_round(self):
        self.assertTrue(is_round(_L(l1=10.0, l5=10.0)))

    def test_l1_below_half_l5_is_not_round(self):
        self.assertFalse(is_round(_L(l1=4.0, l5=10.0)))  # 4 < 0.5*10

    def test_the_boundary_is_inclusive(self):
        self.assertTrue(is_round(_L(l1=5.0, l5=10.0)))  # 5 == 0.5*10, exactly

    def test_the_large_image_exception_above_500_um_l5_gt_50(self):
        # L5=60 > 50, so only L1 >= 0.5*L5 is required, even though
        # L5 (60) is nowhere near 0.5*L1 (5) -- the exception's whole point.
        self.assertTrue(is_round(_L(l1=30.0, l5=60.0)))

    def test_the_500um_exception_does_not_apply_at_exactly_50(self):
        # L5 == 50 is NOT "> 50", so the exception does not apply and the
        # ordinary symmetric test governs.
        self.assertFalse(is_round(_L(l1=10.0, l5=50.0)))  # 10 < 0.5*50=25, and 50 !> 50


class Splash(unittest.TestCase):
    def test_criterion_i_fires_at_its_boundary(self):
        # L1=11 (>10), At just over 3*As.
        lengths = _L(l1=11.0, l5=1.0, area_s=10.0)
        self.assertTrue(is_splash(lengths, at=30.1))

    def test_criterion_i_does_not_fire_below_its_area_threshold(self):
        lengths = _L(l1=11.0, l5=1.0, area_s=10.0)
        self.assertFalse(is_splash(lengths, at=30.0))  # exactly 3.0x, not >

    def test_a_small_compact_event_is_not_splash(self):
        lengths = _L(l1=5.0, l5=5.0, area_s=20.0)
        self.assertFalse(is_splash(lengths, at=25.0))

    def test_uses_the_bounding_box_at_by_default(self):
        lengths = _L(l1=20.0, l5=20.0, area_s=1.0)  # At = 400, way over 3x
        self.assertTrue(is_splash(lengths))


class LineOrDotNoise(unittest.TestCase):
    def test_criterion_i_a_single_diode_line(self):
        # A one-diode-wide line: L1 == As (every slice contributes exactly
        # one shaded pixel), L2 == 1 (never more than one diode per slice).
        lengths = _L(l1=6.0, l2=1.0, area_s=6.0)
        self.assertTrue(is_line_or_dot_noise(lengths))

    def test_criterion_i_needs_l1_over_four(self):
        lengths = _L(l1=4.0, l2=1.0, area_s=4.0)
        self.assertFalse(is_line_or_dot_noise(lengths))

    def test_a_normal_compact_particle_is_not_flagged(self):
        lengths = _L(l1=10.0, l2=8.0, l4=8.0, l5=8.0, area_s=60.0)
        self.assertFalse(is_line_or_dot_noise(lengths, at=64.0))

    def test_criterion_vi_a_two_diode_line_far_exceeding_area(self):
        lengths = _L(l1=10.0, l2=2.0, l4=10.0, l5=10.0, area_s=5.0)
        self.assertTrue(is_line_or_dot_noise(lengths, at=21.0))  # > 4*5


class NoisyDiodeDetector(unittest.TestCase):
    def test_a_uniformly_quiet_array_flags_nothing(self):
        state = NoisyDiodeState.new(128)
        rng = np.random.default_rng(0)
        centers = rng.integers(1, 129, size=2000)
        update_noisy_diode_state(state, centers)
        for d in (1, 64, 128):
            self.assertFalse(is_center_on_bad_diode(state, d))

    def test_one_diode_far_above_the_rest_is_flagged(self):
        state = NoisyDiodeState.new(128)
        rng = np.random.default_rng(0)
        centers = list(rng.integers(1, 129, size=2000))
        centers += [36] * 400  # one diode hit 400 extra times -- an obvious outlier
        update_noisy_diode_state(state, np.array(centers))
        self.assertTrue(is_center_on_bad_diode(state, 36))
        self.assertFalse(is_center_on_bad_diode(state, 64))

    def test_an_image_on_a_bad_diode_can_still_pass_by_exception(self):
        # A large, well-formed event (exception ii) should survive even if
        # it happens to center on a diode the statistical test flags.
        lengths = _L(l1=20.0, l2=10.0, l4=10.0, l5=20.0, area_s=150.0)
        self.assertTrue(passes_noisy_diode_exception(lengths, at=200.0))

    def test_a_small_or_malformed_event_does_not_qualify_for_any_exception(self):
        lengths = _L(l1=2.0, l2=1.0, l4=1.0, l5=2.0, area_s=2.0)
        self.assertFalse(passes_noisy_diode_exception(lengths, at=10.0))


class OnRealisticMultiSliceShapes(unittest.TestCase):
    """No tracked fixture in this repository carries an extractable, already-
    framed per-particle image array to run this module against: proc/sd
    files (`s3_variant_octave_golden.nc`, `s4_sizedist_octave_golden.nc`)
    store only the *derived scalars* (`image_length`, `image_area`, ...),
    and the raw S2 canvas fixtures (`2DS_s3_input_fixture.nc` and similar)
    store *un-framed* record buffers, not individual particle boundaries --
    extracting one would need `imgproc_sm`'s own internal record-scanning
    loop, which is not exposed as a standalone reusable function. This is
    recorded here rather than silently worked around with a fixture that
    only looks real: the classes above, on hand-built multi-slice arrays
    with known, checkable L1/L2/L4/L5/As values, are the actual
    verification this module has.

    This class instead runs the full pipeline (`spec_lengths` through every
    predicate) on a set of larger, deliberately varied synthetic images --
    round, splash-shaped, and line-noise-shaped -- to prove the functions
    compose correctly end to end, which the boundary-exact unit tests above
    do not by themselves demonstrate.
    """

    def test_a_large_round_compact_particle_passes_every_filter(self):
        image = np.zeros((20, 20), dtype=bool)
        for i in range(20):
            image[i, 5:15] = True  # a uniform 10-diode-wide column, L1=L5=20
        lengths = spec_lengths(image)
        self.assertTrue(is_round(lengths))
        self.assertFalse(is_splash(lengths))
        self.assertFalse(is_line_or_dot_noise(lengths))

    def test_a_thin_long_streak_is_flagged_as_line_noise(self):
        image = np.zeros((30, 128), dtype=bool)
        image[:, 63] = True  # one diode, every slice: L1=As, L2=1
        lengths = spec_lengths(image)
        self.assertTrue(is_line_or_dot_noise(lengths))

    def test_a_sparse_wide_scatter_is_flagged_as_splash(self):
        image = np.zeros((40, 40), dtype=bool)
        image[0, 0] = True
        image[39, 39] = True
        image[20, 20] = True  # 3 lit pixels spread across a 40x40 bounding box
        lengths = spec_lengths(image)
        self.assertTrue(is_splash(lengths))


if __name__ == "__main__":
    unittest.main()
