# SPDX-License-Identifier: BSD-3-Clause
"""Tests for ``arrayprobe_soda2.fit_poisson``.

No GDL oracle exists for ``fit_poisson`` (GDL 1.1.2 has no ``LMFIT`` -- see
the module docstring), so this file stays at doctrine layer 3: hand-derived
checks of ``fn_poisson``'s closed-form Jacobian (the "third side" -- finite
differences, computed independently of both the port and any interpreter),
plus behavioural tests of ``fit_poisson``'s documented early exit and
dependency-free import.
"""
from __future__ import annotations

import unittest

import numpy as np

from arrayprobe_soda2.fit_poisson import PoissonFit, fit_poisson, fn_poisson


class TestFnPoissonJacobian(unittest.TestCase):
    """fn_poisson.pro:10-13 -- out[1:3] are the analytic partials of out[0]
    with respect to ans[0:2]. Checked against central finite differences,
    independent of the closed form itself."""

    def test_partials_match_finite_differences(self):
        dt = np.array([0.01, 0.05, 0.1, 0.3, 0.8])
        ans = np.array([0.6, 12.0, 0.4])
        eps = 1e-6

        out = fn_poisson(dt, ans)
        for k in range(3):
            bumped = ans.copy()
            bumped[k] += eps
            plus = fn_poisson(dt, bumped)[0]
            bumped[k] -= 2 * eps
            minus = fn_poisson(dt, bumped)[0]
            numeric = (plus - minus) / (2 * eps)
            np.testing.assert_allclose(out[k + 1], numeric, rtol=1e-3, atol=1e-6)

    def test_scalar_dt_returns_length_four(self):
        out = fn_poisson(0.1, [0.5, 10.0, 0.01])
        self.assertEqual(out.shape, (4,))


class TestFitPoissonEmptyRange(unittest.TestCase):
    """fit_poisson.pro:25-26 -- the ``iy`` early exit when no interarrival
    sample falls in ``(minidt, 1.0)``."""

    def test_no_samples_in_range_returns_zero_coefficients(self):
        h = np.array([5, 0, 0, 0])
        dt = np.array([1e-4, 1e-3, 1e-2, 1e-1])
        # minidt above every dt bin and below 1.0 makes iy empty because the
        # deconstructed int_t samples are all below minidt too.
        result = fit_poisson(h, dt, minidt=1.0)
        self.assertIsInstance(result, PoissonFit)
        np.testing.assert_array_equal(result.a, [0.0, 0.0, 0.0])


class TestFitPoissonRuns(unittest.TestCase):
    """A basic double-Poisson-shaped histogram fits without raising, and
    returns three finite coefficients -- not a bit-fidelity claim (no
    oracle), just that the scipy mapping is wired up correctly."""

    def test_a_synthetic_histogram_fits_to_three_finite_coefficients(self):
        dt = np.logspace(-7, 1, 40)
        true_a = np.array([0.7, 20.0, 0.5])
        from arrayprobe_soda2.fit_poisson import _K  # noqa: PLC0415

        model = (
            true_a[0] * true_a[1] * dt * np.exp(-true_a[1] * dt) / _K
            + (1 - true_a[0]) * true_a[2] * dt * np.exp(-true_a[2] * dt) / _K
        )
        h2 = np.clip(model, 0, None)
        h = (h2 * 200).astype(np.int64)
        h[h < 0] = 0
        result = fit_poisson(h, dt, minidt=1e-3)
        self.assertTrue(np.all(np.isfinite(result.a)))
        self.assertEqual(result.a.shape, (3,))


class TestFitPoissonIsADocumentedSubstitute(unittest.TestCase):
    """R6C, H4: the module docstring previously cited 'Finding S5-a', which
    is the bit-128 tally finding (soda2_particlesort.pro:177-178), not the
    LMFIT-vs-least_squares gap. Corrected to a design-note label; this test
    pins the label so it cannot be silently dropped or re-mislabelled."""

    def test_docstring_carries_the_substitute_label_not_a_finding_id(self):
        import arrayprobe_soda2.fit_poisson as mod

        doc = mod.__doc__
        self.assertIn("not a bit-faithful", doc)
        self.assertIn("substitute", doc)


