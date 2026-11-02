# SPDX-License-Identifier: BSD-3-Clause
"""S4-y (``label_blobs.pro:29``'s BYTE wrap) -- ``label_blobs_int_count.corrected_label_blobs``.

The AB case builds a real >255-blob image (isolated single-pixel foreground on a spaced grid,
so each pixel is its own 4-connected blob by construction) and runs it through the real,
unmodified port's ``label_blobs`` -- the same mechanism finding S4-y describes
(``byte(256) == 0``, ``byte(300) == 44``), on this module's own synthetic image rather than a
transcription of the finding's own case.
"""

from __future__ import annotations

import unittest

import numpy as np
from arrayprobe_soda2.label_blobs import label_blobs

from arrayprobe_soda2_enhancements.label_blobs_int_count import corrected_label_blobs
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve


def _isolated_blob_grid(n_rows: int, n_cols: int, *, step: int = 2) -> np.ndarray:
    """A binary image with one isolated foreground pixel every ``step`` rows/cols --
    each is its own 4-connected (and 8-connected, given the spacing) blob."""
    img = np.zeros((n_rows, n_cols), dtype=np.uint8)
    img[0:n_rows:step, 0:n_cols:step] = 1
    return img


class Equivalence(unittest.TestCase):
    """Below the 256-blob wrap boundary, integer=True (downcast to uint8) must equal the
    port's own default byte output exactly."""

    def test_matches_port_byte_output_below_the_wrap(self):
        img = _isolated_blob_grid(10, 10, step=2)  # 25 isolated blobs
        port_out = label_blobs(img)  # integer=False default
        got = corrected_label_blobs(img).astype(np.uint8)
        np.testing.assert_array_equal(got, port_out)


class ABConsequence(unittest.TestCase):
    """A 279-blob synthetic image: the port's own byte return wraps exactly one label
    (whichever raster-order label equals 256) to 0, indistinguishable from background;
    integer=True does not."""

    def test_recovers_the_wrapped_blob(self):
        img = _isolated_blob_grid(40, 40, step=2)  # 20*20 = 400 isolated blobs
        n_blobs = int(img.sum())
        self.assertGreater(n_blobs, 255, "test construction must exceed the wrap boundary")

        corrected = corrected_label_blobs(img)
        self.assertEqual(corrected.dtype, np.uint32)
        self.assertEqual(len(np.unique(corrected)) - 1, n_blobs,
                          "every isolated pixel must be its own distinct, unwrapped label")

        port_out = label_blobs(img)  # integer=False
        self.assertEqual(port_out.dtype, np.uint8)
        # Exactly one foreground pixel (the one carrying raster label 256) must have
        # wrapped to byte 0 -- indistinguishable from background under the port's own
        # return, present and distinct under the correction.
        lost = np.count_nonzero((img == 1) & (port_out == 0))
        self.assertEqual(lost, 1, "exactly one blob (label 256) must wrap to byte 0")

        recovered_pixel = np.argwhere((img == 1) & (port_out == 0))[0]
        ry, rx = recovered_pixel
        self.assertEqual(int(corrected[ry, rx]), 256)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("label_blobs_int_count", REGISTRY)
        spec = REGISTRY["label_blobs_int_count"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-y")
        self.assertEqual(spec.reachability, "latent")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["label_blobs_int_count"])
        self.assertTrue(resolve({"label_blobs_int_count": True})["label_blobs_int_count"])
        self.assertFalse(resolve({"label_blobs_int_count": False})["label_blobs_int_count"])


if __name__ == "__main__":
    unittest.main()
