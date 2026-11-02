# SPDX-License-Identifier: BSD-3-Clause
"""S4-z (``label_blobs.pro:20``'s dilation kernel clamp) --
``dilation_clamp_fix.corrected_label_blobs_dilation``.

Reproduces the exact scenario finding S4-z measures: two single-diode fragments
separated by a 3-diode gap, ``dilatelength=2``. On a slice-axis-length-1 ROI the port's own
clamp (``s[1]+2``) caps the kernel at 3 wide (radius 1, can't bridge the gap); the correction
(clamp against the padded array's own size) gets the intended 5-wide kernel (radius 2, bridges
it) -- same as what the port itself already does once the slice axis is long enough not to
trigger the clamp (the ``Equivalence`` case below).
"""

from __future__ import annotations

import unittest

import numpy as np
from arrayprobe_soda2.label_blobs import label_blobs

from arrayprobe_soda2_enhancements.dilation_clamp_fix import corrected_label_blobs_dilation
from arrayprobe_soda2_enhancements.registry import PROTECTIVE, REGISTRY, resolve


def _two_fragments(n_diodes: int, n_slices: int, slice_idx: int) -> np.ndarray:
    """Two single-diode fragments (diode 0 and diode 4) separated by a 3-diode gap
    (diodes 1-3), both at ``slice_idx`` -- shape (n_diodes, n_slices), matching
    label_blobs's own (diode, slice) axis convention."""
    img = np.zeros((n_diodes, n_slices), dtype=np.uint8)
    img[0, slice_idx] = 1
    img[4, slice_idx] = 1
    return img


class Equivalence(unittest.TestCase):
    """A slice-axis length of 3 never triggers either clamp (s1+2 == s1+2*pad == 5 for
    dilatelength=2, pad=2) -- both fragments merge under the port's own label_blobs and
    under the correction identically."""

    def test_matches_port_when_the_clamp_does_not_bind(self):
        img = _two_fragments(10, 3, slice_idx=1)

        port_out = label_blobs(img, dilatelength=2, integer=True)
        got = corrected_label_blobs_dilation(img, dilatelength=2, integer=True)

        np.testing.assert_array_equal(got, port_out)
        # Both bridge the gap -- the two fragments share one label under the port too,
        # confirming this case genuinely does not exercise S4-z.
        self.assertEqual(int(port_out[0, 1]), int(port_out[4, 1]))
        self.assertNotEqual(int(port_out[0, 1]), 0)


class ABConsequence(unittest.TestCase):
    """A slice-axis length of 1 triggers the port's own clamp (s1+2 == 3 < 5): the two
    fragments stay separate blobs. The correction's clamp (s1+2*pad == 5) does not bind,
    and the fragments merge -- exactly the "1-slice roi" case of finding S4-z
    measures."""

    def test_recovers_the_bridged_gap_on_a_one_slice_roi(self):
        img = _two_fragments(10, 1, slice_idx=0)

        port_out = label_blobs(img, dilatelength=2, integer=True)
        self.assertNotEqual(int(port_out[0, 0]), 0)
        self.assertNotEqual(int(port_out[4, 0]), 0)
        self.assertNotEqual(
            int(port_out[0, 0]), int(port_out[4, 0]),
            "the port's own clamped (3-wide) kernel must NOT bridge the 3-diode gap")

        fixed_out = corrected_label_blobs_dilation(img, dilatelength=2, integer=True)
        self.assertNotEqual(int(fixed_out[0, 0]), 0)
        self.assertNotEqual(int(fixed_out[4, 0]), 0)
        self.assertEqual(
            int(fixed_out[0, 0]), int(fixed_out[4, 0]),
            "the corrected (5-wide) kernel must bridge the 3-diode gap")

    def test_refuses_dilatelength_zero(self):
        img = _two_fragments(10, 1, slice_idx=0)
        with self.assertRaises(ValueError):
            corrected_label_blobs_dilation(img, dilatelength=0)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("dilation_clamp_fix", REGISTRY)
        spec = REGISTRY["dilation_clamp_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-z")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_on_through_the_protective_set_false_when_opted_out(self):
        self.assertFalse(resolve({})["dilation_clamp_fix"])
        self.assertTrue(resolve({}, protective=PROTECTIVE)["dilation_clamp_fix"])
        self.assertFalse(
            resolve({"dilation_clamp_fix": False}, protective=PROTECTIVE)["dilation_clamp_fix"])
        self.assertFalse(resolve({"dilation_clamp_fix": False})["dilation_clamp_fix"])


if __name__ == "__main__":
    unittest.main()
