# SPDX-License-Identifier: BSD-3-Clause
"""``IntArrAnalysis_time.m`` -- per-particle inter-arrival thresholds, and the file they go in.

The driver around :mod:`arrayprobe.intarr`'s bimodal fit: read a combined per-particle file,
split it into populations, fit each one, pick a threshold, and write the ``.cdf`` that
``sizeDist`` accepts as its optional twelfth argument.

**This stage's output was never consumed by the ORACLES products this project validates
against.** The production call named a threshold file that does not exist, so ``sizeDist.m:70``
set ``iaThreshFile = 'NONE'`` and ``:874`` fell back to the per-probe constant. Porting the
stage completes the package and enables the time-dependent path for other campaigns; it changes
no number that can currently be checked against a reference product.


Source of record is the ORACLES-variant ``IntArrAnalysis_time.m`` (the lineage that processed
ORACLES), **not** the stock tree's differently-shaped ``IntArrAnalysis.m``.

**The remaining routines (author-directed: all three opt-in, default OFF, so the existing default
behaviour above is unchanged byte-for-byte):**

* The diagnostic contour plot -- :mod:`arrayprobe.intarr_plots`, imported lazily, never required
  to import this module. Its time axis reproduces the NaN pre-10:00 timestamps
  (``IntArrAnalysis_time.m:243-250`` -- ``num2str`` right-justifies a mixed-width time column, so
  the ``< 100000`` branch reads a padding space as the hour digit and every pre-10:00:00
  particle's axis value becomes NaN once the same file also has a particle at or after 10:00:00).
  :func:`overlay_time_axis` below reproduces this by default (``fix_b8=False``); a separate,
  also opt-in ``fix_b8=True`` gives the corrected axis. :func:`contour_time_axis` is the
  source's *other*, width-aware time formula (``:258-269``), which is not B8-affected -- it
  already skips the padding column, kept faithfully rather than "fixed" since it is not a bug.
* The ``.mat`` workspace dump -- :func:`write_mat_workspace`, ``scipy.io`` imported lazily.
* The two thresholds ``threshhold``/``threshhold_ww`` the source computes but never writes
  (``:367`` writes only ``threshhold_ak``) -- already returned unconditionally by :func:`analyse`
  below (every key in its dict, always; nothing here is gated on an option, because returning an
  already-computed Python value writes nothing and changes no file). What is newly opt-in is
  *persisting* them anywhere: :func:`write_extra_thresholds_sidecar` writes a JSON sidecar (never
  a netCDF file -- the fidelity doctrine reserves "writes a variable MATLAB never wrote" for
  ``enhancements_uiops/``, and this project only has authorisation to expose the values,
  not to
  add them to the ``.cdf``).
"""

from __future__ import annotations

import json

import numpy as np

from . import ncio
from .intarr import bimodal_model, fit_bimodal_intarr
from .matlab_compat import datenum, datestr

__all__ = [
    "DEFAULT_THRESHOLD",
    "HIST_BINS",
    "CONTOUR_BINS",
    "inter_arrival",
    "population_size",
    "block_thresholds",
    "analyse",
    "write_threshold_file",
    "contour_data",
    "overlay_time_axis",
    "contour_time_axis",
    "expand_tau_per_particle",
    "write_extra_thresholds_sidecar",
    "write_mat_workspace",
]

#: ``:157``, ``:186-187`` -- the value every threshold in a block takes when the fit fails.
DEFAULT_THRESHOLD = 1.3494e-6

#: ``:106`` -- 35 edges, 34 bins, log-spaced over seven decades.
HIST_BINS = np.logspace(-7, 0, 35)

#: ``:107`` -- the source takes the log-width of the first bin and uses it for all of them.
_WIDTH = float(np.log(HIST_BINS[1]) - np.log(HIST_BINS[0]))

#: ``:220`` -- the *contour* plot's own, finer histogram: 70 edges, 69 bins, same seven-decade
#: log range. Deliberately different resolution from the fit's ``HIST_BINS``; both are the
#: source's own choice, not a port inconsistency.
CONTOUR_BINS = np.logspace(-7, 0, 70)

