# SPDX-License-Identifier: BSD-3-Clause
"""The interarrival closure check -- McFarquhar et al. (2017) ch. 11 p. 11.20.

The community review states the check directly: *"checks should ensure that the sum of
particle interarrival times matches the record time."* This module is diagnostic-only --
it reads output, computes a comparison, and reports it; it changes no computed number, so
per this project's own doctrine (speed work aside, anything that "changes no computed
number" belongs beside :mod:`arrayprobe.compare` and :mod:`arrayprobe.triage_server`, not
in ``enhancements_uiops/``) it lives here, in the core port.

**What "the sum of particle interarrival times" actually is, for probetype 2 (2D-S /
HVPS).** ``imgProc_sm.m``'s ``inter_arrival`` variable is ``diff(Time_in_seconds)`` between
consecutive particles in the *whole file* (:func:`arrayprobe.imgproc._particle_time_probetype2`,
``:955-957``); ``Time_in_seconds`` is itself built from the probe's own 32-bit particle-frame
clock count, scaled to seconds by diode pitch and airspeed. Summing every particle's
``inter_arrival`` over a whole proc file therefore **telescopes exactly** to
``Time_in_seconds[-1] - Time_in_seconds[0]`` by construction -- that identity holds no matter
what the port or the original MATLAB does, so it is not the check McFarquhar means, and this
module does not offer it as one.

**The check that is actually informative** compares that particle-clock-derived span against
an *independent* measurement of the same interval: the raw file's own per-record housekeeping
timestamp (``hour``/``minute``/``second``/``millisec``, decoded by :mod:`arrayprobe.readers.spec`
onto every S2 record, the probe's sibling manuals confirm this
is the manufacturer's own wall-clock field, not derived from the particle clock at all). If the
probe's particle-timing clock and its separate housekeeping clock agree, the two spans should
match; if they diverge, that is evidence about clock integration, TAS scaling, or record
continuity that neither span alone would show.

**No published tolerance exists for how close is close enough** -- McFarquhar et al. (2017)
states the check, not a number, and this module does not invent one. :func:`check_closure`
reports the two spans, their difference and their ratio; interpreting whether a given
divergence is instrument noise, a TAS-scaling assumption, or something to escalate is left to
the caller, the way :mod:`arrayprobe.compare` reports tolerance-classed differences without
issuing a single pass/fail verdict.

**Scope: probetype 2 only.** ``inter_arrival``'s own attribute already says the
``diff(time_in_seconds)`` convention is for "all but 2DC/2DP" (probetype 2's dedicated
convention), and 2DC/2DP populate ``inter_arrival`` a different way
(:func:`arrayprobe.imgproc`, the ``probetype in (0, 1, 3)`` branches). Extending this check to
those probes needs its own reading of their convention; not done here.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from . import ncio

__all__ = ["ClosureResult", "check_closure"]


def _wallclock_seconds(hour: float, minute: float, second: float, millisec: float) -> float:
    """Seconds since local midnight, from the four housekeeping fields."""
    return hour * 3600.0 + minute * 60.0 + second + millisec / 1000.0


@dataclasses.dataclass(frozen=True)
class ClosureResult:
    """The two independent measurements of one file's time span, and their disagreement.

    Neither field is a verdict. ``ratio`` near 1.0 is closer agreement; how far from 1.0
    is acceptable is not defined by the source this check implements, and is not defined
    here either.
    """

    #: ``Time_in_seconds[-1] - Time_in_seconds[0]`` from the proc file: the span implied
    #: by the probe's own particle-frame clock, integrated across every particle.
    particle_clock_span_s: float
    #: The wall-clock span between the decoded file's first and last record, from the
    #: housekeeping ``hour``/``minute``/``second``/``millisec`` fields -- independent of
    #: the particle clock entirely.
    record_clock_span_s: float
    #: ``particle_clock_span_s - record_clock_span_s``.
    difference_s: float
    #: ``particle_clock_span_s / record_clock_span_s``; ``nan`` if the record span is zero.
    ratio: float
    n_particles: int
    n_records: int


def check_closure(decoded_path: str, proc_path: str, *, day_rollover_h: float = 24.0
                   ) -> ClosureResult:
    """Compare a proc file's particle-clock time span against its decoded file's own
    record-clock time span (McFarquhar et al. 2017, p. 11.20).

    ``decoded_path`` is the decode stage's output (``.H.nc``/``.V.nc`` from engine 3.5)
    the particles in
    ``proc_path`` were framed from -- the caller is responsible for pairing them
    correctly; this function does not check that ``proc_path``'s ``parent_rec_num``
    range is consistent with ``decoded_path``'s record count, though a caller who wants
    that assurance can read both and compare.

    ``day_rollover_h`` corrects a single midnight crossing between the decoded file's
    first and last record (added once if the raw difference is negative). Two valid
    ``hour``/``minute``/``second``/``millisec`` readings are always less than 24h
    apart, so the default always suffices; the check that the correction actually
    fixed the sign exists so a caller who overrides ``day_rollover_h`` to something
    too small gets a clear error rather than a silently wrong, still-negative span.
    """
    hour = ncio.ncread(decoded_path, "hour").ravel().astype(np.float64)
    minute = ncio.ncread(decoded_path, "minute").ravel().astype(np.float64)
    second = ncio.ncread(decoded_path, "second").ravel().astype(np.float64)
    millisec = ncio.ncread(decoded_path, "millisec").ravel().astype(np.float64)
    n_records = hour.size
    if n_records < 2:
        raise ValueError(
            f"{decoded_path} has {n_records} record(s); need at least 2 for a time span")

    t0 = _wallclock_seconds(hour[0], minute[0], second[0], millisec[0])
    t1 = _wallclock_seconds(hour[-1], minute[-1], second[-1], millisec[-1])
    record_span = t1 - t0
    if record_span < 0:
        record_span += day_rollover_h * 3600.0
        if record_span < 0:
            raise ValueError(
                f"{decoded_path}: last record precedes first even after one "
                f"{day_rollover_h}h rollover correction -- day_rollover_h is too "
                "small for a real midnight crossing, or the two records are not "
                "in file order")

    time_in_seconds = ncio.ncread(proc_path, "Time_in_seconds").ravel().astype(np.float64)
    n_particles = time_in_seconds.size
    if n_particles < 2:
        raise ValueError(
            f"{proc_path} has {n_particles} particle(s); need at least 2 for a time span")

    particle_span = float(time_in_seconds[-1] - time_in_seconds[0])
    difference = particle_span - record_span
    ratio = particle_span / record_span if record_span else float("nan")

    return ClosureResult(
        particle_clock_span_s=particle_span,
        record_clock_span_s=record_span,
        difference_s=difference,
        ratio=ratio,
        n_particles=int(n_particles),
        n_records=int(n_records),
    )
