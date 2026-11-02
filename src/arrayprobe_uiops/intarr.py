# SPDX-License-Identifier: BSD-3-Clause
"""The robust bimodal inter-arrival-time fit -- IntArrAnalysis_time.m's core numeric routine.

``IntArrAnalysis_time.m:152-154`` fits a two-population exponential mixture to a
normalized inter-arrival-time histogram for each block of particles, using
MATLAB's ``nlinfit(..., statset('Robust', 'on', 'FunValCheck', 'off', 'MaxIter', 1000))``::

    bimodalfit = @(tau, dt) (1-tau(3)).*(dt/tau(1)).*exp(-dt/tau(1)) + ...
                            (tau(3)).*(dt/tau(2)).*exp(-dt/tau(2));
    tau_std = abs(nlinfit(binsCenter, h./sum(h)./width, bimodalfit, beta0, ...));

**This is the one routine in the port that structurally cannot be bit-exact against
MATLAB, and that is a documented conclusion, not an assumption** (a recorded port gap).
Neither of the port's
usual two validation layers reaches it:

* **Layer 1 (a real MATLAB-written reference)** does not exist for this routine on
  this machine -- no archived ``*_intArrThreshold_*.cdf`` product is held, and
  separately (a real finding, not this routine's own): the ORACLES 2D-S product of
  record calls ``sizeDist`` with a *missing* threshold-file argument
  (``2DS_intArrThreshold_MISSING.cdf``), so ``sizeDist.m:70`` falls back to
  ``iaThreshFile = 'NONE'`` and this routine's output was never actually consumed
  by the archived product this port targets.
* **Layer 2 (the Octave differential oracle) fails silently, not loudly, which is
  the trap worth recording.** Octave's ``optim-1.6.3`` package does ship
  ``nlinfit``/``statset`` (traced ``nlinfit.m``/``statget.m``: confirmed by running
  it -- ``statset`` prints ``warning: unrecognized option: Robust`` and
  ``...FunValCheck`` and silently drops both, computing a plain *unweighted*
  Levenberg-Marquardt fit instead of the bisquare-robust one MATLAB performs).
  A routine that *runs under Octave with no error* is not evidence it runs the
  *same algorithm* -- confirmed here by directly observing the warning, not
  inferred from reading the wrapper source alone.

**So this module is Layer 3: a documented, standard algorithm, validated on its
own terms rather than against an oracle that cannot check it.** ``robust_nlinfit``
implements bisquare iteratively-reweighted least squares (IRLS) around
``scipy.optimize.least_squares(method='lm')`` -- the same well-known robust-
regression family MATLAB's own ``nlinfit(...,'Robust','on')`` belongs to (bisquare
weight function, tuning constant 4.685, MAD-based scale estimate), but without
MATLAB's own leverage-adjustment refinement to the residuals, which cannot be
confirmed without the proprietary source or a license. This is a real, deliberate
simplification, not an oversight -- see the module's own test file for how it is
validated instead:

* ``robust=False`` reproduces exactly the *unweighted* fit -- the one case with a
  real oracle, since that is what Octave's own ``nlinfit`` silently computes even
  when asked for ``'Robust','on'``. Validated bit-close (5+ significant figures)
  against a real Octave run on a synthetic bimodal histogram
  (``tests/test_intarr.py``, ``tests/data/s8_intarr_octave_golden.json``).
* A hand-built histogram with one deliberately corrupted bin demonstrates the
  actual property this routine exists for: the unweighted fit is thrown badly off
  (a nonsensical mixture fraction > 1 in one measured case) while the robust fit
  stays close to the clean-data answer and assigns the corrupted bin exactly zero
  weight -- the qualitative behavior the MATLAB source's own comment
  ("bimodal fit still isn't achieved") exists to guard against, even though the
  two implementations' precise numeric agreement can never be checked.

Provenance: ``IntArrAnalysis_time.m`` (the ORACLES production variant's file, not shipped --
NOT the stock tree's differently-named ``IntArrAnalysis.m``, which this port does
not target). This module ports only the fit itself, not the surrounding
histogram-population loop, threshold-selection logic, or the three plotting
routines in the source -- those are not yet ported.
"""

from __future__ import annotations

import numpy as np

