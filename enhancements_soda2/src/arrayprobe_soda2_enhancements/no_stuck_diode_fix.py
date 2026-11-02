# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-x + S5-f: the no-stuck-diode case is a silent scalar-index bug on
wide probes (S4-x), reached in production through
``soda2_processbuffer.pro:615``'s always-defined ``h=sbhist`` for the
SPEC path whenever ``stuckbits=1``, on any buffer whose previous second
saw no genuinely stuck diode (S5-f).

``fixstuckbits.pro:17-20``'s ``where()`` sentinel ``-1`` minus the
routine's own ``pad=7`` becomes the scalar index ``-8`` -- valid on any
probe with 8 or more diodes (every SPEC probe), so no diode crossing
the threshold silently zeroes and reconstructs diode column ``n-8``
as though it *had* been flagged, rather than leaving ``image``
unchanged. For fewer than 8 diodes IDL genuinely halts instead.

**Correction**: the register's own suggested edit -- test the
*pre-subtraction* ``where()`` result for "no match" and return
``image`` unchanged when none did, instead of the scalar ``-8`` index
(n>=8) or raising :class:`~arrayprobe_soda2.fixstuckbits.NoStuckBitsHalt`
(n<8).

``src/arrayprobe_soda2/fixstuckbits.py`` is never imported
for writing and never modified. This module calls the real,
unmodified ``fixstuckbits`` when at least one diode crosses the
threshold (the corrected and uncorrected paths agree there by
construction, since the port's own match branch is untouched) and
re-derives only the no-match test, reusing the port's own
``_median_filter_7`` rather than reimplementing it. Tests:
``tests/test_no_stuck_diode_fix.py``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from arrayprobe_soda2.fixstuckbits import _median_filter_7, fixstuckbits

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_fixstuckbits"]

_PAD = 7


def _any_diode_crosses_threshold(image: Any, h: Any) -> bool:
    """Re-derives ``fixstuckbits.pro:8-17``'s own ``where()`` test,
    verbatim, only to decide whether the no-match branch (S4-x)
    applies -- never the correction itself, which is simply "leave
    ``image`` unchanged"."""
    image = np.asarray(image)
    n = image.shape[0]
    if h is None:
        h_float = image.sum(axis=1).astype(np.float64)
    else:
        h_float = np.asarray(h, dtype=np.float64)
    h2 = np.zeros(n + 2 * _PAD, dtype=np.int32)
    h2[_PAD:_PAD + n] = h_float.astype(np.int32)
    hf = _median_filter_7(h2)
    diff = np.abs(h2.astype(np.float32) - hf)
    med_h = np.sort(h_float)[len(h_float) // 2]
    threshold = np.float32(10) * np.float32(np.sqrt(med_h))
    return bool(np.any(diff > threshold))


def corrected_fixstuckbits(image: np.ndarray, h: np.ndarray | None = None) -> np.ndarray:
    """``fixstuckbits(image, h=h)`` with S4-x/S5-f corrected: when no
    diode's histogram deviation crosses the threshold, ``image`` is
    returned unchanged -- not silently corrupted (n>=8 diodes) or
    raised (n<8), the port's two S4-x behaviours."""
    if _any_diode_crosses_threshold(image, h):
        return fixstuckbits(image, h=h)
    return np.asarray(image).copy()


register(EnhancementSpec(
    name="no_stuck_diode_fix",
    summary="fixstuckbits returns the image unchanged when no diode "
            "crosses the threshold, instead of silently corrupting "
            "diode column n-8 (n>=8) or halting (n<8) -- IDL's where() "
            "sentinel -1 minus pad=7 is a valid negative index.",
    finding="S4-x",
    reachability="live",
    entry_point="corrected_fixstuckbits",
))
