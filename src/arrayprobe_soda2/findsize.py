# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_findsize.pro`` -- every size SODA-2 reports, from one silhouette.

89 lines of IDL. Calls ``aspect_ratio`` (and, through it, ``min_circle_fast``
and ``find_angle``), all already ported and GDL-validated.

Provenance: ``SODA2/abansemer-soda2-afcea15/soda2_findsize.pro`` (whole file),
Aaron Bansemer, NCAR, 2009. Copyright (C) 2016 UCAR, 3-clause BSD.
Validated against GDL by ``tests/test_soda2_findsize.py``; bank at
``gdl_oracle/run_soda2_findsize_bank.py``, 22 cases, all matching, 12 of them
without any shim.

**Seven size definitions, and they are not variants of one number.** A caller
choosing between them is making a physics decision, so the port keeps all
seven and names what each one measures:

===============  =========================================================
field            what it is
===============  =========================================================
``xsize``        extent along the diode axis, shadowed columns, inclusive
``ysize``        extent along the slice axis
``diam``         ``(circle.diam + 1) * xres`` -- the minimum enclosing
                 circle, plus one pixel for the 0.5 shading threshold
``areasize``     ``diam * sqrt(ar)`` -- area-equivalent, and the only one
                 that corrects for a partially imaged particle
``xextent``      the largest per-*slice* diode span; Korolev's ``Ly``
``oned``         a 1-D probe emulation: diodes latch once shadowed
``twod``         a 2-D probe emulation: the fullest single slice
===============  =========================================================

``oned`` and ``twod`` are both per Lyle Lilie, 12/2020, and both deliberately
ignore gaps. They differ whenever a particle's shadowed diodes are not all
shadowed in the same slice -- see the bank's
``gap_makes_oned_and_twod_differ``, where ``oned`` is 4 pixels and ``twod`` 2.

**The zero-area early return hands back defaults that look like measurements.**
``:13`` returns the predefined structure when ``area_original`` is 0, and that
structure declares ``centerin: 1b`` and ``allin: 0b``. So an empty image
reports *centre-in* and *not all-in* — the first of which is an assertion the
routine never checked. Nothing in the return distinguishes it from a real
particle that happens to score zero. Finding **S3-e**.

**And it is reachable by an integer resolution.** ``area_original = total(img)
* (yres/xres)``: if a caller passes ``xres``/``yres`` as IDL INTs, that
division is *integer* division, ``yres/xres`` is 0 for any ``yres < xres``,
and every particle silently reports zero for every size. ``soda2_samplearea``
guards against exactly this with ``float()`` at its ``:17-18``; this routine
does not. Measured — the bank's own generator fell into it before it was a
case. Finding **S3-d**. The port reproduces it: pass ``np.int32`` resolutions
and you get zeros, as IDL does.

**``img`` is reformed in place.** ``:15-18`` reforms ``img`` to a single-slice 2-D shape
for 1-D input, and IDL passes a named variable by reference, so **the
caller's own array comes back reshaped**. Measured: a 1-D array of 9 goes in
and ``size(img,/dimensions)`` afterwards reports ``9x1``. Finding **S3-c**.
Python has no such semantics; :func:`soda2_findsize` never mutates its
argument, and :data:`RESHAPES_CALLER_INPUT` documents the divergence so a
caller porting IDL code that *relied* on it is not silently surprised.

**``centerin`` is decided by extent, not by shadow count**, at ``:52`` and
``:58``, with the shadow-count version sitting commented out directly above
each — *"This center-in method seems to work best so far, based on
simulations."* The test is ``ge``, not ``gt``, so a tie sets ``centerin = 0``.
Both are preserved and both are pinned by the bank.

**``!pi`` is single precision** (finding S2-c), and it appears twice in the
truncated-circle geometry at ``:81``. ``_PI`` below is ``np.float32(pi)`` for
that reason, not for speed.

