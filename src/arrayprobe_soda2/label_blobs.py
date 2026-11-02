# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``label_blobs.pro`` -- label connected blobs in a binary image, working
around ``label_region``'s own border-zeroing.

30 lines of IDL. Signature ``label_blobs(img, _EXTRA=e, dilatelength=,
integer=)``. Callers: ``soda2_processbuffer.pro:687-689``
(``keeplargest`` 1/2/3, default 0 at ``soda2_update_op.pro:28``, called
with ``dilate=2``, IDL keyword abbreviation of ``dilatelength``), the
``:574`` HAIL branch (``dilate=1, /int``), and ``fillholes.pro:9``
(``dilatelength=0``, no ``/all``, byte return).


**Line-by-line**:

- ``:12`` -- ``img2 = 1b < img`` (``MIN(1, img)``): any nonzero pixel
  becomes 1.
- ``:13`` -- ``s = [size(img2,/dim), 1]``: a 1-D input gets ``s[1] = 1``
  and the routine's whole body still runs on the 2-D ``temp`` it builds;
  this port accepts a 1-D ``img`` and returns 1-D.
- ``:15-17`` -- ``pad = 1 > dilatelength`` (``MAX(1, dilatelength)``);
  ``temp`` is a zero-filled array ``pad`` pixels larger on every side,
  with ``img2`` written into the middle.
