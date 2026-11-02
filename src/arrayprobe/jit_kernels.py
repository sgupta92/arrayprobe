# SPDX-License-Identifier: BSD-3-Clause
"""Opt-in accelerated kernels for the particle-image stage -- ``imgproc_sm(..., jit=True)``.

**Space: the port.** Every kernel here returns the same value as the function it
replaces, bit for bit, so a run with ``jit=True`` writes the same bytes as one
without (``tests/test_imgproc_jit_identity.py`` runs both and compares the files).
It is opt-in and defaults off, and numba -- an optional extra
(``pip install "arrayprobe[jit]"``) -- is imported only when a caller asks for it, never
by ``import arrayprobe``.

Which kernels, and why only these: the function-level profile of S3 on a dense
ORACLES window ranked the
per-particle work. Each kernel below is one of its hot rows and is exact by
construction -- integer or boolean logic only, no floating-point expression is
evaluated in a different order or by a different library:

``dec2bin_concat``
    The ``[dec2bin(X(:,1),w), ...]`` framing idiom, fused into one NumPy shift
    over all columns. Integer bit extraction; identical by construction. Falls
    back to :func:`arrayprobe.matlab_compat.dec2bin_concat` whenever a column
    would need MATLAB's widening (a value wider than ``width`` bits) or the input
    holds a negative, so both of those behaviours stay in one place.
``particle_perimeter``
    ``ParticlePerimeter.m``'s 4-neighbour boundary count, as a numba loop over
    the image. Integer comparisons and a counter.
``cgal_min_r``
    The minimum enclosing circle. :mod:`arrayprobe.geometry.min_circle` computes
    it in exact rational arithmetic (``fractions.Fraction``); the kernel runs the
    *same* Welzl pass, over the same shuffled candidates, with every circle held
    in homogeneous integers ``(X, Y, R2, D)`` -- centre ``(X/D, Y/D)``, squared
    radius ``R2/D**2``, ``D > 0`` -- so every predicate is the same exact
    comparison the Fraction path makes. Every int64 operation is guarded to keep
    magnitudes below ``2**62``; if any would exceed it, the kernel reports failure
    and the particle is recomputed on the Fraction path. The final ``sqrt`` is
    taken in Python on ``R2 / D**2`` as Python integers, which is correctly
    rounded -- the same float ``float(Fraction(R2, D**2))`` gives. So the guarded
    path is exact whenever it answers and the fallback is the original whenever it
    does not.

    How often the guard trips (derived, then measured): every circle Welzl builds
    is the smallest one through its fixed points containing a subset, so none is
    larger than the final circle; on a 2D-S image (128 x at most 1700 pixels)
    that bounds the centre to a few thousand diodes, ``D`` (four times a triangle's
    area) below 4.4e5, and ``R2`` below ~6e17 -- inside the guard. Measured: 0
    fallbacks in 21,916 dense-cloud particles. The guard is still there because
    the kernel accepts any shape below ``2**15``, and the test suite drives it
    with coordinates near that to prove it refuses rather than overflows.

What stays out, on purpose: :func:`arrayprobe.habit.holroyd` (its rotation and
``arctan``/``cos``/``sin`` are floating point, where a different libm or an FMA
contraction can move a ULP -- not provable here).

**``arrayprobe.reject.calculate_reject_unified`` -- corrected 2026-09-18.**
Its hot kernels are only partly "already numba-compiled in ``reject.py``,
measured and fuzz-tested there", and a real v3.5 CIP production profile
(``_decoded/cip160906/V35_JIT.md``,
``_decoded/cip160906/V35_REJECT_JIT.md``) showed it does not
cover what actually runs hot on that path. What ``reject.py`` (this v3.1.4 module's
sibling) actually compiles, measured by reading ``_ensure_numba_loaded``
rather than assumed from the function names alone:

- :func:`arrayprobe.reject.scan_slice` and
  :func:`arrayprobe.reject.is_it_hollow_sidescan` dispatch to numba kernels
  whenever numba is importable -- unconditionally, not gated by any
  ``jit=`` flag, the opposite posture from the kernels in *this* module.
- :func:`arrayprobe.reject.is_it_hollow` (the **non**-sidescan scan) is only
  partly covered: its internal ``scan_slice`` calls benefit, but its own
  ``_pack``/``_popcount``/``mask_start_end`` calls are the plain-Python
  bodies even when numba is present -- unlike ``is_it_hollow_sidescan``,
  it never got a single fused kernel for its own loop.
- :func:`arrayprobe.reject.calculate_reject_unified` itself -- the per-slice
  scanning pass, the aspect-ratio/threshold ladder, the Korolev lookup --
  has no numba dispatch of any kind; it benefits only indirectly, through
  ``scan_slice``.

None of this reaches the **v3.5 engine** at all: ``arrayprobe_uiops.reject``
has its own, differently-algorithmed ``calculate_reject_unified`` and
``is_it_hollow`` (v3.5 dropped v3.1.4's middle-third restriction and its
pack/bitshift hollow test for a direct ``bitand``), sharing only
``scan_slice`` with this module. Measured on a real v3.5 CIP production
pass, ``calculate_reject_unified`` was the single largest cost centre in a
full ``imgproc_sm_v35`` call -- larger than either kernel in this module's
own table. v3.5 now has its own opt-in kernels for it,
:mod:`arrayprobe_uiops.jit_kernels` (``calculate_reject_unified(jit=True)`` /
``is_it_hollow(jit=True)``), which fuse each whole per-particle loop into
one compiled call rather than one dispatch per slice. This v3.1.4 module's
own kernels are unchanged by that work.
"""

