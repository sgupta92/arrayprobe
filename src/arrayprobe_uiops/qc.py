# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``imgProc_sm.m:801-846`` -- the ``iQC=1``
(the UIOPS quality-control option) denoise pass (Part C).

Run on the char image ``c`` *after* ``dec2bin`` assembly (``:792-795``) and
*before* the width check (``:849-853``) and every measurement, so a cleaned
image is what every downstream measurement sees.  Pure numpy: the port
refuses scipy in core (it is in the ``arrayprobe[extra]`` extra; ``intarr.py:68`` imports
it lazily as an enhancement extra only), so the three MATLAB Image Processing
Toolbox calls this pass makes -- ``bwareaopen``, ``bwconncomp``, ``bwdist``
with ``'chessboard'`` -- are each reimplemented directly against their own
documented semantics rather than pulled from a dependency.

Octave 11.3 (the differential oracle) supplies the first three from its
``image`` package (2.20.0, measured present, ``pkg load image``);
``mink`` (MATLAB R2017b+) is not implemented there (measured
``exist('mink')==0``) and is supplied by ``octave_oracle/v35_qc_shims/mink.m``,
placed on the Octave path *ahead of* the vendored tree -- the tree is never
edited.

What it computes, per particle, verbatim from ``:801-846``:

1. ``pix_thresh = 5``; ``P = max(5, floor(0.01*5*sum(sum(c=='0'))))`` --
   ``'0'`` is the shadowed diode (``:263``, ``:803``).
2. ``c_logical = bwareaopen('1' - c, P)`` -- MATLAB's 2-D default
   connectivity is **8**; Octave's ``bwareaopen`` default
   (``conndef(2,"maximal")``) is also 8 (measured).
3. If every pixel of ``c_logical`` is False: ``num_subparticles = 0``,
   ``dist_min = 0``, and **``c`` is returned unchanged** (``:804-807`` --
   the ``continue`` is commented out in the vendored file).
4. Else: ``c_parts = bwconncomp(c_logical, 8)``;
   ``num_subparticles = c_parts.NumObjects`` (``:809-810``).  If ``> 1``:
   for each component, ``darr = bwdist(component_only, 'chessboard')``
   (``:814-819``); for every pair, ``dist(a,b) = min(darr_a + darr_b) - 1``
   (``:833``); ``dist_min = max(mink(dist_arr, n-1))``, i.e. the
   **(n-1)-th smallest** pairwise distance (``:835``).  If ``== 1``:
   ``dist_min = 0`` (``:837``).
5. ``if dist_min < 5: num_subparticles = 1`` (``:840-842``) --
   **``dist_min`` is NOT reset**, so a two-component image found 3 apart
   merges to ``(num_subparticles=1, dist_min=3)``: a reader of
   ``subparticle_mindist`` sees a nonzero distance for what the file calls
   a single particle. Preserved, not corrected --
   not a bug this port may fix.
6. ``c = char('1' - c_logical)`` (``:844``) -- the cleaned image replaces
   ``c`` for all later measurements, only in the branch that reached here
   (i.e. never in the branch-3 no-survivor case).

