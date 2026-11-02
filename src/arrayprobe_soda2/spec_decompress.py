# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``spec_decompress.pro`` -- one buffer's compressed words to a bit image.

66 lines of IDL that turn a run of 16-bit compressed SPEC words into a
``bytarr(128, numslices)`` shadow/clear bitimage. This is the first of the two
SPEC buffer-decode leaves (the other is `spec_readint`); the
748-line `soda2_processbuffer.pro` that calls this is out of scope.

Provenance: ``SODA2/abansemer-soda2-afcea15/spec_decompress.pro`` (whole
file), Aaron Bansemer, NCAR, 10/2011. Copyright (C) 2016 UCAR, 3-clause BSD.
Validated against GDL by ``tests/test_soda2_spec_decompress.py``; bank at
``gdl_oracle/run_soda2_spec_decompress_bank.py``, 16 cases, all matching.

**Each compressed word packs four bit fields**, tested with masks against a
UINT value (`spec_readint` is its producer):

======  =========  =========================================================
bits    field      meaning
======  =========  =========================================================
15      timeslice  1 = timing/overflow word; the decode loop skips it whole
14      startslice 1 = this word starts a new output slice, resets ``idiode``
7-13    numshaded  run length of shaded (1) diodes
0-6     numclear   run length of clear (0) diodes, or the new diode offset
======  =========  =========================================================

Two IDL constants are magic **values**, checked by equality against the whole
word rather than by field, because both happen to also be well-formed
ordinary words under the bit layout above:

- ``'7fff'x`` (32767) -- a full clear line. Its own bit-14 is set, so the
  ordinary startslice branch runs FIRST (``islice`` increments, ``idiode``
  is set to its numclear field, 127) and *then* the clear-line special case
  overwrites the whole new slice to 0 and resets ``idiode`` to 0. Under
  ``version=1`` (HVPS4/3VCPI only; never the original 2D-S, which is version 0)
  it additionally means "8 words of uncompressed diode data follow" --
  see below.
- ``'4000'x`` (16384) -- a full solid line, bit-14 alone. It also carries
  startslice=1 (a new slice), numshaded=0, so it falls into the *else*
  branch of the ``numshaded[i] gt 0`` test and is caught there by value.

