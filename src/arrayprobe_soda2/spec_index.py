# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``spec_index.pro`` -- walk a SPEC raw file two buffers at a time and
return the pointers to every image, housekeeping and mask record it
contains (P-b).

161 lines of IDL. Signature `spec_index(lun, lite=, minimagesize=,
pointerstart=, pointerstop=, absolutepointer=, version=)`. Every vendored
caller passes **no keyword**: `soda2_buildindex.pro:12` `spec_index(1)` (the
production path, via `soda2_process_2d.pro:366`), `soda2_browse.pro:141`,
`soda2_imagedump.pro:49`. `lite`, `pointerstart`, `pointerstop`,
`absolutepointer` and `version` have no caller in the vendored tree (grepped
directly). `soda2_process_2d.pro:458-461` reads `numimages`, `firstp`,
`imagep` (relative: `i*y.buffsize + y.imagep[...]`), `hkp`, `ihk`,
`buffsize`, `bufftime`, `date`; `spec_absolutepointers.pro` reads
`numimages`, `firstp`, `pointer`, `imagep`. `arrayid`, `ibuffer`,
`particlecounter`, `count`, `error` are read by nothing outside the routine.

Validated against GDL by ``tests/test_soda2_spec_index.py``; bank at
``gdl_oracle/run_soda2_spec_index_bank.py``, 29 cases (26 OK, one
``ERROR``, two ``HALTED``), all matching -- including a third side, an
independent recomputation from the bank's own byte-placement table
(``bank.LAYOUT``), that predicts the golden without importing this module or
NumPy.

**Line-by-line** (IDL 0-based indexing; every index below is exactly what
the source writes):

- ``:12-19`` -- defaults `lite=0`, `minimagesize=2`, `pointerstart=0ULL`,
  `absolutepointer=0`, `version=1` -> `hklength=53`; `version=2` -> 83; any
  other version leaves `hklength` undefined and the IDL's own next use of it
  dies -- this port raises :class:`ValueError` there instead, before any
  read. **`version=1` here is the 2DS/HVPS3 -- the opposite numbering from
  `spec_read_frame`, the same as `spec_read_hk`.** `:15`'s `buffsize=4114ULL`
  default is dead code: `:30` always overwrites it before it is read.
- ``:21-23`` -- `f=fstat(lun)`; `pointerstop` defaults to the file size;
  the bytes to read are `pointerstop` minus `pointerstart`.
- ``:26-30`` -- **buffer-size autodetection**: read the first
  `10000<(f.size/2)` **signed** INT16 words from byte 0 of the file (not
  from `pointerstart`); `w = where(x eq x[0] and x[1:*] eq x[1] and
  x[2:*] eq x[2])` -- IDL's `and` truncates its array operands to the
  shortest length (N-2 here), so this port only ever tests indices
  `range(n-2)`; `buffsize = w[1]*2ULL`, i.e. twice the distance to the
  **first repeat** of the file's own first three words (year, month,
  "dummy" = weekday). Two failure modes, both bank-measured (S4-k): a data
  word triple equal to the header triple within the scanned range gives a
  wrong `buffsize` (`triple_autodetect`: `w=[0,108,2057,4114]`, `buffsize`
  locks onto **216** instead of 4114, so `triple_full`'s later full walk
  reads its third real header as data and `:72` halts); a file of one
  buffer has `w=[0]` (no second match) and IDL dies with `%  SPEC_INDEX:
  Scalar subscript out of range [>]: (1)` at `:30` (`short`) -- this port
  raises :class:`SpecIndexError` naming `spec_index.pro:30` for both the
  no-second-match case and the fewer-than-three-words case it generalises.
- ``:33-35`` -- `headersize=16`; `ndataints=(buffsize-16-2)/2` = 2048 on
  every fixture here -- one trailing "dummy" footer int per buffer is
  skipped by construction.
- ``:37-44`` -- `thisbuffer`/`nextbuffer` are **UINT** (unsigned) arrays of
  `ndataints`; seek to `pointerstart` and read the 8-INT16 **signed**
  header (`year, month, dummy, day, hour, minute, second, millisecond`),
  then `thisbuffer`. (The IDL then seeks back to `pointerstart` at `:44`,
  a no-op for anything this port needs: the next real read, `:78`, always
  repositions the file explicitly, so this port does not reproduce the
  redundant seek.)