from __future__ import annotations

import math
import random

import numpy as np

from arrayprobe_uiops import geometry_core as _mc

from .matlab_compat import dec2bin_concat as _dec2bin_concat_reference
from .particle import shadow_mask

__all__ = ["JitKernels", "load", "FALLBACKS"]

_ZERO = ord("0")

#: Particles whose minimum-circle kernel hit the int64 guard and were recomputed
#: on the exact Fraction path, since the process started. Measured, not
#: assumed: the profile record reports the rate on the dense window.
FALLBACKS = {"min_circle": 0}


# --------------------------------------------------------------------------
# dec2bin_concat -- NumPy, no numba needed.
# --------------------------------------------------------------------------


def dec2bin_concat(columns, width):
    """Fused :func:`arrayprobe.matlab_compat.dec2bin_concat`; same array, same dtype."""
    cols = np.asarray(columns)
    if cols.ndim == 1:
        cols = cols.reshape(-1, 1)
    vals = cols.astype(np.int64)
    w = int(width)
    if vals.size == 0 or vals.min() < 0 or (vals.max() >> w) != 0:
        # Empty, negative (MATLAB errors) or widening (a column needs > w bits):
        # the reference handles each of those, per column, exactly as MATLAB.
        return _dec2bin_concat_reference(columns, width)
    shifts = np.arange(w - 1, -1, -1, dtype=np.int64)
    bits = (vals[:, :, None] >> shifts[None, None, :]) & 1
    return (bits.reshape(vals.shape[0], vals.shape[1] * w) + _ZERO).astype(np.uint8)


# --------------------------------------------------------------------------
# Pure-Python kernel bodies; numba compiles them on first use (see load()).
# --------------------------------------------------------------------------


def _perimeter_kernel(c):
    m, n = c.shape
    count = 0
    for i in range(m):
        for j in range(n):
            if c[i, j] == 48:
                if (i + 1 >= m or c[i + 1, j] != 48
                        or i == 0 or c[i - 1, j] != 48
                        or j + 1 >= n or c[i, j + 1] != 48
                        or j == 0 or c[i, j - 1] != 48):
                    count += 1
    return count


