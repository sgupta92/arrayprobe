# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_process_2d.pro:147-172`` -- the ASCII/CSV and netCDF PTH (true
airspeed) readers. The ``dat``/``sav`` branch (``:131-145``) is
``process_2d._pth_from_sav``; this module is the other two formats.

Provenance: ``SODA2/abansemer-soda2-afcea15/soda2_process_2d.pro:147-172``
plus ``restorenc.pro`` / ``ncdf2sav.pro`` (the netCDF branch's reader), Aaron
Bansemer, NCAR. Copyright (C) 2016 UCAR, 3-clause BSD. Validated against GDL
by ``tests/test_soda2_pth_readers.py``; bank
``gdl_oracle/run_soda2_pth_readers_bank.py`` lifts ``:126-127,129,147-172``
out of the vendored file verbatim at run time, over tiny synthetic fixtures
``tests/data/soda2_pth_*``; golden ``tests/data/gdl_soda2_pth_readers_golden.json``.

**ASCII/CSV (``:147-162``)**, suffix ``txt`` or ``csv``, line by line:

- ``:152`` ``readf,lun,v`` -- one line into a string. The file is split on
  ``\\n``; a CR before it stays in the string and is harmless (below). An
  empty file's first ``readf`` is an end-of-file I/O error, caught by
  ``:150``'s ``on_ioerror`` -- nothing is read.
- ``:153`` ``float(strsplit(v, '[ ,\\t]+', /regex, /extract))`` -- empty
  pieces dropped (leading blanks, a trailing comma). Each piece converts by
  its **longest numeric prefix** (``102x`` -> 102, ``1.00d2`` -> 100,
  ``0x68`` -> 104, ``NaN``/``Inf``); a piece with **no** numeric prefix is a
  type-conversion error, and ``on_ioerror`` jumps to ``bad:`` -- **the whole
  row is dropped, even when only a third, unused column is junk**. All
  GDL-measured (``csv_badtime``, ``csv_exotic``); the hex literal in
  particular is GDL's ``strtod`` and is not IDL-confirmed. The result is
  FLOAT, so a time is rounded to float32 **before** ``round()``:
  ``36001.4999`` becomes ``36001.5`` and indexes as 36002 (``txt_float32``).
- ``:154`` ``i = (round(fields[0]) - op.starttime)/op.rate > 0`` -- ``> 0``
  is IDL's maximum operator: a row **before** ``starttime`` is not rejected,
  it is clamped to record 0 and overwrites from there (``csv_window``). A NaN
  time rounds to LONG's most negative value and clamps the same way
  (``csv_nantime``). ``round`` is half away from zero.
- ``:156`` accepted when there are >= 2 fields, ``i lt numrecords`` and
  ``0 < fields[1] < 500`` -- **500**, where the SAVE (``:135``) and netCDF
  (``:167``) branches bound at 400. ``pth_tas[i:*] = fields[1]``: every
  accepted row fills forward to the end, so the last row read wins from its
  own index (out-of-order rows included). A DOUBLE subscript truncates.
- ``:161`` ``got_pth=1`` **unconditionally** -- a file with no accepted row
  (or no rows) still sets it, so ``aircrafttas`` becomes an all-zero
  ``pth_tas`` rather than falling back to the probe TAS (``txt_empty``,
  ``csv_allbad``). The SAVE branch stops at ``:136`` instead.

**netCDF (``:164-172``)**, suffix ``nc``:

- ``:165`` restores TIME and TASX from ``op.pth`` through ``restorenc`` -> ``ncdf2sav``,
  which upper-cases both the list and each variable name before comparing
  (its own comment says "case sensitive"; it is not -- ``nc_lowercase``), keeps
  the **first** variable of each name in variable-id order ("Skipped
  duplicate", ``nc_duplicate``), and reads with ``ncdf_varget``: **raw**
  values, no ``scale_factor``/``_FillValue`` (``nc_packed``).
- ``:167`` ``good = where(tasx gt 0 and tasx lt 400 and time ge starttime and
  time le stoptime)`` -- when TIME and TASX differ in length the ``and``
  truncates to the shorter (``nc_mismatch``). **No count is checked**: with
  no match ``where`` returns -1 and ``data.time[-1]``/``data.tasx[-1]`` are
  the **last** elements, so a TAS the filter just rejected still fills
  ``pth_tas`` from the last sample's record (``nc_nogood``, GDL-measured;
  IDL 8's negative scalar subscript reads the same, not IDL-confirmed).
- ``:168-170`` ``itas = (round(time[good]) - starttime)/rate``;
  ``pth_tas[itas[i]:*] = tasx[good[i]]``.
- A file without a TASX (or TIME) variable halts at ``:167`` ("Tag name
  ... is undefined for STRUCT", ``nc_notasx``): :class:`PthReaderHalt`.

**Refused by name** (unreached by the bank, so not ported): a TIME or TASX of
more than one dimension (high-rate ``TASX(Time, sps25)``), and a subscript
``:170`` would put outside ``pth_tas`` (IDL halts; which way GDL goes there
is unmeasured).

``starttime``/``rate`` are taken as Python floats (the DOUBLE literals every
driver bank uses). ``example_batch.pro:7,31`` passes INT ``starttime``/
``rate``, making ``:154``/``:168`` LONG division; for the non-negative
numerators an accepted row can have (``:154`` clamps; ``:167`` filters on
``time ge starttime``), LONG division and DOUBLE-then-truncate give the same
subscript (derived).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["PthReaderHalt", "pth_suffix", "read_pth_ascii", "read_pth_ncdf", "read_pth"]


def pth_suffix(pth: str) -> str:
    """``:129`` takes the suffix as the last dot-separated piece of ``op.pth``: the last
    non-empty ``.``-separated token (``strsplit`` drops empty tokens), the
    whole name when it has no ``.``, and ``''`` when every token is empty.
    Case-sensitive, as ``:131-164``'s ``eq`` tests are.

    Source: ``soda2_process_2d.pro:129`` (SODA-2)."""
    tokens = [t for t in pth.split(".") if t]
    return tokens[-1] if tokens else ""


class PthReaderHalt(RuntimeError):
    """An IDL halt inside ``:147-172``, raised naming the line."""


#: `:153`'s delimiter regex, `'[ ,' + STRING(9B) + ']+'`.
_SPLIT = re.compile(rb"[ ,\t]+")

#: The numeric prefix a GDL string-to-FLOAT conversion accepts, measured by
#: the bank: optional blanks and sign, then hex (`0x68`), NaN/Inf, or a
#: decimal with an optional `e`/`E`/`d`/`D` exponent.
_NUMBER = re.compile(
    rb"\s*([+-]?)(?:(0[xX][0-9a-fA-F]+)"
    rb"|(nan|inf(?:inity)?)"
    rb"|((?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?))",
    re.IGNORECASE,
)

_LONG_MIN = -(2 ** 31)


def _to_float32(piece: bytes) -> np.float32 | None:
    """One `:153` element; ``None`` is IDL's type-conversion error."""
    m = _NUMBER.match(piece)
    if m is None:
        return None
    sign = -1.0 if m.group(1) == b"-" else 1.0
    if m.group(2):
        value = float(int(m.group(2), 16))
    elif m.group(3):
        value = float(m.group(3).decode())
    else:
        value = float(m.group(4).replace(b"d", b"e").replace(b"D", b"e").decode())
    return np.float32(sign * value)


def _idl_round_long(value: float) -> int:
    """IDL ``ROUND`` of a FLOAT to LONG: half away from zero; NaN (and
    anything outside LONG) becomes LONG's most negative value, measured
    (``csv_nantime``) as clamping to record 0 through ``:154``'s ``> 0``."""
    if not np.isfinite(value):
        return _LONG_MIN
    r = int(np.floor(abs(value) + 0.5))
    r = -r if value < 0 else r
    if r > 2 ** 31 - 1 or r < _LONG_MIN:
        return _LONG_MIN
    return r


def read_pth_ascii(path: str | Path, starttime: float, rate: float,
                   numrecords: int) -> np.ndarray:
    """``:147-162`` -- returns ``pth_tas`` (float32[numrecords]); the caller
    sets ``got_pth = 1`` whatever this returns (``:161``).

    Source: ``soda2_process_2d.pro:147-162`` (SODA-2)."""
    pth_tas = np.zeros(numrecords, dtype=np.float32)  # `:127`
    content = Path(path).read_bytes()
    lines = content.split(b"\n")
    if content.endswith(b"\n"):
        lines = lines[:-1]  # `eof(lun)` is true after the last terminator
    for line in lines:
        pieces = [p for p in _SPLIT.split(line) if p != b""]
        if not pieces:
            continue  # `strsplit` returns '' -- at most one field: `:156` skips it
        parsed = [_to_float32(p) for p in pieces]
        fields = [f for f in parsed if f is not None]
        if len(fields) != len(parsed):
            continue  # `:150` on_ioerror -> `bad:`, the whole row
        i = max((_idl_round_long(float(fields[0])) - starttime) / rate, 0.0)
        tas = fields[1] if len(fields) > 1 else None
        if (tas is not None and i < numrecords
                and tas > 0 and tas < np.float32(500)):
            pth_tas[int(i):] = tas
    return pth_tas


def _first_var(ds: Any, upper: str) -> Any:
    """``ncdf2sav``: the first variable (id order) whose upper-cased name is
    ``upper``; later ones are "Skipped duplicate variable"."""
    for name, var in ds.variables.items():
        if name.upper() == upper:
            return var
    return None


def read_pth_ncdf(path: str | Path, starttime: float, stoptime: float,
                  rate: float, numrecords: int) -> np.ndarray:
    """``:164-172`` -- returns ``pth_tas`` (float32[numrecords]).

    Source: ``soda2_process_2d.pro:164-172`` (SODA-2)."""
    from netCDF4 import Dataset

    pth_tas = np.zeros(numrecords, dtype=np.float32)  # `:127`
    with Dataset(str(path), "r") as ds:
        tvar = _first_var(ds, "TIME")
        vvar = _first_var(ds, "TASX")
        for var, tag in ((tvar, "TIME"), (vvar, "TASX")):
            if var is None:
                raise PthReaderHalt(
                    f"soda2_process_2d.pro:167: Tag name: {tag} is undefined "
                    "for STRUCT (no such variable in the PTH netCDF)")
            var.set_auto_maskandscale(False)  # `ncdf_varget`: raw values
        # A high-rate (2-D, seconds x sps) variable is indexed in IDL's
        # element order, sps fastest -- C order of netCDF4's (time, sps)
        # array. With a 1-D TIME and a 2-D TASX the `and` below keeps the
        # shorter length, so second k's time pairs with second 0's samples
        # (GDL golden `nc_hirate_tasx2d`, SODA-2 finding S9-u).
        time = np.asarray(tvar[:]).ravel(order="C")
        tasx = np.asarray(vvar[:]).ravel(order="C")

    n = min(time.size, tasx.size)  # IDL `and` of unequal arrays: the shorter
    mask = ((tasx[:n] > 0) & (tasx[:n] < 400)
            & (time[:n] >= starttime) & (time[:n] <= stoptime))
    good = np.nonzero(mask)[0]
    if good.size == 0:
        good = np.array([-1])  # `where` -> -1, unchecked: the last element
    for g in good:
        t = float(time[g])
        if not np.isfinite(t):
            raise NotImplementedError(
                "soda2_process_2d.pro:168: round() of a non-finite TIME -- "
                "unmeasured")
        # `round()`: identity on integer types, half away from zero otherwise.
        rt = t if np.issubdtype(time.dtype, np.integer) else float(
            np.sign(t) * np.floor(abs(t) + 0.5))
        itas = (rt - starttime) / rate
        idx = int(np.trunc(itas))
        if not 0 <= idx < numrecords:
            raise NotImplementedError(
                f"soda2_process_2d.pro:170: subscript {itas!r} outside "
                f"pth_tas[0:{numrecords - 1}] -- IDL halts; unmeasured")
        pth_tas[idx:] = np.float32(tasx[g])
    return pth_tas


def read_pth(pth: str | Path, suffix: str, starttime: float, stoptime: float,
             rate: float, numrecords: int) -> tuple[np.ndarray, int]:
    """``:147-172`` dispatch on ``suffix`` (``:129``, case-sensitive):
    returns ``(pth_tas, got_pth)``. ``dat``/``sav`` is not this module's
    (``process_2d._pth_from_sav``); any other suffix raises ``ValueError``.

    Source: ``soda2_process_2d.pro:147-172`` (SODA-2)."""
    if suffix in ("txt", "csv"):
        return read_pth_ascii(pth, starttime, rate, numrecords), 1
    if suffix == "nc":
        return read_pth_ncdf(pth, starttime, stoptime, rate, numrecords), 1
    raise ValueError(f"read_pth: suffix {suffix!r} is not txt, csv or nc")
