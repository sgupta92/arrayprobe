# SPDX-License-Identifier: BSD-3-Clause
"""Tests for diode_range_fix.py (the upstream image-widening diode number).

Both states are exercised against the *same* input: ``validate=False`` must reproduce the
port's widening exactly (the faithful behaviour, which is what makes the defect real), and
``validate=True`` must raise before the image is ever touched.

The "would widen" claim is not asserted in prose -- it is checked against
``arrayprobe.masks.reilluminate``'s real output, so the two sides of the check come from
different places.
"""

from __future__ import annotations

import unittest

import numpy as np
from arrayprobe.masks import reilluminate
from arrayprobe.matlab_compat import MatlabIndexError

from arrayprobe_enhancements.diode_range_fix import (
    DiodeRangeError,
    out_of_range,
    reilluminate_checked,
    validate_diodes,
    would_widen,
)

_LIT = ord("1")
_SHADOWED = ord("0")
_PAD = 0


def image(rows, cols):
    return np.full((rows, cols), _SHADOWED, dtype=np.uint8)


class TheDefectIsRealAndTheOffStateReproducesIt(unittest.TestCase):
    def test_the_port_widens_rather_than_raising(self):
        out = reilluminate_checked(image(2, 4), [2, 6], validate=False)
        self.assertEqual(out.shape, (2, 6))
        np.testing.assert_array_equal(out[0], [_SHADOWED, _LIT, _SHADOWED, _SHADOWED,
                                               _PAD, _LIT])

    def test_the_off_state_is_the_ports_function_and_nothing_else(self):
        np.testing.assert_array_equal(
            reilluminate_checked(image(3, 8), [1, 5], validate=False),
            reilluminate(image(3, 8), [1, 5]))

    def test_would_widen_agrees_with_what_the_port_actually_does(self):
        for diodes, diodenum in (([2, 6], 4), ([129], 128), ([2, 128], 128), ([], 64),
                                 ([64], 64), ([200, 3], 128)):
            with self.subTest(diodes=diodes, diodenum=diodenum):
                widened = reilluminate(image(2, diodenum), diodes)
                self.assertEqual(would_widen(diodes, diodenum),
                                 widened.shape[1] - diodenum)


class TheValidator(unittest.TestCase):
    def test_an_in_range_mask_passes_and_returns_the_diodes(self):
        np.testing.assert_array_equal(validate_diodes([2, 128], 128), [2.0, 128.0])
        self.assertEqual(validate_diodes([], 128).size, 0)

    def test_an_entry_past_the_last_diode_raises_and_explains_the_truncation(self):
        with self.assertRaises(DiodeRangeError) as caught:
            validate_diodes([2, 129], 128)
        message = str(caught.exception)
        self.assertIn("129", message)
        self.assertIn("128 diodes", message)
        self.assertIn("truncating the run", message)

    def test_the_128_mask_on_a_64_diode_probe_is_the_case_the_finding_names(self):
        with self.assertRaises(DiodeRangeError):
            validate_diodes([2, 128], 64)

    def test_non_positive_and_fractional_entries_are_reported_too(self):
        bad = out_of_range([0, -3, 2.5, 200, 5], 128)
        self.assertEqual(bad["above"], [200.0])
        self.assertEqual(bad["below"], [0.0, -3.0])
        self.assertEqual(bad["fractional"], [2.5])
        with self.assertRaises(DiodeRangeError) as caught:
            validate_diodes([0, 2.5], 128)
        self.assertIn("non-positive", str(caught.exception))
        self.assertIn("fractional", str(caught.exception))

    def test_the_source_is_named_when_given(self):
        with self.assertRaises(DiodeRangeError) as caught:
            validate_diodes([300], 128, source="diode.160906064403.V.mat")
        self.assertIn("diode.160906064403.V.mat", str(caught.exception))

    def test_a_mask_object_is_accepted_the_same_way_a_list_is(self):
        from arrayprobe.masks import ShadowDiodeMask
        mask = ShadowDiodeMask(diodes=np.array([2.0, 300.0]), date=None, time=None,
                               source=None)
        with self.assertRaises(DiodeRangeError):
            validate_diodes(mask, 128)


class TheCorrectionOn(unittest.TestCase):
    def test_it_raises_before_the_image_is_touched(self):
        c = image(2, 4)
        before = c.copy()
        with self.assertRaises(DiodeRangeError):
            reilluminate_checked(c, [2, 6])
        np.testing.assert_array_equal(c, before)

    def test_an_in_range_mask_gives_exactly_the_ports_result(self):
        np.testing.assert_array_equal(
            reilluminate_checked(image(2, 128), [2, 128]),
            reilluminate(image(2, 128), [2, 128]))

    def test_the_default_width_is_the_images_own(self):
        """`:272-276` compares against `diodenum`; with no probe width given, the image's
        own width is the only thing that can be compared against."""
        with self.assertRaises(DiodeRangeError):
            reilluminate_checked(image(2, 64), [65])
        reilluminate_checked(image(2, 64), [64])

    def test_the_loud_matlab_failures_still_come_from_the_port(self):
        """A zero subscript stops MATLAB anyway, so validation must not disguise it as F3."""
        with self.assertRaises(DiodeRangeError):
            reilluminate_checked(image(2, 8), [0])
        with self.assertRaises(MatlabIndexError):
            reilluminate_checked(image(2, 8), [0], validate=False)


if __name__ == "__main__":
    unittest.main()
