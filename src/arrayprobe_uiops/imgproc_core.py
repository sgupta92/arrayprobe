# SPDX-License-Identifier: BSD-3-Clause
"""Shared leaf: the imgProc_sm time-base constants and pure helpers both engines use.

Moved verbatim from ``arrayprobe.imgproc``;
that module re-imports them, so its names still resolve.  Constants and pure
functions: no module state, no numba, nothing a worker pickles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from arrayprobe_uiops import ncio
from arrayprobe_uiops.matlab_compat import bin2dec, dec2bin_concat, mint8, mint16

#: ``imgProc_sm.m:365`` / ``:763``.  The true air speed assumed when none is
#: available, in m/s.
TAS_FALLBACK = 170.0

#: ``imgProc_sm.m:737`` / ``:752``.  A particle-to-particle time difference below
#: this many seconds is read as the 32-bit clock having wrapped, not as time
#: running backwards.
ROLLBACK_SECONDS = -250.0


class UnportedProbeType(NotImplementedError):
    """A probe whose framing and timing branch is out of the framing stage's scope."""


def _time_in_seconds_from_tas(part_time, ds, rec, tas, tas_time,
                              part_time_prev, time_in_seconds_prev):
    """``:724-778`` -- Joe Finlon's 2017-03-03 TAS-based accumulation."""
    # :726.  The image record's time in HHMMSS, used as the TAS lookup key.
    temp_time = (float(rec["hour"]) * 10000 + float(rec["minute"]) * 100
                 + float(rec["second"]))
    tas2d = tas[tas_time == temp_time]   # :727

    if part_time_prev is None:           # :761 -- first particle of the chunk
        if tas2d.size == 0:
            return part_time * (ds / 10 ** 3 / TAS_FALLBACK)     # :763
        return part_time * (ds / 10 ** 3 / _one(tas2d, temp_time))  # :765

    # :730.  MATLAB's `if isempty(tas2d) || isnan(tas2d)` requires every element
    # to be NaN when tas2d has more than one, because `if` on a vector is `all`.
    if tas2d.size == 0 or bool(np.all(np.isnan(tas2d))):
        speed = TAS_FALLBACK
    else:
        speed = _one(tas2d, temp_time)

    scale = ds / 10 ** 3 / speed
    time_diff = (part_time - part_time_prev) * scale   # :735 / :750
    if time_diff >= ROLLBACK_SECONDS:                  # :737 / :752
        return time_in_seconds_prev + time_diff
    # :740 / :755 -- the 32-bit clock wrapped.
    return time_in_seconds_prev + (2 ** 32 - 1 - part_time_prev + part_time) * scale


def _one(tas2d, temp_time):
    """A TAS lookup that matched more than once would be a vector in MATLAB.

    ``time_in_seconds(kk) = time_in_seconds_prev + timeDiff`` (:738) then assigns
    a vector into a scalar slot, which MATLAB rejects outright.  Raised here for
    the same reason rather than silently taking the first match.
    """
    if tas2d.size != 1:
        raise ValueError(
            f"imgProc_sm.m:727 matched {tas2d.size} TAS samples at time "
            f"{temp_time:.0f}; MATLAB then fails at :738 assigning a "
            "1x{n} vector into time_in_seconds(kk). The aircraft file must "
            "carry one sample per HHMMSS second."
        )
    return float(tas2d[0])


def _pecan_pip_hour_offset(rec, hour):
    """``:664-695`` -- PECAN's PIP flew on local time for part of the campaign.

    ``handles.month``/``handles.day``/``handles.hour`` are the IMAGE
    RECORD's own header fields (read once per record, unaffected by any
    particle-level offset), matching :func:`_read_record_header`'s ``rec``.
    Only the hour offset is ever non-zero in the source; minute/second
    offsets are declared but always 0, so they are not reproduced as
    separate no-op additions.
    """
    month, day = int(rec["month"]), int(rec["day"])
    if month == 6 and day == 17:
        return hour - 12
    if month == 6 and day == 20:
        return hour - 12 if rec["hour"] < 6 else hour
    if month == 7 and 6 <= day <= 13:
        return hour - 12
    return hour


@dataclass(frozen=True)
class VariableSpec:
    """One ``netcdf.defVar`` call, with the attributes that follow it.

    Source: one call in the ``netcdf.defVar`` block of ``imgProc_sm.m:241-448`` (UIOOPS v3.1.4).

    Definition *order* is part of the contract, not presentation: MATLAB assigns
    variable IDs in creation order and ``sizeDist`` reads some of them by ID.
    """

    name: str
    xtype: str
    dims: tuple[str, ...]
    units: str = ""
    description: str = ""
    attrs: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def _read_record_header(src, i):
    """``:206-212`` -- the seven per-record time fields, at 0-based ``i-1``."""
    names = ("year", "month", "day", "hour", "minute", "second", "millisec")
    return {
        name: float(np.ravel(
            ncio.get_var(src, ncio.inq_var_id(src, name), i - 1, 1)
        )[0])
        for name in names
    }


