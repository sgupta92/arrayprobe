# SPDX-License-Identifier: BSD-3-Clause
"""``combine_sizedist.m`` -- stitch a flight's several ``sd`` files into one product.

Ported from: the ORACLES-variant ``combine_sizedist.m`` (the 2026-08-20 delivery)
Several things here look wrong
and are not.


This is the ONLY comparison in the project whose two sides are built from the same
inputs -- a raw flight's several files, combined -- as opposed to a per-file
comparison against a product that was itself built from all of a flight's files
(which is why per-file checks are indicative, never the acceptance gate).

"""

from __future__ import annotations

import datetime as _dt

import numpy as np

from . import ncio
from .matlab_compat import datenum, mint16

__all__ = ["combine_sizedist"]

#: :5-13's ``netcdf.getVar(ncid_k, N)`` calls, by variable NAME rather than the
#: bare index the MATLAB uses -- the combine stage's design rule: "read by name, assert
#: by index".  ``test_combine.py`` pins that these names still resolve to the
#: indices the MATLAB hard-codes, so a future S4 write-order change fails there
#: instead of silently combining the wrong columns.
_READ_VARS = (
    "time", "bin_min", "bin_max", "bin_mid", "bin_dD",
    "conc_minR", "conc_AreaR", "n", "Reject_ratio", "count", "mean_area_ratio",
)

#: :5-13 -> the MATLAB's own hard-coded ``netcdf.getVar(ncid, N)`` indices, for
#: the pinning test above.  Not used by :func:`combine_sizedist` itself.
MATLAB_VARID = {
    "time": 0, "bin_min": 1, "bin_max": 2, "bin_mid": 3, "bin_dD": 4,
    "conc_minR": 5, "conc_AreaR": 7, "n": 8, "Reject_ratio": 15,
    "count": 20, "mean_area_ratio": 21,
}

#: :101-107.  A SPEC clock can emit a seconds field of 60 (``HHMM60``); the
#: MATLAB rewrites the string's seconds field to '00' and adds a minute to the
#: datenum.  Implemented here directly on the integer HHMMSS field instead of
#: through MATLAB's num2str/datenum('HHMMSS') string round trip -- the design
#: doc S2 table measured that round trip as numerically clean (space- vs
#: zero-padding parses to the identical instant, diff 0.000000 s), so the
#: string detour has no effect the integer arithmetic below doesn't already
#: reproduce.
_ONE_MINUTE = 1.0 / 1440.0
_ONE_SECOND = 1.0 / 86400.0
#: :135.  ``abs(timevec_new - timevec(k)) < datenum(0,0,0,0,0,0.3)`` -- 0.3 s.
_SYNC_TOL_DAYS = 0.3 / 86400.0


def _read_one(path) -> dict:
    ds = ncio.open(str(path), "nowrite")
    try:
        return {name: ncio.get_var(ds, ncio.inq_var_id(ds, name)) for name in _READ_VARS}
    finally:
        ncio.close(ds)


