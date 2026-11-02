# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S5-a + S5-q: ``d.count_rejected[itime,ireject[0]]++`` only counts
the first (lowest-bit) reject reason and never bit 128.

``soda2_particlesort.pro:177-178``::

    ireject=where(reject and [1,2,4,8,16,32,64])
    d.count_rejected[itime,ireject[0]]++

Two independent defects in the same two lines. **S5-a**: the mask
tests only the first seven reject bits, so ``d.count_rejected`` is
declared with 7 columns (``soda2_process_2d.pro:65``); a particle
rejected on bit 128 (depth-of-field) alone gives ``ireject=[-1]``, and
``ireject[0]`` then increments the array's **last** column (bit-64)
through IDL's negative-index convention, not a dedicated bit-128
column. **S5-q**: for a particle rejected on more than one criterion,
``ireject[0]`` is the *lowest-numbered* matching bit's column only --
the line's own comment ("Increment for each reason") says every
matching reason should be counted, and the source does not.

**Correction**: an 8-column tally, incrementing **every** matching
reason (bits 1-128), not only the lowest-numbered of the first seven
-- the union of both suggested edits in the register.

``src/arrayprobe_soda2/particlesort.py`` is never imported
for writing and never modified -- ``soda2_particlesort`` keeps writing
its own 7-column, first-reason-only ``d.count_rejected`` exactly as
written. This module calls the real, unmodified ``soda2_particlesort``
(which still mutates ``d`` and returns ``rejectionflag`` as always) and
builds a **separate, corrected tally array** from that same returned
``rejectionflag`` -- re-deriving each particle's time index with the
identical formula and bound check the port itself uses at ``:60``/
``:81`` (never re-deriving the accept/reject decision itself, which
``soda2_reject`` already made). Tests:
``tests/test_rejection_tally_fix.py``.
"""
from __future__ import annotations

import numpy as np
from arrayprobe_soda2.particlesort import (
    Accumulator,
    ParticlesortOptions,
    soda2_particlesort,
    spec_sort_locals,
)

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_count_rejected"]

#: The eight reject bits, in column order (S5-a adds column 7, bit 128).
_BITS = np.array([1, 2, 4, 8, 16, 32, 64, 128])


def corrected_count_rejected(
    op: ParticlesortOptions,
    x: dict[str, np.ndarray],
    d: Accumulator,
    reprocessed_time: np.ndarray | None = None,
) -> np.ndarray:
    """Runs the real ``soda2_particlesort`` (mutating ``d`` exactly as
    the unmodified port does) and returns a **separate**
    ``(d.numrecords, 8)`` int32 array: every matching reject bit
    (1..128) counted, for every particle, instead of ``d`` own 7-column
    first-reason-only ``count_rejected``."""
    rejectionflag = soda2_particlesort(op, x, d, reprocessed_time)

    truetime, _interarrival = spec_sort_locals(x, reprocessed_time)
    timeindex = np.trunc((truetime - op.starttime) / op.rate).astype(np.int64)

    corrected = np.zeros((d.numrecords, 8), dtype=np.int32)
    for j in range(rejectionflag.size):
        itime = int(timeindex[j])
        if not (0 <= itime < d.numrecords):
            continue  # :81's own bound check (S5-c), reproduced identically
        reject = int(rejectionflag[j])
        if reject == 0:
            continue
        matches = np.nonzero((reject & _BITS) != 0)[0]
        corrected[itime, matches] += 1
    return corrected


register(EnhancementSpec(
    name="rejection_tally_fix",
    summary="count_rejected gains an 8th column (bit 128, "
            "depth-of-field) and counts every matching reject reason "
            "per particle, not only the lowest-numbered of the first "
            "seven bits.",
    finding="S5-a",
    reachability="live",
    entry_point="corrected_count_rejected",
))
