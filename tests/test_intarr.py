# SPDX-License-Identifier: BSD-3-Clause
"""Tests for arrayprobe.intarr -- IntArrAnalysis_time.m's robust bimodal fit.

See intarr.py's module docstring for why this routine has no oracle for its
actual (robust) behavior on this machine, and what these tests validate
instead: the unweighted special case against a real Octave run, and a
qualitative robustness property against a hand-built outlier case.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe.intarr import bimodal_model, fit_bimodal_intarr, robust_nlinfit

try:  # scipy is an *extra* (pip install "arrayprobe[extra]"), not a core dependency:
    import scipy  # noqa: F401   the package must install with no toolchain.
    _HAS_SCIPY = True
except ImportError:                     # pragma: no cover - depends on the env
    _HAS_SCIPY = False


def setUpModule():
    """Skip, rather than error, when the optional fit dependency is absent.

    `intarr.py` imports scipy lazily inside the fitting function, so the module
    imports fine and the failure surfaced only when a test called it. On the
    author's laptop scipy has always been in the venv, so this path had never
    been taken; the first clean-environment CI run (2026-09-08) turned it into
    34 errors across the port and enhancement suites. An optional dependency
    that is absent must skip with a message, not raise.
    """
    if not _HAS_SCIPY:
        raise unittest.SkipTest(
            "scipy is not installed; it is an extra (pip install \"arrayprobe[extra]\") "
            "and the interarrival fits need it")


DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "s8_intarr_octave_golden.json"


class TestBimodalModel(unittest.TestCase):
    def test_hand_computed_value(self):
        # tau = (1, 1, 0.5): both populations identical, so the mixture
        # collapses to a single exponential term regardless of tau3.
        got = bimodal_model((1.0, 1.0, 0.5), np.array([0.0, 1.0, 2.0]))
        want = np.array([0.0, np.exp(-1.0), 2.0 * np.exp(-2.0)])
        np.testing.assert_allclose(got, want)

    def test_two_distinct_populations_hand_computed(self):
        tau = (2.0, 4.0, 0.25)
        dt = 3.0
        want = 0.75 * (dt / 2.0) * np.exp(-dt / 2.0) + 0.25 * (dt / 4.0) * np.exp(-dt / 4.0)
        got = bimodal_model(tau, np.array([dt]))[0]
        self.assertAlmostEqual(got, want, places=12)

    def test_array_input(self):
        dt = np.linspace(0.01, 1.0, 20)
        got = bimodal_model((0.1, 0.01, 0.3), dt)
        self.assertEqual(got.shape, dt.shape)
        self.assertTrue(np.all(np.isfinite(got)))


class TestUnweightedMatchesOctave(unittest.TestCase):
    """robust=False is the one case with a real oracle: Octave's own nlinfit
    silently drops 'Robust' and computes exactly this fit (confirmed by the
    bank builder's own captured stderr, checked below rather than assumed)."""

    @classmethod
    def setUpClass(cls):
        cls._skip_reason = None
        if not GOLDEN.exists():
            cls._skip_reason = f"oracle golden not found: {GOLDEN}"
            return
        cls.golden = json.loads(GOLDEN.read_text())

    def setUp(self):
        # Raised here, not in setUpClass: a SkipTest from setUpClass is recorded
        # against an _ErrorHolder, so it never increments testsRun and never joins
        # the skipped tally -- the suite reports one FEWER test instead of one more
        # skip. See tests/test_class_level_skips_are_visible.py.
        if self._skip_reason:
            self.skipTest(self._skip_reason)

    def test_octave_confirms_robust_was_dropped(self):
        # This IS the finding the whole module's validation strategy rests
        # on -- if Octave's optim package ever starts honoring 'Robust',
        # this golden is no longer a valid oracle for robust=False and must
        # be regenerated/reinterpreted.
        self.assertTrue(self.golden["octave_stderr_confirms_robust_dropped"])

    def test_unweighted_fit_matches_octave_closely(self):
        x = np.array(self.golden["bins_center"])
        y = np.array(self.golden["y_density"])
        beta0 = self.golden["beta0"]
        want = np.array(self.golden["octave_tau_std_unweighted"])

        got = np.abs(robust_nlinfit(x, y, bimodal_model, beta0, robust=False))
        np.testing.assert_allclose(got, want, rtol=1e-4)

    def test_fit_bimodal_intarr_end_to_end_matches_unweighted_result(self):
        # fit_bimodal_intarr always requests the robust path (matching the
        # MATLAB call site), but on this clean, well-conditioned synthetic
        # histogram (no outliers) the robust and unweighted fits should
        # land close to the same optimum -- a real check that the IRLS loop
        # converges sanely on ordinary data, not just that it runs.
        x = self.golden["bins_center"]
        h = self.golden["hist_counts"]
        width = self.golden["width"]
        beta0 = self.golden["beta0"]
        want = np.array(self.golden["octave_tau_std_unweighted"])

        got = fit_bimodal_intarr(x, h, width, beta0=beta0)
        np.testing.assert_allclose(got, want, rtol=0.05)


class TestRobustDivergesFromNonRobustOnOutlier(unittest.TestCase):
    """No oracle can check the robust path's numeric agreement with MATLAB
    (see module docstring), so this validates the qualitative property the
    routine exists for instead: one corrupted bin should visibly derail the
    unweighted fit while the robust fit stays close to the clean answer and
    assigns the corrupted bin ~zero weight."""

    @classmethod
    def setUpClass(cls):
        cls._skip_reason = None
        if not GOLDEN.exists():
            cls._skip_reason = f"oracle golden not found: {GOLDEN}"
            return
        golden = json.loads(GOLDEN.read_text())
        cls.x = np.array(golden["bins_center"])
        cls.y_clean = np.array(golden["y_density"])
        cls.beta0 = golden["beta0"]
        cls.clean_fit = np.abs(robust_nlinfit(cls.x, cls.y_clean, bimodal_model,
                                               cls.beta0, robust=False))

    def setUp(self):
        # Raised here, not in setUpClass: a SkipTest from setUpClass is recorded
        # against an _ErrorHolder, so it never increments testsRun and never joins
        # the skipped tally -- the suite reports one FEWER test instead of one more
        # skip. See tests/test_class_level_skips_are_visible.py.
        if self._skip_reason:
            self.skipTest(self._skip_reason)

    def _corrupt(self, idx, magnitude):
        y = self.y_clean.copy()
        y[idx] += magnitude * self.y_clean.max()
        return y

    def test_a_large_single_bin_outlier_derails_the_unweighted_fit(self):
        # Bin 10 sits in the valley between the two populations (near-zero
        # density in the clean histogram) -- a large spike there is the
        # kind of single corrupted bin the source's own comment
        # ("bimodal fit still isn't achieved") anticipates.
        y_outlier = self._corrupt(idx=10, magnitude=30)
        nonrobust = np.abs(robust_nlinfit(self.x, y_outlier, bimodal_model,
                                           self.beta0, robust=False))
        # A mixture fraction (tau[2]) outside [0, 1] is a nonsensical
        # answer for this model -- direct evidence the unweighted fit was
        # thrown off, not just "moved somewhat".
        self.assertGreater(nonrobust[2], 1.0)

    def test_the_robust_fit_stays_close_to_the_clean_answer(self):
        y_outlier = self._corrupt(idx=10, magnitude=30)
        robust = np.abs(robust_nlinfit(self.x, y_outlier, bimodal_model,
                                        self.beta0, robust=True))
        np.testing.assert_allclose(robust, self.clean_fit, rtol=0.05)

    def test_the_robust_fit_assigns_the_corrupted_bin_zero_weight(self):
        y_outlier = self._corrupt(idx=10, magnitude=30)
        beta = robust_nlinfit(self.x, y_outlier, bimodal_model, self.beta0, robust=True)
        resid = y_outlier - bimodal_model(beta, self.x)
        scale = np.median(np.abs(resid)) / 0.6745
        scaled = resid / (4.685 * scale)
        weight_at_outlier = (1 - scaled[10] ** 2) ** 2 if abs(scaled[10]) < 1 else 0.0
        self.assertEqual(weight_at_outlier, 0.0)

    def test_a_smaller_outlier_at_the_same_bin_shows_the_same_effect(self):
        # A less extreme version of the same corrupted-valley-bin case
        # (5x instead of 30x) -- confirms the robust win isn't an artifact
        # of one specifically engineered extreme magnitude. Bin 12's own
        # near-zero valley density made a "mild" outlier there ambiguous
        # (both fits drift by comparable amounts for small magnitudes,
        # non-monotonically -- measured, not assumed, while designing this
        # test); bin 10 at reduced magnitude is the case that stays clean.
        y_outlier = self._corrupt(idx=10, magnitude=5)
        nonrobust = np.abs(robust_nlinfit(self.x, y_outlier, bimodal_model,
                                           self.beta0, robust=False))
        robust = np.abs(robust_nlinfit(self.x, y_outlier, bimodal_model,
                                        self.beta0, robust=True))
        nonrobust_drift = np.linalg.norm((nonrobust - self.clean_fit) / self.clean_fit)
        robust_drift = np.linalg.norm((robust - self.clean_fit) / self.clean_fit)
        self.assertLess(robust_drift, nonrobust_drift)


class TestRobustNlinfitGeneral(unittest.TestCase):
    def test_perfect_data_recovers_true_parameters(self):
        # beta0 deliberately close to the truth, not the module's usual
        # (1e-2, 1e-6, 0.5) default: starting the two time constants far
        # apart (as the default does) leaves tau2 essentially unidentified
        # over this x range with zero noise to break the degeneracy, and a
        # symmetric start (tau1 == tau2) hits a singular Jacobian direction
        # -- both are solver-initialization edge cases, not something this
        # fit needs to overcome blind, any more than MATLAB's nlinfit does.
        true_tau = (0.05, 0.001, 0.3)
        x = np.linspace(0.0001, 0.3, 40)
        y = bimodal_model(true_tau, x)
        got = robust_nlinfit(x, y, bimodal_model, (0.04, 0.002, 0.35), robust=True)
        np.testing.assert_allclose(np.abs(got), true_tau, rtol=1e-4)

    def test_negative_convergence_is_sign_flipped_not_rejected(self):
        # fit_bimodal_intarr takes abs() of whatever the fit returns,
        # matching MATLAB's own abs(nlinfit(...)) verbatim -- confirm the
        # wrapper actually applies it rather than silently trusting sign.
        h = [1, 5, 20, 50, 80, 60, 30, 10, 3, 1]
        bins = np.logspace(-4, -1, 11)
        width = np.log(bins[1]) - np.log(bins[0])
        bins_center = bins[:-1] + np.diff(bins) / 2
        result = fit_bimodal_intarr(bins_center, h, width)
        self.assertTrue(np.all(result >= 0))


if __name__ == "__main__":
    unittest.main()
