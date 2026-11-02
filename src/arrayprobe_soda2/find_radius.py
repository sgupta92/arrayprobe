# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``find_radius.pro`` -- Goldman's circumradius, and the degenerate value
``min_circle_fast`` depends on.

The radius and centre of the circle through three points, from the "Triangles"
article in Graphics Gems. `min_circle_fast` calls it for its three-point case
and then tests ``IF finite(circ.r) eq 0`` — so what this routine returns for a
degenerate triangle is not an edge case, it is the branch condition of its only
caller.

::

    d1 = (p3-p1).(p2-p1)     d2 = (p3-p2).(p1-p2)     d3 = (p1-p3).(p2-p3)
    c  = d2*d3 + d3*d1 + d1*d2
    r  = 0.5*sqrt( (d1+d2)*(d2+d3)*(d3+d1) / c )
    cent = ((c2+c3)*p1 + (c3+c1)*p2 + (c1+c2)*p3) / (2*c)

**Two degenerate regimes, and they are not the same.** Measured under GDL:

=========================  ==========  ====================
input                      ``r``       ``center``
=========================  ==========  ====================
collinear, points distinct ``+inf``    ``(nan, nan)``
nearly collinear (1e-12)   ``+inf``    ``(nan, +inf)``
two points coincident      ``nan``     ``(nan, nan)``
all three coincident       ``nan``     ``(nan, nan)``
=========================  ==========  ====================

**The caller's comment about this is wrong.** ``min_circle_fast.pro`` introduces
its fallback with *"Catch and correct error which can occur if all points are on
a very long straight line"* and *"Radius will be NaN in this case"*. Measured, a
collinear triple gives **+inf**, not NaN. The code is unaffected — IDL's
``finite()`` is false for both — so this is a comment that misdescribes the value
it catches, not a defect. It is reported because a reader trusting the comment
would write a NaN-only guard and silently lose the collinear case.

Note the mixed result for the nearly-collinear triple: ``center`` comes back
``(nan, +inf)``, one coordinate of each kind. Any caller testing only
``center[0]`` would reach a different conclusion from one testing ``center[1]``.

**A stale comment in the source itself**, worth knowing when reading it: the
centre is computed in a block dated ``3-31-03`` sitting directly beneath a
comment saying *"Formula for coordinates of center is given in reference, but is
not computed here"*.

Provenance: ``SODA2/abansemer-soda2-afcea15/find_radius.pro`` (whole file).
IDL's ``##`` on two 2-vectors yields the 1×1 matrix product, i.e. the dot
product, which is what ``d1``/``d2``/``d3`` are. Validated against GDL by
``tests/test_soda2_find_radius.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["Circle", "find_radius"]


@dataclass(frozen=True)
class Circle:
    """``{r: ..., center: ...}`` -- the IDL anonymous structure this returns.

    Source: the return structure of ``find_radius.pro`` (SODA-2).

    ``r`` is a **radius**; note that ``min_circle_fast`` doubles it on the way
    out and its own return field is named ``diam``.
    """

    r: float
    center: np.ndarray


def find_radius(p1: ArrayLike, p2: ArrayLike, p3: ArrayLike) -> Circle:
    """``find_radius(p1, p2, p3)`` -- circumradius and centre of three points.

    Source: ``find_radius.pro`` (SODA-2).

    Each point is 2-element ``[x, y]``. Degenerate inputs return ``inf`` or
    ``nan`` rather than raising, exactly as the IDL does — see the module
    docstring for the four measured regimes, and note that the caller's own
    comment about which one occurs is wrong.
    """
    a = np.asarray(p1, dtype=np.float64).ravel()
    b = np.asarray(p2, dtype=np.float64).ravel()
    c_ = np.asarray(p3, dtype=np.float64).ravel()

    # np.float64, deliberately NOT Python float: `x / 0.0` on a Python float
    # raises ZeroDivisionError, where IDL -- and numpy -- yield inf or nan. The
    # degenerate values are the whole point of this routine (its caller branches
    # on them), so an exception here would replace the behaviour being ported.
    d1 = np.dot(c_ - a, b - a)
    d2 = np.dot(c_ - b, a - b)
    d3 = np.dot(a - c_, b - c_)

    cc = d2 * d3 + d3 * d1 + d1 * d2

    with np.errstate(invalid="ignore", divide="ignore"):
        r = 0.5 * np.sqrt((d1 + d2) * (d2 + d3) * (d3 + d1) / cc)
        c1, c2, c3 = d2 * d3, d3 * d1, d1 * d2
        cent = ((c2 + c3) * a + (c3 + c1) * b + (c1 + c2) * c_) / (2.0 * cc)

    return Circle(r=float(r), center=np.asarray(cent, dtype=np.float64))
