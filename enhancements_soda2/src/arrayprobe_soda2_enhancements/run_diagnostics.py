# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""Reporting-only diagnostics for silently-dropped frames/particles/buffers.

Covers all **four** findings the plan groups under this config key --
**S4-q** (a dropped frame or a whole-buffer rejection keeps no count),
**S5-c** (a particle whose time index lands exactly on ``numrecords``
is dropped without a message), **S6-b** (a probe-reported date
off by 1-5 days silently empties the run; beyond 5 days the driver
silently substitutes the file's own date instead) and **S6-d** (a
memory-limit flush that lands exactly on the last accepted buffer
returns ``None`` with no indication the accumulator already holds
sorted particles). S6-b/S6-d were deferred at stage 6 (see
``BACKLOG_STATUS.md``'s prior note) because they live inside
``soda2_process_2d.pro``'s ~550-line driver
(``src/arrayprobe_soda2/process_2d.py``); this module reaches them **without modifying the port**, by wrapping
:func:`arrayprobe_soda2.process_2d.soda2_process_2d` and, only when
needed, re-running the driver's own preamble (``update_op`` ->
``buildindex`` -> the date check -> the window arithmetic) on the
side -- the identical sequence the driver itself runs before the
per-buffer loop, `process_2d.py:404-548`.

Neither function here changes a number a caller already receives from
the port; every one calls the real, unmodified port function (which
still does everything it always did, including mutating its own
accumulator, or in S6-b/S6-d's case, still returns exactly the
``ProcessData``/``None`` it always would) and returns an *additional*
value alongside it. Opt-in since 2026-09-28, not one of
``registry.PROTECTIVE``: purely diagnostic, so there is no written
PBP/netCDF byte for it to protect.

``src/arrayprobe_soda2/process_2d.py``,
``processbuffer_spec.py`` and ``particlesort.py`` are never imported
for writing and never modified. Tests: ``tests/test_run_diagnostics.py``.