def _particle_time_pms(acc, kk, data, header_loc, src, i, cfg, ind_matrix):  # noqa: N803
    """``:580-587`` -- the probetype-0 (2DC/2DP) half of F9.

    Validated against a hand-built synthetic oracle
    (``octave_oracle/run_s7c_2dc_bank.py`` -> ``tests/data/s7c_2dc_octave_golden.nc``),
    bit-exact on the first run.

    ``:582-585``.  The 24-bit TAS-clock particle time lives at
    ``data(header_loc, 2:4)`` (MATLAB 1-based) -- the row immediately after
    the boundary word, whose first byte the boundary-companion check
    (``cfg.boundary_needs_time``) already required to equal ``boundarytime``.
    ``tas2d`` is this image RECORD's own ``tas`` field (read fresh per
    particle, matching the source, which re-reads it inside the per-particle
    loop even though every particle in a record shares the same value).
    """
    h = header_loc - 1  # MATLAB 1-based row -> Python row index.
    bin_convert = dec2bin_concat(data[h:h + 1, 1:4], 8)     # :582
    tas_clock = bin2dec(bin_convert)                        # :583
    tas2d = float(np.ravel(
        ncio.get_var(src, ncio.inq_var_id(src, "tas"), i - 1, 1)
    )[0])                                                    # :584
    # :585.  IEEE division, not Python's: a record whose ``tas`` is 0 gives Inf
    # (NaN for a zero clock) in MATLAB, where a float ``/`` raised.
    with np.errstate(divide="ignore", invalid="ignore"):
        part_time = float(np.float64(tas_clock) / np.float64(tas2d) * cfg.ds / 1e3)

    acc.int_arrival[kk] = part_time                         # :586
    acc.time_in_seconds[kk] = part_time                     # :587

    # :628-629.  Only meaningful for kk>1; harmless to compute unconditionally
    # since kk==1 never reads it (see _pms_time_accumulate).
    with np.errstate(invalid="ignore"):
        frac_time = (part_time - np.floor(part_time)) * 1000
    _pms_time_accumulate(acc, kk, ind_matrix, part_time, frac_time, src, i)


def _particle_time_fast2dc(acc, kk, data, header_loc, src, i, ind_matrix):  # noqa: N803
    """``:588-599`` -- the probetype-3 (Fast2DC) half of F9.

    **A real, previously-undocumented-by-this-project fact, found only by
    running this and comparing against the oracle**: Fast2DC is NOT the
    self-contained branch its own `:594-598` if/else suggests. The shared
    ``firstpart``/accumulate cascade at ``:601-652`` (see
    :func:`_pms_time_accumulate`) applies to probetype 3 exactly as it does
    to probetype 0 -- it lives OUTSIDE the ``if probetype==0 ...
    elseif probetype==3`` sub-block, inside the OUTER
    ``if probetype==0||probetype==3`` one. So Fast2DC particles ALSO seed
    from the record header's int8-typed ``hour``/``minute``/``second``
    fields and are subject to the same saturating ``particle_time`` write
    (A15) -- confirmed against a synthetic oracle
    (``octave_oracle/run_s7e_f2dc_bank.py`` ->
    ``tests/data/s7e_f2dc_octave_golden.nc``), not assumed.

    ``:588-592``.  The 40-bit free-running 12 MHz clock lives at
    ``data(header_loc-1, 4:8)`` (MATLAB 1-based) -- the SAME row as the
    boundary word itself (Fast2DC has no separate boundary-companion row;
    ``cfg.boundary_needs_time`` is ``False``), not the row after it the way
    probetype 0's does.
    """
    h = header_loc - 2  # data(header_loc-1, ...) MATLAB 1-based -> Python row.
    bin_convert = dec2bin_concat(data[h:h + 1, 3:8], 8)     # :589-590
    clock_count = bin2dec(bin_convert)                      # :591
    part_time = clock_count / 12 / 1e6                      # :591-592

    acc.time_in_seconds[kk] = part_time                     # :593
    if kk > 1:                                              # :594-598
        time_diff = part_time - acc.time_in_seconds[kk - 1]
        acc.int_arrival[kk] = time_diff
        frac_time = 1000 * (time_diff - np.floor(time_diff))  # :630-632
    else:
        acc.int_arrival[kk] = 0.0
        frac_time = 0.0  # unused: kk==1 never reads it below.

    _pms_time_accumulate(acc, kk, ind_matrix, part_time, frac_time, src, i)