#: ``:272`` -- the contour fill levels, ``0.005:0.005:0.1`` in MATLAB colon notation (20 levels,
#: inclusive of both ends). Built from an integer count rather than ``np.arange`` so float steps
#: cannot silently drop or duplicate the last level.
CONTOUR_LEVELS = 0.005 * np.arange(1, 21)

#: ``:130`` -- initial guess for (tau1, tau2, fraction).
_BETA0 = (1e-2, 1e-6, 0.5)

#: ``:110-111`` -- anything slower than this is zeroed rather than dropped.
_MAX_INTER_ARRIVAL = 0.1


def inter_arrival(time_in_seconds):
    """``:73-75``, ``:93``, ``:105-111`` -- the source's inter-arrival vector, in its own order.

    The first particle gets 0, the rest are differences; then ``<= 0`` becomes NaN (which takes
    that leading 0 with it), and anything above 0.1 s is set to **0, not dropped**. The two steps
    are ordered as the source orders them: the ``< 0 -> 0`` line at ``:110`` is a no-op once the
    NaN step has run, and is kept for transcription completeness.
    """
    t = np.asarray(time_in_seconds, dtype=float)
    out = np.empty(t.size, dtype=float)
    if t.size == 0:
        return out
    out[0] = 0.0
    out[1:] = np.diff(t)
    out[out <= 0] = np.nan                      # :93
    out[out < 0] = 0.0                          # :110, unreachable after the line above
    out[out > _MAX_INTER_ARRIVAL] = 0.0         # :111
    return out


def population_size(timehhmmss, n_blocks):
    """``:112-119`` -- how many particles go into each bimodal fit.

    ``ceil(N / n_blocks)`` unless the most crowded second holds at least that many, in which case
    the block is that second's count rounded **up to the next quarter** of the base size. Coarse
    by design; reproduced as written.
    """
    t = np.asarray(timehhmmss)
    n = t.size
    if n == 0 or n_blocks <= 0:
        raise ValueError("need particles and a positive block count")
    base = int(np.ceil(n / n_blocks))
    values, counts = np.unique(t, return_counts=True)
    busiest = int(counts.max())                 # numel(find(t == mode(t)))
    if busiest < base:
        return base
    quarter = base / 4
    return int(quarter * np.ceil(busiest / quarter))


def block_thresholds(counts, *, beta0=_BETA0):
    """``:139-190`` for one population: ``(threshold, threshold_ww, threshold_ak, tau)``.

    ``counts`` is the raw histogram of the block's inter-arrival times over :data:`HIST_BINS`.
    All three of the source's thresholds are returned; only ``threshold_ak`` is written to the
    output file, as the source writes it (``:367``).
    """
    centres = HIST_BINS[:-1] + np.diff(HIST_BINS) / 2
    h = np.asarray(counts, dtype=float)
    if h.sum() == 0:
        return DEFAULT_THRESHOLD, DEFAULT_THRESHOLD, DEFAULT_THRESHOLD, None

    tau = fit_bimodal_intarr(centres, h, _WIDTH, beta0=beta0)
    if np.isnan(tau).any():                                     # :156-158
        return DEFAULT_THRESHOLD, DEFAULT_THRESHOLD, DEFAULT_THRESHOLD, tau

    threshold = float(np.min(tau[:2]) * 2)                      # :159
    hi, lo = float(np.max(tau[:2])), float(np.min(tau[:2]))     # :170
    fitted = bimodal_model(tau, centres)
    between = (centres < hi) & (centres > lo)                   # :171

    if not between.any():                                       # :173-177, Finlon's guard
        left = np.flatnonzero(centres < hi)
        right = np.flatnonzero(centres > lo)
        if left.size == 0 or right.size == 0:                   # :183-188
            return threshold, DEFAULT_THRESHOLD, DEFAULT_THRESHOLD, tau
        pick = np.array([left[-1], right[0]])
        new_dt = centres[pick]
        i_fit = int(np.argmin(fitted[pick]))
        i_obs = int(np.argmin(h[pick]))
    else:
        new_dt = centres[between]
        i_fit = int(np.argmin(fitted[between]))
        i_obs = int(np.argmin(h[between]))

    return threshold, float(new_dt[i_fit]), float(new_dt[i_obs]), tau