Component discovery order (a column-major raster scan, matching
``bwconncomp``'s own ``PixelIdxList`` order) does not affect ``dist_min``:
the value is ``min`` over each pairwise Chebyshev distance transform, then
an order statistic over the resulting (order-independent, since it is a set
of pairwise distances) list -- so any consistent labelling gives the same
answer. ``tests/test_v35_qc.py`` pins this with a shuffle test rather than
asserting it.
"""

from __future__ import annotations

import itertools

import numpy as np

from .particle import shadow_mask

__all__ = ["qc_image"]

#: ``:802`` -- the experimental percent threshold, and ``:803``'s ``0.01 *``
#: factor kept as its own literal so the MATLAB expression stays visible.
_PIX_THRESH = 5


def _label8(mask: np.ndarray) -> list[np.ndarray]:
    """8-connected components of a boolean 2-D array (``bwconncomp(mask, 8)``).

    Returns one boolean mask per component, in column-major first-pixel
    discovery order (MATLAB's own linear-index convention) -- documented
    only for reproducibility of intermediate state; see the module
    docstring for why ``dist_min`` does not depend on this order.
    """
    nrows, ncols = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[np.ndarray] = []
    for col in range(ncols):
        for row in range(nrows):
            if not mask[row, col] or visited[row, col]:
                continue
            comp = np.zeros_like(mask, dtype=bool)
            stack = [(row, col)]
            visited[row, col] = True
            while stack:
                r, c0 = stack.pop()
                comp[r, c0] = True
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c0 + dc
                        if (0 <= nr < nrows and 0 <= nc < ncols
                                and mask[nr, nc] and not visited[nr, nc]):
                            visited[nr, nc] = True
                            stack.append((nr, nc))
            components.append(comp)
    return components


def _bwareaopen(mask: np.ndarray, min_pixels: int) -> np.ndarray:
    """``bwareaopen(mask, min_pixels)`` -- keep 8-connected components with at
    least ``min_pixels`` pixels; MATLAB's own wording ("removes ... fewer than
    P pixels") makes ``>= P`` the surviving set, not ``> P``."""
    out = np.zeros_like(mask, dtype=bool)
    for comp in _label8(mask):
        if int(comp.sum()) >= min_pixels:
            out |= comp
    return out


def _chessboard_distance_transform(component: np.ndarray) -> np.ndarray:
    """``bwdist(component, 'chessboard')`` -- per-pixel minimum Chebyshev
    distance to the nearest True pixel of ``component``, over the component's
    own full grid (``:814-819``). Particle images here are at most a few
    hundred pixels, so brute force is exact and obviously right."""
    fg = np.argwhere(component)
    if fg.size == 0:  # pragma: no cover -- every component here is non-empty
        return np.full(component.shape, np.inf)
    rows, cols = np.indices(component.shape)
    all_pts = np.stack([rows.ravel(), cols.ravel()], axis=1)
    d = np.abs(all_pts[:, None, :] - fg[None, :, :]).max(axis=2).min(axis=1)
    return d.reshape(component.shape).astype(np.float64)


def qc_image(c: np.ndarray) -> tuple[np.ndarray, int, int]:
    """``imgProc_sm.m:801-846``. Returns ``(c_after, num_subparticles, dist_min)``.

    ``c`` is the ``(n_slices, diodenum)`` particle image in any form
    :func:`arrayprobe.particle.shadow_mask` accepts (the same convention
    ``measure_record`` uses downstream). ``c_after`` is returned in that same
    canonical form on both branches -- the vendored file's own ``char('1' -
    c_logical)`` rebuild (``:844``) is reproduced literally as a ``'0'``/``'1'``
    ASCII array so a caller inspecting ``c_after``'s dtype sees the same
    convention as the input, not a silently-widened boolean.
    """
    shadow = shadow_mask(c)  # True where c == '0' (shadowed) -- :801-806
    n_shadowed = int(shadow.sum())
    min_pixels = max(5, int(np.floor(0.01 * _PIX_THRESH * n_shadowed)))  # :803

    c_logical = _bwareaopen(shadow, min_pixels)  # :803

    if not c_logical.any():  # :804
        return c, 0, 0  # :805-807 -- c unchanged

    components = _label8(c_logical)  # :809
    num_subparticles = len(components)  # :810

    if num_subparticles > 1:  # :813
        darr = [_chessboard_distance_transform(comp) for comp in components]  # :814-819
        dist_arr = [
            float(np.min(darr[a] + darr[b])) - 1.0  # :833
            for a, b in itertools.combinations(range(num_subparticles), 2)  # :822 nchoosek
        ]
        # :835 -- max(mink(dist_arr, n-1)) is the (n-1)-th smallest value.
        dist_min = int(round(sorted(dist_arr)[num_subparticles - 2]))
    else:
        dist_min = 0  # :837

    if dist_min < 5:  # :840-842 -- dist_min is NOT reset here
        num_subparticles = 1

    c_after = np.where(c_logical, np.uint8(ord("0")), np.uint8(ord("1")))  # :844
    return c_after, num_subparticles, dist_min
