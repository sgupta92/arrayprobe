# SPDX-License-Identifier: BSD-3-Clause
"""D3c -- give probetype 1 the clock-rollback correction the other two branches have.

**What it corrects.**  ``sizeDist.m`` corrects a backwards inter-arrival clock in a
three-way branch on ``probetype`` with only two branches filled
(``uioops_testing/sizeDist.m:726-730``; identically at
``UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/sizeDist.m:852-856``)::

    if 2==probetype
        int_arr(int_arr<-10) = int_arr(int_arr<-10) + (2^32-1)*(res/10^6/tasMax);
    elseif 0==probetype
        int_arr(int_arr<0)   = int_arr(int_arr<0)   + (2^24-1)*(res/10^6/tasMax);
    end
    % no clause for 1==probetype -- int_arr passes through unrolled-back

Twenty lines later the uncorrected value is not ignored, it is *charged to the particle*
(``:748-749``)::

    auto_reject(int_arr<0) = 'I';
    int_arr(int_arr<0)     = 0;

So on a CIP/PIP run every particle sitting at a backwards clock jump is rejected as an
inter-arrival failure and contributes zero to the second's ``sum_IntArr``.  The port
reproduces the missing branch deliberately (``sizedist.py:995-1006``, whose comment says
so); this module is the opt-in correction, outside the port.

**Two premises of the original finding are corrected here, and the corrections matter.**
The original finding (the missing probetype-1 rollback correction) was filed as *read, flagged for your check*, and reading is
where two of its statements came from:

1. It says probetype 1's counters are "the same fixed-width hardware counters probetype 0's
   correction exists for (24-bit)".  **They are not.**  ``imgProc_sm.m:659-663`` decodes the
   DMT record header into a 5-bit hour, 6-bit minute, 6-bit second, 10-bit millisecond and
   13-bit microsecond field, and ``:701`` assembles them::

       time_in_seconds(kk) = part_hour(kk)*3600 + part_min(kk)*60 + part_sec(kk) ...
                             + part_mil(kk)/1000 + part_micro(kk);

   That is a **decoded time of day**, not a free-running counter.  The rollover it can
   suffer is therefore **midnight** -- a drop of exactly 86400 s -- and the finding's
   suggested ``(2^24-1)*(res/10^6/tasMax)`` would be the wrong magnitude for it.  For a PIP
   (``res = 100``, ``tasMax = 200``) that span is 8.4 s; the 2^32 one the source's own
   diagnostic prints is 2147 s.  Neither is a day.
2. It says the source's own ``sum(int_arr<0)>0`` diagnostic "would not catch" the symptom.
   **Measured 2026-09-02, it does**: running the unmodified ``sizeDist.m`` under Octave on a
   probetype-1 proc file carrying one injected 86400 s backwards jump prints
   ``-8.6400e+04 -8.4253e+04`` from ``:733`` -- the uncorrected value beside what the 2^32
   formula would have made of it.  The run is loud, not silent.

What survives, and is the whole of the finding, is its first sentence: **probetype 1 gets no
correction of any kind**, and the particle at the jump pays for it.

**What it changes.**  Nothing inside ``arrayprobe``.  Following ``tas_grid_fix.py`` and
``pressure_units_fix.py``, the correction is applied to the *input* and the port then runs
completely unmodified:

* :func:`rollback_indices` and :func:`rollback_report` are the diagnostic;
* :func:`corrected_time_in_seconds` restores monotonicity by adding ``step`` to the tail at
  each backwards jump, cumulatively;
* :func:`proc_file_with_rollback_corrected` writes a corrected **copy** of a proc file, which
  ``arrayprobe.sizedist.run`` then reads with no argument changed.  ``Time_in_seconds`` has
  exactly one read site in the port (``sizedist.py:946``) and feeds only ``int_arr`` and
  ``int_arr3``, so the correction's blast radius is the finding's own scope.
* :func:`matlab_int_arr_rollback` is the faithful three-way branch, kept here so the module
  can state its own "before" side; the tests assert the port's *own unmodified run* on the
  uncorrected file reproduces MATLAB's, so the "before" of every A/B is measured, not
  argued.

**It refuses to pick the magnitude, and that is deliberate.**  Two readings are defensible
and they are not close together, so both ship as named constants and ``step`` is a required
argument -- the same stance ``pressure_units_fix.py`` takes on 900 hPa versus 9e5 Pa:

* :data:`SECONDS_PER_DAY` -- what ``imgProc_sm.m:701``'s construction implies, and the only
  rollover a time-of-day clock can have;
* :func:`counter_span` -- the finding's own suggestion, the fixed-width span probetype 0's
  branch uses, for a caller who has evidence that some DMT variant does wrap a counter here.

**What this module does NOT claim.**

* **No CIP/PIP campaign data exists on this machine, so nothing here is measured on a real
  flight.**  The only probetype-1 fixture in the project is 12 PECAN records, 1,184
  particles, two seconds -- far too short to roll over anything.  The oracle
  (``scripts/d3c_rollback_bank.py``) *injects* one backwards jump into that fixture and runs
  unmodified ``sizeDist.m`` over it under Octave.  That measures what MATLAB does with a
  rollback; it does **not** measure how often real CIP/PIP data contains one.  The answer to
  that is unknown here and is exactly what D3c asks the original authors to check.
* **It does not establish that any published CIP/PIP product is affected.**  It establishes
  what happens if one is.  A flight that never crosses midnight is untouched -- the same
  position ``rollover_fix.py`` (A5) is in, and for the same reason.
* **It cannot be validated against a corrected MATLAB output, because none can exist**: the
  branch the correction adds is not in any UIOOPS version.  What *is* validated against real
  MATLAB is the uncorrected side -- the port's faithful run is asserted equal to unmodified
  ``sizeDist.m``'s own output on the rollback file, all 25 variables.
* **It does not distinguish a midnight crossing from a corrupt record.**  Neither does the
  MATLAB, on any branch: probetype 0 and 2 both correct *any* sufficiently negative value.
  ``min_drop`` lets a caller require a jump of a stated size before treating it as a
  rollover, but the choice is a science call this module does not make.
* **It does not touch ``Time`` or ``particle_time``.**  A real midnight crossing also wraps
  those, and that is A5's site (``rollover_fix.py``), a separate correction with a separate
  decision behind it.
"""