def analyse(int_arr, timehhmmss, *, n_blocks=5, beta0=_BETA0, collect_histograms=False):
    """Run the whole population loop.  Returns a dict of per-particle arrays.

    Keys: ``threshold``, ``threshold_ww``, ``threshold_ak`` (each one value per particle, constant
    within a block), ``tau`` (one row per block), ``population_size``, ``block_starts``. All
    three thresholds are always returned -- the source itself computes all three and writes only
    ``threshold_ak`` (``:367``); returning the other two here writes nothing and changes no file,
    so it needs no opt-in (see the module docstring's note on the remaining inter-arrival work).

    ``collect_histograms=False`` (default) leaves this function's return value byte-for-byte
    identical to a call without the option: no extra key appears and nothing above is computed
    differently. ``collect_histograms=True`` additionally returns ``hist2dc``
    -- ``:106,148`` -- the raw 34-bin histogram counts per block (one row per block), needed only by
    :func:`write_mat_workspace`.
    """
    arr = np.asarray(int_arr, dtype=float)
    n = arr.size
    size = population_size(timehhmmss, n_blocks)
    out = {k: np.empty(n, dtype=float) for k in ("threshold", "threshold_ww", "threshold_ak")}
    taus, starts, hists = [], [], []
    for start in range(0, n, size):                             # :139
        end = min(start + size, n)
        block = arr[start:end]
        counts, _ = np.histogram(block[~np.isnan(block)], bins=HIST_BINS)
        thr, ww, ak, tau = block_thresholds(counts, beta0=beta0)
        out["threshold"][start:end] = thr
        out["threshold_ww"][start:end] = ww
        out["threshold_ak"][start:end] = ak
        taus.append(tau if tau is not None else np.full(3, np.nan))
        starts.append(start)
        if collect_histograms:
            hists.append(counts.astype(float))
    out["tau"] = np.asarray(taus, dtype=float)
    out["block_starts"] = np.asarray(starts, dtype=int)
    out["population_size"] = size
    if collect_histograms:
        out["hist2dc"] = np.asarray(hists, dtype=float)          # :106,148
    return out


def write_threshold_file(filename, timehhmmss, threshold, *, probename, flight_date,
                         data_source, population_size, creation_time=None):
    """``:336-368`` -- the file ``sizeDist`` reads as its twelfth argument.

    Attribute names, order, units and variable names follow the source exactly; ``Creation Time``
    is overridable so two runs can be compared byte for byte.
    """
    times = np.asarray(timehhmmss, dtype=float)
    values = np.asarray(threshold, dtype=float)
    if times.shape != values.shape:
        raise ValueError(f"time and threshold must match: {times.shape} vs {values.shape}")

    f = ncio.create(filename, "clobber")
    dim = f.def_dim("particleTime", times.size)
    g = ncio.NC_GLOBAL
    f.put_att(g, "Software", "UIOOPS/IntArrAnalysis_revised")
    f.put_att(g, "Institution", "Univ. Oklahoma, SoM")
    f.put_att(g, "Creation Time",
              creation_time if creation_time is not None
              else datestr(None, "yyyy/mm/dd HH:MM:SS"))
    f.put_att(g, "Description", "Contains inter-arrival threshold information for each particle "
                                "following Field et al. (2006)")
    f.put_att(g, "Flight Date", str(flight_date))
    f.put_att(g, "Data Source", str(data_source))
    f.put_att(g, "Probe Type", str(probename))
    f.put_att(g, "Population Size", f"{population_size} particles per distribution fit")

    vid_time = f.def_var("particle_time", "double", dim)
    f.put_att(vid_time, "units", "HHMMSS")
    f.put_att(vid_time, "name", "Time")
    vid_thr = f.def_var("threshold", "double", dim)
    f.put_att(vid_thr, "units", "sec")
    f.put_att(vid_thr, "name", "Inter-arrival time threshold in n-particle blocks")

    f.end_def()
    f.put_var(vid_time, times)
    f.put_var(vid_thr, values)
    f.close()
    return filename