- ``:46-51`` -- `numbuffs = bytes2read/buffsize` (floor); `bufftime`
  DOUBLE[numbuffs]; `buffpoint = lindgen(numbuffs)*buffsize` (LONG x
  ULONG64 -> **ULONG64**); `firstp = lonarr(numbuffs)-1`; `numimages =
  intarr(numbuffs)`; `date = lonarr(numbuffs)`.
- ``:53-68`` -- `numpointers = bytes2read/10`; `imagep = intarr(numpointers)`
  (**INT16**, relative offsets <= 4110 on a 4114-byte buffer) or, with
  `/absolutepointer`, `lon64arr(numpointers)` (**INT64**, full file offset);
  `ibuffer`, `ihk` **LONG** (INT32); `particlecounter` **UINT** (UINT16);
  `arrayid` **BYTE** (UINT8); `maskp = lon64arr(1000)`, `hkp =
  lon64arr(100000)` -- **fixed capacities, no bound check** (S4-m, read
  only -- not reachable by anything this bank builds).
- ``:71-72`` -- **`FOR i=0L, numbuffs-2`** -- the loop walks buffers
  `0..numbuffs-2` only; the **last buffer's own data is never scanned**
  (its header is read at `:79` and consumed only by `:144-145`, after the
  loop). This port's `for i in range(numbuffs - 1)` reproduces exactly that
  range (S4-i). `stop, 'File misaligned'` fires when `header.year` is
  outside 2005..2050, checked for buffers `0..numbuffs-2` **only** -- the
  final header is never range-checked (the bank's `main_rel` case carries
  year 1999 in buffer 5, the never-checked last buffer, and it is accepted:
  `date[5]=2451429`). This port raises :class:`SpecFileMisaligned` there,
  reproducing the halt as an exception rather than IDL's interactive
  `stop`.
- ``:75-76`` -- `bufftime[i] = hour*3600D + minute*60D + second +
  millisecond/1000D`, DOUBLE, left to right -- reproduced as four
  Python-float operations in the same order, no reassociation; goldens are
  compared as 16-hex-digit IEEE-754 double bit patterns with no tolerance.
  `date[i] = julday(month, day, year)`, the Julian Day Number as a LONG
  (see :func:`julday`).
