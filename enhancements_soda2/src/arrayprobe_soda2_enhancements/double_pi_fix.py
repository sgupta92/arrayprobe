# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S2-c: ``min_circle_fast.pro`` compares against IDL's single-precision ``!pi``/``!pi/2``,
so an exact right angle at the routine's third point never takes the two-point branch.

``min_circle_fast.pro:34, :37, :41, :51`` use ``!pi`` -- IDL's FLOAT ``3.1415927410125732``,
not DOUBLE ``3.141592653589793`` (``!dpi``, which never appears in the SODA-2 tree). ``:34``'s
``angP = !pi - angR - angQ`` carries a ``+8.74e-8`` rad bias from the constant alone, and the
three obtuse-angle tests at ``:37``, ``:41`` and ``:51`` compare DOUBLE angles against FLOAT
``!pi/2`` (``1.5707963705062866``), strictly greater than the true DOUBLE right angle
(``acos(0) = 1.5707963267948966``). Consequence, measured directly by the port's own bank
(``tests/test_soda2_min_circle_fast.py::TheCornerCountReflectsThePrecisionBug::
test_right_angle_at_R_yields_three_corners_on_every_rectangle_like_case``): every rectangle,
axis-aligned pixel block and digitised disc outline takes the **three**-point branch where the
exact geometry needs only two (``rect_4``, ``block_5x3``, ``outline_20x8``,
``disc_outline_r12``, ``rect_tas_1p037``). The circle itself (``diam``, ``center``) is
unaffected to double-precision rounding; only ``corners`` changes, and since
``aspect_ratio.pro:27`` branches on ``n_elements(circle.corners)`` and uses a different
construction per branch, the changed corner count can change the reported ``orientation``/
``aspr`` for affected particles.

**Correction**: ``corrected_min_circle_fast`` re-derives ``min_circle_fast_traced`` with
``PI_SINGLE`` -> ``math.pi`` and ``HALF_PI_SINGLE`` -> ``math.pi / 2`` at all four sites,
reusing the port's own ``find_angle``, ``find_angle_array``, ``find_radius``,
``_two_point_circle``, ``MinCircle``, ``ITERATION_CAP`` and ``EmptyInput`` -- nothing else is
copied. ``corrected_aspect_ratio`` composes it with the port's own unmodified
``outline_indices``, the port's ``tas_adjust`` type-dispatch block
(``aspect_ratio.py:503-515``), and the port's own unmodified ``axis_and_ratio``.

**Scope, stated because the register's "throughout" is broader than this module.** Only
``min_circle_fast``'s four ``!pi`` uses are widened here. ``aspect_ratio.pro:53``'s
``orientation_deg`` (``180/!pi``) and ``soda2_findsize.pro:106``'s own ``_PI`` are a *different*
pair of findings (S2-e/S3-f, not yet corrected; see docs/DEFERRED.md) and are not touched -- ``orientation_deg`` still computes
in single precision, unconditionally, whichever branch of this module runs.
``src/arrayprobe_soda2/`` is never imported for writing and never modified.

**Measured impact, and why it is opt-in (not one of PROTECTIVE) since 2026-09-28.**
``enhancements_soda2/tools/double_pi_ab.py``, run against the tracked S2 and frame fixtures at
both ``yres == xres`` and ``yres != xres``: on all four runs (28 real particles pooled) not one
particle's ``aspr``/``orientation`` changed (``f == 0``, ``m == 0``), and the 20-case
``min_circle_fast`` bank changes only ``corners`` (4 of 20 cases), with ``diam`` agreeing to
``1.2e-16`` relative everywhere. This module was registered ``default_on=True`` before A14
applied the UIOOPS opt-in policy to SODA-2 (2026-09-28): the measured, real
no-op is the reason it is not in :data:`registry.PROTECTIVE` -- there is nothing here confirmed
to destroy or corrupt written data. **Caveat, stated because the sample is thin**: 28 particles
across two small tracked fixtures is not evidence that no real ORACLES particle ever exercises
this branch -- see ``BACKLOG_STATUS.md``'s row for the full numbers and this caveat spelled out.

