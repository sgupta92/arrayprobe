# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""Reprocess-from-PBP: ``soda2_restore_pbp.pro`` and ``spec_newtime.pro``,
the two helpers ``soda2_process_2d.pro``'s ``fn_pbp`` branch (`:584-617`)
calls. Source: SODA-2 (``SODA2/abansemer-soda2-afcea15/``).

The driver half (the loop at `:599-613`) lives in
:func:`arrayprobe_soda2.process_2d.soda2_process_2d`; this module only reads
the ``.pbp.nc`` and recomputes the SPEC particle time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .particlesort import idl_median

__all__ = ["PbpRestoreError", "SpecNewtimeStop", "pbp_particle_count",
           "restore_pbp", "spec_newtime"]


class PbpRestoreError(RuntimeError):
    """An ``ncdf_varget`` read the IDL could not perform (offset past the end)."""


class SpecNewtimeStop(RuntimeError):
    """``spec_newtime.pro:7`` -- ``stop, 'File does not contain full rawtime,
    just truncated.'``"""


class SpecNewtimeSubscriptError(IndexError):
    """A subscript ``spec_newtime.pro`` evaluates out of range, where the IDL halts:
    ``rawtime[1:*]`` at `:10` on a one-particle file (GDL 8.4: "Subscript out of
    range [s:*]")."""


@dataclass
class RestoredPbp:
    """``soda2_restore_pbp``'s return: the per-particle columns (every
    variable whose length equals ``time``'s, `:17-24`) plus ``x.global``."""

    columns: dict[str, np.ndarray]
    global_attrs: dict[str, Any] = field(default_factory=dict)


def pbp_particle_count(fn: str) -> int:
    """`:587` -- ``restorenc, fn_pbp, 'pbp', var='time'``; only the length
    is used (`:599`, `:611`)."""
    import netCDF4

    with netCDF4.Dataset(fn, "r") as ds:
        return int(ds.variables["time"].shape[0])


def restore_pbp(fn: str, offset: int = 0, count: int | None = None) -> RestoredPbp:
    """``soda2_restore_pbp.pro:1-30`` over ``restorenc``/``ncdf2sav``.

    ``ncdf_varget`` with ``offset`` past the last record cannot read; IDL
    halts there (read from the IDL documentation, not measured under GDL),
    raised here as :class:`PbpRestoreError`. ``offset + count`` past the end
    reads to the end, IDL's documented ``COUNT`` reduction."""
    import netCDF4

    with netCDF4.Dataset(fn, "r") as ds:
        n = int(ds.variables["time"].shape[0])
        if offset >= n:
            raise PbpRestoreError(
                f"soda2_restore_pbp.pro:7 / ncdf2sav.pro:83 -- ncdf_varget "
                f"offset {offset} is past the {n} records in {fn}")
        stop = n if count is None else min(n, offset + count)
        cols: dict[str, np.ndarray] = {}
        for name, var in ds.variables.items():
            if var.ndim != 1 or var.shape[0] != n:
                continue
            arr = np.asarray(var[offset:stop])
            if isinstance(arr, np.ma.MaskedArray):
                arr = arr.data
            cols[name.lower()] = np.asarray(arr)
        glob = {a.lower(): ds.getncattr(a) for a in ds.ncattrs()}
    return RestoredPbp(columns=cols, global_attrs=glob)


