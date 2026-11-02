# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``poisson_spot_correct.pro`` -- Korolev (2007) hole-filling size correction.

Source: ``SODA2/abansemer-soda2-afcea15/poisson_spot_correct.pro`` (33 lines).
Called from exactly one place, the shared per-particle tail of
``soda2_processbuffer.pro:716``::

    zeed = 0
    area_orig[i]   = total(roi)
    roifilled      = fillholes(roi)
    area_filled[i] = total(roifilled)
    sizecorrection[i] = poisson_spot_correct(area_orig[i], area_filled[i], zd=zeed)

``total()`` of a byte/int array is IDL FLOAT (``soda2_processbuffer.pro:713-716``),
so both call-site arguments are FLOAT scalars, and the whole computation here is
float32 end to end -- bare decimal literals in the ``.pro`` source are also FLOAT.

What ``poisson_spot_correct.pro`` does, by line:

- ``:1`` -- takes the original and filled image areas; returns ``zd``
  through a keyword.
- ``:8-13``, ``:14-18``, ``:19-22`` -- three 164-entry FLOAT tables: the
  spot-to-edge ratio (0.003 to 0.95), the edge-to-true-diameter ratio
  (1.0 to 1.845) and ``Zd`` (0.0 to 8.15 in 0.05 steps).
- ``:24-25`` -- defaults: correction 1.0, ``Zd`` 0.0.
- ``:26`` -- only when both areas are non-negative:
- ``:27`` -- the ratio is the square root of the hole fraction, (filled
  minus original) over filled, in FLOAT;
- ``:28`` -- the index is the last table entry not above that ratio,
  clamped to the table's bounds;
- ``:29-30`` -- ``Zd`` and the correction are read at that index.
- ``:32`` -- returns the correction.