Tests: ``tests/test_double_pi_fix.py``.
"""

from __future__ import annotations

import math

import arrayprobe_soda2.aspect_ratio as _aspect_ratio_module
import numpy as np
from arrayprobe_soda2.angles import find_angle, find_angle_array
from arrayprobe_soda2.aspect_ratio import AspectRatioResult, outline_indices
from arrayprobe_soda2.find_radius import find_radius
from arrayprobe_soda2.min_circle_fast import (
    ITERATION_CAP,
    EmptyInput,
    MinCircle,
    _two_point_circle,
)

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_min_circle_fast", "corrected_aspect_ratio"]

#: The correction: IDL's ``!dpi`` in place of the source's own single-precision ``!pi``,
#: at the same four sites ``PI_SINGLE``/``HALF_PI_SINGLE`` mark in the port.
PI_DOUBLE = math.pi
HALF_PI_DOUBLE = math.pi / 2.0


def corrected_min_circle_fast(xin, yin) -> MinCircle:
    """``min_circle_fast_traced`` (``src/arrayprobe_soda2/min_circle_fast.py:176-287``)
    re-derived with ``PI_SINGLE`` -> :data:`PI_DOUBLE` and ``HALF_PI_SINGLE`` ->
    :data:`HALF_PI_DOUBLE` at the four sites the port cites (``:34, :37, :41, :51``). Every
    other line is unchanged from the port's own translation -- this is a targeted
    re-derivation, not an independent reimplementation, so any disagreement beyond the corner
    count/branch choice is itself a finding, not expected behaviour.
    """
    xin_a = np.asarray(xin).ravel()
    yin_a = np.asarray(yin).ravel()
    area = xin_a.size
    if area == 0:
        raise EmptyInput(
            "min_circle_fast.pro has no value for an empty array -- min(y, P) "
            "on it is itself an IDL error")
    if area == 1:
        center = np.array([float(xin_a[0]), float(yin_a[0])], dtype=np.float64)
        return MinCircle(diam=0.0, center=center,
                          corners=np.array([0, 0], dtype=np.intp), area=1)

    x = xin_a.astype(np.float64)
    y = yin_a.astype(np.float64)

    p = int(np.argmin(y))

    b = y - y[p]
    a = np.abs(x - x[p])
    with np.errstate(divide="ignore", invalid="ignore"):
        b_narrowed = b.astype(np.float32).astype(np.float64)
        angle = np.arctan(b_narrowed / a)
    angle[p] = 100.0
    q = int(np.nanargmin(angle))

    c = 0
    r_idx = p
    ang_r = 0.0
    while True:
        doagain = False
        with np.errstate(divide="ignore", invalid="ignore"):
            anglearray = np.asarray(
                find_angle_array(x, y, x[p], y[p], x[q], y[q]), dtype=np.float64)
        anglearray = anglearray.copy()
        anglearray[[p, q]] = 100.0
        r_idx = int(np.nanargmin(anglearray))
        ang_r = float(anglearray[r_idx])

        ang_q = float(find_angle([x[q], y[q]], [x[r_idx], y[r_idx]], [x[p], y[p]]))
        ang_p = PI_DOUBLE - ang_r - ang_q  # corrected: DOUBLE !pi, not FLOAT

        if ang_p >= HALF_PI_DOUBLE:  # corrected: DOUBLE !pi/2
            doagain = True
            p = r_idx
        if ang_q >= HALF_PI_DOUBLE:  # corrected: DOUBLE !pi/2
            doagain = True
            q = r_idx

        c += 1
        if c > ITERATION_CAP:
            doagain = False
        if not doagain:
            break

    if ang_r >= HALF_PI_DOUBLE:  # corrected: DOUBLE !pi/2 -- an exact right angle takes this branch
        r, center = _two_point_circle(x, y, p, q)
        corners = [p, q]
    else:
        circ = find_radius([x[p], y[p]], [x[q], y[q]], [x[r_idx], y[r_idx]])
        r = np.float64(circ.r)
        center = circ.center
        corners = [p, q, r_idx]

    fell_back = not np.isfinite(r)
    if fell_back:
        ixmax, ixmin = int(np.argmax(xin_a)), int(np.argmin(xin_a))
        iymax, iymin = int(np.argmax(yin_a)), int(np.argmin(yin_a))
        xwid = float(xin_a.max()) - float(xin_a.min())
        ywid = float(yin_a.max()) - float(yin_a.min())
        if xwid > ywid:
            p, q = ixmax, ixmin
        else:
            p, q = iymax, iymin
        r, center = _two_point_circle(x, y, p, q)
        corners = [p, q]

    return MinCircle(
        diam=float(2.0 * r),
        center=np.asarray(center, dtype=np.float64),
        corners=np.array(corners, dtype=np.intp),
        area=int(area),
    )


def corrected_aspect_ratio(
    img_or_coords,
    *,
    tas_adjust=None,
    coordinates: bool = False,
    edge_rule: str | None = None,
) -> AspectRatioResult:
    """``aspect_ratio.pro``, composed from the port's own unmodified ``outline_indices`` and
    ``axis_and_ratio`` plus :func:`corrected_min_circle_fast`. The ``tas_adjust`` type-dispatch
    (FLOAT for ``np.float32``, DOUBLE otherwise) is copied verbatim from
    ``aspect_ratio.py:503-515`` -- **only the circle's precision changes**; this module does not
    widen ``tas_adjust`` handling, ``orientation_deg``'s own ``!pi`` (S2-e) or anything else.
    """
    if not coordinates:
        x_ind, y_ind_orig, _area = outline_indices(img_or_coords, edge_rule=edge_rule)
    else:
        coords = np.asarray(img_or_coords)
        x_ind = coords[:, 0].astype(np.int32)
        y_ind_orig = coords[:, 1].astype(np.int32)

    if tas_adjust is None:
        y_ind_adj = y_ind_orig
    elif isinstance(tas_adjust, np.float32):
        y_ind_adj = (y_ind_orig.astype(np.float32) * tas_adjust).astype(np.float32)
    else:
        y_ind_adj = y_ind_orig.astype(np.float64) * np.float64(tas_adjust)

    circle = corrected_min_circle_fast(x_ind, y_ind_adj)
    # Looked up through the port module at call time, not the name bound at import, so that
    # when the driver adapter also routes aspr_nan_fix / den_clamp_fix through the
    # `axis_and_ratio` hook point the three corrections compose. At rest the attribute IS the
    # imported function (enhancement_hooks.pristine()), so nothing changes without the adapter.
    aspr, orientation = _aspect_ratio_module.axis_and_ratio(x_ind, y_ind_adj, circle)
    return AspectRatioResult(
        aspr=aspr, orientation=orientation, circle=circle,
        x_ind=x_ind, y_ind=y_ind_orig,
    )


register(EnhancementSpec(
    name="double_pi_fix",
    summary="min_circle_fast's four !pi/!pi-2 comparisons run in DOUBLE (!dpi) instead of "
            "IDL's FLOAT !pi, so an exact right angle at R takes the two-point branch instead "
            "of three. Measured on the tracked S2 + frame fixtures (28 particles, equal and "
            "unequal yres:xres): zero particles changed aspr/orientation, and the min_circle_fast "
            "bank changes only corners (diam agrees to 1.2e-16 relative). Opt-in since "
            "2026-09-28: measured to be a no-op on real driver runs, so it is not one of "
            "PROTECTIVE's data-destroying corrections. See BACKLOG_STATUS.md for the numbers "
            "and the small-sample caveat.",
    finding="S2-c",
    reachability="live",
    entry_point="corrected_aspect_ratio",
))
