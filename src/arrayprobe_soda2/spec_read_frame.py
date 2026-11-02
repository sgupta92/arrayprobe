# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``spec_read_frame.pro`` -- read and assemble one HVPS3/2DS frame, composing
``spec_readint`` and `spec_decompress`.

98 lines of IDL. This is the routine `soda2_processbuffer.pro` (out of scope,
748 lines) calls once per particle pointer: given a byte offset into an open
SPEC raw file and which array (`'H'`/`'V'`) to read, it decodes the frame's
own tiny 3-word header, reads the rest of the frame with `spec_readint`
(already ported), assembles a 32-bit time word out of two 16-bit halves,
recurses up to two levels deep to stitch together a particle whose image was
split across "missing time word" fragments, and calls `spec_decompress`
(already ported) on the concatenated raw compressed words.

Provenance: ``SODA2/abansemer-soda2-afcea15/spec_read_frame.pro`` (whole
file), Aaron Bansemer, NCAR, 5/2011. Copyright (C) 2016 UCAR, 3-clause BSD.
Validated against GDL by ``tests/test_soda2_spec_read_frame.py``; bank at
``gdl_oracle/run_soda2_spec_read_frame_bank.py``, 17 cases on a new
synthetic fixture, all matching. A third side -- a `struct`-only
recomputation of the whole routine's arithmetic, sharing no code with either
this module or NumPy -- is asserted against both the golden and the port in
the same test module (never a fixture compared with itself).

**Line-by-line** (IDL 0-based array indexing throughout; every index below
is exactly what the source writes, no MATLAB-style off-by-one to convert):

