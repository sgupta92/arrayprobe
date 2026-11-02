# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``aspect_ratio.pro`` -- SODA-2's rotation-invariant aspect ratio, the last
file of the geometry core.

**The real dependency list, measured (a grep of every call in the 106
lines), and a correction to this doc's own earlier call graph.** V1.4's call
graph reads ``aspect_ratio <- calls min_circle_fast + princomp``. That is
wrong: ``grep -c princomp aspect_ratio.pro`` is 0. The routine calls
``min_circle_fast`` once, :func:`arrayprobe_soda2.angles.find_angle` three
times, IDL's ``erode`` (only when the image has more than two slices), and a
handful of intrinsics (``byte``, ``size``, ``where``, ``mod``, ``/``, ``min``,
``max``, ``atan``, ``float``, ``sqrt``). ``princomp`` and ``find_angle_array``
are not called here at all -- do not substitute either for ``find_angle``.

**What it computes.** An aspect ratio in ``[0, 1]``, rotation-invariant up to
pixelisation, from the particle's minimum enclosing circle (``min_circle_fast``,
ported separately):

1. Outline pixels (:func:`outline_indices`) or given coordinates.
2. ``y_ind *= tas_adjust`` -- the true-airspeed / pixel-aspect correction,
   applied to the geometry only; the ``y_ind`` keyword hands back the
   *unadjusted* indices, which this port mirrors via
   :class:`AspectRatioResult`.
