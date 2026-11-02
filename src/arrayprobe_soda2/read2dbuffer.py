# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""`soda2_read2dbuffer.pro`, SPEC branch
(`:15-17`, `:109-117`); the SEA branch's CIP route
(`:69-89`, :func:`read2dbuffer_sea`); the DMT/PADS branch (`:91-107`,
:func:`read2dbuffer_dmt`, bank `gdl_oracle/run_soda2_dmt_bank.py`). RAF, TXT,
T28, HVPS1995 and the legacy SEA probes stay unported.

Vendored source: `SODA2/abansemer-soda2-afcea15/soda2_read2dbuffer.pro`.
Bank: `gdl_oracle/run_soda2_preloop_bank.py`, golden
`tests/data/gdl_soda2_preloop_golden.json`.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Any, BinaryIO

import numpy as np

from .spec_index import _read_header, julday


@dataclass
class Buffer2D:
    """The structure ``soda2_read2dbuffer.pro`` (SODA-2) returns, e.g. the SPEC branch at
    ``:116``, one field per IDL tag."""
    time: float | np.integer
    image: int
    difftime: float
    eof: int
    tas: float | np.integer | np.floating
    pointer: int
    date: int
    overload: int


def _fstat_size(f: BinaryIO) -> int:
    """IDL `fstat(lun).size`: the on-disk size of the file behind `f` (for a
    `gzip` stream, the compressed length, as GDL reports it).

    A `GzipFile` is unwrapped to the stream it reads from before any length is
    taken: seeking to the end of the `GzipFile` itself would give the
    DECOMPRESSED length, which GDL never reports."""
    import gzip
    while isinstance(f, gzip.GzipFile) and getattr(f, "fileobj", None) is not None:
        f = f.fileobj  # type: ignore[assignment]
    try:
        fd = f.fileno()
    except (AttributeError, OSError, ValueError):
        name = getattr(f, "name", None)
        if isinstance(name, (str, bytes, os.PathLike)) and os.path.exists(name):
            return os.stat(name).st_size
        here = f.tell()
        f.seek(0, 2)
        size = f.tell()
        f.seek(here)
        return size
    return os.fstat(fd).st_size


def read2dbuffer_spec(f: BinaryIO, op: dict) -> Buffer2D:
    """`soda2_read2dbuffer.pro:15-17` (EOF test) then `:109-117` (the SPEC
    branch). `f` is an open binary file already positioned by the caller
    (`point_lun,1,buffpoint[i]`, driver `:451`)."""
    pointer = f.tell()  # :15

    # :17 returns the null buffer at end of file -- true only when the file
    # position is exactly at end-of-file; a partial header (fewer than 16
    # bytes left) is NOT eof(), so `readu` below raises instead.
    #
    # A bounded probe: only len(tail) in {0, 1-15, >=16} is used here (the
    # three-way test below, and the message quotes it only when < 16). The
    # probe read the whole remainder of the file until 2026-09-15, once per
    # buffer -- quadratic in file size, 7.3 s per buffer on a 622 MB UND file,
    # where IDL's eof() is O(1). Same answers, byte for byte:
    # tests/test_soda2_read2dbuffer_bounded.py.
    start = f.tell()
    tail = f.read(16)
    f.seek(start)
    if len(tail) == 0:
        # :16 nullbuffer -- INT tas/time (the struct literal declares them
        # 0, not 0.0/0d).
        return Buffer2D(image=0, tas=np.int16(0), time=np.int16(0),
                         difftime=0.0, eof=1, pointer=pointer, overload=0,
                         date=0)
    if len(tail) < 16:
        raise EOFError(
            "soda2_read2dbuffer.pro:110 readu on a partial 8-word header "
            f"({len(tail)} bytes remain) -- IDL 'End of file encountered'.")

    year, month, _dummy, day, hour, minute, second, millisecond = _read_header(f)
    time = hour * 3600.0 + minute * 60.0 + second * 1.0 + millisecond / 1000.0  # :112, DOUBLE
    date = julday(month, day, year) if year > 0 else 0  # :113

    fixedtas = op.get("fixedtas", np.float32(0.0))
    tas = float(fixedtas) if float(fixedtas) > 0 else 100.0  # :114, FLOAT

    timeoffset = op.get("timeoffset", np.float32(0.0))
    # FLOAT widening rule (T7): a np.float32 timeoffset is widened via
    # Python float() the same way IDL widens FLOAT -> DOUBLE, carrying
    # float32 rounding into the double sum.
    offset = float(timeoffset)
    return Buffer2D(time=time + offset, image=0, difftime=0.0, eof=0,
                     tas=np.float32(tas), pointer=pointer, date=date,
                     overload=0)


