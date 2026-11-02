# SPDX-License-Identifier: BSD-3-Clause
"""Shared leaf: the sizeDist time-conversion helpers both engines use.

Moved verbatim from ``arrayprobe.sizedist``;
that module re-imports them, so its names still resolve.  Pure functions: no
module state, no numba, nothing a worker pickles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from arrayprobe_uiops.matlab_compat import (
    madd,
    mcolon,
    mdiv,
    mfind,
    mmax,
    mmul,
    mpow,
    msqrt,
    msum,
    msum_extra,
    nanmean,
    nansum,
)


def _hhmmss_to_insec(a):
    """``hhmmss2insec.m``, vectorised.

    ``time_convert.hhmmss_to_insec`` is scalar (it calls ``float()``); this stage
    applies it to whole arrays.  All three terms are floored, seconds included
    (``floor(mod(timehhmmss,100))`` in stock v3.1.4, the ORACLES variant and v3.5
    alike; Octave 11.3 gives ``hhmmss2insec(120000.5) = 43200`` on all three).
    Every file-driven caller passes whole seconds, so the floor on the seconds
    term changes no written value.
    """
    t = np.asarray(a, dtype=np.float64)
    return (t // 10000) * 3600 + ((t % 10000) // 100) * 60 + np.floor(t % 100)


def _insec_to_hhmmss(a):
    """``insec2hhmmss.m``, vectorised -- the inverse of :func:`_hhmmss_to_insec`.

    ``timehhmmss = floor(insec/3600)*10000 + floor(mod(insec,3600)/60)*100 +
    floor(mod(insec,60))`` -- unlike :func:`_hhmmss_to_insec`, EVERY term is
    floored here, matching the real ``insec2hhmmss.m`` (confirmed by reading
    it directly, not assumed from the sibling function's convention).
    """
    s = np.asarray(a, dtype=np.float64)
    return (np.floor(s / 3600) * 10000
            + np.floor((s % 3600) / 60) * 100
            + np.floor(s % 60))


#: ``:1080`` -- the reject codes that count as an accepted particle.
GOOD_REJECT_CODES: str = "0HhuR"


#: ``:441`` -- the fourteen reject-criterion columns, in source order.  Computed
#: by MATLAB and never written to the file; kept because it is cheap and is the
#: only per-code breakdown the stage produces.
REJECT_CRITERION_CODES: tuple[str, ...] = (
    "centerin", "0", "H", "h", "u", "a", "t", "p", "s", "z", "i", "A", "S", "R",
)


_VARS = (
    ("time", ("Time",), (("units", "HHMMSS"), ("name", "Time"))),
    ("bin_min", ("CIPcorrlen",), (("units", "millimeter"),
     ("long_name", "bin minimum size"), ("short_name", "bin min"))),
    ("bin_max", ("CIPcorrlen",), (("units", "millimeter"),
     ("long_name", "bin maximum size"), ("short_name", "bin max"))),
    ("bin_mid", ("CIPcorrlen",), (("units", "millimeter"),
     ("long_name", "bin midpoint size"), ("short_name", "bin mid"))),
    ("bin_dD", ("CIPcorrlen",), (("units", "millimeter"),
     ("long_name", "bin size"), ("short_name", "bin size"))),
    ("conc_minR", ("CIPcorrlen", "Time"), (("units", "cm-4"),
     ("long_name", "Size distribution using Dmax"), ("short_name", "N(Dmax)"))),
    ("area", ("CIParealen", "CIPcorrlen", "Time"), (("units", "cm-4"),
     ("long_name", "binned area ratio"), ("short_name", "binned area ratio"))),
    ("conc_AreaR", ("CIPcorrlen", "Time"), (("units", "cm-4"),
     ("long_name", "Size distribution using area-equivalent Diameter"),
     ("short_name", "N(Darea)"))),
    ("n", ("Time",), (("units", "cm-3"),
     ("long_name", "number concentration"), ("short_name", "N"))),
    ("total_area", ("CIPcorrlen", "Time"), (("units", "mm2/cm4"),
     ("long_name", "projected area (extinction)"), ("short_name", "Ac"))),
    ("mass", ("CIPcorrlen", "Time"), (("units", "g/cm4"),
     ("long_name", "mass using m-D relations"), ("short_name", "mass"))),
    ("habitsd", ("Habit", "CIPcorrlen", "Time"), (("units", "cm-4"),
     ("long_name", "Size Distribution with Habit"),
     ("short_name", "habit SD"))),
    # 'mm' is the variant text; _write swaps in AttributeText.re_units
    # (stock :1935/:2031 says 'um').
    ("re", ("Time",), (("units", "mm"),
     ("long_name", "effective radius"), ("short_name", "Re"))),
    ("ar", ("Time",), (("units", "100/100"),
     ("long_name", "Area Ratio"), ("short_name", "AR"))),
    ("massBL", ("CIPcorrlen", "Time"), (("units", "g/cm4"),
     ("long_name", "mass using Baker and Lawson method"),
     ("short_name", "mass_BL"))),
    ("Reject_ratio", ("Time",), (("units", "100/100"),
     ("long_name", "Reject Ratio"),)),
    ("vt", ("CIPcorrlen", "Time"), (("units", "g/cm4"),
     ("long_name", "Mass-weighted terminal velocity"),)),
    ("Prec_rate", ("CIPcorrlen", "Time"), (("units", "mm/hr"),
     ("long_name", "Precipitation Rate"),)),
    ("habitmsd", ("Habit", "CIPcorrlen", "Time"), (("units", "g/cm-4"),
     ("long_name", "Mass Size Distribution with Habit"),
     ("short_name", "Habit Mass SD"))),
    ("Calcd_area", ("CIPcorrlen", "Time"), (("units", "mm^2/cm4"),
     ("long_name", "Particle Area Calculated using A-D realtions"),
     ("short_name", "Ac_calc"))),
    ("count", ("CIPcorrlen", "Time"), (("units", "1"),
     ("long_name",
      "number count for partial images without any correction"),)),
)

_VARS_ASPECT = (
    ("mean_aspect_ratio_rectangle", ("CIPcorrlen", "Time"), (("units", "1"),
     ("long_name", "Aspect Ratio by Rectangle fit"),)),
    ("mean_aspect_ratio_ellipse", ("CIPcorrlen", "Time"), (("units", "1"),
     ("long_name", "Aspect Ratio by Ellipse fit"),)),
)

_VARS_TAIL = (
    ("mean_area_ratio", ("CIPcorrlen", "Time"), (("units", "1"),
     ("long_name", "Area Ratio"),)),
    ("mean_perimeter", ("CIPcorrlen", "Time"), (("units", "um"),
     ("long_name", "mean perimeter"),)),
)

_VARS_INTARR = (
    ("sum_IntArr", ("Time",), (("units", "s"), ("long_name",
     "sum of inter-arrival times, excluding the overload time for particles "
     "affected by saving of image data"),)),
    ("sample_vol", ("CIPcorrlen", "Time"), (("units", "cm^3"),
     ("long_name", "sample volume for each bin"),)),
)

#: ``:1852-1938`` -- the nineteen ``REJ_`` twins, in definition order.  There is
#: **no** ``REJ_Reject_ratio``, and the two aspect-ratio variables appear here
#: whether or not ``iCreateAspectRatio`` is set.
_REJ_ORDER = (
    "conc_minR", "area", "conc_AreaR", "n", "total_area", "mass", "habitsd",
    "re", "ar", "massBL", "vt", "Prec_rate", "habitmsd", "Calcd_area", "count",
    "mean_aspect_ratio_rectangle", "mean_aspect_ratio_ellipse",
    "mean_area_ratio", "mean_perimeter",
)


def _num2str(x):
    """MATLAB ``num2str`` for the two reacceptance numbers in the attribute."""
    v = float(x)
    if v == int(v):
        return str(int(v))
    return f"{v:.4g}"


def _optional_parameters(bad, aspect, intarr):
    """``:1705-1728`` -- the eight-way attribute string, in source order."""
    parts = []
    if bad:
        parts.append("SDs from rejected particles")
    if aspect:
        parts.append("SDs w/ aspect ratio")
    if intarr:
        parts.append("Sample volume info")
    return ", ".join(parts) if parts else "None"


_REJ_ATTS = {
    "conc_minR": (("units", "cm-4"),
                  ("long_name",
                   "Size distribution of rejected particles using Dmax"),
                  ("short_name", "N(Dmax) rejected")),
    "area": (("units", "cm-4"),
             ("long_name", "binned area ratio of rejected particles"),
             ("short_name", "binned area ratio of rejected particles")),
    "conc_AreaR": (("units", "cm-4"),
                   ("long_name", "Size distribution of rejected particles "
                    "using area-equivalent Diameter"),
                   ("short_name", "N(Darea) rejected")),
    "n": (("units", "cm-3"),
          ("long_name", "number concentration of rejected particles"),
          ("short_name", "N_rejected")),
    "total_area": (("units", "mm2/cm4"),
                   ("long_name",
                    "projected area (extinction) of rejected particles"),
                   ("short_name", "Ac_rejected")),
    "mass": (("units", "g/cm4"),
             ("long_name", "mass of rejected particles using m-D relations"),
             ("short_name", "mass_rejected")),
    "habitsd": (("units", "cm-4"),
                ("long_name",
                 "Size Distribution with Habit of rejected particles"),
                ("short_name", "habit SD rejected")),
    # 'mm' is the variant text; _write swaps in AttributeText.re_units
    # (stock :1935/:2031 says 'um').
    "re": (("units", "mm"),
           ("long_name", "effective radius of rejected particles"),
           ("short_name", "Re_rejected")),
    "ar": (("units", "100/100"),
           ("long_name", "Area Ratio of rejected particles"),
           ("short_name", "AR_rejected")),
    "massBL": (("units", "g/cm4"),
               ("long_name", "mass of rejected particles using Baker and "
                "Lawson method"),
               ("short_name", "mass_BL_rejected")),
    "Reject_ratio": (("units", "100/100"), ("long_name", "Reject Ratio")),
    "vt": (("units", "g/cm4"),
           ("long_name",
            "Mass-weighted terminal velocity of rejected particles")),
    "Prec_rate": (("units", "mm/hr"),
                  ("long_name", "Precipitation Rate of rejected particles")),
    "habitmsd": (("units", "g/cm-4"),
                 ("long_name", "Mass Size Distribution with Habit of "
                  "rejected particles"),
                 ("short_name", "Habit Mass SD rejected")),
    "Calcd_area": (("units", "mm^2/cm4"),
                   ("long_name", "Particle Area of rejected particles "
                    "Calculated using A-D realtions"),
                   ("short_name", "Ac_calc_rejected")),
    "count": (("units", "1"),
              ("long_name", "number count of rejected particles for partial "
               "images without any correction")),
    "mean_aspect_ratio_rectangle": (("units", "1"),
                                    ("long_name", "Aspect Ratio of rejected "
                                     "particles by Rectangle fit")),
    "mean_aspect_ratio_ellipse": (("units", "1"),
                                  ("long_name", "Aspect Ratio of rejected "
                                   "particles by Ellipse fit")),
    "mean_area_ratio": (("units", "1"),
                        ("long_name", "Area Ratio of rejected particles")),
    "mean_perimeter": (("units", "um"),
                       ("long_name", "mean perimeter of rejected particles")),
}


# ---------------------------------------------------------------------------
# Moved verbatim from arrayprobe.sizedist (v3.1.4 cut S2, 2026-10-10): the
# population binner, shattered-particle reacceptance, midnight rollover, the six
# d_choice definitions and the module constants they read.  arrayprobe.sizedist
# re-exports every name (same objects).
# ---------------------------------------------------------------------------

#: ``warn_suspect_rollover`` logs under the v3.1.4 module's name, as before the move.
_logger = logging.getLogger("arrayprobe.sizedist")

#: ``:1207-1248`` -- the ten habit codes, in the order they are binned into the
#: ``Habit`` dimension.  ``holroyd.m`` can emit more than these ten; anything not
#: listed simply lands in no habit slice, which is upstream behaviour, not a
#: transcription gap.
HABIT_ORDER: str = "slothigdaI"


#: ``:475`` -- ``area_bins = 0:.1:1.01``, giving eleven edges and ten slices.
AREA_BINS: np.ndarray = np.array(
    [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)


@dataclass(frozen=True)
class RejectThresholds:
    """The reject constants that live in ``sizeDist.m`` rather than in
    ``calculate_reject_unified.m``.

    One field today.  It is a dataclass and not a bare float because the value
    is a *provable* divergence between the trees with ``file:line`` provenance on
    both sides -- the same standard ``FidelityProfile`` holds itself to -- and
    because hard-wiring either number is exactly the error this project has
    made three times.
    """

    area_ratio_z: float
    """``:849`` -- ``auto_reject(area_ratio < X) = 'z'``."""

    provenance: str


ORACLES_REJECT = RejectThresholds(
    area_ratio_z=0.5,
    provenance=(
        "sizeDist.m:849 of the variant that wrote the archived product sets "
        "area_ratio < .5, where stock sizeDist.m uses .2."
    ),
)


STOCK_REJECT = RejectThresholds(
    area_ratio_z=0.2,
    provenance=(
        "UIOPS-v3.1.4 sizeDist.m and the OptArrProbDataProcessing variant tree "
        "both use .2 -- measured, both trees, 2026-08-19."
    ),
)


def _d_length(im_length, im_width, diodesize, minr):
    """``:756`` -- ``d_choice == 1``.

    ``im_length`` is ``int16`` (``imgProc_sm.m:299``); MATLAB keeps the integer
    type across ``* diodesize`` and saturates.
    :func:`arrayprobe.matlab_compat.mmul` carries
    that rule; a plain ``*`` would let NumPy silently promote to float64 and
    fix the bug.
    """
    return mmul(im_length, diodesize)


def _d_width(im_length, im_width, diodesize, minr):
    """``:758`` -- ``d_choice == 2``. Same int16 diameter saturation trap as :func:`_d_length`."""
    return mmul(im_width, diodesize)


def _d_mean(im_length, im_width, diodesize, minr):
    """``:760`` -- ``d_choice == 3``.

    ``(im_length + im_width)/2 * diodesize`` -- three int-dominant ops in a
    row, each saturating in turn.
    """
    return mmul(mdiv(madd(im_length, im_width), 2.0), diodesize)


def _d_hypot(im_length, im_width, diodesize, minr):
    """``:762`` -- ``d_choice == 4``.

    ``sqrt(im_width.^2+im_length.^2) * diodesize``. The squares and their sum
    saturate as int16, but ``sqrt`` **promotes** to double, so the final
    ``* diodesize`` is an ordinary double multiply -- this is the one d_choice
    that escapes the zero-collapse, though the radicand still saturates above
    181 diodes. See :func:`arrayprobe.matlab_compat.msqrt`.
    """
    return msqrt(madd(mpow(im_width, 2.0), mpow(im_length, 2.0))) * diodesize


def _d_max(im_length, im_width, diodesize, minr):
    """``:764`` -- ``d_choice == 5``.

    ``max`` on two int16 arrays stays int16 (no promotion), so the trailing
    ``* diodesize`` still saturates. Uses :func:`arrayprobe.matlab_compat.mmax`
    rather than a bare ``np.maximum`` -- behaviourally identical for this port's
    actual inputs (``im_width``/``im_length`` are always the same dtype as each
    other), but correct rather than coincidental if that ever stops being true.
    """
    return mmul(mmax(im_width, im_length), diodesize)


def _d_minr(im_length, im_width, diodesize, minr):
    """``:766`` -- ``d_choice == 6``, the default in every UIOOPS run script.

    Reads ``image_diam_minR`` straight out of the proc file and does **not**
    rescale it; the struck-out ``% * diodesize`` at the end of that line is the
    author noticing the value is already in millimetres.  Contrast ``:669``.
    """
    return minr


_D_CHOICE_SPECS = (
    (1, "sizedist_length", _d_length, "L_x", "sizeDist.m:1054"),
    (2, "sizedist_width", _d_width, "L_y", "sizeDist.m:1056"),
    (3, "sizedist_mean", _d_mean, "mean(L_x,L_y)", "sizeDist.m:1058"),
    (4, "sizedist_hypot", _d_hypot, "hypotenuse(L_x,L_y)", "sizeDist.m:1060"),
    (5, "sizedist_max", _d_max, "max(L_x,L_y)", "sizeDist.m:1062"),
    (6, "sizedist_minR", _d_minr, "D of minimum enclosing circle",
     "sizeDist.m:1064"),
)


def _rollover_240000(x):
    """``:83-84`` and ``:544-545`` -- the midnight correction, bug included.

    ``x(find(diff(x)<0)+1:end) = x(find(diff(x)<0)+1:end) + 240000``.  MATLAB's
    colon operator collapses each vector operand to its **first** element, so
    only the first decrease is ever corrected; a flight crossing midnight twice
    keeps the second discontinuity.  An empty ``find`` makes the whole statement
    a silent no-op, which is the common case and must not raise.

    Mutates and returns ``x``, as the MATLAB statement does.
    """
    idx = mfind(np.diff(x) < 0) + 1          # 1-based, as MATLAB's find is
    rng = mcolon(idx, len(x))                # ...collapsed to its first element
    if rng.size:
        x[rng - 1] += 240000
    return x


def warn_suspect_rollover(x, engine: str) -> int:
    """Say so when the midnight correction is about to shift particles on no crossover.

    Diagnostic only -- it reads ``x`` and changes nothing, so the written bytes are the MATLAB's.
    ``sizeDist``'s correction (v3.1.4 ``:544-545``; v3.5's single-decrease branch ``:790-792``)
    adds 240000 to every particle after the first decrease in the particle clock, whatever its
    size. When that decrease fails the developers' own crossover test from v3.5
    (``sizeDist.m:796-797``: previous value ``> 230000`` and a drop ``> 230000``), it is a clock
    glitch, not midnight, and every later particle is filed a day late -- 2,899,268 of 3,796,565
    session-2 CIP particles on 2016-09-06, with nothing printed. Returns the number of particles
    the correction will move (0 when it is a real crossover or there is no decrease).
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    dec = np.flatnonzero(np.diff(x) < 0)
    if dec.size == 0:
        return 0
    d = int(dec[0])
    if x[d] > 230000 and x[d] - x[d + 1] > 230000:
        return 0
    moved = int(x.size - d - 1)
    _logger.warning(
        "sizeDist midnight correction (engine %s): particle %d steps back from %06d to %06d, "
        "which is not a day crossover (sizeDist.m:796-797's test fails), yet all %d later "
        "particles (%.1f %%) are shifted +240000 and filed a day late -- reproduced faithfully. "
        "To keep them, run the enhancement particle_time_glitch_fix "
        "(arrayprobe-enhancements, [enhancements] particle_time_glitch_fix = true) or a "
        "SODA-2 run.", engine, d + 1, int(x[d]), int(x[d + 1]), moved,
        100.0 * moved / x.size)
    return moved


