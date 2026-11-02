# SPDX-License-Identifier: BSD-3-Clause
"""A5 at the probetype-1 site -- repair glitched CIP/PIP particle times before ``sizeDist`` files them.

**What goes wrong in the port (and in the MATLAB it reproduces).**  For probetype 1 a particle's
UT comes from the particle header's own clock, ``particle_time`` (``sizeDist.m:511-514``), not
from the buffer's record time.  On 2016-09-06 the CIP header clock of session 2 steps backwards
1,045 times: isolated header times that read ``0``, ``202``, ``316363`` (``31:63:63``, every
field all-ones, not a valid HHMMSS) and a few hundred other out-of-sequence values, each followed
by a return to the running clock.  Two things then happen, both faithfully reproduced by the port:

1. **The cascade** (``sizeDist.m:544-545``, production tree; stock ``:657-658``).  The midnight
   correction ``x(find(diff(x)<0)+1:end) += 240000`` tests ``diff(x) < 0`` with no magnitude, so
   the first glitch -- 09:56:02 UT, particle 897,297 -- adds 240000 to **every later particle**.
   2,899,268 of 3,796,565 session-2 particles are filed 24 h late, past the last TAS second, and
   the ``sd`` file is empty for the remaining 4 h 44 min.  Nothing is printed.
2. **Misfiling.**  Even with no cascade, a glitched time opens its own one-second block
   (``:549-596`` sorts and de-duplicates block start times), and its garbage ``Time_in_seconds``
   makes a negative inter-arrival for itself or its successor, which the ``'S'`` gate reads as
   shattering (``:726-730`` has no probetype-1 rollback).

**What this module does.**  It rewrites a proc file so that its particle clock is what the
instrument meant, and nothing else:

* **Classification.**  A particle is *out of sequence* when its ``particle_time`` is not a valid
  HHMMSS, or is not a member of the longest non-decreasing subsequence of the (valid) particle
  clock -- i.e. the smallest set of particles whose removal makes the clock monotone.  A genuine
  midnight crossing is first unwrapped with the **developers' own crossover test** from v3.5
  (``sizeDist.m:796-797``, Joe Finlon 02/13/19: previous value ``> 230000`` and a drop
  ``> 230000``), so a real day boundary is never mistaken for a glitch.
* **Recovery.**  An out-of-sequence particle is *recoverable* when the in-sequence particles on
  either side of it (in stream order) read the **same second**: the stream is time-ordered, so
  its true second is that second -- which is the only resolution ``sizeDist`` files at.  Its
  ``particle_time`` is set to that HHMMSS, and its ``Time_in_seconds`` is placed evenly between
  its two neighbours' so the inter-arrival gaps it creates sum to the true gap.  **The sub-second
  position is an estimate, not a recovery** -- it reaches only the ``'S'`` gate, through those two
  gaps.  ``particle_millisec`` / ``particle_microsec`` are left as written (``sizeDist`` does not
  read them for filing).
* **Unrecoverable.**  When the neighbours straddle a second boundary (or the particle has no
  in-sequence neighbour on one side), the header carries no information that places it in one
  second rather than another.  Such a particle is **dropped** from every ``time``-dimensioned
  variable, and the count is reported by cause.  Nothing else is dropped.

**Two policies, and what each one assumes** (2026-09-18).  The recovery above assumes the
stream is time-ordered, so a glitched particle bracketed by two in-sequence particles reading the
same second belongs in that second.  That is an inference about what the header *meant*, and it is
only sound once the corruption's origin is known -- a mis-decoded clock word can be recovered that
way, a particle that was never really there cannot.  So the module offers both, and the caller
picks:

* ``policy="repair"`` (the default, unchanged): recover where the brackets agree, drop the rest.
* ``policy="drop"``: **recover nothing.**  Every particle not on the longest non-decreasing
  subsequence is dropped -- the smallest set whose removal makes the clock monotone.  No value is
  invented and no sub-second position is estimated; the cost is the dropped particles themselves.

``policy="drop"`` is the safe choice while the corruption is still unexplained, and it is the one
that composes with an unmodified engine: the surviving clock is non-decreasing **by construction**,
so ``np.diff(x) < 0`` is empty and no version's rollover -- v3.1.4's ``:544-545``, v3.5's
``fix_multiday_particle_times`` -- has anything to fire on.

**Dropping only the syntactically invalid values is not enough** (measured 2026-09-18 on
2016-09-06 session 2, v3.5 lane).  347 of 3,797,537 ``particle_time`` values fail
:func:`hhmmss_is_valid`; dropping exactly those still leaves 839 decreases, v3.5's crossover test
still fires, and stage 4 still serves only 2,161 of 5,697 seconds.  The reason is that the CIP
clock is re-based by ``+24570`` s before ``sizeDist`` sees it, and a glitch that is a *valid*
HHMMSS on the raw clock can cross the ``> 230000`` threshold once shifted (the all-ones ``316363``
becomes ``385333`` -- ``38:53:33``, minutes and seconds both legal).  Dropping all 1,622
out-of-sequence particles (0.043 %) is what removes the cascade; that is what ``policy="drop"``
does.  **The pre-pass therefore belongs before any clock re-basing**, on the clock in the encoding
the probe wrote.

After this the particle clock has no decrease that is not a genuine midnight crossing, so
``:544-545`` fires only where it was meant to and the cascade cannot happen.  The port itself
(``arrayprobe.sizedist``) is untouched: a caller runs the unmodified S4 on the corrected proc.

**Relation to the other time corrections.**  ``rollover_fix`` (A5) corrects the *opposite*
failure -- a flight crossing midnight more than once, where the source corrects only the first
decrease -- and applying it to a glitched CIP clock would make things far worse (+240000 per
glitch).  Its own docstring names this gap ("it does not distinguish a midnight crossing from a
clock glitch").  ``int_arr_rollback_fix`` (D3c) repairs ``Time_in_seconds`` clock *rollbacks*
for the inter-arrival, not the filing clock.  This module is the missing third piece; it composes
with both because it removes glitches before either looks for a decrease.

**v3.5.**  The developers met the cascade themselves (``sizeDist.m:787-806``, Joe Finlon
02/13/19, "ignore corrupt particle boundary times"): with more than one decrease, v3.5 shifts
only after the first decrease that passes their day-crossover test.  This module uses that
test to tell a crossover from a glitch -- but on the **local medians** either
side of a decrease, because on single values one glitch passes it: an all-ones header reads
``316363 > 230000`` and drops by more than 230000 to the running clock.  Measured on 2016-09-06
session 2 with ``arrayprobe_uiops.sizedist.fix_multiday_particle_times``: 232 of the 1,045
decreases pass the single-value test, and v3.5 shifts 2,886,521 particles from particle 910,043
(09:56:31 UT) on -- the same cascade, 28 s later.  A file with exactly one glitch cascades on
v3.5 too (``:787-789`` shifts on a single decrease unconditionally), and no version removes the
glitched particles from the block table (half 2).  So the module APPLIES on both engines.

**What it found on 2016-09-06 (measured).**  Session 1: nothing (0 decreases).
Session 2: 1,587 of 3,796,565 particles out of sequence (335 invalid HHMMSS, 1,252 valid but out of
sequence), 1,319 recovered, **268 dropped** -- every one straddling a second boundary, where
neither the header (its millisecond field lies between its neighbours' in only 381 of the 1,319
recovered particles, so it is corrupted with the time word) nor the buffer's record time (0 of
268 resolved at the measured 1 s tolerance) can place it.  0 genuine crossovers.
"""

