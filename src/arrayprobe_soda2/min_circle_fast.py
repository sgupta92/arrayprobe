# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
r"""``min_circle_fast.pro`` -- SODA-2's minimum-enclosing-circle routine.

**Rokne, not Welzl.** The source's own header cites *"algorithm in Graphics
Gems II, article by Jon Rokne"* and *"A faster version that eliminates the
'for' loops 6/2012"*. It is an iterative angle-based method -- take the
lowest point ``P``, find ``Q`` minimising the angle to the x-axis, then
repeatedly find ``R`` minimising angle ``PRQ`` and swap ``P`` or ``Q``
whenever their vertex angle is obtuse -- not the exact incremental algorithm
(`Miniball`, via CGAL) that this repository's own v3.1.4/v3.5 ports already
use for the same *problem*. The two can legitimately disagree on the same
points; see :mod:`tools.soda2_min_circle_vs_exact` for a search that has not
found one yet.

Four properties, each read from
the source rather than inferred:

1. **It can terminate without converging.** ``c=c+1`` / ``IF c gt 10000 THEN
   doagain=0`` caps the loop at 10 001 iterations and returns whatever
   ``P``/``Q``/``R`` it happens to hold, with no flag and no way for a caller
   to tell -- see :func:`min_circle_fast_traced` and :class:`Trace`, which
   expose this additively, and :data:`ITERATION_CAP`.
2. **The angle at ``:19`` narrows only its numerator to single precision, not
   the whole computation.** ``angle=atan(float(b)/a)``: ``b`` is cast to
   FLOAT, but ``a`` is already DOUBLE (from ``:11-12``), so IDL promotes the
   division back to DOUBLE and ``atan`` runs in DOUBLE. Measured under GDL,
   ``typename(float(b)/a)`` is **DOUBLE**, not FLOAT -- a corrected reading:
   an earlier draft of this project's own design record described the whole
   expression as "computed in single precision", which would be a different
   (and wrong) port. What actually happens: ``float(b)`` rounds ``b`` to the
   nearest float32 value, and that rounding -- not a float32 ``atan`` -- is
   what changes which point wins ``Q`` on a close call. Measured:
   ``atan(float(0.1)/3.0) = 3.3320996374401286e-02`` against pure double
   ``atan(0.1/3.0) = 3.3320995878247196e-02``; a full-float32 evaluation would
   give a third value, ``3.3320997e-02``, and silently port the wrong thing.
3. **A NaN/inf fallback for near-collinear point sets.** :func:`find_radius`
   returns non-finite for collinear input; this routine's ``IF finite(circ.r)
   eq 0`` branch (``:64``) catches it and recomputes from the maximally
   separated x or y extent instead -- two different circle definitions
   depending on conditioning, both reproduced.
4. **An acknowledged, unexplained defect sits in the source.** A commented-out
   speedup carries the author's own note: ``;Q=max(where(angle eq
   min(angle))) ;Speedup, use point furthest away to start, ** CAUSES ERROR...
   WHY? **``. Not reproduced (it is commented out in the original too); worth
   raising with NCAR as their own open item.

**`!pi` is IDL's FLOAT pi, and that is the headline finding of this file.**
``!pi`` is ``3.1415927410125732``, not double-precision
``3.141592653589793`` (``!dpi``, which appears nowhere in the whole SODA-2
tree). This routine uses ``!pi`` four times (``:34, :37, :41, :51``). Its
consequence is not cosmetic: ``angP = !pi - angR - angQ`` (``:34``) carries a
``+8.74e-8`` rad bias, and the obtuse tests at ``:37, :41, :51`` compare
DOUBLE angles against FLOAT ``!pi/2`` (``1.5707963705062866``), which is
strictly *greater* than the true DOUBLE right angle
(``acos(0) = 1.5707963267948966``). So an **exact right angle at R never
takes the two-point branch at :51** -- every rectangle, every axis-aligned
pixel block, and a digitised disc outline all take the three-point branch
instead, with an identical circle but three ``corners`` where the exact
geometry has two. GDL-measured on ``rect_4``, ``block_5x3``,
``outline_20x8``, ``disc_outline_r12`` and ``rect_tas_1p037`` -- see
``tests/data/gdl_soda2_min_circle_fast_golden.json``.


**`corners` and `area` are both part of the public contract, not incidental.**
``aspect_ratio.pro:27-49`` branches on ``n_elements(circle.corners)``, indexes
the input arrays by them, and uses their order for an orientation sign;
``soda2_findsize.pro:34`` stores ``circle.area`` as ``out.perimeterarea``.
``area`` is a misnomer worth keeping and documenting: it is simply
``n_elements(xin)``, the count of points passed in (named "area" because the
caller passes perimeter pixels), never an actual area computation.

Provenance: ``SODA2/abansemer-soda2-afcea15/min_circle_fast.pro`` (82 lines,
whole file). Calls :func:`arrayprobe_soda2.angles.find_angle`,
:func:`arrayprobe_soda2.angles.find_angle_array` and
:func:`arrayprobe_soda2.find_radius.find_radius`, all three already
GDL-validated leaves -- composed here, not re-translated. Validated against
GDL by ``tests/test_soda2_min_circle_fast.py``.
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from .angles import find_angle, find_angle_array
from .find_radius import find_radius

__all__ = [
    "PI_SINGLE",
    "HALF_PI_SINGLE",
    "ITERATION_CAP",
    "MinCircle",
    "Trace",
    "MinCircleCapWarning",
    "EmptyInput",
    "min_circle_fast",
    "min_circle_fast_traced",
]

#: IDL's ``!pi``, measured under GDL: FLOAT, not DOUBLE. ``!dpi``
#: (``3.1415926535897931``) appears nowhere in the vendored SODA-2 tree.
PI_SINGLE = float(np.float32(np.pi))  # 3.1415927410125732

#: ``!pi/2`` -- FLOAT divided by an INT literal stays FLOAT in IDL.
HALF_PI_SINGLE = float(np.float32(np.pi) / np.float32(2))  # 1.5707963705062866

#: ``min_circle_fast.pro:48`` -- the loop is stopped once ``c`` passes 10000. The loop
#: body always runs at least once before the test, so the maximum iteration
#: count actually reached is ``ITERATION_CAP + 1`` (10 001).
ITERATION_CAP = 10000


class EmptyInput(ValueError):
    """``xin``/``yin`` had zero elements.

    The IDL has no explicit guard for this: ``min(y, P)`` on an empty array is
    itself an IDL error, so there is no return value from the original to
    reproduce here -- raising is the port's own choice, not a translated one.
    """


class MinCircleCapWarning(UserWarning):
    """Opt-in only (see ``warn_on_cap``): the 10001-iteration cap was hit.

    The IDL emits nothing here -- no flag, no message -- so a warning is
    itself a behaviour change relative to the source, and this project's own
    tests run degenerate inputs under ``warnings.simplefilter("error")``,
    where a warning becomes an exception the IDL never raises. Silent by
    default; see :func:`min_circle_fast_traced` for the always-on channel.
    """


@dataclass(frozen=True)
class MinCircle:
    """The IDL anonymous structure ``{diam, center, corners, area}``.

    ``diam`` is a **diameter** (the source's own comment: ``;RETURNS
    *DIAMETER*``). ``corners`` is 0-based indices into ``xin``/``yin`` in the
    order the IDL builds them -- ``[P, Q]``, ``[P, Q, R]``, or the fallback's
    ``[i_max, i_min]`` -- consumed by ``aspect_ratio.pro:27-49`` for both its
    branch and its orientation sign. ``area`` is ``len(xin)``, not a
    geometric area; kept under this name because ``soda2_findsize.pro:34``
    reads it as ``circle.area``.
    """

    diam: float
    center: np.ndarray
    corners: np.ndarray
    area: int


@dataclass(frozen=True)
class Trace:
    """What the IDL computes but never returns -- exposed additively.

    ``niter`` is the number of times the ``REPEAT...UNTIL`` body ran (so
    ``ITERATION_CAP + 1`` marks a capped run); ``hit_cap`` and ``fell_back``
    name the two mechanisms SODA-2 register entry S2-h found to be one (the fallback's
    ``finite()`` test at ``:64`` is, for finite duplicate-free input, only
    ever reached after the cap); ``q0`` is the initial ``Q`` chosen at
    ``:21``, before any swap.
    """

    niter: int
    hit_cap: bool
    fell_back: bool
    q0: int | None


def _two_point_circle(
    x: np.ndarray, y: np.ndarray, p: int, q: int,
) -> tuple[np.floating, np.ndarray]:
    r = np.sqrt((x[p] - x[q]) ** 2 + (y[p] - y[q]) ** 2) / 2.0
    center = np.array([(x[p] + x[q]) / 2.0, (y[p] + y[q]) / 2.0])
    return r, center


def min_circle_fast_traced(
    xin: ArrayLike, yin: ArrayLike, *, _angle_at_q: Callable[..., float] | None = None,
) -> tuple[MinCircle, Trace]:
    """``min_circle_fast(xin, yin)`` plus everything the IDL computes but
    discards on return -- see :class:`Trace`. :func:`min_circle_fast` is a
    thin wrapper that keeps only the first element.

    Source: ``min_circle_fast.pro`` (SODA-2).

    Degenerate arithmetic (``0.0/0.0``, ``x/0.0``) is kept in numpy scalars
    throughout, never a bare Python ``float`` division -- ``x / 0.0`` on a
    Python ``float`` raises ``ZeroDivisionError`` where IDL, and numpy, yield
    ``inf``/``nan``. Those values are the behaviour being ported: the fallback
    at ``:64`` branches on exactly this.

    ``_angle_at_q`` is a **private, test-only** hook (default
    :func:`~arrayprobe_soda2.angles.find_angle`, matching ``:33`` exactly).
    It exists only so a formula-pairing
    search can pass :func:`~arrayprobe_soda2.angles.find_angle_array` instead,
    wrapped to the same ``(p1, p2, p3)`` calling convention, to look for a
    case where the formula pairing of SODA-2 register entry S2-a changes
    which ``corners`` come back.
    :func:`min_circle_fast` never sets it.
    """
    xin_a = np.asarray(xin).ravel()  # :1  ORIGINAL type/values -- the fallback uses these, not x/y
    yin_a = np.asarray(yin).ravel()
    area = xin_a.size
    if area == 0:
        raise EmptyInput(
            "min_circle_fast.pro has no value for an empty array -- min(y, P) "
            "on it is itself an IDL error")
    if area == 1:  # :10
        center = np.array([float(xin_a[0]), float(yin_a[0])], dtype=np.float64)
        return (MinCircle(diam=0.0, center=center,
                           corners=np.array([0, 0], dtype=np.intp), area=1),
                Trace(niter=0, hit_cap=False, fell_back=False, q0=None))

    x = xin_a.astype(np.float64)  # :11
    y = yin_a.astype(np.float64)  # :12

    p = int(np.argmin(y))  # :14  dummy=min(y,P) -- first index on ties (GDL-measured)

    b = y - y[p]  # :17
    a = np.abs(x - x[p])  # :18
    with np.errstate(divide="ignore", invalid="ignore"):
        # :19  angle=atan(float(b)/a) -- ONLY `b` narrows to float32; `a` is
        # already double, so the division promotes back to double and atan
        # runs in double (measured: typename(float(b)/a) is DOUBLE). The
        # narrowing of `b` alone -- not a float32 atan -- is what can flip Q.
        b_narrowed = b.astype(np.float32).astype(np.float64)
        angle = np.arctan(b_narrowed / a)
    angle[p] = 100.0  # :20  sentinel -- ignore P itself
    q = int(np.nanargmin(angle))  # :21  min(angle, Q) -- GDL skips NaN (measured)
    q0 = q

    angle_at_q = _angle_at_q or find_angle

    c = 0
    r_idx = p  # keeps mypy/pyflakes happy across the loop; always reassigned below
    ang_r = 0.0
    while True:  # :25-49  REPEAT ... UNTIL not doagain (a do-while)
        doagain = False
        with np.errstate(divide="ignore", invalid="ignore"):
            anglearray = np.asarray(
                find_angle_array(x, y, x[p], y[p], x[q], y[q]), dtype=np.float64)  # :29
        anglearray = anglearray.copy()
        anglearray[[p, q]] = 100.0  # :30
        r_idx = int(np.nanargmin(anglearray))  # :31  GDL's min() skips NaN
        ang_r = float(anglearray[r_idx])

        # :33  dot product, NOT find_angle_array -- see the module docstring / S2-a
        ang_q = float(angle_at_q([x[q], y[q]], [x[r_idx], y[r_idx]], [x[p], y[p]]))
        ang_p = PI_SINGLE - ang_r - ang_q  # :34  FLOAT !pi widened into double arithmetic

        if ang_p >= HALF_PI_SINGLE:  # :37-40  NaN >= x is False, as in IDL
            doagain = True
            p = r_idx
        if ang_q >= HALF_PI_SINGLE:  # :41-44
            doagain = True
            q = r_idx

        c += 1
        if c > ITERATION_CAP:  # :47-48
            doagain = False
        if not doagain:
            break

    if ang_r >= HALF_PI_SINGLE:  # :51  FLOAT !pi/2 -- an exact right angle fails this test
        r, center = _two_point_circle(x, y, p, q)  # :53-54
        corners = [p, q]
    else:
        circ = find_radius([x[p], y[p]], [x[q], y[q]], [x[r_idx], y[r_idx]])  # :59
        r = np.float64(circ.r)
        center = circ.center
        corners = [p, q, r_idx]  # :60

    fell_back = not np.isfinite(r)  # :64  finite() is False for both NaN and +inf
    if fell_back:
        ixmax, ixmin = int(np.argmax(xin_a)), int(np.argmin(xin_a))  # :65
        iymax, iymin = int(np.argmax(yin_a)), int(np.argmin(yin_a))  # :66
        xwid = float(xin_a.max()) - float(xin_a.min())
        ywid = float(yin_a.max()) - float(yin_a.min())
        if xwid > ywid:  # :68  strict gt -- a tie goes to y
            p, q = ixmax, ixmin
        else:  # :71-74
            p, q = iymax, iymin
        r, center = _two_point_circle(x, y, p, q)  # :75-76
        corners = [p, q]  # :78

    circle = MinCircle(
        diam=float(2.0 * r),
        center=np.asarray(center, dtype=np.float64),
        corners=np.array(corners, dtype=np.intp),
        area=int(area),
    )
    trace = Trace(niter=c, hit_cap=c > ITERATION_CAP, fell_back=fell_back, q0=q0)
    return circle, trace


def min_circle_fast(xin: ArrayLike, yin: ArrayLike, *, warn_on_cap: bool = False) -> MinCircle:
    """``min_circle_fast(xin, yin)`` -- SODA-2's minimum bounding circle.

    Source: ``min_circle_fast.pro`` (SODA-2).

    ``warn_on_cap`` is an opt-in flag, **defaulting OFF** per this project's
    fidelity doctrine: the IDL returns whatever it holds at the 10001st
    iteration with no signal at all, so silence is the faithful default. When
    ``True`` and the cap was hit, emits :class:`MinCircleCapWarning`; it
    changes no returned field (pinned by a silent-by-default test).
    """
    circle, trace = min_circle_fast_traced(xin, yin)
    if warn_on_cap and trace.hit_cap:
        warnings.warn(
            MinCircleCapWarning(
                f"iteration cap {ITERATION_CAP} reached after {trace.niter} "
                "iterations; result is whatever P/Q/R were held, as in "
                "min_circle_fast.pro:48"),
            stacklevel=2)
    return circle
