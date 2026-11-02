# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_export_ascii.pro`` -- the ASCII particle-size-
distribution (or counts) export ``soda2_process_2d.pro:722-726`` calls when
``op.asciipsdfile eq 1``.

Vendored source, read whole: ``SODA2/abansemer-soda2-afcea15/
soda2_export_ascii.pro`` (158 lines) and its call tree, all pure IDL:
``compute_bulk_simple.pro`` (73), ``mmdiam.pro``, ``mvdiam.pro``,
``meandiam.pro``, ``unnormalize.pro``. ``soda2_parsedate`` is already ported
(``timeconv.py``); ``soda2_filename`` is already ported as
:func:`arrayprobe_soda2.pbp_writer.pbp_filename`. Where this file was measured
against GDL, the result in a few places corrects the earlier design's
*derived, not yet measured* guesses.


Imports nothing from ``arrayprobe``/``arrayprobe_uiops`` (separate port, own
oracle discipline, like every other ``arrayprobe_soda2`` module).

**Scope refused by name:**
- ``1D2D`` housekeeping (`:19-43`) whose ``leftreject``/``rightreject``
  fields are not integer-typed -- raises :class:`OneD2DHousekeepingNotPorted`.
  The integer case is ported and asserted byte-for-byte against the GDL
  golden (``gdl_oracle/run_soda2_export_ascii_1d2d_bank.py``, INT fields);
  ``byte()`` of a float sum is not pinned by any bank case.