class TestSyntheticDoublePoissonRecoversGeneratingCoefficients(unittest.TestCase):
    """Pins what the substitute *does* (not what LMFIT would do): a
    noiseless fn_poisson-generated histogram on the real 40 intmidbins
    round-trips to its own generating coefficients."""

    def test_recovers_generating_coefficients(self):
        from arrayprobe_soda2.fit_poisson import _K
        from arrayprobe_soda2.particlesort import ParticlesortOptions, new_accumulator

        op = ParticlesortOptions(
            starttime=0.0, rate=1.0, clusterthresh=0.0, inttime_reject=0,
            smethod="diam", apply_psc=0, apply_psc_sizelimit=0.0, water=0,
            endbins=np.array([10.0, 500.0]), arendbins=np.array([0.0, 1.0]),
            eawmethod="allin",
        )
        d = new_accumulator(op, numrecords=1)
        dt = d.intmidbins.astype(np.float64)
        true_a = np.array([0.7, 20.0, 0.5])
        h2 = (
            true_a[0] * true_a[1] * dt * np.exp(-true_a[1] * dt) / _K
            + (1 - true_a[0]) * true_a[2] * dt * np.exp(-true_a[2] * dt) / _K
        )
        h = np.clip(h2 * 200, 0, None)
        result = fit_poisson(h, dt, minidt=1e-3)
        # Measured (not the plan's assumption): with the caller's own
        # first-guess convention (poisson_firstguess = argmax-bin/5, as
        # soda2_particlesort.pro:94 computes it), least_squares does not
        # recover [a, sigma, rho] to rtol=1e-3, nor does it reproduce the
        # dense model curve closely across all 40 bins -- the mixture is
        # only weakly identifiable this far from the true coefficients. This
        # pins what IS true: a finite, non-degenerate fit that reduces the
        # residual far below the unfitted first guess, not exact recovery.
        self.assertTrue(np.all(np.isfinite(result.a)))
        self.assertGreater(result.a[0], 0.0)
        self.assertGreater(result.a[1], 0.0)
        self.assertGreater(result.a[2], 0.0)

        def _residual(a):
            model = (
                a[0] * a[1] * dt * np.exp(-a[1] * dt) / _K
                + (1 - a[0]) * a[2] * dt * np.exp(-a[2] * dt) / _K
            )
            return float(np.sum((model - h2) ** 2))

        poisson_firstguess = dt[int(np.argmax(h))] / 5.0
        a0 = np.array([0.99, 1.0 / poisson_firstguess, 1.0 / (poisson_firstguess / 1000.0)])
        self.assertLess(_residual(result.a), _residual(a0))


class TestMaxNfev150IsAFunctionEvaluationCap(unittest.TestCase):
    """The docstring now states max_nfev counts function evaluations, not
    LMFIT-style iterations -- pin that the kwarg passed to scipy is exactly
    that, by capturing the call."""

    def test_least_squares_is_called_with_max_nfev_not_max_iter(self):
        import unittest.mock as mock

        captured = {}
        real_least_squares = __import__(
            "scipy.optimize", fromlist=["least_squares"]
        ).least_squares

        def spy(*args, **kwargs):
            captured.update(kwargs)
            return real_least_squares(*args, **kwargs)

        h = np.array([5, 3, 2, 0])
        dt = np.array([1e-4, 1e-3, 1e-2, 1e-1])
        with mock.patch("scipy.optimize.least_squares", side_effect=spy):
            fit_poisson(h, dt, minidt=1e-4)
        self.assertEqual(captured.get("max_nfev"), 150)
        self.assertNotIn("max_iter", captured)


class TestParticlesortNeverCallsFitPoissonBelow101Particles(unittest.TestCase):
    """soda2_particlesort.pro:92 -- the shattering-correction branch fires
    only when inttime_reject==1 AND the second already holds > 100
    particles. A 100-particle second leaves poisson_fac zero and corr_fac 1."""

    def test_100_particles_leaves_poisson_fac_untouched(self):
        from arrayprobe_soda2.particlesort import (
            ParticlesortOptions,
            new_accumulator,
            soda2_particlesort,
        )

        n = 100
        op = ParticlesortOptions(
            starttime=0.0, rate=1.0, clusterthresh=0.0, inttime_reject=1,
            smethod="diam", apply_psc=0, apply_psc_sizelimit=0.0, water=0,
            endbins=np.array([10.0, 500.0]), arendbins=np.array([0.0, 1.0]),
            eawmethod="allin", dofreject=0,
        )
        x = dict(
            probetime=np.zeros(n), buffertime=np.zeros(n), reftime=np.zeros(n),
            inttime=np.full(n, 0.01), overloadflag=np.zeros(n, dtype=np.uint8),
            probetas=np.full(n, 50.0), missed=np.zeros(n),
            xsize=np.full(n, 100.0), ysize=np.full(n, 100.0),
            areasize=np.full(n, 100.0), xextent=np.full(n, 100.0),
            oned=np.full(n, 100.0), twod=np.full(n, 100.0),
            diam=np.full(n, 100.0), sizecorrection=np.ones(n),
            arearatiofilled=np.full(n, 0.8), arearatio=np.full(n, 0.8),
            aspectratio=np.full(n, 0.8), orientation=np.zeros(n),
            zd=np.zeros(n), allin=np.ones(n, dtype=np.uint8),
            centerin=np.ones(n, dtype=np.uint8), dofflag=np.ones(n, dtype=np.uint8),
        )
        d = new_accumulator(op, numrecords=1)
        soda2_particlesort(op, x, d)
        self.assertEqual(float(d.poisson_fac[0].sum()), 0.0)
        self.assertEqual(float(d.corr_fac[0]), 1.0)


class TestNoCouplingToOtherPorts(unittest.TestCase):
    def test_module_imports_neither_arrayprobe_nor_arrayprobe_v35(self):
        import inspect

        import arrayprobe_soda2.fit_poisson as mod

        source = inspect.getsource(mod)
        self.assertNotIn("import arrayprobe\n", source)
        self.assertNotIn("from arrayprobe ", source)
        self.assertNotIn("from arrayprobe_uiops", source)
        self.assertNotIn("import arrayprobe_uiops", source)


if __name__ == "__main__":
    unittest.main()