- ``:78-81`` -- `point_lun, lun, (i+1)*buffsize` -- **from the file start,
  ignoring `pointerstart`** (S4-j). This port seeks to exactly
  `(i + 1) * buffsize`, not `pointerstart + (i + 1) * buffsize` -- a
  reproduced divergence, not a fix. Reads `header` (buffer i+1's) and
  `nextbuffer`; `b = [thisbuffer, nextbuffer]` (`2*ndataints` UINT words).
- ``:83-138`` -- `REPEAT ... UNTIL j ge ndataints`, resuming from the
  **carried-over `j`**. `CASE b[j] OF`:

  - `12883` (`'2S'`): `nh = b[j+1] and 'fff'x`, `nv = b[j+2] and 'fff'x`,
    `pc = b[j+3]`. If `nh>=minimagesize or nv>=minimagesize`:
    `deltacounter = pc - lastparticlecounterh` if `nh>=minimagesize`, **then
    overwritten** by `pc - lastparticlecounterv` if `nv>=minimagesize` (both
    checks are independent `IF`s, not `IF/ELSE`). If `deltacounter != 0`
    (UINT16 wraparound; only "not zero" is ever observed -- reproduced as
    `(pc - last) & 0xFFFF` so the arithmetic reads like the source, per the
    plan's U3): record `imagep = headersize + j*2` (relative) or
    `i*buffsize + headersize + j*2` (absolute), `ibuffer = i`, `ihk =
    max(hkc - 1, 0)`, `particlecounter = pc`, `firstp[i]` if this buffer's
    first, `numimages[i] += 1`, `arrayid = 'H'` (72) then **unconditionally
    overwritten by `'V'` (86)** when `nv>=minimagesize` too -- a dual H+V
    frame is indexed exactly once, as `'V'`, and updates both
    `lastparticlecounterh` and `lastparticlecounterv`. Always
    `j += 5 + nh + nv`, even for a frame too small to index.
  - `19787` (`'MK'`): `maskp[maskc] = i*buffsize + headersize + j*2`
    (**always absolute**, regardless of `absolutepointer`); `j += 23`.
  - `18507` (`'HK'`): `hkp[hkc] = i*buffsize + headersize + j*2` (also
    always absolute); `j += hklength`.
  - `20044` (`'NL'`): `j = ndataints` -- the rest of the buffer is skipped.
  - `0`, `48813`: `j += 1`.
  - anything else: `j += 1`.
- ``:139-141`` -- `j -= ndataints` (carrying into the next buffer -- a frame
  straddling the boundary is indexed once and its remainder is *skipped*,
  never re-walked); **`IF j ge ndataints THEN j=0`** -- a declared length
  that overshoots the boundary by more than one buffer's worth resets the
  walk to the very start of the next buffer rather than continuing the
  carry (the bank's `nh4095_pc7` -> `h_pc8_after_reset` pair is the
  discriminating case: dropping this reset loses `h_pc8_after_reset`
  entirely, M2 below); `thisbuffer = nextbuffer`.
- ``:144-145`` -- after the loop, the last-read header's `bufftime`/`date`
  are written for `numbuffs-1` -- the header belonging to the file's final
  buffer, whose own data was never walked (S4-i, same finding).
- ``:148`` -- `lite=1` returns `{bufftime, buffpoint, firstp}` **after the
  full walk has already run** -- the source's own comment ("very slow...
  'Lite' option") reads as if it skips the walk; it only skips building the
  image/HK/mask arrays before returning. No caller uses it.
- ``:149-155`` -- trim to `[0 : max(imagec-1, 0)]` (IDL's `>` is MAX, not a
  comparison) -- **an empty result is a 1-element zero array, never a
  length-0 array**: with no images, `imagep=[0]`, `ibuffer=[0]`, `ihk=[0]`,
  `particlecounter=[0]`, `arrayid=[0]`; with no HK records, `hkp=[0]`; no
  mask records, `maskp=[0]` (bank-measured: `hk_rel` has `NIMG=1 IMAGEP=0`;
  `frame_rel`/`s2_pstop` have `NHK=1 HKP=0`). This port's `_trim` helper
  reproduces the sentinel exactly by slicing a zero-initialised array.
- ``:157-159`` -- returns `date, bufftime, pointer, firstp, imagep, hkp,
  maskp, count, numimages, buffsize, ibuffer, ihk, particlecounter,
  arrayid, error:0` -- measured tnames (`size(/tname)`): `LONG, DOUBLE,
  ULONG64, LONG, INT, LONG64, LONG64, ULONG64, INT, ULONG64, LONG, LONG,
  UINT, BYTE, INT` (`imagep` is `LONG64` with `/absolutepointer`).

**`spec_absolutepointers.pro`** (22 lines) is ported alongside this module
in :mod:`arrayprobe_soda2.spec_absolutepointers` -- it consumes exactly the
struct this function returns.

**Findings**: **S4-i** (the last
buffer of every file is never walked, and its header's year is never range
-checked), **S4-j** (`pointerstart` is honoured for the first buffer only;
every later seek is file-relative), **S4-k** (buffer-size autodetection
halts on a data triple equal to the header's own, and dies outright on a
one-buffer file), **S4-l** (images before the first HK record take index 0,
and a file with no HK record at all hands pointer 0 -- the file's own first
header -- to `spec_read_hk`), **S4-m** (`maskp`/`hkp` are fixed-capacity
arrays with no bound check, read only, not measured here).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO

import numpy as np
from numpy.typing import DTypeLike

__all__ = [
    "SpecIndex",
    "SpecIndexLite",
    "SpecIndexError",
    "SpecFileMisaligned",
    "julday",
    "spec_index",
]


class SpecIndexError(ValueError):
    """`:30` -- the buffer-size autodetection found fewer than two matches
    for the file's own first three words, so IDL's `w[1]` is a scalar
    subscript out of range.

    Source: ``spec_index.pro:30`` (SODA-2)."""


class SpecFileMisaligned(RuntimeError):
    """`:72` -- IDL's `stop, 'File misaligned'`. Measured under GDL
    (two separate runs): `stop` here printed the message and
    returned control within seconds rather than blocking, unlike the
    `soda2_samplearea` bank -- see `run_soda2_spec_index_bank`'s module
    docstring.

    Source: ``spec_index.pro:72`` (SODA-2).

    Carries the ``buffsize`` the `:26-30` autodetection computed before the
    walk that raised this -- `:72` fires only after `buffsize` is already
    known, and `triple_full`'s own halt is evidence about *that* value
    (216, not 4114; SODA-2 register entry S4-k) as much as about the halt itself.
    """

    def __init__(self, message: str, buffsize: int | None = None) -> None:
        super().__init__(message)
        self.buffsize = buffsize


def julday(month: int, day: int, year: int) -> int:
    """The Julian Day Number IDL's `julday(month, day, year)` returns for a
    date at 00:00 (no fractional-day argument is ever passed here) --
    Fliegel-Van Flandern, ported rather than transcribed from `julday.pro`
    (not in the vendored tree; IDL's own library routine). Bank-measured:
    ``julday(9,6,2016) == 2457638``, ``julday(9,7,1999) == 2451429``,
    ``julday(1,1,2000) == 2451545``, ``julday(9,2,2016) == 2457634``; the
    day-0 arithmetic case ``julday(9,0,2016) == 2457632`` is GDL-measured
    only, not IDL-confirmed (nothing in the fixtures reaches it).
    """
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


@dataclass
class SpecIndexLite:
    """`lite=1`'s return (`:148`) -- built only after the full walk has
    already run; no caller in the vendored tree uses it."""

    bufftime: np.ndarray   # float64[numbuffs]
    buffpoint: np.ndarray  # uint64[numbuffs]
    firstp: np.ndarray     # int32[numbuffs], -1 where a buffer has no image


@dataclass
class SpecIndex:
    """`spec_index`'s return struct (`:157-159`), one field per IDL tag.
    Dtypes are the measured `size(/tname)` values, not assumed.

    Source: ``spec_index.pro:157-159`` (SODA-2)."""

    date: np.ndarray             # int32[numbuffs]  -- julday(month,day,year)
    bufftime: np.ndarray         # float64[numbuffs]
    pointer: np.ndarray          # uint64[numbuffs] -- IDL's `buffpoint`
    firstp: np.ndarray           # int32; -1 where a buffer has no image
    imagep: np.ndarray           # int16 (relative, :55) or int64 (absolute, :56); [0] when empty
    hkp: np.ndarray               # int64, always an absolute file offset; [0] when empty
    maskp: np.ndarray             # int64, always an absolute file offset; [0] when empty
    count: int                    # numbuffs
    numimages: np.ndarray         # int16
    buffsize: int
    ibuffer: np.ndarray           # int32; [0] when empty
    ihk: np.ndarray               # int32; [0] when empty
    particlecounter: np.ndarray   # uint16; [0] when empty
    arrayid: np.ndarray           # uint8: 72 'H', 86 'V'; [0] when empty
    error: int = 0


def _read_header(f: BinaryIO) -> tuple[int, int, int, int, int, int, int, int]:
    """8 signed INT16 words: `year, month, dummy, day, hour, minute, second,
    millisecond` (`:33`'s anonymous struct)."""
    return struct.unpack("<8h", f.read(16))  # type: ignore[return-value]


def _trim(values: list[int], dtype: DTypeLike) -> np.ndarray:
    """`arr[0 : max(count-1, 0)]` (`:149-155`) via a growing Python list
    instead of IDL's fixed-capacity pre-allocation: empty -> the `[0]`
    sentinel (matching a zero-initialised IDL array sliced to one element),
    non-empty -> exactly the collected values.

    Built via an int64 array, then narrowed with `.astype(dtype)` (W2b,
    D.3): a plain `np.asarray(values, dtype=dtype)` on Python ints out of
    `dtype`'s range raises under NumPy 2's NEP-50 rules, where IDL's own
    assignment into a fixed-width array (e.g. `imagep[imagec]=headersize+
    j*2` into an `intarr`, `spec_index.pro:96`) silently wraps. `.astype`
    reproduces the wrap instead of raising where IDL wraps -- latent on
    real SPEC data (needs `buffsize > 32.7 kB`, measured 4114 in every
    fixture and on UND's 0914 HVPS3 file), kept for a pathological file."""
    return np.asarray(values if values else [0], dtype=np.int64).astype(dtype)


def spec_index(
    f: BinaryIO,
    *,
    lite: bool = False,
    minimagesize: int = 2,
    pointerstart: int = 0,
    pointerstop: int | None = None,
    absolutepointer: bool = False,
    version: int = 1,
) -> SpecIndex | SpecIndexLite:
    """``idx = spec_index(lun, lite=lite, minimagesize=minimagesize,
    pointerstart=pointerstart, pointerstop=pointerstop,
    absolutepointer=absolutepointer, version=version)``.

    Source: ``spec_index.pro`` (SODA-2); bare line references here are into that file.

    ``f`` is an open binary SPEC raw file. Every vendored caller passes no
    keyword at all; `minimagesize=2`, `pointerstart=0`,
    `absolutepointer=False` and `version=1` are IDL's own effective
    defaults (`:12-19`). `pointerstop=None` reproduces "defaults to the
    file size" (`:22`).

    Raises :class:`SpecIndexError` where IDL's own buffer-size
    autodetection would die (`:30`, a one-buffer file or fewer than three
    words to scan), :class:`SpecFileMisaligned` where IDL's `stop, 'File
    misaligned'` would halt (`:72`, a header year outside 2005..2050 in any
    buffer but the last -- the last is never checked, SODA-2 register entry S4-i), and
    :class:`ValueError` for any `version` other than 1 or 2 (`:18-19`
    leaves `hklength` undefined and the IDL's own next use of it dies).
    None of the three refusals advances the file position past what the
    autodetection scan itself required.
    """
    if version == 1:
        hklength = 53
    elif version == 2:
        hklength = 83
    else:
        raise ValueError(
            f"spec_index: version={version!r} is not 1 or 2 -- the IDL "
            "leaves `hklength` undefined here and the next line dies "
            "(spec_index.pro:18-19)")

    f.seek(0, 2)
    size = f.tell()
    if pointerstop is None:
        pointerstop = size
    bytes2read = pointerstop - pointerstart

    # `:26-30` -- buffer-size autodetection, from byte 0 regardless of
    # `pointerstart`. IDL's `and` on operands of length N, N-1, N-2
    # truncates to the shortest (N-2), so only `range(n-2)` is ever tested.
    f.seek(0)
    n = min(10000, size // 2)
    if n < 3:
        raise SpecIndexError(
            "spec_index: fewer than three words in the file to scan for "
            "the buffer-size autodetection (spec_index.pro:27-30)")
    x = np.frombuffer(f.read(2 * n), dtype="<i2")
    hits = [i for i in range(n - 2)
            if x[i] == x[0] and x[i + 1] == x[1] and x[i + 2] == x[2]]
    if len(hits) < 2:
        raise SpecIndexError(
            "spec_index: the buffer-size autodetection found fewer than "
            "two matches for the file's own first three words -- IDL dies "
            "with 'Scalar subscript out of range [>]: (1)' at "
            "spec_index.pro:30")
    buffsize = hits[1] * 2

    headersize = 16
    ndataints = (buffsize - headersize - 2) // 2

    f.seek(pointerstart)
    header = _read_header(f)
    thisbuffer = np.frombuffer(f.read(2 * ndataints), dtype="<u2")

    numbuffs = bytes2read // buffsize
    bufftime = np.zeros(numbuffs, dtype=np.float64)
    pointer = np.arange(numbuffs, dtype=np.uint64) * np.uint64(buffsize)
    firstp = np.full(numbuffs, -1, dtype=np.int32)
    numimages = np.zeros(numbuffs, dtype=np.int16)
    date = np.zeros(numbuffs, dtype=np.int32)

    imagep_list: list[int] = []
    ibuffer_list: list[int] = []
    ihk_list: list[int] = []
    particlecounter_list: list[int] = []
    arrayid_list: list[int] = []
    maskp_list: list[int] = []
    hkp_list: list[int] = []

    imagec = 0
    maskc = 0
    hkc = 0
    j = 0
    lastparticlecounterh = 0
    lastparticlecounterv = 0
    nh = nv = 0  # only meaningful while inside a '2S' branch

    for i in range(numbuffs - 1):  # `FOR i=0L, numbuffs-2` (:71)
        year, month, _dummy, day, hour, minute, second, millisecond = header
        if year < 2005 or year > 2050:
            raise SpecFileMisaligned(
                f"spec_index.pro:72: header.year={year} is outside "
                f"2005..2050 at buffer i={i} of {numbuffs}",
                buffsize=buffsize)
        bufftime[i] = hour * 3600.0 + minute * 60.0 + second + millisecond / 1000.0
        date[i] = julday(month, day, year)

        # `:78` -- file-relative, ignoring `pointerstart` (S4-j).
        f.seek((i + 1) * buffsize)
        header = _read_header(f)
        nextbuffer = np.frombuffer(f.read(2 * ndataints), dtype="<u2")
        b = np.concatenate([thisbuffer, nextbuffer])

        while True:
            tag = int(b[j])
            if tag == 12883:  # '2S'
                nh = int(b[j + 1]) & 0xFFF
                nv = int(b[j + 2]) & 0xFFF
                pc = int(b[j + 3])
                if nh >= minimagesize or nv >= minimagesize:
                    deltacounter = 0
                    if nh >= minimagesize:
                        deltacounter = (pc - lastparticlecounterh) & 0xFFFF
                    if nv >= minimagesize:
                        deltacounter = (pc - lastparticlecounterv) & 0xFFFF
                    if deltacounter != 0:
                        if absolutepointer:
                            imagep_list.append(i * buffsize + headersize + j * 2)
                        else:
                            imagep_list.append(headersize + j * 2)
                        ibuffer_list.append(i)
                        ihk_list.append(max(hkc - 1, 0))
                        particlecounter_list.append(pc)
                        if firstp[i] == -1:
                            firstp[i] = imagec
                        numimages[i] += 1
                        arrayid = 0
                        if nh >= minimagesize:
                            arrayid = 72  # 'H'
                            lastparticlecounterh = pc
                        if nv >= minimagesize:
                            arrayid = 86  # 'V' -- overwrites 'H' for a dual frame
                            lastparticlecounterv = pc
                        arrayid_list.append(arrayid)
                        imagec += 1
                j += 5 + nh + nv
            elif tag == 19787:  # 'MK' -- always absolute
                maskp_list.append(i * buffsize + headersize + j * 2)
                maskc += 1
                j += 23
            elif tag == 18507:  # 'HK' -- always absolute
                hkp_list.append(i * buffsize + headersize + j * 2)
                hkc += 1
                j += hklength
            elif tag == 20044:  # 'NL'
                j = ndataints
            else:  # 0, 48813 ('BEAD'), or anything unrecognised
                j += 1
            if j >= ndataints:
                break

        j -= ndataints
        if j >= ndataints:  # `:140` -- a giant overshoot resets, not carries
            j = 0
        thisbuffer = nextbuffer

    # `:143-145` -- the last-read header, never range-checked (S4-i).
    year, month, _dummy, day, hour, minute, second, millisecond = header
    date[numbuffs - 1] = julday(month, day, year)
    bufftime[numbuffs - 1] = hour * 3600.0 + minute * 60.0 + second + millisecond / 1000.0

    if lite:
        return SpecIndexLite(bufftime=bufftime, buffpoint=pointer, firstp=firstp)

    imagep_dtype = np.int64 if absolutepointer else np.int16
    return SpecIndex(
        date=date,
        bufftime=bufftime,
        pointer=pointer,
        firstp=firstp,
        imagep=_trim(imagep_list, imagep_dtype),
        hkp=_trim(hkp_list, np.int64),
        maskp=_trim(maskp_list, np.int64),
        count=numbuffs,
        numimages=numimages,
        buffsize=buffsize,
        ibuffer=_trim(ibuffer_list, np.int32),
        ihk=_trim(ihk_list, np.int32),
        particlecounter=_trim(particlecounter_list, np.uint16),
        arrayid=_trim(arrayid_list, np.uint8),
        error=0,
    )