from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_right
from pathlib import Path

import netCDF4
import numpy as np

__all__ = [
    "CROSSOVER_PREV_MIN",
    "CROSSOVER_DROP_MIN",
    "hhmmss_is_valid",
    "hhmmss_to_seconds",
    "CROSSOVER_WINDOW",
    "POLICIES",
    "POLICY_DROP",
    "POLICY_REPAIR",
    "is_crossover",
    "crossover_indices",
    "longest_nondecreasing",
    "classify",
    "repair",
    "apply_policy",
    "port_cascade",
    "corrected_proc_file",
    "main",
]

#: Recover a glitched time from its in-sequence neighbours where they bracket one second, and drop
#: only what they cannot place.  The module's original and still-default behaviour.
POLICY_REPAIR = "repair"
#: Recover nothing; drop every out-of-sequence particle.  Invents no value and estimates no
#: sub-second position, so it needs no theory of what the corrupt header meant.
POLICY_DROP = "drop"
POLICIES = (POLICY_REPAIR, POLICY_DROP)

#: What each policy did, in one sentence, for the sidecar -- a silent repair is worse than the bug.
_POLICY_RULE = {
    POLICY_REPAIR:
        "out-of-sequence particles whose in-sequence neighbours read the same second take that "
        "second (particle_time), with Time_in_seconds spaced evenly between the neighbours; the "
        "rest are dropped",
    POLICY_DROP:
        "every particle not on the longest non-decreasing subsequence of the particle clock is "
        "dropped; no particle_time or Time_in_seconds value is altered",
}

