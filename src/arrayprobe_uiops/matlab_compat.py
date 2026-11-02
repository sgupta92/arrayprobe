# SPDX-License-Identifier: BSD-3-Clause
"""MATLAB language semantics that NumPy does not reproduce.

This module exists so that a line-by-line transliteration of UIOOPS v3.1.4 keeps
MATLAB's behaviour, including its bugs.  Every helper carries the file:line of
the UIOOPS call site that motivates it.  MATLAB source of truth:
``UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/``.



Fidelity doctrine: preserve bugs, do not fix them.  A "fix" that changes output
is a defect here.  Behaviour-changing deviations belong behind opt-in flags that
default OFF.

Integer semantics below were verified in Octave 11.3.0 on 2026-08-19 (Octave
implements MATLAB-compatible saturating integer arithmetic)::

    class(int16(37)*0.010) -> int16      int16(37)*0.010  -> 0
    int16(50)*0.010        -> 1          int16(-50)*0.010 -> -1
    int16(300)^2           -> 32767      int16(5)/int16(2) -> 3
    sqrt(int16(10))        -> 3.1623     (a DOUBLE -- sqrt promotes)
"""

from __future__ import annotations

import datetime as _dt
import math

import numpy as np

__all__ = [
    "mround", "mint8", "mint16", "mint32", "mdouble",
    "madd", "msub", "mmul", "mdiv", "mpow", "msqrt", "mmax",
    "mcolon", "mfind",
    "dec2bin", "dec2bin_concat", "dec2bin_bits", "bin2dec",
    "nansum", "nanmean",
    "datenum", "datestr",
    "mchar", "REJECT_CODES", "REJECT_CODE_WORDS", "UNREACHABLE_REJECT_CODES", "HOLROYD_HABITS",
    "mvertcat", "mhorzcat", "mdiff",
    "MGrowVector",
    "to0", "to1",
    "MatlabIndexError",
]


class MatlabIndexError(IndexError):
    """Raised where MATLAB raises ``Index exceeds matrix dimensions``.

    A run that would have died in MATLAB must die here too: returning a
    truncated result instead would silently turn a failed run into a
    plausible-looking one.

    Three call sites so far.  The earlier translation's SPEC reader raises it under
    :attr:`~arrayprobe.profiles.FidelityProfile.spec_buffer_guard` ``False``
    (the production variant, which predates the 2017-03-08 guards);
    ``dropsize.py`` raises it for a negative chord, where ``dropsize.m:220-222``
    indexes its lookup tables with ``round(chord * 10)`` and never checks the
    sign; and the earlier translation's ``sizeDist`` raises it for a single-particle last block
    under
    ``tree='production'``, where the production-variant ``sizeDist.m:713-716`` indexes
    an empty ``diff`` result at ``end`` == 0 (an earlier port version had
    been applying stock's Finlon 02/09/18 guard to a tree that has none, so it
    completed where MATLAB aborts).
    """


# --------------------------------------------------------------------------
# Rounding and integer casts
# --------------------------------------------------------------------------

def mround(x):
    """MATLAB ``round``: half away from zero, elementwise.

    Python and NumPy round half to even -- ``np.round(2.5) == 2`` but MATLAB
    ``round(2.5) == 3``.

    ``floor(abs(x) + 0.5)`` is NOT this function: the addition itself rounds, so
    ``0.49999999999999994`` and every odd integer above 2^52 came out one too
    high (the same defect a review fixed in the v3.5 helpers, its findings
    2 and 6).  ``abs(x) - floor(abs(x))`` is exact for every finite double, so the
    half is tested on that instead.

    Provenance: ``dropsize.m:198`` and ``dropsize.m:219``, where the result is
    used directly as a 1-based lookup-table index (``dropsize.m:199-200,220-221``),
    so an off-by-one changes the reported diameter.  ``dropsize`` is called from
    ``imgProc_sm.m:834``.
    """
    a = np.asarray(x, dtype=np.float64)
    out = np.sign(a) * _round_abs_half_up(np.abs(a))
    # sign(0)*... is 0.0, and NaN/inf propagate unchanged.
    return out if out.ndim else out[()]


def _round_abs_half_up(a):
    """``round`` of a non-negative array, half up, with no rounding in the test:
    ``a - floor(a)`` is exact for every finite double.  NaN and inf pass through
    (``inf - inf`` is NaN, which compares False, so ``floor(inf)`` is kept)."""
    f = np.floor(a)
    with np.errstate(invalid="ignore"):
        return f + (a - f >= 0.5)