**The truncation runs in DOUBLE and the all-in branch in FLOAT.** ``:76``
takes ``x`` from ``circle.center[0]`` -- the raw DOUBLE that ``find_radius``
produced -- and not from ``out.c[0]``, the FLOAT copy stored into the output
struct two lines earlier. So every expression in the ``allin eq 0`` branch
promotes to double, while ``circle_area_imaged = !pi * r^2`` on the other
branch has no DOUBLE operand and stays single. The same quantity is therefore
computed at two precisions depending on where the particle sat on the array.
Finding **S3-f**, and the same FLOAT/DOUBLE mixture S2-e reports for
``aspect_ratio``. This port got it wrong first -- it used ``out.c[0]`` -- and
the error was 7e-8 relative in ``ar``, one float32 ulp, which the golden
caught on every edge-touching case and no amount of reading had.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from arrayprobe_soda2.aspect_ratio import _op as _idl_op
from arrayprobe_soda2.aspect_ratio import aspect_ratio

__all__ = [
    "RESHAPES_CALLER_INPUT",
    "FindSizeResult",
    "soda2_findsize",
]

#: IDL reforms the caller's own ``img`` in place for 1-D input (``:16``);
#: this port does not. Named so the divergence is greppable rather than
#: buried in prose. See the module docstring, finding S3-c.
RESHAPES_CALLER_INPUT = False

#: ``!pi``, which IDL types as FLOAT and never as ``!dpi`` anywhere in
#: SODA-2 (finding S2-c). Used at ``:81`` twice.
_PI = np.float32(math.pi)

#: IDL's ``< 1`` at :77-78 and ``< 1.0`` at :83-84 -- one is an INT literal
#: and the other a FLOAT one, and the difference is load-bearing. An INT does
#: not promote a FLOAT operand, so the double precision of the truncation
#: geometry comes entirely from ``x`` being ``circle.center[0]``'s DOUBLE.
#: Writing a Python ``1.0`` here instead would promote the expression by
#: itself and mask that -- measured: it made the "take x from the FLOAT copy"
#: mutation pass, i.e. the test stopped guarding the thing it was written for.
_ONE_INT = np.int16(1)
_ONE_FLOAT = np.float32(1.0)


def _f(value: Any) -> np.float32:
    """A bare IDL decimal literal: FLOAT, not DOUBLE."""
    return np.float32(value)


def _idl_div(a: Any, b: Any) -> Any:
    """``a / b`` as IDL evaluates it, integer division included.

    NumPy's ``/`` is true division for every dtype, so ``np.int32(5) /
    np.int32(10)`` is 0.5 where IDL gives **0**. That difference is the whole
    of finding S3-d, and a port using bare ``/`` here would quietly repair the
    defect it is meant to reproduce -- which is worse than not porting the
    line, because the repair is invisible.

    IDL truncates toward zero rather than flooring, so ``-1/2`` is 0 and not
    NumPy's ``-1``. Both operands must be integer types for this to apply;
    one FLOAT promotes the whole expression, which is exactly why
    ``soda2_samplearea``'s ``float()`` casts work as a guard.
    """
    a_arr, b_arr = np.asarray(a), np.asarray(b)
    if (np.issubdtype(a_arr.dtype, np.integer)
            and np.issubdtype(b_arr.dtype, np.integer)):
        quotient = np.trunc(a_arr.astype(np.float64)
                            / b_arr.astype(np.float64))
        return quotient.astype(a_arr.dtype)
    return a / b


@dataclass
class FindSizeResult:
    """``soda2_findsize.pro``'s predefined output structure (``:9-10``), field
    for field and in declaration order.

    The declared types are part of the contract and are reproduced: the seven
    sizes and ``ar``/``arfilled``/``aspr``/``orientation`` are declared
    ``0.0`` (FLOAT); ``perimeterarea`` is ``0L`` (LONG); ``allin``,
    ``centerin`` and ``edgetouch`` are BYTE; ``c`` is ``fltarr(2)``.
    """

    diam: np.float32 = field(default_factory=lambda: np.float32(0.0))
    xsize: np.float32 = field(default_factory=lambda: np.float32(0.0))
    ysize: np.float32 = field(default_factory=lambda: np.float32(0.0))
    areasize: np.float32 = field(default_factory=lambda: np.float32(0.0))
    ar: np.float32 = field(default_factory=lambda: np.float32(0.0))
    arfilled: np.float32 = field(default_factory=lambda: np.float32(0.0))
    aspr: np.float32 = field(default_factory=lambda: np.float32(0.0))
    allin: int = 0
    c: np.ndarray = field(
        default_factory=lambda: np.zeros(2, dtype=np.float32))
    centerin: int = 1
    orientation: np.float32 = field(default_factory=lambda: np.float32(0.0))
    perimeterarea: int = 0
    edgetouch: int = 0
    xextent: np.float32 = field(default_factory=lambda: np.float32(0.0))
    oned: np.float32 = field(default_factory=lambda: np.float32(0.0))
    twod: np.float32 = field(default_factory=lambda: np.float32(0.0))