3. ``circle = min_circle_fast(x_ind, y_ind)``.
4. The major axis: for a 3-point circle, the line from the vertex of smallest
   interior angle to the circle centre (a radius); for a 2-point circle, the
   line through the two points (a diameter). See finding S2-c (the other
   pair's): ``min_circle_fast`` compares against **FLOAT** ``!pi/2``
   (:math:`1.5707963705062866`), which is *greater* than an exact right angle
   (:math:`\\mathrm{acos}(0) = 1.5707963267948966`) -- so squares, axis-aligned
   rectangles and digitised discs all take the **3-point** branch, not the
   2-point one a hand-picked case list might expect. This module does not
   choose that branch; it only reads whatever ``circle.corners`` it is given,
   so the consequence lands entirely in the golden's recorded corner counts
   (``:func:`axis_and_ratio``'s own docstring below).
5. ``orientation`` -- degrees, folded to (-90, 90] with respect to the array
   axis.
6. ``width`` = (max signed perpendicular distance from the axis) - (min) + 1
   px ("Korolev and Isaac 2003"); ``aspr = width / (circle.diam + 1)``,
   returned as ``min(aspr, 1.0)``.

**``!pi`` is IDL's single-precision pi**, :math:`3.1415927410125732`, not
:math:`3.141592653589793` -- measured under GDL (the other geometry pair's finding,
folded in here because line :53 divides by it). ``!dpi`` never appears in the
SODA-2 tree. :func:`orientation_deg` uses ``np.float32(np.pi)``, not
``np.pi``, for exactly this reason; see
``tests/test_soda2_aspect_ratio.py``'s ``PiIsSinglePrecision`` class for a
case where the double-vs-float difference is measured directly rather than
left to a tolerance that happens to be tight enough to catch it.

**Every ``<``/``>`` in the file, classified** (design record V1.3's hazard,
confirmed line by line rather than assumed):

===== ======================================= ===============================
line  text                                    class
===== ======================================= ===============================
13    ``IF s[2] gt 2``                        genuine comparison (``gt``)
24    ``n_elements(tas_adjust) gt 0``          genuine comparison
27,89 ``eq 3``, ``eq 2``                       genuine comparison
38    ``min([angP,angQ,angR], vertex)``        the ``min`` **function**
**66**   ``den=sqrt(a^2+b^2) > 1``             **MAX**: ``max(den, 1)``
**105** ``return, aspr < 1.0``                 **MIN**: ``min(aspr, 1.0)``
===== ======================================= ===============================

Line 105's comment reads "Eliminate round-off errors". Measured, it does more
than that: **a non-finite ``aspr`` also becomes exactly 1.0**, because IDL's
``<`` returns the *other* operand when one side is NaN
(``!values.d_nan < 1.0d`` prints ``1.0000000`` under GDL) -- finding S2-d, in
the design doc section this module's docstring points to. The symmetric
behaviour for ``>`` at line 66 is assumed by the same convention, not
separately measured; the code implementing it (:func:`axis_and_ratio`) says so
where it matters.

**Three same-rank IDL hazards, each with its own test:**

- ``mod`` at line 57 takes the *dividend's* sign (``-450.0 mod 180 = -90``,
  measured) -- :func:`orientation_deg` uses ``np.fmod``, never Python ``%``.
- ``where`` with no match returns the scalar ``-1``, count 0; IDL's ``-1/nx``
  truncates to 0 and ``-1 mod nx`` stays ``-1`` (dividend's sign again) --
  :func:`outline_indices` returns exactly ``([-1], [0], 0)`` for an empty
  image rather than empty arrays.
- ``orientation`` is computed in **single precision throughout** (``float()``
  at line 53, ``!pi`` itself is FLOAT); the 2-point branch's ``distmajor`` is
  FLOAT whatever the input dtype (``sqrt(LONG)`` promotes to FLOAT, so does
  ``LONG/FLOAT``), but the 3-point branch's is DOUBLE, because
  ``circle.center`` is double. NumPy's own promotion rule for
  ``int32 * float32`` is **float64**, which is *not* IDL's ``LONG*FLOAT ->
  FLOAT`` -- :func:`axis_and_ratio` routes every such mixed operation through
  :func:`_idl_promote` instead of raw NumPy operators, specifically to avoid
  that silent widening.

**The oracle gap: GDL has no ``ERODE``.** ``erode`` runs only when the image
has more than two slices along airflow (``s[2] gt 2``), so GDL runs
``aspect_ratio.pro`` **unmodified** for coordinate input and for images with
at most two slices -- doctrine layer 2, no shim needed. For images with more
than two slices, the GDL oracle bank supplies its own ``erode.pro`` (a plain
4-connected cross erosion), and that reading of IDL's edge behaviour at the
image border is **not confirmed** -- the IDL/NV5 ERODE reference pages did not
resolve when checked (see the design doc section). ``ERODE_EDGE_RULE`` is the
one switch this module exposes for the two candidate readings:

- ``"zero_outside"`` -- a pixel outside the image counts as 0, so every pixel
  touching the image border is eroded away (a tight, border-touching ROI has
  its whole boundary in the outline).
- ``"clip_element"`` -- a missing neighbour is simply not required to be 1
  (as if the structuring element were clipped to the image), so a border
  pixel can survive erosion.

Both are implemented and tested; the module default is ``"zero_outside"``,
labelled unconfirmed everywhere it is exercised. A pixel more than one row
away from every border sees the same answer under both rules, which is why
the padded family in the test suite is rule-*independent* evidence and the
unpadded one is not.

Provenance: ``SODA2/abansemer-soda2-afcea15/aspect_ratio.pro``, whole file
minus the ``makeplot`` block (lines 76-102), which is plotting only and has
no numeric effect. Validated against GDL by
``tests/test_soda2_aspect_ratio.py``; the composition test
(:func:`aspect_ratio` end to end) needs ``arrayprobe_soda2.min_circle_fast``
(the concurrent S2-c pair's module) and skips at method level via
:class:`MinCircleFastNotPorted` if it is ever absent.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from arrayprobe_soda2.angles import find_angle, find_angle_f32

__all__ = [
    "ERODE_EDGE_RULE",
    "AspectRatioResult",
    "MinCircleFastNotPorted",
    "aspect_ratio",
    "axis_and_ratio",
    "orientation_deg",
    "outline_indices",
]

#: Which reading of IDL's (GDL-absent) ERODE border behaviour this module
#: uses by default. See the module docstring's "oracle gap" section -- this
#: is a declared, tested switch, not a confirmed fact. Read at call time
#: (functions default their keyword to ``None`` and resolve it here), so a
#: test can monkeypatch this module attribute and have it take effect.
ERODE_EDGE_RULE = "zero_outside"


class MinCircleFastNotPorted(ImportError):
    """``arrayprobe_soda2.min_circle_fast`` has not landed yet (a concurrent
    pair owns that port). Raised lazily, at call time, so importing this
    module never requires it -- only calling :func:`aspect_ratio` does."""


@dataclass(frozen=True)
class AspectRatioResult:
    """Everything ``aspect_ratio.pro`` returns, keyword outputs included.

    ``circle`` is whatever :func:`arrayprobe_soda2.min_circle_fast.min_circle_fast`
    returns -- an object or mapping with ``diam``, ``center`` (2-element) and
    ``corners`` (2 or 3 zero-based indices into ``x_ind``/``y_ind``).
    ``y_ind`` is the **unadjusted** indices, exactly as IDL's ``y_ind_orig``
    keyword output is (:74 in the source): the TAS correction is applied to a
    local copy only, and the keyword hands back the copy made before that.
    """

    aspr: np.float64
    orientation: np.float32
    circle: Any
    x_ind: np.ndarray
    y_ind: np.ndarray


def _field(circle: Any, name: str) -> Any:
    """Read ``name`` off ``circle``, which may be an attribute-bearing object
    (a dataclass, a ``SimpleNamespace``, the eventual ``min_circle_fast``
    return type) or a mapping (the golden's own records, read back as
    dicts). Both must work so the differential tests can build a fake circle
    straight from the GDL golden without needing the other pair's module."""
    if isinstance(circle, Mapping):
        return circle[name]
    return getattr(circle, name)


def _to_byte(img_in: np.ndarray) -> np.ndarray:
    """IDL ``byte(img_in)``: truncate (not round) toward zero for floating
    input, then wrap into ``[0, 255]``. Every case this port is fed is already
    strictly 0/1, so this only matters as documented behaviour, not as a
    tested path."""
    arr = np.asarray(img_in)
    if arr.dtype.kind == "f":
        arr = np.trunc(arr)
    return np.mod(arr.astype(np.int64), 256).astype(np.uint8)


def _erode_cross(img01: np.ndarray, edge_rule: str) -> np.ndarray:
    """4-connected (cross) binary erosion -- GDL 1.1.2 has no ``ERODE``
    (measured: ``Attempt to call undefined function: ERODE``), so this is the
    port's own implementation, not a translation of one. ``edge_rule`` picks
    between the two candidate readings of IDL's real border behaviour, which
    is unconfirmed (module docstring). A pixel is retained iff it and all
    four of its cross neighbours are 1; a neighbour that falls outside the
    image is treated as 0 under ``"zero_outside"`` and simply not required
    under ``"clip_element"``.
    """
    fg = img01 != 0
    up = np.zeros_like(fg)
    up[1:, :] = fg[:-1, :]
    down = np.zeros_like(fg)
    down[:-1, :] = fg[1:, :]
    left = np.zeros_like(fg)
    left[:, 1:] = fg[:, :-1]
    right = np.zeros_like(fg)
    right[:, :-1] = fg[:, 1:]

    if edge_rule == "zero_outside":
        eroded = fg & up & down & left & right
    elif edge_rule == "clip_element":
        border_up = np.zeros_like(fg)
        border_up[0, :] = True
        border_down = np.zeros_like(fg)
        border_down[-1, :] = True
        border_left = np.zeros_like(fg)
        border_left[:, 0] = True
        border_right = np.zeros_like(fg)
        border_right[:, -1] = True
        eroded = (
            fg
            & (up | border_up)
            & (down | border_down)
            & (left | border_left)
            & (right | border_right)
        )
    else:
        raise ValueError(f"unknown edge_rule {edge_rule!r}; expected "
                          "'zero_outside' or 'clip_element'")
    return eroded.astype(np.uint8)


def outline_indices(
    img: np.ndarray, *, edge_rule: str | None = None
) -> tuple[np.ndarray, np.ndarray, int]:
    """``aspect_ratio.pro`` lines 11-17: outline pixel indices of an image.

    ``img`` is ``(n_slices, n_diodes)`` -- y (along airflow) first, x (across
    the array) second, matching how this port holds every other SODA-2/UIOOPS
    image. IDL's array is column-major with x as dimension 1, so its flat
    ``where`` index order (x fastest) is exactly this array's C-order
    ``ravel()`` -- **this equivalence is load-bearing** for
    ``min_circle_fast``'s tie-breaking on the returned index order, so it is
    asserted directly by ``OutlineAndIndexOrderMatchIdl`` rather than only
    implied by matching final answers.

    A 1-D ``img`` is treated as a single slice (no erosion), which is also
    what IDL does here, but not for the reason it looks like: after
    ``img = byte(img_in)``, IDL's ``size(img)`` for a 1-D array is
    ``[1, n, type, n_elements]``, so ``s[2]`` is the **type code** (1, for
    BYTE), never the y-dimension, and 1 is never greater than 2. The outline
    step is skipped by coincidence, not by an explicit 1-D branch -- SODA-2
    register entry S2-g. It is harmless in production because ``soda2_findsize.pro`` reforms
    1-D images before calling this routine.

    Returns ``(x_ind, y_ind, area)``, both ``int32``. An image with nothing
    shadowed returns exactly ``([-1], [0], 0)`` -- IDL's ``where`` returns the
    scalar ``-1`` with count 0 on no match, and ``-1 mod nx`` keeps the
    dividend's sign (stays ``-1``) while IDL's ``/`` truncates toward zero
    (``-1/nx`` is 0 for any ``nx > 1``), not the floor NumPy's ``//`` would
    give.
    """
    if edge_rule is None:
        edge_rule = ERODE_EDGE_RULE

    byte_img = _to_byte(img)
    if byte_img.ndim <= 1:
        # 1-D input: single slice, erosion never applies (see docstring).
        row = byte_img.reshape(1, -1) if byte_img.ndim == 1 else byte_img.reshape(1, 1)
        im = row
        nx = im.shape[1]
    else:
        ny, nx = byte_img.shape
        if ny > 2:
            im = _erode_cross(byte_img, edge_rule) ^ byte_img
        else:
            im = byte_img

    z = np.flatnonzero(im.ravel(order="C") == 1)
    if z.size == 0:
        return np.array([-1], dtype=np.int32), np.array([0], dtype=np.int32), 0
    x_ind = (z % nx).astype(np.int32)
    y_ind = (z // nx).astype(np.int32)
    return x_ind, y_ind, int(z.size)


def orientation_deg(cx1: Any, cy1: Any, cx2: Any, cy2: Any) -> np.float32:
    """``aspect_ratio.pro`` lines 53 and 57: orientation in degrees.

    ``atan(float(cy2-cy1), float(cx2-cx1)) * 180/!pi``, then folded to
    ``(-90, 90]`` by ``((orientation - 360 - 90) mod 180) + 90``.

    Each difference is computed at its *native* precision first (whatever
    dtype the caller's ``cx1``/``cy1``/``cx2``/``cy2`` actually carry -- the
    only mixing that ever occurs here is with ``float64``
    (:func:`axis_and_ratio`'s 3-point branch, via ``circle.center``), which
    NumPy promotes to unambiguously, exactly as IDL would) and *then*
    narrowed to ``float32`` with an explicit cast -- mirroring IDL's
    ``float(cy2-cy1)``, which narrows after subtracting, not before. ``!pi``
    is IDL's **single-precision** pi (measured under GDL:
    ``3.1415927410125732``, not ``3.141592653589793``); ``!dpi`` is never used
    in this tree. ``np.fmod``, not Python's ``%``, for the ``mod`` at line 57
    -- IDL's ``mod`` takes the dividend's sign, and ``np.fmod`` does too.
    """
    dy = np.float32(np.asarray(cy2) - np.asarray(cy1))
    dx = np.float32(np.asarray(cx2) - np.asarray(cx1))
    pi32 = np.float32(np.pi)  # IDL's `!pi` is FLOAT, not DOUBLE -- measured.

    # ``atan`` on FLOAT: the double atan2 rounded to FLOAT (platform ``atan2f``
    # differs by one ULP under glibc, which the fmod chain below amplifies).
    orientation = np.float32(np.arctan2(np.float64(dy), np.float64(dx))) * np.float32(180)
    orientation = orientation / pi32
    orientation = (
        np.fmod(orientation - np.float32(360) - np.float32(90), np.float32(180))
        + np.float32(90)
    )
    return np.float32(orientation)


def _idl_promote(dtype_a: Any, dtype_b: Any) -> type:
    """The result dtype of an IDL binary numeric op between LONG/FLOAT/DOUBLE
    operands (the only three that occur in this routine): DOUBLE beats FLOAT
    beats LONG. NumPy's own promotion of ``int32`` with ``float32`` is
    ``float64`` -- not IDL's ``LONG*FLOAT -> FLOAT`` -- so callers must route
    through this and :func:`_op` rather than the bare NumPy operators.
    """
    def rank(dt: Any) -> int:
        dt = np.dtype(dt)
        if dt.kind in "iu":
            return 0
        if dt == np.dtype(np.float32):
            return 1
        if dt == np.dtype(np.float64):
            return 2
        raise TypeError(f"unexpected dtype in aspect_ratio arithmetic: {dt}")

    order = max(rank(dtype_a), rank(dtype_b))
    return (np.int32, np.float32, np.float64)[order]


def _op(x: Any, y: Any, fn: Any) -> np.ndarray:
    """Apply a binary NumPy ufunc under IDL's promotion rule (see
    :func:`_idl_promote`) instead of NumPy's own: both operands are cast to
    the IDL result dtype *before* the ufunc runs, so the actual NumPy
    operation that executes is same-dtype and unambiguous.
    """
    xa = np.asarray(x)
    ya = np.asarray(y)
    dt = _idl_promote(xa.dtype, ya.dtype)
    return fn(xa.astype(dt), ya.astype(dt))


def _sqrt_idl(x: Any) -> np.ndarray:
    """IDL ``sqrt``: LONG always promotes to FLOAT (never stays integer);
    FLOAT stays FLOAT, DOUBLE stays DOUBLE."""
    xa = np.asarray(x)
    out_dtype = np.float32 if xa.dtype.kind in "iu" else xa.dtype
    return np.sqrt(xa.astype(out_dtype)).astype(out_dtype)


def axis_and_ratio(
    x_ind: np.ndarray, y_ind_adjusted: np.ndarray, circle: Any
) -> tuple[np.float64, np.float32]:
    """``aspect_ratio.pro`` lines 27-73 and 105, given an already-computed
    ``circle``. Returns ``(aspr, orientation)``.

    ``circle`` needs ``corners`` (2 or 3 zero-based indices into ``x_ind`` /
    ``y_ind_adjusted``), ``center`` (2-element, DOUBLE in the source) and
    ``diam`` (DOUBLE); see :func:`_field` for the attribute-or-mapping
    accessor that lets this take either a real ``min_circle_fast`` result or
    a ``SimpleNamespace``/``dict`` built straight from the GDL golden.

    **Dtype.** ``y_ind_adjusted``'s own dtype is IDL's "Ty": ``int32`` if no
    TAS correction was applied, ``float32`` in production
    (``tas_adjust`` is a FLOAT keyword), ``float64`` only if a caller passes a
    genuine DOUBLE. In the 2-point branch, ``a`` (``cy1-cy2``) and the running
    sums stay in Ty; ``b`` (``cx2-cx1``) is always ``int32`` (``x_ind`` is
    always LONG) but gets promoted to Ty the moment it multiplies against a
    Ty operand, via :func:`_op`/:func:`_idl_promote` rather than NumPy's own
    (wider) promotion. In the 3-point branch ``cx2``/``cy2`` come from
    ``circle.center``, which is DOUBLE, so **everything** downstream --
    ``a``, ``b``, ``c``, ``den``, ``distmajor`` -- ends up ``float64``
    regardless of Ty; this falls out of :func:`_idl_promote` automatically
    once ``cx2``/``cy2`` are cast to ``float64`` up front, with no separate
    branch needed. ``aspr`` is always returned as ``float64`` (``circle.diam``
    is DOUBLE, so ``width / (diam + 1)`` is DOUBLE regardless of ``width``'s
    own dtype).

    **The two clamps.** ``den = sqrt(a^2+b^2) > 1`` (MAX) and the final
    ``return, aspr < 1.0`` (MIN) are both written as a Python ternary
    (``x if x > floor else floor`` / ``x if x < ceiling else ceiling``) rather
    than ``max``/``min``, because Python's comparison operators already give
    ``False`` for a NaN operand, which is exactly IDL's own measured
    behaviour for ``<`` (SODA-2 register entry S2-d: ``!values.d_nan < 1.0d`` is ``1.0`` under
    GDL) -- so the *ternary form* reproduces the NaN case for free, where
    calling ``min()``/``max()`` would not reliably. The ``>`` side is written
    the same way for consistency; only the ``<`` case has actually been
    measured against real IDL/GDL.
    """
    x_ind = np.asarray(x_ind)
    y_ind = np.asarray(y_ind_adjusted)
    corners = np.asarray(_field(circle, "corners")).ravel()

    if corners.size == 3:
        p_idx, q_idx, r_idx = (int(corners[0]), int(corners[1]), int(corners[2]))
        # Measured (the min_circle_fast pair, folded in here 2026-09-12):
        # `[x_ind[P], y_ind[P]]` is an IDL array LITERAL combining a LONG
        # (`x_ind`) with Ty (`y_ind`), so it takes IDL's own array-promotion
        # type -- FLOAT whenever Ty is int32 or float32 (`total()`/`acos`
        # inside find_angle.pro cannot stay LONG, the same "sqrt/trig always
        # promotes" rule as :func:`_sqrt_idl`), DOUBLE only when Ty is
        # float64. Measured: `find_angle([0L,0.0],[1L,0.0],[1L,1e-3])` is
        # FLOAT `9.765625e-04`, against `9.99999667e-04` in double -- a 2.3%
        # difference, and :38's `min(..., vertex)` can pick a **different
        # corner** on a near-tie at that resolution. `find_angle` itself is
        # owned by the concurrent min_circle_fast pair and is not edited
        # here; this only controls what precision *this* call site feeds it
        # with, so the effect is inert until their centralised dtype fix
        # lands -- until then `find_angle` still widens everything to
        # float64 internally, exactly as before.
        ty_trig = np.float32 if y_ind.dtype != np.float64 else np.float64

        def _trig_pt(idx: int) -> np.ndarray:
            return np.array([x_ind[idx], y_ind[idx]], dtype=ty_trig)

        p_pt, q_pt, r_pt = _trig_pt(p_idx), _trig_pt(q_idx), _trig_pt(r_idx)
        # FLOAT find_angle on this path (measured under GDL).
        fa = find_angle_f32 if ty_trig is np.float32 else find_angle
        ang_p = fa(p_pt, r_pt, q_pt)
        ang_q = fa(q_pt, r_pt, p_pt)
        ang_r = fa(r_pt, q_pt, p_pt)
        vertex = int(np.argmin([ang_p, ang_q, ang_r]))  # first index on ties,
        # matching IDL's `min(array, subscript)` convention.
        corner_idx = int(corners[vertex])
        cx1, cy1 = x_ind[corner_idx], y_ind[corner_idx]
        center = np.asarray(_field(circle, "center"), dtype=np.float64).ravel()
        cx2, cy2 = np.float64(center[0]), np.float64(center[1])
    else:
        i0, i1 = int(corners[0]), int(corners[1])
        cx1, cy1 = x_ind[i0], y_ind[i0]
        cx2, cy2 = x_ind[i1], y_ind[i1]

    orientation = orientation_deg(cx1, cy1, cx2, cy2)

    with np.errstate(invalid="ignore", divide="ignore"):
        a = _op(cy1, cy2, np.subtract)
        b = _op(cx2, cx1, np.subtract)
        c = _op(_op(cx1, cy2, np.multiply), _op(cx2, cy1, np.multiply), np.subtract)

        den_raw = _sqrt_idl(_op(_op(a, a, np.multiply), _op(b, b, np.multiply), np.add))
        den_dtype = den_raw.dtype
        den = den_raw if float(den_raw) > 1.0 else den_dtype.type(1.0)

        term1 = _op(a, x_ind, np.multiply)
        term2 = _op(b, y_ind, np.multiply)
        numerator = _op(_op(term1, term2, np.add), c, np.add)
        distmajor = _op(numerator, den, np.divide)

        width = _op(_op(np.max(distmajor), np.min(distmajor), np.subtract), 1, np.add)
        diam = np.float64(_field(circle, "diam"))
        aspr_raw = _op(width, diam + 1.0, np.divide)

    aspr64 = np.float64(aspr_raw)
    aspr = aspr64 if float(aspr64) < 1.0 else np.float64(1.0)
    return np.float64(aspr), np.float32(orientation)


def aspect_ratio(
    img_or_coords: np.ndarray,
    *,
    tas_adjust: Any = None,
    coordinates: bool = False,
    edge_rule: str | None = None,
) -> AspectRatioResult:
    """``aspect_ratio.pro``, whole routine (minus the ``makeplot`` block).

    ``coordinates=True``: ``img_or_coords`` is an ``(n, 2)`` array of
    ``[x, y]`` integer coordinates (lines 19-21) rather than an image.

    ``tas_adjust`` selects IDL's own type behaviour by the *type of the
    Python value passed*, mirroring what a caller in IDL would have to do
    with a literal: ``None`` means the keyword was never supplied (line 24's
    ``n_elements(tas_adjust) gt 0`` is false), so ``y_ind`` stays whatever
    integer/float type it already was; ``np.float32`` gives FLOAT, which is
    what the real production caller passes
    (``soda2_findsize.pro:30``, ``tas_adjust=yres/xres`` where both are FLOAT
    fields); any other floating value -- a bare Python ``float`` or
    ``np.float64`` -- is treated as DOUBLE, exactly as IDL would treat a
    ``0.5d`` literal. **A bare Python float is therefore not "whatever is
    convenient" here: it silently selects DOUBLE**, so a caller wanting to
    reproduce the production path must pass ``np.float32(yres / xres)``
    explicitly, not a plain float that happens to equal it.

    The enclosing circle comes from ``arrayprobe_soda2.min_circle_fast``
    (ported; checked against GDL by a test that is not part of this package), imported lazily. The
    ``except ImportError`` branch that raises :class:`MinCircleFastNotPorted`
    is unreachable in a complete install and is kept so an old import of the
    exception does not break.
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

    # min_circle_fast is ported (min_circle_fast.py); the except branch is
    # dead in a complete install and kept only for the exception's importers.
    try:
        from arrayprobe_soda2.min_circle_fast import min_circle_fast
    except ImportError as exc:
        raise MinCircleFastNotPorted(
            "arrayprobe_soda2.min_circle_fast is not ported yet; "
            "aspect_ratio() needs it to compute the enclosing circle. "
            "axis_and_ratio() works without it, given a circle from "
            "elsewhere (e.g. the GDL golden)."
        ) from exc

    circle = min_circle_fast(x_ind, y_ind_adj)
    aspr, orientation = axis_and_ratio(x_ind, y_ind_adj, circle)
    return AspectRatioResult(
        aspr=aspr, orientation=orientation, circle=circle,
        x_ind=x_ind, y_ind=y_ind_orig,
    )
