# SPDX-License-Identifier: BSD-3-Clause
"""``imgProc_sm.m:1293-1301,1361-1374`` (v3.5) -- the ``iRectEllipse`` unit (Part D).

Computed once per particle, right after ``axis_ratio`` (``measure.py``'s
``:1287-1291``) and before the area-ratio recomputation (``:1302-1309``,
already inside :func:`arrayprobe_uiops.measure.measure_record` as
:func:`arrayprobe_uiops.imgproc._percent_shadow`)::

    if 1==iRectEllipse
        [images.RectangleL(kk), images.RectangleW(kk), ...
            images.RectangleAngle(kk)] = CGAL_RectSize(c);
        if hasExtendedOutputs
            [images.EllipseL(kk), images.EllipseW(kk), images.EllipseAngle(kk), ...
                images.EllipseY(kk), images.EllipseX(kk)] = CGAL_EllipseSize(c);
        else
            [images.EllipseL(kk), images.EllipseW(kk), ...
                images.EllipseAngle(kk)] = CGAL_EllipseSize(c);
        end
    end

``c`` is the record loop's post-QC particle image (``imgproc.py:590``, or its
:func:`arrayprobe_uiops.qc.qc_image` replacement under ``iQC==1``) -- the SAME
``c`` the reject call and the habit call already consume, **not** a
TAS-rescaled copy (only ``CGAL_minR`` gets ``tasRatio``, ``:1275-1280`` /
:func:`arrayprobe_uiops.min_circle.cgal_min_r_v35`). It is passed to
``CGAL_RectSize``/``CGAL_EllipseSize`` completely unconverted -- both ported
routines read it through :func:`arrayprobe.particle.shadow_mask`, which
already accepts the raw ASCII ``'0'``/``'1'`` (48/49) form
:func:`arrayprobe.matlab_compat.dec2bin_concat` produces, so no ``codes``
array needs to be built here the way
:func:`arrayprobe_uiops.measure._ascii` builds one for the reject/habit calls --
pinned by ``tests/test_v35_rect_ellipse.py``'s two Step-1 MEX cases either way.

**Two CGAL sources, two fidelity stories:**

* ``CGAL_RectSize.cpp`` is SHA-256 **identical** between v3.1.4 and v3.5 (the
  same file the v3.1.4 port already goldens against the real MEX,
  ``tests/test_cgal_mex_oracle.py``), so
  :func:`arrayprobe_uiops.min_rectangle.cgal_rect_size` serves both
  releases -- **reused, not reimplemented**, following the
  ``FORK_ONLY``/``SHARED`` distinction in ``uiops.CATALOGUE``.
* ``CGAL_EllipseSize.cpp`` **differs**: v3.5 drops v3.1.4's ``major``/``minor``
  ``+1.`` bias, adds the two centre outputs (their own ``+1``), a sign
  normalisation, and two near-circular tie-break angle branches (see
  :mod:`arrayprobe_uiops.min_ellipse`'s own module docstring for the full diff).
  ``hasExtendedOutputs`` (``imgProc_sm.m:255-272``) selects which binary is on
  the MATLAB path and therefore which of the two output schemas is written --
  recorded here as the caller-supplied ``extended`` flag rather than probed at
  run time (the binary-dependent output schema). ``extended=True`` calls
  :func:`arrayprobe_uiops.min_ellipse.cgal_ellipse_size` (5 outputs, the
  ``CGAL_EllipseSize_v35.mex`` binary this stage compiled);
  ``extended=False`` calls
  :func:`arrayprobe.geometry.min_ellipse.cgal_ellipse_size` (3 outputs, the
  ``+1``-biased v3.1.4 form -- what an *old* binary left on the path actually
  writes for a v3.5 run, ``:1299``).

**Y before X is correct, not a defect** (``:1297``). ``CGAL_EllipseSize.cpp``
pushes ``Point(i, j)`` with ``i`` the MATLAB **column** (diode) index and
``j`` the **row** (slice/time) index (``:79-88``), so its 4th output (C++
"x", ``:154``) is the diode-direction centre and its 5th ("y", ``:155``) is
the time-direction centre -- matching the netCDF descriptions
(``imgProc_sm.m:547-557``): ``image_EllipseX`` is "time direction",
``image_EllipseY`` is "photodiode direction". MATLAB's destructuring
assigns the 4th output to the variable named ``EllipseY`` and the 5th to
``EllipseX``, i.e. it un-swaps the C++'s x/y naming back onto its own
axis-labelled variables. :func:`arrayprobe_uiops.min_ellipse.cgal_ellipse_size`
returns ``(major, minor, angle, 1+cx, 1+cy)`` in that same C++ (diode, time)
order, so here too the 4th value goes to ``ell_y`` and the 5th to ``ell_x``.

**MATLAB's collinear-particle ellipse abort does not happen in this port.**
``CGAL_EllipseSize.cpp`` has no degeneracy guard -- CGAL's
``Optimisation_ellipse_2.h:250`` precondition ``!is_degenerate()`` fires on a
collinear point set (a one-diode-wide or one-slice-tall particle, common in
real 2D-S data) and ``std::terminate`` kills the whole MATLAB session,
uncatchable from ``.m`` code (``tests/test_cgal_mex_oracle.py:113-134``).
Both Python ellipse routines instead return a finite degenerate-segment
answer (:func:`arrayprobe.geometry.min_ellipse._degenerate_segment_ellipse`)
-- the same "a port must not reproduce a silent or fatal failure quietly"
call already made for :class:`arrayprobe.imgproc.ImageWidthMismatch`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .geometry_core import cgal_ellipse_size as _cgal_ellipse_size_v314
from .min_ellipse import cgal_ellipse_size as _cgal_ellipse_size_v35
from .min_rectangle import cgal_rect_size

__all__ = ["RectEllipse", "rect_ellipse_for_image"]


@dataclass(frozen=True)
class RectEllipse:
    """One particle's ``:1293-1301`` outputs, diode units / radians (unscaled
    by ``diode_size`` -- the caller applies that at the ``:1364-1373`` writer,
    the same split :func:`arrayprobe_uiops.measure.ParticleMeasurement` uses for
    ``minR``/``AreaR``/``Perimeter``).

    Source: ``imgProc_sm.m:1293-1301`` (UIOOPS v3.5)."""

    rect_l: float
    rect_w: float
    rect_angle: float
    ell_l: float
    ell_w: float
    ell_angle: float
    ell_x: float | None  #: time direction; ``None`` unless ``extended``
    ell_y: float | None  #: photodiode direction; ``None`` unless ``extended``


def rect_ellipse_for_image(c: Any, *, extended: bool) -> RectEllipse:
    """``:1293-1301`` for one particle image ``c``.

    Source: ``imgProc_sm.m:1293-1301`` (UIOOPS v3.5).

    ``extended`` is the recorded ``hasExtendedOutputs`` flag (module
    docstring) -- ``True`` selects the 5-output v3.5 ``CGAL_EllipseSize``
    schema, ``False`` the 3-output v3.1.4-binary schema a v3.5 run gets when
    an old ``.mex`` is on the MATLAB path.
    """
    rect_l, rect_w, rect_angle = cgal_rect_size(c)
    if extended:
        ell_l, ell_w, ell_angle, out4, out5 = _cgal_ellipse_size_v35(c)
        ell_y, ell_x = out4, out5  # :1297 -- Y<-output4 (diode), X<-output5 (time)
        return RectEllipse(rect_l, rect_w, rect_angle, ell_l, ell_w, ell_angle, ell_x, ell_y)
    ell_l, ell_w, ell_angle = _cgal_ellipse_size_v314(c)
    return RectEllipse(rect_l, rect_w, rect_angle, ell_l, ell_w, ell_angle, None, None)