@dataclass
class SeaBuffer2D:
    """`soda2_read2dbuffer.pro:86-88`'s SEA return. ``stoptime``
    is the field `soda2_processbuffer.pro:200` overwrites through the caller's
    ``b`` (IDL passes it by reference)."""

    time: float
    stoptime: float
    image: np.ndarray
    difftime: float
    eof: int
    tas: np.floating
    pointer: int
    imagepoint: int
    timepoint: int
    date: int
    overload: int


CIP1D_RECORD_BYTES = 180


def _decode_cip1d(payload: bytes) -> dict:
    """`readseabuffer_caps.pro:26-28`, `:40-41` -- one CIP-1D image record.

    The IDL struct is fourteen little-endian fields, 180 bytes: header,
    bytecount, oversizereject (INT), count (INT[62], bytes 6-130), dofreject,
    endreject (INT), housekeeping (INT[16], bytes 134-166), particlecounter
    (UINT, 166-168), secmsec, hourmin, hostsynccounter, resetflag, checksum,
    trailer (INT). `probetime` is the `:40-41` decode of hourmin and secmsec,
    a DOUBLE; the INT operands promote to LONG for the masks, which for a
    negative INT selects the same bits as its unsigned pattern.
    """
    if len(payload) < CIP1D_RECORD_BYTES:
        raise ValueError(f"CIP-1D record needs {CIP1D_RECORD_BYTES} bytes, got {len(payload)}")
    head = struct.unpack_from("<3h", payload, 0)
    count = np.frombuffer(payload, "<i2", 62, 6).astype(np.int16)
    dofreject, endreject = struct.unpack_from("<2h", payload, 130)
    housekeeping = np.frombuffer(payload, "<i2", 16, 134).astype(np.int16)
    (particlecounter,) = struct.unpack_from("<H", payload, 166)
    secmsec, hourmin, hostsync, resetflag, checksum, trailer = struct.unpack_from(
        "<6h", payload, 168)
    probetime = (((hourmin & 1984) >> 6) * 10000.0 + (hourmin & 63) * 100.0
                 + ((secmsec & 64512) >> 10) + (secmsec & 1023) / 1000.0)
    return {"header": head[0], "bytecount": head[1], "oversizereject": head[2],
            "count": count, "dofreject": dofreject, "endreject": endreject,
            "housekeeping": housekeeping, "particlecounter": particlecounter,
            "secmsec": secmsec, "hourmin": hourmin, "hostsynccounter": hostsync,
            "resetflag": resetflag, "checksum": checksum, "trailer": trailer,
            "probetime": float(probetime)}


def _nullbuffer(pointer: int) -> Buffer2D:
    """`:16` -- INT tas/time (the struct literal declares them 0, not 0.0/0d)."""
    return Buffer2D(image=0, tas=np.int16(0), time=np.int16(0), difftime=0.0,
                    eof=1, pointer=pointer, overload=0, date=0)


def _at_eof(f: BinaryIO) -> bool:
    """IDL ``eof(lun)``: true only exactly at end of file (O(1) probe)."""
    start = f.tell()
    probe = f.read(1)
    f.seek(start)
    return len(probe) == 0


def read2dbuffer_sea(f: BinaryIO, op: dict) -> Buffer2D | SeaBuffer2D:
    """`soda2_read2dbuffer.pro:15-17` then `:69-89` (the SEA branch), for
    ``probetype`` ``'CIP'``/``'CIPG'`` (`:72-76`: ``readseabuffer_caps`` with
    ``tag=op.seatag[0]``). The legacy SEA probes (2DC, 1D2D, HVPS, HAIL:
    `:77-82`, ``read2dseabuffer.pro``) are refused by name."""
    from .sea import SeaEOF, idl_sfm, readseabuffer_caps

    pointer = f.tell()                                          # :15
    if _at_eof(f):                                              # :17
        return _nullbuffer(pointer)
    probetype = str(op.get("probetype"))
    if probetype not in ("CIP", "CIPG"):
        raise NotImplementedError(
            f"soda2_read2dbuffer.pro:77-82: SEA probetype {probetype!r} needs "
            "read2dseabuffer.pro, not ported (only the CIP route, :72-76, is)")
    fixedtas = op.get("fixedtas", np.float32(0.0))              # :74, FLOAT
    tas = np.float32(fixedtas) if float(fixedtas) > 0 else np.float32(100.0)
    seatag = np.atleast_1d(np.asarray(op["seatag"]))
    a = readseabuffer_caps(f, tag=int(seatag[0]), probetype="CIP")   # :75
    if isinstance(a, SeaEOF):                                   # :84
        return _nullbuffer(pointer)
    date = julday(a.month, a.day, a.year) if a.year > 0 else 0  # :85
    offset = float(op.get("timeoffset", np.float32(0.0)))       # FLOAT widening (T7)
    return SeaBuffer2D(                                         # :86-88
        time=idl_sfm(a.starttime) + offset, stoptime=idl_sfm(a.stoptime) + offset,
        image=a.image, difftime=0.0, eof=0, tas=tas, pointer=pointer,
        imagepoint=a.imagepoint, timepoint=a.timepoint, date=date, overload=0)


