# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``fit_poisson.pro`` + ``fn_poisson.pro`` -- the double-Poisson interarrival
fit used by ``soda2_particlesort.pro:95`` when ``inttime_reject eq 1`` and a
one-second bin holds more than 100 particles.

Provenance: ``SODA2/abansemer-soda2-afcea15/fit_poisson.pro`` (49 lines) and
``fn_poisson.pro`` (16 lines), Aaron Bansemer, NCAR, 2009. Copyright (C) 2016
UCAR, 3-clause BSD.

**No GDL oracle exists for this module, and that is a measured fact, not an
assumption.** GDL 1.1.2 does not implement ``LMFIT``: it is absent from
``routine_info(/system,/functions)`` and no ``lmfit.pro`` exists under
``scripts/gdl/share/gnudatalanguage/lib`` (only ``curvefit.pro`` does). This was
checked directly, not inferred from the file list. Consequently
``fit_poisson`` cannot be validated bit-for-bit against the real IDL/GDL
routine the way every other SODA-2 module in this package is. It is **layer 3
only** (documented semantics + a pinned test), per the
three-layer validation approach, until an ``LMFIT`` oracle exists. Callers
that need a fully-oracled path should set ``op.inttime_reject = 0`` on the
accumulation module (``particlesort.py``), which then skips this branch
entirely -- exactly as the IDL does.

``fn_poisson`` (the model + its analytic Jacobian) has no numerics beyond
``alog10``/``exp`` and is a hand-derived, reference-independent port: its
correctness is checked against the closed-form derivative by finite
differences in ``tests/test_fit_poisson.py``, which is the "third side" the
project's doctrine asks for.

``fit_poisson`` itself calls IDL's ``LMFIT`` (Levenberg-Marquardt, non-linear
least squares), which this port maps to ``scipy.optimize.least_squares``
(Levenberg-Marquardt method, ``method="lm"``) rather than hand-rolling LM in
NumPy -- ``scipy`` is already an accepted *extra* dependency of this package
(see ``pyproject.toml``'s ``extra = ["scipy>=1.16", ...]``, added for other
enhancements work), so this is not a new dependency the port would otherwise
refuse.

**Documented substitute, not a bit-faithful port.** IDL ``LMFIT`` (Numerical
Recipes ``mrqmin``: ``iter`` is an iteration cap, ``tol`` defaults per the
IDL reference, convergence returned in ``converg``) and
``scipy.optimize.least_squares(method='lm')`` (MINPACK ``lmder``; ``max_nfev``
counts *function evaluations*, not iterations; ``ftol/xtol/gtol`` 1e-8) are
different algorithms with different stopping rules. Coefficients agree only
to the extent both converge to the same minimum; no oracle has confirmed even
that. Recorded as a design note, not as a finding. (IDL's own ``LMFIT``
default ``tol`` value
is not verified on this machine -- no IDL reference was opened to check it;
do not infer one.)
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

__all__ = ["fn_poisson", "fit_poisson", "PoissonFit"]

#: ``k=alog10(exp(1))``, fn_poisson.pro:6 -- converts natural-log-based
#: exponential slopes into the same log10 units the histogram is expressed in.
_K = np.log10(np.e)


