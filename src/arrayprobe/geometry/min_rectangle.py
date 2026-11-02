# SPDX-License-Identifier: BSD-3-Clause
"""Minimum-area enclosing rectangle -- the replacement for ``CGAL_RectSize.mexa64``.

``CGAL_RectSize.cpp`` collects the coordinates of every shadowed pixel as
``Point_2(i, j)`` -- **column first, row second** (``i`` is the outer/column
loop, ``j`` the inner/row loop; the opposite convention from
:mod:`.min_circle`'s ``(row, col)``, kept because the *angle* output depends
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
:mod:`.min_circle`: the minimum-area bounding rectangle of a finite point set
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

``CGAL_RectSize.cpp`` is byte-identical between v3.1.4 and v3.5, so one translation serves
both engines: it lives in :mod:`arrayprobe_uiops.min_rectangle`, and this module re-exports the
same objects lazily, so importing ``arrayprobe.geometry.min_rectangle`` loads no v3.5 module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["cgal_rect_size", "min_area_rectangle"]

if TYPE_CHECKING:
    from arrayprobe_uiops.min_rectangle import _TRUNCATED_PI as _TRUNCATED_PI
    from arrayprobe_uiops.min_rectangle import _convex_hull as _convex_hull
    from arrayprobe_uiops.min_rectangle import _direction_angle as _direction_angle
    from arrayprobe_uiops.min_rectangle import _shadow_points_xy as _shadow_points_xy
    from arrayprobe_uiops.min_rectangle import cgal_rect_size as cgal_rect_size
    from arrayprobe_uiops.min_rectangle import min_area_rectangle as min_area_rectangle

_REEXPORTED = frozenset({
    "_TRUNCATED_PI",
    "_convex_hull",
    "_direction_angle",
    "_shadow_points_xy",
    "cgal_rect_size",
    "min_area_rectangle",
})


def __getattr__(name: str) -> Any:
    """Resolve a re-exported name from ``arrayprobe_uiops.min_rectangle`` on first access."""
    if name in _REEXPORTED:
        from arrayprobe_uiops import min_rectangle as _home

        value = getattr(_home, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | _REEXPORTED)
