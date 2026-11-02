# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""SODA-2's SEA M300 buffer walk for the CIP : ``readdatadir.pro``,
``seaimagepointers.pro`` and ``readseabuffer_caps.pro``, ported whole.

Author-directed 2026-09-15 (the open SODA-2 decision answered for the
CIP): *"Prioritize also the soda2 port and soda processing of the cip data
using this package alone"*. This is the SODA-2 route through a UND ``.sea``
file, ported from the IDL, **not** borrowed from ``arrayprobe.readers.sea``
(the UIOOPS-side reader, which reads the same tag ``33000``/``4098`` records by
its own logic): the two walks differ in where they look for the next buffer,
which time tag they accept and when they give up, so sharing code would make
the SODA-2 port reproduce UIOOPS's reading instead of SODA-2's.

Vendored sources (never edited): ``SODA2/abansemer-soda2-afcea15/
readdatadir.pro`` (9 lines), ``seaimagepointers.pro`` (83),
``readseabuffer_caps.pro`` (48), ``sfm.pro`` (10, identical in body to
``hms2sfm.pro``, reused from :mod:`timeconv`). GDL bank:
``gdl_oracle/run_soda2_cip_bank.py``.

**The file layout these routines assume.** An SEA file is a chain of
*buffers*; each starts with a list of 16-byte data directories
(``readdatadir``: ``tagNumber, dataOffset, numberBytes, samples,
bytesPerSample`` UINT, ``type, parameter1..3`` BYTE, ``address`` UINT) ended
by tag ``999``, whose ``dataOffset`` (plus ``parameter1*65536``) is the
distance to the next buffer. Tag ``0`` with 36 (or 18) bytes is the time
record; the probe's image tag (``op.seatag[0]``, ``33000`` for the UND CIP)
points at the image bytes. All reads are native little-endian (``readu`` on
x86, no ``swap_endian``).

**Line-by-line points worth knowing** (the no-image, short-image, >320000 and end-of-file
cases are in the bank; the rest are read):

- ``seaimagepointers.pro:8`` -- a walk that starts within 5000 bytes of the
  end of file returns ``eof`` without reading anything.
- ``:17-22`` -- ``imagepoint``, ``timepoint``, ``numberbytes`` are set
  **once**, before the outer loop, and never reset between buffers: a buffer
  with no image tag keeps the previous buffer's values (harmless in the
  measured cases because the stale ``numberbytes`` is the one that made the
  previous buffer skip; no bank case isolates it -- read, not measured).
- ``:37`` -- the image test is ``tagnumber eq tag[0]`` and is tested
  independently of the time test, so ``tag[0] = 0`` would make every time
  record an "image"; ``readseabuffer_caps.pro:5`` stops on ``tag[0] eq 0``
  before that can happen.
- ``:56`` -- when any directory in the buffer has ``numberBytes+dataOffset
  >= 65535`` the ``999`` record's own offset is replaced by that maximum.
- ``:62-64`` -- two end-of-file guards, one against the buffer's own extent
  and one against the next directory read.
- ``readseabuffer_caps.pro:18`` -- the start time is ``hh*10000 + mm*100 +
  ss + frac_num/frac_den`` in DOUBLE, ``:38`` zeroes it above ``320000``;
  the stop time (``:22``) has no such guard.
- ``:34`` -- the CIP image is ``bytarr(numberbytes)``: the whole 4098-byte
  record, 2 bytes more than the 4096-byte DMT compressed image
  ``decompress_dmt3`` was written for (it is given all 4098).
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import BinaryIO

import numpy as np

__all__ = [
    "DataDir",
    "SeaPointers",
    "SeaBuffer",
    "SeaEOF",
    "readdatadir",
    "seaimagepointers",
    "readseabuffer_caps",
    "idl_sfm",
    "CIP1D_DTYPE",
]

_DATADIR = struct.Struct("<HHHHHBBBBH")

#: ``readseabuffer_caps.pro:26-28`` -- the CIP-1D record, 180 bytes. Every
#: field is INT except ``particlecounter`` (UINT, ``0us``); ``hostsynccounter``
#: is declared ``02``, an INT literal.
CIP1D_DTYPE = np.dtype([
    ("header", "<i2"), ("bytecount", "<i2"), ("oversizereject", "<i2"),
    ("count", "<i2", (62,)), ("dofreject", "<i2"), ("endreject", "<i2"),
    ("housekeeping", "<i2", (16,)), ("particlecounter", "<u2"),
    ("secmsec", "<i2"), ("hourmin", "<i2"), ("hostsynccounter", "<i2"),
    ("resetflag", "<i2"), ("checksum", "<i2"), ("trailer", "<i2"),
])


class SeaReadError(RuntimeError):
    """An IDL halt this module reproduces as a raise, naming the line."""