def _time_of_day(hhmmss: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """HHMMSS integers -> (time-of-day in days, was-a-:60-second-field mask).

    The mask drives the :101-107 fixup: those rows get one more minute added
    to their datenum by the caller, after the date component is added in.
    """
    hh = np.floor_divide(hhmmss, 10000)
    mm = np.mod(np.floor_divide(hhmmss, 100), 100)
    ss = np.mod(hhmmss, 100)
    is_60 = ss == 60
    ss = np.where(is_60, 0, ss)
    tod = hh / 24.0 + mm / 1440.0 + ss / 86400.0
    return tod, is_60


def _timevec_matlab_replica(hhmmss: np.ndarray, year2: int, month: int, day: int,
                            current_year: int) -> np.ndarray:
    """:109-110's two-datenum-cancellation arithmetic, literally.

    ``datenum(time_1, 'HHMMSS')`` on a string with no date component is
    documented MATLAB/Octave behaviour that resolves to "January 1 of the
    year the code is RUN in, plus the time of day" (design doc S4, measured
    under Octave). ``current_year`` exists to cancel that run-year term, and
    the design doc's own finding is that nothing checks it -- a wrong value
    silently shifts every timestamp by whole years.  That
    dependency on the real-world calendar date at execution time is not a
    shortcut taken here: it is the bug being reproduced.  Use this only to
    reproduce a *specific* historical mis-set run for comparison;
    :func:`combine_sizedist`'s default (``current_year=None``) computes the
    intended axis directly and does not call this at all.
    """
    run_year = _dt.date.today().year
    tod, is_60 = _time_of_day(hhmmss)
    # :110's `datenum(current_year,0,1,0,0,0)` -- month 0, day 1. Empirically
    # verified under Octave (the project's only available interpreter -- no
    # MATLAB licence, ever) that this call clamps to January 1 of
    # `current_year` itself: `datenum(Y,0,1,...) == datenum(Y,1,1,...)`
    # exactly, numerically confirmed. The port's datenum() reproduces Octave's
    # month<1 -> 1 rule bit for bit (the Octave bank run_datenum_bank.py, dev repository only), so
    # passing month 0 would give the same value; it is written as the latter
    # so the clamp is explicit at the call site. The S4c design doc S2 table
    # flags MATLAB/Octave as diverging on month<1; matching the measured
    # behaviour of the computation that made the actual product outranks a
    # documentation reading for this environment-dependent secondary path --
    # see Z_D/SPOT_EDGE in reject.py for the same principle applied elsewhere.
    tv = (datenum(year2, month, day) + datenum(run_year, 1, 1) + tod
          - datenum(current_year, 1, 1, 0, 0, 0))
    return tv + np.where(is_60, _ONE_MINUTE, 0.0)


def combine_sizedist(sd_files, outfile, *, flight_date, summary_time,
                     current_year=None, creation_time=None):
    """``combine_sizedist.m`` -- stitch several ``sd`` files into one flight product.

    Parameters
    ----------
    sd_files : sequence of paths, IN ORDER
        ``:31,:37`` glob a directory and process files in ``dir`` order, which
        is alphabetical for these basenames. Passing an explicit ordered list
        turns that coincidence into a contract (the combine design record, section 8, decision 1); a
        test pins that the product-of-record's own file order is what
        alphabetical globbing of the five 09/06 raw-derived basenames gives.
    outfile : path to write.
    flight_date : str, ``'YYYYMMDD'``
        Full year. ``:9`` slices ``flightdate(3:8)`` (MATLAB 1-based) for the
        output stem and ``(3:4)`` for the *wrong* two-digit year used in the
        MATLAB's own cancellation trick (see ``current_year`` below) -- this
        function's default path uses the full year correctly instead.
    summary_time : str, ``'YY_MM_DD_HH_MM_SS'``
        The campaign summary file's own basename, without the campaign
        extension -- e.g. ``'16_09_06_06_40_17'`` for
        ``16_09_06_06_40_17.oracles``. ``:150-154`` needs its full date and
        time for the sync step below; ``:199-200`` needs only its HH/MM/SS
        for the output filename, which this module's caller builds separately
        (the combine design record, section 3: the script uses the summary file's NAME only, never
        its contents, so there is no filesystem dependency to satisfy here).
    current_year : int or None
        ``None`` (default) computes the intended time axis directly: the
        flight date plus time of day, with no dependency on when this code
        happens to run. A given int replicates ``:109-110``'s own arithmetic
        via :func:`_timevec_matlab_replica`, for reproducing a specific
        historical mis-set run -- see that function's docstring.
    creation_time : unused
        ``combine_sizedist.m`` writes no global attributes at all (measured;
        ``:202-231`` defines only variables). Accepted for interface symmetry
        with the earlier translation's ``imgproc_sm`` and ``sizedist.run``, and ignored.

    Returns the path written.
    """
    per_file = [_read_one(p) for p in sd_files]

    # :62-65.  Reassigned every loop iteration to file 1's values regardless of
    # `i` -- a MATLAB quirk with no effect (the bin ladder does not vary
    # file to file), reproduced by simply reading it once, from file 1.
    bin_min = np.asarray(per_file[0]["bin_min"], dtype=np.float64).reshape(-1)
    bin_max = np.asarray(per_file[0]["bin_max"], dtype=np.float64).reshape(-1)
    bin_mid = np.asarray(per_file[0]["bin_mid"], dtype=np.float64).reshape(-1)
    bin_dD = np.asarray(per_file[0]["bin_dD"], dtype=np.float64).reshape(-1)

    time_parts, nd_parts, darea_parts = [], [], []
    nt_parts, count_parts, mar_parts, rr_parts = [], [], [], []
    for vals in per_file:
        t_k = np.asarray(vals["time"], dtype=np.float64).reshape(-1)
        # :47-50.  get_var returns MATLAB shape (bin, time); '.T' is the ' in
        # the MATLAB source, giving (time, bin) to match the concat target.
        nd_k = (np.asarray(vals["conc_minR"], dtype=np.float64).T / 10.0) * bin_dD
        darea_k = (np.asarray(vals["conc_AreaR"], dtype=np.float64).T / 10.0 ** 4) * bin_dD
        # :70-71.  MATLAB reads count/mean_area_ratio untransposed and
        # transposes at the concat step instead; same result, done here.
        count_k = np.asarray(vals["count"], dtype=np.float64).T
        mar_k = np.asarray(vals["mean_area_ratio"], dtype=np.float64).T
        nt_k = np.asarray(vals["n"], dtype=np.float64).reshape(-1)
        rr_k = np.asarray(vals["Reject_ratio"], dtype=np.float64).reshape(-1)

        time_parts.append(t_k)
        nd_parts.append(nd_k)
        darea_parts.append(darea_k)
        nt_parts.append(nt_k)
        count_parts.append(count_k)
        mar_parts.append(mar_k)
        rr_parts.append(rr_k)

    time = np.concatenate(time_parts)
    twods_Nd = np.concatenate(nd_parts, axis=0)
    conc_darea = np.concatenate(darea_parts, axis=0)
    twods_Nt = np.concatenate(nt_parts)
    count = np.concatenate(count_parts, axis=0)
    mean_area_ratio = np.concatenate(mar_parts, axis=0)
    reject_ratio = np.concatenate(rr_parts)

    # :84-91.  Drop the SECOND of each *consecutive* duplicate stamp -- MATLAB's
    # diff(time)==0 only ever fires on adjacent equal pairs, so a repeat that
    # is not adjacent (e.g. after other stamps in between) is kept.  This is
    # the same rule combine's own use as an oracle target already pins.
    #
    dup = np.flatnonzero(np.diff(time) == 0) + 1
    keep = np.ones(len(time), dtype=bool)
    keep[dup] = False
    time = time[keep]
    twods_Nd = twods_Nd[keep]
    conc_darea = conc_darea[keep]
    twods_Nt = twods_Nt[keep]
    count = count[keep]
    mean_area_ratio = mean_area_ratio[keep]
    reject_ratio = reject_ratio[keep]

    # :95-120.  Time axis.
    hhmmss = time.astype(np.int64)
    if current_year is None:
        year, month, day = int(flight_date[0:4]), int(flight_date[4:6]), int(flight_date[6:8])
        tod, is_60 = _time_of_day(hhmmss)
        timevec = datenum(year, month, day) + tod + np.where(is_60, _ONE_MINUTE, 0.0)
    else:
        year2 = int(flight_date[2:4])
        month, day = int(flight_date[4:6]), int(flight_date[6:8])
        timevec = _timevec_matlab_replica(hhmmss, year2, month, day, current_year)

    # :124-148.  Append missing 1 Hz steps.  Built by multiplication from an
    # integer step count rather than MATLAB's colon-operator accumulation, for
    # the same reason Z_D is in reject.py: many thousands of 1/86400 additions
    # would drift off an exact-second grid.
    n_steps = int(round((timevec[-1] - timevec[0]) * 86400.0)) + 1
    if n_steps > 5_000_000 or n_steps < 1:
        # A real flight file is a few hours (<20,000 s). Something this far
        # off the rail is a garbage time axis -- almost certainly a bad
        # current_year for _timevec_matlab_replica -- not a real gap to fill.
        # Fail loudly rather than allocate tens of gigabytes silently.
        raise ValueError(
            f"combine_sizedist: computed a {n_steps}-second time axis "
            f"({timevec[0]!r} to {timevec[-1]!r}); this is almost certainly a "
            f"bad current_year, not a real flight gap. Refusing to allocate."
        )
    timevec_new = timevec[0] + np.arange(n_steps) * _ONE_SECOND
    B = len(bin_mid)
    # :125,:161 build a NaN-padded `time` (the HHMMSS stamps) here too, but it
    # is never passed to a `putVar` call (the combine design doc: "time... is never
    # written") -- dead in the MATLAB, so not reproduced here either.
    nt_new = np.full(n_steps, np.nan)
    nd_new = np.full((n_steps, B), np.nan)
    count_new = np.full((n_steps, B), np.nan)
    mar_new = np.full((n_steps, B), np.nan)
    rr_new = np.full(n_steps, np.nan)
    darea_new = np.full((n_steps, B), np.nan)

    # :135.  MATLAB searches for the nearest new-grid index within 0.3 s; every
    # timevec value here is an exact whole second (built from integer HHMMSS
    # plus, at most, one exact extra minute), so the nearest index is just the
    # rounded integer offset -- no search needed, and no risk of the 0.3 s
    # tolerance ever mattering for this data.
    idx = np.round((timevec - timevec[0]) * 86400.0).astype(np.int64)
    nt_new[idx] = twods_Nt
    nd_new[idx] = twods_Nd
    count_new[idx] = count
    mar_new[idx] = mean_area_ratio
    rr_new[idx] = reject_ratio
    darea_new[idx] = conc_darea

    # :150-182.  Sync with the summary file's own timestamp.
    yy2, mm_, dd_ = int(summary_time[0:2]), int(summary_time[3:5]), int(summary_time[6:8])
    hh_, mi_, ss_ = int(summary_time[9:11]), int(summary_time[12:14]), int(summary_time[15:17])
    # :152-154 computes this as `datenum(2000,0,0,0,0,0) + datenum(YY,MM,DD,...)`
    # with a 2-digit YY -- the same shape of two-small-numbers-cancel trick as
    # the flight-date arithmetic in :109-110, and just as run-environment
    # dependent: verified under Octave that the trick DOES recover the correct
    # instant (736579.277974537 for this file, matching the design doc's own
    # measured product value) -- because Octave sets a month below 1 to 1,
    # which the port's datenum() reproduces, so the two-term form evaluated
    # here gives the same 736579.277974537. MATLAB's documentation is read as
    # treating month<1 differently (S4c design doc S2), so the two-term form
    # is an environment-specific coincidence, not the intended computation.
    # Same port decision as the flight-date axis (S4c design doc S4): compute
    # the intended value directly.
    timevec_summary = float(datenum(2000 + yy2, mm_, dd_, hh_, mi_, ss_))

    if timevec_new[0] > timevec_summary:
        # :157-167.  Prepend NaN rows from the summary time up to (not
        # including) the first real row.
        n_pad = int(round((timevec_new[0] - timevec_summary) * 86400.0))
        if n_pad > 5_000_000:
            # Same guard as n_steps above, same reason: a real summary-to-data
            # gap is minutes, not years. This path is reachable with a bad
            # current_year (the flight-date and summary-time axes then use
            # different year conventions and appear days or years apart).
            raise ValueError(
                f"combine_sizedist: computed {n_pad} s of summary-sync padding "
                f"(summary {timevec_summary!r}, data starts {timevec_new[0]!r}); "
                f"almost certainly a bad current_year. Refusing to allocate."
            )
        pad = timevec_summary + np.arange(n_pad) * _ONE_SECOND
        timevec_final = np.concatenate([pad, timevec_new])
        nt_final = np.concatenate([np.full(n_pad, np.nan), nt_new])
        nd_final = np.concatenate([np.full((n_pad, B), np.nan), nd_new], axis=0)
        count_final = np.concatenate([np.full((n_pad, B), np.nan), count_new], axis=0)
        mar_final = np.concatenate([np.full((n_pad, B), np.nan), mar_new], axis=0)
        rr_final = np.concatenate([np.full(n_pad, np.nan), rr_new])
    else:
        # :169-181.  Trim leading rows before the summary time. Dead for every
        # real ORACLES flight measured so far (the summary file always
        # predates the first raw file by design doc S3), reproduced anyway:
        # MATLAB's `arr(1:y,:)=[]` with y<=0 removes nothing (`1:0` is empty
        # in MATLAB), which int16's saturating round-half-away-from-zero cast
        # can only produce when the two datenums are equal or `timevec_new`
        # is (impossibly) earlier than a summary time already excluded by the
        # branch condition -- so y>0 whenever this branch is reached at all.
        y = int(mint16((timevec_new[0] - timevec_summary) * 86400.0))
        y = max(y, 0)
        timevec_final = timevec_new[y:]
        nt_final = nt_new[y:]
        nd_final = nd_new[y:]
        count_final = count_new[y:]
        mar_final = mar_new[y:]
        rr_final = rr_new[y:]

    _write(outfile, len(sd_files), bin_min, bin_max, bin_mid, bin_dD,
           timevec_final, mar_final, count_final, nd_final, nt_final, rr_final)
    return outfile


def _write(outfile, n_files, bin_min, bin_max, bin_mid, bin_dD,
          timevec, mean_area_ratio, count, twods_Nd, twods_Nt, reject_ratio):
    """:202-231.  Ten variables, no global attributes -- measured, not assumed."""
    f = ncio.create(str(outfile), "clobber")
    time_dim = ncio.def_dim(f, "time", len(timevec))
    bin_dim = ncio.def_dim(f, "bin_count", len(bin_min))
    # :207.  Declared, used by no variable -- the only record of how many
    # files went into the product. Preserved rather than dropped.
    ncio.def_dim(f, "files_stitched", n_files)

    v_time = ncio.def_var(f, "Time Vector", "double", [time_dim])
    v_bmin = ncio.def_var(f, "Bin Minimum", "double", [bin_dim])
    v_bmax = ncio.def_var(f, "Bin Maximum", "double", [bin_dim])
    v_bmid = ncio.def_var(f, "Bin Midpoints", "double", [bin_dim])
    v_bdD = ncio.def_var(f, "Bin Width", "double", [bin_dim])
    # :213 etc. -- MATLAB's own dims list is [dimid0 dimid1] = [time, bin],
    # in that order; ncio.def_var takes dimids in that same MATLAB order.
    v_mar = ncio.def_var(f, "Mean Area Ratio", "double", [time_dim, bin_dim])
    v_count = ncio.def_var(f, "Counts", "double", [time_dim, bin_dim])
    v_nd = ncio.def_var(f, "Size Distribution cm-3", "double", [time_dim, bin_dim])
    v_nt = ncio.def_var(f, "Number Concentration cm-3", "double", [time_dim])
    v_rr = ncio.def_var(f, "Reject Ratio", "double", [time_dim])
    ncio.end_def(f)

    ncio.put_var(f, v_time, timevec)
    ncio.put_var(f, v_bmin, bin_min)
    ncio.put_var(f, v_bmax, bin_max)
    ncio.put_var(f, v_bmid, bin_mid)
    ncio.put_var(f, v_bdD, bin_dD)
    ncio.put_var(f, v_mar, mean_area_ratio)
    ncio.put_var(f, v_count, count)
    ncio.put_var(f, v_nd, twods_Nd)
    ncio.put_var(f, v_nt, twods_Nt)
    ncio.put_var(f, v_rr, reject_ratio)
    ncio.close(f)