from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np

__all__ = [
    "SECONDS_PER_DAY",
    "ROLLBACK_SITE",
    "REJECT_SITE",
    "PROBETYPE_THRESHOLDS",
    "AFFECTED_PROBETYPES",
    "NotAffectedProbetype",
    "counter_span",
    "matlab_int_arr_rollback",
    "int_arr_from_time_in_seconds",
    "rollback_indices",
    "corrected_time_in_seconds",
    "rollback_report",
    "proc_file_with_rollback_corrected",
]

#: One day.  ``imgProc_sm.m:701`` makes probetype 1's ``Time_in_seconds`` a time of day.
SECONDS_PER_DAY = 86400.0

#: The three-way branch with the missing clause.
ROLLBACK_SITE = "uioops_testing/sizeDist.m:726-730 (stock: sizeDist.m:852-856)"

#: Where an uncorrected negative value is charged to the particle.
REJECT_SITE = "uioops_testing/sizeDist.m:748-749 (stock: sizeDist.m:871-872)"

#: The negativity threshold each filled branch uses, and ``None`` for the one that is not.
#: probetype 2 uses ``-10``, not ``0`` -- a real asymmetry, not a transcription slip.
PROBETYPE_THRESHOLDS = {0: 0.0, 1: None, 2: -10.0, 3: None}

#: The probetypes this correction is FOR (2026-09-23). Probetype 1 only: it is the one
#: whose ``Time_in_seconds`` is a decoded time of day (``imgProc_sm.m:701``), which is the
#: only reason :data:`SECONDS_PER_DAY` is the right step, and the one ``:726-730`` gives no
#: branch at all. Probetype 3 also has no branch, but its clock is not established here, so
#: it is not claimed.
#:
#: **Probetype 2 (2D-S) is excluded by measurement, not only by the docstring's title.**
#: On seven ORACLES 2017 v3.5 2D-S proc files (95,986 to 17,822,350 particles each) the
#: backward steps in ``Time_in_seconds`` number 8 to 361 per file, all between -249.8 s and
#: -1.4e-5 s: the 2D-S clock is a 32-bit tick counter scaled by TAS (period about 250 s,
#: which is ``imgProc_sm.m:737``'s ``-250`` wrap test), and ``sizeDist.m:852-853`` already
#: corrects its steps below -10 s with the 2^32 span. Adding a day at each step instead
#: gives inter-arrivals of 86,150-86,400 s and a ``Time_in_seconds`` ending at up to
#: 31,193,677 s (361 days), measured September 2026.
AFFECTED_PROBETYPES = (1,)