def fn_poisson(dt: np.ndarray | float, ans: Sequence[float] | np.ndarray) -> np.ndarray:
    """Port of ``fn_poisson.pro``.

    ``ans = [a, sigma, rho]``. Returns a length-4 array (for scalar ``dt``)
    or an ``(4, len(dt))`` array (for array ``dt``): index 0 is the model
    value, indices 1-3 are ``d(value)/d(ans[0..2])`` -- what IDL's ``LMFIT``
    user function contract requires when it computes its own Jacobian
    analytically rather than by finite differences.

    Ported line-for-line from the IDL; the four output slots are exactly the
    source's ``out[0..3]``.
    """
    dt_arr = np.asarray(dt, dtype=np.float64)
    a0, a1, a2 = ans[0], ans[1], ans[2]

    out0 = (
        a0 * a1 * dt_arr * np.exp(-a1 * dt_arr) / _K
        + (1.0 - a0) * a2 * dt_arr * np.exp(-a2 * dt_arr) / _K
    )
    out1 = a1 * dt_arr * np.exp(-a1 * dt_arr) / _K - a2 * dt_arr * np.exp(-a2 * dt_arr) / _K
    out2 = (
        a0 * dt_arr * np.exp(-a1 * dt_arr) / _K
        - a0 * a1 * dt_arr**2 * np.exp(-a1 * dt_arr) / _K
    )
    out3 = (
        (1.0 - a0) * dt_arr * np.exp(-a2 * dt_arr) / _K
        - (1.0 - a0) * a2 * dt_arr**2 * np.exp(-a2 * dt_arr) / _K
    )

    if dt_arr.ndim == 0:
        return np.array([out0, out1, out2, out3])
    return np.stack([out0, out1, out2, out3], axis=0)


@dataclass
class PoissonFit:
    """``fit_poisson``'s return. IDL returns ``{a:[0.0,0.0,0.0]}`` on the
    empty-``iy`` early exit (``:26``) and ``{a:a}`` (the fitted coefficients)
    otherwise -- both cases are one field, ``a``, reproduced here.

    Source: the return of ``fit_poisson.pro`` (SODA-2); bare line references here are into that
    file."""

    a: np.ndarray


def fit_poisson(
    h: np.ndarray,
    dt: np.ndarray,
    minidt: float,
    plot: bool = False,
) -> PoissonFit:
    """Port of ``fit_poisson.pro``.

    ``h`` -- histogram counts at the ``dt`` midbins (``d.intspec_all[itime,
    *]`` in the caller). ``minidt`` -- first-guess separator for the two
    Poisson components.

    ``plot`` is accepted for signature parity with the IDL keyword but does
    nothing: the source's plotting branch (``:34-46``) is interactive
    visualisation, out of scope for this accumulation port and never called
    with a true value from ``soda2_particlesort.pro:95`` (``plot=0``).
    """
    h = np.asarray(h, dtype=np.float64).ravel()
    dt = np.asarray(dt, dtype=np.float64).ravel()

    # Deconstruct the histogram back into individual interarrival samples,
    # fit_poisson.pro:16-18. IDL's fltarr(h[i]) requires h[i] >= 0; a
    # negative count is a caller bug the source does not guard, so this
    # doesn't either.
    pieces = [np.full(int(h[i]), dt[i], dtype=np.float64) for i in range(len(dt)) if h[i] > 0]
    int_t = np.concatenate(pieces) if pieces else np.array([], dtype=np.float64)

    dlogdt = 0.2
    th = h.sum()
    # IDL: h/th/dlogdt with th possibly 0 -> IEEE inf/nan, not an exception.
    with np.errstate(divide="ignore", invalid="ignore"):
        h2 = h / th / dlogdt

    iy = np.where((int_t > minidt) & (int_t < 1.0))[0]
    if iy.size == 0:
        # fit_poisson.pro:26 -- IDL's `where` returning no matches gives
        # iy[0] eq -1, taken as the empty-result sentinel.
        return PoissonFit(a=np.array([0.0, 0.0, 0.0]))

    mean_iy = np.nanmean(int_t[iy])
    a0 = np.array([0.99, 1.0 / mean_iy, 1.0 / (mean_iy / 1000.0)])

    def residual(ans: np.ndarray) -> np.ndarray:
        model = fn_poisson(dt, ans)[0]
        return model - h2

    def jacobian(ans: np.ndarray) -> np.ndarray:
        # fn_poisson's own analytic partials, exactly what LMFIT's `func`
        # contract supplies as out[1:].
        return fn_poisson(dt, ans)[1:4].T

    from scipy.optimize import least_squares

    result = least_squares(
        residual,
        a0,
        jac=jacobian,
        method="lm",
        max_nfev=150,
    )
    return PoissonFit(a=result.x)
