# SPDX-License-Identifier: BSD-3-Clause
"""Shared leaf: the Holroyd shape statistics both engines use.

Moved verbatim from ``arrayprobe.habit``;
that module re-imports them, so its names still resolve.  Pure functions and a
frozen dataclass: no module state, no numba.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .particle import shadow_mask

__all__: list[str] = []


#: ``holroyd.m:108``.  A sentinel ceiling, used as ``*3`` for the running
#: minimum of the slice index.  S2 measured particles as long as ``nS = 7829``
#: slices in the ORACLES raw files, so 18000 still clears real data -- but the
#: margin is a factor of two, not the factor of a thousand the number suggests.
MAX_TWOD_DATA_LENGTH = 6000


@dataclass(frozen=True)
class ShapeStats:
    """The nine outputs of ``calc_stat`` (``holroyd.m:105``).

    Field order follows the MATLAB return list so the two can be read side by
    side.  Only ``x_length``, ``y_length``, ``d_length``, ``a_angle``, ``area``,
    ``r2_correlation``, ``F_fine_detail`` and ``S_ratio`` reach the decision
    tree; ``w_width`` is computed, returned, and never used by anything -- which
    is why the ``dmax_y`` defect below has no effect on any UIOOPS output.
    """

    x_length: float
    y_length: float
    d_length: float
    w_width: float
    a_angle: float
    area: float
    r2_correlation: float
    F_fine_detail: float
    S_ratio: float


def calc_stat(image_buffer, bits_per_slice) -> ShapeStats:
    """``holroyd.m:105-278``, vectorized.  Equal to :func:`calc_stat_scalar`.

    The two scans in the MATLAB are transitions along the row-major and
    column-major flattenings of the image with the state carried across
    boundaries (see :func:`calc_stat_scalar`), so each is exactly the number of
    changes in the flattened sequence prefixed by a lit diode -- one
    ``np.diff`` apiece.  Everything else is a sum or an extreme over the
    shadowed pixels, and the rotation is a two-line matrix product.

    The sentinel initialisers are applied *after* the vectorized reduction
    rather than seeded into it, which reproduces them exactly: a reduction over
    an empty set is undefined in NumPy, but MATLAB's answer in that case is
    simply the sentinel.
    """
    shadow = shadow_mask(image_buffer)
    n_slices = shadow.shape[0]
    if n_slices <= 0:
        raise ValueError("calc_stat requires at least one slice")

    # MATLAB scans exactly `bits_per_slice` columns whatever the array holds.
    # Reproduce the framing rather than trusting the caller's width: a narrower
    # image would index out of range in MATLAB, a wider one would be truncated.
    if shadow.shape[1] < bits_per_slice:
        raise IndexError(
            f"image has {shadow.shape[1]} diodes, fewer than bits_per_slice={bits_per_slice}"
        )
    shadow = shadow[:, :bits_per_slice]

    rows, cols = np.nonzero(shadow)
    n_count = int(rows.size)
    tx = rows.astype(np.float64) + 1.0
    ty = cols.astype(np.float64) + 1.0
    area = float(n_count)

    per_row = shadow.sum(axis=1)
    fully_on_count = int(np.count_nonzero(per_row == bits_per_slice))
    partial_on_count = int(np.count_nonzero(per_row != 0))

    # holroyd.m:128,170-178 and :193-207.  A transition is any change in the
    # flattened sequence; prefixing a lit diode supplies the `spot_on_off = 0`
    # initial state, and not appending one reproduces the missing close.
    row_major = shadow.ravel(order="C")
    col_major = shadow.ravel(order="F")
    p_perimeter_change = int(
        np.count_nonzero(np.diff(np.concatenate(([False], row_major))))
        + np.count_nonzero(np.diff(np.concatenate(([False], col_major))))
    )

    if n_count:
        max_x, min_x = int(tx.max()), min(MAX_TWOD_DATA_LENGTH * 3, int(tx.min()))
        max_y, min_y = int(ty.max()), min(bits_per_slice, int(ty.min()))
    else:
        max_x, min_x = 0, MAX_TWOD_DATA_LENGTH * 3
        max_y, min_y = 0, bits_per_slice

    x_length = float(max_x - min_x + 1) if max_x >= min_x else 0.0
    y_length = float(max_y - min_y + 1) if max_y >= min_y else 0.0

    return _finish(
        n_count=n_count,
        px=tx,
        py=ty,
        area=area,
        sum_x=float(tx.sum()),
        sum_y=float(ty.sum()),
        sum_x2=float((tx * tx).sum()),
        sum_y2=float((ty * ty).sum()),
        sum_xy=float((tx * ty).sum()),
        x_length=x_length,
        y_length=y_length,
        p_perimeter_change=p_perimeter_change,
        fully_on_count=fully_on_count,
        partial_on_count=partial_on_count,
        bits_per_slice=bits_per_slice,
    )


def _finish(
    *,
    n_count,
    px,
    py,
    area,
    sum_x,
    sum_y,
    sum_x2,
    sum_y2,
    sum_xy,
    x_length,
    y_length,
    p_perimeter_change,
    fully_on_count,
    partial_on_count,
    bits_per_slice,
) -> ShapeStats:
    """``holroyd.m:222-277`` -- the part after both scans, shared by both paths.

    Split out because it is identical in the scalar and vectorized versions and
    is where every NaN-producing division lives; keeping one copy means the two
    paths cannot drift on the delicate arithmetic.

    All arithmetic here runs on ``np.float64`` rather than Python ``float``, for
    one reason: MATLAB divides by zero the way IEEE-754 says to -- ``0/0`` is
    NaN, ``c/0`` is a signed infinity -- and Python raises ``ZeroDivisionError``
    instead.  Both cases are *reachable and load-bearing* here (an empty image
    takes the first, a single-slice particle very nearly takes the second), so
    the arithmetic has to be done in a type that produces MATLAB's answer
    instead of being guarded into a different one.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        area = np.float64(area)
        sum_x, sum_y = np.float64(sum_x), np.float64(sum_y)
        sum_x2, sum_y2, sum_xy = np.float64(sum_x2), np.float64(sum_y2), np.float64(sum_xy)

        # holroyd.m:222-224.  With no shadowed pixel every term is zero, so
        # these are 0 - 0/0 = NaN.  MATLAB carries the NaN forward; the caller's
        # `area == 0` test at :45 catches the particle before it matters.
        cross_xy = sum_xy - (sum_x * sum_y / area)
        cross_x2 = sum_x2 - (sum_x * sum_x / area)
        cross_y2 = sum_y2 - (sum_y * sum_y / area)

        # holroyd.m:226.  A particle confined to a single slice has zero
        # variance in x, so this is 0/0 -> NaN, and every comparison downstream
        # is false.  That is not a degenerate curiosity: it steers single-slice
        # particles into the *linear* branch at :51 by way of a NaN d_length.
        slope = cross_xy / cross_x2

        angle_radian = np.arctan(slope)
        a_angle = angle_radian * (180.0 / math.pi)

        # holroyd.m:232-235.  NaN < 0 is false, so a degenerate particle keeps
        # its NaN angle and every downstream comparison fails closed.
        if a_angle < 0:
            a_angle = a_angle + 180.0
            angle_radian = angle_radian + math.pi

        # holroyd.m:244-249.  Folds (pi/2, pi] back into [0, pi/2).  The `> pi`
        # arm prints a diagnostic and returns with the outputs unassigned, which
        # in MATLAB is an error; it is unreachable because atan(x) + pi <= pi
        # only when atan(x) <= 0, and that branch has already been taken.
        if (angle_radian > (math.pi / 2.0)) and (angle_radian <= math.pi):
            angle_radian = math.pi - angle_radian
        elif angle_radian > math.pi:  # pragma: no cover - unreachable, see above
            raise ValueError(f"HEY: something is wrong here  a_angle = {a_angle}")

        dmin_x = float(MAX_TWOD_DATA_LENGTH * 3)
        dmin_y = float(bits_per_slice)
        dmax_x = 0.0
        dmax_y = 0.0

        if n_count:
            cos_a, sin_a = np.cos(angle_radian), np.sin(angle_radian)
            new_x = px * cos_a + py * sin_a
            new_y = py * cos_a - px * sin_a
            # holroyd.m:253-264 compares against the sentinels, so a rotated
            # coordinate that never beats one leaves it in place.  Two
            # consequences, both preserved:
            #
            #   * `dmax_y = 0` is wrong for a quantity that is routinely
            #     negative -- `y*cos - x*sin` is below zero for every point of a
            #     steeply inclined particle -- so `w_width` is inflated there.
            #   * `if (new_x > dmax_x)` is FALSE for NaN, so a NaN slope (a
            #     single-slice particle) leaves all four sentinels standing and
            #     `d_length` comes out as 1 - 18000 = -17999.
            #
            # `keep` reproduces the second: it is the subset of points MATLAB's
            # comparisons can actually act on.  The rotation makes every
            # coordinate NaN at once or none of them, so it is all-or-nothing.
            keep = ~np.isnan(new_x)
            if keep.any():
                dmax_x = max(dmax_x, float(new_x[keep].max()))
                dmin_x = min(dmin_x, float(new_x[keep].min()))
            keep_y = ~np.isnan(new_y)
            if keep_y.any():
                dmax_y = max(dmax_y, float(new_y[keep_y].max()))
                dmin_y = min(dmin_y, float(new_y[keep_y].min()))

        d_length = np.float64(dmax_x - dmin_x) + 1
        w_width = np.float64(dmax_y - dmin_y) + 1

        # holroyd.m:270.  cross_x2 and cross_y2 are variances and so cannot be
        # negative in exact arithmetic; the product is zero for a single-slice
        # or single-diode particle, and 0/0 is again NaN.
        r2_correlation = cross_xy / np.sqrt(cross_x2 * cross_y2)
        f_fine_detail = np.float64(p_perimeter_change) * d_length / area
        s_ratio = fully_on_count / partial_on_count if partial_on_count != 0 else 0.0

    return ShapeStats(
        x_length=x_length,
        y_length=y_length,
        d_length=float(d_length),
        w_width=float(w_width),
        a_angle=float(a_angle),
        area=float(area),
        r2_correlation=float(r2_correlation),
        F_fine_detail=float(f_fine_detail),
        S_ratio=float(s_ratio),
    )
