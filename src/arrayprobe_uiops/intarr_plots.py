# SPDX-License-Identifier: BSD-3-Clause
"""The production-variant ``IntArrAnalysis_time.m:220-291``: the contoured inter-arrival figure.

Opt-in and decoupled from the core port: importing :mod:`arrayprobe.intarr_analysis`, or
any other module in this package, never requires matplotlib. This module is the one place that
does, and it is imported lazily inside :func:`plot_intarr_contour` itself, not at module load.

**Reproduces the source figure's data, axes and contour levels** -- the 69-bin contour
(:data:`arrayprobe.intarr_analysis.CONTOUR_BINS`, ``:220``), the fill levels
(:data:`arrayprobe.intarr_analysis.CONTOUR_LEVELS`, ``0.005:0.005:0.1`` at ``:272``), the three
threshold overlay lines (``:278-280``), the log y-axis over ``[1e-7, 1]`` (``:282``) and an
``HH:MM`` time x-axis (``datetick('x','HH:MM')``, also ``:282``).

**``fix_b8=False`` (default, matching every real run of the source) reproduces the NaN
pre-10:00 timestamps** on the three overlay lines' own time axis: :func:`arrayprobe.intarr_analysis.
overlay_time_axis` returns NaN for every particle before 10:00:00 in a file that also has one at
or after it, and matplotlib -- like MATLAB's own ``plot`` -- renders a NaN x-value as a gap in
the line, not a crash and not a zero. The filled contour itself is drawn against
:func:`arrayprobe.intarr_analysis.contour_time_axis`, the source's *other*, width-aware time
formula (``:258-269``), which is not B8-affected, so the contour fill is identical either way --
only the three overlay lines can show the gap. A separate, also opt-in ``fix_b8=True`` gives the
corrected overlay axis instead.

Axis *values* are pinned directly, against a real Octave run of the source's own
``num2str``/``str2double``/``datenum`` logic, in ``tests/test_intarr_analysis.py`` --
deliberately not by image comparison, which cannot check a NaN gap's position, only tests here
check that this module's plotting *call* does not crash and places the right data on the right
axes.
"""

from __future__ import annotations

import datetime as _dt
import math

import numpy as np

from .intarr_analysis import (
    CONTOUR_BINS,
    CONTOUR_LEVELS,
    contour_data,
    contour_time_axis,
    overlay_time_axis,
)

__all__ = ["plot_intarr_contour"]

#: MATLAB day 1 is 0000-01-01; Python's ``date.fromordinal(1)`` is 0001-01-01 -- the same
#: constant :mod:`arrayprobe.matlab_compat` uses (``_DATENUM_OFFSET``), restated here rather than
#: imported across a private name so this module's only coupling to matlab_compat stays the
#: public :func:`arrayprobe.matlab_compat.datenum` that ``intarr_analysis`` itself already uses.
_DATENUM_TO_ORDINAL_OFFSET = 366


def _datenum_to_mpl_num(value, mdates):
    """One MATLAB serial datenum -> matplotlib's numeric date-axis value; NaN stays NaN (a gap)."""
    if not np.isfinite(value):
        return float("nan")
    whole = math.floor(value)
    frac = value - whole
    day = _dt.date.fromordinal(int(whole) - _DATENUM_TO_ORDINAL_OFFSET)
    when = _dt.datetime.combine(day, _dt.time()) + _dt.timedelta(seconds=frac * 86400.0)
    return mdates.date2num(when)


def plot_intarr_contour(int_arr, timehhmmss, date, threshold, threshold_ww, threshold_ak,
                        *, population_size, date_string="", fix_b8=False):
    """``:220-291`` -- draw the contoured inter-arrival-time figure with matplotlib.

    ``int_arr``, ``timehhmmss``, ``date`` are the same per-particle arrays
    :func:`arrayprobe.intarr_analysis.analyse` and :func:`arrayprobe.intarr_analysis.
    contour_data` take. ``threshold``, ``threshold_ww``, ``threshold_ak`` are ``analyse``'s own
    per-particle outputs (all three are always returned; see that module's docstring).
    ``population_size`` must be the same block size used for the fit (``analyse``'s
    ``out["population_size"]``), since the contour loop (``:225``) reuses it rather than
    re-deriving it.

    Returns ``(fig, ax)``. Never called at import time; matplotlib is imported here, lazily.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    hist, new_time, new_date = contour_data(int_arr, timehhmmss, date, population_size)
    row_sums = hist.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (hist / row_sums).T                                    # :240-241,271

    x_datenum = contour_time_axis(new_time, new_date)               # :258-269, not B8-affected
    overlay_datenum = overlay_time_axis(timehhmmss, date, fix_b8=fix_b8)  # :243-250, B8

    x_num = np.asarray([_datenum_to_mpl_num(v, mdates) for v in x_datenum])
    overlay_num = np.asarray([_datenum_to_mpl_num(v, mdates) for v in overlay_datenum])

    bin_centres = CONTOUR_BINS[:-1] + np.diff(CONTOUR_BINS) / 2      # :221,229

    fig, ax = plt.subplots()
    fig.patch.set_facecolor("w")                                    # :257 set(gcf,'color','w')
    cs = ax.contourf(x_num, bin_centres, z, levels=CONTOUR_LEVELS, cmap="jet")  # :271-272,276
    fig.colorbar(cs, ax=ax)
    (line_thr,) = ax.plot(overlay_num, threshold, "g", linewidth=2)     # :278, 2*lower peak
    (line_ww,) = ax.plot(overlay_num, threshold_ww, "b", linewidth=2)   # :279, freq. min (fit)
    (line_ak,) = ax.plot(overlay_num, threshold_ak, "r", linewidth=2)   # :280, freq. min (hist)

    ax.set_ylim(1e-7, 1)                                             # :282
    ax.set_yscale("log")
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))      # :282 datetick('x','HH:MM')
    ax.set_title(f"Inter-arrival Time Frequency for {date_string}")  # :283
    ax.set_xlabel("Time")                                            # :284
    ax.set_ylabel("Inter-arrival Time [sec]")
    # :285-286's legend has a fourth entry, 'frequency', for the contour fill itself -- omitted
    # here since a filled contourf has no single Line2D handle to attach it to without a proxy
    # artist, and this plot is not checked for pixel/legend content (see the module docstring).
    ax.legend([line_thr, line_ww, line_ak],
             ["2*lower peak", "freq. min between peaks from fit",
              "freq. min between peaks in hist"], fontsize=6, loc="upper left")  # :285-286
    return fig, ax