def _saturating_cast(x, dtype):
    """MATLAB integer cast: round half away from zero, then saturate.

    MATLAB never wraps on integer overflow -- it clamps to the type's range.
    ``int16(300)^2`` is 32767, not 90000 and not the wrapped 24464.
    """
    info = np.iinfo(dtype)
    a = np.asarray(x, dtype=np.float64)
    r = np.sign(a) * _round_abs_half_up(np.abs(a))
    # NaN casts to 0 in MATLAB; +/-inf saturate.
    r = np.where(np.isnan(r), 0.0, r)
    r = np.clip(r, info.min, info.max)
    out = r.astype(dtype)
    return out if out.ndim else out[()]


def mint8(x):
    """MATLAB ``int8(x)`` -- rounds half away from zero, saturates."""
    return _saturating_cast(x, np.int8)


def mint16(x):
    """MATLAB ``int16(x)``.

    Provenance: ``imgProc_sm.m:898`` ``int16(images.auto_reject)`` and
    ``imgProc_sm.m:923`` ``int16(images.holroyd_habit)``.
    """
    return _saturating_cast(x, np.int16)


def mint32(x):
    """MATLAB ``int32(x)``."""
    return _saturating_cast(x, np.int32)


def mdouble(x):
    """MATLAB ``double(x)``."""
    out = np.asarray(x, dtype=np.float64)
    return out if out.ndim else out[()]


# --------------------------------------------------------------------------
# Integer-contaminating arithmetic (design doc trap T1)
# --------------------------------------------------------------------------

def _int_dtype_of(*operands):
    """Return the MATLAB integer dtype governing a binary op, or None.

    In MATLAB an integer operand wins over a double operand: the result keeps
    the integer type, rounding half away from zero and saturating.  Verified in
    Octave: ``class(int16(37)*0.010)`` is ``int16``.

    CALLER TRAP: a bare Python ``int`` literal (``2``, not ``2.0``) becomes an
    integer-dtype NumPy scalar and will be picked up here as though it were a
    MATLAB integer-typed operand -- even though a numeric literal in MATLAB
    source is ``double``.  Found 2026-08-27 porting ``sizeDist.m:760``
    (``.../2 * diodesize``): ``mdiv(sum_array, 2)`` silently forced integer
    rounding on an already-``double`` ``sum_array``.  Always pass ``2.0``, not
    ``2``, for a MATLAB literal operand.
    """
    for op in operands:
        dt = np.asarray(op).dtype
        if np.issubdtype(dt, np.integer):
            return dt
    return None


def _binary(a, b, fn):
    dt = _int_dtype_of(a, b)
    raw = fn(np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64))
    if dt is None:
        return raw if raw.ndim else raw[()]
    return _saturating_cast(raw, dt)


def madd(a, b):
    """MATLAB ``a + b`` with integer dominance and saturation."""
    return _binary(a, b, np.add)


def msub(a, b):
    """MATLAB ``a - b`` with integer dominance and saturation."""
    return _binary(a, b, np.subtract)


def mmul(a, b):
    """MATLAB ``a .* b`` with integer dominance and saturation.

    This is the integer-saturation trap.  ``sizeDist.m:770-771`` reads
    ``image_width``/``image_length``, declared ``'short'`` (int16) at
    ``imgProc_sm.m:295,299``.  With ``diodesize == 0.010`` for the 2DS
    (``sizeDist.m:179,264,368``), ``sizeDist.m:882,884,886,890`` produce an
    int16 array that is almost entirely ZERO.  That contaminates ``area_ratio``
    at ``sizeDist.m:984`` and therefore ``auto_reject`` at ``:985``.

    Only ``d_choice == 6`` (``sizeDist.m:892``) escapes -- which is exactly what
    ``run_sizeDist_Munich.m:16`` uses, presumably why the bug survived.  NumPy
    would give float64 here and silently FIX the bug, breaking bit-for-bit
    comparison against the reference output.
    """
    return _binary(a, b, np.multiply)