class NotAffectedProbetype(ValueError):
    """Raised by :func:`proc_file_with_rollback_corrected` when told the file is from a
    probetype this correction is not for (:data:`AFFECTED_PROBETYPES`)."""


def counter_span(res: float, tas_max: float, bits: int = 24) -> float:
    """``(2^bits - 1) * (res/10^6/tasMax)`` -- the span a filled branch adds.

    ``bits=24`` is probetype 0's (``:729``), ``bits=32`` probetype 2's (``:727``).  Offered
    for a caller who has evidence that a DMT probe wraps a fixed-width counter here; the
    module does not assume it does.  For a PIP (``res=100``, ``tasMax=200``) the 24-bit span
    is 8.39 s and the 32-bit one 2147.48 s -- neither is a day, which is the point.
    """
    return (2.0 ** bits - 1.0) * (res / 1e6 / tas_max)


def matlab_int_arr_rollback(int_arr, probetype: int, res: float, tas_max: float):
    """``:726-730`` as written -- correct for probetype 2 and 0, nothing for 1 and 3.

    Returns a new array; the MATLAB statement mutates in place and the port reproduces
    that, so the copy here is a convenience for A/B use, not a semantic change.  Kept in
    this module so it can state its own "before" side without reaching into the port; the
    tests assert the *port's own unmodified run* produces the same output as unmodified
    MATLAB on the same file, which is the stronger check.
    """
    v = np.asarray(int_arr, dtype=np.float64).copy()
    if probetype == 2:
        roll = v < -10.0
        v[roll] += counter_span(res, tas_max, 32)
    elif probetype == 0:
        roll = v < 0.0
        v[roll] += counter_span(res, tas_max, 24)
    # probetype 1 and 3: no clause exists.  Falling through IS the finding.
    return v


def int_arr_from_time_in_seconds(time_in_seconds, *, first_block: bool = False):
    """``:690-698`` for probetype != 0 -- ``diff`` of the absolute clock.

    ``first_block`` reproduces ``:692``'s ``[0; diff(...)]`` for the block that has no
    preceding particle to difference against.  Provided so a caller can see what
    ``int_arr`` the port will build from a given ``Time_in_seconds``, without running
    ``sizeDist``.
    """
    t = np.asarray(time_in_seconds, dtype=np.float64).ravel()
    if first_block:
        return np.concatenate([[0.0], np.diff(t)])
    return np.diff(t)


def rollback_indices(time_in_seconds, *, min_drop: float = 0.0) -> np.ndarray:
    """0-based indices ``i`` where ``Time_in_seconds[i] < Time_in_seconds[i-1]``.

    ``min_drop`` (default ``0.0``, matching probetype 0's own ``int_arr<0`` rule) requires
    the decrease to be at least that large before it counts.  Probetype 2's branch uses
    ``-10`` instead; pass ``min_drop=10.0`` to reproduce that convention.
    """
    v = np.asarray(time_in_seconds, dtype=np.float64).ravel()
    if v.size < 2:
        return np.empty(0, dtype=np.int64)
    drop = v[:-1] - v[1:]
    return np.flatnonzero(drop > min_drop) + 1


def corrected_time_in_seconds(time_in_seconds, *, step: float,
                              min_drop: float = 0.0) -> np.ndarray:
    """Add ``step`` to the tail at **each** backwards jump, cumulatively.

    ``step`` is required: see the module docstring on why the magnitude is the caller's
    decision.  Pass :data:`SECONDS_PER_DAY` for the midnight reading, or
    :func:`counter_span` for the fixed-width-counter one.

    Because a constant is added to a whole suffix, the set of jumps in the raw array is the
    same set this pass walks, so the result is monotone wherever the raw array's only
    decreases were the jumps.
    """
    v = np.asarray(time_in_seconds, dtype=np.float64).ravel().copy()
    if v.size < 2:
        return v
    steps = np.zeros(v.size, dtype=np.float64)
    for i in rollback_indices(v, min_drop=min_drop):
        steps[i:] += float(step)
    return v + steps


