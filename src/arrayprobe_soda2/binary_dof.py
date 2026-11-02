# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``binary_dof.pro`` -- depth-of-field rejection by neighbour compactness.

Source: ``SODA2/abansemer-soda2-afcea15/binary_dof.pro`` (33 lines). Called
from exactly one place, ``soda2_processbuffer.pro:303``, inside the SPEC
branch already ported as :mod:`arrayprobe_soda2.processbuffer_spec`, and
only when ``(*pop).dofreject eq 3``::

    dof[c] = binary_dof(x.image)

``x.image`` is the decoded frame, IDL dims ``[128, nslices]``
(``spec_read_frame.pro:29``); this package's convention holds it
**transposed**, ``(nslices, 128)`` uint8 (``spec_read_frame.py:204``). The
result lands in ``dofflag``/``dof`` (``soda2_processbuffer.pro:744``) and
reaches output.

What ``binary_dof.pro`` does, by line:

- ``:1`` -- the function takes ``bitimage`` and returns ``neighbor_count``
  through a keyword.
- ``:5`` -- an image holding any value above 1 halts IDL with a
  "must be binary" message.
- ``:6`` -- ``s`` is the image's dimensions.
- ``:8-13`` -- an image under 3 pixels on either side is zero-padded to at
  least 3x3 (original in the low corner); otherwise it is used as is.
- ``:16`` -- a 3x3 kernel: 0.7 on the diagonals, 1 on the edges, 0 centre.
- ``:17`` -- ``neighbor_count`` is the sum, over shaded pixels, of the
  zero-edged convolution of the (padded) image with that kernel.
- ``:21`` -- ``area`` is the shaded-pixel total of the unpadded image.
- ``:22`` -- ``dof`` starts at 0.
- ``:23-31`` -- ``dof`` becomes 1 for area 1 unconditionally, and for areas
  2-6 when ``neighbor_count`` reaches 2, 5, 8, 11 and 17 respectively;
  above 6, when it reaches three times the area.
- ``:32`` -- returns ``dof``.

**``stop`` -> ``ValueError``.** ``:5``'s ``stop`` is an interactive IDL
halt; this port raises :class:`ValueError` instead, a deliberate,
documented divergence.
In practice this is unreachable from ``:303`` -- ``x.image`` is binary by
construction out of ``spec_decompress`` -- confirmed under GDL (bank case
``value_two``, ``status=HALTED``); this turned out to be fine and is not
a defect.

**The GDL oracle needed a zero-ring embedding, not a raw call** (measured
2026-09-14). On this machine's GDL (v1.1.2-52),
``EDGE_CONSTANT`` is accepted by ``convol`` but silently **ignored** --
edge outputs come back zero exactly as the no-keyword default -- and a 3x3
kernel is **refused** on any array with a dimension equal to 3
(``% CONVOL: Incompatible dimensions for Array and Kernel``). Since every
real particle typically touches slice 0 and slice n-1 (both array edges),
a raw GDL call gives the wrong ``neighbor_count`` for essentially every
case, not just a corner: measured ``binary_dof(bytarr(3,3)+1b)`` gives
``NC=6.8, DOF=0`` under GDL where IDL's documented ``EDGE_CONSTANT``
(pad-with-constant) computes ``NC=35.2, DOF=1``.

The bank instead calls the **unmodified** ``binary_dof.pro`` on the image
embedded in a one-pixel ring of zeros. This equals IDL's
``EDGE_CONSTANT=0`` result on the unpadded image **by derivation from the
keyword's definition** (pad-with-constant), not by measurement against
IDL: the zeroed GDL edge outputs then fall on the padding ring, which
``* image`` masks to 0 regardless; interior sums are exact; ``area =
total(bitimage)`` is unchanged by zero padding; and both dimensions are
now >= 3, so the "Incompatible dimensions" refusal cannot fire. Both GDL
facts are **oracle notes**, not
SODA-2 findings -- the routine itself is unmodified.

**IDL semantics this port models:**

- ``:6-13`` padding to ``[s0>3, s1>3]`` is output-neutral under
  ``EDGE_CONSTANT=0`` (a zero-filled convolution edge either way); this
  port never pads -- ``test_unpadded_and_zero_ring_embedded_images_agree``
  pins that a 1-, 2- and 3-slice image gives the same ``neighbor_count``
  whether or not it is embedded in a zero ring first.