# --------------------------------------------------------------------------
# The interarrival remainder: the contour plot's data, the .mat dump, and the two
# unwritten thresholds' sidecar. All opt-in; nothing above this point changes.
# --------------------------------------------------------------------------

def _intarr_pre_clip(time_in_seconds):
    """The source's own ``intarr`` variable's *final* value (``:73-75``, ``:93`` only).

    Unlike ``int_arr`` -- which goes on to receive the ``:110-111`` clipping and is what
    :func:`inter_arrival` returns -- the source never touches ``intarr`` again after the
    ``<=0 -> NaN`` step at ``:91``, so what ends up in the workspace under that name is the
    NaN-only-clipped inter-arrival vector, without the later ``>0.1 -> 0`` zeroing. Needed only
    for :func:`write_mat_workspace`, which writes both under their own MATLAB names.
    """
    t = np.asarray(time_in_seconds, dtype=float)
    out = np.empty(t.size, dtype=float)
    if t.size == 0:
        return out
    out[0] = 0.0
    out[1:] = np.diff(t)
    out[out <= 0] = np.nan                                        # :91
    return out


def contour_data(int_arr, timehhmmss, date, size):
    """``:220-236`` -- the contour plot's own, coarser-fit-but-finer-bin per-block histogram.

    A second population loop over the *same* blocks :func:`analyse` uses (``size`` is its
    ``population_size``), but histogrammed into :data:`CONTOUR_BINS` (69 bins, not 34) and
    without any fitting -- the source only ever plots this one, it does not fit it.

    Returns ``(hist2dc_contour, new_time2dc, new_date2dc)``. ``:235-236`` overwrites the *last*
    block's own recorded start time/date with the sequence's very last particle's time/date --
    reproduced here exactly, including on a single-block input.
    """
    arr = np.asarray(int_arr, dtype=float)
    t = np.asarray(timehhmmss, dtype=float)
    d = np.asarray(date, dtype=float)
    n = arr.size
    if n == 0 or size <= 0:
        raise ValueError("need particles and a positive block size")
    n_blocks = int(np.ceil(n / size))
    hist = np.zeros((n_blocks, len(CONTOUR_BINS) - 1), dtype=float)
    new_time = np.empty(n_blocks, dtype=float)
    new_date = np.empty(n_blocks, dtype=float)
    row = 0
    for start in range(0, n, size):                              # :225
        end = min(start + size, n)
        block = arr[start:end]
        counts, _ = np.histogram(block[~np.isnan(block)], bins=CONTOUR_BINS)
        hist[row, :] = counts
        new_time[row] = t[start]
        new_date[row] = d[start]
        row += 1
    new_time[row - 1] = t[-1]                                     # :235
    new_date[row - 1] = d[-1]                                     # :236
    return hist, new_time, new_date


def _num2str_int_column(values):
    """MATLAB ``num2str`` on a column vector of non-negative integer-valued doubles.

    ``num2str`` on a numeric *column* right-justifies every row to one common width -- the
    mechanism the NaN pre-10:00 timestamps turn on. ``timehhmmss``/``date`` values here are always
    whole-number HHMMSS/YYYYMMDD doubles (read straight off netCDF), so ``str(int(round(v)))``
    reproduces MATLAB's own default integer formatting exactly. Returns ``(rows, width)``.
    """
    strs = [str(int(round(v))) for v in np.asarray(values, dtype=float)]
    width = max((len(s) for s in strs), default=0)
    return [s.rjust(width) for s in strs], width


def _str2double(s):
    """MATLAB ``str2double`` of one substring: NaN if all blank (the NaN pre-10:00 timestamps)."""
    s = s.strip()
    return float("nan") if not s else float(s)


def _time2datenum(date_value):
    """The ORACLES-variant ``time2datenum.m``'s numeric-``datestring`` branch (``:174-181``), called
    (as the source calls it, ``:246`` etc.) with a single argument -- no ``timestring``, so
    ``HH=MI=SC=0`` and only the ``yyyymmdd`` decomposition of ``date_value`` matters.
    """
    yy = np.floor(date_value / 10000)
    mm = np.floor((date_value - 10000 * yy) / 100)
    dd = np.floor(date_value - 10000 * yy - 100 * mm)
    return datenum(yy, mm, dd, 0, 0, 0)


