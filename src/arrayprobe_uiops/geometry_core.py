# SPDX-License-Identifier: BSD-3-Clause
"""Shared leaf: the minimum-enclosing-circle helpers both engines use.

Moved verbatim from ``arrayprobe.geometry.min_circle``; that module re-imports them,
so its names still resolve.  Pure functions: no module state, no numba.
"""

from __future__ import annotations

import math
import random
from fractions import Fraction

import numpy as np

from .particle import shadow_mask

__all__: list[str] = []


def _shadow_points(c) -> np.ndarray:
    """The shadowed pixels of a particle image, as ``(n, 2)`` integer coordinates.

    ``CGAL_minR.cpp:56-70`` walks the MATLAB array in column-major order and
    pushes ``p = (j, i)`` -- row index first, column index second, both 0-based --
    for every entry equal to ``48``, the character ``'0'``, which is UIOOPS's
    encoding for *shadowed*.  Order does not affect the circle, so the walk is
    vectorized; the coordinate convention is kept because the centre is reported
    in it.

    Accepts either the canonical boolean ``shadow`` array (``True`` = shadowed) or
    the MATLAB char matrix itself, so a call site can pass whichever it holds.
    The coercion itself lives in :func:`arrayprobe.particle.shadow_mask` -- it
    was private here at first, and moved out once ``habit`` and ``reject``
    needed the same rule.  Three modules agreeing on which value means
    "shadowed" is worth more than three modules each being sure.
    """
    rows, cols = np.nonzero(shadow_mask(c))
    return np.column_stack((rows, cols))


def _hull_candidates(points: np.ndarray) -> list[tuple[int, int]]:
    """Reduce to a superset of the convex-hull vertices, cheaply.

    A convex-hull vertex is extreme in some direction, so it cannot lie strictly
    between two other points of the set on the same vertical line: it must be the
    topmost or bottommost point of its own column.  Keeping two points per column
    therefore preserves the hull exactly, and it collapses a dense particle from
    O(pixels) to O(columns) before any exact arithmetic runs.

    A full convex hull afterwards would shrink the set further, but not usefully:
    the incremental algorithm is expected-linear in the input size, and the
    monotone chain would cost the same sort.
    """
    cols = points[:, 1]
    order = np.argsort(cols, kind="stable")
    sorted_pts = points[order]
    sorted_cols = cols[order]
    starts = np.flatnonzero(np.r_[True, sorted_cols[1:] != sorted_cols[:-1]])
    ends = np.r_[starts[1:], len(sorted_pts)] - 1
    rows = sorted_pts[:, 0]
    keep = []
    for s, e in zip(starts, ends, strict=True):
        block = rows[s : e + 1]
        col = int(sorted_cols[s])
        keep.append((int(block.min()), col))
        keep.append((int(block.max()), col))
    return keep


# --------------------------------------------------------------------------
# Exact circle primitives.  A circle is (cx, cy, r2) over Fraction.
# --------------------------------------------------------------------------


def _contains(circle, p) -> bool:
    cx, cy, r2 = circle
    dx = Fraction(p[0]) - cx
    dy = Fraction(p[1]) - cy
    return dx * dx + dy * dy <= r2


def _from_two(a, b):
    cx = Fraction(a[0] + b[0], 2)
    cy = Fraction(a[1] + b[1], 2)
    dx = Fraction(a[0] - b[0])
    dy = Fraction(a[1] - b[1])
    return cx, cy, (dx * dx + dy * dy) / 4