def _hull_kernel(mask):
    """Per column, ascending: (topmost row, col), (bottommost row, col).

    The same list, in the same order, as ``min_circle._hull_candidates`` builds
    from ``np.nonzero`` + a stable sort by column.
    """
    m, n = mask.shape
    out = np.empty((2 * n, 2), dtype=np.int64)
    k = 0
    for j in range(n):
        lo = -1
        hi = -1
        for i in range(m):
            if mask[i, j]:
                if lo < 0:
                    lo = i
                hi = i
        if lo >= 0:
            out[k, 0] = lo
            out[k, 1] = j
            out[k + 1, 0] = hi
            out[k + 1, 1] = j
            k += 2
    return out[:k]


_LIM = 1 << 62


def _welzl_kernel(pts):
    """Welzl over homogeneous int64 circles; returns (ok, R2, D).

    Mirrors ``min_circle.min_enclosing_circle_exact`` line for line. ``ok`` is
    False when a product would exceed 2**62 or a square 2**62 (so a sum of two
    squares stays below 2**63); the caller then recomputes on the Fraction path.
    """
    lim = _LIM
    n = pts.shape[0]
    # circle = (X, Y, R2, D): centre (X/D, Y/D), r2 = R2 / D**2, D > 0.
    cx = pts[0, 0]
    cy = pts[0, 1]
    cr = 0
    cd = 1
    for i in range(n):
        p0 = pts[i, 0]
        p1 = pts[i, 1]
        # _contains(circle, p)
        if abs(p0) > lim // cd or abs(p1) > lim // cd:
            return False, 0, 0
        dx = p0 * cd - cx
        dy = p1 * cd - cy
        if abs(dx) >= 3037000499 or abs(dy) >= 3037000499:  # isqrt(2**63 - 1)
            return False, 0, 0
        if dx * dx >= lim or dy * dy >= lim:
            return False, 0, 0
        if dx * dx + dy * dy <= cr:
            continue
        cx, cy, cr, cd = p0, p1, 0, 1
        for j in range(i):
            q0 = pts[j, 0]
            q1 = pts[j, 1]
            if abs(q0) > lim // cd or abs(q1) > lim // cd:
                return False, 0, 0
            dx = q0 * cd - cx
            dy = q1 * cd - cy
            if abs(dx) >= 3037000499 or abs(dy) >= 3037000499:
                return False, 0, 0
            if dx * dx >= lim or dy * dy >= lim:
                return False, 0, 0
            if dx * dx + dy * dy <= cr:
                continue
            # _from_two(p, q): centre (p+q)/2, r2 = |p-q|**2 / 4.
            ex = p0 - q0
            ey = p1 - q1
            cx, cy, cr, cd = p0 + q0, p1 + q1, ex * ex + ey * ey, 2
            for r in range(j):
                r0 = pts[r, 0]
                r1 = pts[r, 1]
                if abs(r0) > lim // cd or abs(r1) > lim // cd:
                    return False, 0, 0
                dx = r0 * cd - cx
                dy = r1 * cd - cy
                if abs(dx) >= 3037000499 or abs(dy) >= 3037000499:
                    return False, 0, 0
                if dx * dx >= lim or dy * dy >= lim:
                    return False, 0, 0
                if dx * dx + dy * dy <= cr:
                    continue
                # _from_three(p, q, r).  Coordinates are pixel indices (< 2**15,
                # checked by the caller), so d, a2.. and the numerators below
                # stay far inside int64 before any guard is needed.
                d = 2 * (p0 * (q1 - r1) + q0 * (r1 - p1) + r0 * (p1 - q1))
                if d == 0:
                    # Collinear: the widest of the three two-point circles,
                    # ties keeping the earlier one (Fraction's `>` is strict).
                    ex = p0 - q0
                    ey = p1 - q1
                    bx, by, br = p0 + q0, p1 + q1, ex * ex + ey * ey
                    ex = p0 - r0
                    ey = p1 - r1
                    if ex * ex + ey * ey > br:
                        bx, by, br = p0 + r0, p1 + r1, ex * ex + ey * ey
                    ex = q0 - r0
                    ey = q1 - r1
                    if ex * ex + ey * ey > br:
                        bx, by, br = q0 + r0, q1 + r1, ex * ex + ey * ey
                    cx, cy, cr, cd = bx, by, br, 2
                    continue
                a2 = p0 * p0 + p1 * p1
                b2 = q0 * q0 + q1 * q1
                c2 = r0 * r0 + r1 * r1
                ux = a2 * (q1 - r1) + b2 * (r1 - p1) + c2 * (p1 - q1)
                uy = a2 * (r0 - q0) + b2 * (p0 - r0) + c2 * (q0 - p0)
                if d < 0:
                    d = -d
                    ux = -ux
                    uy = -uy
                # r2 = (ax - ux/d)**2 + (ay - uy/d)**2 = R2 / d**2.
                if abs(p0) > lim // d or abs(p1) > lim // d:
                    return False, 0, 0
                ex = p0 * d - ux
                ey = p1 * d - uy
                if abs(ex) >= 3037000499 or abs(ey) >= 3037000499:
                    return False, 0, 0
                if ex * ex >= lim or ey * ey >= lim:
                    return False, 0, 0
                cx, cy, cr, cd = ux, uy, ex * ex + ey * ey, d
    return True, cr, cd


