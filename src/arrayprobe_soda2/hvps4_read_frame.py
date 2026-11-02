# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``hvps4_read_frame.pro`` -- read one HVPS-4 frame (SPEC subformat 2).

67 lines of IDL, Aaron Bansemer, NCAR, 8/2022. Copyright (C) 2016 UCAR,
3-clause BSD. Provenance: ``SODA2/abansemer-soda2-afcea15/hvps4_read_frame.pro``.
Validated against GDL by ``tests/test_soda2_hvps4_read_frame.py``; bank at
``gdl_oracle/run_soda2_hvps4_read_frame_bank.py`` (synthetic fixture). GDL
cannot run ``:39-40``'s IDL string methods, so the bank runs an oracle-path
shim of those two lines (``gdl_oracle/shims/hvps4_read_frame.pro``); which
block runs (``array``/``res``) is shim-derived.

**Line-by-line** (IDL 0-based indexing; every slice below is the source's):

- `:11-14` -- seek, ``x = spec_readint(lun, 3)``; ``nh``/``nv`` low 12 bits.
- `:17-22` -- bit 12 missing time word, **bit 14 the array resolution**
  (1 = 50 um, 0 = 150 um; 2D-S reads it as the empty-FIFO flag), bit 15 overload.
- `:25` -- reads ``2+nh+nv`` words with ``spec_readint``, with the undecremented counts.
- `:31-36` -- defaults: one blank slice, ``time = 0L`` (LONG), ``error = 1``,
  ``overload = 0`` (INT).
- `:39-42` -- ``array`` is ``id``'s first letter, ``res`` its integer tail;
  the frame is decoded only when the letter **and** the bit-14 resolution
  match. ``'h50'`` matches nothing (``eq`` is case-sensitive).
- `:44-53` -- H block, ``nh gt 3``: ``nh = nh-1``; image ``buff[2:nh-1]``;
  counter ``ulong(buff[nh:nh+2])``; ``time = ishft(c[2],32) + ishft(c[1],16)
  + c[0]`` in ULONG. **Measured under GDL: ``ishft(ULONG, 32)`` returns its
  operand unshifted** (the shift count is taken mod 32, as x86 does), so
  ``c[2]`` is *added* to the time, and the sum wraps mod 2**32 (bank case
  ``high_counter``; whether IDL agrees is an open oracle question, flagged, not measured).
  ``error = missingtwh`` -- a split particle is dropped, never stitched.
- `:55-64` -- V block, same shape, image ``buff[2:nv-1]`` and counter
  ``buff[nv:nv+2]`` with **no** ``nh`` offset (a SODA-2 finding, preserved: on a frame with
  both arrays the V block reads the H words; bank case ``dual_v50``).
- `:66` -- ``{image, time, error, overload, particlecount}``; no ``imageraw``,
  no ``timetrunc``, no ``nn eq 2`` check.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

import numpy as np

from .spec_decompress import spec_decompress
from .spec_readint import spec_readint

__all__ = ["Hvps4Frame", "hvps4_read_frame"]

_MASK_12BIT = 0xFFF


@dataclass
class Hvps4Frame:
    """``hvps4_read_frame``'s return struct (`:66`), IDL types carried as
    NumPy scalar dtypes as GDL reports them (bank ``TN`` field)."""

    #: ``(numslices, 128)`` uint8 (the package's transpose of ``bytarr(128,n)``).
    image: np.ndarray
    #: ULONG (``np.uint32``) when a block ran; LONG ``0`` (``np.int32``) otherwise.
    time: np.uint32 | np.int32
    #: INT.
    error: np.int16
    #: LONG when a block ran (``ishft`` of ``x and '8000'x``); INT ``0`` otherwise.
    overload: np.int32 | np.int16
    #: UINT, ``buff[0]``.
    particlecount: np.uint16


def _ishft_ulong(value: int, shift: int) -> int:
    """GDL's measured ``ishft`` on a ULONG: count taken mod 32, result mod 2**32."""
    return (value << (shift % 32)) & 0xFFFFFFFF


def hvps4_read_frame(f: BinaryIO, bpoint: int, id: str) -> Hvps4Frame:
    """``q = hvps4_read_frame(lun, bpoint, id)``; ``id`` is e.g. ``'H50'``.

    Source: ``hvps4_read_frame.pro`` (SODA-2)."""
    f.seek(bpoint)  # `:11`
    x = spec_readint(f, 3)  # `:12`
    nh = int(x[1]) & _MASK_12BIT
    nv = int(x[2]) & _MASK_12BIT
    missingtwh = (int(x[1]) & 0x1000) >> 12
    missingtwv = (int(x[2]) & 0x1000) >> 12
    arrayhid = (int(x[1]) & 0x4000) >> 14
    arrayvid = (int(x[2]) & 0x4000) >> 14
    overloadh = (int(x[1]) & 0x8000) >> 15
    overloadv = (int(x[2]) & 0x8000) >> 15

    buff = spec_readint(f, 2 + nh + nv)  # `:25`
    particlecount = np.uint16(buff[0])

    image = np.zeros((1, 128), dtype=np.uint8)
    time: np.uint32 | np.int32 = np.int32(0)
    error = np.int16(1)
    overload: np.int32 | np.int16 = np.int16(0)

    # `:39-40`, IDL ``substring(0,0)`` / ``fix(substring(1,3))``.
    array = id[0:1]
    res = int(id[1:4])
    arrayhres = 50 if arrayhid == 1 else 150
    arrayvres = 50 if arrayvid == 1 else 150

    def _block(n: int, overload_bit: int, missingtw: int) -> None:
        nonlocal image, time, error, overload
        n -= 1  # `:45` / `:56`
        imageraw = buff[2:n].copy()  # IDL [2:n-1] inclusive
        c = buff[n:n + 3].astype(np.uint32)  # IDL [n:n+2]
        t = (_ishft_ulong(int(c[2]), 32) + _ishft_ulong(int(c[1]), 16)
             + int(c[0])) & 0xFFFFFFFF
        time = np.uint32(t)
        image = spec_decompress(imageraw, overload_bit, version=1)
        error = np.int16(1 if missingtw else 0)
        overload = np.int32(overload_bit)

    if nh > 3 and array == "H" and arrayhres == res:  # `:44`
        _block(nh, overloadh, missingtwh)
    if nv > 3 and array == "V" and arrayvres == res:  # `:55`, no nh offset (preserved)
        _block(nv, overloadv, missingtwv)

    return Hvps4Frame(image=image, time=time, error=error, overload=overload,
                      particlecount=particlecount)