def bin_index(values, kk):
    """Which ``kk`` bin each value falls in, or ``-1``.

    Source: the per-bin ``>= kk(j) & < kk(j+1)`` counts of ``sizeDist.m`` (UIOOPS v3.1.4), e.g.
    ``:1330-1333``.

    The source writes ``>= kk(j) & < kk(j+1)`` explicitly for every ``j``.  For a
    strictly increasing ``kk`` that is exactly a right-side search minus one,
    with everything below ``kk(1)`` or at/above ``kk(end)`` excluded.  NaN sorts
    to the end and is therefore excluded too, which is the MATLAB behaviour --
    both comparisons are false for NaN.

    Returned indices are 0-based, because they index Python accumulators rather
    than appearing in a transcribed expression.
    """
    v = np.asarray(values, dtype=np.float64)
    idx = np.searchsorted(kk, v, side="right") - 1
    idx[~((v >= kk[0]) & (v < kk[-1]))] = -1
    return idx


def _count_by_bin(idx, num_bins, mask=None):
    """``length(find(... >= kk(j) & ... < kk(j+1)))`` for every ``j`` at once."""
    sel = idx >= 0 if mask is None else (idx >= 0) & mask
    return np.bincount(idx[sel], minlength=num_bins).astype(np.float64)


def _nansum_by_bin(idx, values, num_bins, mask=None):
    """``nansum`` over each bin -- NaN counted as zero, empty bin giving 0."""
    v = np.asarray(values, dtype=np.float64)
    sel = (idx >= 0) & np.isfinite(v)
    if mask is not None:
        sel = sel & mask
    return np.bincount(idx[sel], weights=v[sel], minlength=num_bins)


