# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""`soda2_buildindex.pro:8-17` (SPEC branch);
the generic `REPEAT` loop at `:20-61`, reached for SEA (the CIP
route through :func:`read2dbuffer.read2dbuffer_sea`) -- :func:`buildindex_generic`.

Vendored source: `SODA2/abansemer-soda2-afcea15/soda2_buildindex.pro`.
Bank: `gdl_oracle/run_soda2_preloop_bank.py`, golden
`tests/data/gdl_soda2_preloop_golden.json`.
"""
from __future__ import annotations

import gzip
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np

from .spec_index import SpecIndex, spec_index

#: `:32` -- ``bignumber = 5000000``, the index arrays' fixed length.
_BIGNUMBER = 5_000_000


@dataclass
class GenericIndex:
    """`soda2_buildindex.pro:60`'s ``{bufftime, date, pointer, count, error}``,
    or the error returns ``{error:2}`` (empty file, `:28`) and ``{error:1}``
    (fewer than two buffers, `:54`), which carry ``count=0`` here. ``pointer``
    and ``date`` are LONG (`:33,:35` ``lonarr``), ``bufftime`` DOUBLE."""

    bufftime: np.ndarray
    date: np.ndarray
    pointer: np.ndarray
    count: int
    error: int


def buildindex_generic(path: str | Path, op: dict) -> GenericIndex:
    """`soda2_buildindex.pro:20-61`: walk the file with ``soda2_read2dbuffer``
    and keep every buffer with ``eof eq 0`` and ``0 < time < 200000``
    (`:42`; ``time`` already includes ``op.timeoffset``). A ``.gz`` file is
    opened decompressed (`:22-24`, ``compress=1``); the SPEC branch (`:8-17`)
    opens without ``compress=``, as IDL does."""
    from .read2dbuffer import read2dbuffer

    fn = str(path)
    compress = fn[-3:] == ".gz"                                   # :21-22
    # :25 `fstat(1).size` on a `compress=1` lun is the compressed on-disk
    # length (GDL-measured: 279 for a 256-byte payload; 20 for an empty .gz),
    # so an empty .gz never takes the error-2 branch and walks to EOF at once.
    if os.path.getsize(fn) == 0:                                   # :25-29
        return GenericIndex(np.zeros(0), np.zeros(0, np.int32), np.zeros(0, np.int32), 0, 2)
    with (gzip.open(fn, "rb") if compress else open(fn, "rb")) as f:  # :24
        pointer: list[int] = []
        bufftime: list[float] = []
        date: list[int] = []
        while True:                                                # :39-49
            x = read2dbuffer(f, op)  # type: ignore[arg-type]
            if x.eof == 0 and 0 < float(x.time) < 200000:
                if len(pointer) >= _BIGNUMBER:
                    raise RuntimeError("soda2_buildindex.pro:43: pointer[c] subscript out of range")
                pointer.append(int(x.pointer))
                bufftime.append(float(x.time))
                date.append(int(x.date))
            if x.eof == 1:
                break
    c = len(pointer)
    if c < 2:                                                      # :52-54
        return GenericIndex(np.zeros(0), np.zeros(0, np.int32), np.zeros(0, np.int32), 0, 1)
    return GenericIndex(bufftime=np.asarray(bufftime, dtype=np.float64),
                        date=np.asarray(date, dtype=np.int32),
                        pointer=np.asarray([lonarr_store(p) for p in pointer], dtype=np.int32),
                        count=c, error=0)


def lonarr_store(value: int) -> int:
    """What `pointer[c] = x.pointer` (`soda2_buildindex.pro:43`) leaves in a
    `lonarr` element: IDL/GDL converts a LONG64 to 32-bit LONG by two's-complement
    wrap, with no error (measured under GDL,
    `tests/data/gdl_soda2_lonarr_wrap_golden.json`: 2147483648 -> -2147483648,
    3000000000 -> -1294967296, 5000000000 -> 705032704). NumPy's `int32` cast
    raises instead, so the wrap is done explicitly here."""
    return ((int(value) + 2**31) % 2**32) - 2**31


def point_lun(f: BinaryIO, pointer: int) -> None:
    """`soda2_process_2d.pro:451` ``point_lun, lun, pointer``. Under GDL a
    negative (wrapped, S9-t) pointer is ignored: the position is unchanged
    and no error is raised (golden ``negative_seek``)."""
    if int(pointer) >= 0:
        f.seek(int(pointer))


def buildindex(path: str | Path, op: dict) -> SpecIndex | GenericIndex:
    """`soda2_buildindex.pro:8-17`. Opens `path`, calls `spec_index` with
    **no keywords** (`:12`), closes, then adds `op["timeoffset"]` to
    `bufftime` (`:15`) -- same FLOAT-widening rule as
    `read2dbuffer.read2dbuffer_spec` (T7). `spec_index`'s own exceptions
    (`SpecIndexError`, `SpecFileMisaligned`) propagate unchanged. Any other
    format takes the generic walk (`:20-61`, :func:`buildindex_generic`)."""
    if op.get("format") != "SPEC":
        return buildindex_generic(path, op)

    with open(path, "rb") as f:
        idx = spec_index(f)  # no keyword -> always SpecIndex, never SpecIndexLite
    assert isinstance(idx, SpecIndex)

    offset = float(op.get("timeoffset", 0.0))  # FLOAT -> DOUBLE widening (T7)
    idx.bufftime = idx.bufftime + offset
    return idx