@dataclass
class DmtBuffer2D:
    """`soda2_read2dbuffer.pro:106`'s DMT return: ``image`` is the raw
    ``bytarr(4096)`` (`:93`), ``eof`` 1 when fewer than 4112 bytes remained
    (`:98`; the header is then all zeros, so ``time`` is ``timeoffset``)."""

    time: float
    image: np.ndarray
    difftime: float
    eof: int
    tas: np.floating
    pointer: int
    date: int
    overload: int


def read2dbuffer_dmt(f: BinaryIO, op: dict) -> Buffer2D | DmtBuffer2D:
    """`soda2_read2dbuffer.pro:15-17` then `:91-107` (the DMT/PADS branch,
    every ``probetype``: PIP is already ``'CIP'`` by `soda2_update_op.pro:49`).

    Layout (`:92-93`): 8 INT16 ``year, month, day, hour, minute, second,
    millisecond, weekday`` then 4096 image bytes -- 4112 bytes; ``subformat
    0`` (PACS) appends 12 bytes read into ``dummy`` (`:94,:99`), so a record
    is 4124 bytes there. `:98` reads the record only when at least 4112 bytes
    remain, else ``eofile=1`` with the struct still zero; `:99` then reads the
    12 dummy bytes **regardless**, so a PACS file whose remainder is under 12
    bytes makes IDL's ``readu`` raise ``End of file encountered``
    (``EOFError`` here). `:101` divides milliseconds by 100 for ``subformat
    2`` (the PADS centisecond error)."""
    pointer = f.tell()                                          # :15
    if _at_eof(f):                                              # :17
        return _nullbuffer(pointer)
    subformat = int(op.get("subformat", 0))
    start = f.tell()
    # :96-98 `fstat(lun).size`: on a `compress=1` lun this is the compressed
    # on-disk length (measured under GDL, gdl_soda2_gz_input_golden.json).
    remaining = _fstat_size(f) - start
    year = month = day = hour = minute = second = millisecond = 0
    image: np.ndarray = np.zeros(4096, dtype=np.uint8)
    eofile = 0
    if remaining >= 4112:                                       # :98
        year, month, day, hour, minute, second, millisecond, _weekday = \
            struct.unpack("<8h", f.read(16))
        image = np.frombuffer(f.read(4096), dtype=np.uint8).copy()
    else:
        eofile = 1
    if subformat == 0:                                          # :99
        dummy = f.read(12)
        if len(dummy) < 12:
            raise EOFError(
                "soda2_read2dbuffer.pro:99 readu on the 12 dummy bytes with "
                f"{len(dummy)} remaining -- IDL 'End of file encountered'.")
    divisor = 100.0 if subformat == 2 else 1000.0               # :100-101
    time = hour * 3600.0 + minute * 60.0 + second * 1.0 + millisecond / divisor  # :102
    date = julday(month, day, year) if year > 0 else 0          # :103
    fixedtas = op.get("fixedtas", np.float32(0.0))              # :104, FLOAT
    tas = np.float32(fixedtas) if float(fixedtas) > 0 else np.float32(100.0)
    offset = float(op.get("timeoffset", np.float32(0.0)))       # FLOAT widening (T7)
    return DmtBuffer2D(time=time + offset, image=image, difftime=0.0, eof=eofile,
                       tas=tas, pointer=pointer, date=date, overload=0)


@dataclass
class RafBuffer2D:
    """`soda2_read2dbuffer.pro:64-65`'s RAF return: ``image`` is ``a.image``
    (2DC ``ulonarr(1024)``, F2DC/F2DC_v2 ``ulon64arr(512)``, HVPS1
    ``intarr(2048)``, `:21-31`), ``a`` the whole swapped record."""

    time: float
    image: np.ndarray
    difftime: int
    eof: int
    tas: np.integer | np.floating
    pointer: int
    date: int
    overload: np.floating
    a: dict


_RAF_HEAD = ">BB9h"  # :21-22 probetype, probenumber (BYTE), 9 INT tags


def _raf_image_dtype(probetype: str) -> str:
    """`:21-31`: the image array per probe type (big-endian after :54)."""
    if probetype in ("F2DC", "F2DC_v2"):                        # :24-27
        return ">u8"
    if probetype == "HVPS1":                                    # :28-31
        return ">i2"
    return ">u4"                                                # :21-23


