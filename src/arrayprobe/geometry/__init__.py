# SPDX-License-Identifier: BSD-3-Clause
"""Computational geometry on particle images -- the CGAL MEX replacements.

UIOOPS ships three geometry routines (``CGAL_minR``, ``CGAL_RectSize``,
``CGAL_EllipseSize``) as compiled MEX binaries for Linux and Intel Mac only.
There is no Windows build and no build script, so on this machine the MATLAB
pipeline cannot run *at all* -- and the routine on the critical path,
``CGAL_minR``, produces ``image_diam_minR``, which is the primary particle size
whenever ``d_choice = 6``.  That is the default in every run script UIOOPS ships.

Replacing the binaries is therefore not a portability chore; it is the single
change that makes the pipeline executable here. And the replacement is
*checkable* in a way the binary never was: `Miniball.hpp` ships as source
alongside the `.cpp`, so the algorithm has a specification, and the result can
be cross-validated against brute force on small point sets and against
``image_diam_minR`` in the ORACLES reference output on real ones.

All three CGAL geometry primitives now live here: min-circle,
min-rectangle and min-ellipse. All three are gated behind
``iRectEllipse``, which the ORACLES variant sets to ``0``
(``imgProc_sm.m:51``) and which the reference product confirms -- it
carries no rectangle or ellipse variables -- so rectangle and ellipse are
not wired into ``imgproc.py``'s per-particle loop yet; they exist as
complete, tested, standalone primitives first, matching how the port shipped
``min_circle.py`` before S3 wired it in.

``min_ellipse.py`` is on a different footing from the other two, worth
knowing before trusting it as far as they're trusted: minimum-enclosing-
ellipse has no local reference algorithm the way ``Miniball.hpp`` gave
min-circle one, so it uses an independent numerical method (Khachiyan-
Todd-Yildirim) rather than reimplementing CGAL's own exact-rational
incremental algorithm from memory. See its own module docstring for the
two cross-checks that stand in for a direct oracle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from arrayprobe_uiops.geometry_core import (
    cgal_ellipse_size,
    cgal_min_r,
    min_area_ellipse,
    min_enclosing_circle,
)

if TYPE_CHECKING:
    from .min_rectangle import cgal_rect_size as cgal_rect_size
    from .min_rectangle import min_area_rectangle as min_area_rectangle

__all__ = [
    "cgal_ellipse_size",
    "cgal_min_r",
    "cgal_rect_size",
    "min_area_ellipse",
    "min_area_rectangle",
    "min_enclosing_circle",
]


def __getattr__(name: str) -> Any:
    """Resolve the rectangle names on first access.

    They live in the v3.5 engine (``CGAL_RectSize.cpp`` is byte-identical between releases), so
    importing ``arrayprobe.geometry`` loads no v3.5 module until one of them is used.
    """
    if name in ("cgal_rect_size", "min_area_rectangle"):
        from . import min_rectangle as _rect

        value = getattr(_rect, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