# --------------------------------------------------------------------------
# The loaded kernel set.
# --------------------------------------------------------------------------


class JitKernels:
    """The compiled kernels, and the drop-in functions imgproc calls through."""

    def __init__(self, njit):
        opts = {"cache": True, "boundscheck": True}  # fastmath stays OFF
        self._perimeter = njit(**opts)(_perimeter_kernel)
        self._hull = njit(**opts)(_hull_kernel)
        self._welzl = njit(**opts)(_welzl_kernel)
        self.dec2bin_concat = dec2bin_concat

    def particle_perimeter(self, c) -> int:
        """Drop-in for :func:`arrayprobe.particle_perimeter.particle_perimeter`."""
        a = np.asarray(c)
        if a.ndim != 2 or a.dtype.kind not in "iu":
            from .particle_perimeter import particle_perimeter
            return particle_perimeter(c)
        return int(self._perimeter(np.ascontiguousarray(a)))

    def cgal_min_r(self, c) -> float:
        """Drop-in for :func:`arrayprobe_uiops.geometry_core.cgal_min_r`."""
        a = np.asarray(c)
        if a.size == 0:
            return 0.0
        mask = np.ascontiguousarray(shadow_mask(a))
        if mask.ndim != 2 or not mask.any():
            return _mc.cgal_min_r(c)  # NaN (no shadowed pixel) or an unusual shape
        cand = self._hull(mask)
        pts = [(int(r), int(k)) for r, k in cand]
        random.Random(_mc._SEED).shuffle(pts)
        ok = False
        if max(mask.shape) < (1 << 15):
            ok, r2, d = self._welzl(np.asarray(pts, dtype=np.int64))
        if not ok:
            FALLBACKS["min_circle"] += 1
            return _mc.cgal_min_r(c)
        # Python ints: int / int is correctly rounded, so this is exactly
        # float(Fraction(r2, d*d)) -- what math.sqrt(Fraction) evaluates.
        return 1.0 + 2.0 * math.sqrt(int(r2) / (int(d) * int(d)))


_LOADED: JitKernels | None = None


def load() -> JitKernels:
    """Import numba and compile (or load from cache) the kernels, once per process."""
    global _LOADED
    if _LOADED is None:
        try:
            from numba import njit
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ModuleNotFoundError(
                "imgproc_sm(jit=True) / --jit needs numba, an optional extra: "
                'pip install "arrayprobe[jit]" ("arrayprobe[pinned]" installs the tested pin). '
                "The default "
                "(jit=False) writes the same bytes without it."
            ) from exc
        _LOADED = JitKernels(njit)
    return _LOADED