def _pms_time_accumulate(acc, kk, ind_matrix, part_time, frac_time, src, i):
    """``:601-652`` -- shared between probetype 0 and 3.

    ``part_time`` feeds ``part_sec``'s accumulation (``:636``) directly and
    UNCONDITIONALLY in both cases, even though ``frac_time`` (used only when
    ``kk>1``) is computed differently per probetype by the two callers.
    """
    acc.particle_sliceCount[kk] = float(ind_matrix.shape[0])   # :601
    acc.particle_DOF[kk] = float(np.ravel(
        ncio.get_var(src, ncio.inq_var_id(src, "wkday"), i - 1, 1)
    )[0])                                                        # :602

    if kk == 1:  # :604-625.  `firstpart` and `kk==1` coincide -- both reset
                 # only at a record boundary, and firstpart is cleared the
                 # moment the first particle in a record reaches this branch.
        acc.part_hour[kk] = float(np.ravel(
            ncio.get_var(src, ncio.inq_var_id(src, "hour"), i - 1, 1))[0])
        acc.part_min[kk] = float(np.ravel(
            ncio.get_var(src, ncio.inq_var_id(src, "minute"), i - 1, 1))[0])
        acc.part_sec[kk] = float(np.ravel(
            ncio.get_var(src, ncio.inq_var_id(src, "second"), i - 1, 1))[0])
        acc.part_mil[kk] = float(np.ravel(
            ncio.get_var(src, ncio.inq_var_id(src, "millisec"), i - 1, 1))[0])
        acc.part_micro[kk] = 0.0
    else:                                                    # :627-638
        # The seed above fixes the classes: part_hour/part_min/part_sec are
        # int8 and part_mil int16, the header variables' own types (the same
        # fact _particle_time_write rests on), while part_micro starts from a
        # double 0. So each sum is rounded and saturated as it is stored: a
        # tas of 0 makes part_time Inf, part_sec saturates at 127 and part_mil,
        # fed NaN, becomes 0.
        with np.errstate(invalid="ignore"):
            acc.part_micro[kk] = (acc.part_micro[kk - 1]
                                  + (frac_time - np.floor(frac_time)) * 1000)
            acc.part_mil[kk] = float(mint16(acc.part_mil[kk - 1] + np.floor(frac_time)))
            acc.part_sec[kk] = float(mint8(acc.part_sec[kk - 1] + np.floor(part_time)))
        acc.part_min[kk] = acc.part_min[kk - 1]
        acc.part_hour[kk] = acc.part_hour[kk - 1]

    _pms_carry(acc, kk)


def _pms_carry(acc, kk):
    """``:641-652`` (v3.5 ``:922-933``) -- the carry fix-up, applied to the
    WHOLE vector ``1..kk`` at every particle, in the integer classes above.

    Each line is a masked whole-vector assignment, so a particle that one pass
    leaves at 60 or more -- ``part_sec`` saturated at 127 comes out at 67 -- is
    carried again by the next particle's pass. The masks are recomputed line by
    line, in the source's order."""
    micro = np.asarray(acc.part_micro[1:kk], dtype=np.float64).copy()
    mil = np.asarray(acc.part_mil[1:kk], dtype=np.float64).copy()
    sec = np.asarray(acc.part_sec[1:kk], dtype=np.float64).copy()
    mnt = np.asarray(acc.part_min[1:kk], dtype=np.float64).copy()
    hour = np.asarray(acc.part_hour[1:kk], dtype=np.float64).copy()
    m = micro >= 1000                                        # :641-642
    mil[m] = mint16(mil[m] + 1)
    micro[m] = micro[m] - 1000
    m = mil >= 1000                                          # :644-645
    sec[m] = mint8(sec[m] + 1)
    mil[m] = mint16(mil[m] - 1000)
    m = sec >= 60                                            # :647-648
    mnt[m] = mint8(mnt[m] + 1)
    sec[m] = mint8(sec[m] - 60)
    m = mnt >= 60                                            # :650-651
    hour[m] = mint8(hour[m] + 1)
    mnt[m] = mint8(mnt[m] - 60)
    m = hour >= 24                                           # :652
    hour[m] = mint8(hour[m] - 24)
    acc.part_micro[1:kk] = micro
    acc.part_mil[1:kk] = mil
    acc.part_sec[1:kk] = sec
    acc.part_min[1:kk] = mnt
    acc.part_hour[1:kk] = hour
