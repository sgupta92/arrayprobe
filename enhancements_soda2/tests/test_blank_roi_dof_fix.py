# SPDX-License-Identifier: BSD-3-Clause
"""S4-v (``binary_dof.pro:21-31``'s blank-image ``ELSE`` acceptance) --
``blank_roi_dof_fix.corrected_binary_dof``.
"""
from __future__ import annotations

import unittest

import numpy as np
from arrayprobe_soda2.binary_dof import binary_dof

from arrayprobe_soda2_enhancements.blank_roi_dof_fix import corrected_binary_dof
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve


class Equivalence(unittest.TestCase):
    """A single-pixel image has area=1, which the CASE statement
    accepts unconditionally (area==1: dof=1) -- never the ELSE branch
    this finding is about."""

    def test_matches_port_when_area_is_one(self):
        img = np.zeros((3, 3), dtype=np.uint8)
        img[1, 1] = 1
        port_out = binary_dof(img)
        got = corrected_binary_dof(img)
        self.assertEqual(got.dof, port_out.dof)
        self.assertEqual(float(got.neighbor_count), float(port_out.neighbor_count))
        self.assertEqual(float(got.area), float(port_out.area))
        self.assertEqual(port_out.dof, 1, "sanity: area==1 always accepts")


class ABConsequence(unittest.TestCase):
    """A blank (all-zero) image: the port's ELSE branch takes
    0 ge 0 as true and accepts (dof=1); the correction refuses it."""

    def test_blank_image_is_rejected_not_accepted(self):
        img = np.zeros((3, 3), dtype=np.uint8)
        port_out = binary_dof(img)
        self.assertEqual(port_out.dof, 1, "the port's own S4-v acceptance")
        self.assertEqual(float(port_out.area), 0.0)

        fixed = corrected_binary_dof(img)
        self.assertEqual(fixed.dof, 0)
        self.assertEqual(float(fixed.area), float(port_out.area))
        self.assertEqual(float(fixed.neighbor_count), float(port_out.neighbor_count))


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("blank_roi_dof_fix", REGISTRY)
        spec = REGISTRY["blank_roi_dof_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-v")
        self.assertEqual(spec.reachability, "flagged")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["blank_roi_dof_fix"])
        self.assertTrue(resolve({"blank_roi_dof_fix": True})["blank_roi_dof_fix"])
        self.assertFalse(resolve({"blank_roi_dof_fix": False})["blank_roi_dof_fix"])


if __name__ == "__main__":
    unittest.main()