# scipy is an *extra* (``arrayprobe[extra]``), so it is imported lazily inside
# the one function that needs it: importing ``arrayprobe`` must not require it.

__all__ = ["bimodal_model", "robust_nlinfit", "fit_bimodal_intarr"]

_BISQUARE_TUNE = 4.685
_DEFAULT_BETA0 = (1e-2, 1e-6, 0.5)


def bimodal_model(tau, dt):
    """``IntArrAnalysis_time.m:132``'s ``bimodalfit`` -- a two-population exponential mixture.

    ``tau = (tau1, tau2, tau3)``: the two population time constants and the
    mixture fraction of population 2.
    """
    tau1, tau2, tau3 = tau
    dt = np.asarray(dt, dtype=float)
    return (1 - tau3) * (dt / tau1) * np.exp(-dt / tau1) + tau3 * (dt / tau2) * np.exp(-dt / tau2)


def _lm_fit(model, x, y, beta0, weights=None):
    if weights is None:
        def resid(beta):
            """Unweighted residual vector, the first ``nlinfit`` pass."""
            return y - model(beta, x)
    else:
        sqrt_w = np.sqrt(weights)

        def resid(beta):
            """Residuals pre-multiplied by ``sqrt(w)``.

            MATLAB's ``nlinfit`` takes weights and minimises ``sum(w * r^2)``;
            ``least_squares`` minimises ``sum(r^2)`` of whatever it is handed,
            so the weight is folded into the residual as its square root. The
            two objectives are then the same function, not merely similar.
            """
            return sqrt_w * (y - model(beta, x))

    from scipy.optimize import least_squares  # extra dependency, see module header

    result = least_squares(resid, beta0, method="lm", max_nfev=1000 * (len(beta0) + 1))
    return result.x


def _bisquare_weights(scaled_resid):
    w = np.zeros_like(scaled_resid)
    inside = np.abs(scaled_resid) < 1
    w[inside] = (1 - scaled_resid[inside] ** 2) ** 2
    return w


def robust_nlinfit(x, y, model, beta0, *, robust=True, tune=_BISQUARE_TUNE,
                    max_iter=1000, tol=1e-8):
    """Bisquare-IRLS nonlinear least squares around ``scipy.optimize.least_squares``.

    ``robust=False`` is the ordinary unweighted Levenberg-Marquardt fit -- the
    one case validated against a real Octave run, since Octave's own
    ``nlinfit(...,'Robust','on')`` silently computes exactly this (see the
    module docstring). ``robust=True`` (the default, matching the MATLAB call
    site) performs the iteratively-reweighted loop: fit, compute a MAD-based
    robust scale of the residuals, compute bisquare weights from the scaled
    residuals, refit weighted, repeat until the parameter vector stops moving
    (or ``max_iter`` is reached -- MATLAB's own ``MaxIter`` cap, matched here).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    beta0 = np.asarray(beta0, dtype=float)

    beta = _lm_fit(model, x, y, beta0)
    if not robust:
        return beta

    for _ in range(max_iter):
        resid = y - model(beta, x)
        scale = np.median(np.abs(resid)) / 0.6745
        if scale == 0 or not np.isfinite(scale):
            break  # residuals already (near) zero -- nothing left to reweight
        weights = _bisquare_weights(resid / (tune * scale))
        beta_new = _lm_fit(model, x, y, beta, weights)
        if np.allclose(beta_new, beta, rtol=tol, atol=tol):
            beta = beta_new
            break
        beta = beta_new
    return beta


def fit_bimodal_intarr(bins_center, hist_counts, width, beta0=_DEFAULT_BETA0):
    """``IntArrAnalysis_time.m:152-154`` -- the per-population bimodal robust fit.

    ``hist_counts`` is the raw histogram count array (``h`` in the source);
    normalized to a density (``h/sum(h)/width``) before fitting, exactly as the
    source does. Returns ``abs(tau)`` -- the source's own ``abs(nlinfit(...))``,
    preserved verbatim: a fit that converges to a negative time constant is
    sign-flipped, not rejected, matching MATLAB bug-for-bug.
    """
    h = np.asarray(hist_counts, dtype=float)
    y = h / h.sum() / width
    beta = robust_nlinfit(bins_center, y, bimodal_model, beta0, robust=True, max_iter=1000)
    return np.abs(beta)
