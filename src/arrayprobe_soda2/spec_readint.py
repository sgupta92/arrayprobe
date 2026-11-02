# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``spec_readint.pro`` -- read ``length`` SPEC integers, skipping buffer
boundaries transparently.

49 lines of IDL. A SPEC raw file is a sequence of fixed-size buffers
(default 4114 bytes: an 8-``int16`` header, 4096 bytes of image data, a
2-byte footer -- ``headersize=9`` below is this footer-plus-header pair, in
**words**, not bytes). This routine's whole job is letting a caller ask for
``length`` consecutive *data* integers without caring whether that span
crosses one of those 18-byte dead zones.

Provenance: ``SODA2/abansemer-soda2-afcea15/spec_readint.pro`` (whole file),
Aaron Bansemer, NCAR, 5/2011. Copyright (C) 2016 UCAR, 3-clause BSD.
Validated against GDL by ``tests/test_soda2_spec_readint.py``; bank at
``gdl_oracle/run_soda2_spec_readint_bank.py``. The test also recomputes the
non-zero cases independently from the tracked fixture's raw bytes with
``struct`` -- a third, differently-coded side, never a fixture compared with
itself.

**How many buffer boundaries the requested span crosses decides everything**
(`:19-23`): ``crossings = (pointer+length*2)//buffsize - pointer//buffsize``.

- **0** -- an ordinary contiguous read, no boundary in the way.
- **1** -- read ``length+9`` words starting at ``pointer`` (spanning straight
  through the dead zone), then splice it out: ``div`` is how many *live*
  words remain before the boundary. `:34`'s two branches are the same
  splice, just written differently when ``div<=0`` (the boundary is at or
  before ``pointer`` itself, so nothing needs keeping from the first side).
- **2 or more** -- **not implemented upstream.** `:38` prints a message and
  returns ``length + crossings*9`` **zeros** -- not ``length`` zeros, and not
  an error. The file position still advances by the full amount `readu`
  would have consumed (the IDL discards the values with ``x[*]=0`` only
  *after* reading them), so a caller chaining reads stays in sync with the
  file even though this particular read came back meaningless. Finding
  **S4-b**. This port raises no exception either, and reproduces both the
  oversized return and the file-pointer advance; the ``print`` becomes a
  ``warnings.warn`` (a documented divergence -- IDL's original wrote to
  stdout, this cannot, and reproducing a print via a print would be invisible
  to any caller that wanted to know).

**The post-read jump** (`:46-47`): after the read, if the pointer lands
*exactly* on a footer's first byte (``pointer mod buffsize == buffsize-2``),
the file is advanced a further 18 bytes, over the footer and the next
buffer's header, so the *next* call starts already inside live data. This
is why the plan's ``to_footer_exactly`` case (a length chosen so the read
ends precisely there) reports ``AFTER=4130`` rather than ``4112``.
"""
from __future__ import annotations

import warnings
from typing import BinaryIO

import numpy as np

__all__ = ["spec_readint"]

#: Words spanning one buffer boundary: a 1-word (2-byte) footer plus an
#: 8-word (16-byte) header, i.e. 18 bytes -- `:17`, `:47`.
_HEADERSIZE = 9


def spec_readint(
    f: BinaryIO,
    length: int,
    buffsize: int = 4114,
    signed: bool = False,
) -> np.ndarray:
    """``x = spec_readint(lun, length, buffsize=buffsize, signed=signed)``.

    Source: ``spec_readint.pro`` (SODA-2).

    ``f`` is an open binary file positioned at the read start (IDL's ``lun``
    plus ``point_lun,-lun,pointer``, here ``f.tell()``/``f.seek()``).
    ``buffsize=0`` bypasses the boundary logic entirely (`:11-16`, the
    2DSCPIHK-file case, which has no buffer structure to skip).

    Returns a 1-D array, dtype ``int16`` if ``signed`` else ``uint16``. On a
    2+-crossing span the array is ``length + crossings*9`` **zeros** --
    longer than ``length`` -- reproducing SODA-2 register entry S4-b rather than raising.
    """
    dtype = np.int16 if signed else np.uint16
    itemsize = 2

    if buffsize == 0:
        # `:11-16` -- 2DSCPIHK files have no buffer boundaries to skip.
        raw = f.read(length * itemsize)
        return np.frombuffer(raw, dtype=dtype).copy()

    pointer = f.tell()
    m1 = pointer // buffsize
    m2 = (pointer + length * itemsize) // buffsize
    crossings = m2 - m1

    if crossings == 0:
        raw = f.read(length * itemsize)
        x = np.frombuffer(raw, dtype=dtype).copy()
    elif crossings == 1:
        total = length + _HEADERSIZE
        raw = f.read(total * itemsize)
        x2 = np.frombuffer(raw, dtype=dtype)
        # `:33` -- live words remaining before the boundary, less one for
        # the footer itself (integer division, matches IDL's `/` on
        # non-negative operands).
        div = (buffsize - (pointer % buffsize)) // 2 - 1
        if div > 0:
            x = np.concatenate([x2[0:div], x2[div + _HEADERSIZE:length + _HEADERSIZE]])
        else:
            x = x2[div + _HEADERSIZE:length + _HEADERSIZE].copy()
    else:
        # `:37-42`, finding S4-b: the file position still advances by the
        # full over-length read; only the returned values are discarded.
        warnings.warn(
            f"spec_readint: frame spans {crossings} buffers, unsupported so far",
            stacklevel=2,
        )
        total = length + crossings * _HEADERSIZE
        f.read(total * itemsize)  # advance the file pointer; bytes discarded
        x = np.zeros(total, dtype=dtype)

    # `:46-47` -- landed exactly on a footer's first byte: skip the footer
    # and the next header so the caller starts already inside live data.
    after = f.tell()
    if (after % buffsize) == (buffsize - 2):
        f.seek(after + _HEADERSIZE * itemsize)

    return x