@dataclass
class DataDir:
    """``readdatadir.pro:4-5``'s ``datadir`` structure."""

    tagnumber: int
    dataoffset: int
    numberbytes: int
    samples: int
    bytespersample: int
    type: int
    parameter1: int
    parameter2: int
    parameter3: int
    address: int


@dataclass
class SeaEOF:
    """``{starttime:999999, image:0, eof:1}`` -- the end-of-file return of
    ``seaimagepointers.pro:8,62,64`` and ``readseabuffer_caps.pro:9``."""

    starttime: int = 999999
    image: int = 0
    eof: int = 1


@dataclass
class SeaPointers:
    """``seaimagepointers.pro:81-82``'s return."""

    timepoint: int
    imagepoint: int
    numberbytes: int
    cur_ptr: int
    elapsedpoint: int
    taspoint: int
    nextpointer: int
    eof: int = 0


@dataclass
class SeaBuffer:
    """``readseabuffer_caps.pro:45-47``'s return (``eof == 0``)."""

    starttime: float
    stoptime: float
    year: int
    month: int
    day: int
    image: np.ndarray
    difftime: float
    eof: int
    pointer: int
    tas: int
    probetime: float
    imagepoint: int
    numberbytes: int
    timepoint: int


def _fsize(f: BinaryIO) -> int:
    return os.fstat(f.fileno()).st_size


def readdatadir(f: BinaryIO) -> DataDir:
    """``readdatadir.pro`` -- one 16-byte directory at the current position.
    A short read is IDL's ``readu`` "End of file encountered" halt."""
    raw = f.read(16)
    if len(raw) < 16:
        raise SeaReadError(
            f"readdatadir.pro:7: readu hit end of file ({len(raw)} of 16 bytes)")
    return DataDir(*_DATADIR.unpack(raw))


def seaimagepointers(f: BinaryIO, tag: int | np.ndarray | list[int]) -> SeaPointers | SeaEOF:
    """``seaimagepointers.pro:1-83``. ``tag`` is a scalar (``readseabuffer_caps``
    always passes one) or up to three tags ``[image, tas, elapsed]``."""
    tags = np.atleast_1d(np.asarray(tag)).astype(np.int64)
    q_size = _fsize(f)
    q_cur = f.tell()
    lastpointer = q_cur                                   # :7
    if q_size - q_cur <= 5000:                            # :8
        return SeaEOF()

    tas_tagexists = tags.size >= 2 and int(tags[1]) > 0    # :13
    elapsed_tagexists = tags.size == 3 and int(tags[2]) > 0  # :14

    imagepoint = 0                                        # :17-22, set once
    timepoint = 0
    elapsedpoint = 0
    taspoint = 0
    numberbytes = 4098
    tag0 = int(tags[0])

    while True:                                           # :24
        maxbytes = 0
        while True:                                       # :26
            buf = readdatadir(f)
            maxbytes = max(maxbytes, buf.numberbytes + buf.dataoffset)  # :28
            if buf.tagnumber == 0 and buf.numberbytes in (36, 18):      # :31
                timepoint = lastpointer + buf.dataoffset
            if buf.tagnumber == tag0:                                    # :37
                imagepoint = lastpointer + buf.dataoffset
                numberbytes = buf.numberbytes
            if tas_tagexists and buf.tagnumber == int(tags[1]):          # :44
                taspoint = lastpointer + buf.dataoffset
            if elapsed_tagexists and buf.tagnumber == int(tags[2]):      # :47
                elapsedpoint = lastpointer + buf.dataoffset
            if buf.tagnumber == 999:                                     # :50-57
                dataoffset = buf.dataoffset
                if maxbytes >= 65535:
                    dataoffset = maxbytes
            if lastpointer + maxbytes + 16 >= q_size:                    # :62
                return SeaEOF()
            if f.tell() + 16 >= q_size:                                  # :64
                return SeaEOF()
            if buf.tagnumber == 999:                                     # :65
                break

        step = dataoffset + buf.parameter1 * 65536
        if imagepoint == 0 or timepoint == 0 or numberbytes < 100:      # :68-72
            lastpointer = lastpointer + step
            f.seek(lastpointer)
        else:                                                            # :73-77
            nextpointer = lastpointer + step
            break

    return SeaPointers(timepoint=timepoint, imagepoint=imagepoint,
                       numberbytes=numberbytes, cur_ptr=q_cur,
                       elapsedpoint=elapsedpoint, taspoint=taspoint,
                       nextpointer=nextpointer)


