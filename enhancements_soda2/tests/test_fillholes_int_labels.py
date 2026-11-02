# SPDX-License-Identifier: BSD-3-Clause
"""S4-u (``fillholes.pro:9``'s BYTE-wrapping ``label_blobs`` call) --
``fillholes_int_labels.corrected_fillholes``.

The AB case reproduces the shape finding S4-u measures directly: a foreground
ROI with more than 255 isolated single-pixel holes, none touching an edge -- the port's own
``fillholes`` comes back exactly one pixel short of full ``area_filled``; the correction fills
every hole.
"""

from __future__ import annotations

import unittest

import numpy as np
from arrayprobe_soda2.fillholes import fillholes

from arrayprobe_soda2_enhancements.fillholes_int_labels import corrected_fillholes
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve


class Equivalence(unittest.TestCase):
    """A single interior hole never approaches the 256-label wrap -- corrected_fillholes
    must match the real port's fillholes bit for bit."""

    def test_matches_port_with_one_hole(self):
        arr = np.ones((6, 6), dtype=np.uint8)
        arr[3, 3] = 0  # one interior hole, not touching an edge

        port_out = fillholes(arr)
        got = corrected_fillholes(arr)

        np.testing.assert_array_equal(got, port_out)
        self.assertEqual(int(got.sum()), arr.size, "the one hole must be filled")


class ABConsequence(unittest.TestCase):
    """279 isolated interior holes (none touching an edge) -- label 256, whichever pixel
    gets it in raster order, wraps to byte 0 under the port's own fillholes and is never
    filled; the correction fills all 279."""

    def test_recovers_the_one_missed_hole(self):
        roilen, ndiodes = 40, 128
        arr = np.ones((roilen, ndiodes), dtype=np.uint8)
        diode_idx = np.arange(2, 126, 4)   # margin >= 2 from either diode edge
        slice_idx = np.arange(2, roilen - 2, 4)  # margin >= 2 from either slice edge
        for s in slice_idx:
            arr[s, diode_idx] = 0
        n_holes = len(diode_idx) * len(slice_idx)
        self.assertGreater(n_holes, 255, "test construction must exceed the wrap boundary")

        total_cells = roilen * ndiodes

        port_out = fillholes(arr)
        self.assertEqual(int(port_out.sum()), total_cells - 1,
                          "exactly one hole (label 256) must be left unfilled")

        fixed_out = corrected_fillholes(arr)
        self.assertEqual(int(fixed_out.sum()), total_cells,
                          "every hole must be filled once labels don't wrap")


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("fillholes_int_labels", REGISTRY)
        spec = REGISTRY["fillholes_int_labels"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-u")
        self.assertEqual(spec.reachability, "latent")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["fillholes_int_labels"])
        self.assertTrue(resolve({"fillholes_int_labels": True})["fillholes_int_labels"])
        self.assertFalse(resolve({"fillholes_int_labels": False})["fillholes_int_labels"])


if __name__ == "__main__":
    unittest.main()