- ``minsize`` above every bin edge (`:14-15`) -- raises :class:`MinsizeOutOfRange`
  naming the line; GDL-bank-verified as a real halt (or corrected here if the
  bank showed otherwise -- see that design record's follow-up section).

**Surprises, each mapped to a GDL bank case in ``run_soda2_export_ascii_bank.py``:**

1. ``a``/``b`` are undefined keywords the driver never passes, so
   ``compute_bulk_simple``'s own defaults (0.00294, 1.9) become the values
   the ice-branch header line prints (`:16`, `:106`) -- IDL keyword
   arguments are by reference, so an undefined variable passed as a keyword
   is *defined* by the callee's own default and that definition is visible
   back in the caller. Bank case ``defaults_only``.
2. The export mutates the caller's ``data.conc1d`` in place (`:138-139`):
   ``data`` is ``soda2_process_2d.pro``'s own positional PRO argument, hence
   pass-by-reference, so the NaN-to-zero rewrite is visible to whatever the
   driver does with ``data`` afterward (here: nothing further reads it, but
   the side effect is a general finding). This port reproduces
   the mutation on the caller's own array, not a private copy. Bank case
   ``nan_conc_side_effect``.
3. ``minsize`` above every bin edge halts -- **measured** (``minsize_above_bins``),
   and not for the reason first guessed: ``iminsize = min(where(endbins ge
   minsize))`` is ``-1``, and IDL's negative indices count from the end, so
   ``endbins[-1]`` and the slice ``(mass*spec)[binstart:binstop]`` with
   ``binstart=-1`` do NOT raise -- they silently collapse to the array's
   *last element only* (a length-1 slice). ``compute_bulk_simple`` then
   calls ``mmdiam`` with a length-1 ``endbins`` slice, and
   ``mmdiam.pro:12``'s ``z=fltarr(n)`` with ``n=n_elements(endbins)-1=0``
   fails: GDL raises "Array dimensions must be greater than 0" there, not
   at the ``endbins[-1]`` access this port first suspected.
4. ``data.time`` is DOUBLE, printed with format ``i6`` (`:151`) -- whether
   GDL rounds or truncates the fractional part decides the printed value;
   bank case ``fractional_time``.
5. The water branch (`op.water >= 1`) uses ``lwc``/``mvd``; the ice branch
   uses ``iwc``/``dmedianmass`` (``mmdiam``). ``mmdiam``/``mvdiam``
   interpolate on a cumulative array padded with a leading 0
   (``interpol(endbins, [0,z], half)``); a run of empty bins makes ``z``
   flat (repeated values, not strictly increasing) and IDL's ``INTERPOL``
   tie-breaking there is implementation-defined. Bank cases ``ice_default``,
   ``water_1``, ``water_2``, ``gappy_spectrum``.
6. ``compute_bulk_simple`` clamps ice mass to 0.91x water mass per bin
   (`:45`) and switches to water outright for ``acoeff > 0.52 and bcoeff ==
   3.0`` (`:46`) -- silent in the printed header, which always prints the
   nominal ``a``, ``b``. Read-only; a documentation finding if GDL confirms
   the printed header never reflects the substitution.
7. ``1D2D`` housekeeping columns (`:19-43`) fire only when ``data`` has a
   ``house`` with two or more fields AND ``probetype == '1D2D'``; a 1D2D
   without one writes no house columns. ``byte(left+right)<1`` wraps the sum
   modulo 256 before the clip, so both edges on at 128+128 reads 0
   (``edge_sum_256``).
8. Output formats, each pinned by the bank rather than assumed: ``(500e12.2)``
   and ``(500i12)`` for the row body, ``(i6, 3e12.2, $)`` for the row prefix
   (``$`` suppresses the newline), ``(500f9.2)``, ``(500e9.2)``,
   ``(a6, 500a12)`` for the short-name header line. ``500`` is IDL's *repeat
   count*, not a field width -- more than 500 values wraps onto a second
   line; this port refuses ``numbins > 500`` rather than silently emulating
   the wrap (no probe in this project's scope has that many bins).

The ``.conc.1Hz`` naming in the plan's row D is the UND/ADPAA product,
written by ADPAA, not by any SODA-2 routine
(``grep -ril "conc.1Hz" SODA2/`` is empty) -- this ``.txt`` is the only
SODA-2 ASCII PSD writer, so it *is* the port's answer to that row.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

import numpy as np

from .pbp_writer import pbp_filename
from .timeconv import soda2_parsedate

__all__ = [
    "MinsizeOutOfRange",
    "OneD2DHousekeepingNotPorted",
    "interpol",
    "unnormalize",
    "mmdiam",
    "mvdiam",
    "meandiam",
    "compute_bulk_simple",
    "soda2_export_ascii",
]


class MinsizeOutOfRange(IndexError):
    """``soda2_export_ascii.pro:14-15`` -- no bin edge is ``>= minsize``, so
    ``iminsize = min(where(...))`` is ``-1``. Measured under GDL (case
    ``minsize_above_bins``): this does NOT itself raise (IDL's negative
    index -1 is the last element, a valid access) -- the real halt is one
    level down, in ``mmdiam.pro:12``'s ``z=fltarr(n)`` with ``n=0``, because
    ``binstart=-1`` collapses the ``endbins``/spec slices passed into
    ``mmdiam`` to length 1. This port raises here, before calling
    ``compute_bulk_simple`` at all, rather than reproducing the deeper
    GDL stack -- the *user-visible* outcome (a halt for this input) is the
    same either way, and this port has no ``fltarr(0)``-shaped failure mode
    to reproduce faithfully."""


class OneD2DHousekeepingNotPorted(NotImplementedError):
    """``soda2_export_ascii.pro:37`` -- ``byte(leftreject+rightreject)`` on
    non-integer housekeeping fields: no GDL bank case pins IDL's float-to-byte
    conversion, so this port refuses it rather than guess. Integer fields
    are ported (`:19-43`)."""


def _house_columns(data: Any, probetype: Any, ntimes: int
                   ) -> tuple[list[str], list[str], list[np.ndarray]]:
    """``soda2_export_ascii.pro:19-51``: titles, short names and per-row
    integer columns of the housekeeping block (all empty unless ``data``
    has a ``house`` with two or more fields and the probe is ``1D2D``).
    ``house`` is a mapping (field names case-insensitive, as IDL tags)."""
    house = getattr(data, "house", None)
    if house is None:
        return [], [], []
    # `:19` -- `n_elements(tag_names(data.house)) gt 1`: a mapping's keys, or
    # a structure-like object's fields (``process_hk.HouseData``, a dataclass).
    if isinstance(house, Mapping):
        fields = {str(k).lower(): v for k, v in house.items()}
    elif dataclasses.is_dataclass(house):
        fields = {f.name.lower(): getattr(house, f.name)
                  for f in dataclasses.fields(house)}
    else:
        fields = {str(k).lower(): v for k, v in vars(house).items()}
    if len(fields) <= 1 or probetype != "1D2D":
        return [], [], []
    h = {k: np.asarray(v) for k, v in fields.items()}
    # `:30-35` -- `bytarr(n)+1`, then mode 2, then mode 3 overriding it.
    probemode = np.ones(ntimes, dtype=np.int64)
    probemode[(h["dofnumreject"] != 0) & (h["dofpercent"] == 0)] = 2
    probemode[h["dofpercent"] != 0] = 3
    left, right = h["leftreject"], h["rightreject"]
    for name, arr in (("leftreject", left), ("rightreject", right)):
        if not np.issubdtype(arr.dtype, np.integer):
            raise OneD2DHousekeepingNotPorted(
                f"soda2_export_ascii.pro:37: byte() of a {arr.dtype} "
                f"house.{name} is not pinned by the GDL bank")
    # `:37` -- byte() keeps the low 8 bits of the integer sum; `<1` clips.
    edgereject = np.minimum((left.astype(np.int64) + right.astype(np.int64)) % 256, 1)
    titles = ["1D2D Probe Mode (1: No Depth of Field Rejections, 2: N75 Count "
              "Rejection, 3: N75/N50 Ratio Rejection)",
              "1D2D Edge-touch Rejection (0:Disabled, 1:Enabled)"]
    return titles, ["ProbeMode", "EdgeReject"], [probemode, edgereject]


# ---------------------------------------------------------------------------
# Call tree
# ---------------------------------------------------------------------------

def interpol(v: np.ndarray, x: np.ndarray,
             xout: float | np.floating | np.ndarray) -> float | np.ndarray:
    """IDL's 3-argument ``INTERPOL(V, X, XOUT)``: linear interpolation that
    **extrapolates** past both ends of ``x`` using the nearest segment's
    slope, rather than clamping (``numpy.interp`` clamps -- do not use it
    here). ``x`` is located by the equivalent of IDL's ``VALUE_LOCATE``,
    clamped to ``[0, n-2]`` so the two endpoint segments serve every
    out-of-range query. Only the *left* extrapolation from a cumulative
    sum's leading ``0`` pad is reachable from :func:`mmdiam`/:func:`mvdiam`
    in this codebase; a run of empty bins makes ``x`` non-strictly-increasing
    (repeated values), where the tie-breaking is implementation-defined and
    pinned by the ``gappy_spectrum`` bank case, not assumed here."""
    v_arr = np.asarray(v, dtype=np.float64)
    x_arr = np.asarray(x, dtype=np.float64)
    scalar_input = np.ndim(xout) == 0
    xout_arr = np.atleast_1d(np.asarray(xout, dtype=np.float64))
    n = len(x_arr)
    idx = np.searchsorted(x_arr, xout_arr, side="right") - 1
    idx = np.clip(idx, 0, n - 2)
    x0, x1 = x_arr[idx], x_arr[idx + 1]
    v0, v1 = v_arr[idx], v_arr[idx + 1]
    denom = x1 - x0
    with np.errstate(divide="ignore", invalid="ignore"):
        result = v0 + (xout_arr - x0) * (v1 - v0) / denom
    return float(result[0]) if scalar_input else result


def _as_idl_float(x: Any) -> np.ndarray:
    """An operand as IDL would hold it: FLOAT/DOUBLE stay as they are, and
    any integer operand meets a FLOAT literal in every expression below, so it
    becomes FLOAT (IDL's INT * FLOAT promotion), never float64."""
    arr = np.asarray(x)
    return arr if np.issubdtype(arr.dtype, np.floating) else arr.astype(np.float32)


def _idl_total(x: np.ndarray, nan: bool = False) -> np.floating:
    """IDL ``total(x)`` (``/nan`` optional) on a 1-D FLOAT or DOUBLE array:
    **sequential** accumulation in the array's own type, first element first.

    Measured under GDL (``run_soda2_compute_bulk_simple_bank.py``'s
    ``semantics``): ``total([1e8, 1 x16, -1e8])`` on FLOAT is 0.0 of type FLOAT
    -- every ``+1`` is lost against 1e8 -- where a float64 accumulator gives 16
    and ``numpy.sum``'s pairwise float32 sum gives neither. ``numpy.cumsum`` is
    sequential, so its last element is IDL's total. ``/nan`` skips NaN, which
    for a sum is adding nothing."""
    arr = np.asarray(x).ravel()
    if nan:
        arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return arr.dtype.type(0)
    return np.cumsum(arr, dtype=arr.dtype)[-1]


def _idl_cube(x: np.ndarray) -> np.ndarray:
    """IDL ``x^3`` with an INT exponent on FLOAT: ``(x*x)*x`` in the operand's
    type. Measured under GDL: 0 of 3000 random FLOAT values differ from
    this, 763 differ from ``powf`` (``numpy.power(x, 3)``)."""
    return x * x * x


def _idl_powf(x: np.ndarray, y: float | np.floating[Any]) -> np.ndarray:
    """IDL FLOAT^FLOAT: the double-precision power rounded to FLOAT, the same
    rule as ``_idl_alog10``. numpy's float32 power calls the platform ``powf``,
    which is correctly rounded under the MSVC runtime (where it matched the GDL
    goldens) and not under glibc (one ULP off in ``dmass``/``msd``)."""
    out = np.power(np.asarray(x, dtype=np.float64), np.float64(y))
    return out.astype(np.float32)


def _idl_alog10(x: np.ndarray) -> np.ndarray:
    """IDL ``alog10`` on FLOAT: the double-precision ``log10`` rounded to FLOAT.
    Measured under GDL: 0 of 3000 differ from this, 7 differ from
    numpy's own float32 ``log10``."""
    arr = np.asarray(x)
    if arr.dtype == np.float32:
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.log10(arr.astype(np.float64)).astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log10(arr)


def unnormalize(spectra: np.ndarray, endbins: np.ndarray) -> np.ndarray:
    """``unnormalize.pro`` (whole file, 16 lines). ``spectra`` in m^-4,
    ``endbins`` in um; returns m^-3. 1-D or 2-D (``[ntimes, nbins]``) input,
    same shape out.

    In IDL's types, not float64: ``spec_un = spectra*0.0`` (`:7`) fixes
    the 2-D result's type to the spectra's own, each row is
    ``(spectra[i,*]*binwidth)/1.0e6`` with ``1.0e6`` a FLOAT literal, and a
    wider row (DOUBLE ``endbins``) is rounded back on assignment. The 1-D
    branch (`:12`) keeps the promoted type."""
    spectra_arr = _as_idl_float(spectra)
    endbins_arr = _as_idl_float(endbins)
    binwidth = endbins_arr[1:] - endbins_arr[:-1]
    if spectra_arr.ndim == 1:
        return spectra_arr * binwidth / np.float32(1.0e6)
    return (spectra_arr * binwidth / np.float32(1.0e6)).astype(spectra_arr.dtype)


def mmdiam(iwc_spec: np.ndarray, endbins: np.ndarray, nan: bool = False) -> np.ndarray:
    """``mmdiam.pro`` (36 lines). ``iwc_spec`` un-normalized mass (g/m3),
    1-D or ``[ntimes, nbins]``; returns one value per time record. Pads the
    cumulative-mass array with a leading 0 so the first bin is interpolable
    (`:31`).

    ``tmass`` (`:22`) is a sequential ``total`` in the spectrum's own type;
    ``z`` (`:12`, ``fltarr``) is FLOAT whatever the spectrum's type, each
    ``z[j] = total(iwc_spec[i,0:j])`` (`:23`) -- a sequential prefix sum,
    which is ``cumsum``; ``[0,z]`` is FLOAT; GDL's ``INTERPOL`` computes in
    double and returns FLOAT (measured)."""
    nullvalue = np.nan if nan else 0.0
    spec = np.atleast_2d(_as_idl_float(iwc_spec))
    endbins_arr = _as_idl_float(endbins)
    n = len(endbins_arr) - 1
    ntimes = spec.shape[0]
    mmd = np.zeros(ntimes, dtype=np.float32)
    for i in range(ntimes):
        tmass = _idl_total(spec[i, :])
        z = np.cumsum(spec[i, :n], dtype=spec.dtype).astype(np.float32)
        padded_z = np.concatenate((np.zeros(1, dtype=np.float32), z))
        mmd[i] = interpol(endbins_arr, padded_z, tmass / np.float32(2.0))
        if tmass == 0:
            mmd[i] = nullvalue
    return mmd


def mvdiam(conc_raw: np.ndarray, endbins: np.ndarray, nan: bool = False) -> np.ndarray:
    """``mvdiam.pro`` (32 lines). ``conc_raw`` un-normalized concentration
    (m^-3), ``[ntimes, nbins]``. ``midbins`` here is
    ``(endbins[1:]+endbins[:-1])/2`` -- read directly off ``mvdiam.pro:13``,
    which writes it as ``(endbins[1:*] + endbins)/2.0``, two arrays of
    *different* length (n-1 and n): IDL arithmetic between differently-sized
    arrays silently truncates both operands to the smaller size, using each
    operand's own *first* N elements -- so ``endbins[1:*][i] + endbins[i]``
    for ``i in 0..n-2`` is exactly ``endbins[i+1] + endbins[i]``, the
    ordinary midpoint formula. No IDL bug; just an unusual way to write it.

    In IDL's types: ``volume=(!pi/6)*midbins^3*conc_raw[i,*]`` (`:19`)
    is ``((!pi/6)*((m*m)*m))*conc`` in FLOAT (``!pi`` is FLOAT, ``^3`` an INT
    exponent), ``tvolume`` a sequential ``total``, ``z`` a FLOAT ``fltarr``
    of sequential prefix sums."""
    nullvalue = np.nan if nan else 0.0
    conc_arr = np.atleast_2d(_as_idl_float(conc_raw))
    endbins_arr = _as_idl_float(endbins)
    midbins = (endbins_arr[1:] + endbins_arr[:-1]) / np.float32(2.0)
    n = len(midbins)
    ntimes = conc_arr.shape[0]
    pi6 = np.float32(np.pi) / np.float32(6)
    mvd = np.zeros(ntimes, dtype=np.float32)
    for i in range(ntimes):
        volume = pi6 * _idl_cube(midbins) * conc_arr[i, :]
        tvolume = _idl_total(volume)
        z = np.cumsum(volume[:n], dtype=volume.dtype).astype(np.float32)
        padded_z = np.concatenate((np.zeros(1, dtype=np.float32), z))
        mvd[i] = interpol(endbins_arr, padded_z, tvolume / np.float32(2.0))
        if tvolume == 0:
            mvd[i] = nullvalue
    return mvd


def meandiam(conc_raw: np.ndarray, midbins: np.ndarray, nan: bool = False,
             minimum: float = 0.0) -> np.ndarray:
    """``meandiam.pro`` (29 lines). ``midbins`` (not ``endbins`` -- the
    source's own ``:16`` guard checks this by comparing lengths and
    ``stop``s otherwise; reproduced as :class:`ValueError`).

    `:19` in IDL's types: ``total(conc*midbins)/(total(conc) > 0.0001)``,
    both totals sequential in the operands' type, ``0.0001`` a FLOAT literal
    and ``>`` IDL's maximum operator."""
    nullvalue = np.nan if nan else 0.0
    conc_arr = np.atleast_2d(_as_idl_float(conc_raw))
    midbins_arr = _as_idl_float(midbins)
    if len(midbins_arr) != conc_arr.shape[1]:
        raise ValueError(
            "meandiam.pro:16: stop -- Need to enter midbins rather than "
            "endbins to meandiam")
    ntimes = conc_arr.shape[0]
    meand = np.zeros(ntimes, dtype=np.float32)
    for i in range(ntimes):
        total = _idl_total(conc_arr[i, :])
        num = _idl_total(conc_arr[i, :] * midbins_arr)
        meand[i] = num / np.maximum(total, total.dtype.type(np.float32(0.0001)))
        if total == 0:
            meand[i] = nullvalue
    if minimum != 0:
        totals = np.array([_idl_total(row) for row in conc_arr])
        meand[totals < minimum] = nullvalue
    return meand


def compute_bulk_simple(
    conc1d: np.ndarray,
    endbins: np.ndarray,
    *,
    binstart: int | None = None,
    binstop: int | None = None,
    acoeff: float | None = None,
    bcoeff: float | None = None,
) -> dict[str, np.ndarray]:
    """``compute_bulk_simple.pro`` (73 lines). ``conc1d`` in m^-4
    ``[ntimes, nbins]`` FLOAT, ``endbins`` in um. Returns a dict of one
    FLOAT32 value (or ``[ntimes, nbins]`` array for ``msd``/``msdnorm``) per
    key, matching the IDL structure's tag names.

    NaN in ``conc1d`` is zeroed on this function's own working copy
    (`:16-17`). Measured under GDL (bank case ``nan_and_inf``): the
    write reaches the caller through a *bare variable* argument (by
    reference) but not through a structure field (by value), and every
    vendored caller passes a field (``data.conc1d``, ``(*p1).conc1d``), so
    the private copy is the faithful reading.

    **Arithmetic in IDL's types, bit for bit** (bank
    the GDL bank ``run_soda2_compute_bulk_simple_bank.py`` (dev repository only),
    all fifteen tags of
    twelve cases bit-exact): every ``total`` is a sequential FLOAT sum
    (:func:`_idl_total`), ``^3`` is ``(x*x)*x`` (:func:`_idl_cube`),
    ``alog10`` is double-rounded-to-FLOAT (:func:`_idl_alog10`), and
    ``unnormalize``/``mmdiam``/``mvdiam``/``meandiam`` stay FLOAT. A pairwise float64 sum
    differs from these by 1-2 float32 ULPs. ``acoeff``/``bcoeff`` are held
    FLOAT, as the two export callers' are (``soda2_export_ascii.pro:16``
    passes undefined ``a``/``b``, so the FLOAT defaults at `:7-8` apply;
    ``soda2_export_ncdf.pro:194-202`` passes none). The GUI callers
    (``soda2_browse``/``soda2_compare``) pass widget values of unmeasured
    type; a DOUBLE coefficient would promote the IDL computation to DOUBLE,
    which this port does not model.
    """
    if acoeff is None:
        acoeff = 0.00294
    if bcoeff is None:
        bcoeff = 1.9
    acoeff_f = np.float32(acoeff)
    bcoeff_f = np.float32(bcoeff)

    endbins_arr = np.asarray(endbins, dtype=np.float32)
    numbins = len(endbins_arr) - 1
    midbins = (endbins_arr[:numbins] + endbins_arr[1:numbins + 1]) / np.float32(2.0)
    binwidth = (endbins_arr[1:numbins + 1] - endbins_arr[:numbins]).astype(np.float32)

    conc1d_arr = np.array(conc1d, dtype=np.float32, copy=True)
    if conc1d_arr.ndim == 1:
        conc1d_arr = conc1d_arr.reshape(1, -1)
    conc1d_arr[~np.isfinite(conc1d_arr)] = np.float32(0.0)
    num = conc1d_arr.shape[0]

    if binstart is None:
        binstart = 0
    if binstop is None:
        binstop = conc1d_arr.shape[1] - 1
    sl = slice(binstart, binstop + 1)

    pi = np.float32(np.pi)  # IDL `!pi` is FLOAT (3.1415927), not DOUBLE.
    # `^bcoeff` is FLOAT^FLOAT: the double power rounded to FLOAT (`_idl_powf`;
    # numpy's float32 power is the platform `powf`, which agreed under the MSVC
    # runtime, and is one ULP off under glibc); `^3` at `:44` is an INT
    # exponent, i.e. (x*x)*x, which it does not.
    mass: np.ndarray = acoeff_f * _idl_powf(midbins / np.float32(1.0e4), bcoeff_f)
    mass_lwc = pi / np.float32(6) * _idl_cube(midbins / np.float32(1.0e4))
    mass = np.minimum(mass, mass_lwc * np.float32(0.91))  # `:45`
    if acoeff_f > np.float32(0.52) and bcoeff_f == np.float32(3.0):
        mass = mass_lwc.copy()  # `:46` -- silent water switch
    dm6 = (np.float32(6) / pi) ** 2 * mass ** 2 * np.float32(1.0e6)
    third = np.float32(1.0) / np.float32(3.0)  # `1.0/3.0`, FLOAT / FLOAT
    midbins_melted = _idl_powf(np.float32(6) / pi * mass, third) * np.float32(1.0e4)

    iwc = np.zeros(num, dtype=np.float32)
    lwc = np.zeros(num, dtype=np.float32)
    dmass = np.zeros(num, dtype=np.float32)
    dmassw = np.zeros(num, dtype=np.float32)
    dmassmelted = np.zeros(num, dtype=np.float32)
    dmedianmass = np.zeros(num, dtype=np.float32)
    z = np.zeros(num, dtype=np.float32)
    msd = np.zeros_like(conc1d_arr)
    msdnorm = np.zeros_like(conc1d_arr)

    # Every `total` below is IDL's sequential FLOAT accumulation (`_idl_total`),
    # not numpy's pairwise sum and not float64 -- the 1-2 ULP gap the export bank measured
    # through soda2_export_ncdf's netCDF (bank run_soda2_compute_bulk_simple).
    for i in range(num):
        spec = conc1d_arr[i, :] * binwidth / np.float32(1.0e6)
        iwc[i] = _idl_total((mass * spec)[sl])
        lwc[i] = _idl_total((mass_lwc * spec)[sl])
        z[i] = _idl_total((dm6 * spec)[sl])
        msd[i, :] = mass * spec
        msdnorm[i, :] = mass * spec / (binwidth / np.float32(1.0e6))
        if iwc[i] > 0:
            dmass[i] = _idl_total((mass * spec * midbins)[sl]) / iwc[i]
            dmassmelted[i] = _idl_total((mass * spec * midbins_melted)[sl]) / iwc[i]
            dmedianmass[i] = mmdiam((mass * spec)[sl],
                                     endbins_arr[binstart:binstop + 2])[0]
        if lwc[i] > 0:
            dmassw[i] = _idl_total((mass_lwc * spec * midbins)[sl]) / lwc[i]

    u = unnormalize(conc1d_arr, endbins_arr)
    nt = np.array([_idl_total(row, nan=True) for row in u[:, sl]], dtype=u.dtype)  # `:66`
    mvd = mvdiam(u[:, sl], endbins_arr[binstart:binstop + 2])
    mnd = meandiam(u[:, sl], midbins[sl])

    # `:71`: `10*(alog10(z))-7.2` -- INT 10 and the FLOAT literal 7.2 keep FLOAT.
    dbzw = np.float32(10) * _idl_alog10(z)
    dbz = dbzw - np.float32(7.2)

    return {
        "iwc": iwc, "lwc": lwc, "dmass": dmass, "dmedianmass": dmedianmass,
        "dmassw": dmassw, "dmassmelted": dmassmelted, "dbz": dbz, "dbzw": dbzw,
        "nt": nt, "mvd": mvd, "mnd": mnd, "msd": msd, "msdnorm": msdnorm,
        "massparam": mass, "massparamlwc": mass_lwc,
    }


# ---------------------------------------------------------------------------
# Format emulation -- one helper per ascii_format code, each pinned by the
# GDL bank (`run_soda2_export_ascii_bank.py`).
# ---------------------------------------------------------------------------

def _f_format(value: float, width: int, dec: int) -> str:
    """IDL ``fW.D``: fixed-point, width ``W`` (0 = auto), ``D`` decimals."""
    s = f"{float(value):.{dec}f}"
    return s if width == 0 else f"{s:>{width}}"


def _e_format(value: float, width: int, dec: int) -> str:
    """IDL ``eW.D``: scientific notation, sign always shown, exponent at
    least 2 digits (expanding further for extreme magnitudes -- measured on
    the PBP writer's ``tiny_inttime`` case, B8: ``1.00000e-120``, no
    truncation)."""
    s = f"{float(value):.{dec}e}"
    mantissa, exp = s.split("e")
    exp_i = int(exp)
    body = f"{mantissa}e{'+' if exp_i >= 0 else '-'}{abs(exp_i):02d}"
    return body if width == 0 else f"{body:>{width}}"


def _i_format(value: int, width: int) -> str:
    """IDL ``iW``: right-justified integer, width ``W`` (0 = auto)."""
    s = str(int(value))
    return s if width == 0 else f"{s:>{width}}"


def _a_format(value: str, width: int) -> str:
    """IDL ``aW``: right-justified string, width ``W`` (a longer value is
    printed in full, never truncated)."""
    return f"{value:>{width}}"


def _row_values(fmt: str, values: np.ndarray) -> str:
    """A whole ``(500<code>)`` row: IDL's ``500`` is a *repeat count*, not a
    width -- more than 500 values wraps onto a second output line, which
    this port refuses rather than silently emulating (no probe in scope has
    that many bins)."""
    if len(values) > 500:
        raise ValueError(
            f"soda2_export_ascii.pro: numbins={len(values)} exceeds the "
            "'(500...)' format's repeat count; the wrap-to-a-second-line "
            "behaviour is not ported")
    if fmt == "e12.2":
        return "".join(_e_format(v, 12, 2) for v in values)
    if fmt == "i12":
        return "".join(_i_format(int(v), 12) for v in values)
    if fmt == "f9.2":
        return "".join(_f_format(v, 9, 2) for v in values)
    if fmt == "e9.2":
        return "".join(_e_format(v, 9, 2) for v in values)
    raise ValueError(f"unhandled row format {fmt!r}")


# ---------------------------------------------------------------------------
# soda2_export_ascii
# ---------------------------------------------------------------------------

def soda2_export_ascii(
    data: Any,
    outfile: str | None = None,
    *,
    a: float | None = None,
    b: float | None = None,
    minsize: float | None = None,
    counts: int = 0,
) -> str:
    """``soda2_export_ascii.pro`` (158 lines), byte-for-byte. ``data`` is the
    ``ProcessData`` :func:`arrayprobe_soda2.process_2d.soda2_process_2d`
    returns: ``.op`` (a dict, lower-case keys, as elsewhere in this
    package), ``.conc1d``, ``.spec1d``, ``.midbins``, ``.sa``, ``.time``,
    ``.date_processed``.

    Returns the path written (``outfile`` if given, else the internal
    default naming, `:63` -- not exercised by the driver, which always
    passes ``outfile`` itself, `soda2_process_2d.pro:723-724`)."""
    op: Mapping[str, Any] = data.op
    lower = {k.lower(): v for k, v in op.items()}

    if minsize is None:
        minsize = 100.0
        if float(lower["res"]) <= 15:
            minsize = 50.0  # `:8-11`

    endbins = np.asarray(lower["endbins"], dtype=np.float32)
    ge = np.nonzero(endbins >= minsize)[0]
    if ge.size == 0:
        raise MinsizeOutOfRange(
            "soda2_export_ascii.pro:14-15: min(where(endbins ge minsize)) "
            f"is -1 for minsize={minsize} against endbins up to "
            f"{float(endbins[-1])}")
    iminsize = int(ge.min())
    minsizestring = _f_format(float(endbins[iminsize]), 0, 2)  # `f0.2`

    # `:7-8` of compute_bulk_simple.pro -- visible back here because IDL
    # keyword arguments are by reference (surprise 1).
    if a is None:
        a = 0.00294
    if b is None:
        b = 1.9
    bulk100 = compute_bulk_simple(data.conc1d, endbins, binstart=iminsize,
                                   acoeff=a, bcoeff=b)

    # `:19-51` -- housekeeping columns, written as `i12` per row (`:153`).
    housetitles, houseshortnames, housedata = _house_columns(
        data, lower.get("probetype"), len(np.asarray(data.time)))

    if int(counts) == 1:
        longname = "counts"
        description = "CountXXX: Particle counts per size bin [#]"
    else:
        longname = "concentration"
        description = ("ConcXXX: Particle concentration per size bin, "
                        "normalized by bin width [#/m4]")

    if outfile is None:
        outfile = pbp_filename(
            op, str(lower["shortname"]) + "_" + longname.upper(),
            extension=".txt", outdir="")  # `:63`

    date = soda2_parsedate(str(lower["date"]))

    lines: list[str] = []
    if int(counts) == 1:
        lines.append(f"Particle counts for the {lower['probetype']} probe "
                      f"in {lower['project']}")
    else:
        lines.append(f"Particle size distributions for the "
                      f"{lower['probetype']} probe in {lower['project']}")
    if date.order == "mdy":
        lines.append(f"Flight date (mm/dd/yyyy):   {date.month}/{date.day}/{date.year}")
    if date.order == "ymd":
        lines.append(f"Flight date (yyyy/mm/dd):   {date.year}/{date.month}/{date.day}")
    lines.append(f"Processed:   {data.date_processed}")
    lines.append(f"Raw data source:  {lower['fn']}")
    lines.append(f"Sizing method:  {lower['smethod']}")
    if "eawmethod" in lower:
        lines.append(f"Partial particle method:  {lower['eawmethod']}")
    if "reconstruct" in lower:
        lines.append("Partial particle reconstruction:  " +
                      ("off", "on")[int(lower["reconstruct"])])
    if "inttime_reject" in lower:
        lines.append("Shattering correction:  " +
                      ("off", "on")[int(lower["inttime_reject"])])
    if "timereject" in lower:
        lines.append(f"Shattering correction:  {lower['timereject']}")
    lines.append("Liquid water processing:  " +
                  ("off", "on", "strict")[int(lower["water"])])
    lines.append("")
    lines.append("Bin midpoints (microns):")
    lines.append(_row_values("f9.2", np.asarray(data.midbins, dtype=np.float32)))
    lines.append("Bin endpoints (microns):")
    lines.append(_row_values("f9.2", endbins))
    dofconst = float(lower["dofconst"]) if "dofconst" in lower else 0.0
    doftitle = ("Sample area using a depth of field constant of "
                f"{_f_format(dofconst, 0, 2)} (m^2):")
    if "customdof" in lower and float(np.max(np.asarray(lower["customdof"]))) > 0:
        doftitle = "Sample area (m^2) using a custom depth of field constant:"
    lines.append(doftitle)
    lines.append(_row_values("e9.2", np.asarray(data.sa, dtype=np.float32)))
    lines.append("")
    lines.append("Notes:")
    lines.append(f"   All bulk properties are computed using particles "
                 f"larger than {minsizestring} microns in size.")

    water = int(lower["water"])
    if water >= 1:
        if water == 1:
            lines.append('   This file contains "round" particles only, '
                         'with area ratio > 0.5 and diameter < 6mm.')
        if water == 2:
            lines.append('   This file contains "round" particles only, '
                         'with area ratio > 0.7 and diameter < 6mm.')
        lines.append("   The intent is to process liquid drops only, "
                     "there may be substantial errors in LWC when ice "
                     "particles are also present.")
        masstitle = "LWC: Estimated Liquid Water Content [g/m3]"
        massshortname = "LWC"
        mass = bulk100["lwc"]
        diamtitle = "MVD: Median Volume Diameter [microns]"
        diamshortname = "MVD"
        diam = bulk100["mvd"]
    else:
        lines.append("   Size distributions were processed using ice "
                     "rejection criteria.")
        lines.append("   Mass-size parameterization coefficients: a=" +
                     _e_format(a, 10, 2) + ", b=" + _f_format(b, 4, 2))
        masstitle = "IWC: Estimated Ice Water Content [g/m3]"
        massshortname = "IWC"
        mass = bulk100["iwc"]
        diamtitle = "MMD: Median Mass-weighted Diameter [microns]"
        diamshortname = "MMD"
        diam = bulk100["dmedianmass"]
    lines.append("")

    numbins = len(np.asarray(data.midbins))
    shortname_word = "Count" if int(counts) == 1 else "Conc"
    titles = [
        "Time: Time at start of interval [UTC seconds]",
        f"Nt: Total Concentration for Particles with D>{minsizestring}um [#/m3]",
        masstitle, diamtitle, *housetitles, description,
    ]
    shortnames = [
        "Time", "Nt", massshortname, diamshortname, *houseshortnames,
        *[f"{shortname_word}{i + 1:03d}" for i in range(numbins)],
    ]

    lines.append("Variables:")
    for title in titles:
        lines.append(f"   {title}")
    lines.append("")
    lines.append(_a_format(shortnames[0], 6) +
                 "".join(_a_format(s, 12) for s in shortnames[1:]))
    lines.append("----------------------------------------------------")

    nt = np.where(np.isfinite(bulk100["nt"]), bulk100["nt"], 0.0)
    mass = np.where(np.isfinite(mass), mass, 0.0)
    diam = np.where(np.isfinite(diam), diam, 0.0)

    # `:138-139` -- mutates the CALLER's `data.conc1d` in place (surprise 2):
    # `data` was passed by reference into `soda2_export_ascii`, so any
    # further reader of the same `ProcessData` (e.g. a SAVE file written
    # afterward) sees zeros, not NaN, at these positions.
    conc1d = data.conc1d
    conc1d[~np.isfinite(conc1d)] = 0.0

    if int(counts) == 1:
        data2write = data.spec1d
        row_fmt = "i12"
    else:
        data2write = conc1d
        row_fmt = "e12.2"

    time_arr = np.asarray(data.time)
    with open(outfile, "w", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")
        for i in range(len(time_arr)):
            prefix = (_i_format(int(time_arr[i]), 6) +
                     _e_format(float(nt[i]), 12, 2) +
                     _e_format(float(mass[i]), 12, 2) +
                     _e_format(float(diam[i]), 12, 2) +
                     "".join(_i_format(int(col[i]), 12) for col in housedata))
            f.write(prefix + _row_values(row_fmt, data2write[i, :]) + "\n")

    return str(outfile)
