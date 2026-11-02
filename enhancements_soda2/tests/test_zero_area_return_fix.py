# SPDX-License-Identifier: BSD-3-Clause
"""S3-e (``soda2_findsize.pro:9-13``'s zero-area early return) --
``zero_area_return_fix.corrected_soda2_findsize``.

``_image`` is duplicated from ``test_soda2_findsize.py`` rather than
imported across the package boundary (~8 lines of pure fixture
plumbing, not port logic) -- the same convention ``test_den_clamp_fix.py``
set in stage 2.
"""
from __future__ import annotations

import unittest

import numpy as np
from arrayprobe_soda2.findsize import soda2_findsize

from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve
from arrayprobe_soda2_enhancements.zero_area_return_fix import corrected_soda2_findsize


def _image(rows: list[str]) -> np.ndarray:
    ny, nx = len(rows), len(rows[0])
    arr = np.zeros((ny, nx), dtype=np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            arr[y, x] = 1 if ch == "#" else 0
    return arr


_ROWS = ["..###....", "..###...."]


class Equivalence(unittest.TestCase):
    """A real particle with FLOAT resolutions never takes the zero-area
    early return -- corrected and port must agree on every field."""

    def test_matches_port_when_area_is_nonzero(self):
        img = _image(_ROWS)
        port_out = soda2_findsize(img, np.float32(10.0), np.float32(5.0))
        got = corrected_soda2_findsize(img, np.float32(10.0), np.float32(5.0))

        self.assertEqual(float(got.diam), float(port_out.diam))
        self.assertEqual(float(got.oned), float(port_out.oned))
        self.assertEqual(got.centerin, port_out.centerin)
        self.assertEqual(got.allin, port_out.allin)
        self.assertEqual(float(got.ar), float(port_out.ar))
        self.assertNotEqual(port_out.centerin, 0)  # sanity: not itself the S3-e case


class ABConsequence(unittest.TestCase):
    """An all-zero image takes the zero-area early return (S3-d shows
    this is also reachable via an integer resolution on a real
    particle, but an all-blank image is the simplest, most direct
    trigger of the same :13 branch)."""

    def test_zero_area_image_gets_centerin_zero_not_one(self):
        img = np.zeros((2, 9), dtype=np.uint8)
        port_out = soda2_findsize(img, np.float32(10.0), np.float32(5.0))
        self.assertEqual(port_out.centerin, 1, "the port's own S3-e default")
        self.assertEqual(float(port_out.diam), 0.0)

        fixed = corrected_soda2_findsize(img, np.float32(10.0), np.float32(5.0))
        self.assertEqual(fixed.centerin, 0)
        # nothing else about the zero-area default structure changes
        self.assertEqual(fixed.allin, port_out.allin)
        self.assertEqual(float(fixed.diam), float(port_out.diam))

    def test_s3_d_integer_resolution_zero_area_also_gets_centerin_zero(self):
        """S3-d's own reachability path (an integer resolution on a
        REAL particle) is a second, independent way to trigger the same
        :13 branch -- not re-fixing S3-d, only confirming S3-e's fix
        applies wherever the early return fires."""
        img = _image(_ROWS)
        port_out = soda2_findsize(img, np.int32(10), np.int32(5))
        self.assertEqual(port_out.centerin, 1)
        self.assertEqual(float(port_out.diam), 0.0)

        fixed = corrected_soda2_findsize(img, np.int32(10), np.int32(5))
        self.assertEqual(fixed.centerin, 0)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("zero_area_return_fix", REGISTRY)
        spec = REGISTRY["zero_area_return_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S3-e")
        self.assertEqual(spec.reachability, "flagged")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["zero_area_return_fix"])
        self.assertTrue(resolve({"zero_area_return_fix": True})["zero_area_return_fix"])
        self.assertFalse(resolve({"zero_area_return_fix": False})["zero_area_return_fix"])


if __name__ == "__main__":
    unittest.main()
