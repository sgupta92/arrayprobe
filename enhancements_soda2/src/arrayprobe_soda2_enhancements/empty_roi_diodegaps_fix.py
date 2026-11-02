# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S5-h: the empty-ROI ``diodegaps`` value is 1, not 0, through the
same no-match ``where()`` sentinel S4-t and S5-f both reach by
different routes.

``soda2_processbuffer.pro:707-709``: ``:707`` finds the shaded diodes of
``roihist``, which for an all-zero ``roihist`` is the scalar sentinel
``-1`` with a count of 0; ``:708``'s span (largest index minus smallest,
plus one) is then 1, so ``:709``'s gap (span minus count) is 1 rather than the ``0`` a
caller might expect from "no shaded diodes, so no gap".

**Correction**: the register's own suggested edit -- guard ``nw eq 0``
explicitly and set ``diodegaps[i] = 0``.

``src/arrayprobe_soda2/processbuffer_tail.py`` is never
imported for writing and never modified -- this finding lives inside
``process_buffer_tail``'s per-particle loop, not behind a callable of
its own, so this module re-derives exactly ``:707-709``'s four-line
computation from ``roihist`` (a per-diode shadow count over one
particle's ROI, the same quantity ``process_buffer_tail`` builds at
``:703-704``) rather than wrapping the whole tail. Tests:
``tests/test_empty_roi_diodegaps_fix.py``, proved against the real
``process_buffer_tail`` end to end on the tracked SPEC fixture, not a
self-referential re-derivation.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_diodegaps"]


def corrected_diodegaps(roihist: Any) -> np.int16:
    """``diodegaps[i]`` (``soda2_processbuffer.pro:707-709``) with S5-h
    corrected: an all-zero ``roihist`` (no shaded diode anywhere in the
    particle's ROI) gives ``0``, not ``1``."""
    roihist = np.asarray(roihist)
    w = np.flatnonzero(roihist > 0)
    nw = w.size
    if nw == 0:
        return np.int16(0)  # S5-h correction; the port's :709 gives 1
    xspan = int(w.max()) - int(w.min()) + 1
    return np.int16(xspan - nw)


register(EnhancementSpec(
    name="empty_roi_diodegaps_fix",
    summary="diodegaps is 0, not 1, for a particle whose ROI has no "
            "shaded diode at all -- soda2_processbuffer.pro:707-709's "
            "where()-with-no-match sentinel (xspan=1) no longer applies.",
    finding="S5-h",
    reachability="flagged",
    entry_point="corrected_diodegaps",
))
