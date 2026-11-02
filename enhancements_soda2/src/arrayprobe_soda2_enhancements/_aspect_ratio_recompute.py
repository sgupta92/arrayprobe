# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""Shared re-derivation of ``aspect_ratio.axis_and_ratio`` for S2-d and S2-f.

Not registered itself (leading underscore -- ``test_registry.py`` excludes it from the
on-disk/registered comparison). Both :mod:`aspr_nan_fix` and :mod:`den_clamp_fix` correct one
clamp each inside the *same* port function
(``arrayprobe_soda2.aspect_ratio.axis_and_ratio``, ``aspect_ratio.pro:27-73,105``), so this
module reproduces that function's arithmetic once, parametrized by which clamp is corrected,
rather than duplicating it twice.

**Corner/vertex resolution (`:27-51`) is reproduced verbatim from the port**, using the port's
own primitives (``_field``, ``_op``, ``_sqrt_idl``, ``orientation_deg`` -- imported, not
copied, from ``arrayprobe_soda2.aspect_ratio``, the same reuse discipline
``arrayprobe_enhancements.wide_hollow_fix`` uses for ``arrayprobe.reject``'s ``_pack``/
``_popcount``) -- both S2-d and S2-f are entirely about the arithmetic that follows corner
selection, not about which corner gets picked, so nothing here can disagree with the port about
that step. With both clamps left uncorrected (the defaults), :func:`recompute` reproduces
``axis_and_ratio`` bit for bit -- each module's own ``Equivalence`` test class checks this
directly against the real port function.

Does not touch ``arrayprobe_soda2`` -- ``aspect_ratio.py`` keeps both clamps exactly as
written (`den = sqrt(a^2+b^2) > 1` at `:66`, `return, aspr < 1.0` at `:105`), per the fidelity
doctrine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from arrayprobe_soda2.aspect_ratio import _field, _op, _sqrt_idl, orientation_deg

__all__ = ["Recomputed", "recompute"]


@dataclass(frozen=True)
class Recomputed:
    """``axis_and_ratio``'s two return values, plus the two intermediates each correction
    needs to know it actually changed something (``den`` for S2-f, ``aspr_raw`` -- the value
    before the final clamp -- for S2-d)."""

    aspr: np.float64
    orientation: np.float32
    den: Any
    aspr_raw: np.float64


def recompute(x_ind, y_ind_adjusted, circle, *,
              den_zero_guard: bool = False,
              aspr_nan_passthrough: bool = False) -> Recomputed:
    """Re-derive ``axis_and_ratio(x_ind, y_ind_adjusted, circle)`` with either or both
    clamps corrected.

    ``den_zero_guard=True``: S2-f's fix -- ``den`` is set to 1 only when it is exactly 0 (the
    single-point-outline case the clamp was written for), instead of whenever it is merely
    less than 1 (which also fires on a genuine sub-pixel-radius 3-point circle,
    ``aspect_ratio.pro:66``'s ``> 1`` reading as MAX).

    ``aspr_nan_passthrough=True``: S2-d's fix -- a non-finite ``aspr`` is returned as NaN
    instead of being clamped to the ordinary value 1.0 (``aspect_ratio.pro:105``'s ``< 1.0``
    reading as MIN, which IDL's ``<`` resolves to the *other*, finite operand on a NaN input).

    Both ``False`` (the default) is exactly ``axis_and_ratio``'s own computation.
    """
    x_ind = np.asarray(x_ind)
    y_ind = np.asarray(y_ind_adjusted)
    corners = np.asarray(_field(circle, "corners")).ravel()

    if corners.size == 3:
        from arrayprobe_soda2.angles import find_angle

        p_idx, q_idx, r_idx = (int(corners[0]), int(corners[1]), int(corners[2]))
        ty_trig = np.float32 if y_ind.dtype != np.float64 else np.float64

        def _trig_pt(idx: int) -> np.ndarray:
            return np.array([x_ind[idx], y_ind[idx]], dtype=ty_trig)

        p_pt, q_pt, r_pt = _trig_pt(p_idx), _trig_pt(q_idx), _trig_pt(r_idx)
        ang_p = find_angle(p_pt, r_pt, q_pt)
        ang_q = find_angle(q_pt, r_pt, p_pt)
        ang_r = find_angle(r_pt, q_pt, p_pt)
        vertex = int(np.argmin([ang_p, ang_q, ang_r]))
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
        if den_zero_guard:
            den = den_raw if float(den_raw) != 0.0 else den_dtype.type(1.0)
        else:
            den = den_raw if float(den_raw) > 1.0 else den_dtype.type(1.0)

        term1 = _op(a, x_ind, np.multiply)
        term2 = _op(b, y_ind, np.multiply)
        numerator = _op(_op(term1, term2, np.add), c, np.add)
        distmajor = _op(numerator, den, np.divide)

        width = _op(_op(np.max(distmajor), np.min(distmajor), np.subtract), 1, np.add)
        diam = np.float64(_field(circle, "diam"))
        aspr_raw = _op(width, diam + 1.0, np.divide)

    aspr64 = np.float64(aspr_raw)
    if aspr_nan_passthrough and not np.isfinite(aspr64):
        aspr = np.float64(np.nan)
    else:
        aspr = aspr64 if float(aspr64) < 1.0 else np.float64(1.0)

    return Recomputed(aspr=np.float64(aspr), orientation=np.float32(orientation),
                       den=den, aspr_raw=aspr64)