def spec_newtime(rawtime: np.ndarray, buffertime: np.ndarray,
                 probetas: np.ndarray, yres: Any) -> np.ndarray:
    """``spec_newtime.pro:1-39`` on the columns ``restorenc`` reads (`:5`).

    Kept as the IDL has it:

    - `:7` stops unless ``max(rawtime) >= 2^31``.
    - `:15-16` ``where(..., nrollover)`` with no match returns ``-1``, and a
      scalar ``-1`` subscript is the last element, so with no rollover the
      **last** particle's counter delta gains ``2^32``.
    - `:19` ``yres/(1.0e6*probetas)`` is FLOAT arithmetic (``probetas`` is
      FLOAT in the file) widened to DOUBLE after the division.
    - `:23`, `:33` ``where(...)`` with no match is likewise ``-1``.
    - `:34` ``median`` without ``/EVEN`` (upper-middle element).
    - `:10` ``rawtime[1:*]`` on one particle is out of range and halts the IDL.
    - `:34` subscripts ``buffertime`` with ``itimematch[matches]`` but ``elaptime``
      with ``[itimematch[matches]]``. When ``matches`` is ``-1`` (no buffer end in
      the period) the inner value is a SCALAR, so ``buffertime``'s subscript wraps
      a negative index (``-2`` -> ``n-2``) while ``elaptime``'s, an array, is
      clipped to 0; when ``matches`` is an array both are clipped. Measured under
      GDL 8.4 (``tests/data/gdl_soda2_spec_newtime_single_buffer_golden.json``).
    """
    rawtime = np.asarray(rawtime, dtype=np.float64)
    buffertime = np.asarray(buffertime, dtype=np.float64)
    if float(rawtime.max()) < 2.0 ** 31:
        raise SpecNewtimeStop(
            "spec_newtime.pro:7: stop -- File does not contain full rawtime, just truncated.")
    n = rawtime.size
    if n < 2:
        raise SpecNewtimeSubscriptError(
            "spec_newtime.pro:10: Subscript out of range [s:*] (rawtime[1:*] on one particle)")
    # `:10-11` -- `[0, a[1:*] - a]`: the subtraction runs to the shorter operand.
    dcounter = np.concatenate([[0.0], rawtime[1:] - rawtime[:-1]])
    dbuffer = np.concatenate([[0.0], buffertime[1:] - buffertime[:-1]])
    # `:15-16`.
    rollover = np.nonzero((dcounter < 0) | (dbuffer > 200))[0]
    nrollover = rollover.size
    if nrollover == 0:
        dcounter[-1] += 2.0 ** 32  # `where` -> -1 -> last element
    else:
        dcounter[rollover] += 2.0 ** 32
    # `:19-20`.
    probetas32 = np.asarray(probetas, dtype=np.float32)
    freq = (np.float32(yres) / (np.float32(1.0e6) * probetas32)).astype(np.float64)
    inttime = dcounter * freq
    # `:23-25`.
    hits = np.nonzero(dbuffer > 0)[0]
    itimematch = (hits - 1) if hits.size else np.array([-2])
    newtime = buffertime.copy()
    elaptime = buffertime * 0.0
    # `:28-36` -- no `-1` on the loop bound.
    for i in range(nrollover + 1):
        istart = 0 if i == 0 else int(rollover[i - 1])
        istop = n - 1 if i == nrollover else int(rollover[i]) - 1
        elaptime[istart:istop + 1] = np.cumsum(inttime[istart:istop + 1])
        matches = np.nonzero((itimematch >= istart) & (itimematch <= istop))[0]
        if matches.size == 0:
            # `where` -> scalar -1 -> the last element, a SCALAR subscript value:
            # `buffertime[v]` wraps a negative v (IDL halts below -n), while
            # `elaptime[[v]]` is an array subscript and is clipped.
            v = int(itimematch[-1])
            if v < -n:
                raise SpecNewtimeSubscriptError(
                    f"spec_newtime.pro:34: Scalar subscript out of range [<0]: ({v})")
            b_idx = np.array([v + n if v < 0 else v])
            e_idx = np.clip(np.array([v]), 0, n - 1)
        else:
            # An array subscript out of range is clipped by IDL, not wrapped.
            b_idx = e_idx = np.clip(itimematch[matches], 0, n - 1)
        offset = idl_median(buffertime[b_idx] - elaptime[e_idx])
        newtime[istart:istop + 1] = elaptime[istart:istop + 1] + offset
    return newtime