**The ``where`` / clamp trap.**  ``where(Dspot_Dedge le ratio)`` on an empty
match returns ``-1``; IDL's ``max`` of a single-element ``[-1]`` array is
``-1``; ``> 0`` (IDL's binary MAX, not a comparison) lifts that to ``0``; the
trailing ``< 163`` (IDL's binary MIN) is a no-op at that end. So a ``ratio``
of ``NaN`` (from a ``0/0`` or a negative radicand) makes every ``le``
comparison false, ``where`` returns ``-1``, and the clamp lands on index 0 --
exactly the same ``(1.0, 0.0)`` the *untaken* branch (``img_orig < 0`` or
``img_fill < 0``) returns, by a completely different route. See
finding S4-t for the
arithmetic-error consequence
IDL/GDL reports along the way.

**Cross-chain table identity.** ``Dspot_Dedge`` equals UIOOPS's ``SPOT_EDGE``
(``arrayprobe.reject.SPOT_EDGE``) at every index except **146**, where SODA-2
has the correct ``0.757`` and UIOOPS carries the preserved ``calculate_reject_
unified.m:54`` typo ``0757`` (parsed as the integer ``757.0``). ``Dedge_D0``
equals ``arrayprobe.reject.EDGE_0`` and ``Zeed`` equals ``arrayprobe.reject.
Z_D``, all 164 entries each -- both chains transcribed the same Korolev (2007)
table; SODA-2's copy is the one without the typo. This module does **not**
import ``arrayprobe`` -- the tables below are transcribed independently from
``poisson_spot_correct.pro:8-22`` so the cross-chain test in
``test_soda2_poisson_spot_correct.py`` compares two independent transcriptions,
not one value imported twice.

Validated against GDL by ``tests/test_soda2_poisson_spot_correct.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["DSPOT_DEDGE", "DEDGE_D0", "ZEED", "PoissonCorrection", "poisson_spot_correct"]

#: ``poisson_spot_correct.pro:8-13`` -- Korolev's hole-to-edge diameter ratio.
#: Monotone non-decreasing. 164 entries.
DSPOT_DEDGE = np.array([
    0.003, 0.008, 0.017, 0.024, 0.033, 0.04, 0.047, 0.054, 0.062, 0.072,
    0.076, 0.088, 0.093, 0.096, 0.101, 0.119, 0.123, 0.127, 0.13, 0.134,
    0.139, 0.148, 0.175, 0.18, 0.184, 0.188, 0.192, 0.195, 0.199, 0.202,
    0.206, 0.209, 0.213, 0.217, 0.221, 0.225, 0.23, 0.235, 0.243, 0.327,
    0.334, 0.34, 0.345, 0.351, 0.355, 0.36, 0.365, 0.369, 0.373, 0.377,
    0.381, 0.385, 0.389, 0.393, 0.397, 0.4, 0.404, 0.408, 0.411, 0.415,
    0.419, 0.422, 0.426, 0.429, 0.433, 0.436, 0.439, 0.443, 0.446, 0.45,
    0.453, 0.457, 0.46, 0.463, 0.467, 0.47, 0.473, 0.477, 0.48, 0.484,
    0.487, 0.49, 0.494, 0.497, 0.501, 0.504, 0.507, 0.511, 0.514, 0.518,
    0.521, 0.525, 0.528, 0.532, 0.535, 0.539, 0.543, 0.547, 0.55, 0.554,
    0.558, 0.562, 0.566, 0.569, 0.572, 0.575, 0.578, 0.581, 0.584, 0.587,
    0.59, 0.593, 0.596, 0.598, 0.601, 0.605, 0.61, 0.614, 0.618, 0.623,
    0.627, 0.631, 0.635, 0.64, 0.644, 0.648, 0.653, 0.657, 0.662, 0.666,
    0.671, 0.676, 0.68, 0.685, 0.69, 0.695, 0.7, 0.705, 0.711, 0.716,
    0.721, 0.727, 0.733, 0.738, 0.744, 0.751, 0.757, 0.763, 0.77, 0.777,
    0.784, 0.792, 0.8, 0.808, 0.817, 0.826, 0.836, 0.846, 0.858, 0.87,
    0.884, 0.901, 0.921, 0.95,
], dtype=np.float32)

#: ``:14-18`` -- Korolev's size-correction factor. NOT monotone (rises to
#: 1.908, then falls) -- that is the shape of Korolev's curve, not a defect.
#: 164 entries.
DEDGE_D0 = np.array([
    1.0, 1.054, 1.083, 1.101, 1.095, 1.11, 1.148, 1.162, 1.155, 1.123,
    1.182, 1.121, 1.162, 1.21, 1.242, 1.134, 1.166, 1.202, 1.238, 1.27,
    1.294, 1.278, 1.13, 1.148, 1.17, 1.194, 1.218, 1.242, 1.265, 1.288,
    1.31, 1.331, 1.351, 1.369, 1.386, 1.4, 1.411, 1.416, 1.407, 1.074,
    1.08, 1.087, 1.096, 1.106, 1.117, 1.127, 1.139, 1.15, 1.162, 1.173,
    1.185, 1.197, 1.208, 1.22, 1.232, 1.243, 1.255, 1.266, 1.277, 1.289,
    1.3, 1.311, 1.322, 1.333, 1.344, 1.355, 1.366, 1.376, 1.387, 1.397,
    1.407, 1.418, 1.428, 1.438, 1.448, 1.458, 1.467, 1.477, 1.486, 1.496,
    1.505, 1.515, 1.524, 1.533, 1.542, 1.551, 1.559, 1.568, 1.577, 1.585,
    1.594, 1.602, 1.61, 1.618, 1.626, 1.634, 1.642, 1.65, 1.657, 1.665,
    1.673, 1.68, 1.687, 1.694, 1.702, 1.709, 1.716, 1.722, 1.729, 1.736,
    1.742, 1.749, 1.755, 1.761, 1.768, 1.774, 1.78, 1.786, 1.791, 1.797,
    1.803, 1.808, 1.813, 1.819, 1.824, 1.829, 1.834, 1.839, 1.843, 1.848,
    1.852, 1.857, 1.861, 1.865, 1.869, 1.872, 1.876, 1.88, 1.883, 1.886,
    1.889, 1.892, 1.895, 1.897, 1.899, 1.901, 1.903, 1.905, 1.906, 1.907,
    1.908, 1.908, 1.908, 1.908, 1.907, 1.905, 1.903, 1.9, 1.897, 1.892,
    1.885, 1.877, 1.865, 1.845,
], dtype=np.float32)

#: ``:19-22`` -- Korolev's dimensionless object-plane distance, 0.05 steps.
#: Monotone. 164 entries.
ZEED = np.array([
    0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45,
    0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95,
    1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45,
    1.5, 1.55, 1.6, 1.65, 1.7, 1.75, 1.8, 1.85, 1.9, 1.95,
    2.0, 2.05, 2.1, 2.15, 2.2, 2.25, 2.3, 2.35, 2.4, 2.45,
    2.5, 2.55, 2.6, 2.65, 2.7, 2.75, 2.8, 2.85, 2.9, 2.95,
    3.0, 3.05, 3.1, 3.15, 3.2, 3.25, 3.3, 3.35, 3.4, 3.45,
    3.5, 3.55, 3.6, 3.65, 3.7, 3.75, 3.8, 3.85, 3.9, 3.95,
    4.0, 4.05, 4.1, 4.15, 4.2, 4.25, 4.3, 4.35, 4.4, 4.45,
    4.5, 4.55, 4.6, 4.65, 4.7, 4.75, 4.8, 4.85, 4.9, 4.95,
    5.0, 5.05, 5.1, 5.15, 5.2, 5.25, 5.3, 5.35, 5.4, 5.45,
    5.5, 5.55, 5.6, 5.65, 5.7, 5.75, 5.8, 5.85, 5.9, 5.95,
    6.0, 6.05, 6.1, 6.15, 6.2, 6.25, 6.3, 6.35, 6.4, 6.45,
    6.5, 6.55, 6.6, 6.65, 6.7, 6.75, 6.8, 6.85, 6.9, 6.95,
    7.0, 7.05, 7.1, 7.15, 7.2, 7.25, 7.3, 7.35, 7.4, 7.45,
    7.5, 7.55, 7.6, 7.65, 7.7, 7.75, 7.8, 7.85, 7.9, 7.95,
    8.0, 8.05, 8.1, 8.15,
], dtype=np.float32)


@dataclass(frozen=True)
class PoissonCorrection:
    """``{correction, zd}`` -- ``poisson_spot_correct``'s return value plus
    its ``zd=`` keyword output, and ``ip``, the clamped table index (not part
    of the IDL return, exposed here because the tests and the GDL bank need
    to inspect it). ``ip == -1`` means the branch at ``:26`` was not taken."""

    correction: np.float32
    zd: np.float32
    ip: int


def poisson_spot_correct(
    img_orig: float | np.floating, img_fill: float | np.floating,
) -> PoissonCorrection:
    """``poisson_spot_correct(img_orig, img_fill, zd=zd)`` -- Korolev (2007)
    hole-filling size correction, ported line for line.

    Source: ``poisson_spot_correct.pro`` (SODA-2).

    Both arguments are cast to ``np.float32`` at entry (the call site's
    ``total()`` already returns FLOAT, so this is a type assertion, not a
    conversion decision). Runs under ``np.errstate(all="ignore")`` because a
    zero or shrinking fill area drives ``:27`` to ``0/0`` or the square root
    of a negative -- IDL/GDL report this as a floating-point arithmetic error
    (SODA-2 register entry S4-t) but the *value* that reaches the caller is well defined: the same
    ``(1.0, 0.0)`` the untaken branch returns, arrived at through the
    ``where`` result of ``-1`` being clamped to ``0`` at ``:28``.
    """
    img_orig = np.float32(img_orig)
    img_fill = np.float32(img_fill)

    correction = np.float32(1.0)  # :24
    zd = np.float32(0.0)          # :25
    ip = -1

    with np.errstate(all="ignore"):
        if img_orig >= 0 and img_fill >= 0:                          # :26
            diff = np.float32(img_fill) - img_orig                   # :27
            ratio = np.sqrt(diff / img_fill)                         # :27
            hits = np.flatnonzero(DSPOT_DEDGE <= ratio)               # :28 where(...)
            ip = int(hits[-1]) if hits.size else -1                   #      max(where(...))
            ip = min(max(ip, 0), DSPOT_DEDGE.size - 1)                 #      > 0 < 163
            zd = ZEED[ip]                                              # :29
            correction = DEDGE_D0[ip]                                  # :30

    return PoissonCorrection(correction=correction, zd=zd, ip=ip)
