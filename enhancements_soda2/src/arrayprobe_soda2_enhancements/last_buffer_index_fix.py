# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-i: the last buffer of every SPEC raw file is never indexed, and
its own header is never range-checked.

``spec_index.pro:71``, ``FOR i=0L, numbuffs-2`` -- the walk covers
buffers ``0..numbuffs-2`` only. The file's final buffer is read once,
as ``nextbuffer`` on the loop's last pass, and its header feeds
``bufftime[numbuffs-1]``/``date[numbuffs-1]`` after the loop exits --
but its own 2048 data words are never scanned for ``'2S'``/``'HK'``/
``'MK'`` markers, so a run over N files loses N buffers' worth of
particles, silently. The same range also means the final header's own
year is the one header ``:72``'s validity check never reaches.

**Correction**: the register's own suggested edit -- loop to
``numbuffs-1`` instead of ``numbuffs-2``, feeding a zero-filled
``nextbuffer`` on the final pass (there is no buffer past the last one
to read), and apply the ``:72`` year check to the final header too.

This is the plan's named borderline case: the fix is a change to the
driver loop's own range, not a value substitutable after the fact, so
this module duplicates ``spec_index``'s walk (the tag-parsing ``CASE``
included) rather than wrapping a smaller piece of it --
``src/arrayprobe_soda2/spec_index.py`` is never imported
for writing and never modified. Every helper it *can* reuse
(``julday``, ``_read_header``, ``_trim``) is imported, not
retranscribed. ``lite=True`` is refused by name -- no caller in the
vendored tree uses it (the port's own docstring), and this module has
no obligation to support the whole surface, only the default call
production reaches. Tests: ``tests/test_last_buffer_index_fix.py``.
"""
from __future__ import annotations

from typing import BinaryIO

import numpy as np
from arrayprobe_soda2.spec_index import (
    SpecFileMisaligned,
    SpecIndex,
    SpecIndexError,
    _read_header,
    _trim,
    julday,
)

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["LiteNotSupported", "corrected_spec_index"]


class LiteNotSupported(NotImplementedError):
    """``lite=True`` is refused -- no caller in the vendored tree passes
    it (the port's own docstring), and S4-i's fix concerns only the
    full walk's own buffer range."""


def corrected_spec_index(
    f: BinaryIO,
    *,
    minimagesize: int = 2,
    pointerstart: int = 0,
    pointerstop: int | None = None,
    absolutepointer: bool = False,
    version: int = 1,
    lite: bool = False,
) -> SpecIndex:
    """``spec_index`` with S4-i corrected: the walk covers buffers
    ``0..numbuffs-1`` (every buffer), the final pass uses a zero-filled
    ``nextbuffer`` (there is nothing past the file's last buffer to
    read), and the ``:72`` year range-check applies to the final
    header too. Every other line reproduces ``spec_index.pro`` exactly
    -- including S4-j/S4-k/S4-l/S4-m, none of which this module
    corrects."""
    if lite:
        raise LiteNotSupported(
            "last_buffer_index_fix.corrected_spec_index: lite=True is "
            "not supported -- no vendored caller uses it")

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

    # S4-i: `range(numbuffs)`, not `range(numbuffs - 1)` -- every buffer,
    # including the last, is walked and year-checked.
    for i in range(numbuffs):
        year, month, _dummy, day, hour, minute, second, millisecond = header
        if year < 2005 or year > 2050:
            raise SpecFileMisaligned(
                f"spec_index.pro:72: header.year={year} is outside "
                f"2005..2050 at buffer i={i} of {numbuffs}",
                buffsize=buffsize)
        bufftime[i] = hour * 3600.0 + minute * 60.0 + second + millisecond / 1000.0
        date[i] = julday(month, day, year)

        if i + 1 < numbuffs:
            f.seek((i + 1) * buffsize)
            header = _read_header(f)
            nextbuffer = np.frombuffer(f.read(2 * ndataints), dtype="<u2")
        else:
            # S4-i: there is no buffer past the file's last one. A
            # zero-filled `nextbuffer` gives the walk's own bookkeeping
            # something in range; `header` is never read again after
            # this iteration.
            nextbuffer = np.zeros(ndataints, dtype="<u2")
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
                            arrayid = 86  # 'V'
                            lastparticlecounterv = pc
                        arrayid_list.append(arrayid)
                        imagec += 1
                j += 5 + nh + nv
            elif tag == 19787:  # 'MK'
                maskp_list.append(i * buffsize + headersize + j * 2)
                maskc += 1
                j += 23
            elif tag == 18507:  # 'HK'
                hkp_list.append(i * buffsize + headersize + j * 2)
                hkc += 1
                j += hklength
            elif tag == 20044:  # 'NL'
                j = ndataints
            else:
                j += 1
            if j >= ndataints:
                break

        j -= ndataints
        if j >= ndataints:
            j = 0
        thisbuffer = nextbuffer

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


register(EnhancementSpec(
    name="last_buffer_index_fix",
    summary="spec_index walks every buffer, including the file's last "
            "one (previously never scanned for '2S'/'HK'/'MK' markers), "
            "and range-checks the final header's own year too.",
    finding="S4-i",
    reachability="live",
    entry_point="corrected_spec_index",
))