def _nanmean_by_bin(idx, values, num_bins, mask=None):
    """``nanmean`` over each bin -- NaN ignored, empty or all-NaN bin giving NaN."""
    v = np.asarray(values, dtype=np.float64)
    sel = (idx >= 0) & np.isfinite(v)
    if mask is not None:
        sel = sel & mask
    total = np.bincount(idx[sel], weights=v[sel], minlength=num_bins)
    n = np.bincount(idx[sel], minlength=num_bins)
    out = np.full(num_bins, np.nan)
    np.divide(total, n, out=out, where=n > 0)
    return out


def _mean_or_nan(v, extra=False):
    """MATLAB ``mean`` of a possibly empty vector -- ``NaN``, silently.

    ``sum(x)/length(x)`` with MATLAB's in-order accumulation, not NumPy's
    pairwise one; see :func:`arrayprobe.matlab_compat.msum`.

    ``extra=True`` switches to Octave 11.3's compensated accumulator instead.
    That is **not** MATLAB behaviour and exists only so the oracle comparison
    can be exact -- see :func:`arrayprobe.matlab_compat.msum_extra` and
    ``run(octave_mean_extra=...)``.
    """
    a = np.asarray(v, dtype=np.float64)
    if a.size == 0:
        return np.float64(np.nan)
    total = msum_extra(a) if extra else msum(a)
    return np.float64(total / a.size)


