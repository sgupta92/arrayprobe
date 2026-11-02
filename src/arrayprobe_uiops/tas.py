# SPDX-License-Identifier: BSD-3-Clause
"""True-airspeed repair and the probe/aircraft TAS ratio (UIOOPS v3.5).

Ported from: ``read_binary_SPEC.m`` (UIOOPS v3.5), the TAS machinery added by
Joe Finlon 11/3/19 and extended 5/13/22. **None of this exists in v3.1.4** --
`interp_tas` is absent from that file entirely, and the v3.1.4 reader has no
`tasRatio`, no aircraft-TAS input and no TAS-update gate. This is new surface,
not a changed translation, which is why it is its own module rather than a
delta on ``arrayprobe.readers.spec``.

The TAS machinery of the v3.5 port, ported and oracle-validated,
leaving ``read_binary_SPEC``'s record-walking driver for its own session.
Every function here is pure -- no file handles, no netCDF, no binary buffers --
which is exactly why this slice could be separated out and validated on its own.

**Fidelity.** Bug-for-bug, as everywhere in this project. Three behaviours below
are faithful reproductions of measured MATLAB/Octave behaviour that a reader of
the source would not predict, and each is preserved rather than fixed:

1. **A negative TAS is neither good nor bad.** ``interp_tas`` selects nodes with
   ``tasValues > 0`` and targets with ``tasValues == 0 | isnan``. A negative
   value satisfies neither, so it is *excluded from the interpolation nodes and
   left in place unrepaired*. This matters because ``-999.`` is the file's own
   sentinel for an uncorrectable probe TAS (``read_binary_SPEC.m:186``), so a
   ``-999`` can survive into ``fltTAS_fixed``, pass the ``~isnan`` guard at
   ``:185``, and produce a negative ``tasRatio``. Measured, not read.
2. **Leading and trailing bad values are never repaired.** MATLAB's ``interp1``
   does not extrapolate, so a bad value outside the span of the good nodes
   becomes ``NaN``. Benign in context -- ``:185``'s ``~isnan`` guard then falls
   back to ``tasRatio = 1.0`` -- but it means "fix bad TAS values", the
   function's own comment, is true only in the interior.
3. **Fewer than two good nodes raises.** ``interp1`` needs two points, so a TAS
   array that is entirely zero/NaN (a dead TAS feed) aborts the decode rather
   than degrading to a fallback. Reproduced as ``InterpTasError``.

Interpolation is over *index* coordinates, not over the values, so a
non-monotonic TAS series interpolates between its neighbours by position.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

#: What these functions accept for a TAS or flight-time series. Every one of
#: them calls ``np.asarray`` on its input, so an ndarray is not merely tolerated
#: -- it is what :func:`interp_tas` hands to :func:`tas_ratio` in the v3.5
#: driver (``arrayprobe_uiops.spec.read_binary_spec_v35``). Named so that is a
#: declared part of the interface rather than something a caller has to
#: discover.
Series = Sequence[float] | np.ndarray

__all__ = [
    "AmbiguousFlightTimeError",
    "Series",
    "InterpTasError",
    "interp_tas",
    "tas_ratio",
    "update_tas",
]

#: ``read_binary_SPEC.m:407-408``. A probe TAS reading of exactly this value is
#: treated as untrustworthy and the previous record's value is kept instead.
#: The number is upstream's, unexplained there; it coincides with the 2D-S
#: ``tasMax`` cap used elsewhere in UIOOPS, which is worth knowing but is not
#: stated by either site to be the reason.
SUSPECT_TAS = 170.0


class AmbiguousFlightTimeError(ValueError):
    """More than one flight-time row matched one record's timestamp.

    Upstream builds a vector ``tasRatio`` here and writes it with a count of
    one; what MATLAB does with that is unestablished, so this port refuses
    rather than inventing the answer. See :func:`tas_ratio`.
    """


class InterpTasError(ValueError):
    """``interp1`` could not run: fewer than two usable TAS nodes.

    MATLAB's message is ``interp1: minimum of 2 points required in each
    dimension``; Octave's is identical, which is how it was measured.
    """


def interp_tas(tas_values: Series) -> np.ndarray:
    """Repair zero/NaN TAS values by linear interpolation over index position.

    ``read_binary_SPEC.m:453-461``. See this module's docstring for the three
    preserved behaviours -- negatives untouched, ends unrepaired, and a raise
    below two good nodes.
    """
    values = np.asarray(tas_values, dtype=float)
    out = values.copy()
    good = np.flatnonzero((values > 0) & ~np.isnan(values))
    bad = np.flatnonzero((values == 0) | np.isnan(values))
    if bad.size == 0:
        return out
    if good.size < 2:
        raise InterpTasError("interp1: minimum of 2 points required in each dimension")
    # np.interp clamps outside the node span; MATLAB's interp1 returns NaN there.
    interpolated = np.interp(bad, good, values[good])
    interpolated[(bad < good[0]) | (bad > good[-1])] = np.nan
    out[bad] = interpolated
    return out


#: A probe TAS as the reader carries it: a numpy float32 once it came from a
#: housekeeping packet (MATLAB single), a float for the initial -999 (double).
TasValue = float | np.float32


def update_tas(tas_temp: TasValue, tas_prev: TasValue, n_hol: int, n_vol: int) -> TasValue:
    """The per-record TAS update gate, ``read_binary_SPEC.m:406-414``.

    A new reading replaces the running value only when it differs from it and is
    not itself suspect: a reading of exactly :data:`SUSPECT_TAS`, or any holdover
    or overload count on either channel, keeps the previous value instead.

    Returns the TAS to use for this record, which is also the next record's
    ``tasPrev``. The MATLAB writes ``tasPrev = tas`` only inside the
    ``tasTemp ~= tasPrev`` branch; when the branch is not taken the two are
    already equal, so the single return value here is faithful, not a
    simplification.
    """
    if tas_temp != tas_prev:
        if tas_temp == SUSPECT_TAS or (n_hol + n_vol) > 0:
            return tas_prev
        return tas_temp
    return tas_prev


def tas_ratio(
    img_tas: float,
    flt_time: Series,
    flt_tas_fixed: Series,
    hour: int,
    minute: int,
    second: int,
) -> float:
    """Probe-to-aircraft TAS ratio for one record, ``read_binary_SPEC.m:176-193``.

    ``flt_tas_fixed`` is the aircraft TAS series already passed through
    :func:`interp_tas`. Returns ``1.0`` -- "assume the probe TAS is correct" --
    whenever the aircraft series has nothing usable at this record's time, and
    likewise when the probe's own TAS is the ``-999.`` uncorrectable sentinel.

    **The date-crossover dummy** (``:177-181``, Finlon 5/13/22): when the flight
    time series runs past 240000 and this record's hour is before noon, the
    record is looked up at ``hour + 24``. The shifted hour is used for the
    lookup only and is never written.
    """
    times = np.asarray(flt_time, dtype=float)
    fixed = np.asarray(flt_tas_fixed, dtype=float)
    if times.size == 0:
        # :177 reads `fltTime(end)` before the `&&` can short-circuit, so an
        # empty aircraft series raises in MATLAB (Octave 8.4, measured:
        # tests/data/v35_tas_ratio_octave_golden.json case b11). Pass 6.
        raise IndexError(
            "read_binary_SPEC.m:177: fltTime(0): subscripts must be either "
            "integers 1 to (2^63)-1 or logicals (empty aircraft time series)"
        )
    hour2 = hour + 24 if times.size and times[-1] >= 240000 and hour < 12 else hour
    index = np.flatnonzero(times == hour2 * 10000 + minute * 100 + second)
    if index.size == 0:
        return 1.0
    # MATLAB's `if ~isnan(v)` over a vector is true only when EVERY element is,
    # and `find` can match more than one row. Preserved rather than collapsed to
    # index[0], because the multi-match case is where upstream breaks.
    if np.isnan(fixed[index]).any():
        return 1.0
    if img_tas == -999.0:
        return 1.0
    if index.size > 1:
        # Upstream would build a vector here and hand it to
        # `netcdf.putVar(f, varid10, kk1-1, 1, tasRatio)` -- a count of one. What
        # MATLAB does with that is not established, and guessing a scalar would
        # invent a fidelity claim, so this refuses instead. Reachable only from a
        # flight-time series with duplicate timestamps.
        raise AmbiguousFlightTimeError(
            f"{index.size} flight-time rows match {hour2:02d}:{minute:02d}:{second:02d}; "
            "read_binary_SPEC.m:184-189 would produce a vector tasRatio here"
        )
    # `imgTAS ./ fltTAS_fixed(...)` (:188) is single ./ double, which MATLAB
    # evaluates as single(imgTAS) / single(fltTAS) in single arithmetic
    # (Octave-measured, pass 5 item 4: 4917 of 20000 random pairs differ by one
    # float32 ULP from the double quotient rounded once; applied pass 6).
    # spec.py's outer np.float32() is therefore a no-op, kept as a guard.
    return float(np.float32(img_tas) / np.float32(fixed[index[0]]))