def _from_three(a, b, c):
    """Circumcircle of three points, or the two-point circle when they are collinear.

    Collinear triples do reach here: three shadowed pixels in a row is an
    unremarkable particle.  The minimum circle enclosing collinear points is the
    one spanning the two extremes, which is what the fallback returns.
    """
    ax, ay = Fraction(a[0]), Fraction(a[1])
    bx, by = Fraction(b[0]), Fraction(b[1])
    cx_, cy_ = Fraction(c[0]), Fraction(c[1])
    d = 2 * (ax * (by - cy_) + bx * (cy_ - ay) + cx_ * (ay - by))
    if d == 0:
        best = _from_two(a, b)
        for pair in ((a, c), (b, c)):
            cand = _from_two(*pair)
            if cand[2] > best[2]:
                best = cand
        return best
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx_ * cx_ + cy_ * cy_
    ux = (a2 * (by - cy_) + b2 * (cy_ - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx_ - bx) + b2 * (ax - cx_) + c2 * (bx - ax)) / d
    return ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2


_TRUNCATED_PI = 3.1415926  # CGAL_EllipseSize.cpp:35's own #define PI


def _shadow_points_xy(c) -> np.ndarray:
    """Shadowed pixels as ``(n, 2)`` integer ``(col, row)`` coordinates --
    identical convention to :func:`arrayprobe.geometry.min_rectangle._shadow_points_xy`."""
    rows, cols = np.nonzero(shadow_mask(c))
    return np.column_stack((cols, rows))


def _khachiyan_ellipsoid(points: np.ndarray, tol: float = 1e-4, max_iter: int = 3000):
    """The 2D Loewner-John ellipse via Khachiyan's barycentric algorithm.

    ``points`` is ``(n, 2)`` float. Returns ``(center, shape)`` where
    ``shape`` is the symmetric positive-definite 2x2 matrix defining the
    ellipse ``{x : (x-center)^T shape (x-center) <= 1}``, or ``None`` if the
    points do not affinely span the plane (all collinear or fewer than 3
    distinct points) -- the caller handles those degenerate cases directly,
    the same way :mod:`.min_rectangle` special-cases a 1- or 2-point hull.

    Khachiyan's (1996) barycentric multiplicative-update algorithm: lift
    each point to ``(x, y, 1)``, maintain a probability weighting over the
    points, and repeatedly shift weight toward whichever point is currently
    farthest (in the Mahalanobis sense) from the running weighted
    ellipsoid, until every point is within tolerance of the boundary.
    Provably convergent to the unique minimum-volume enclosing ellipsoid
    regardless of starting weights, independent of anything CGAL's own
    algorithm does -- Todd & Yildirim (2007) is the reference for this
    convergence analysis, though the step rule used here is the classic
    Khachiyan one, not their accelerated variant.

    **A real, measured numerical property, not a theoretical nicety**: near
    the optimum this step rule has a well-documented slow tail (each step
    shrinks the remaining gap only linearly, not geometrically), so
    ``tol``/``max_iter``'s defaults target practical diode-scale accuracy
    (a few parts in 10\\ :sup:`4` on the semi-axis lengths -- far finer than
    any downstream measurement resolves) rather than machine precision.
    *Every* iterate, converged or not, defines a valid ellipsoid containing
    all the input points -- the iteration only ever shrinks a starting
    superset -- so running out of ``max_iter`` still returns a correct,
    merely very slightly non-minimal, answer; it is not treated as failure.
    """
    n = points.shape[0]
    if n < 3:
        return None
    q = np.hstack([points, np.ones((n, 1))])  # (n, 3), the lifted points
    u = np.full(n, 1.0 / n)
    d = 2  # dimension

    for _ in range(max_iter):
        qtq = (q * u[:, None]).T @ q  # (3, 3)
        try:
            qtq_inv = np.linalg.inv(qtq)
        except np.linalg.LinAlgError:
            return None  # degenerate (collinear) point set
        m = np.einsum("ij,jk,ik->i", q, qtq_inv, q)  # Mahalanobis-type scores
        j = int(np.argmax(m))
        max_m = m[j]
        if max_m <= d + 1 + tol:
            break
        step = (max_m - d - 1) / ((d + 1) * (max_m - 1))
        u = (1 - step) * u
        u[j] += step
    # Reached tolerance or exhausted max_iter -- either way `u` defines a
    # valid (if not perfectly minimal, in the latter case) enclosing
    # ellipsoid; see the docstring's note on why this is safe to use as-is.

    center = u @ points  # (2,)
    p_centered = points - center
    cov = (p_centered * u[:, None]).T @ p_centered  # (2, 2)
    try:
        shape = np.linalg.inv(cov) / d
    except np.linalg.LinAlgError:
        return None
    return center, shape