@dataclass
class _BinnedSecond:
    """One second's per-bin accumulators, before binwidth normalisation."""

    dist_minR: np.ndarray
    dist_AreaR: np.ndarray
    habitsd: np.ndarray          # (num_bins, 10)
    habitmsd: np.ndarray         # (num_bins, 10)
    area: np.ndarray
    meanp: np.ndarray
    areaRatio1: np.ndarray
    #: ``:1257-1263`` -- filled only under ``iCreateAspectRatio``; ``None``
    #: otherwise, so the flag-off path allocates nothing and the flag-on path
    #: cannot silently fall back to a NaN row.
    aspectRatio: np.ndarray | None
    aspectRatio1: np.ndarray | None
    iwc: np.ndarray
    partarea: np.ndarray
    iwcbl: np.ndarray
    vt: np.ndarray
    pr: np.ndarray
    area_dist2: np.ndarray       # (num_bins, 10)


def _bin_second(sel, kk, num_bins):
    """Vectorised ``:1200-1289``.  ``sel`` is a :class:`_Selection`."""
    idx = bin_index(sel.diameter, kk)
    idx1 = bin_index(sel.diameter1, kk)

    habitsd = np.zeros((num_bins, 10))
    habitmsd = np.zeros((num_bins, 10))
    for h, code in enumerate(HABIT_ORDER):
        is_h = sel.habit == ord(code)
        habitsd[:, h] = _count_by_bin(idx, num_bins, is_h)
        # :1229 -- the mask is built over `good_one_sec_locs` and then applied to
        # the UNSLICED `good_iwc`.  Reproduced by slicing to the mask's length
        # first, which is what MATLAB's logical indexing does.
        habitmsd[:, h] = _nansum_by_bin(idx, sel.iwc_unsliced[:idx.size],
                                        num_bins, is_h)

    area_dist2 = np.zeros((num_bins, 10))
    for k in range(10):
        in_slice = (sel.ar >= AREA_BINS[k]) & (sel.ar < AREA_BINS[k + 1])
        area_dist2[:, k] = _count_by_bin(idx, num_bins, in_slice)

    return _BinnedSecond(
        dist_minR=_count_by_bin(bin_index(sel.diameter_minR, kk), num_bins),
        dist_AreaR=_count_by_bin(bin_index(sel.diameter_AreaR, kk), num_bins),
        habitsd=habitsd,
        habitmsd=habitmsd,
        area=_nansum_by_bin(idx, sel.area, num_bins),
        meanp=_nanmean_by_bin(idx, sel.perimeter, num_bins),
        areaRatio1=_nanmean_by_bin(idx1, sel.ar1, num_bins),
        # :1259,:1262 -- both indexed by `good_one_sec_locs1` and
        # `good_particle_diameter1`, i.e. the entire-in-excluded set, exactly
        # like areaRatio1 above and unlike every `idx` sibling.
        aspectRatio=(None if sel.aspect is None
                     else _nanmean_by_bin(idx1, sel.aspect, num_bins)),
        aspectRatio1=(None if sel.aspect1 is None
                      else _nanmean_by_bin(idx1, sel.aspect1, num_bins)),
        iwc=_nansum_by_bin(idx, sel.iwc, num_bins),
        partarea=_nansum_by_bin(idx, sel.partarea, num_bins),
        iwcbl=_nansum_by_bin(idx, sel.iwcbl, num_bins),
        vt=_nansum_by_bin(idx, sel.vt, num_bins),
        pr=_nansum_by_bin(idx, sel.pr, num_bins),
        area_dist2=area_dist2,
    )


