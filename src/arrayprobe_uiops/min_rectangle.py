# SPDX-License-Identifier: BSD-3-Clause
"""Minimum-area enclosing rectangle -- the replacement for ``CGAL_RectSize.mexa64``.

``CGAL_RectSize.cpp`` collects the coordinates of every shadowed pixel as
``Point_2(i, j)`` -- **column first, row second** (``i`` is the outer/column
loop, ``j`` the inner/row loop; the opposite convention from
:mod:`arrayprobe.geometry.min_circle`'s ``(row, col)``, kept because the *angle* output depends
on which axis is which) -- takes their convex hull, and calls
``CGAL::min_rectangle_2`` (the standard rotating-calipers minimum-area
bounding rectangle: Toussaint 1983; the minimum-area rectangle enclosing a
convex polygon always has one side flush with a hull edge, so trying every
hull edge as a candidate orientation is exhaustive, not heuristic). The two
resulting edge lengths get ``+1`` each (same "assume round diode, add 1 for
the boundary" convention :func:`arrayprobe_uiops.geometry_core.cgal_min_r`
documents) and are returned as ``(length, width, angle)`` with
``length >= width`` and ``angle`` the direction, in radians, of whichever of
the two actual computed edges is the *longer* one.

**Why this port can be exact where the original is not**, same reasoning as
:mod:`arrayprobe.geometry.min_circle`: the minimum-area bounding rectangle of a finite point set
is unique (up to the symmetric tie of a square), so there is no "our
algorithm versus theirs" question -- agreement is a theorem. The comparison
across candidate hull-edge orientations needs no square root at all: with an
UNNORMALIZED integer edge vector ``(dx, dy)``, a point's projection along and
perpendicular to the edge, scaled by ``|edge|``, is a plain integer dot/cross
product; dividing the resulting box area by ``edge_len_sq`` (exact
:class:`fractions.Fraction`) gives the true area without ever taking a root.
Square roots appear exactly once, at the very end, converting the winning
orientation's two squared extents into the lengths CGAL's polygon output
would have reported.

Provenance: ``CGAL_RectSize.cpp`` (whole file); called at
``imgProc_sm.m:849``, gated by ``iRectEllipse`` (never ``1`` in any real
ORACLES call -- see :mod:`arrayprobe.geometry`'s own module docstring).

**One place this port cannot claim more than "derived."** No Windows build of
the CGAL binary exists, and Octave cannot supply an oracle for a MEX-only
routine, so the degenerate cases below
were worked out by reading ``CGAL_RectSize.cpp`` and the standard rotating-
calipers algorithm, not by running the real CGAL library and comparing:

* **A single shadowed pixel** (a 1-point hull): no hull edge exists to rotate
  around. Reported as ``length = width = 1.0`` (both extents 0, then the
  ``+1``), ``angle = pi/2`` (the perpendicular-direction branch is taken
  because ``L`` is not strictly greater than ``W``, and that direction's own
  ``dx`` is 0).
* **All shadowed pixels collinear** (a 2-point hull after collapsing):
  degenerates to a zero-width rectangle -- ``length = 1 + span``,
  ``width = 1``, angle along the line.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

import numpy as np

from .particle import shadow_mask

__all__ = ["cgal_rect_size", "min_area_rectangle"]

#: The source's own truncated-pi literal (``CGAL_RectSize.cpp:134``), the
#: same one already preserved at ``imgProc_sm.m:428``/``:845`` and
#: ``sizeDist.m``'s equivalents -- not a typo unique to this file.
_TRUNCATED_PI = 3.1415926


def _shadow_points_xy(c: Any) -> np.ndarray:
    """Shadowed pixels as ``(n, 2)`` integer ``(col, row)`` coordinates.

    ``CGAL_RectSize.cpp:66-78`` walks the MATLAB array in column-major order
    and pushes ``Point_2(i, j)`` -- ``i`` the column, ``j`` the row, both
    0-based -- for every entry equal to ``48`` (``'0'``, UIOOPS's "shadowed").
    """
    rows, cols = np.nonzero(shadow_mask(c))
    return np.column_stack((cols, rows))


def _convex_hull(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Andrew's monotone chain. Exact integer arithmetic, CCW, no closing dup.

    ``cross <= 0`` (not ``< 0``) discards collinear interior points, so a
    hull of exactly-collinear input correctly collapses to its two extremes
    regardless of how many points were on the line.
    """
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> int:
        """2-D cross product of ``o->a`` and ``o->b``: >0 left turn, 0 collinear.

        Integer in, integer out -- the inputs are diode/slice indices, so this
        is exact and the ``<= 0`` turn test above has no tolerance to tune.
        """
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[int, int]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[int, int]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _direction_angle(dx: float, dy: float) -> float:
    """``atan(dy/dx)``, with the source's own ``dx==0 -> pi/2`` special case
    (``CGAL_RectSize.cpp:134``) and its truncated-pi literal."""
    if dx == 0:
        return _TRUNCATED_PI / 2
    return math.atan(dy / dx)


def min_area_rectangle(points: Any) -> Any:
    """The minimum-area bounding rectangle of an integer point set, exact.

    Source: stands in for ``CGAL::min_rectangle_2`` in ``CGAL_RectSize.cpp:96`` (UIOOPS v3.1.4).

    Returns ``(along_dx, along_dy, along_len, perp_len)``: ``along_dx``/
    ``along_dy`` is the (unnormalized) direction of the winning orientation,
    ``along_len`` the extent along it, ``perp_len`` the extent perpendicular
    to it -- both plain floats, the one place a square root happens.
    ``None`` for an empty point set.
    """
    pts = [(int(p[0]), int(p[1])) for p in points]
    if not pts:
        return None

    hull = _convex_hull(pts)

    if len(hull) == 1:
        return (1, 0, 0.0, 0.0)
    if len(hull) == 2:
        (x0, y0), (x1, y1) = hull
        dx, dy = x1 - x0, y1 - y0
        return (dx, dy, math.sqrt(dx * dx + dy * dy), 0.0)

    n = len(hull)
    best = None  # (area: Fraction, dx, dy, along_len2: Fraction, perp_len2: Fraction)
    for i in range(n):
        x0, y0 = hull[i]
        x1, y1 = hull[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        edge_len2 = dx * dx + dy * dy
        if edge_len2 == 0:
            continue  # degenerate zero-length hull edge; cannot happen after dedup, guarded anyway

        along_vals = []
        perp_vals = []
        for px, py in hull:
            qx, qy = px - x0, py - y0
            along_vals.append(qx * dx + qy * dy)          # raw projection * |edge|
            perp_vals.append(qx * dy - qy * dx)            # raw perpendicular projection * |edge|
        along_span = max(along_vals) - min(along_vals)
        perp_span = max(perp_vals) - min(perp_vals)
        area = Fraction(along_span * perp_span, edge_len2)

        if best is None or area < best[0]:
            along_len2 = Fraction(along_span * along_span, edge_len2)
            perp_len2 = Fraction(perp_span * perp_span, edge_len2)
            best = (area, dx, dy, along_len2, perp_len2)

    assert best is not None
    _, dx, dy, along_len2, perp_len2 = best
    return (dx, dy, math.sqrt(along_len2), math.sqrt(perp_len2))


def cgal_rect_size(c: Any) -> tuple[float, float, float]:
    """``CGAL_RectSize(c)`` -- ``(length, width, angle)``, diode units / radians.

    ``length >= width`` always; ``angle`` is the direction of whichever of
    the two actual rectangle edges is the longer one -- computed directly
    from ``min_area_rectangle``'s own two candidate directions, so this
    never needs to reproduce CGAL's internal polygon-edge numbering, only
    the final ``(L, W, angle)`` relationship ``CGAL_RectSize.cpp`` itself
    exposes.

    **A different empty-image convention from** :func:`arrayprobe_uiops.geometry_core.cgal_min_r`:
    ``CGAL_RectSize.cpp:81-89`` returns ``(0.0, 0.0, 0.0)`` for no shadowed
    pixel, not NaN -- confirmed by reading both C++ sources side by side
    rather than assuming the two MEX functions agree on this.
    """
    a = np.asarray(c)
    points = _shadow_points_xy(a)
    if len(points) == 0:
        return 0.0, 0.0, 0.0

    dx, dy, along_len, perp_len = min_area_rectangle(points)
    length_along = 1.0 + along_len
    length_perp = 1.0 + perp_len
    if length_along > length_perp:
        return length_along, length_perp, _direction_angle(dx, dy)
    return length_perp, length_along, _direction_angle(-dy, dx)