#: The developers' own day-crossover test, v3.5 ``sizeDist.m:796-797``: a decrease is a real
#: midnight crossing only when the value before it is later than 23:00:00 and the drop exceeds
#: 23 hours in HHMMSS digits.  Taken from their fix, not re-invented.
CROSSOVER_PREV_MIN = 230000.0
CROSSOVER_DROP_MIN = 230000.0
#: Particles on each side of a decrease whose median the crossover test is applied to.  The
#: longest glitch run measured on 2016-09-06 is 25 particles; a run must be longer than half the
#: window to move a median.
CROSSOVER_WINDOW = 101

_TIME_VARS = ("particle_time", "Time_in_seconds")
_BLOCK = 16_384


def hhmmss_is_valid(x) -> np.ndarray:
    """True where ``x`` is a non-negative integer HHMMSS with minutes and seconds below 60.

    Hours are not capped at 23: a probe clock that counts from its own zero may legitimately
    pass 24 h of clock time only in a > 24 h file, and the crossover handling covers that case.
    ``316363`` (31:63:63, every field all-ones) is the measured glitch this rejects.
    """
    v = np.asarray(x, dtype=np.float64).ravel()
    ok = np.isfinite(v) & (v >= 0) & (v == np.floor(v))
    iv = np.where(ok, v, 0).astype(np.int64)
    return ok & ((iv // 100) % 100 < 60) & (iv % 100 < 60)


def hhmmss_to_seconds(x) -> np.ndarray:
    """HHMMSS digits to seconds, all three terms floored (integer HHMMSS in, integer seconds out)."""
    iv = np.floor(np.asarray(x, dtype=np.float64).ravel()).astype(np.int64)
    return (iv // 10000) * 3600 + ((iv // 100) % 100) * 60 + iv % 100


def is_crossover(prev_hhmmss: float, next_hhmmss: float) -> bool:
    """v3.5 ``sizeDist.m:796-797``: is the step ``prev -> next`` a genuine day crossover?"""
    return bool(prev_hhmmss > CROSSOVER_PREV_MIN and prev_hhmmss - next_hhmmss > CROSSOVER_DROP_MIN)


def longest_nondecreasing(values) -> np.ndarray:
    """Boolean mask of one longest non-decreasing subsequence of ``values``.

    Patience sorting, O(n log n); ``bisect_right`` makes equal values extend a run (the clock is
    non-decreasing, not increasing: many particles share a second).  Among equally long
    subsequences the one ending at the latest element is kept, and each element's predecessor is
    the latest tail it extended -- deterministic, and for isolated glitches the answer is unique.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    n = v.size
    keep = np.zeros(n, dtype=bool)
    if n == 0:
        return keep
    tails: list[float] = []       # smallest possible tail value of a run of each length
    tail_idx: list[int] = []      # index of that tail element
    prev = np.full(n, -1, dtype=np.int64)
    vl = v.tolist()
    for i, x in enumerate(vl):
        k = bisect_right(tails, x)
        if k:
            prev[i] = tail_idx[k - 1]
        if k == len(tails):
            tails.append(x)
            tail_idx.append(i)
        else:
            tails[k] = x
            tail_idx[k] = i
    j = tail_idx[-1]
    while j >= 0:
        keep[j] = True
        j = int(prev[j])
    return keep


def crossover_indices(vals, window: int = CROSSOVER_WINDOW) -> np.ndarray:
    """0-based positions ``d`` where ``vals[d] -> vals[d+1]`` is a genuine day crossover.

    The developers' test (:func:`is_crossover`) applied to the **local medians** of the
    ``window`` values before and after each decrease, not to the two single values.  Applied to
    single values it is fooled by one glitch: on 2016-09-06 session 2, 232 decreases pass it,
    the first being the all-ones ``316363`` header at particle 910,043, so v3.5's own
    ``sizeDist.m:796-799`` shifts 2,886,521 particles by 240000 there (measured with
    ``arrayprobe_uiops.sizedist.fix_multiday_particle_times``).  A glitch run shorter than half
    the window cannot move a median; a real crossover moves both.  Candidates within one window
    of a confirmed crossover are the same crossover and are not counted twice.
    """
    v = np.asarray(vals, dtype=np.float64).ravel()
    out: list[int] = []
    for d in np.flatnonzero(np.diff(v) < 0):
        if out and d - out[-1] < window:
            continue
        before = float(np.median(v[max(0, d - window + 1):d + 1]))
        after = float(np.median(v[d + 1:d + 1 + window]))
        if is_crossover(before, after):
            out.append(int(d))
    return np.asarray(out, dtype=np.int64)


def _unwrapped_seconds(pt: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, int]:
    """Seconds of the valid particles, with +86400 after each genuine crossover.

    Only *valid* particles are compared (:func:`crossover_indices`), so an invalid header can
    neither create nor hide a crossover.  Returns ``(seconds, crossovers)``, ``seconds`` NaN
    where the time is invalid.
    """
    sec = np.full(pt.size, np.nan)
    vi = np.flatnonzero(valid)
    if vi.size == 0:
        return sec, 0
    vals = pt[vi]
    steps = np.zeros(vi.size)
    cross = crossover_indices(vals)
    for d in cross:
        steps[d + 1:] += 86400.0
    sec[vi] = hhmmss_to_seconds(vals) + steps
    return sec, int(cross.size)


def classify(particle_time) -> dict:
    """Classify every particle of one proc file's clock.  Changes nothing.

    Returns arrays (``cause``: 0 in sequence, 1 invalid HHMMSS, 2 out of sequence;
    ``recoverable``; ``repaired_hhmmss`` -- the in-sequence neighbour's value, NaN where not
    recoverable; ``prev_good``/``next_good`` indices, -1 where absent) and counts.
    """
    pt = np.asarray(particle_time, dtype=np.float64).ravel()
    n = pt.size
    valid = hhmmss_is_valid(pt)
    sec, crossovers = _unwrapped_seconds(pt, valid)
    good = np.zeros(n, dtype=bool)
    vi = np.flatnonzero(valid)
    if vi.size:
        good[vi[longest_nondecreasing(sec[vi])]] = True
    cause = np.where(good, 0, np.where(valid, 2, 1)).astype(np.int8)

    gi = np.flatnonzero(good)
    idx = np.arange(n)
    if gi.size:
        k = np.searchsorted(gi, idx, side="left")       # first good index >= i
        nxt = np.where(k < gi.size, gi[np.minimum(k, gi.size - 1)], -1)
        prv = np.where(k > 0, gi[np.maximum(k - 1, 0)], -1)
        # for a good particle, its own index is both; only the bad ones are read below
    else:
        nxt = np.full(n, -1)
        prv = np.full(n, -1)
    bad = ~good
    both = bad & (prv >= 0) & (nxt >= 0)
    same = np.zeros(n, dtype=bool)
    same[both] = sec[prv[both]] == sec[nxt[both]]
    recoverable = bad & same
    repaired = np.full(n, np.nan)
    repaired[recoverable] = pt[prv[recoverable]]
    unrec = bad & ~same
    edge = unrec & ((prv < 0) | (nxt < 0))
    span = np.full(n, np.nan)
    span[both & ~same] = sec[nxt[both & ~same]] - sec[prv[both & ~same]]
    return {
        "n": int(n),
        "cause": cause,
        "good": good,
        "recoverable": recoverable,
        "repaired_hhmmss": repaired,
        "prev_good": prv,
        "next_good": nxt,
        "bracket_span_s": span,
        "counts": {
            "particles": int(n),
            "in_sequence": int(good.sum()),
            "invalid_hhmmss": int((cause == 1).sum()),
            "out_of_sequence_valid": int((cause == 2).sum()),
            "recovered": int(recoverable.sum()),
            "recovered_invalid_hhmmss": int((recoverable & (cause == 1)).sum()),
            "recovered_out_of_sequence": int((recoverable & (cause == 2)).sum()),
            "dropped_unrecoverable": int(unrec.sum()),
            "dropped_straddles_second": int((unrec & ~edge).sum()),
            "dropped_no_neighbour": int(edge.sum()),
            "dropped_invalid_hhmmss": int((unrec & (cause == 1)).sum()),
            "dropped_out_of_sequence": int((unrec & (cause == 2)).sum()),
            "genuine_crossovers": int(crossovers),
            "decreases_before": int((np.diff(pt) < 0).sum()) if n > 1 else 0,
        },
    }


def repair(particle_time, time_in_seconds, cls: dict | None = None) -> dict:
    """Apply :func:`classify`'s verdict to the two clock columns ``sizeDist`` reads.

    Returns ``keep`` (particles written), the repaired ``particle_time`` and ``Time_in_seconds``
    over **all** particles (the caller subsets with ``keep``), and the classification.
    ``Time_in_seconds`` of a run of recovered particles between in-sequence neighbours ``p`` and
    ``q`` is spaced evenly in ``(T[p], T[q])`` -- an estimate of the sub-second position (see the
    module docstring); the second it falls in is exact.
    """
    pt = np.asarray(particle_time, dtype=np.float64).ravel().copy()
    tis = np.asarray(time_in_seconds, dtype=np.float64).ravel().copy()
    c = classify(pt) if cls is None else cls
    rec = c["recoverable"]
    pt[rec] = c["repaired_hhmmss"][rec]
    ri = np.flatnonzero(rec)
    if ri.size:
        p, q = c["prev_good"][ri], c["next_good"][ri]
        # runs: consecutive recovered particles sharing one (p, q) bracket
        new_run = np.r_[True, (p[1:] != p[:-1]) | (q[1:] != q[:-1])]
        run_id = np.cumsum(new_run) - 1
        run_start = np.flatnonzero(new_run)
        pos = np.arange(ri.size) - run_start[run_id] + 1           # 1..k within the run
        run_len = np.bincount(run_id)[run_id]
        tis[ri] = tis[p] + (tis[q] - tis[p]) * pos / (run_len + 1)
    keep = c["good"] | rec
    return {"keep": keep, "particle_time": pt, "Time_in_seconds": tis, "classification": c}


def apply_policy(particle_time, time_in_seconds, policy: str = POLICY_REPAIR,
                 cls: dict | None = None) -> dict:
    """:func:`classify`'s verdict acted on under ``policy`` -- see the module docstring.

    Returns what :func:`repair` returns (``keep``, ``particle_time``, ``Time_in_seconds``,
    ``classification``) plus ``policy`` and ``applied``.  ``applied`` is what the policy **did**,
    counted from the masks rather than from the classifier's verdict: ``recovered`` in ``counts``
    says how many particles *could* be recovered, and under ``policy="drop"`` none of them is --
    so a sidecar carrying only ``counts`` would read as a repair that never happened.
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}: expected one of {POLICIES}")
    pt = np.asarray(particle_time, dtype=np.float64).ravel()
    c = classify(pt) if cls is None else cls
    if policy == POLICY_DROP:
        out = {"keep": c["good"].copy(), "particle_time": pt.copy(),
               "Time_in_seconds": np.asarray(time_in_seconds, dtype=np.float64).ravel().copy(),
               "classification": c}
    else:
        out = repair(pt, time_in_seconds, c)
    keep = out["keep"]
    changed = int(np.count_nonzero(out["particle_time"][keep] != pt[keep]))
    out["policy"] = policy
    out["applied"] = {
        "policy": policy,
        "repaired": changed,
        "dropped": int(pt.size - keep.sum()),
        "kept": int(keep.sum()),
        "rule": _POLICY_RULE[policy],
    }
    return out


def port_cascade(particle_time) -> dict:
    """What ``sizeDist.m:544-545`` does to this clock, as the port reproduces it.

    ``shifted`` is the number of particles after the first decrease -- every one of them is moved
    24 h by the first-decrease rollover.  Read-only; used for the before/after of the A/B.
    """
    pt = np.asarray(particle_time, dtype=np.float64).ravel()
    d = np.flatnonzero(np.diff(pt) < 0)
    first = int(d[0]) + 1 if d.size else -1
    return {"decreases": int(d.size), "first_decrease_index": first,
            "shifted": int(pt.size - first) if d.size else 0}


def corrected_proc_file(src, dst, probetype: int = 1, policy: str = POLICY_REPAIR) -> dict:
    """Write ``dst``: ``src`` with its glitched particle clock corrected under ``policy``.

    ``policy="repair"`` (default) recovers what the neighbours place and drops the rest;
    ``policy="drop"`` drops every out-of-sequence particle and alters no value -- module docstring.

    Refuses any probetype but 1 -- probetype 0/2/3 file on the record ``Time``, not the particle
    header clock (``sizeDist.m:515-537``), so the defect this corrects does not reach them.  Every
    variable not on the ``time`` dimension is copied verbatim; every ``time`` variable is subset
    with the same mask; only ``particle_time`` and ``Time_in_seconds`` change value, and under
    ``policy="drop"`` not even those.  ``src`` is never modified.  Returns the report: the
    classifier's ``counts``, what the policy ``applied``, and the port's cascade before and after.
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}: expected one of {POLICIES}")
    if probetype != 1:
        raise ValueError(f"particle_time_glitch_fix applies to probetype 1 only (got {probetype}): "
                         "other probetypes file particles on the record Time (sizeDist.m:515-537)")
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        raise ValueError("corrected_proc_file: dst must differ from src")
    with netCDF4.Dataset(src) as ds_in:
        ds_in.set_auto_mask(False)
        pt = np.asarray(ds_in["particle_time"][:], dtype=np.float64).ravel()
        tis = np.asarray(ds_in["Time_in_seconds"][:], dtype=np.float64).ravel()
        r = apply_policy(pt, tis, policy)
        keep = r["keep"]
        pdim = ds_in["particle_time"].dimensions[0]
        fmt = ds_in.file_format
        with netCDF4.Dataset(dst, "w", format=fmt) as ds_out:
            # Fill off: every cell is written below, so pre-filling only doubles the I/O.
            ds_out.set_fill_off()
            ds_out.setncatts({k: ds_in.getncattr(k) for k in ds_in.ncattrs()})
            for name, dim in ds_in.dimensions.items():
                ds_out.createDimension(name, None if dim.isunlimited() else len(dim))
            rec_vars = []
            for name, var in ds_in.variables.items():
                var.set_auto_mask(False)
                attrs = {k: var.getncattr(k) for k in var.ncattrs() if k != "_FillValue"}
                out = ds_out.createVariable(
                    name, var.dtype, var.dimensions,
                    fill_value=(var.getncattr("_FillValue")
                                if "_FillValue" in var.ncattrs() else None))
                out.setncatts(attrs)
                out.set_auto_mask(False)
                if not var.size:
                    continue
                if var.dimensions and var.dimensions[0] == pdim:
                    rec_vars.append(name)
                else:
                    out[:] = np.asarray(var[:])
            # Record variables go out in blocks of particles, every variable per block, so the
            # file is written in record order. Variable-at-a-time writes of a 3.8-million-record
            # NETCDF3 file stride the whole file once per variable (measured: > 10 min for the
            # first of 40 variables on the 1.25 GB CIP proc).
            o0 = 0
            for i0 in range(0, pt.size, _BLOCK):
                i1 = min(i0 + _BLOCK, pt.size)
                k = keep[i0:i1]
                o1 = o0 + int(k.sum())
                if o1 > o0:
                    for name in rec_vars:
                        var = ds_in.variables[name]
                        if name in _TIME_VARS:
                            data = r[name][i0:i1]
                        else:
                            data = np.asarray(var[i0:i1])
                        data = np.asarray(data).reshape((i1 - i0,) + var.shape[1:])[k]
                        ds_out.variables[name][o0:o1] = data.astype(var.dtype, copy=False)
                o0 = o1
            counts = r["classification"]["counts"]
            applied = r["applied"]
            ds_out.particle_time_glitch_fix = json.dumps(counts, sort_keys=True)
            # A separate attribute, not a key inside the one above: that one is the classifier's
            # verdict and a test reads it by key; this one is what was done to the file.
            ds_out.particle_time_glitch_fix_applied = json.dumps(applied, sort_keys=True)
    report = {
        "enhancement": "particle_time_glitch_fix",
        "source": str(src),
        "output": str(dst),
        "probetype": probetype,
        "policy": policy,
        "counts": counts,
        "applied": applied,
        "written": int(keep.sum()),
        "port_cascade_before": port_cascade(pt),
        "port_cascade_after": port_cascade(r["particle_time"][keep]),
    }
    Path(f"{dst}.particle_time_glitch_fix.json").write_text(
        json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    """``... particle_time_glitch_fix SRC DST [--probetype 1] [--policy repair|drop]``."""
    ap = argparse.ArgumentParser(prog="particle_time_glitch_fix", description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--probetype", type=int, default=1)
    ap.add_argument("--policy", choices=POLICIES, default=POLICY_REPAIR,
                    help="repair (default): recover a glitched time from its in-sequence "
                         "neighbours where they bracket one second, drop the rest.  drop: "
                         "recover nothing, drop every out-of-sequence particle.")
    a = ap.parse_args(argv)
    rep = corrected_proc_file(a.src, a.dst, a.probetype, a.policy)
    print(json.dumps({k: rep[k] for k in ("policy", "counts", "applied", "written",
                                          "port_cascade_before", "port_cascade_after")},
                     indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