def _bin_second_literal(sel, kk, num_bins):
    """``:1200-1289`` transcribed as written -- one ``j`` loop, one test per line.

    Not used in production (it is O(num_bins x n) per second); it exists so the
    vectorised path above has something to be proved equal to, and so a reader
    can check the transcription against the MATLAB without unpicking a bincount.
    """
    d = np.asarray(sel.diameter, dtype=np.float64)
    d1 = np.asarray(sel.diameter1, dtype=np.float64)
    # Named, not positional: the positional form silently mis-slotted every
    # field after the insertion point when `aspectRatio` was added in the
    # middle, which a `*(... for _ in range(8))` spread cannot make visible.
    out = _BinnedSecond(
        dist_minR=np.zeros(num_bins), dist_AreaR=np.zeros(num_bins),
        habitsd=np.zeros((num_bins, 10)), habitmsd=np.zeros((num_bins, 10)),
        area=np.zeros(num_bins), meanp=np.zeros(num_bins),
        areaRatio1=np.zeros(num_bins),
        aspectRatio=None if sel.aspect is None else np.zeros(num_bins),
        aspectRatio1=None if sel.aspect1 is None else np.zeros(num_bins),
        iwc=np.zeros(num_bins), partarea=np.zeros(num_bins),
        iwcbl=np.zeros(num_bins), vt=np.zeros(num_bins), pr=np.zeros(num_bins),
        area_dist2=np.zeros((num_bins, 10)))
    dminR = np.asarray(sel.diameter_minR, dtype=np.float64)
    dAreaR = np.asarray(sel.diameter_AreaR, dtype=np.float64)

    for j in range(num_bins):
        lo, hi = kk[j], kk[j + 1]
        out.dist_minR[j] = np.count_nonzero((dminR >= lo) & (dminR < hi))
        out.dist_AreaR[j] = np.count_nonzero((dAreaR >= lo) & (dAreaR < hi))

        in_bin = (d >= lo) & (d < hi)
        in_bin1 = (d1 >= lo) & (d1 < hi)

        for h, code in enumerate(HABIT_ORDER):
            is_h = (sel.habit == ord(code)) & in_bin
            out.habitsd[j, h] = np.count_nonzero(is_h)
            out.habitmsd[j, h] = nansum(sel.iwc_unsliced[:is_h.size][is_h])

        out.area[j] = nansum(sel.area[in_bin])
        out.meanp[j] = nanmean(sel.perimeter[in_bin])
        out.areaRatio1[j] = nanmean(sel.ar1[in_bin1])
        if sel.aspect is not None:                       # :1257-1263
            out.aspectRatio[j] = nanmean(sel.aspect[in_bin1])
            out.aspectRatio1[j] = nanmean(sel.aspect1[in_bin1])
        out.iwc[j] = nansum(sel.iwc[in_bin])
        out.partarea[j] = nansum(sel.partarea[in_bin])
        out.iwcbl[j] = nansum(sel.iwcbl[in_bin])
        out.vt[j] = nansum(sel.vt[in_bin])
        out.pr[j] = nansum(sel.pr[in_bin])

        for k in range(10):
            out.area_dist2[j, k] = np.count_nonzero(
                (sel.ar >= AREA_BINS[k]) & (sel.ar < AREA_BINS[k + 1]) & in_bin
            )

    return out


