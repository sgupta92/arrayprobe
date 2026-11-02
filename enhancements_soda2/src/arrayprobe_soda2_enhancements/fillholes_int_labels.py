# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-u: ``fillholes`` wraps its hole labels modulo 256, so region 256 is never filled and
region 257 shares region 1's fate.

``fillholes.pro:9`` -- ``reverse = byte(label_blobs(img xor 1b))`` -- calls the port's own
``label_blobs`` with no keywords (``integer=0``, the BYTE-wrapping default, S4-y), then casts
the already-byte result to byte again. An ROI whose negative decomposes into more than 255
4-connected regions wraps region numbers modulo 256: region 256 becomes label 0 --
indistinguishable from "not part of any labelled blob", never filled by ``:20``'s
``img or (reverse<1b)``. Region 257 shares label 1's fate. Measured:
a synthetic 400-hole ROI comes back with ``AREA_FILLED`` one pixel short of the full
ROI area.

**Correction**: re-derive ``fillholes`` calling the port's own ``label_blobs(..., integer=True)``
instead of the keyword-less default -- the finding's own suggested edit
(``label_blobs(img xor 1b, /integer)`` and drop the ``byte()`` at ``:9``). The rest of
``fillholes.pro``'s body (border-vector edge removal, the final ``<1b`` clip) is dtype-agnostic
-- edge labels are compared for equality or clipped to ``{0,1}``, never stored -- so nothing
else needs to change, and this module duplicates ``fillholes.py``'s orchestration (not its
labelling) for exactly that reason: reuse the corrected label source, keep everything
downstream identical.

``src/arrayprobe_soda2/fillholes.py`` is never imported for writing and never
modified -- ``:9`` keeps calling ``label_blobs`` with byte-wrapping defaults, per the fidelity
doctrine. Tests: ``tests/test_fillholes_int_labels.py``.
"""

from __future__ import annotations

import numpy as np
from arrayprobe_soda2.label_blobs import label_blobs

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_fillholes"]


def _labelled_negative_int(img: np.ndarray) -> np.ndarray:
    """S4-u corrected: ``label_blobs(neg.T, integer=True)`` instead of
    ``fillholes.py``'s own ``_labelled_negative`` (byte-wrapping default). Same axis
    transpose (``label_blobs`` wants diode-fastest, this package's ``img`` is
    slice-fastest -- see ``fillholes.py``'s own docstring for the axis-convention note)."""
    neg = np.asarray(img, dtype=np.uint8) ^ np.uint8(1)
    labelled = np.asarray(label_blobs(neg.T, integer=True))
    return labelled.T.astype(np.uint32)


def corrected_fillholes(img, *, jit: bool = False) -> np.ndarray:  # noqa: ARG001
    """``fillholes(img)`` with S4-u corrected: the intermediate hole labels are
    ``uint32`` (via ``label_blobs(..., integer=True)``), never wrapped modulo 256. Returns
    the same ``(roilen, ndiodes)`` uint8 0/1 array shape as the port's own ``fillholes``.

    ``jit`` is accepted and **deliberately ignored**, so this stays a drop-in for the
    port's ``fillholes`` after 2026-09-18 gave that one a ``jit`` switch (the SODA-2
    flood-fill kernel, 36.2x, byte-identical). This correction runs its own
    ``integer=True`` path, which the compiled kernel does not cover, so accepting the
    keyword and taking the reference path is the honest behaviour: the alternative was a
    ``TypeError`` the moment ``processbuffer_tail`` started passing it, which is what the
    suite caught. If the kernel ever gains an integer-label mode, wire it here and delete
    this note -- silently ignoring a speed flag is only acceptable while it moves no byte
    and the docstring says so."""
    arr = np.asarray(img, dtype=np.uint8)

    if arr.ndim < 2:
        return arr.astype(np.uint8)
    roilen, ndiodes = arr.shape
    if roilen < 4 or ndiodes < 4:
        return arr.astype(np.uint8)

    reverse = _labelled_negative_int(arr)

    edges = np.concatenate([
        reverse[:, 0],
        reverse[0, :],
        reverse[:, -1],
        reverse[-1, :],
    ])
    edge_labels = np.unique(edges)

    mask = np.isin(reverse, edge_labels)
    reverse = np.where(mask, np.uint32(0), reverse)

    surviving_holes = np.minimum(reverse, np.uint32(1))
    newimg = (arr.astype(bool) | surviving_holes.astype(bool)).astype(np.uint8)
    return newimg


register(EnhancementSpec(
    name="fillholes_int_labels",
    summary="fillholes labels its negative image's blobs with label_blobs(..., "
            "integer=True) instead of the BYTE-wrapping default, so a >255-hole ROI "
            "no longer drops one hole (region 256 -> label 0) or misfills another "
            "(region 257 aliasing region 1).",
    finding="S4-u",
    reachability="latent",
    entry_point="corrected_fillholes",
))
