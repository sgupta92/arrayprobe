# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-z: the dilation kernel clamps against the roi's own slice count, not the padded
array it dilates.

``label_blobs.pro:20`` -- ``kerneldim = (dilatelength*2+1) < (s[1]+2)`` -- reads as though it
protects against exceeding ``temp``'s own size (``s[1] + 2*pad``), but clamps against
``s[1]+2`` instead, independent of ``pad``. For the production call
(``dilatelength=2``, ``soda2_processbuffer.pro:687-689``), a roi with 1 or 2 slices gets a
3-wide kernel instead of the intended 5-wide one, changing which fragments
``keeplargest`` merges.

**Correction**: re-derive ``label_blobs``'s dilation branch with the clamp corrected to
``s1 + 2*pad`` (equivalently, since ``pad = max(1, dilatelength)``, the clamp never actually
binds for any real call site -- as the finding's own suggested edit notes, the padded array is
never exceeded, so dropping the clamp is equivalent to fixing it). Duplicates
``label_blobs``'s orchestration (`:12-29`, ~20 lines) because the bug is inside the clamp
expression itself, not something a keyword can select -- but reuses the port's own
``_label_region``/``_dilate_square`` primitives (the labelling flood-fill and the square
dilation, both already standalone functions in ``label_blobs.py``) rather than reimplementing
either, so only the kernel-size formula can differ from the port.

``src/arrayprobe_soda2/label_blobs.py`` is never imported for writing and never
modified -- ``:20`` keeps the ``s[1]+2`` clamp exactly as written, per the fidelity doctrine.
Tests: ``tests/test_dilation_clamp_fix.py``.
"""

from __future__ import annotations

import numpy as np
from arrayprobe_soda2.label_blobs import _dilate_square, _label_region

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_label_blobs_dilation"]


def corrected_label_blobs_dilation(img, dilatelength: int,
                                    all_neighbors: bool = False,
                                    integer: bool = False) -> np.ndarray:
    """``label_blobs``'s dilation branch (`dilatelength != 0`) with S4-z's kernel clamp
    corrected to the padded array's own dimension. Only meaningful for
    ``dilatelength != 0`` -- the non-dilating branch never reaches the clamp at all, so
    :mod:`label_blobs_int_count` (S4-y) or the port's own ``label_blobs`` covers that case
    identically.
    """
    if dilatelength == 0:
        raise ValueError(
            "S4-z's clamp is inside the dilatelength != 0 branch; the port's own "
            "label_blobs(img, dilatelength=0, ...) already reproduces the non-dilating "
            "path exactly and needs no correction.")

    img = np.asarray(img)
    one_d = img.ndim == 1
    img2d = img.reshape(1, -1) if one_d else img

    img2 = np.minimum(1, img2d).astype(np.uint8)
    s0, s1 = img2.shape[0], img2.shape[1]

    pad = max(1, dilatelength)
    temp = np.zeros((s0 + 2 * pad, s1 + 2 * pad), dtype=np.uint8)
    temp[pad:pad + s0, pad:pad + s1] = img2
    temp_yx = temp.T

    # S4-z: clamp against the padded array's own dimension (s1 + 2*pad), not s1 + 2.
    kerneldim = min(dilatelength * 2 + 1, s1 + 2 * pad)
    dilated_yx = _dilate_square(temp_yx, kerneldim)
    region_labels_yx = _label_region(dilated_yx, all_neighbors)
    labels_yx = temp_yx.astype(np.uint32) * region_labels_yx

    labels = labels_yx.T
    cropped = labels[pad:pad + s0, pad:pad + s1]
    if one_d:
        cropped = cropped.reshape(-1)

    if integer:
        return cropped.astype(np.uint32)
    return (cropped % 256).astype(np.uint8)


register(EnhancementSpec(
    name="dilation_clamp_fix",
    summary="label_blobs's dilation kernel clamps against the padded array's own "
            "dimension (s1 + 2*pad), not s1 + 2 -- a 1- or 2-slice roi with "
            "dilatelength=2 gets the intended 5-wide kernel instead of 3-wide.",
    finding="S4-z",
    reachability="live",
    entry_point="corrected_label_blobs_dilation",
))