class RafSubformatError(RuntimeError):
    """The IDL ``stop`` at `:42`/`:44`, raised instead of halting."""


def read2dbuffer_raf(f: BinaryIO, op: dict) -> RafBuffer2D | Buffer2D:
    """`soda2_read2dbuffer.pro:19-66`, the NCAR RAF branch."""
    pointer = f.tell()                                          # :15
    subformat = int(op.get("subformat", 0))
    if pointer < 157:                                           # :34 skip the xml tag
        f.seek(0)                                               # :35
        s = f.read(1000)                                        # :36-37
        if len(s) < 1000:
            raise EOFError("soda2_read2dbuffer.pro:37 readu of bytarr(1000) "
                           "past end of file -- IDL 'End of file encountered'.")
        pos = s.find(b"</PMS2D>")                               # :38 strpos
        f.seek(pos + 9)                                         # :39 (pos=-1 -> 8)
        if pos == -1:                                           # :40 new identifier, 2011
            pos = s.find(b"</OAP>")                             # :41
            f.seek(pos + 7)                                     # :42
            if subformat != 3:                                  # :43
                raise RafSubformatError(
                    "soda2_read2dbuffer.pro:43 stop: </OAP> file with "
                    f"subformat {subformat} (needs 3) -- leads to bad TAS")
        elif subformat == 3:                                    # :45
            raise RafSubformatError(
                "soda2_read2dbuffer.pro:45 stop: </PMS2D> file with "
                "subformat 3 -- leads to bad TAS")
    img_dt = np.dtype(_raf_image_dtype(op.get("probetype", "")))
    nimg = 4116 - struct.calcsize(_RAF_HEAD)
    size = _fstat_size(f)
    while True:                                                 # :49-55 REPEAT
        if size - f.tell() < 4116:                              # :51
            return _nullbuffer(pointer)
        rec = f.read(4116)                                      # :52 readu; :53 swap_endian
        head = struct.unpack(_RAF_HEAD, rec[:20])
        image = np.frombuffer(rec[20:20 + nimg], dtype=img_dt).astype(
            img_dt.newbyteorder("="))
        probeid = bytes(head[:2]).decode("latin-1")             # :54 string([type, number])
        if probeid == op.get("probeid"):                        # :55
            break
    keys = ("probetype", "probenumber", "hours", "minutes", "seconds", "year",
            "month", "day", "tas", "milliseconds", "overload")
    # Header words are scalars; "image" (an array) joins the same record below.
    a: dict[str, Any] = {k: (np.uint8(v) if i < 2 else np.int16(v))
                         for i, (k, v) in enumerate(zip(keys, head, strict=True))}
    a["image"] = image
    if subformat == 3:                                          # :57 TAS format changed 2011
        tas = a["tas"]
    else:
        tas = np.float32(a["tas"] * np.float32(125.0) / np.float32(255.0))
    time = (int(a["hours"]) * 3600.0 + int(a["minutes"]) * 60.0     # :58 last slice
            + int(a["seconds"]) * 1.0 + int(a["milliseconds"]) / 1000.0)
    time = time + float(np.float32(op.get("timeoffset", np.float32(0.0))))  # :60
    date = julday(int(a["month"]), int(a["day"]), max(int(a["year"]), 1))   # :61 year>1
    overload = np.float32(a["overload"] / np.float32(1000.0))   # :62
    return RafBuffer2D(time=time, image=image, difftime=0, eof=0, tas=tas,
                       pointer=pointer, date=date, overload=overload, a=a)


def read2dbuffer(f: BinaryIO, op: dict) -> Buffer2D | SeaBuffer2D | DmtBuffer2D | RafBuffer2D:
    """Dispatches on `op["format"]`: `'SPEC'` (`:109-117`), `'SEA'`
    (`:69-89`, the CIP route) and `'DMT'` (`:91-107`) are ported.

    Source: ``soda2_read2dbuffer.pro`` (SODA-2); bare line references here are into that file."""
    fmt = op.get("format")
    if fmt == "SEA":
        return read2dbuffer_sea(f, op)
    if fmt == "DMT":
        return read2dbuffer_dmt(f, op)
    if fmt == "RAF":
        return read2dbuffer_raf(f, op)
    if fmt != "SPEC":
        raise NotImplementedError(
            "soda2_read2dbuffer.pro:118-210 (formats TXT/T28/HVPS1995) are "
            "not ported; SPEC, SEA (CIP), DMT and RAF (:19-66) are.")
    return read2dbuffer_spec(f, op)
