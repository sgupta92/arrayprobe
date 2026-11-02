# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``spec_read_hk.pro`` -- read one HVPS3/2DS housekeeping record: 48 diode
voltages, a custom-encoded TAS, and a 32-bit time word.

68 lines of IDL. Signature `spec_read_hk(lun, bpoint, buffsize, version=version)`.
`bpoint` is the byte offset of the `'HK'` marker word itself
(`spec_index.pro:123-124` records it at the word whose value is 18507), so
`x[0]` is 18507 and `y[0]` (this module's `.x` field) is 18507.0 -- channel 0
of the returned array is the tag, not data. `buffsize` is an **optional
positional** in the IDL; both callers in the vendored tree omit it:
`soda2_processbuffer.pro:285` `hk=spec_read_hk(1,(*pmisc).hkpointers[i])` (no
buffsize, no version -- the original 2D-S path) and `spec_process_hk.pro:65`
`spec_read_hk(lun,hkindex.hkp[i],hkindex.buffsize,version=version)`. An
undefined `buffsize` reaches `spec_readint.pro:9` and defaults there to 4114
-- this port makes that default explicit as `buffsize=4114`.

Provenance: ``SODA2/abansemer-soda2-afcea15/spec_read_hk.pro`` (whole file),
Aaron Bansemer, NCAR, 5/2011. Copyright (C) 2016 UCAR, 3-clause BSD.
Validated against GDL by ``tests/test_soda2_spec_read_hk.py``; bank at
``gdl_oracle/run_soda2_spec_read_hk_bank.py``, 12 cases (11 on a new
synthetic HK fixture, one -- ``s2_real`` -- on the pre-existing tracked
``tests/data/s2_spec_raw_fixture``), all matching. A third side, a
``struct``-only recomputation that derives ``tas`` from the IEEE bit fields
directly rather than by the source's own `dec2bin` loop, is asserted against
both the golden and the port in the same test module.

**Line-by-line** (IDL 0-based indexing; every index below is exactly what
the source writes):

- ``:8`` -- ``version`` defaults to **1** ("2DS/HVPS3") -- the *opposite*
  numbering from `spec_read_frame`, where 0 is the 2DS. This module ports
  both versions: ``version=1``, the original 2D-S call shape, here, and
  ``version=2`` in ``_spec_read_hk_v2`` (``:43-65``, below), which
  ``spec_process_hk.pro:65`` reaches through its ``version=version``.
- ``:10-11`` -- ``hklength=53`` for version 1, ``83`` for version 2; any
  other version leaves ``hklength`` undefined and the IDL's own next line
  would die. This port raises ``ValueError`` there instead.
- ``:13-14`` -- ``point_lun``; ``x = spec_readint(lun, hklength,
  buffsize=buffsize, /signed)`` -- **signed** INT16, unlike `spec_read_frame`'s
  unsigned reads. ``x`` is INT[53].
- ``:16`` -- ``f1 = 0.00244140625``, a FLOAT literal that is exactly
  5*2**-11, hence exact in float32; every coefficient built from it
  (``f1*2``, ``f1*10``, ``f1/2``) is therefore also exact.
- ``:19-30`` -- ``c0 = fltarr(49)``; ``c0[9:21]=1.6``; ``c0[24]=-3.846``;
  ``c1 = fltarr(49)+1.0``; ``c1[1:6]=f1``; ``c1[7:8]=f1*2``;
  ``c1[9:21]=f1*10``; ``c1[22:23]=f1*2``; ``c1[24]=0.018356``;
  ``c1[25:32]=f1``; ``c1[36:37]=f1/2``. IDL's ``a:b`` slice is **inclusive**;
  the Python slices below add one to the upper bound accordingly. ``1.6``,
  ``-3.846`` and ``0.018356`` are the three coefficients that are NOT exact
  in float32 (measured bit patterns ``3FCCCCCD``, ``C07624DD``, ``3C965F52``).
- ``:32`` -- ``y = x[0:48]*c1 + c0`` -- INT times FLOAT promotes to FLOAT,
  then a separate FLOAT addition: **two independent single-precision
  roundings, no fused multiply-add**. Reproduced here as two explicit
  float32 NumPy operations, never combined into one expression.
- ``:35`` -- ``exponent = ishft(x[49] and '3f80'x, -7) + 1`` -- bits 13..7 of
  the high TAS word give the low 7 bits of an IEEE exponent byte; bit 15
  (sign) and bit 14 (the exponent's own MSB) are excluded by the mask, so
  they are silently ignored ("Only works for positive exponents", the
  source's own comment).
- ``:36`` -- ``mantissabits = [dec2bin8(x[49] and '7f'x), dec2bin16(x[50] and
  'ffff'x)]`` -- 8 + 16 = 24 bits, **MSB first** (``dec2bin8.pro:9``,
  ``dec2bin16.pro:9``); element 0 is always 0 (a 7-bit value packed into 8
  bits). ``'ffff'x`` is LONG 65535 under GDL, so a negative signed
  ``x[50]`` is masked to its unsigned low word before ``dec2bin16`` examines
  bits 0-15 -- the result is the same as treating it as unsigned outright.
- ``:37`` -- ``mantissa = 1 + total(mantissabits/2^findgen(24))`` -- every
  term is ``bit_i * 2**-i`` for ``i = 1..23`` (bit 0 is always the padding
  zero), each exactly representable in float32, so the sum is the exact
  IEEE significand ``1.f`` regardless of summation order.
- ``:38`` -- ``tas = mantissa * 2^exponent`` -- IDL's integer ``^`` on two
  INT operands returns an **INT, wrapping at 16 bits**: measured under GDL,
  ``2^15 = -32768``, ``2^16 = 0``, ``2^128 = 0``, ``2^7 = 128``. This is a
  16-bit-integer power of two, not a floating-point one -- reproduced here
  with explicit modular arithmetic rather than ``2.0 ** exponent`` (S4-h;
  see ``_wrapped_int_pow2``).
- ``:40`` -- ``time = ishft(ulong(x[51]),16) + x[52]`` -- the high word is
  correctly widened to ULONG and shifted, but **the low word ``x[52]`` is
  added as the signed INT `:14` already read it**, with no re-masking:
  ULONG + INT promotes to ULONG (measured under GDL), so a low word
  ``>= 0x8000`` is added as a *negative* number, making ``time`` 65536 too
  small; with a zero high word this wraps to just under 2**32 (S4-g).
- ``:43-65`` -- version 2 (3VCPI/Hawkeye/HVPS-4, 83-word HK): **ported**
  in ``_spec_read_hk_v2``, bit-exact against GDL on four
  synthetic records (``test_soda2_spec_read_hk_v2.py``); the caller is
  ``spec_process_hk.pro:65`` with ``buffsize=0`` from ``spec_index_hk``.
- ``:67`` -- returns ``{time, tas, x:y, raw:x}``; the struct's own field
  named ``x`` is this port's ``x`` field (the float32[49] `y` array, per the
  source's variable name inside the block) and ``raw`` is the signed
  int16[53] read at `:14`. Measured tnames: ``ULONG, FLOAT, FLOAT[49],
  INT[53]``.

**Who consumes what** (read, not measured): ``soda2_processbuffer.pro:288``
overrides ``hk.tas`` with ``probetas`` when ``subformat ne 0``; for the
original 2D-S (``subformat=0``) ``hk.tas`` reaches ``clocktas[c]`` (`:305`)
and the stretch factor (`:307-308`, gated ``hk.tas gt 0``).
``spec_process_hk.pro:66-68`` sums ``h.x``, ``h.raw``, ``h.tas``. **No
caller in the vendored tree reads the ``time`` tag** -- confirmed with
``grep -rn "\\.time" soda2_processbuffer.pro spec_process_hk.pro`` (no
``hk.time``/``h.time`` hit; the many ``x.time``/``buffer.time`` hits belong
to unrelated structs).

**Findings**: **S4-g** (the signed
low time word makes `time` 65536 low whenever it is >= 0x8000, unconsumed
today), **S4-h** (the 16-bit-integer `2^exponent` turns a zero or sub-2 m/s
TAS into 2.0 or 0.0, and a >=2**15 TAS negative -- reachable through
`hk.tas` for the 2D-S).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

import numpy as np

from .spec_readint import spec_readint

__all__ = ["SpecHK", "spec_read_hk"]

#: `:16` -- exactly 5 * 2**-11, hence exact in float32.
_F1 = np.float32(0.00244140625)

#: `:19-30`, built once at import time. IDL slices are inclusive; the Python
#: slices below add one to every upper bound. `1.6`, `-3.846` and `0.018356`
#: are the three coefficients NOT exactly representable in float32.
_C0 = np.zeros(49, dtype=np.float32)
_C0[9:22] = np.float32(1.6)
_C0[24] = np.float32(-3.846)

_C1 = np.ones(49, dtype=np.float32)
_C1[1:7] = _F1
_C1[7:9] = _F1 * np.float32(2)
_C1[9:22] = _F1 * np.float32(10)
_C1[22:24] = _F1 * np.float32(2)
_C1[24] = np.float32(0.018356)
_C1[25:33] = _F1
_C1[36:38] = _F1 / np.float32(2)


def _wrapped_int_pow2(exponent: int) -> int:
    """``2^exponent`` (IDL's integer ``^``) as GDL evaluates it: a 16-bit
    **signed INT**, wrapping modulo 65536 (`:38`, S4-h). Measured under GDL:
    ``2^7 = 128``, ``2^15 = -32768``, ``2^16 = 0``, ``2^128 = 0``."""
    p = pow(2, exponent) % 65536
    if p >= 32768:
        p -= 65536
    return p


@dataclass
class SpecHK:
    """``hk = spec_read_hk(...)``'s return struct (`:67`).

    Source: ``spec_read_hk.pro:67`` (SODA-2)."""

    #: `:40` -- ULONG. Carries S4-g (the signed low word) and the modulo-2**32
    #: wrap that follows from it.
    time: int
    #: `:38` -- FLOAT, built from an exact mantissa and a 16-bit-wrapped
    #: integer power of two (S4-h).
    tas: np.float32
    #: `:32` -- float32[49], the struct's own ``x`` tag (named ``y`` in the
    #: source's local variables). Channel 0 is the `'HK'` marker word itself
    #: (18507.0), not data.
    x: np.ndarray
    #: `:14` -- int16[53], the raw signed housekeeping words as read.
    raw: np.ndarray


def spec_read_hk(
    f: BinaryIO,
    bpoint: int,
    buffsize: int = 4114,
    version: int = 1,
) -> SpecHK:
    """``hk = spec_read_hk(lun, bpoint, buffsize=buffsize, version=version)``.

    ``f`` is an open binary SPEC raw file; ``bpoint`` the byte offset of the
    housekeeping record's `'HK'` marker word (IDL's ``point_lun,lun,bpoint``,
    `:13`). ``buffsize=4114`` reproduces the IDL's *effective* default: the
    source declares ``buffsize`` as an optional positional with no explicit
    default, and an omitted argument reaches ``spec_readint.pro:9``, which
    defaults it to 4114 -- both vendored callers omit it.

    ``version=1`` (2DS/HVPS3, 53 words) and ``version=2`` (3VCPI/Hawkeye,
    83 words, `:43-65`, ``_spec_read_hk_v2``) are both ported; any other
    value raises ``ValueError``, matching the IDL's own fate at `:14`
    (``hklength`` undefined). The refusal does not advance the file
    position -- exactly as the IDL would not have read anything either.
    """
    if version == 2:
        return _spec_read_hk_v2(f, bpoint, buffsize)
    if version != 1:
        raise ValueError(
            f"spec_read_hk: version={version!r} is not 1 or 2 -- the IDL "
            "leaves `hklength` undefined here and the next line dies "
            "(spec_read_hk.pro:10-14)")

    f.seek(bpoint)

    # `:13-14` -- 53 signed words: marker, 48 channels, TAS hi/lo, time hi/lo.
    x = spec_readint(f, 53, buffsize=buffsize, signed=True)

    # `:32` -- INT * FLOAT -> FLOAT, then + FLOAT: two separate roundings.
    y = x[0:49].astype(np.float32) * _C1 + _C0

    hi = int(x[49])
    lo = int(x[50])

    # `:35` -- bits 13..7 of the high word are the low 7 bits of an IEEE
    # exponent byte; the sign bit (15) and exponent MSB (14) are excluded.
    exponent = ((hi & 0x3F80) >> 7) + 1

    # `:36` -- 8 + 16 mantissa bits, MSB first. `hi & 0x7F` is the 7-bit low
    # byte of the high word (bit 0 of the 8-bit result is always 0); `lo &
    # 0xFFFF` masks a negative signed low word to its unsigned bit pattern,
    # matching IDL's `'ffff'x` LONG mask under GDL.
    hi_bits = [(hi & 0x7F) >> (7 - i) & 1 for i in range(8)]
    lo_bits = [((lo & 0xFFFF) >> (15 - i)) & 1 for i in range(16)]
    bits = hi_bits + lo_bits

    # `:37` -- exact: every term is a dyadic fraction, so order cannot matter.
    mantissa = np.float32(1.0 + sum(b / 2.0 ** i for i, b in enumerate(bits)))

    # `:38` -- S4-h: a 16-bit-wrapped integer power of two, not `2.0 **
    # exponent`.
    p = _wrapped_int_pow2(exponent)
    tas = np.float32(mantissa) * np.float32(p)

    # `:40` -- S4-g: the low word is added signed, unmasked; ULONG + INT
    # promotes to ULONG under GDL, so the whole sum is taken modulo 2**32.
    # NOTE: the time halves are x[51]/x[52], distinct from the TAS halves
    # x[49]/x[50] (`hi`/`lo` above) -- do not conflate the two.
    time_hi = int(x[51])
    time = (((time_hi & 0xFFFF) << 16) + int(x[52])) & 0xFFFFFFFF

    return SpecHK(time=time, tas=tas, x=y, raw=x)


def _decode_tas(hi: int, lo: int) -> np.float32:
    """`:35-38` / `:59-62`, identical in both versions (S4-h)."""
    exponent = ((hi & 0x3F80) >> 7) + 1
    hi_bits = [(hi & 0x7F) >> (7 - i) & 1 for i in range(8)]
    lo_bits = [((lo & 0xFFFF) >> (15 - i)) & 1 for i in range(16)]
    mantissa = np.float32(1.0 + sum(b / 2.0 ** i for i, b in enumerate(hi_bits + lo_bits)))
    return np.float32(mantissa) * np.float32(_wrapped_int_pow2(exponent))


#: `:50`'s three FLOAT literals, widened to DOUBLE by `alog(rt)` (DOUBLE).
_T_A = float(np.float32(1.111e-3))
_T_B = float(np.float32(237e-6))
_T_C = float(np.float32(75.8e-9))


def _spec_read_hk_v2(f: BinaryIO, bpoint: int, buffsize: int) -> SpecHK:
    """`:43-65` -- version 2 (3VCPI/Hawkeye/HVPS-4), 83 words.

    - `:46` ``y = float(x)``, then `:49-56` overwrite three bands.
    - `:49` ``rt = 6.5536e9*(1-x/65536d)/(5*x)`` on ``x[2:28]``: ``5*x`` is
      **INT times INT, wrapping at 16 bits** before the DOUBLE division, so
      any raw word above 6553 (or below -6553) gives a wrong-signed or wrong
      denominator; a zero word divides by zero (``rt = +Inf``, temperature
      -273.15); a negative ``rt`` gives NaN.
    - `:50` DOUBLE Steinhart-Hart with FLOAT-literal coefficients, stored to
      FLOAT. `:53` pressure and `:56` volts: FLOAT, two roundings.
    - `:59-62` TAS from ``x[75:76]``, the v1 decode (S4-h included).
    - `:64` ``time = ishft(ulong(x[72]),32) + ishft(ulong(x[73]),16) + x[74]``
      -- a 32-bit shift of a 32-bit ULONG, then the signed low word added
      unmasked as in v1 (S4-g). What GDL makes of the 32-bit shift is the
      golden's; the port reproduces the measured value (see ``_ishft32``).
    """
    f.seek(bpoint)
    x = spec_readint(f, 83, buffsize=buffsize, signed=True)
    y = x.astype(np.float32)  # `:46`

    xt = x[2:29].astype(np.int64)
    five_x = ((5 * xt + 32768) % 65536) - 32768  # INT*INT wraps
    with np.errstate(divide="ignore", invalid="ignore"):
        rt = float(np.float32(6.5536e9)) * (1 - xt / 65536.0) / five_x.astype(np.float64)
        lr = np.log(rt)
        t = np.float64(np.float32(-273.15)) + (_T_A + _T_B * lr + _T_C * lr ** 3) ** (-1)
    y[2:29] = t.astype(np.float32)

    y[29] = np.float32(np.float32(x[29]) * np.float32(5.72e-4)) - np.float32(3.75)  # `:53`
    y[34:54] = x[34:54].astype(np.float32) * _F1  # `:56`

    tas = _decode_tas(int(x[75]), int(x[76]))

    time = (_ishft32(int(x[72]) & 0xFFFFFFFF) + (((int(x[73]) & 0xFFFFFFFF) << 16)
            & 0xFFFFFFFF) + int(x[74])) & 0xFFFFFFFF
    return SpecHK(time=time, tas=tas, x=y, raw=x)


def _ishft32(v: int) -> int:
    """``ishft(ulong(v), 32)`` as GDL evaluates it (`:64`): **unshifted**.
    Measured (bank ``read_r1``, ``x[72]=1``; ``read_r3``, ``x[72]=2``): the
    word is added as is, the x86 behaviour of a 32-bit shift whose count is
    taken modulo 32. So the high time word lands on the low bits instead of
    bits 32-47, which a ULONG cannot hold anyway. GDL-measured only; what
    IDL returns for a shift >= the type's width is not confirmed here."""
    return v & 0xFFFFFFFF