def _as_2d(img: Any) -> np.ndarray:
    """``img`` as ``(n_slices, n_diodes)``.

    **This is the transpose of IDL's own indexing, and it is the convention
    every image in this port already uses** -- ``aspect_ratio.outline_indices``
    documents it, and ``min_circle_fast``'s tie-breaking depends on the C-order
    ``ravel()`` of exactly this layout matching IDL's flat ``where`` order.
    So ``img[x, y]`` in the source is ``im[y, x]`` here, and IDL's ``dim=1``
    (reduce over x) is ``axis=1`` while its ``dim=2`` (reduce over y) is
    ``axis=0``. Every reduction below names which it is.

    ``:15-18``'s reform is reproduced on a local copy: a 1-D input becomes one
    slice. The only thing not reproduced is the write-back to the caller's
    variable (:data:`RESHAPES_CALLER_INPUT`).
    """
    arr = np.asarray(img)
    if arr.ndim == 1:
        return arr.reshape(1, arr.shape[0])
    return arr


def soda2_findsize(
    img: Any,
    xres: Any,
    yres: Any,
    voidarea: Any = 0,
) -> FindSizeResult:
    """``out = soda2_findsize(img, xres, yres, voidarea=voidarea)``.

    Source: ``soda2_findsize.pro`` (SODA-2).

    ``img`` is a binary silhouette indexed ``[diode, slice]``, matching IDL's
    ``img[x, y]``. ``xres`` and ``yres`` are micrometres per pixel along the
    diode and slice axes.

    **Pass FLOAT resolutions.** An integer ``xres``/``yres`` reproduces IDL's
    integer division at ``:11`` and can zero every returned size without
    error (SODA-2 register entry S3-d), and the reason the type of these two arguments is
    respected rather than coerced.
    """
    out = FindSizeResult()

    im = _as_2d(img)
    ny, nx = im.shape  # slices, diodes -- see _as_2d

    # :11-12 -- `total()` on a BYTE array is FLOAT in IDL. `yres/xres` keeps
    # the caller's types, integer division included: that IS the behaviour.
    total_img = im.sum()
    ratio = _idl_div(yres, xres)
    area_original = np.float32(total_img) * ratio
    area_original_filled = np.float32(total_img + voidarea) * ratio

    # :13 -- the early return. Everything below is left at its declared
    # default, `centerin = 1` among them.
    if area_original == 0:
        return out

    # :21-22 / :25-26 -- `total(img,2)` sums over IDL's y (the slice axis),
    # giving one number per diode; `total(img,1)` sums over x, one per slice.
    # In this port's (slices, diodes) layout those are axis=0 and axis=1.
    per_diode = im.sum(axis=0)
    per_slice = im.sum(axis=1)

    w = np.nonzero(per_diode > 0)[0]
    out.xsize = _f(w.max() - w.min() + 1) * xres
    w = np.nonzero(per_slice > 0)[0]
    out.ysize = _f(w.max() - w.min() + 1) * yres

    # :30 -- the comment is right: min_circle_fast runs inside aspect_ratio,
    # so it must not be run again here. `tas_adjust` is FLOAT in production
    # (both operands are FLOAT probespecs fields), and aspect_ratio selects
    # IDL's type behaviour from the Python type it is handed.
    res = aspect_ratio(im, tas_adjust=np.float32(ratio))
    circle = res.circle
    x_ind, y_ind = res.x_ind, res.y_ind

    out.aspr = np.float32(res.aspr)
    # :31 -- `(circle.diam+1)*xres`: `circle.diam` is DOUBLE, `1` an INT
    # literal (promotes to DOUBLE), `xres` FLOAT -- IDL's DOUBLE*FLOAT stays
    # DOUBLE, and the *only* rounding to FLOAT happens once, at assignment
    # into the struct's declared-FLOAT `diam` field. Casting `circle.diam`
    # to float32 before the add/multiply (as this line used to) rounds
    # twice in a different order and differs from GDL by exactly one
    # float32 ULP on any particle whose true value sits near a rounding
    # boundary -- measured on `frame_h_all18` particles 4/5/6 (R7C),
    # root-caused by bisection against `min_circle_fast`, which
    # already agreed with GDL bit for bit on these exact ROIs.
    out.diam = _f((float(circle.diam) + 1.0) * float(xres))
    out.c = np.asarray(circle.center, dtype=np.float32)
    out.orientation = res.orientation
    out.perimeterarea = int(circle.area)

    # :35 -- allin is about the two END diodes only, whatever the particle
    # does in between.
    out.allin = 0 if (im[:, 0].sum() + im[:, nx - 1].sum()) != 0 else 1

    # :38-45 -- an all-NaN image, filled at the OUTLINE indices only, so the
    # extent is over the outline rather than over every shadowed pixel.
    # `max`/`min` without /NAN meet NaN here; GDL skips it (finding S2-i)
    # and `nanmax`/`nanmin` are the same rule.
    img2 = np.full((ny, nx), np.nan, dtype=np.float32)
    img2[y_ind, x_ind] = y_ind
    with np.errstate(invalid="ignore"):
        # IDL `max(img2, dim=2) - min(img2, dim=2)`: reduce over y, one
        # value per diode. That is axis=0 in this layout.
        extent = _nanspan(img2, axis=0)

    ileft, iright = 0, nx - 1
    if per_diode[ileft] > 0:
        out.edgetouch += 1
        # :52 -- `ge`, not `gt`: a tie sets centerin to 0.
        if _ge_ignoring_nan(extent[ileft], _nanmax(extent)):
            out.centerin = 0
    if per_diode[iright] > 0:
        out.edgetouch += 2
        if _ge_ignoring_nan(extent[iright], _nanmax(extent)):
            out.centerin = 0

    # :61-62 -- the SAME NaN image, refilled with the diode index, reduced
    # the other way: the largest x-span within any one slice. Korolev's `Ly`.
    img2[y_ind, x_ind] = x_ind
    with np.errstate(invalid="ignore"):
        # IDL `dim=1`: reduce over x, one value per slice -- axis=1 here.
        xspan = _nanspan(img2, axis=1)
    out.xextent = _f(_nanmax(xspan) + 1.0) * xres

    # :66-68 -- `total(img,2) < 1` is a MIN: every shadowed diode counts once,
    # however many slices it appears in. Gaps along the slice axis vanish.
    latch = np.minimum(per_diode, 1)
    out.oned = _f(latch.sum()) * xres

    # :71-72 -- no latching: the single fullest slice decides.
    out.twod = _f(per_slice.max()) * xres

    # :74-82 -- the truncated-circle correction, reached only when the
    # particle touches an end diode.
    r = out.diam / xres / _f(2.0)
    # :76 -- `x = circle.center[0]`, the raw DOUBLE from `find_radius`, NOT
    # `out.c[0]`, which is the FLOAT copy stored two lines earlier. The
    # distinction is not cosmetic: it makes the whole truncation below run in
    # double, and using the FLOAT copy instead moved `ar` by 7e-8 relative --
    # one float32 ulp, and enough to miss the golden on every edge-touching
    # case. Measured, after the port got it wrong first.
    x = np.float64(circle.center[0])
    if out.allin == 0:
        # `<1` is MIN: acos's domain is enforced by a clamp, not a check.
        # `x` is DOUBLE and `r` FLOAT, so every expression here promotes --
        # the same FLOAT/DOUBLE mixture finding S2-e reports for
        # `aspect_ratio`, in a second routine.
        # `s[1]-1-x` is LONG minus x. NumPy would make `int32 - float32`
        # into float64 -- IDL makes it FLOAT -- so it goes through
        # aspect_ratio's `_op`, the same helper that routine already needs for
        # the same reason. Writing `np.float64(nx - 1)` here instead promoted
        # the sum by itself and masked the `x` mutation: the test then passed
        # with `x` taken from the FLOAT copy, i.e. stopped guarding what it
        # was written to guard.
        right = _idl_op(np.int32(nx - 1), x, np.subtract)
        theta = np.arccos(np.minimum(x / r, _ONE_INT))
        phi = np.arccos(np.minimum(_idl_op(right, r, np.divide), _ONE_INT))
        circle_area_imaged = (
            x * r * np.sin(theta)
            + _idl_op(right, r, np.multiply) * np.sin(phi)
            + _PI * r ** 2 * ((_PI - phi - theta) / _PI)
        )
    else:
        # The all-in branch has no DOUBLE operand, so it stays FLOAT. The two
        # branches therefore return different precisions for the same
        # quantity -- preserved, and reported as part of S3-f.
        circle_area_imaged = _PI * r ** 2

    # :83-84 -- `< 1.0` is MIN again, and it absorbs a non-finite ratio into
    # exactly 1.0, the same overload S2-d reports for `aspect_ratio`.
    with np.errstate(invalid="ignore", divide="ignore"):
        # Computed at whatever precision the branch above produced, then
        # narrowed on assignment because the struct field is `0.0` (FLOAT).
        out.ar = _f(np.minimum(area_original / circle_area_imaged, _ONE_FLOAT))
        out.arfilled = _f(np.minimum(
            area_original_filled / circle_area_imaged, _ONE_FLOAT))

    # :86 -- "Can show by derivation. This also adjusts for partial images."
    out.areasize = out.diam * np.sqrt(out.ar)
    return out