- **``label_region``'s own border rule**, worked around by the padding:
  IDL's ``label_region`` zeroes the outermost pixel ring of *its own
  input* (measured under GDL: a set pixel on ``temp``'s border gets label
  0). Because ``temp`` is always padded by at least 1, a real foreground
  pixel at ``img``'s own edge is never on ``temp``'s border, so
  ``label_blobs`` itself never loses an edge pixel -- that is the whole
  point of the padding (``:2``'s comment). Reimplemented here as
  :func:`_label_region`: a flood fill over ``temp``'s interior only,
  4-connected by default or 8-connected with ``all_neighbors=True``,
  labels assigned in **raster order (x fastest, then y)** over the first
  pixel of each blob encountered -- measured against GDL on a 3-blob case.
  Returns ``uint32`` labels (IDL: ``label_region`` "automatically converts
  to integer").
- ``:19-23`` -- when ``dilatelength != 0``: ``kerneldim = (dilatelength*2+1)
  < (s[1]+2)`` -- **clamped against the slice count plus 2, not against
  ``temp``'s own dimension** ``s[1]+2*pad`` -- so for a 1- or 2-slice roi
  with ``dilatelength=2`` the kernel is 3x3 in *both* directions, not 5x5
  (S4-z). A square all-ones kernel of that size, origin centred, dilates
  ``temp``; ``label_region`` runs on the dilated image; the *original*
  pixels then take the label of the dilated blob they fall in
  (``labels = temp * dilatedimage``). Because the foreground sits ``pad``
  pixels inside ``temp`` and the kernel radius never exceeds ``pad``
  (``kerneldim <= 2*dilatelength+1`` and ``pad >= dilatelength``),
  dilation never reaches ``temp``'s own border -- so no shim assumption
  about out-of-range reads is exercised here.
- ``:28-29`` -- crop back to the original footprint; ``integer=1`` returns
  the ``uint32`` crop, otherwise **``byte()``** -- modulo 256, so a roi
  with more than 255 blobs wraps (S4-y).
"""
from __future__ import annotations

import numpy as np

__all__ = ["label_blobs"]


def _label_region(temp: np.ndarray, all_neighbors: bool) -> np.ndarray:
    """4- (or 8-, ``all_neighbors``) connected labelling of ``temp``,
    raster order (x fastest, y slowest), matching GDL's ``label_region``
    on a padded (border-safe) input. ``temp`` is 2-D, ``uint8``-or-similar,
    0/nonzero."""
    ny, nx = temp.shape  # temp is stored [y, x] here; caller transposes
    labels = np.zeros((ny, nx), dtype=np.uint32)
    next_label = 1
    if all_neighbors:
        neighbours = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                      (0, 1), (1, -1), (1, 0), (1, 1)]
    else:
        neighbours = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for y in range(ny):
        for x in range(nx):
            if temp[y, x] == 0 or labels[y, x] != 0:
                continue
            # New blob found at raster position (x fastest): flood fill.
            stack = [(y, x)]
            labels[y, x] = next_label
            while stack:
                cy, cx = stack.pop()
                for dy, dx in neighbours:
                    ny_, nx_ = cy + dy, cx + dx
                    if (0 <= ny_ < ny and 0 <= nx_ < nx
                            and temp[ny_, nx_] != 0 and labels[ny_, nx_] == 0):
                        labels[ny_, nx_] = next_label
                        stack.append((ny_, nx_))
            next_label += 1
    return labels


def _dilate_square(img: np.ndarray, kerneldim: int) -> np.ndarray:
    """Binary dilation with a square all-ones kernel, origin centred,
    out-of-range reads as 0. Not exercised beyond ``temp``'s own padding
    (see module docstring), so no shim assumption is at stake here."""
    ny, nx = img.shape
    r = kerneldim // 2
    out = np.zeros_like(img)
    ys, xs = np.nonzero(img)
    for y, x in zip(ys.tolist(), xs.tolist(), strict=True):
        y0, y1 = max(0, y - r), min(ny, y + r + 1)
        x0, x1 = max(0, x - r), min(nx, x + r + 1)
        out[y0:y1, x0:x1] = 1
    return out


def label_blobs(
    img: np.ndarray,
    dilatelength: int = 0,
    all_neighbors: bool = False,
    integer: bool = False,
    jit: bool = False,
) -> np.ndarray:
    """``label_blobs(img, dilatelength=dilatelength,
    all_neighbors=all_neighbors, integer=integer)``
    (``label_blobs.pro:9-29``).

    ``all_neighbors`` is this port's name for IDL's ``/all`` keyword
    (passed through ``_EXTRA`` to ``label_region``'s ``ALL_NEIGHBORS``).
    Accepts and returns 1-D input for a 1-D ``img`` (``:13``). Returns
    ``uint32`` labels when ``integer=True``, else ``uint8`` (**wraps at
    256 blobs, modulo; SODA-2 register entry S4-y**, ``:29``).

    ``jit``
        Speed only, **default off** (space: the port --
        a profile found
        :func:`_label_region` the single hottest leaf in a real SODA-2 run,
        ~24-28 %). ``True`` routes :func:`_label_region` through
        :mod:`arrayprobe_soda2.jit_kernels`'s numba flood fill, exact by
        construction, so the array returned is the same bytes
        (``tests/test_soda2_label_region_jit_identity.py``). Needs numba,
        imported only here, never by ``import arrayprobe_soda2``. Not IDL's.
    """
    img = np.asarray(img)
    one_d = img.ndim == 1
    if one_d:
        img2d = img.reshape(1, -1)  # s[1] = 1, :13
    else:
        img2d = img

    img2 = np.minimum(1, img2d).astype(np.uint8)  # :12, [x, y] convention
    s0, s1 = img2.shape[0], img2.shape[1]  # s0 = diode axis, s1 = slice axis

    pad = max(1, dilatelength)
    temp = np.zeros((s0 + 2 * pad, s1 + 2 * pad), dtype=np.uint8)
    temp[pad:pad + s0, pad:pad + s1] = img2

    # _label_region above takes [y, x] = [slice, diode]; temp here is
    # [diode, slice], so transpose in and back out for the flood fill.
    temp_yx = temp.T

    if jit:
        # Imported here, never at module level: numba costs seconds to
        # import and the default path must not pay for it.
        from . import jit_kernels
        region_fn = jit_kernels.load().label_region
    else:
        region_fn = _label_region

    if dilatelength != 0:
        kerneldim = min(dilatelength * 2 + 1, s1 + 2)  # :20, S4-z
        dilated_yx = _dilate_square(temp_yx, kerneldim)
        region_labels_yx = region_fn(dilated_yx, all_neighbors)
        labels_yx = temp_yx.astype(np.uint32) * region_labels_yx
    else:
        labels_yx = region_fn(temp_yx, all_neighbors)

    labels = labels_yx.T  # back to [diode, slice]

    cropped = labels[pad:pad + s0, pad:pad + s1]
    if one_d:
        cropped = cropped.reshape(-1)

    if integer:
        return cropped.astype(np.uint32)
    return (cropped % 256).astype(np.uint8)  # byte(), :29, S4-y