@dataclass
class _Selection:
    """One second's accepted (or rejected) particles -- ``:1126-1147``.

    ``diameter`` and ``diameter_minR`` are the same array in the source
    (``:1146``); both names are kept because the MATLAB uses both and a later
    change to one and not the other should be visible.
    """

    diameter_minR: np.ndarray
    diameter_AreaR: np.ndarray
    diameter: np.ndarray
    diameter1: np.ndarray
    habit: np.ndarray
    area: np.ndarray
    perimeter: np.ndarray
    ar: np.ndarray
    ar1: np.ndarray
    iwc: np.ndarray
    iwc_unsliced: np.ndarray
    partarea: np.ndarray
    iwcbl: np.ndarray
    vt: np.ndarray
    pr: np.ndarray
    #: ``:685-686`` -- ``image_RectangleW/L`` and ``image_EllipseW/L``, read
    #: only under ``iCreateAspectRatio``.  ``None`` when the flag is off, which
    #: is the default in both MATLAB trees; last with a default so the callers
    #: that predate the flag construct unchanged.
    aspect: np.ndarray | None = None
    aspect1: np.ndarray | None = None


def _reaccept_shattered(auto_reject, int_arr, int_arr3, ia_thresh,
                        particle_diameter_minR, cfg) -> None:
    """``sizeDist.m:894-912`` / ``:1155-1173`` -- put one shattered particle back.

    **The source carries this block twice, once under each shattering gate**, and
    the two copies differ only in which threshold array they read: `iaThresh`
    under `iaThreshType == 1`, `intar_threshold(i)` under `== 2`. Passing the
    threshold in is therefore a faithful sharing of one behaviour, not a merge of
    two -- and it means a future correction cannot be applied to one copy and
    forgotten in the other, which is how the two drifted apart in the first place
    (the `:1155` copy still carries Stechman's original attribution while `:894`
    carries Finlon's 2017 revision).

    The rationale, in the source's own words: particles flagged as shattered "may
    in fact be the result of diffraction fringes", which are expected to be
    LARGER than fragments and to arrive with a particularly small inter-arrival.
    So within one shattering event the largest particle above ``reaccptD`` that
    also arrives faster than ``reaccptMaxIA`` is restored with the code ``'R'``,
    which ``GOOD_REJECT_CODES`` counts as accepted.

    **TWO PRESERVED BUGS, both from one MATLAB idiom.**
    The reacceptance loop (``sizeDist.m:1036``) builds its range from two *vectors*
    (the found begin and end indices), and ``a:b`` uses only the first element of each:

    1. only the FIRST shattering event in a second is ever scanned, however many
       the second holds; and
    2. if the first ``rEnd`` precedes the first ``rBegin`` -- which an event
       beginning at a block boundary produces, because that block's first
       inter-arrival is the sentinel 0 -- the range is empty and **nothing is
       reaccepted at all**.

    The second was demonstrated rather than argued: stock, run under Octave on a
    fixture of exactly that shape, binned one particle where a reacceptance would
    have made it two (``octave_oracle/run_reacceptance_bank.py``).
    """
    r_begin = (int_arr > ia_thresh) & (int_arr3 < ia_thresh)
    r_end = (int_arr < ia_thresh) & (int_arr3 > ia_thresh)

    max_particle = cfg.reaccpt_d
    e_index = None
    begins = np.flatnonzero(r_begin)
    ends = np.flatnonzero(r_end)
    if begins.size and ends.size:
        # `find(...)` on an empty match yields an empty range in MATLAB and the
        # loop simply does not run; the same is true here, without the ambiguity
        # of an empty argmax.
        for i_event in range(int(begins[0]), int(ends[0]) + 1):
            if (particle_diameter_minR[i_event] > max_particle
                    and int_arr[i_event] < cfg.reaccpt_max_ia):
                max_particle = particle_diameter_minR[i_event]
                e_index = i_event
    if e_index is not None:
        # `auto_reject(eIndex) = 'R'` with `eIndex = []` is a no-op in MATLAB,
        # which is what "no candidate" means.
        auto_reject[e_index] = ord("R")