**What S6-b/S6-d's wrappers cannot observe** (recorded here, not
just in the plan): attributing a S6-d ``None`` return to a *specific*
buffer, or reporting how many particles were already flushed to disk
before the ``None`` -- both require the driver's own loop locals
(``istop``, the per-buffer index ``i``), which are not visible from
outside `soda2_process_2d`. The two functions below distinguish the
*two return sites* (`:550-551` vs `:632-636`), which is what the
finding's own suggested edit asks for; they do not go further.
"""
from __future__ import annotations

from typing import BinaryIO

import numpy as np
from arrayprobe_soda2.buildindex import buildindex
from arrayprobe_soda2.particlesort import (
    Accumulator,
    ParticlesortOptions,
    soda2_particlesort,
    spec_sort_locals,
)
from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d
from arrayprobe_soda2.processbuffer_spec import (
    NullBuffer,
    SpecBufferParticles,
    SpecMisc,
    SpecOp,
    process_spec_buffer,
)
from arrayprobe_soda2.timeconv import soda2_parsedate
from arrayprobe_soda2.update_op import update_op

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = [
    "spec_buffer_diagnostics",
    "particlesort_diagnostics",
    "driver_date_diagnostics",
    "run_with_return_diagnostics",
]


def spec_buffer_diagnostics(
    f: BinaryIO, buffer_time: float, op: SpecOp, misc: SpecMisc,
) -> tuple[SpecBufferParticles | NullBuffer, dict]:
    """S4-q: ``soda2_processbuffer.pro:296``'s per-frame drop (decode
    error, or a frame reaching 1000+ slices) and ``:339``'s
    whole-buffer rejection (kept lines exceeding 10 000) both keep no
    count. Calls the real, unmodified ``process_spec_buffer`` and
    returns ``(result, diagnostics)`` where ``diagnostics`` is::

        {"frames_in": int,          # misc.nimages before the call
         "frames_kept": int,        # 0 if the whole buffer was rejected
         "frames_dropped": int,     # frames_in - frames_kept
         "buffer_rejected": bool}   # True for either :267 or :339's NullBuffer

    ``:296``'s own ``continue`` is the per-image loop's *only*
    frame-skip path, so ``frames_in - result.num_images`` is exactly
    the S4-q count when the buffer itself is not rejected outright;
    when it is (``NullBuffer``), every input frame is counted as not
    kept -- this combines both of S4-q's conditions rather than
    distinguishing them, which the port's return value alone does not
    support without re-running its own per-frame loop a second time.
    """
    frames_in = misc.nimages
    result = process_spec_buffer(f, buffer_time, op, misc)
    if isinstance(result, NullBuffer):
        frames_kept = 0
        buffer_rejected = True
    else:
        frames_kept = result.num_images
        buffer_rejected = False
    return result, {
        "frames_in": frames_in,
        "frames_kept": frames_kept,
        "frames_dropped": frames_in - frames_kept,
        "buffer_rejected": buffer_rejected,
    }


def particlesort_diagnostics(
    op: ParticlesortOptions,
    x: dict[str, np.ndarray],
    d: Accumulator,
    reprocessed_time: np.ndarray | None = None,
) -> tuple[np.ndarray, int]:
    """S5-c: ``soda2_particlesort.pro:79-81``'s outer loop bound
    (``(max(timeindex)<d.numrecords)``, IDL's ``<`` is MIN) means a
    particle whose own ``timeindex`` lands exactly on ``d.numrecords``
    is silently skipped -- never accumulated into ``d``, never
    reported. Calls the real, unmodified ``soda2_particlesort`` (which
    still mutates ``d`` exactly as always) and returns
    ``(rejectionflag, dropped_at_numrecords)`` -- the count of
    particles whose own ``timeindex`` equalled ``d.numrecords``,
    re-derived with the identical formula the port itself uses at
    ``:60`` (truncation toward zero), never the accept/reject decision
    itself."""
    truetime, _interarrival = spec_sort_locals(x, reprocessed_time)
    timeindex = np.trunc((truetime - op.starttime) / op.rate).astype(np.int64)
    dropped_at_numrecords = int(np.count_nonzero(timeindex == d.numrecords))
    rejectionflag = soda2_particlesort(op, x, d, reprocessed_time)
    return rejectionflag, dropped_at_numrecords


def _resolved_fn_list(resolved_op: dict) -> list:
    """`process_2d.py:411-412`'s own normalisation, copied verbatim -- both
    S6-b and S6-d's re-run helpers need it before calling ``buildindex``."""
    fn = resolved_op["fn"]
    return list(fn) if isinstance(fn, (list, tuple)) else [fn]


def driver_date_diagnostics(op: dict) -> dict:
    """S6-b: ``process_2d.py:528-532``'s date-mismatch branch, observed
    **without modifying the port** by re-running the driver's own preamble
    up to that line -- ``update_op`` (`:404`) -> ``buildindex`` (`:515`,
    the same call, same import as the driver's own `.buildindex`) ->
    ``soda2_parsedate`` (`:472`) -- and then applying `:530`'s own test
    (``abs(buffdate[0]-startdate) > 5``) a second time, on the side. This
    never calls :func:`soda2_process_2d` itself, so the driver's per-buffer
    loop, its accumulator and its return value are untouched by calling
    this function.

    Returns::

        {"requested_julday": int,   # date.julday, :529
         "file_julday": int,        # buffdate[0], the file's own date
         "branch": "within_5_days" | "substituted",
         "startdate_used": int}     # :530-531's own startdate, whichever

    A mismatch of 1-5 days (``branch == "within_5_days"``) is the case the
    driver's own return value cannot distinguish from "no data in this
    window" -- both give ``None`` with no message.
    Beyond 5 days (``branch == "substituted"``) the driver silently
    adopts the file's date and succeeds, which this function also makes
    observable before the fact.
    """
    resolved = update_op(op)
    fn_list = _resolved_fn_list(resolved)
    y = buildindex(fn_list[0], resolved)
    buffdate = np.asarray(y.date, dtype=np.int64)

    date = soda2_parsedate(str(resolved["date"]))
    requested_julday = int(date.julday)
    file_julday = int(buffdate[0])
    if abs(file_julday - requested_julday) > 5:
        return {
            "requested_julday": requested_julday,
            "file_julday": file_julday,
            "branch": "substituted",
            "startdate_used": file_julday,
        }
    return {
        "requested_julday": requested_julday,
        "file_julday": file_julday,
        "branch": "within_5_days",
        "startdate_used": requested_julday,
    }


def _window_is_empty(op: dict) -> bool:
    """Re-runs ``process_2d.py:515-548`` (``buildindex`` through the
    ``firstbuff``/``lastbuff`` computation) verbatim on the side -- the
    same ``update_op`` -> ``buildindex`` -> date-substitution -> sort ->
    ``firstbuff``/``lastbuff`` sequence the driver itself runs, reusing
    :func:`driver_date_diagnostics`'s own date branch so the two never
    disagree. Only the boolean the `:550` test itself computes is
    returned; nothing here is written back to the driver."""
    resolved = update_op(op)
    fn_list = _resolved_fn_list(resolved)
    y = buildindex(fn_list[0], resolved)
    bufftime = np.asarray(y.bufftime, dtype=np.float64)
    buffdate = np.asarray(y.date, dtype=np.int64)

    date_diag = driver_date_diagnostics(resolved)
    startdate = date_diag["startdate_used"]
    bufftime = bufftime + 86400.0 * (buffdate - startdate)

    # `:419-423` -- sort (order does not change the *set* of values, but
    # matches the driver's own computation exactly, as the plan requires).
    order = np.argsort(bufftime, kind="stable")
    bufftime = bufftime[order]

    starttime = float(resolved["starttime"])
    stoptime = float(resolved["stoptime"])
    numbuffs = bufftime.size

    # `:427-429` -- trap 1 / S6-a, reproduced verbatim.
    lt_start = np.nonzero(bufftime < starttime)[0]
    firstbuff = max(int(lt_start.max()), 0) if lt_start.size else 0
    gt_stop = np.nonzero(bufftime > stoptime)[0]
    lastbuff = int(gt_stop.min()) if gt_stop.size else numbuffs - 1

    return (lastbuff - firstbuff) <= 0


def run_with_return_diagnostics(
    op: dict, **kw,
) -> tuple[ProcessData | None, dict]:
    """S6-d: ``process_2d.py:565-576``'s memory-limit flush can return
    ``None`` (`:632-636`, ``istop < 0``) even though the accumulator ``d``
    already holds every particle sorted before the flush -- indistinguishable,
    from the return value alone, from `:550-551`'s "no buffers in the
    requested window at all" return. Calls the real, unmodified
    :func:`soda2_process_2d` with ``op``/``**kw`` exactly as given; when
    (and only when) it returns ``None``, classifies which of the two
    ``return None`` sites fired by re-running the preamble a second time
    (:func:`_window_is_empty`) -- the driver's per-buffer loop, its
    accumulator and its actual return value are never touched or
    re-derived; only the classification is additional.

    Returns ``(result, diagnostics)`` where ``diagnostics`` is::

        {"returned": bool,          # result is not None
         "none_reason": None | "no_buffers_in_window" | "flush_left_nothing"}

    ``"no_buffers_in_window"`` is `:550-551` (``lastbuff - firstbuff <= 0``,
    S6-a); ``"flush_left_nothing"`` is `:632-636` (window non-empty, so the
    loop ran and the ``None`` can only have come from S6-d's own flush
    path). **Cannot** be done without modifying the port: attributing the
    ``flush_left_nothing`` case to a *specific* buffer or reporting the
    count of already-flushed particles, since both require the driver's
    own loop locals (see the module docstring)."""
    result = soda2_process_2d(op, **kw)
    if result is not None:
        return result, {"returned": True, "none_reason": None}
    none_reason = "no_buffers_in_window" if _window_is_empty(op) else "flush_left_nothing"
    return result, {"returned": False, "none_reason": none_reason}


register(EnhancementSpec(
    name="run_diagnostics",
    summary="spec_buffer_diagnostics (S4-q: frames dropped/buffer "
            "rejected, per buffer), particlesort_diagnostics (S5-c: "
            "particles dropped at itime==numrecords), "
            "driver_date_diagnostics (S6-b: date-mismatch branch, "
            "observed by re-running the driver's own preamble) and "
            "run_with_return_diagnostics (S6-d: classifies a None return "
            "as the empty-window or the flush-left-nothing site) -- "
            "reporting only, changes no written output.",
    finding="S4-q",
    reachability="flagged",
    entry_point="spec_buffer_diagnostics",
))