**The array-layout convention.** IDL's ``bitarr(128, numslices)`` is
diode-major; this port returns **``(numslices, 128)``**, the package's
standing transpose (the sizing core's design record, item 1) -- callers index
``bitimage[slice, diode]``.

**Findings:**

- **S4-a** (`:14`, `:21`) -- ``numslices = total(startslice) + 3`` allocates
  three slices beyond the count of startslice-bearing words, and ``islice``
  is incremented *before* any word's data is ever written to it, so **slice
  0 of the returned array is always blank** -- confirmed against every case
  in the bank, none of which ever writes to row 0.
- **S4-c** (`:46`) -- the overflow guard (``idiode+numshaded-1 lt 128``)
  drops an over-length run **without rolling `idiode` back**: the next word's
  run starts from wherever the startslice branch left `idiode`, not from
  where the dropped run would have ended. Measured with
  ``overflow_word_dropped``: a run that would end at diode 129 is dropped,
  and the following 3-diode run lands at ``[120, 123)``, not ``[130, 133)``.

**U1, resolved by the bank, not assumed.** `:42` (``i+=8``, version=1 only)
reassigns the FOR loop's own counter inside its body. IDL/GDL FOR loops
re-read the loop variable each pass, so the reassignment **is honoured**:
the next iteration resumes at ``i+8`` **plus** the loop's own automatic
``+1``, i.e. at ``i+9`` from where the branch started, not merely
``i+1``. Measured with ``v1_clear_then_8_words``: the golden's slice content
is bit-for-bit what you get by (a) treating indices ``[i+1, i+8]`` as one
consumed block and (b) resuming at ``i+9`` -- and is *not* what you get by
re-visiting those same indices as ordinary compressed words. This port uses
an explicit ``while`` loop over a mutable index so the ``i += 8`` can be
written exactly as the source writes it, rather than a Python ``for`` loop
over a fixed range, which cannot express a body reassigning its own counter.

**The version=1 uncompressed block, decoded exactly.** ``dec2bin16`` maps
row ``r`` of its output to bit ``15-r`` of the input (MSB first); ``reverse``
with no dimension argument reverses along IDL's first (fastest-varying)
dimension, undoing that -- row ``r`` of the reversed array is bit ``r``
(LSB first). ``1 - reverse(dec2bin16(...))`` then bit-inverts. Assigning an
IDL ``(16, 8)`` array into a 128-element target reads it column-major (all
16 rows of column 0, then column 1, ...), so word ``j`` of the 8-word block
lands at diodes ``[16*j, 16*j+16)``, LSB first. Net: ``diode[16*j+r] =
1 - bit_r(word_j)`` for ``j`` in 0..7, ``r`` in 0..15. Reproduced by
``_decode_uncompressed_block`` below rather than through NumPy bit-twiddling
functions, so the mapping stays legible against the IDL line it replaces.
"""
from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["spec_decompress"]

_TIMESLICE_MASK = 0x8000
_STARTSLICE_MASK = 0x4000
_NUMSHADED_MASK = 0x3F80
_NUMCLEAR_MASK = 0x007F
_CLEAR_LINE = 0x7FFF
_SOLID_LINE = 0x4000
_NDIODES = 128


def _decode_uncompressed_block(words: np.ndarray) -> np.ndarray:
    """``1-reverse(dec2bin16(words))``, flattened column-major (`:41`).

    ``words`` is exactly 8 elements. Returns 128 uint8 values, LSB of
    ``words[0]`` first.
    """
    out = np.empty(_NDIODES, dtype=np.uint8)
    for j in range(8):
        word = int(words[j])
        for r in range(16):
            out[16 * j + r] = 1 - ((word >> r) & 1)
    return out


def spec_decompress(cimage: ArrayLike, overload: int, version: int = 0) -> np.ndarray:
    """``bi = spec_decompress(cimage, overload, version=version)``.

    Source: ``spec_decompress.pro`` (SODA-2).

    ``cimage`` is a sequence of 16-bit unsigned compressed words (as produced
    by `spec_readint`). ``overload`` is truthy/1 when the frame's overload
    flag is set, which drops the last two words from the decode (`:23`).
    ``version`` selects the HVPS4/3VCPI 8-word-uncompressed-block convention
    (1) versus the original 2D-S/HVPS3 convention (0).

    Returns a ``(numslices, 128)`` ``uint8`` array, row-major over slices --
    the transpose of IDL's ``bitarr(128, numslices)``. Row 0 is always blank
    (SODA-2 register entry S4-a); no clamping, no bounds "fix" beyond what `:46` itself
    already does (SODA-2 register entry S4-c is preserved, not corrected).
    """
    cimage_u16 = np.asarray(cimage, dtype=np.uint16)
    n = int(cimage_u16.size)
    # Widen before masking: IDL's UINT `and` an INT hex literal promotes to
    # LONG, and the values here (0-65535) are unaffected by that promotion --
    # int64 keeps every intermediate exact with no sign ambiguity (U3).
    words = cimage_u16.astype(np.int64)

    timeslice = (words & _TIMESLICE_MASK) >> 15
    startslice = (words & _STARTSLICE_MASK) >> 14
    numshaded = (words & _NUMSHADED_MASK) >> 7
    numclear = words & _NUMCLEAR_MASK

    # `:14` -- total() over the WHOLE array, regardless of which words the
    # loop below actually visits (overload's skip, or a version=1 block
    # consuming several indices at once, does not change this count).
    numslices = int(startslice.sum()) + 3
    bitimage = np.zeros((numslices, _NDIODES), dtype=np.uint8)

    islice = 0
    idiode = 0
    skip = int(overload) * 2
    bound = n - 1 - skip  # IDL `FOR i=0,bound DO` -- inclusive, no run if bound<0

    i = 0
    while i <= bound:
        if not timeslice[i]:
            if startslice[i]:
                islice += 1
                idiode = int(numclear[i])
            else:
                idiode += int(numclear[i])

            shaded = int(numshaded[i])
            if shaded > 0:
                if int(words[i]) == _CLEAR_LINE:
                    bitimage[islice, :] = 0
                    idiode = 0
                    if version == 1:
                        istart = i + 1
                        istop = i + 8
                        if istop < n:
                            block = words[istart:istop + 1]
                            bitimage[islice, :] = _decode_uncompressed_block(block)
                        i += 8  # honoured by GDL's FOR -- see module docstring, U1
                        idiode = 0
                else:
                    if idiode + shaded - 1 < _NDIODES:
                        goodbit = True
                        # `:49-53` -- HVPS3/MC3E 32-diode artifact rule.
                        if shaded == 32 and (idiode % 32) == 0:
                            if islice == 0:
                                goodbit = False
                            if islice > 0:
                                prior = bitimage[islice - 1, idiode:idiode + shaded]
                                if int(prior.sum()) < 4:
                                    goodbit = False
                        if goodbit:
                            bitimage[islice, idiode:idiode + shaded] = 1
                        # `idiode` advances here whenever the overflow check
                        # above passed -- even on an MC3E goodbit=False drop.
                        # It does NOT advance on the overflow drop itself
                        # (finding S4-c): that case never reaches this line,
                        # so `idiode` is left wherever the startslice/else
                        # branch put it, and the *next* word's run starts
                        # there rather than past the dropped run's length.
                        idiode += shaded
            else:
                if int(words[i]) == _SOLID_LINE:
                    bitimage[islice, :] = 1
        i += 1

    return bitimage
