# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-y: ``label_blobs``'s default BYTE return wraps at 256 blobs.

``label_blobs.pro:29`` -- the non-``/integer`` return path casts the label array to BYTE,
which wraps modulo 256: blob 256 becomes background (label 0), blob 257 aliases blob 1, and so
on. Reaches ``nblobs``, `numregions[i]`` and the ``keeplargest`` pixel selection at
``soda2_processbuffer.pro:690-695`` -- plausible on a busy buffer with ``keeplargest`` set.

**Correction**: call the port's own ``arrayprobe_soda2.label_blobs.label_blobs`` with
``integer=True`` -- a keyword the port already implements and documents
(``label_blobs.py``'s own docstring: "Returns uint32 labels when integer=True, else uint8").
Nothing is re-derived; this module is a thin wrapper naming the correct call, the same pattern
the finding's own suggested edit describes ("Pass /integer at the soda2_processbuffer.pro call
sites").

``src/arrayprobe_soda2/label_blobs.py`` is never imported for writing and never
modified -- the driver call sites (not ported by this repository's SODA-2 pipeline stage) would
still need `/integer` passed through, which is outside this correction's scope; this module
gives a caller the corrected call to use directly. Tests:
``tests/test_label_blobs_int_count.py``.
"""

from __future__ import annotations

import numpy as np
from arrayprobe_soda2.label_blobs import label_blobs

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_label_blobs"]


def corrected_label_blobs(img, dilatelength: int = 0,
                           all_neighbors: bool = False) -> np.ndarray:
    """``label_blobs(img, dilatelength=dilatelength, all_neighbors=all_neighbors,
    integer=True)`` -- S4-y corrected: labels are returned as ``uint32``, never wrapped
    modulo 256. Delegates entirely to the port's own function; the only difference from
    calling it directly is that ``integer=True`` is not left to the caller to remember."""
    return label_blobs(img, dilatelength=dilatelength, all_neighbors=all_neighbors,
                        integer=True)


register(EnhancementSpec(
    name="label_blobs_int_count",
    summary="label_blobs is called with integer=True, so labels are uint32 and never "
            "wrap modulo 256 (label_blobs.pro:29's default BYTE return).",
    finding="S4-y",
    reachability="latent",
    entry_point="corrected_label_blobs",
))