def _time_of_day_fraction(hh, mi, sc):
    """MATLAB ``datenum(0,0,0,HH,MI,SC)`` -- the source's own idiom at ``:246-267`` for adding a
    time-of-day offset to a whole-day ``time2datenum`` value, called as written.

    It replaces a local ``HH/24 + MI/1440 + SC/86400``, which differs from Octave's
    ``(HH + (MI + SC/60)/60)/24`` by one ulp on about 40 % of instants; added to a whole-day
    datenum of any real date the two give the same bits (``tests/test_datenum_octave_oracle.py``).
    """
    return datenum(0, 0, 0, hh, mi, sc)


def overlay_time_axis(timehhmmss, date, *, fix_b8=False):
    """``:243-250`` -- the per-particle datenum axis for the threshold-overlay lines.

    ``fix_b8=False`` (default, matching every real run of the source) reproduces the upstream
    finding that a mixed-width time vector puts NaN into every pre-10:00 timestamp:
    ``num2str`` right-justifies the whole ``timehhmmss`` column to one common width,
    so in a file spanning 10:00:00 every row before it is left-padded with a space and the
    ``< 100000`` branch reads that pad as the hour digit -- ``str2double`` of a blank is NaN.
    ``fix_b8=True`` computes the same value directly from the integer,
    never touching a string.
    """
    t = np.asarray(timehhmmss, dtype=float)
    d = np.asarray(date, dtype=float)
    if t.shape != d.shape:
        raise ValueError(f"timehhmmss and date must match: {t.shape} vs {d.shape}")
    n = t.size
    out = np.empty(n, dtype=float)

    if fix_b8:
        hh = np.floor(t / 10000.0)
        mi = np.floor(np.mod(t, 10000.0) / 100.0)
        sc = np.mod(t, 100.0)
        for k in range(n):
            out[k] = _time2datenum(d[k]) + _time_of_day_fraction(hh[k], mi[k], sc[k])
        return out

    rows, _width = _num2str_int_column(t)                         # :243
    for k in range(n):                                            # :244-250
        row = rows[k]
        if t[k] < 100000:
            hh = _str2double(row[0:1])
            mi = _str2double(row[1:3])
            sc = _str2double(row[3:5])
        else:
            hh = _str2double(row[0:2])
            mi = _str2double(row[2:4])
            sc = _str2double(row[4:6])
        out[k] = _time2datenum(d[k]) + _time_of_day_fraction(hh, mi, sc)
    return out


def contour_time_axis(new_time2dc, new_date2dc):
    """``:258-269`` -- the contour plot's own per-block ``x`` axis.

    A *different* formula from :func:`overlay_time_axis`, and -- unlike it -- not affected by that
    NaN: it branches on ``size(y,2)`` (the char matrix's actual width) rather than always slicing
    the same fixed columns, so the width-6 case correctly reads column 2 (a single digit) as the
    hour rather than column 1 (the padding space). Kept faithfully rather than "fixed", since it
    is not a bug -- the source got this one right.
    """
    t = np.asarray(new_time2dc, dtype=float)
    d = np.asarray(new_date2dc, dtype=float)
    if t.shape != d.shape:
        raise ValueError(f"new_time2dc and new_date2dc must match: {t.shape} vs {d.shape}")
    n = t.size
    out = np.empty(n, dtype=float)
    rows, width = _num2str_int_column(t)                          # :258
    for k in range(n):                                            # :259-269
        row = rows[k]
        if t[k] < 100000:
            if width == 5:
                hh = _str2double(row[0:1])
                mi = _str2double(row[1:3])
                sc = _str2double(row[3:5])
            elif width == 6:
                hh = _str2double(row[1:2])
                mi = _str2double(row[2:4])
                sc = _str2double(row[4:6])
            else:
                raise ValueError(
                    f"NEWtime2dc column width {width} has no branch in the source (:261-265 "
                    "only handle 5 or 6) -- read the .m before extending this")
        else:
            hh = _str2double(row[0:2])
            mi = _str2double(row[2:4])
            sc = _str2double(row[4:6])
        out[k] = _time2datenum(d[k]) + _time_of_day_fraction(hh, mi, sc)
    return out