- ``:16-17`` the kernel is symmetric with a zero centre, so orientation
  and correlation-vs-convolution conventions are moot; for each ON pixel,
  ``neighbor_count`` accumulates the weighted count of its ON 8-neighbours
  (direct 1.0, diagonal 0.7). ``total()`` of a FLOAT array is FLOAT;
  accumulation order/precision of IDL ``total`` is undocumented for this
  purpose, so this port sums explicitly in **float32**, in IDL memory
  order (diode fastest, then slice -- plain C-order over the transposed
  ``(nslices, 128)`` array).
- ``:21-31`` ``area`` is FLOAT; the ``CASE`` compares FLOAT against
  integer literals (``1.0 eq 1`` is true in IDL). A blank image
  (``area = 0``) falls to ``ELSE``, and ``0 ge 0`` is true -- **accepted**
  (finding S4-v).

Validated against GDL by ``tests/test_soda2_binary_dof.py``; bank at
``gdl_oracle/run_soda2_binary_dof_bank.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["KERNEL", "THRESHOLDS", "BinaryDof", "binary_dof"]

#: ``binary_dof.pro:16``, transcribed verbatim. FLOAT, symmetric, centre 0.
KERNEL = np.array(
    [[0.7, 1.0, 0.7], [1.0, 0.0, 1.0], [0.7, 1.0, 0.7]], dtype=np.float32,
)

#: ``binary_dof.pro:23-29``. ``area == 1`` accepts unconditionally (``None``
#: means "no threshold test needed" -- handled separately below).
THRESHOLDS: dict[int, float | None] = {1: None, 2: 2.0, 3: 5.0, 4: 8.0, 5: 11.0, 6: 17.0}

_OFFSETS = (
    (-1, -1, 0.7), (-1, 0, 1.0), (-1, 1, 0.7),
    (0, -1, 1.0), (0, 1, 1.0),
    (1, -1, 0.7), (1, 0, 1.0), (1, 1, 0.7),
)


@dataclass(frozen=True)
class BinaryDof:
    """``binary_dof.pro``'s return value plus its ``neighbor_count=``
    output keyword and the ``area`` it computed along the way."""

    dof: int
    neighbor_count: np.float32
    area: np.float32


def binary_dof(bitimage: np.ndarray) -> BinaryDof:
    """``d = binary_dof(bitimage, neighbor_count=nc)``.

    Source: ``binary_dof.pro`` (SODA-2).

    ``bitimage`` is a 2-D binary (0/1) array, this package's
    ``(nslices, 128)`` convention. A 1-D 128-vector (the one-slice IDL
    frame ``[128, 1]``, itself 2-D) is reshaped to ``(1, 128)``.
    """
    arr = np.asarray(bitimage)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.size == 0:
        max_val = 0
    else:
        max_val = int(arr.max())
    if max_val > 1:
        raise ValueError("binary_dof.pro:5: Bitimage must be binary")

    img = np.asarray(arr, dtype=np.uint8)
    f = img.astype(np.float32)
    nrows, ncols = f.shape

    # `:17` -- for each ON pixel, sum the weighted ON 8-neighbours, in IDL
    # memory order (diode fastest, then slice: plain C-order here).
    contrib = np.zeros_like(f, dtype=np.float32)
    for dr, dc, weight in _OFFSETS:
        shifted = np.zeros_like(f, dtype=np.float32)
        src_r0, src_r1 = max(0, -dr), nrows - max(0, dr)
        src_c0, src_c1 = max(0, -dc), ncols - max(0, dc)
        dst_r0, dst_r1 = max(0, dr), nrows - max(0, -dr)
        dst_c0, dst_c1 = max(0, dc), ncols - max(0, -dc)
        if src_r1 > src_r0 and src_c1 > src_c0:
            shifted[dst_r0:dst_r1, dst_c0:dst_c1] = f[src_r0:src_r1, src_c0:src_c1]
        contrib += np.float32(weight) * shifted

    masked = contrib * f
    neighbor_count = np.float32(0)
    for v in masked.ravel(order="C"):
        neighbor_count = np.float32(neighbor_count + v)

    area = np.float32(img.sum())

    area_int = int(area)
    dof = 0
    named_thr = THRESHOLDS.get(area_int) if float(area_int) == float(area) else None
    if area == np.float32(1):
        dof = 1
    elif float(area_int) == float(area) and area_int in THRESHOLDS:
        if named_thr is not None and neighbor_count >= np.float32(named_thr):
            dof = 1
    else:
        else_thr = np.float32(area * np.float32(3))
        if neighbor_count >= else_thr:
            dof = 1

    return BinaryDof(dof=dof, neighbor_count=neighbor_count, area=area)