- `:8-9` -- ``version`` defaults to 0 ("original 2DS/HVPS"; a 2D-S with
  ``subformat=0`` is always this value -- ``soda2_probespecs.pro``'s ``subformat=0``);
  ``recursioncount`` defaults to 0, the recursion-depth counter below.
- `:11` -- ``point_lun, lun, fpoint`` -- seek to the frame's start.
- `:13-15` -- ``x = spec_readint(lun, 3)`` reads the frame's own 3-word
  header (unsigned, default ``buffsize``); ``nh = x[1] and 0xFFF``,
  ``nv = x[2] and 0xFFF`` are the H/V block lengths, each a 12-bit field.
- `:18-23` -- the top four bits of each of ``x[1]``/``x[2]`` are flags:
  bit 12 ``missingtw*`` ("missing time words"), bit 14 ``fifo*`` ("empty
  FIFO" -- decoded and never used downstream, S4-f), bit 15 ``overload*``
  ("last 2 words are overload times"). IDL's ``and`` against a hex INT
  literal like ``'8000'x`` (-32768 as a signed INT) promotes a UINT operand
  to LONG, but every value here is a plain 16-bit field extracted by mask
  and shift, so the promotion changes no bit this port needs to reproduce.
- `:26-28` -- ``spec_readint`` reads ``2+nh+nv`` words, the rest of the
  frame using the **undecremented** ``nh``/``nv`` (the `version==1`
  decrements at `:39`/`:50` happen only inside the H/V blocks below, after
  this read has already used the original lengths) -- ``particlecount =
  buff[0]``, ``numslices = buff[1]`` (**read and never used again** --
  `spec_decompress` computes its own slice count from the startslice bits,
  S4-f).
- `:29-35` -- defaults for a frame where neither block ends up running:
  ``image`` a single blank slice, ``time``/``timetrunc`` 0, ``error=1``,
  ``imageraw`` the IDL scalar ``0b`` (never an array), ``overload=0``,
  ``gotframe=0``.
- `:38-46` -- **H block**, gated on ``nh > 3 and id == 'H'``. `version==1`
  decrements ``nh`` by one first (`:39`) -- "for some reason nh and nv are
  different for these instruments, dummy byte?", the source's own comment,
  reproduced in the bank's `v1_h` case, which carries one literal unused
  dummy word for exactly this reason. `:40`'s ``ELSE imageraw=0s`` is
  unreachable here: it guards ``nh < 3``, but the block is only entered when
  the *original* ``nh > 3``, and a `version==1` decrement of a value that
  was already `> 3` leaves it `>= 3`. ``imageraw = buff[2:nh-1]`` inclusive
  (`nh-2` elements); ``counter = buff[nh:nh+1]`` (2 elements, ``ulong``d).
- `:49-57` -- **V block**, the mirror image, gated on ``nv > 3 and id ==
  'V'``. Its slice is ``buff[nh+2:nh+nv-1]`` / ``buff[nh+nv:nh+nv+1]`` --
  note the ``nh`` offset is the **undecremented** value even when the H
  block never ran (``nh`` stays whatever `:14` set it to, 0 in every V-only
  fixture case here, since this port's fixture convention is `nh =
  len(hwords)`).
- `:63-71` -- assembled only if `gotframe` (either block ran). Version 0:
  ``time = counter[0]<<16 + counter[1]``, ``timetrunc = counter[1]``.
  Version 1: the halves are **reversed** -- ``time = counter[1]<<16 +
  counter[0]``, ``timetrunc = counter[0]`` -- confirmed by the bank's
  `v1_h` case (`TIME=2031646 = 31<<16+30`, matching Hwords' counter
  `[30, 31]` read in reversed order) rather than assumed from the comment
  alone.
- `:74-86` -- **the recursion**, gated on ``missingtw > 0 and
  recursioncount < 2``. ``REPEAT ... UNTIL q.error eq 0`` calls this same
  routine again at the *current* file position (after this frame's own
  ``spec_readint`` calls have already advanced the pointer), skipping over
  any intervening frame that itself comes back ``error=1`` (a "timeword-only"
  frame the source's own comment names, or -- as the bank's
  `mtw_then_v_then_h`/`v_in_chain` pair demonstrates -- simply a frame for
  the *other* array, which errors here because its ``id`` does not match).
  On success, ``imageraw`` is concatenated with the fragment's, and
  ``time``/``timetrunc``/``overload`` are all **replaced** by the
  fragment's own values (`:82-85`) -- ``particlecount`` alone survives
  from the first fragment, because it is set once at `:27` and never
  touched again. The recursion depth cap silently truncates a particle
  spanning four or more fragments to its first three, and the values
  returned then come from the *third* fragment even though that fragment's
  own header still flags ``missingtw=1`` (finding S4-d, bank case
  `chain_m1`: three ``missingtw``-flagged frames followed by a complete
  one that is never read).
- `:89` -- the image is ``spec_decompress`` of the raw words with ``overload`` and ``version``,
  the existing port.
- `:92-93` -- ``error = 0``, then ``IF (overload eq 0) and (nn eq 2) THEN
  error = 1``. **Unreachable**, and kept verbatim: ``nn`` is assigned only
  inside the H/V blocks (`:44`, `:55`), to ``nh``/``nv`` themselves -- both
  are always `>= 3` wherever `nn` is set (the block's own gate is `> 3`,
  and a `version==1` decrement of a value `> 3` cannot reach 2), so this
  comparison against 2 can never be true (finding S4-e).
- `:96-97` -- the returned fields; ``overload`` is a GDL/IDL ``LONG`` when a
  frame was found and the plain ``INT`` `:34` initialiser otherwise (the
  bank's ``TN`` field distinguishes the two; this port always returns a
  Python ``int``, so the distinction is a fact about IDL's own type system,
  not something this port's callers can observe).

**Findings**: **S4-d** (the recursion
cap silently truncates and reports the truncated fragment's own time),
**S4-e** (`:93`'s error check is dead code), **S4-f** (`fifoh`/`fifov` and
the frame's own ``numslices`` are read and discarded).

**The GDL-oracle shim.** GDL 1.1.2's ``ISHFT`` returns a 1-element array for
a scalar operand where real IDL returns a scalar (measured:
``size(ishft(0L,-15),/n_dim)`` is 1 under GDL). ``overload`` here is built
with ``ishft`` (`:22`-`:23`), so when it reaches `spec_decompress.pro`'s
``skip=overload*2`` / ``FOR i=0,n-1-skip`` GDL halts. The bank supplies GDL
a **copy** of the vendored `spec_decompress.pro` with one line inserted
(``overload = overload[0]``, a no-op under real IDL) ahead of the vendored
tree on ``GDL_PATH`` -- never an edit to `SODA2/` itself
(`tests/test_upstream_tree_is_unmodified.py` sweeps it). This is an oracle
limitation, not a SODA-2 finding; see `gdl_oracle/run_soda2_spec_read_frame_bank.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

import numpy as np

from .spec_decompress import spec_decompress
from .spec_readint import spec_readint

__all__ = ["SpecFrame", "spec_read_frame"]

_MASK_12BIT = 0xFFF
_MISSINGTW_MASK = 0x1000
_FIFO_MASK = 0x4000  # `:20-21` -- decoded, never used (S4-f).
_OVERLOAD_MASK = 0x8000


@dataclass
class SpecFrame:
    """``q = spec_read_frame(...)``'s return struct (`:96-97`).

    Source: ``spec_read_frame.pro:96-97`` (SODA-2)."""

    #: ``(numslices, 128)`` uint8, the package's standing transpose of IDL's
    #: ``bitarr(128, numslices)`` (`spec_decompress`'s own convention). A
    #: single blank slice, ``(1, 128)``, when no frame for `id` was found.
    image: np.ndarray
    #: uint16 1-D when a frame was found; the IDL scalar ``0b`` (here
    #: ``np.uint8(0)``) otherwise -- never a length-1 array. `:33`, `:81`.
    imageraw: np.ndarray | np.uint8
    #: `:64`/`:69` -- assembled from two 16-bit halves, never overflows.
    time: int
    timetrunc: int
    #: 1 unless a frame for `id` was found and decoded (`:32`, `:92`); `:93`
    #: is unreachable and never sets this to anything else (S4-e).
    error: int
    #: 0/1 (or, after the recursion, whatever the last fragment reported).
    overload: int
    #: ``buff[0]`` -- the FIRST fragment's, even after `:74-86`'s
    #: concatenation replaces every other field with the last fragment's.
    particlecount: int


def spec_read_frame(
    f: BinaryIO,
    fpoint: int,
    id: str,
    version: int = 0,
    recursioncount: int = 0,
) -> SpecFrame:
    """``q = spec_read_frame(lun, fpoint, id, version=version,
    recursioncount=recursioncount)``.

    Source: ``spec_read_frame.pro`` (SODA-2).

    ``f`` is an open binary SPEC raw file; ``fpoint`` the byte offset of the
    frame's start (IDL's ``point_lun, lun, fpoint``, `:11`). ``id`` is
    ``'H'`` or ``'V'`` and is matched **case-sensitively** (IDL's ``eq`` on
    strings), exactly like the source -- ``'h'`` matches neither block and
    comes back as a no-frame result even over a perfectly good H frame
    (bank case ``h_plain_lowercase_id``).

    No EOF guard: a recursion chain that runs off the end of the file
    raises, exactly as the IDL would (an unhandled read failure), rather
    than silently returning a short frame.
    """
    f.seek(fpoint)

    # `:13-15` -- the frame's own 3-word header.
    x = spec_readint(f, 3)
    nh = int(x[1]) & _MASK_12BIT
    nv = int(x[2]) & _MASK_12BIT

    # `:18-23` -- flags packed into the top 4 bits of x[1]/x[2].
    missingtwh = (int(x[1]) & _MISSINGTW_MASK) >> 12
    missingtwv = (int(x[2]) & _MISSINGTW_MASK) >> 12
    # fifoh/fifov (`:20-21`) are decoded for fidelity but never consumed --
    # see the module docstring, S4-f.
    overloadh = (int(x[1]) & _OVERLOAD_MASK) >> 15
    overloadv = (int(x[2]) & _OVERLOAD_MASK) >> 15

    # `:26-28` -- the rest of the frame, using the UNDECREMENTED nh/nv.
    buff = spec_readint(f, 2 + nh + nv)
    particlecount = int(buff[0])
    # numslices = int(buff[1]) -- read (`:28`) and never used again (S4-f).

    # `:29-35` -- defaults for "no block ran".
    image = np.zeros((1, 128), dtype=np.uint8)
    time = 0
    timetrunc = 0
    error = 1
    imageraw: np.ndarray | np.uint8 = np.uint8(0)
    overload = 0
    gotframe = False
    nn: int | None = None
    counter: np.ndarray | None = None
    missingtw = 0

    # `:38-46` -- H block.
    if nh > 3 and id == "H":
        if version == 1:
            nh -= 1  # `:39`
        # `:40` -- `ELSE imageraw=0s` is unreachable here (nh stays >= 3);
        # kept as a comment, not a guard, per the module docstring.
        imageraw = buff[2:nh].copy()  # IDL `[2:nh-1]` inclusive -> nh-2 elems
        counter = buff[nh:nh + 2].astype(np.uint32)
        overload = overloadh
        missingtw = missingtwh
        nn = nh
        gotframe = True

    # `:49-57` -- V block, undecremented `nh` as the offset even here.
    if nv > 3 and id == "V":
        if version == 1:
            nv -= 1  # `:50`
        imageraw = buff[nh + 2:nh + nv].copy()
        counter = buff[nh + nv:nh + nv + 2].astype(np.uint32)
        overload = overloadv
        missingtw = missingtwv
        nn = nv
        gotframe = True

    if gotframe:
        assert counter is not None and nn is not None
        # `:63-71` -- assemble the 32-bit time word.
        if version == 0:
            time = (int(counter[0]) << 16) + int(counter[1])
            timetrunc = int(counter[1])
        if version == 1:
            time = (int(counter[1]) << 16) + int(counter[0])
            timetrunc = int(counter[0])

        # `:74-86` -- recursion, capped at depth 2 (three fragments total).
        if missingtw > 0 and recursioncount < 2:
            while True:
                cpoint = f.tell()
                q = spec_read_frame(f, cpoint, id, version=version,
                                    recursioncount=recursioncount + 1)
                if q.error == 0:
                    break
            imageraw = np.concatenate(
                [np.atleast_1d(imageraw), np.atleast_1d(q.imageraw)]
            ).astype(np.uint16)
            time = q.time
            timetrunc = q.timetrunc
            overload = q.overload

        # `:89` -- decompress.
        image = spec_decompress(imageraw, overload, version=version)

        # `:92-93` -- unreachable (S4-e), kept verbatim.
        error = 0
        if overload == 0 and nn == 2:
            error = 1

    return SpecFrame(
        image=image,
        imageraw=imageraw,
        time=time,
        timetrunc=timetrunc,
        error=error,
        overload=overload,
        particlecount=particlecount,
    )
