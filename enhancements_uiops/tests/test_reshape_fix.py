# SPDX-License-Identifier: BSD-3-Clause
"""Tests for reshape_fix.py."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements.reshape_fix import correct_reshaped_time_bin_array

_REAL_SD = Path(__file__).resolve().parent.parent.parent / "_decoded" / "sd.base160906064403.H.nc"


def _scramble(correct: np.ndarray) -> np.ndarray:
    """The A6 bug itself, for building test fixtures: what a (n_time, n_bins)
    array looks like after MATLAB's column-major fill into the variable's
    (n_bins, n_time)-declared shape. This is the exact forward transform
    whose inverse `correct_reshaped_time_bin_array` implements -- derived by
    requiring round-trip identity, not assumed."""
    n_time, n_bins = correct.shape
    return correct.T.reshape(n_time, n_bins, order="C")


class RoundTripTests(unittest.TestCase):
    def test_recovers_a_known_array(self):
        rng = np.random.default_rng(0)
        correct = rng.random((10, 6))
        scrambled = _scramble(correct)
        recovered = correct_reshaped_time_bin_array(scrambled, n_bins=6)
        np.testing.assert_allclose(recovered, correct)

    def test_recovers_sparse_pattern_like_the_real_bug(self):
        # Mimics the real shape: mostly-empty (time, bin) grid with a few
        # occupied seconds -- exactly what a genuine accepted-particle
        # accumulation looks like.
        correct = np.full((50, 8), np.nan)
        occupied_seconds = [3, 7, 20, 41]
        for t in occupied_seconds:
            correct[t, t % 8] = 0.7 + 0.01 * t
        scrambled = _scramble(correct)
        recovered = correct_reshaped_time_bin_array(scrambled, n_bins=8)
        occupied_rows = np.isfinite(recovered).any(axis=1)
        self.assertEqual(sorted(np.where(occupied_rows)[0].tolist()), occupied_seconds)
        np.testing.assert_allclose(recovered[occupied_seconds], correct[occupied_seconds])

    def test_wrong_bin_count_raises(self):
        arr = np.zeros((10, 6))
        with self.assertRaises(ValueError):
            correct_reshaped_time_bin_array(arr, n_bins=5)

    def test_non_2d_raises(self):
        with self.assertRaises(ValueError):
            correct_reshaped_time_bin_array(np.zeros(10), n_bins=6)


@unittest.skipUnless(_REAL_SD.exists(), f"real decoded flight not present: {_REAL_SD}")
class RealDataInvariantTests(unittest.TestCase):
    """The actual validation strategy from the design doc: no MATLAB oracle
    exists for "corrected" output (there is no un-scrambled reference run in
    any UIOOPS tree), so the check is against ground truth already in the
    same file -- a second either has accepted particles or it doesn't, and a
    correctly-shaped sibling variable (mean_perimeter) that isn't affected
    by this bug."""

    def test_recovered_rows_match_particle_counts_exactly(self):
        import netCDF4

        with netCDF4.Dataset(_REAL_SD) as ds:
            raw = np.asarray(ds.variables["mean_area_ratio"][:].filled(np.nan))
            mean_perimeter = np.asarray(ds.variables["mean_perimeter"][:].filled(np.nan))
            n = ds.variables["n"][:]

        n_bins = raw.shape[1]
        recovered = correct_reshaped_time_bin_array(raw, n_bins)

        recovered_rows = np.isfinite(recovered).any(axis=1)
        good_rows = n > 0
        self.assertTrue(bool((recovered_rows == good_rows).all()))

        # Cross-check against a sibling variable computed over a very
        # similar per-bin mask and known NOT to have this bug.
        mp_bins = np.isfinite(mean_perimeter).any(axis=0)
        recovered_bins = np.isfinite(recovered).any(axis=0)
        self.assertEqual(int(recovered_bins.sum()), int(mp_bins.sum()))

        finite = recovered[np.isfinite(recovered)]
        self.assertGreater(len(finite), 0)
        # Area ratio is nominally bounded by 1; allow a little headroom for
        # pixel-level discretization the way other bounded ratios in this
        # project are documented not to be perfectly bounded either.
        self.assertTrue(bool(((finite > 0) & (finite < 1.5)).all()))


if __name__ == "__main__":
    unittest.main()
