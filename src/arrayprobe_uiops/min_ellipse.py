# SPDX-License-Identifier: BSD-3-Clause
"""``CGAL_EllipseSize(c)`` for v3.5 -- gains centre x/y outputs, drops the
major/minor "+1" bias v3.1.4 has.

Ported from: ``CGAL_EllipseSize.cpp`` (UIOOPS v3.5, CHANGED from v3.1.4 --
Lee Dunnavan and Joe Finlon, 29 Jan 2024). **An Octave oracle exists since 2026-09-13**: Part D
measured that the
``cgal_oracle`` conda env's CGAL headers compile this exact ``.cpp`` clean
under Octave's own ``mkoctfile --mex`` (``octave_oracle/mex_build/README.md``),
and :func:`cgal_ellipse_size` is now goldened against the real
``CGAL_EllipseSize_v35.mex`` on a dedicated non-degenerate fixture
(``octave_oracle/run_v35_rect_ellipse_bank.py``,
``tests/test_v35_rect_ellipse.py``) -- doctrine layer 2 for major/minor/x/y
(within the Khachiyan-vs-CGAL bound already established for the v3.1.4 port)
and for the angle on well-conditioned (non-circular) particles; layer 3
still, by necessity, for the near-circular tie case point 5 below describes,
where the real MEX was independently measured to disagree with ITSELF
across separate Octave processes on identical input (CGAL's ``Min_ellipse_2``
is a randomized incremental algorithm), so no run of it is more authoritative
than another to compare against. **The ellipse-fitting algorithm itself is
unchanged between versions**; the diff (read in full, both files) is:

1. **Two new outputs, ``x``/``y``, the ellipse centre** -- computed in the
   C++ from the implicit conic's coefficients: ``x = 1+(2*c*d-b*f)/(b*b-4*a*c)``,
   ``y = 1+(2*a*f-b*d)/(b*b-4*a*c)`` (``:154-155``). This is algebraically
   the conic-form route to a quantity the Khachiyan fit already produces
   directly as its own ``center`` -- see
   :func:`arrayprobe.geometry.min_ellipse._khachiyan_ellipsoid`, reused here
   unmodified. No need to reconstruct a/b/c/d/f/g to get there.
2. **``major``/``minor`` DROP the "+1." bias v3.1.4 has** (``:127-128``:
   v3.1.4 is ``major=1.+2*sqrt(...)``; v3.5 is ``major=2*sqrt(...)``, no
   leading term) -- while the NEW ``x``/``y`` outputs GAIN their own "+1"
   (the same 0-based-to-1-based MATLAB-index convention v3.1.4 puts on
   major/minor instead). Preserved exactly as measured: this is not the same
   bias moved, it is applied to different outputs than in v3.1.4.
3. **A sign-normalization block** (v3.5 only, ``:107-117``): if the conic
   coefficient ``a`` is negative, every coefficient is negated. Because the
   Khachiyan fit here never produces the raw CGAL conic coefficients at all
   (this port reaches the ellipse a different, coefficient-free way), this
   normalization has no analogue to preserve -- it is CGAL's own internal
   housekeeping for a representation this port does not use.
4. **A named ``PI = 3.1415926`` used consistently** for the angle-wrap
   comparison AND the add/subtract (``:148-152``). v3.1.4 uses
   ``3.1415926/2`` for the comparison but a DIFFERENT, more precise
   ``3.141592653`` for the actual add/subtract -- an inconsistency v3.1.4's
   own Python port (:data:`arrayprobe.geometry.min_ellipse._TRUNCATED_PI`)
   preserves exactly. v3.5 fixes the inconsistency; ported as fixed, using
   ``3.1415926`` for both sides here.
5. **Two new angle branches for the near-circular tie case**
   (``a==c and b>0`` -> ``-PI/4``; ``a==c and b<0`` -> ``PI/4``, ``:141-144``)
   are a CGAL-conic-coefficient tie-break this port has no coefficient-level
   access to reproduce (see point 3) -- **not ported, flagged as an honest
   gap**: near-circular particles (major approx minor) may get a
   numerically-valid but not CGAL-bit-identical angle from this port's
   eigendecomposition, which is not meaningfully different physically (the
   major axis of a near-circle is not a well-conditioned quantity either
   way) but is stated here rather than silently claimed as reproduced.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .geometry_core import (
    _degenerate_segment_ellipse,
    _is_collinear,
    _khachiyan_ellipsoid,
    _shadow_points_xy,
)

__all__ = ["cgal_ellipse_size"]

#: v3.5's own #define PI (CGAL_EllipseSize.cpp:40) -- used for BOTH the
#: comparison and the add/subtract, unlike v3.1.4's two-different-literals
#: inconsistency (see module docstring point 4).
_PI = 3.1415926


def _wrap_angle_v35(angle: float) -> float:
    if angle > _PI / 2:
        angle -= _PI
    if angle < -_PI / 2:
        angle += _PI
    return angle


def _min_area_ellipse_with_center(points: Any) -> Any:
    """Like :func:`arrayprobe.geometry.min_ellipse.min_area_ellipse`, but
    also returns the fit centre -- v3.1.4's version discards it because
    v3.1.4 never needed it. Returns ``(major, minor, angle, cx, cy)``;
    major/minor are full axis lengths (diameters), NOT the "+1"-biased form.

    **Bug found and fixed 2026-09-13 (Part D), not a Step-7 angle change.**
    This used to ``return None`` for fewer than 3 points before ever reaching
    the ``len(unique) < 3`` branch below -- which already exists specifically
    to give a degenerate-segment answer for 1-2 point images -- so 1- and
    2-pixel particles (``pixel1``, ``two_pixel_diagonal`` in the driver's fixture;
    "6 of 16" particles on real ORACLES data per
    ``test_cgal_mex_oracle.py::test_real_data_contains_the_A16_trigger_in_its_first_record``)
    raised ``TypeError: cannot unpack non-iterable NoneType object`` in
    :func:`cgal_ellipse_size` instead of returning the degenerate value the
    module docstring already promises ("the port returns instead of
    aborting"). Latent because Part D (``rect_ellipse.py``) is the first
    caller to reach ``extended=True`` on a real per-particle loop; the measurement block's own
    ``min_ellipse`` tests never called this function with fewer than 3
    points. The fix is simply not to special-case fewer-than-3 at all: the
    ``len(unique) < 3`` branch immediately below already handles it
    correctly (``unique`` can only be smaller than ``pts``), the same way it
    already handles a 3+-point image whose points happen to collapse to
    fewer than 3 distinct ones.
    """
    pts = np.asarray([(float(p[0]), float(p[1])) for p in points])

    unique = np.unique(pts, axis=0)
    if len(unique) < 3 or _is_collinear(unique):
        span, minor, angle = _degenerate_segment_ellipse(unique)
        if len(unique) == 1:
            cx, cy = unique[0]
        else:
            # The same two extreme points _degenerate_segment_ellipse itself
            # picks -- its own midpoint is the natural degenerate "centre".
            diffs = unique[:, None, :] - unique[None, :, :]
            dist2 = np.einsum("ijk,ijk->ij", diffs, diffs)
            i, j = np.unravel_index(np.argmax(dist2), dist2.shape)
            cx, cy = (unique[i] + unique[j]) / 2.0
        return span, minor, angle, float(cx), float(cy)

    result = _khachiyan_ellipsoid(pts)
    if result is None:
        span, minor, angle = _degenerate_segment_ellipse(unique)
        cx, cy = unique.mean(axis=0)
        return span, minor, angle, float(cx), float(cy)

    center, shape = result
    eigvals, eigvecs = np.linalg.eigh(shape)
    semi_major = 1.0 / math.sqrt(eigvals[0])
    semi_minor = 1.0 / math.sqrt(eigvals[1])
    major_dir = eigvecs[:, 0]
    angle = _wrap_angle_v35(math.atan2(major_dir[1], major_dir[0]))
    return 2.0 * semi_major, 2.0 * semi_minor, angle, float(center[0]), float(center[1])


def cgal_ellipse_size(c: Any) -> tuple[float, float, float, float, float]:
    """``CGAL_EllipseSize(c)`` -- ``(major, minor, angle, x, y)``, v3.5.

    No shadowed pixel: ``(0.0, 0.0, 0.0, 0.0, 0.0)``, matching v3.5's own
    zero-initialization of all five outputs before the early return
    (``CGAL_EllipseSize.cpp:63-64,100-101``) -- unlike v3.1.4's Python port,
    which only zero-initializes three outputs because v3.1.4 only computes
    three.
    """
    a = np.asarray(c)
    points = _shadow_points_xy(a)
    if len(points) == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    result = _min_area_ellipse_with_center(points)
    major, minor, angle, cx, cy = result
    return major, minor, angle, 1.0 + cx, 1.0 + cy
