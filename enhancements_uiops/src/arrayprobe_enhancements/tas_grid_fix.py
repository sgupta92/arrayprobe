# SPDX-License-Identifier: BSD-3-Clause
"""A17 -- collapse duplicated TAS seconds so no second's particles are discarded.

``sizeDist.m:476`` sets ``one_sec_times = tas_time``, and ``:88`` floors the housekeeping-packet
times to whole seconds.  Two housekeeping packets inside one second therefore produce **two
identical grid entries**: the first spans the half-open interval ``[t, t)``, which is empty,
while the block-advance at ``:627-644`` still consumes that column's particles.  Every particle
whose second is duplicated is counted nowhere.

Measured on real 09/06/2016 files: 256-562 duplicated seconds per
file, and on ``base160906104932`` **1,210,698 accepted particles, 32,831 of them in the used
bins, against that file's used-bin total of 69,117**.  The archived product shows the same loss,
so this is UIOOPS behaviour that the port reproduces deliberately -- which is why the recovery is
an enhancement rather than a fix.

**Nothing in the port changes.**  The enhancement transforms the *input*: it collapses the
``(tas, timehhmmss)`` pair to one row per whole second before ``arrayprobe.sizedist.run`` is
called, keeping the first row of each second (MATLAB's own ``unique(..., 'first')`` convention,
used at ``:593`` for the particle blocks).  The port then runs unmodified over a grid whose
intervals are all non-empty.

Validation without an oracle -- the archived product cannot adjudicate this, because it exhibits
the loss:

* the collapsed grid is strictly increasing, so **every interval is non-empty** and the seconds
  partition the timeline: :func:`empty_intervals` returns none, on real TAS files as well as
  synthetic ones;
* the first row of each second survives and its ``tas`` value travels with it;
* an already-unique grid is returned unchanged (the enhancement is a no-op where the defect is
  absent);
* on a real file, the recovered particle count is compared against the independently-measured
  loss -- see ``enhancements_uiops/docs/CORRECTIONS.md`, part `tas_grid_fix.py``.
"""

from __future__ import annotations

import numpy as np

__all__ = ["floor_to_seconds", "duplicate_seconds", "empty_intervals", "collapse_tas_grid"]


def floor_to_seconds(timehhmmss):
    """``sizeDist.m:88`` -- HHMMSS(.frac) to whole seconds, with MATLAB's floors."""
    t = np.asarray(timehhmmss, dtype=np.float64)
    return (np.floor(t / 10000) * 3600
            + np.floor((t % 10000) / 100) * 60
            + np.floor(t % 100))


def duplicate_seconds(timehhmmss):
    """The whole seconds that appear more than once in the TAS times."""
    secs = floor_to_seconds(timehhmmss)
    values, counts = np.unique(secs, return_counts=True)
    return values[counts > 1]


def empty_intervals(timehhmmss):
    """Indices ``i`` whose interval ``[t_i, t_{i+1})`` is empty -- the defect itself.

    ``sizeDist`` assigns a particle to column ``i`` when
    ``one_sec_times[i] <= image_time < one_sec_times[i+1]``; when two grid entries are equal the
    first column can never match anything, yet its particle block is consumed.
    """
    secs = floor_to_seconds(timehhmmss)
    return np.flatnonzero(np.diff(secs) == 0)


def collapse_tas_grid(tas, timehhmmss):
    """Return ``(tas, timehhmmss, report)`` with one row per whole second.

    The first row of each second is kept, so the ``tas`` value used for a second is the one the
    unmodified run would have used for its (empty) first column.  Order is preserved; a grid
    that already has one row per second is returned unchanged.
    """
    tas = np.asarray(tas, dtype=np.float64)
    times = np.asarray(timehhmmss, dtype=np.float64)
    if tas.shape != times.shape:
        raise ValueError(f"tas and timehhmmss must match: {tas.shape} vs {times.shape}")
    secs = floor_to_seconds(times)
    if secs.size == 0:
        return tas, times, {"rows_in": 0, "rows_out": 0, "removed": 0,
                            "duplicated_seconds": 0, "empty_intervals_before": 0}
    # First occurrence of each second, in the order the seconds appear.
    keep = np.concatenate([[True], secs[1:] != secs[:-1]])
    report = {
        "rows_in": int(secs.size),
        "rows_out": int(keep.sum()),
        "removed": int(secs.size - keep.sum()),
        "duplicated_seconds": int(duplicate_seconds(times).size),
        "empty_intervals_before": int(empty_intervals(times).size),
    }
    return tas[keep], times[keep], report
