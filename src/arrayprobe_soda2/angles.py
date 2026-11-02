# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``find_angle.pro`` and ``find_angle_array.pro`` -- SODA-2's two angle routines.

Both return the angle at vertex ``p1``. They are the leaves of the
geometry chain: ``min_circle_fast`` calls both, on every iteration of its search.

**They use different formulas, and that is not cosmetic.**

===================  ==========================================================
``find_angle``       ``acos( B.C / sqrt(|B|^2 |C|^2) )``            dot product
``find_angle_array`` ``acos( (b2+c2-a2) / (2 sqrt(b2 c2)) )``    law of cosines
===================  ==========================================================

Algebraically the same; numerically not. Measured over 200,000 random triangles
they disagree in **56 % of cases**, by up to **8.3e-10 rad** — and the GDL golden
carries a triangle where the real IDL shows it (``3.14159185086`` against
``3.14159185003``).

**This matters because `min_circle_fast` mixes them.** It takes ``angR`` from
``find_angle_array`` and ``angQ`` from ``find_angle``, then computes the third
angle as ``angP = !pi - angR - angQ`` — never directly. So the two formulas'
disagreement lands in ``angP``, which is then compared against ``!pi/2`` to
decide whether to keep iterating. On a near-right vertex that comparison can go
either way, and the port must inherit the same arithmetic to inherit the same
decision. Reproducing this pair with one shared helper would be a "tidy-up" that
silently changes which circle SODA-2 returns.

**Two degeneracies, both reproduced rather than guarded.**

* Coincident points make the denominator zero, so the argument is ``0/0`` and
  ``acos`` yields NaN. Measured under GDL for ``p2 == p1``, ``p3 == p1``, and all
  three equal.
* **A thin angle is lost entirely.** For ``p1=(0,0)``, ``p2=(1,0)``,
  ``p3=(1,1e-9)`` the true angle is about ``1e-9`` rad, and both routines return
  **exactly 0** — the cosine rounds to 1.0 and ``acos(1.0)`` is 0. This is
  inherent to an ``acos`` formulation: it cannot resolve angles below roughly
  ``1.5e-8`` rad. It is not a defect introduced by either formula, and it is
  reproduced because SODA-2's answers depend on it.

**`find_angle_array` halts on a non-double input.**
``IF typename(x1) ne 'DOUBLE' THEN stop, 'find_angle_array.pro needs double
floating point values.'`` — ``stop`` drops IDL to its prompt, which ends a batch
run. Reproduced as a raise, for the same reason ``princomp``'s length check is:
the original produces no value on that path.

Provenance: ``SODA2/abansemer-soda2-afcea15/find_angle.pro`` (8 lines) and
``find_angle_array.pro`` (24 lines), both whole-file. Validated against GDL by
``tests/test_soda2_angles.py``.
"""
from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["NotDoublePrecision", "find_angle", "find_angle_array"]


class NotDoublePrecision(RuntimeError):
    """``find_angle_array.pro``'s own type guard reached. It ``stop``s rather
    than returning, so there is no value for the port to produce."""


def find_angle(p1: ArrayLike, p2: ArrayLike, p3: ArrayLike) -> float:
    """``find_angle(p1, p2, p3)`` -- the angle at ``p1``, by the dot product.

    Source: ``find_angle.pro`` (SODA-2).

    ``p1``/``p2``/``p3`` are 2-element ``[x, y]``. NaN for coincident points;
    exactly 0 for an angle too thin for ``acos`` to resolve. See the module
    docstring — do not substitute :func:`find_angle_array` here.
    """
    a = np.asarray(p1, dtype=np.float64).ravel()
    b = np.asarray(p2, dtype=np.float64).ravel() - a
    c = np.asarray(p3, dtype=np.float64).ravel() - a
    with np.errstate(invalid="ignore", divide="ignore"):
        arg = (b * c).sum() / np.sqrt((b ** 2).sum() * (c ** 2).sum())
        return float(np.arccos(arg))


def find_angle_f32(p1: ArrayLike, p2: ArrayLike, p3: ArrayLike) -> np.float32:
    """``find_angle.pro`` evaluated in IDL FLOAT, as ``aspect_ratio.pro:35-37``
    calls it: the points are ``[x_ind, y_ind*tas_adjust]`` literals (LONG with
    FLOAT promotes to FLOAT), so every intermediate -- the differences, the
    two-element ``total``s, the ``sqrt`` -- is float32 and ``acos`` is the
    correctly rounded FLOAT kernel (computed in float64, rounded once).
    Measured under GDL (a GDL probe script, 2026-10-04): on
    x=[109,101,105], y=[10,99,54] this gives angP = angQ = 0.0009765625 and
    angR = 3.139579534531, where :func:`find_angle` (float64) gives a strict
    minimum at Q. ``min_circle_fast`` keeps :func:`find_angle` (DOUBLE)."""
    from arrayprobe_soda2.process_hk import f32_via_f64

    a = np.asarray(p1, dtype=np.float32).ravel()
    b = np.asarray(p2, dtype=np.float32).ravel() - a
    c = np.asarray(p3, dtype=np.float32).ravel() - a
    with np.errstate(invalid="ignore", divide="ignore"):
        dot = np.float32(0)
        bb = np.float32(0)
        cc = np.float32(0)
        for i in range(b.size):  # IDL total: sequential FLOAT accumulation
            dot = np.float32(dot + b[i] * c[i])
            bb = np.float32(bb + b[i] * b[i])
            cc = np.float32(cc + c[i] * c[i])
        arg = np.float32(dot / np.sqrt(np.float32(bb * cc)))
        return np.float32(f32_via_f64(np.arccos, arg))


def find_angle_array(
    x1: ArrayLike, y1: ArrayLike, x2: ArrayLike, y2: ArrayLike,
    x3: ArrayLike, y3: ArrayLike,
) -> float | np.ndarray:
    """``find_angle_array(x1, y1, x2, y2, x3, y3)`` -- the angle at
    ``(x1, y1)``, by the law of cosines. ``x1``/``y1`` may be arrays.

    Source: ``find_angle_array.pro`` (SODA-2).

    Raises :class:`NotDoublePrecision` for a non-floating input, reproducing the
    source's own ``typename(x1) ne 'DOUBLE'`` guard. Integer input is refused
    rather than silently promoted: IDL would have halted, and promoting it here
    would answer a question the original refuses to answer.
    """
    x1a = np.asarray(x1)
    if x1a.dtype.kind != "f":
        raise NotDoublePrecision(
            "find_angle_array.pro needs double floating point values; it calls "
            f"stop for anything else, and x1 is {x1a.dtype!s}")
    x1a = x1a.astype(np.float64)
    y1a = np.asarray(y1, dtype=np.float64)
    x2a = np.asarray(x2, dtype=np.float64)
    y2a = np.asarray(y2, dtype=np.float64)
    x3a = np.asarray(x3, dtype=np.float64)
    y3a = np.asarray(y3, dtype=np.float64)

    dx1, dy1 = x2a - x3a, y2a - y3a       # side opposite the vertex
    dx2, dy2 = x1a - x2a, y1a - y2a
    dx3, dy3 = x1a - x3a, y1a - y3a
    b2 = dx2 ** 2 + dy2 ** 2
    c2 = dx3 ** 2 + dy3 ** 2
    a2 = dx1 ** 2 + dy1 ** 2

    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.arccos((b2 + c2 - a2) / (2 * np.sqrt(b2 * c2)))
    return float(out) if out.ndim == 0 else out
