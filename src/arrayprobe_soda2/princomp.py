# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``princomp.pro`` -- SODA-2's orthogonal ("principal components") line fit.

23 lines of IDL, no dependencies.

**Not a geometry-chain file**, despite being ported first: the design doc's call graph said
``aspect_ratio`` calls it, and measured against the source it does not. Its only
callers in the vendored tree are ``fitexp.pro:8`` and ``fitpl.pro:11``, so it is a
distribution-**fitting** utility. The port is correct and validated; only its
stage attribution was wrong.

**What it computes, and why it is not least squares.** ``yfit = c[0] + c[1]*x``
minimising the **perpendicular** distance from each point to the line, not the
vertical one. For a particle's major axis that is the correct choice and an
ordinary least-squares fit is not: OLS is asymmetric in x and y, so rotating the
particle would change the answer. The slope comes from the larger eigenvalue of
the scatter matrix (``princomp.pro:17-20``): the larger eigenvalue
``xlam`` of the 2x2 scatter matrix; the slope ``c[1]`` as ``xlam`` minus
``sxx`` over ``sxy``; the intercept ``c[0]`` through the means
(``:19``); and the correlation as ``sxy`` over the root of ``sxx*syy``.

**Two unguarded divisions, and they are reproduced rather than fixed.**  ``sxy``
is zero for any point set with no linear correlation -- a horizontal or vertical
line, a symmetric cross, a symmetric parabola, a single point. IDL does not raise
there; it yields Inf or NaN by IEEE rules and carries on. Measured under GDL on
the vendored source (``gdl_oracle/run_soda2_princomp_bank.py``), and the four
outcomes are genuinely different, which is why they are worth pinning:

===================  ==========  ==========  =======  ====================================
case                 ``c[0]``    ``c[1]``    ``corr`` why
===================  ==========  ==========  =======  ====================================
horizontal line      NaN         NaN         NaN      ``sxy`` and ``syy`` both 0
vertical line        ``-inf``    ``+inf``    NaN      ``sxx`` 0, so ``xlam-sxx`` > 0 over 0
symmetric cross      NaN         NaN         **0**    ``xlam == sxx`` exactly, so 0/0
symmetric parabola   NaN         ``+inf``    **0**    ``xlam-sxx`` > 0 over 0
===================  ==========  ==========  =======  ====================================

Note the last two: ``corr`` is a clean **0** in both -- ``sxy`` is 0 and
``sqrt(sxx*syy)`` is positive -- while ``c[1]`` is NaN in one and ``+inf`` in the
other, decided purely by whether ``xlam - sxx`` is zero. A port that collapsed
these to a single "degenerate" answer would be wrong about three of the four.

**The length mismatch is a halt, not a return.** ``print`` then ``stop``: IDL
drops to the interactive prompt, which in a batch run ends it. Reproduced as a
raised exception, the same pattern the v3.5 port uses for ``CGAL_minR``'s
abort -- an exception is the closest Python equivalent of "execution stops here",
and returning a value would invent a behaviour the original does not have.

Provenance: ``SODA2/abansemer-soda2-afcea15/princomp.pro`` (whole file).
Validated against GDL by ``tests/test_soda2_princomp.py``.
"""
from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["PrincompLengthMismatch", "princomp"]


class PrincompLengthMismatch(RuntimeError):
    """``princomp.pro``'s own length check reached: it prints
    ``** Error: x and y arrays not the same length`` and then ``stop``, which
    halts IDL rather than returning. Raised here for the same reason the v3.5
    port raises on ``CGAL_minR``'s abort: the original does not produce a value
    on this path, so neither may the port."""


def princomp(x: ArrayLike, y: ArrayLike) -> tuple[np.ndarray, float]:
    """``c = princomp(x, y, corr)`` -- returns ``(c, corr)``.

    Source: ``princomp.pro`` (SODA-2).

    IDL's third argument is a pass-by-reference **output**; Python has no such
    thing, so it is returned alongside ``c`` rather than mutated into a caller's
    variable.

    Arithmetic is float64 throughout, matching ``dblarr(2)`` and the
    ``total()`` calls on doubled inputs. Division by zero is left to IEEE --
    see the module docstring for the four measured outcomes.
    """
    xa = np.asarray(x, dtype=np.float64).ravel()
    ya = np.asarray(y, dtype=np.float64).ravel()
    if ya.size != xa.size:
        raise PrincompLengthMismatch(
            f"x and y arrays not the same length ({xa.size} vs {ya.size}); "
            "princomp.pro prints and then stops, so there is no return value "
            "to reproduce")

    npts = xa.size
    xmean = xa.sum() / float(npts)
    ymean = ya.sum() / float(npts)
    sxx = ((xa - xmean) ** 2).sum()
    syy = ((ya - ymean) ** 2).sum()
    sxy = ((xa - xmean) * (ya - ymean)).sum()

    xlam = 0.5 * (sxx + syy) + 0.5 * np.sqrt((sxx - syy) ** 2 + 4.0 * sxy ** 2)

    # `errstate(invalid, divide)`: IDL raises nothing here and neither may we.
    # numpy would otherwise warn on 0/0 and x/0, and a warning filter set
    # elsewhere in a caller's process could turn that into an exception.
    with np.errstate(invalid="ignore", divide="ignore"):
        c1 = (xlam - sxx) / sxy
        c0 = ymean - c1 * xmean
        corr = sxy / np.sqrt(sxx * syy)

    return np.array([c0, c1], dtype=np.float64), float(corr)