def mdiv(a, b):
    """MATLAB ``a ./ b`` with integer dominance, rounding and saturation.

    MATLAB integer division ROUNDS, it does not truncate:
    ``int16(5)/int16(2) == 3``.  Verified in Octave.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return _binary(a, b, np.divide)


def mpow(a, b):
    """MATLAB ``a .^ b`` with integer dominance and saturation.

    ``int16(300)^2 == 32767``.  Relevant at ``sizeDist.m:888``, where
    ``im_width.^2 + im_length.^2`` saturates before the sqrt.
    """
    return _binary(a, b, np.power)


def msqrt(x):
    """MATLAB ``sqrt`` -- PROMOTES an integer argument to double.

    This does NOT follow the saturating-integer rule that mmul/mpow follow.
    Verified in Octave: ``sqrt(int16(10))`` is 3.1623, class ``double``.

    Consequence for ``sizeDist.m:888``
    (``sqrt(im_width.^2+im_length.^2) * diodesize``): the squares and their sum
    saturate as int16, sqrt then promotes to double, and the final multiply
    stays double.  So ``d_choice == 4`` escapes the zero-collapse that hits
    d_choice 1, 2, 3 and 5 -- but carries int16 saturation INSIDE the radicand,
    which bites once im_width or im_length exceeds 181 diodes.
    """
    with np.errstate(invalid="ignore"):
        out = np.sqrt(np.asarray(x, dtype=np.float64))
    return out if out.ndim else out[()]


def mmax(a, b):
    """MATLAB two-argument ``max`` with integer dominance.

    Provenance: ``sizeDist.m:890`` ``max(im_width, im_length) * diodesize``.
    """
    return _binary(a, b, np.maximum)


# --------------------------------------------------------------------------
# The colon operator and find
# --------------------------------------------------------------------------

def _first_or_empty(v):
    """MATLAB collapses a vector colon operand to its first element."""
    a = np.atleast_1d(np.asarray(v))
    if a.size == 0:
        return None
    return a.reshape(-1)[0]


def mcolon(a, b, step=1):
    """MATLAB ``a:b`` including its operand-collapsing rule.

    MATLAB uses only the FIRST element of a vector operand, and yields an empty
    range if either operand is empty.  Returns a 1-based integer ndarray; use
    :func:`to0` at the array boundary.

    All four call sites are latent UIOOPS bugs preserved deliberately:

    * ``sizeDist.m:98-99``   ``timehhmmss(find(diff(timehhmmss)<0)+1:end)``
    * ``sizeDist.m:657-658`` same, on ``image_time_hhmmssall``
    * ``sizeDist.m:1036``    the reacceptance loop over the shattering events,
      whose range runs from the first ``find`` of the event starts to the first
      ``find`` of the event ends
    * ``sizeDist.m:1169``    same, in the fixed-threshold branch

    In sites 1 and 2 an empty ``find`` makes the whole assignment a silent
    no-op, so this must not raise.  In sites 3 and 4 a descending range (an
    event that ends before the first one begins) yields an empty loop.
    """
    lo = _first_or_empty(a)
    hi = _first_or_empty(b)
    if lo is None or hi is None:
        return np.array([], dtype=np.int64)
    return np.arange(lo, hi + (1 if step > 0 else -1), step, dtype=np.int64)


def mfind(condition):
    """MATLAB ``find``: 1-based indices of nonzero elements.

    Orientation follows MATLAB: a row input gives a row, anything else gives a
    column.  Orientation matters downstream -- ``sizeDist.m:686``
    ``start_all = find(startindex)-1`` and ``IntArrAnalysis.m:37-38``.
    """
    a = np.asarray(condition)
    idx = np.flatnonzero(a) + 1
    if a.ndim == 2 and a.shape[0] == 1:
        return idx.reshape(1, -1)
    return idx.reshape(-1, 1) if a.ndim == 2 else idx


# --------------------------------------------------------------------------
# Binary string conversion
# --------------------------------------------------------------------------

_ZERO = ord("0")
_ONE = ord("1")


def dec2bin(v, width=None):
    """MATLAB ``dec2bin(V, N)`` -> ``(M, W)`` uint8 array of ASCII '0'/'1'.

    ``width`` is a MINIMUM, not a maximum: MATLAB widens rather than truncating
    when a value needs more bits.  ``imgProc_sm.m:568-571`` depends on this --
    it compares ``size(c,2)`` against ``diodenum`` and RETURNS from the whole
    function on mismatch.  Masking to N bits would make that guard dead code.

    Raises ValueError on negative input, matching MATLAB.  Reachable at
    ``imgProc_sm.m:562`` via ``65535 - data(start:j-1,:)``.

    Returns ASCII codes so that call sites transliterate directly:
    ``imgProc_sm.m:802,804,805`` do ``sum(c=='0',1)``.

    Provenance: ``imgProc_sm.m:556`` (2DC, 4x8), ``:559-560`` (2DS/Fast2DC, 8x8),
    ``:563-564`` (HVPS, 8x16), ``:582``, ``:589-590``, ``:655-656``, ``:699``;
    ``calculate_reject_unified.m:491,642`` call it without a width.
    """
    a = np.atleast_1d(np.asarray(v))
    if a.size and np.any(a < 0):
        raise ValueError(
            "dec2bin: negative input (MATLAB errors here; reachable at "
            "imgProc_sm.m:562 when data exceeds 65535)"
        )
    vals = a.reshape(-1).astype(np.int64)
    needed = 1 if vals.size == 0 else max(1, int(max(vals, default=0)).bit_length())
    w = needed if width is None else max(int(width), needed)
    shifts = np.arange(w - 1, -1, -1, dtype=np.int64)
    bits = (vals[:, None] >> shifts[None, :]) & 1
    return (bits + _ZERO).astype(np.uint8)


def dec2bin_bits(v, width=None):
    """Boolean form of :func:`dec2bin` for the hot path (True == '1')."""
    return dec2bin(v, width) == _ONE


def dec2bin_concat(columns, width):
    """The ``[dec2bin(X(:,1),w), dec2bin(X(:,2),w), ...]`` idiom, fused.

    Returns the ``(nslices, ncols*width)`` char matrix MATLAB calls ``c``.
    Provenance: ``imgProc_sm.m:556``, ``:559-560``, ``:563-564``.
    """
    cols = np.asarray(columns)
    if cols.ndim == 1:
        cols = cols.reshape(-1, 1)
    return np.hstack([dec2bin(cols[:, k], width) for k in range(cols.shape[1])])


def bin2dec(chars):
    """MATLAB ``bin2dec``.  Row -> float scalar; ``(M,N)`` -> ``(M,)`` float64.

    Returns double, as MATLAB does.  UIOOPS never exceeds 40 bits
    (``imgProc_sm.m:591``), so double precision is exact throughout.

    Provenance: ``imgProc_sm.m:583``, ``:591``, ``:658-662`` (1-based inclusive
    substring slices of a 1x40 row), ``:699``;
    ``calculate_reject_unified.m:465-485,599-635``.
    """
    if isinstance(chars, str):
        a = np.frombuffer(chars.encode("ascii"), dtype=np.uint8).reshape(1, -1)
    else:
        a = np.asarray(chars, dtype=np.uint8)
        if a.ndim == 1:
            a = a.reshape(1, -1)
    bits = (a == _ONE).astype(np.float64)
    w = a.shape[1]
    weights = np.power(2.0, np.arange(w - 1, -1, -1, dtype=np.float64))
    out = bits @ weights
    return float(out[0]) if out.size == 1 else out


# --------------------------------------------------------------------------
# NaN-aware reductions
# --------------------------------------------------------------------------

def _matlab_axis(x, dim):
    """MATLAB reduces along the first non-singleton dimension by default."""
    a = np.asarray(x)
    if dim is not None:
        return a, int(dim) - 1          # MATLAB dims are 1-based
    if a.ndim <= 1:
        return a, 0
    for i, n in enumerate(a.shape):
        if n != 1:
            return a, i
    return a, 0


def msum(x, dim=None):
    """MATLAB ``sum``, accumulated **in order**.

    NumPy sums pairwise: it splits the array into blocks and adds partial sums,
    which is more accurate and is *not* what MATLAB or Octave do.  Both walk the
    vector once, so the two disagree by 1-5 ULP on a long row -- invisible until
    a bit-exactness claim rests on it.  S4 measured it: with ``np.nansum``, 20 of
    4,110 values of ``sizeDist``'s ``n`` and 23 of ``re`` missed the Octave
    oracle by 2-5 ULP; accumulating in order made all three variables exact.

    ``np.cumsum`` is the sequential accumulator, and taking its last element is
    the whole reduction -- vectorised, and verified equal to a Python loop across
    sizes 3 to 5,000 and eight decades of magnitude.

    ``dim`` is 1-based; None means MATLAB's first-non-singleton rule.
    """
    a, axis = _matlab_axis(x, dim)
    a = np.asarray(a, dtype=np.float64)
    if a.size == 0:
        # A 1-D empty input has no surviving dimension to preserve -- MATLAB's
        # own `sum([])` is the scalar 0. But for ndim>=2 (e.g. sizeDist.py's
        # (n_sec, num_bins) accumulators under a degenerate zero-second
        # window), MATLAB's `sum` along an empty axis keeps the OTHER
        # dimensions' shape: `sum(zeros(0,5), 2)` is `0x1`, not a bare 0.
        # Found 2026-08-27: the old `if a.shape[axis]==0: return zeros(...)`
        # below this comment was unreachable dead code, because any
        # zero-length axis already makes `a.size == 0` and this branch fires
        # first -- silently collapsing a shape-preserving empty result to a
        # bare float wherever a sibling axis (not just the reduced one) was
        # the one that was empty.
        survivor_shape = np.delete(a.shape, axis)
        if survivor_shape.size == 0:
            return 0.0
        return np.zeros(tuple(survivor_shape), dtype=np.float64)
    return np.take(np.cumsum(a, axis=axis), -1, axis=axis)


def msum_extra(x):
    """Octave's ``sum(x, dim, "extra")`` -- the double-double accumulator.

    **Not a MATLAB function.**  MATLAB's ``sum`` has no ``"extra"`` option and
    MATLAB's ``mean`` does not compensate.  This exists because Octave 11.3
    rewrote ``mean`` to go through ``robust_mean_sum``, which calls
    ``sum(..., "extra")``, so the Octave *oracle* is more accurate than the
    MATLAB it stands in for wherever a plain ``mean`` appears.  Keeping the two
    behaviours separate is the only honest way to report a bit-exactness result
    that touches ``mean``: see ``docs/developer/OCTAVE_AS_ORACLE.md``.

    Transcribes the accumulator rather than substituting a stand-in: a running
    (hi, lo) pair updated by Knuth's two-sum, which is what Octave's
    ``mx_inline_xsum`` maintains.  Measured against the S4 oracle on all 94
    non-empty seconds of ``ar``, it agrees exactly -- as do Neumaier summation
    and ``math.fsum``, which is the expected outcome for vectors this short and
    is why the *mechanism* was transcribed instead of any of them being adopted
    on the strength of agreeing.

    One dimension only; that is the whole of the need.
    """
    hi = 0.0
    lo = 0.0
    for v in np.asarray(x, dtype=np.float64).reshape(-1):
        s = hi + v
        b = s - hi
        lo += (hi - (s - b)) + (v - b)
        hi = s
    return hi + lo


def nansum(x, dim=None):
    """MATLAB ``nansum``: NaNs treated as zero; all-NaN and empty both give 0.

    ``dim`` is 1-based; None means MATLAB's first-non-singleton rule, which
    differs from NumPy's "reduce everything".  Summation order is MATLAB's --
    see :func:`msum`.

    Provenance: ``sizeDist.m:1380,1398,1401,1404,1407,1410`` (accepted
    particles) and ``:1535,1553,1556,1559,1562,1565`` (rejected twins);
    ``:1769`` and ``:1784`` pass dim=2 explicitly.

    Only NaN is replaced; ``Inf`` passes through, so ``nansum([Inf NaN 1])``
    is ``Inf`` and ``nansum([Inf -Inf NaN])`` is ``NaN`` (Octave-measured).
    An earlier version used ``np.nan_to_num`` here, which also mapped
    ``+-Inf`` to ``+-realmax``, so v3.5's zero-live-time seconds wrote
    ``n = realmax/10`` where MATLAB writes ``Inf``.
    """
    a, axis = _matlab_axis(x, dim)
    a = np.asarray(a, dtype=np.float64)
    if a.size == 0:
        return 0.0
    return msum(np.where(np.isnan(a), 0.0, a), dim=(axis + 1))


def nanmean(x, dim=None):
    """MATLAB ``nanmean``: all-NaN and empty both give NaN, silently.

    NumPy emits ``RuntimeWarning: Mean of empty slice`` where MATLAB is silent;
    the sizeDist loop hits this for every empty size bin, so the warning is
    suppressed rather than allowed to flood the logs.

    Provenance: ``sizeDist.m:1383,1388,1391,1394`` and ``:1538,1542,1545,1549``.
    """
    a, axis = _matlab_axis(x, dim)
    a = np.asarray(a, dtype=np.float64)
    if a.size == 0:
        # Same shape-preservation issue as msum (see its comment): a sibling
        # axis being empty, not just the reduced one, still needs the
        # surviving dimensions kept, not collapsed to a bare scalar.
        survivor_shape = np.delete(a.shape, axis)
        if survivor_shape.size == 0:
            return np.float64(np.nan)
        return np.full(tuple(survivor_shape), np.nan, dtype=np.float64)
    good = ~np.isnan(a)
    total = msum(np.where(good, a, 0.0), dim=(axis + 1))
    n = np.count_nonzero(good, axis=axis)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(n > 0, total / np.where(n > 0, n, 1), np.nan)
    return out if out.ndim else np.float64(out)


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Days from 1 March to the start of each month, January first: the year is
# counted from March so that the leap day falls at its end.
_MONTHSTART = np.array([306, 337, 0, 31, 61, 92, 122, 153, 184, 214, 245, 275],
                       dtype=np.float64)
_MONTHLENGTH = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31],
                        dtype=np.float64)


def _is_leap_year(y):
    return ((np.mod(y, 4) == 0) & (np.mod(y, 100) != 0)) | (np.mod(y, 400) == 0)


def _datenum_fields(y, mo, d, h, mi, s):
    """The serial day number, operation for operation as Octave 11.3's ``datenum.m``.

    Proleptic Gregorian arithmetic on doubles, with no calendar object, so year
    0 and earlier work as they do in the interpreter. Every step below is one
    statement of that file, in its order, because the order fixes the last bit
    of the result: the time of day is ``(H + (M + S/60)/60)/24``, which differs
    from ``H/24 + M/1440 + S/86400`` by one ulp on about a third of instants.
    Held bit for bit against ``tests/data/datenum_octave_golden.json``.
    """
    if all(np.ndim(c) == 0 and math.isfinite(c) for c in (y, mo, d, h, mi, s)):
        return np.float64(_datenum_scalar(*(float(c) for c in (y, mo, d, h, mi, s))))
    y, mo, d, h, mi, s = np.broadcast_arrays(
        *[np.asarray(c, dtype=np.float64) for c in (y, mo, d, h, mi, s)])
    y, mo, d = y.copy(), mo.copy(), d.copy()
    mo[mo < 1] = 1                     # months below 1 are set to 1, not rolled back
    if np.any(mo != np.fix(mo)):       # a fractional month becomes days
        frac = mo - np.floor(mo)
        mo = np.floor(mo)
        mi_idx = (np.mod(mo - 1, 12)).astype(np.intp)
        idx = (mi_idx + 1 != 2) | ~_is_leap_year(np.floor(y))
        d[idx] += frac[idx] * _MONTHLENGTH[mi_idx[idx]]
        d[~idx] += frac[~idx] * 29
    y += np.ceil((mo - 14) / 12)       # the year starts in March; months > 12 roll over
    d += _MONTHSTART[np.mod(mo - 1, 12).astype(np.intp)] + 60
    if np.any(y != np.fix(y)):         # a fractional year becomes days
        frac = y - np.floor(y)
        y = np.floor(y)
        d += frac * (365 + _is_leap_year(y + 1))
    d += 365 * y + np.floor(y / 4) - np.floor(y / 100) + np.floor(y / 400)
    return d + (h + (mi + s / 60) / 60) / 24


def _datenum_scalar(y, mo, d, h, mi, s):
    """:func:`_datenum_fields` for six Python floats, the same IEEE operations in
    the same order (per-particle callers would otherwise pay NumPy's overhead)."""
    if mo < 1:
        mo = 1.0
    if mo != math.trunc(mo):
        frac = mo - math.floor(mo)
        mo = float(math.floor(mo))
        k = int(mo - 1) % 12
        fy = math.floor(y)
        leap = (fy % 4 == 0 and fy % 100 != 0) or fy % 400 == 0
        d += frac * (_MONTHLENGTH_T[k] if (k + 1 != 2 or not leap) else 29)
    y += math.ceil((mo - 14) / 12)
    d += _MONTHSTART_T[int(mo - 1) % 12] + 60
    if y != math.trunc(y):
        frac = y - math.floor(y)
        y = float(math.floor(y))
        y1 = y + 1
        leap = (y1 % 4 == 0 and y1 % 100 != 0) or y1 % 400 == 0
        d += frac * (365 + leap)
    d += 365 * y + math.floor(y / 4) - math.floor(y / 100) + math.floor(y / 400)
    return d + (h + (mi + s / 60) / 60) / 24


_MONTHSTART_T = tuple(float(v) for v in _MONTHSTART)
_MONTHLENGTH_T = tuple(float(v) for v in _MONTHLENGTH)


def datenum(y, mo=None, d=None, h=0, mi=0, s=0):
    """MATLAB ``datenum`` -> serial day number.

    Accepts three to six scalar/array components, broadcast together, or a
    single ``(N,3)`` to ``(N,6)`` date-vector array (``IntArrAnalysis.m:304-306``).

    The result is written to netCDF as ``'double'`` under ``'units'`` =
    ``'MATLAB datetime'`` (``IntArrAnalysis.m:265-267,273-275``), so it is part
    of the output contract -- a POSIX timestamp would be wrong.

    Reproduces Octave's ``datenum`` bit for bit (the Octave bank
    ``run_datenum_bank.py``, dev repository only):
    a month below 1 is set to 1; days, hours, minutes and seconds out of range
    carry linearly, which ``IntArrAnalysis.m:302`` and the ``+240000`` midnight
    fixes at ``sizeDist.m:98`` rely on; months above 12 roll into later years;
    fractional months and years become days; year 0 and earlier are ordinary.
    So MATLAB's zero-date time-of-day idiom ``datenum(0,0,0,H,M,S)`` returns
    exactly the time-of-day fraction ``(H + (M + S/60)/60)/24``.
    """
    if mo is None:
        vec = np.atleast_2d(np.asarray(y, dtype=np.float64))
        if not 3 <= vec.shape[1] <= 6:
            raise ValueError("datenum: a single argument must be an (N,3) to (N,6) date vector")
        cols = [vec[:, k] for k in range(vec.shape[1])]
        cols += [np.zeros(vec.shape[0])] * (6 - vec.shape[1])
        out = _datenum_fields(*cols)
        return out if out.size != 1 else float(out[0])
    if d is None:
        raise TypeError("datenum: give the year, month and day, or one date-vector array")
    out = _datenum_fields(y, mo, d, h, mi, s)
    if out.ndim == 0:
        return float(out)
    return out


def datestr(dt=None, fmt=None):
    """MATLAB ``datestr``.

    Default format is MATLAB's ``'dd-mmm-yyyy HH:MM:SS'``.
    ``'yyyy/mm/dd HH:MM:SS'`` is the only explicit format UIOOPS uses
    (``imgProc_sm.m:221``, ``sizeDist.m:1810``, ``IntArrAnalysis.m:252``), where
    it becomes the non-deterministic ``'Creation Time'`` global attribute --
    exclude it from byte comparisons.
    """
    when = _dt.datetime.now() if dt is None else dt
    if fmt is None:
        return (f"{when.day:02d}-{_MONTHS[when.month - 1]}-{when.year:04d} "
                f"{when.hour:02d}:{when.minute:02d}:{when.second:02d}")
    pyfmt = (fmt.replace("yyyy", "%Y").replace("mm", "%m").replace("dd", "%d")
                .replace("HH", "%H").replace("MM", "%M").replace("SS", "%S"))
    return when.strftime(pyfmt)


# --------------------------------------------------------------------------
# char <-> numeric coercion
# --------------------------------------------------------------------------

def mchar(c):
    """MATLAB's implicit char->numeric coercion.  ``mchar('S') == 83``.

    ``imgProc_sm.m:323`` declares ``image_auto_reject`` as ``'short'`` and
    ``:898`` writes ``int16(images.auto_reject)`` from a CHAR array.
    ``sizeDist.m:769`` reads it back as int16 and then assigns character
    literals into it -- ``:809`` ='D', ``:871`` ='I', ``:985`` ='z',
    ``:1009,1012,1017`` ='S', ``:1042,1176`` ='R' -- and compares against them
    at ``:1047,1060``.  MATLAB coerces silently; NumPy raises.

    Also ``imgProc_sm.m:897`` computes ``images.image_touching_edge - '0'``.
    """
    if isinstance(c, str):
        if len(c) == 1:
            return ord(c)
        return np.array([ord(ch) for ch in c], dtype=np.int16)
    return c


#: Reject codes.  **Corrected 2026-08-20 against the emitting code**, not
#: only the ``Description`` attribute at ``imgProc_sm.m:325-329``: that
#: attribute lists seven codes where ``calculate_reject_unified`` emits eleven,
#: and it names one that no path produces.  Anything decoding
#: ``image_auto_reject`` from the file's own metadata will mis-bucket the rest.
REJECT_CODES = {
    "0": 48,   # accepted
    "a": 97,   # aspect ratio outside [1/5, 5]      (calculate_reject_unified.m:270)
    "p": 112,  # < 25% of the bounding rectangle    (:276)
    "s": 115,  # split image                        (:235)
    "z": 122,  # zero area                          (:122, :264)
    "h": 104,  # hollow, no measurable hole ratio   (:322)
    "H": 72,   # hollow, Korolev correction applied (:332)
    "u": 117,  # hollow, area-to-hole ratio too big (:344, :348, :352)
    # --- emitted but ABSENT from the netCDF Description ---
    "A": 65,   # > 80% of the block shadowed        (:229)
    "i": 105,  # side scans contradict the hollow verdict (:338)
    # --- from sizeDist, added downstream of imgProc ---
    "D": 68,   # DMT DOF / SPEC overload   (sizeDist.m:809)
    "I": 73,   # inter-arrival             (sizeDist.m:871)
    "R": 82,   # shattering reacceptance   (sizeDist.m:1042,1176)
    "S": 83,   # shattering                (sizeDist.m:1009,1012,1017)
}

#: Each code of :data:`REJECT_CODES` (and :data:`UNREACHABLE_REJECT_CODES`) in words, from the
#: emitting lines cited beside each code above.  ``'z'`` is written twice: by
#: ``calculate_reject_unified`` for zero area, and by ``sizeDist`` for an area ratio below its cut.
REJECT_CODE_WORDS = {
    "0": "accepted",
    "a": "aspect ratio beyond the contained-particle ceiling or its reciprocal",
    "p": "too little of the bounding rectangle shadowed",
    "s": "split image",
    "z": "zero area (image stage), or area ratio below the cut (sizeDist)",
    "h": "hollow, no measurable hole ratio",
    "H": "hollow, Korolev correction applied",
    "u": "hollow, area-to-hole ratio too big",
    "A": "more than 80% of the block shadowed",
    "i": "side scans contradict the hollow verdict",
    "D": "DMT depth of field / SPEC overload",
    "I": "inter-arrival",
    "R": "shattering reacceptance",
    "S": "shattering",
    "t": "aspect ratio beyond the edge-particle ceiling (documented; no path emits it)",
    "f": "zero area image (documented; no path emits it)",
}

#: Codes the ``Description`` attribute declares but no code path can produce.
#:
#: * ``'t'`` (116) is documented as "aspect ratio > 5 + image touching edge",
#:   but :272 requires the ratio to exceed ``max_edge_img_ar = 6`` *after* :269
#:   has already rejected everything above ``max_comp_img_ar = 5``.  Six being
#:   the larger of the two makes the edge test strictly weaker than the one
#:   before it, so it never fires.  (The attribute states the two thresholds the
#:   other way round -- which is the ordering that would make ``'t'``
#:   reachable.)
#: * ``'f'`` (102) is documented as "zero area image" and appears in no branch.
UNREACHABLE_REJECT_CODES = {"t": 116, "f": 102}

#: Holroyd habit codes, from the Description attribute at ``imgProc_sm.m:424-427``.
HOLROYD_HABITS = {
    "M": 77, "C": 67, "d": 100, "t": 116, "o": 111,
    "l": 108, "a": 97, "g": 103, "s": 115, "h": 104, "i": 105,
}


# --------------------------------------------------------------------------
# Orientation-sensitive helpers
# --------------------------------------------------------------------------

def _as_2d_col(a):
    a = np.asarray(a)
    return a.reshape(-1, 1) if a.ndim <= 1 else a


def mvertcat(*arrays):
    """MATLAB ``[a; b; ...]``.

    Provenance: ``sizeDist.m:815`` ``int_arr = [0;diff(Time_in_seconds)]`` and
    ``:713`` ``count_all = [diff(start_all); NumofPart-start_all(end)]`` -- both
    only make sense because ``netcdf.getVar`` returns a COLUMN for a 1-D
    variable (the column-orientation gap in the netCDF-shim design record).
    """
    return np.vstack([_as_2d_col(a) for a in arrays if np.asarray(a).size or True])


def mhorzcat(*arrays):
    """MATLAB ``[a, b, ...]``."""
    parts = []
    for a in arrays:
        a = np.asarray(a)
        parts.append(a.reshape(1, -1) if a.ndim <= 1 else a)
    return np.hstack(parts)


def mdiff(x, dim=None):
    """MATLAB ``diff``: along the first non-singleton dimension by default."""
    a, axis = _matlab_axis(x, dim)
    return np.diff(a, axis=axis)


class MGrowVector:
    """A 1-based MATLAB vector that auto-extends with zero fill.

    MATLAB grows an array on out-of-range assignment and fills the gap with 0
    (numeric).  A Python port using ``list.append`` gets this wrong whenever the
    index skips.

    Provenance: ``IntArrAnalysis.m:37-38`` (``intarr(1)=0`` then
    ``intarr(2:length(tempTime))=diff(tempTime)``), ``:106,109``;
    ``imgProc_sm.m:575-577,601,697-699`` (the ``images.*`` accumulators indexed
    by ``kk``).

    Note the companion hazard: ``imgProc_sm.m:863`` does ``clear c ind_matrix``
    inside the per-particle loop.  That ``clear`` is load-bearing -- keeping
    ``ind_matrix`` alive across particles would leak stale rows from a longer
    previous particle into ``dec2bin(ind_matrix(:,k))`` at ``:556/559/563``.
    """

    def __init__(self, dtype=np.float64):
        self._a = np.zeros(0, dtype=dtype)
        self._dtype = dtype

    def _grow(self, n):
        if n > self._a.size:
            pad = np.zeros(n - self._a.size, dtype=self._dtype)
            self._a = np.concatenate([self._a, pad])

    def __setitem__(self, i, value):
        """1-based assignment; accepts an int or a 1-based slice."""
        if isinstance(i, slice):
            start = 1 if i.start is None else i.start
            stop = i.stop
            self._grow(stop)
            self._a[start - 1:stop] = value
        else:
            self._grow(i)
            self._a[i - 1] = value

    def __getitem__(self, i):
        if isinstance(i, slice):
            start = 1 if i.start is None else i.start
            return self._a[start - 1:i.stop]
        return self._a[i - 1]

    def __len__(self):
        return self._a.size

    def asarray(self):
        """A **copy** of the grown vector, 0-based, as an ordinary ndarray.

        A copy rather than a view on purpose: the caller is usually handing the
        result to a netCDF write or to a comparison, while this object may keep
        growing afterwards, and a view would silently change length or be
        invalidated by the next reallocation in :meth:`_grow`.

        Length is the highest index ever assigned, with the skipped positions
        holding the zeros MATLAB fills them with -- not the number of
        assignments made.
        """
        return self._a.copy()

    def __repr__(self):
        return f"MGrowVector({self._a!r})"


# --------------------------------------------------------------------------
# Index-base conversion
# --------------------------------------------------------------------------

def to0(i):
    """MATLAB 1-based index -> Python 0-based.

    Convention for this port: keep MATLAB 1-based indices visible in the code
    and convert only at the array boundary, so the source's deliberate +/-1
    differences stay visually identical.  Several sites MIX 1-based MATLAB
    indices with 0-based netCDF starts in one expression, so a uniform global
    shift double-shifts them -- see ``sizeDist.m:686`` vs ``:955``,
    ``sizeDist.m:818,822,833``, ``imgProc_sm.m:452-453,555,558,582,589,655``.
    """
    return np.asarray(i) - 1 if np.ndim(i) else i - 1


def to1(i):
    """Python 0-based index -> MATLAB 1-based.  See :func:`to0`."""
    return np.asarray(i) + 1 if np.ndim(i) else i + 1