def expand_tau_per_particle(tau_blocks, block_starts, population_size, n):
    """``:162-164``'s ``tau_all(j,:) = tau_std`` -- broadcast each block's fitted ``tau`` to
    every particle in that block, needed only for :func:`write_mat_workspace`'s ``tau_all``.

    The inner ``for j`` loop runs unconditionally (both the NaN and non-NaN branches reach it),
    so a block whose fit failed still broadcasts its ``[NaN, NaN, NaN]`` row to every one of its
    particles, exactly like a successful block broadcasts its real ``tau``.
    """
    tau_blocks = np.asarray(tau_blocks, dtype=float)
    out = np.empty((n, 3), dtype=float)
    for row, start in enumerate(block_starts):
        end = min(int(start) + population_size, n)
        out[start:end, :] = tau_blocks[row]
    return out


def write_extra_thresholds_sidecar(filename, timehhmmss, threshold, threshold_ww, *,
                                   threshold_ak=None):
    """Opt-in: persist the two thresholds the source computes but never writes (``:159``,
    ``:189``) alongside the ``.cdf`` -- as a plain JSON sidecar, **never** a netCDF file.

    ``threshold`` (``min(tau(1:2))*2``) and ``threshold_ww`` (the fitted-curve selection) sit
    next to ``threshold_ak`` (the one value ``:363`` writes) purely for a user who wants to
    compare the three techniques; :func:`analyse` already returns all three unconditionally
    (see the module docstring), so this function only decides where the extra two get
    *persisted*, and the fidelity doctrine's "an enhancement writes a variable MATLAB never
    wrote" line draws that boundary at the ``.cdf`` file specifically, not at "on disk at all".
    """
    times = np.asarray(timehhmmss, dtype=float)
    thr = np.asarray(threshold, dtype=float)
    ww = np.asarray(threshold_ww, dtype=float)
    if not (times.shape == thr.shape == ww.shape):
        raise ValueError("timehhmmss, threshold and threshold_ww must all match shape")
    payload = {
        "particle_time": times.tolist(),
        "threshold": thr.tolist(),
        "threshold_ww": ww.tolist(),
    }
    if threshold_ak is not None:
        ak = np.asarray(threshold_ak, dtype=float)
        if ak.shape != times.shape:
            raise ValueError("threshold_ak must match timehhmmss's shape")
        payload["threshold_ak"] = ak.tolist()
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return filename