def _nanspan(arr: np.ndarray, axis: int) -> np.ndarray:
    """``max(arr, dim=n) - min(arr, dim=n)`` with IDL/GDL's NaN handling.

    GDL's bare ``min``/``max`` skip NaN (finding S2-i), which is what
    ``nanmax``/``nanmin`` do. A column that is entirely NaN -- a diode with no
    outline pixel -- yields NaN here rather than raising, and NaN is then what
    the ``ge`` comparisons below see, which is the behaviour being reproduced.
    """
    # An all-NaN reduction is EXPECTED here, not exceptional: a diode with no
    # outline pixel has nothing to take a span over, and IDL/GDL return NaN
    # rather than complaining. numpy warns; the warning is suppressed rather
    # than the case avoided, because avoiding it would mean not reproducing it.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", r"All-NaN slice encountered",
                                RuntimeWarning)
        with np.errstate(invalid="ignore"):
            hi = np.nanmax(arr, axis=axis)
            lo = np.nanmin(arr, axis=axis)
    return hi - lo


def _nanmax(arr: np.ndarray) -> Any:
    """max(arr) with GDL's NaN-skipping and no warning on an all-NaN
    input, which is a reachable state rather than a mistake."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", r"All-NaN", RuntimeWarning)
        return np.nanmax(arr)


def _ge_ignoring_nan(value: Any, limit: Any) -> bool:
    """``value ge limit`` as IDL evaluates it: FALSE if either side is NaN.

    Spelled out because ``np.nan >= x`` is also False in NumPy and it would
    be easy to leave that to luck. Reproducing it deliberately means a future
    reader knows it was checked.
    """
    return bool(value >= limit)


def _all_nan_columns_are_possible() -> None:  # pragma: no cover - documentation
    """A diode with no *outline* pixel is entirely NaN in ``img2``, even
    though the diode is shadowed: for a solid block, the interior columns
    keep their outline pixels but a one-pixel-thick interior would not. The
    bank's ``hollow_ring`` reaches the case; this stub exists only so the
    reasoning is greppable from the code that depends on it."""
