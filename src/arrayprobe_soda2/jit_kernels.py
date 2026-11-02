# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""SODA-2's opt-in accelerated kernel -- ``label_blobs(..., jit=True)``.

**Space: the port.** The kernel here returns the same value as the function
it replaces, bit for bit, so a call with ``jit=True`` returns the same array
as one without (``tests/test_soda2_label_region_jit_identity.py`` runs both
and compares with ``np.array_equal``/``tobytes()``, never ``allclose``). It
is opt-in and defaults off, and numba -- already an optional dependency of
the two UIOOPS-engine JIT paths (``arrayprobe.jit_kernels``,
``arrayprobe_uiops.jit_kernels``) -- is imported only when a caller asks for
it, never by ``import arrayprobe_soda2``, matching that same posture.

Which kernel, and why only this one: the function-level profile of a real
UND CIP run (profiled 2026-09-18) found
:func:`arrayprobe_soda2.label_blobs._label_region` -- the 4-/8-connected
flood fill ``label_blobs`` uses to work around IDL ``label_region``'s own
border-zeroing -- to be the single hottest **leaf** by self-time in the
profiled tail, ~24 % of it measured (305-particle dense window) and ~28 % of
a real run once combined with the established 97.3 %-of-a-run tail share.
It is two nested ``for`` loops over a small
2-D integer array plus a flood-fill stack: integer comparisons and array
indexing only, zero floating-point trig. Structurally almost identical to
the UIOOPS engine's own ``particle_perimeter`` kernel
(:mod:`arrayprobe.jit_kernels`), which was accelerated on exactly this
precedent -- pure integer double loop, numba-compiled, proven byte-identical
-- so no new exactness argument is needed here, only the same kind of
rewrite ``particle_perimeter``/``cgal_min_r`` already needed to become numba
kernels in the first place.

:func:`_label_region_kernel` is :func:`arrayprobe_soda2.label_blobs._label_region`
with its Python ``list`` of ``(y, x)`` tuples (numba's nopython mode does not
accept a growing reflected list of tuples) replaced by a pre-sized ``int64``
array stack with an explicit top pointer -- the same shape of rewrite
``cgal_min_r``'s Welzl pass needed for its own Python structures
(:mod:`arrayprobe.jit_kernels`'s module docstring). ``ny * nx`` rows is
always enough: a pixel is pushed at most once, immediately after its label
is set, and the ``labels[...] == 0`` guard then excludes it from ever being
pushed again. The stack's LIFO push/pop matches Python's
``list.append``/``list.pop()`` exactly, but this is provable overkill: the
*order* pixels are visited inside one flood fill cannot change the array
returned, because every pixel reached from a seed receives that seed's
``next_label`` regardless of the order the fill reaches it in -- only the
outer raster scan's y-then-x order (unchanged here, and the only place
``next_label`` is assigned) decides which id a blob receives. Connectivity
(4- vs 8-neighbour) is threaded through as a plain ``(k, 2)`` int64 offset
array rather than compiling two kernels, since neither array shape nor
values are part of a numba array type signature -- one compilation serves
both :func:`arrayprobe_soda2.label_blobs.label_blobs`'s ``all_neighbors``
states.

What stays out, on purpose (the profile's own "Ranked candidates" section):
``findsize``'s ``aspect_ratio``/``min_circle_fast_traced`` complex, ~61 % of
a real run. It routes through ``angles.find_angle_array``'s law-of-cosines,
the same floating-point-trig shape the UIOOPS profile excluded ``holroyd``
for ("rotates particle pixels with arctan, cos and sin ... one ULP could
move" -- ``arrayprobe/jit_kernels.py``'s own module docstring). Porting it
needs a trig-exactness proof this module does not attempt.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["JitKernels", "load"]


#: 4-connected and 8-connected neighbour offsets, ``(dy, dx)`` -- passed as
#: data, not baked into two separate compiled kernels (see module docstring).
_NEIGH4 = np.array([(-1, 0), (1, 0), (0, -1), (0, 1)], dtype=np.int64)
_NEIGH8 = np.array([(-1, -1), (-1, 0), (-1, 1), (0, -1),
                     (0, 1), (1, -1), (1, 0), (1, 1)], dtype=np.int64)


def _label_region_kernel(temp: np.ndarray, neighbours: np.ndarray) -> np.ndarray:
    """``label_blobs._label_region``'s body, numba-shaped: raster-order
    (y then x) flood fill of ``temp`` (2-D, 0/nonzero) using ``neighbours``
    (an ``(k, 2)`` int64 array of ``(dy, dx)`` offsets, ``k`` = 4 or 8).
    Returns ``uint32`` labels, same shape as ``temp``. See module docstring
    for why an array-backed stack replacing the reference's Python list
    cannot change the result.
    """
    ny, nx = temp.shape
    labels = np.zeros((ny, nx), dtype=np.uint32)
    next_label = 1
    n_nb = neighbours.shape[0]
    stack = np.empty((ny * nx, 2), dtype=np.int64)
    for y in range(ny):
        for x in range(nx):
            if temp[y, x] == 0 or labels[y, x] != 0:
                continue
            # New blob found at raster position (x fastest): flood fill.
            top = 0
            stack[top, 0] = y
            stack[top, 1] = x
            top += 1
            labels[y, x] = next_label
            while top > 0:
                top -= 1
                cy = stack[top, 0]
                cx = stack[top, 1]
                for k in range(n_nb):
                    ny_ = cy + neighbours[k, 0]
                    nx_ = cx + neighbours[k, 1]
                    if (0 <= ny_ < ny and 0 <= nx_ < nx
                            and temp[ny_, nx_] != 0 and labels[ny_, nx_] == 0):
                        labels[ny_, nx_] = next_label
                        stack[top, 0] = ny_
                        stack[top, 1] = nx_
                        top += 1
            next_label += 1
    return labels


class JitKernels:
    """The compiled kernel, and the drop-in function ``label_blobs`` calls
    through."""

    def __init__(self, njit: Any) -> None:
        opts = {"cache": True, "boundscheck": True}  # fastmath stays OFF
        self._label_region = njit(**opts)(_label_region_kernel)

    def label_region(self, temp: np.ndarray, all_neighbors: bool) -> np.ndarray:
        """Drop-in for :func:`arrayprobe_soda2.label_blobs._label_region`."""
        a = np.asarray(temp)
        if a.ndim != 2 or a.dtype.kind not in "iu":
            from .label_blobs import _label_region
            return _label_region(temp, all_neighbors)
        neighbours = _NEIGH8 if all_neighbors else _NEIGH4
        return self._label_region(np.ascontiguousarray(a), neighbours)


_LOADED: JitKernels | None = None


def load() -> JitKernels:
    """Import numba and compile (or load from cache) the kernel, once per
    process."""
    global _LOADED
    if _LOADED is None:
        try:
            from numba import njit
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ModuleNotFoundError(
                "label_blobs(jit=True) needs numba, an optional extra: "
                "pip install \"arrayprobe[jit]\". The default "
                "(jit=False) returns the same array without it."
            ) from exc
        _LOADED = JitKernels(njit)
    return _LOADED
