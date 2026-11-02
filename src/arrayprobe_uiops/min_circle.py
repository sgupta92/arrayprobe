# SPDX-License-Identifier: BSD-3-Clause
"""Smallest enclosing circle, v3.5's version -- ``CGAL_minR.cpp`` gained a
true-airspeed-ratio input and a circle-centre output over v3.1.4 (Wei Wu,
June 3 2019; Joe Finlon, May 12 2019).

**What actually changed**, from the real diff (v3.1.4 vs. v3.5's
``CGAL_minR.cpp``), not the design doc's earlier one-line summary:

* A second input, ``tasRatio``. Every point's *row* coordinate is divided
  by it before the circle is computed. ``CGAL_minR.cpp:75-84`` walks the
  MATLAB array **column-major** -- ``m = mxGetM`` is the row count, and the
  inner loop variable ``j`` indexes ``ICEPIC[i*m+j]``, so ``j`` is the
  **row** and ``i`` the column::

      for i<n { for j<m { if ICEPIC[i*m+j]=='0' { p[0] = j / *tasRatio;
                                                  p[1] = i; } } }

  so ``p[0]`` is the scaled row and ``p[1]`` the unscaled column.
* The output grows from a scalar diameter to a ``1x3`` row: diameter, then
  the enclosing circle's centre in the SAME two coordinates the points were
  given in -- ``B[1] = center[0]`` = centre **row** (scaled),
  ``B[2] = center[1]`` = centre **column** (unscaled), at ``:115-120``.
  ``imgProc_sm.m``'s v3.5 call site reads them as
  ``images.minR(kk)=tempreturn(1)``, ``images.ctx(kk)=tempreturn(2)``,
  ``images.cty(kk)=tempreturn(3)`` (``:1213-1216``) -- so ``ctx`` is the
  scaled-**row** centre, ``cty`` the unscaled-**column** centre, and the
  diameter is ``1 + hypot(drow / tasRatio, dcol)``.

  **This axis convention was read the wrong way round when this module was
  first written** (``j`` taken as the column), and the error survived
  validation because the square-bank fixture fed the port the transpose of
  the matrix the MEX saw and all 30 of its non-error records are 11x11 --
  two errors that cancel exactly on a square grid. Proven both ways on 60
  non-square records against the real compiled ``CGAL_minR_v35.mex``,
  pinned by
  ``tests/test_v35_min_circle_axis.py``.
* The empty-*matrix* case (``0 == m*n``, i.e. the array itself has zero rows
  or columns -- unrelated to whether any pixel is shadowed) now sets all
  three outputs to 0.0, printing "No Illuminated Doide!" unconditionally
  (v3.1.4 has the same message, commented out, and only zeroed the single
  scalar).

**A non-empty matrix with no shadowed ('0') pixel returns NaN** -- the same
value the v3.1.4 port returns, and for the same reason. Such an image falls
through to Miniball with an empty point range in BOTH versions; the v3.5
diff added no check for it. ``Miniball.hpp:192``'s
``assert(points_begin != points_end)`` is what decides the outcome, and
whether it is live depends entirely on the **build flags**:

* Built WITHOUT ``-DNDEBUG`` -- which is what ``mex_build/`` holds, because
  Octave's bare ``mkoctfile`` does not define it -- the assert fires and the
  process aborts. That is what this module was originally written against,
  and it is the wrong oracle: no MATLAB user ever runs that binary.
* Built WITH ``-DNDEBUG``, **MATLAB's own documented ``mex`` release
  default**, the assert is compiled out, ``pivot_mb`` loops over nothing,
  ``current_sqr_r`` stays at its initial ``-1`` (``Miniball.hpp:183``) and
  the caller takes ``sqrt(-1)``. Re-measured 2026-09-16 by
  rebuilding the unmodified ``CGAL_minR.cpp`` of BOTH versions with
  ``-DNDEBUG`` and running each input in its own Octave process: v3.5
  returns ``[NaN 0 0]``, v3.1.4 returns ``NaN``, exit code 0, neither
  aborts. ``scripts/validation/octave/mex_ndebug_v35_remeasure/
  probe_results.log``.


Raising here was therefore a **behaviour this port invented** and the
original does not have, and it halted every real flight: 3,932 of 49,637
particles (7.92 %) on ``base160906064403`` hit this path, and 0 of 66 S3
blocks completed. Returning ``(nan, 0.0, 0.0)`` is a fidelity correction,
not an enhancement -- it makes the port match what MATLAB, built as MATLAB
builds it, actually produces, and it makes v3.5 agree with the v3.1.4 port
(``arrayprobe.geometry.min_circle.cgal_min_r:199-206``), which was written
against release behaviour from the start and has consequently never halted.
Pinned by ``tests/test_v35_min_circle_ndebug_matches_v314.py``.
:class:`NoShadowedPixelsError` is kept defined for importers and is not
raised on this path.

**Exact arithmetic survives the scaling.** ``tas_ratio`` is a runtime float,
but ``Fraction(tas_ratio)`` is the EXACT value of that float (Python's
``Fraction`` from a float never rounds), so dividing an integer row index by
it stays exact -- there is still no floating-point tolerance anywhere in the
circle computation, the same property that makes the v3.1.4 port exact.
The per-column hull reduction (:func:`arrayprobe.geometry.min_circle.
_hull_candidates`) is computed on the ORIGINAL, unscaled integer coordinates
before scaling is applied. It groups by column and keeps the topmost and
bottommost *row* in each: dividing every row index by the same positive
``tas_ratio`` is a monotone map, so it cannot change which point is topmost
or bottommost within a column, and it does not touch the column values the
grouping is keyed on. The reduction therefore stays exact whichever side of
the scaling it runs on, and running it first means the existing v3.1.4
helper is reused unchanged rather than re-derived.

Provenance: ``CGAL_minR.cpp`` (whole file, v3.5); called at
``imgProc_sm.m:1213-1215`` (v3.5). ``Miniball.hpp`` unchanged from v3.1.4.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

import numpy as np

from .geometry_core import (
    _from_three,
    _from_two,
    _hull_candidates,
    _shadow_points,
)

__all__ = ["cgal_min_r_v35", "NoShadowedPixelsError"]


class NoShadowedPixelsError(RuntimeError):
    """**Not raised by this module.** It names the
    abort a ``CGAL_minR`` built WITHOUT ``-DNDEBUG`` performs on a non-empty
    matrix with no shadowed pixel. Built WITH ``-DNDEBUG`` -- MATLAB's own
    ``mex`` release default -- the same source returns NaN and exits 0, so
    :func:`cgal_min_r_v35` returns ``(nan, 0.0, 0.0)`` there instead. Kept
    defined so existing importers still resolve. See the module docstring."""


def _min_enclosing_circle_exact_scaled(points: Any, tas_ratio: float) -> Any:
    """:func:`arrayprobe.geometry.min_circle.min_enclosing_circle_exact`,
    generalized to scale each point's **row** (index 0) by ``1 / tas_ratio``
    in exact rational arithmetic before running Welzl's algorithm.

    Index 0 is the row because ``_shadow_points`` returns ``(row, column)``
    and ``CGAL_minR.cpp:75-84`` divides the row index -- see the module
    docstring for the column-major derivation.

    Duplicated rather than parameterizing the v3.1.4 function: that function
    is the v3.1.4 port and must stay untouched (its own fidelity claim does
    not involve ``tas_ratio` at all), and the shuffle/incremental logic is
    small enough that copying it here is clearer than threading a scale
    factor through a function whose whole point is "no v3.5 concept leaks
    into it."
    """
    import random

    inv_tas = Fraction(1) / Fraction(tas_ratio)
    pts = [(Fraction(int(p[0])) * inv_tas, Fraction(int(p[1]))) for p in points]
    if not pts:
        return None
    random.Random(0x6D696E52).shuffle(pts)

    def contains(circle: Any, p: Any) -> Any:
        cx, cy, r2 = circle
        dx = p[0] - cx
        dy = p[1] - cy
        return dx * dx + dy * dy <= r2

    circle = (pts[0][0], pts[0][1], Fraction(0))
    for i, p in enumerate(pts):
        if contains(circle, p):
            continue
        circle = (p[0], p[1], Fraction(0))
        for j, q in enumerate(pts[:i]):
            if contains(circle, q):
                continue
            circle = _from_two(p, q)
            for r in pts[:j]:
                if not contains(circle, r):
                    circle = _from_three(p, q, r)
    return circle


def cgal_min_r_v35(c: Any, tas_ratio: float) -> tuple[float, float, float]:
    """``CGAL_minR(c, tasRatio)`` -- v3.5's 3-output form.

    Returns ``(diameter, ctx, cty)`` matching ``imgProc_sm.m``'s own
    ``tempreturn(1)``/``(2)``/``(3)`` unpacking: ``ctx`` is the enclosing
    circle's centre along the (tas-ratio-scaled) **row** axis, ``cty`` along
    the (unscaled) **column** axis. ``c`` must be given in the orientation
    the MEX itself sees -- rows are diodes, columns are slices; passing the
    transpose silently returns the two centres swapped and, whenever
    ``tas_ratio != 1``, a wrong diameter.

    Two edge cases, both taken from the C++ rather than invented -- see the
    module docstring for the full derivation:

    * **An empty matrix returns (0.0, 0.0, 0.0).** ``CGAL_minR.cpp`` (v3.5)
      tests ``0 == m*n`` and zeroes all three outputs before touching
      Miniball -- the same test v3.1.4 has, extended to the wider output.
    * **A non-empty matrix with no shadowed pixel returns
      ``(nan, 0.0, 0.0)``.** Measured on the real ``CGAL_minR.cpp`` rebuilt
      with ``-DNDEBUG``, MATLAB's own ``mex`` release default: ``[NaN 0 0]``,
      exit code 0. The same value the earlier translation returns. A non-NDEBUG
      build halts instead; :class:`NoShadowedPixelsError` stays defined
      for importers and is never raised here (see the module docstring).
    """
    a = np.asarray(c)
    if a.size == 0:
        return (0.0, 0.0, 0.0)
    points = _shadow_points(a)
    if len(points) == 0:
        # Miniball leaves current_sqr_r at -1 and the caller takes sqrt(-1);
        # the two centre outputs were never assigned past their 0.0 init.
        return (math.nan, 0.0, 0.0)
    reduced = _hull_candidates(points)
    circle = _min_enclosing_circle_exact_scaled(reduced, tas_ratio)
    center_row, center_col, r2 = circle
    diameter = 1.0 + 2.0 * math.sqrt(float(r2))
    return diameter, float(center_row), float(center_col)