def _process_population(i, mask, entirein, image_time, one_sec_times, kk,
                        num_bins, binwidth, diameter_minR, diameter_AreaR,
                        habit1, area, perimeter, area_ratio, particle_mass,
                        calcd_area, particle_massbl, particle_vt, particle_pr,
                        store, octave_mean_extra=False,
                        aspect_ratio=None, aspect_ratio1=None):
    """``:1126-1342`` for one population (accepted or rejected).

    The MATLAB writes this block twice, once per population, with every name
    prefixed ``bad_`` in the second copy.  The two are identical line for line
    -- verified by diffing ``:1126-1342`` against ``:1151-1482`` -- so they are
    one function here.  Two asymmetries between the populations sit outside it
    and are preserved at their own call sites: the ``entirein``/``centerin``
    filter at ``:1094-1100``, and the four scalars ``:1327``/``:1337-1340``
    rewrite when the accepted population is empty.

    Returns True when this second produced no particles of this population,
    which is what the caller needs in order to apply that second asymmetry.
    """
    mask1 = mask & (entirein == 0)
    times = image_time[mask]
    times1 = image_time[mask1]

    locs = np.flatnonzero((times >= one_sec_times[i])
                          & (times < one_sec_times[i + 1]))
    locs1 = np.flatnonzero((times1 >= one_sec_times[i])
                           & (times1 < one_sec_times[i + 1]))

    ar1_all = area_ratio[mask1]
    store["one_sec_ar"][i] = _mean_or_nan(ar1_all[locs1], octave_mean_extra)

    if locs.size == 0:
        # :1316-1327.  Note what is NOT reset: `particle_area` (-> total_area)
        # and `cip2_meanp` (-> mean_perimeter) keep their NaN fill, while every
        # sibling goes to 0.  So a second with data but no accepted particle has
        # conc_minR == 0 and total_area == NaN.  Upstream asymmetry, preserved.
        store["dist_minR"][i, :] = 0
        store["dist_AreaR"][i, :] = 0
        store["area_dist2"][i, :, :] = 0
        store["partarea"][i, :] = 0
        store["iwc"][i, :] = 0
        store["iwcbl"][i, :] = 0
        store["vt"][i, :] = 0
        store["pr"][i, :] = 0
        store["re"][i] = 0
        store["habitsd"][i, :, :] = 0
        store["habitmsd"][i, :, :] = 0
        return True

    d_all = diameter_minR[mask]
    sel = _Selection(
        diameter_minR=d_all[locs],
        diameter_AreaR=diameter_AreaR[mask][locs],
        diameter=d_all[locs],
        diameter1=diameter_minR[mask1][locs1],
        habit=habit1[mask][locs],
        area=area[mask][locs],
        perimeter=perimeter[mask][locs],
        ar=area_ratio[mask][locs],
        ar1=ar1_all[locs1],
        # :1134-1135 / :1159-1160 -- sliced by `mask1`, the entire-in-excluded
        # population, then by `locs1`.  The same two-step every `1`-suffixed
        # name in this block takes.
        aspect=(None if aspect_ratio is None else aspect_ratio[mask1][locs1]),
        aspect1=(None if aspect_ratio1 is None else aspect_ratio1[mask1][locs1]),
        iwc=particle_mass[mask][locs],
        iwc_unsliced=particle_mass[mask],
        partarea=calcd_area[mask][locs],
        iwcbl=particle_massbl[mask][locs],
        vt=particle_vt[mask][locs],
        pr=particle_pr[mask][locs],
    )
    b = _bin_second(sel, kk, num_bins)

    # :1293-1309 -- normalise by binwidth and convert mm -> cm.
    store["dist_minR"][i, :] = b.dist_minR / binwidth * 10
    store["dist_AreaR"][i, :] = b.dist_AreaR / binwidth * 10
    store["iwc"][i, :] = b.iwc / binwidth * 10
    store["iwcbl"][i, :] = b.iwcbl / binwidth * 10
    store["vt"][i, :] = b.vt / binwidth * 10
    store["pr"][i, :] = b.pr / binwidth * 10
    store["partarea"][i, :] = b.partarea / binwidth * 10
    store["area"][i, :] = b.area / binwidth * 10
    store["habitsd"][i, :, :] = b.habitsd / binwidth[:, None] * 10
    store["habitmsd"][i, :, :] = b.habitmsd / binwidth[:, None] * 10
    store["area_dist2"][i, :, :] = b.area_dist2 / binwidth[:, None] * 10
    store["meanp"][i, :] = b.meanp
    store["areaRatio1"][i, :] = b.areaRatio1
    if b.aspectRatio is not None:
        store["aspectRatio"][i, :] = b.aspectRatio
        store["aspectRatio1"][i, :] = b.aspectRatio1

    # :1312 -- Fu (1996) generalized effective radius.  Plain `sum`, not
    # `nansum`, so a NaN anywhere in the row propagates; neither input can carry
    # one, both having just come out of a nansum.
    with np.errstate(divide="ignore", invalid="ignore"):
        store["re"][i] = ((np.sqrt(3) / (3 * 0.91)) * 1000
                          * (msum(store["iwc"][i, :] / binwidth)
                             / msum(store["area"][i, :] / binwidth)) * 1000)
    return False


#: ``d_choice`` -> registry key, and the ``Dmax Definition`` attribute string the
#: file carries for it (``:1680-1692``).  Filled here; ``arrayprobe.sizedist``
#: registers the same six functions with ``arrayprobe.sizing``.
D_CHOICE: dict[int, tuple[str, str]] = {
    _n: (_key, _label) for _n, _key, _fn, _label, _prov in _D_CHOICE_SPECS
}