def min_area_ellipse(points):
    """The minimum-area enclosing ellipse of a 2D point set.

    Returns ``(major, minor, angle)``: full axis lengths (diameters, not
    semi-axes -- matching ``CGAL_EllipseSize.cpp``'s own ``2*sqrt(...)``
    convention) with ``major >= minor``, and ``angle`` the major axis's
    direction in radians, wrapped to ``(-pi/2, pi/2]`` the way
    ``CGAL_EllipseSize.cpp:120-124`` does. ``None`` for fewer than 3 points.

    **Degenerate point sets -- derived, not measured** (no CGAL to run):

    * **All points collinear**: the Khachiyan iteration cannot converge (the
      lifted covariance is singular), so this returns the same "degenerate
      ellipse is the spanning line segment" answer
      :func:`arrayprobe.geometry.min_rectangle.min_area_rectangle` already
      documents for its own 2-point-hull case -- ``minor = 0``, ``major``
      spans the two extreme points, ``angle`` along the line.
    """
    pts = np.asarray([(float(p[0]), float(p[1])) for p in points])
    if len(pts) < 3:
        return None

    unique = np.unique(pts, axis=0)
    if len(unique) < 3 or _is_collinear(unique):
        return _degenerate_segment_ellipse(unique)

    result = _khachiyan_ellipsoid(pts)
    if result is None:
        return _degenerate_segment_ellipse(unique)

    center, shape = result
    eigvals, eigvecs = np.linalg.eigh(shape)  # ascending eigenvalues
    # shape = V diag(eigvals) V^T; semi-axis along eigvecs[:,k] has length 1/sqrt(eigvals[k]).
    # Smaller eigenvalue -> longer (major) axis.
    semi_major = 1.0 / math.sqrt(eigvals[0])
    semi_minor = 1.0 / math.sqrt(eigvals[1])
    major_dir = eigvecs[:, 0]
    angle = _wrap_angle(math.atan2(major_dir[1], major_dir[0]))
    return 2.0 * semi_major, 2.0 * semi_minor, angle


def _is_collinear(pts: np.ndarray) -> bool:
    base = pts[0]
    rest = pts[1:] - base
    if len(rest) < 2:
        return True
    cross = rest[0, 0] * rest[:, 1] - rest[0, 1] * rest[:, 0]
    return bool(np.allclose(cross, 0.0))


def _degenerate_segment_ellipse(pts: np.ndarray):
    if len(pts) == 1:
        return 0.0, 0.0, 0.0
    diffs = pts[:, None, :] - pts[None, :, :]
    dist2 = np.einsum("ijk,ijk->ij", diffs, diffs)
    i, j = np.unravel_index(np.argmax(dist2), dist2.shape)
    dx, dy = pts[j] - pts[i]
    span = math.hypot(dx, dy)
    angle = _wrap_angle(math.atan2(dy, dx)) if span > 0 else 0.0
    return span, 0.0, angle


def _wrap_angle(angle: float) -> float:
    """``CGAL_EllipseSize.cpp:120-124`` -- wrap into ``(-pi/2, pi/2]`` using
    the source's own truncated-pi literal."""
    if angle > _TRUNCATED_PI / 2:
        angle -= 3.141592653
    if angle < -_TRUNCATED_PI / 2:
        angle += 3.141592653
    return angle