def write_mat_workspace(filename, *, timehhmmss, date, time_in_seconds, dmax, probe_name,
                        date_string, infile, n_blocks=5, beta0=_BETA0):
    """``:331`` -- ``save([directory_2, probeName, '_IntArrAnalysis.', dateString, '_',
    startTime, '_', endTime, '.mat'])``, with no variable list: MATLAB saves the function's
    *entire* local workspace at that line. ``scipy.io`` is imported lazily -- opt-in, like the
    plots, so nothing in this module needs it merely to be imported.

    Writes the named result variables a user opening the ``.mat`` would actually want back,
    under their own MATLAB names, with MATLAB's own shapes (row vectors stay ``(1, N)``, matrices
    stay ``(n_blocks, n_bins)``). **Deliberately excluded**, and named here rather than silently
    dropped:

    * loop scratch that is only ever a *last-iteration* leftover, an artifact of MATLAB script
      scoping rather than a real result -- ``i``, ``j``, ``k``, ``h``, ``arr``, ``indicies``,
      ``dt``, ``hfit``, ``tau1``, ``tau2``, ``newDT``, ``minFit``, ``indexFit``, ``minOriginal``,
      ``indexOriginal``, ``y`` (redundant with ``NEWtime2dc`` in any case);
    * ``bimodalfit``, a function handle, not data ``scipy.io.savemat`` can round-trip;
    * ``ncid``, ``file`` -- an open netCDF handle and an OS ``dir()`` struct, meaningless once
      the run has finished;
    * the function's own parameters (``campaign``, ``filedate``, ``startTime``, ...), which the
      source's own hardcoded "Inputs" block (``:33-40``) overwrites before first use, so what a
      caller passed is never actually what ends up in the workspace under those names.

    Every OTHER named quantity the source's own workspace holds at ``:331`` is included:
    ``hist2dc``, ``NEWtime2dc``, ``NEWdate2dc`` (the *contour* loop's versions, since ``:231-236``
    overwrite the fit loop's own same-named arrays), ``threshhold``, ``threshhold_ww``,
    ``threshhold_ak``, ``tau_all``, ``hist2dc_contour``, ``histsum``, ``x``, ``time``, ``bins``
    and ``binsCenter`` (the *contour* loop's 70-point versions -- ``:220`` reassigns ``bins``
    after the fit loop, so that is what is left in the workspace), ``width`` (the *fit* loop's
    35-point value -- computed once at ``:119``, before ``:220``'s reassignment, and never
    touched again), ``num_particles``, ``numparticles``, ``timehhmmss``, ``date``, ``int_arr``,
    ``intarr``, ``Dmax``, ``n`` (the *contour* loop's final counter, since ``:224`` resets it),
    ``dateString``, ``probeName``, ``infile``.
    """
    import scipy.io

    times = np.asarray(timehhmmss, dtype=float)
    dates = np.asarray(date, dtype=float)
    n = times.size

    int_arr = inter_arrival(time_in_seconds)                      # :55-72, the port's own name
    intarr = _intarr_pre_clip(time_in_seconds)                    # :91's own final value

    size = population_size(times, n_blocks)
    result = analyse(int_arr, times, n_blocks=n_blocks, beta0=beta0, collect_histograms=True)
    hist2dc_contour, new_time2dc, new_date2dc = contour_data(int_arr, times, dates, size)

    tau_all = expand_tau_per_particle(result["tau"], result["block_starts"], size, n)

    row_sums = hist2dc_contour.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        histsum = np.repeat(row_sums, hist2dc_contour.shape[1], axis=1)  # :241

    x_axis = contour_time_axis(new_time2dc, new_date2dc)          # :258-269
    time_axis = overlay_time_axis(times, dates)                   # :243-250, B8 reproduced

    bins_contour = CONTOUR_BINS                                   # :220, final `bins`
    bins_center_contour = bins_contour[:-1] + np.diff(bins_contour) / 2  # :229, final `binsCenter`

    variables = {
        "hist2dc": result["hist2dc"],
        "NEWtime2dc": new_time2dc.reshape(1, -1),                 # :136, row vector
        "NEWdate2dc": new_date2dc.reshape(1, -1),
        "threshhold": result["threshold"],
        "threshhold_ww": result["threshold_ww"],
        "threshhold_ak": result["threshold_ak"],
        "tau_all": tau_all,
        "hist2dc_contour": hist2dc_contour,
        "histsum": histsum,
        "x": x_axis.reshape(-1, 1),                               # :262 etc., column vector
        "time": time_axis.reshape(1, -1),                         # :246 etc., `time(k)=...` row
        "bins": bins_contour.reshape(1, -1),
        "binsCenter": bins_center_contour.reshape(1, -1),
        "width": np.asarray([[_WIDTH]], dtype=float),
        "num_particles": np.asarray([[size]], dtype=float),
        "numparticles": np.asarray([[size]], dtype=float),
        "timehhmmss": times.reshape(-1, 1),
        "date": dates.reshape(-1, 1),
        "int_arr": int_arr.reshape(-1, 1),
        "intarr": intarr.reshape(-1, 1),
        "Dmax": np.asarray(dmax, dtype=float).reshape(-1, 1),
        "n": np.asarray([[hist2dc_contour.shape[0] + 1]], dtype=float),  # :224,234, post-loop n
        "dateString": date_string,
        "probeName": probe_name,
        "infile": infile,
    }
    scipy.io.savemat(filename, variables)
    return filename
