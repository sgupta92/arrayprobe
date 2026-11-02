# SPDX-License-Identifier: BSD-3-Clause
"""A reader for the ``.MK.csv`` sidecar ``read_binary_SPEC.m`` writes with no
line terminators at all -- the unterminated mask sidecar: *tooling*, since it reads an existing
file and computes no new number.

**Why the file has no newlines.** ``read_binary_SPEC.m:313-315`` declares
twenty ``%d`` conversions in its format string but supplies only nineteen
values (``timeWord``, sixteen ``MaskBits``, ``timeStart``, ``timeEnd``).
MATLAB's ``fprintf`` stops the instant the data runs out, dropping the
trailing ``' \\n'`` -- so every mask record in a run lands on one unbroken
line, confirmed by actually running the source under Octave (see
:class:`arrayprobe.readers.spec.SidecarWriter`'s docstring, which this port's
own writer reproduces byte-for-byte).

**Why a reader is still possible despite that.** Each record is a *fixed*
width -- exactly nineteen integers, each written as ``str(v) + ", "`` -- so
the file is unambiguously splittable by counting tokens, not by looking for a
delimiter that was never written. This module does the counting; it does not
try to recover the missing newlines, because there is nothing to recover them
*from* -- the information which byte offset MATLAB's writer happened to be at
when it moved to the next record was never distinguishable from "still the
same record" in the first place, and guessing would be exactly the kind of
invented fact this project's own doctrine refuses to produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: timeWord + 16 MaskBits + timeStart + timeEnd, matching read_binary_SPEC.m:314's argument list.
_RECORD_WIDTH = 19
_N_MASK_BITS = 16

__all__ = ["MaskRecord", "load_mask_csv"]


@dataclass(frozen=True)
class MaskRecord:
    """One automask event, in the order ``read_binary_SPEC.m:314`` writes it."""

    time_word: int
    mask_bits: tuple[int, ...]
    time_start: int
    time_end: int


def load_mask_csv(path: str | Path) -> list[MaskRecord]:
    """Parse a ``.MK.csv`` sidecar into its fixed-width records.

    Source: reads what ``read_binary_SPEC.m:314-315`` (UIOOPS v3.1.4) writes.

    Raises :class:`ValueError` if the file's token count is not a multiple of
    nineteen -- a truncated write or a file that is not actually a mask
    sidecar, either of which should stop a caller rather than silently drop
    a partial trailing record.
    """
    text = Path(path).read_text(encoding="ascii")
    tokens = [t for t in text.split(",") if t.strip()]
    if len(tokens) % _RECORD_WIDTH != 0:
        raise ValueError(
            f"{path}: {len(tokens)} comma-separated values is not a multiple of "
            f"{_RECORD_WIDTH} -- not a well-formed .MK.csv (or it was truncated)")
    values = [int(t) for t in tokens]
    records = []
    for i in range(0, len(values), _RECORD_WIDTH):
        row = values[i:i + _RECORD_WIDTH]
        records.append(MaskRecord(
            time_word=row[0],
            mask_bits=tuple(row[1:1 + _N_MASK_BITS]),
            time_start=row[1 + _N_MASK_BITS],
            time_end=row[2 + _N_MASK_BITS],
        ))
    return records