def rollback_report(time_in_seconds, *, probetype: int, res: float, tas_max: float,
                    step: float | None = None, min_drop: float = 0.0) -> dict:
    """What the missing branch costs one ``Time_in_seconds`` array.  Changes nothing.

    ``particles_rejected`` is the count of particles ``:748`` would mark ``'I'`` on --
    the direct cost of the missing clause.  It is computed from the whole-array ``diff``,
    which is what the port builds per one-second block with a one-particle overlap, so it
    is exact except at the very first particle of the file (``:692``'s leading ``0``).
    """
    t = np.asarray(time_in_seconds, dtype=np.float64).ravel()
    idx = rollback_indices(t, min_drop=min_drop)
    raw = int_arr_from_time_in_seconds(t, first_block=True)
    faithful = matlab_int_arr_rollback(raw, probetype, res, tas_max)
    out = {
        "n": int(t.size),
        "probetype": probetype,
        "branch_threshold": PROBETYPE_THRESHOLDS.get(probetype),
        "has_correction_branch": PROBETYPE_THRESHOLDS.get(probetype) is not None,
        "rollbacks": int(idx.size),
        "rollback_indices": idx.tolist(),
        "largest_drop": float((t[:-1] - t[1:]).max()) if t.size > 1 else 0.0,
        "particles_rejected": int(np.count_nonzero(faithful < 0.0)),
        "span_24bit": counter_span(res, tas_max, 24),
        "span_32bit": counter_span(res, tas_max, 32),
        "seconds_per_day": SECONDS_PER_DAY,
    }
    if step is not None:
        corrected = corrected_time_in_seconds(t, step=step, min_drop=min_drop)
        fixed = int_arr_from_time_in_seconds(corrected, first_block=True)
        out.update({
            "step": float(step),
            "monotonic_after_correction": bool(
                rollback_indices(corrected, min_drop=min_drop).size == 0),
            "particles_rejected_after": int(np.count_nonzero(fixed < 0.0)),
        })
    return out


def proc_file_with_rollback_corrected(src, dst, *, step: float,
                                      min_drop: float = 0.0,
                                      probetype: int | None = None) -> dict:
    """Write a copy of ``src`` to ``dst`` with ``Time_in_seconds`` made monotone.

    Every other dimension, variable, value and attribute is copied verbatim, and ``src`` is
    never modified.  ``arrayprobe.sizedist.run`` then reads the copy with no argument
    changed -- the port stays exactly as validated, which is what makes the A/B a
    measurement of this correction rather than of a modified port.

    ``probetype``, when given, must be in :data:`AFFECTED_PROBETYPES`, or
    :class:`NotAffectedProbetype` is raised before anything is written. The driver
    adapter always passes it; ``None`` keeps the function usable on a file whose probetype
    the caller has established some other way.
    """
    if probetype is not None and probetype not in AFFECTED_PROBETYPES:
        own = PROBETYPE_THRESHOLDS.get(probetype)
        branch = (f"has its own branch at {ROLLBACK_SITE} (threshold {own})" if own is not None
                  else "has a clock this module has not established to be a time of day")
        raise NotAffectedProbetype(
            f"int_arr_rollback_fix is for probetype {AFFECTED_PROBETYPES}, not {probetype}: "
            f"probetype {probetype} {branch}, and a one-day step is the wrong magnitude for "
            "any clock that is not a time of day")
    src, dst = Path(src), Path(dst)
    with netCDF4.Dataset(src) as ds_in:
        var_in = ds_in.variables["Time_in_seconds"]
        var_in.set_auto_mask(False)
        raw = np.asarray(var_in[:], dtype=np.float64).ravel()
        fixed = corrected_time_in_seconds(raw, step=step, min_drop=min_drop)
        idx = rollback_indices(raw, min_drop=min_drop)
        shape = var_in.shape
        dtype = var_in.dtype
    # Byte copy, then overwrite the one variable in place: a variable-by-variable rebuild wrote
    # a (time, 2) ``position`` in one call at netCDF-C's default (1, 2) chunking, ~7 KB of
    # memory per chunk (measured September 2026).
    import shutil
    shutil.copyfile(src, dst)
    with netCDF4.Dataset(dst, "r+") as ds_out:
        out = ds_out.variables["Time_in_seconds"]
        out.set_auto_mask(False)
        out[:] = fixed.astype(dtype).reshape(shape)
    return {
        "source": str(src),
        "output": str(dst),
        "step": float(step),
        "rollbacks": int(idx.size),
        "rollback_indices": idx.tolist(),
        "changed": int(np.count_nonzero(fixed != raw)),
        "monotonic_after_correction": bool(
            rollback_indices(fixed, min_drop=min_drop).size == 0),
    }