def cgal_ellipse_size(c) -> tuple[float, float, float]:
    """``CGAL_EllipseSize(c)`` -- ``(major, minor, angle)``, diode units / radians.

    Same empty-image convention as
    :func:`arrayprobe.geometry.min_rectangle.cgal_rect_size` (``CGAL_EllipseSize.cpp:82-89``):
    no shadowed pixel returns ``(0.0, 0.0, 0.0)`` directly, not NaN like
    :func:`arrayprobe_uiops.geometry_core.cgal_min_r`.
    """
    a = np.asarray(c)
    points = _shadow_points_xy(a)
    if len(points) == 0:
        return 0.0, 0.0, 0.0
    if len(points) < 3:
        span, minor, angle = _degenerate_segment_ellipse(
            np.unique(points.astype(float), axis=0)
        )
        return 1.0 + span, 1.0 + minor, angle

    result = min_area_ellipse(points)
    major, minor, angle = result
    return 1.0 + major, 1.0 + minor, angle


#: Fixed shuffle seed.  Welzl's incremental algorithm is randomized for expected
#: linear time, but the circle it returns is unique, so the seed affects speed
#: and nothing else.  It is fixed anyway: an algorithm whose *runtime* varies run
#: to run makes a slow case impossible to reproduce from a bug report.
_SEED = 0x6D696E52  # 'minR'


def min_enclosing_circle_exact(points):
    """The unique minimum enclosing circle, as exact ``(cx, cy, r2)`` Fractions.

    Source: stands in for the Miniball call in ``CGAL_minR.cpp:81-89`` (UIOOPS v3.1.4), which
    computes the same unique circle.

    Welzl's incremental algorithm (the move-to-front formulation Gaertner builds
    on).  Every comparison is exact, so there is no tolerance to tune and no
    degenerate configuration that can flip a decision the wrong way -- which is
    the failure mode a floating-point implementation has to defend against.

    Returns ``None`` for an empty point set; the caller decides what that means.
    """
    pts = [(int(p[0]), int(p[1])) for p in points]
    if not pts:
        return None
    random.Random(_SEED).shuffle(pts)

    circle = (Fraction(pts[0][0]), Fraction(pts[0][1]), Fraction(0))
    for i, p in enumerate(pts):
        if _contains(circle, p):
            continue
        circle = (Fraction(p[0]), Fraction(p[1]), Fraction(0))
        for j, q in enumerate(pts[:i]):
            if _contains(circle, q):
                continue
            circle = _from_two(p, q)
            for r in pts[:j]:
                if not _contains(circle, r):
                    circle = _from_three(p, q, r)
    return circle


def min_enclosing_circle(points):
    """:func:`min_enclosing_circle_exact` as floats: ``(cx, cy, radius)``.

    Source: stands in for the Miniball call in ``CGAL_minR.cpp:81-89`` (UIOOPS v3.1.4).

    ``None`` for an empty point set.
    """
    circle = min_enclosing_circle_exact(points)
    if circle is None:
        return None
    cx, cy, r2 = circle
    return float(cx), float(cy), math.sqrt(r2)


def cgal_min_r(c) -> float:
    """``CGAL_minR(c)`` -- the enclosing-circle diameter in diode units.

    Two edge cases, both taken from the C++ rather than invented:

    * **An empty matrix returns 0.0.**  ``CGAL_minR.cpp:47-52`` tests ``0 == m*n``
      and returns before touching Miniball.
    * **A non-empty matrix with no shadowed pixel returns NaN.**  That case falls
      through to Miniball with an empty point range.  The constructor's
      ``assert(points_begin != points_end)`` is compiled out -- MATLAB's ``mex``
      defines ``NDEBUG`` -- so ``pivot_mb`` runs its loop over nothing, leaves
      ``current_sqr_r`` at its initial ``-1`` (``Miniball.hpp:183``), and the
      caller takes ``sqrt(-1)``.  Preserved as NaN rather than "fixed" to 0: a
      zero would be a plausible diameter and would flow silently into
      ``area_ratio`` and the size distribution, where NaN is at least loud.
    """
    a = np.asarray(c)
    if a.size == 0:
        return 0.0
    points = _shadow_points(a)
    if len(points) == 0:
        return math.nan
    circle = min_enclosing_circle(_hull_candidates(points))
    return 1.0 + 2.0 * circle[2]