def _hhmmss(t: np.ndarray) -> float:
    """``readseabuffer_caps.pro:18,22`` -- ``t[3]*10000d + t[4]*100d + t[5] +
    t[6]/double(t[7])``, left to right in DOUBLE. A zero denominator is IEEE
    (IDL prints a floating-point warning and continues)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.float64(t[6]) / np.float64(t[7])
    return float(np.float64(t[3]) * 10000.0 + np.float64(t[4]) * 100.0
                 + np.float64(t[5]) + frac)


def _idl_long(v: float) -> int:
    """IDL ``long()`` of a DOUBLE: truncation toward zero; a NaN, an infinity
    or a value outside the LONG range gives ``-2147483648`` (measured under
    GDL 1.1.2 -- IDL's own value for these is platform-defined)."""
    if not np.isfinite(v) or not (-2147483648.0 <= v < 2147483648.0):
        return -2147483648
    return int(v)


def _idl_ldiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def idl_sfm(hms: float) -> float:
    """``sfm.pro`` / ``hms2sfm.pro`` (identical bodies) for a DOUBLE ``hms``,
    including a non-finite or out-of-LONG-range one: every step is the IDL
    LONG arithmetic, then ``fraction = double(hms) - long(hms)`` is added, so
    a NaN or infinite ``hms`` gives back the same non-finite value whatever
    ``long()`` returned (derived; the GDL value of ``long()`` is used)."""
    lv = _idl_long(hms)
    hour = _idl_ldiv(lv, 10000)
    minute = _idl_ldiv(lv - hour * 10000, 100)
    second = lv - hour * 10000 - minute * 100
    fraction = float(np.float64(hms) - np.float64(lv))
    return float(hour * 3600 + minute * 60 + second) + fraction


def readseabuffer_caps(f: BinaryIO, tag: int | np.ndarray, probetype: str) -> SeaBuffer | SeaEOF:
    """``readseabuffer_caps.pro:1-48``, ``probetype`` ``'CIP'``/``'CIPG'`` (a
    ``numberbytes``-long BYTE image) or ``'CIP1D'`` (a :data:`CIP1D_DTYPE`
    record). ``'CAS'`` is refused by name (no CAS route in this port)."""
    tags = np.atleast_1d(np.asarray(tag))
    if int(tags[0]) == 0:                                                # :5
        raise SeaReadError(
            "readseabuffer_caps.pro:5: stop -- Enter correct tag numbers into "
            "probeversion.pro or soda2_probespecs.pro")
    if probetype == "CAS":
        raise NotImplementedError(
            "readseabuffer_caps.pro:29-31: the CAS record is not ported")

    x = seaimagepointers(f, tag)                                         # :8
    if isinstance(x, SeaEOF):                                            # :9
        return SeaEOF()

    f.seek(x.timepoint)                                                  # :12
    raw = f.read(18)
    if len(raw) < 18:
        raise SeaReadError("readseabuffer_caps.pro:14: readu hit end of file")
    t = np.frombuffer(raw, dtype="<i2")
    year, month, day = int(t[0]), int(t[1]), int(t[2])
    hhmmss = _hhmmss(t)                                                  # :18
    raw = f.read(18)                                                     # :21
    if len(raw) < 18:
        raise SeaReadError("readseabuffer_caps.pro:21: readu hit end of file")
    hhmmss_stop = _hhmmss(np.frombuffer(raw, dtype="<i2"))               # :22

    f.seek(x.imagepoint)                                                 # :33
    if probetype == "CIP1D":
        nbytes = CIP1D_DTYPE.itemsize
    else:
        nbytes = x.numberbytes                                           # :34
    raw = f.read(nbytes)                                                 # :35
    if len(raw) < nbytes:
        raise SeaReadError("readseabuffer_caps.pro:35: readu hit end of file")
    image: np.ndarray
    if probetype == "CIP1D":
        image = np.frombuffer(raw, dtype=CIP1D_DTYPE)[0:1].copy()
    else:
        image = np.frombuffer(raw, dtype=np.uint8).copy()

    if hhmmss > 320000:                                                  # :38
        hhmmss = 0.0
    probetime = 0.0                                                      # :39 (INT 0)
    if probetype == "CIP1D":                                             # :40-41
        hm = int(image["hourmin"][0])  # type: ignore[call-overload]
        sm = int(image["secmsec"][0])  # type: ignore[call-overload]
        probetime = (((hm & 1984) >> 6) * 10000.0 + (hm & 63) * 100.0
                     + ((sm & 64512) >> 10) + (sm & 1023) / 1000.0)

    f.seek(x.nextpointer)                                                # :44
    return SeaBuffer(starttime=hhmmss, stoptime=hhmmss_stop, year=year,
                     month=month, day=day, image=image,
                     difftime=idl_sfm(hhmmss_stop) - idl_sfm(hhmmss),
                     eof=0, pointer=x.cur_ptr, tas=100, probetime=probetime,
                     imagepoint=x.imagepoint, numberbytes=x.numberbytes,
                     timepoint=x.timepoint)
