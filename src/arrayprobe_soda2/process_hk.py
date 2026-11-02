# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""`spec_process_hk.pro`, versions 1 and 2, and `spec_index_hk.pro`.
Version 1: (`:1-13`, `:26-102`, `:169-184`). **Version 2** (3VCPI/Hawkeye/HVPS4/
Fast2DS, `:14-25`, `:104-167`) and the index it needs, `spec_index_hk.pro`
(whole file), were added on a synthetic 2DSCPIHK file whose
layout is derived from `spec_index_hk.pro:11,44-52` alone -- no real
3VCPI/Hawkeye/HVPS-4 file exists here, so the byte layout is the source's,
and the channel meanings are the source's own indexing.

Vendored sources: `SODA2/abansemer-soda2-afcea15/spec_process_hk.pro`,
`spec_index_hk.pro`. Banks: version 1, `gdl_oracle/run_soda2_preloop_bank.py`
(golden `tests/data/gdl_soda2_preloop_golden.json`); version 2,
`gdl_oracle/run_soda2_spec_read_hk_bank.py --v2` (golden
`tests/data/gdl_soda2_spec_read_hk_v2_golden.json`).
"""
from __future__ import annotations

import copy
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import DTypeLike

from .buildindex import GenericIndex, buildindex
from .spec_index import SpecIndex, julday
from .spec_read_hk import spec_read_hk
from .timeconv import soda2_parsedate
from .update_op import update_op


def f32_via_f64(fn: Callable[..., Any], *args: Any) -> np.ndarray:
    """IDL FLOAT transcendental (``alog``, ``exp``, ``sin`` ...): compute ``fn``
    in float64 and round once to float32. GDL's FLOAT kernels are correctly
    rounded; numpy's float32 ``log``/``exp``/``sin``/``cos``/``log10``/``power``
    are not.
    Use only where the IDL operand is FLOAT."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        return np.asarray(fn(*(np.asarray(a, dtype=np.float64) for a in args))).astype(np.float32)


_TEMPID = [
    "horiz arm tx", "horiz arm rx", "vert arm tx", "vert arm rx",
    "horiz tip tx", "horiz tip rx", "rear optical bridge", "DSP board",
    "forward vessel", "horiz laser", "vert laser", "front plate",
    "power supply",
]


@dataclass
class HouseData:
    """The ``data`` structure ``spec_process_hk.pro:183-184`` (SODA-2) builds, one field per
    IDL tag."""
    op: dict
    time: np.ndarray
    nb: np.ndarray
    arrayid: str
    tas: np.ndarray
    diodes: list[int]
    volts: np.ndarray
    canpressure: np.ndarray
    power: np.ndarray
    tempid: list[str]
    temp: np.ndarray
    laservolts: np.ndarray
    overloads: np.ndarray
    counts: np.ndarray


def _idiv(a: float, b: float) -> int:
    """IDL LONG-cast division truncates toward zero (`:32`'s `long(...)`,
    `:62`'s `long(...)` -- trap T2)."""
    q = a / b
    return int(q) if q >= 0 else -int(-q)


def _interpol(v: np.ndarray, x: np.ndarray, xout: float) -> float:
    """IDL `INTERPOL`'s documented linear-case formula, evaluated at one
    `xout` against the bracketing pair of the (sorted) `x`/`v` arrays."""
    i = int(np.searchsorted(x, xout)) - 1
    i = max(0, min(i, len(x) - 2))
    return float(v[i] + (xout - x[i]) * (v[i + 1] - v[i]) / (x[i + 1] - x[i]))


class ProcessHKStop(RuntimeError):
    """An IDL ``stop`` or halt inside ``spec_process_hk``, naming the line."""


@dataclass
class SpecIndexHK:
    """``spec_index_hk``'s return struct (`spec_index_hk.pro:68`). Dtypes
    are the bank's measured ``size(/tname)``: LONG, DOUBLE, LONG, LONG64,
    LONG64."""

    date: np.ndarray       # int32
    bufftime: np.ndarray   # float64
    pointer: np.ndarray    # int32 -- a LONG index array (`spec_index_hk.pro:25`)
    hkp: np.ndarray        # int64; [0] when the file holds no HK buffer
    maskp: np.ndarray      # int64; [0] when it holds no mask buffer
    buffsize: int = 0      # `:67` -- disables `spec_readint`'s framing
    error: int = 0


def spec_index_hk(fn: str) -> SpecIndexHK:
    """``spec_index_hk.pro`` (whole file, 69 lines) -- index a
    3VCPI/Hawkeye ``2DSCPIHK`` housekeeping file.

    `:11` the buffer header is eight INTs and a UINT ``buffertype`` (18
    bytes). `:30` **every** 2-byte offset is tried as a header, and `:33-35`
    accept one whose year equals the first header's and whose month and day
    equal it or it plus one -- so a payload word sequence that happens to
    read as a matching date is indexed as a buffer (no framing check).
    `:30`'s bound ``(f.size-headersize)/2 - 1`` leaves the last 2-byte
    position a header could start at unscanned. `:44-52` an HK buffer
    (``buffertype`` 18507) or mask buffer (19787) is recorded AT its
    ``buffertype`` word (``ip*2 + headersize - 2``). `:55-59` each list is
    trimmed to ``[0:(n-1)>0]``: **with no HK buffer at all, ``hkp`` is
    ``[0]``** and ``spec_process_hk`` reads a phantom record from byte 0
    (bank ``phk_nohk``). `:24` ``numbuffs = 100000`` is a hard cap (IDL
    halts on the 100001st match; raised here)."""
    with open(fn, "rb") as fh:
        raw = fh.read()
    size = len(raw)
    headersize = 18
    if size < headersize:
        raise ProcessHKStop("spec_index_hk.pro:16: readu past end of file")
    words = np.frombuffer(raw[: size - (size % 2)], dtype="<i2").astype(np.int64)
    first = words[0:9]
    n_ip = (size - headersize) // 2  # `:30` -- ip = 0 .. n_ip-1
    k = np.arange(max(n_ip, 0))
    year, month, day = words[k], words[k + 1], words[k + 3]
    ok = ((year == first[0])
          & ((month == first[1]) | (month == first[1] + 1))
          & ((day == first[3]) | (day == first[3] + 1)))
    hits = k[ok]
    numbuffs = 100000
    if hits.size > numbuffs:
        raise ProcessHKStop("spec_index_hk.pro:37: more than numbuffs=100000 "
                            "header matches -- subscript out of range")
    hour, minute = words[hits + 4], words[hits + 5]
    second, ms = words[hits + 6], words[hits + 7]
    btype = words[hits + 8] & 0xFFFF
    bufftime = (hour * 3600.0 + minute * 60.0) + second + ms / 1000.0  # `:38`
    date = np.array([julday(int(mo), int(d), int(yr)) for mo, d, yr in
                     zip(words[hits + 1], words[hits + 3], words[hits], strict=True)],
                    dtype=np.int32)
    hkp = (hits[btype == 18507] * 2 + headersize - 2).astype(np.int64)
    maskp = (hits[btype == 19787] * 2 + headersize - 2).astype(np.int64)

    def _trim(a: np.ndarray, dtype: DTypeLike) -> np.ndarray:  # `:55-59`
        return a.astype(dtype) if a.size else np.zeros(1, dtype=dtype)

    return SpecIndexHK(date=_trim(date, np.int32), bufftime=_trim(bufftime, np.float64),
                       pointer=_trim(hits * 2, np.int32), hkp=_trim(hkp, np.int64),
                       maskp=_trim(maskp, np.int64))


#: `spec_process_hk.pro:115-151`, version 2: probeid -> (volts columns,
#: overloads, laservolts, counts), each an `hkraw` column.
_V2_CASE: dict[str, tuple[list[int], int, int, int]] = {
    "V": (list(range(36, 43)), 67, 30, 58),
    "H": (list(range(44, 51)), 66, 31, 57),
    "V50": (list(range(2, 9)), 67, 30, 60),
    "V150": (list(range(36, 43)), 67, 30, 58),
    "H50": ([24, 25, 26, 27, 30, 31, 32], 66, 30, 59),
    "H150": (list(range(44, 51)), 66, 30, 57),
}

_V2_TEMPID = [
    "fwd sample tube", "central sample tube", "nose cone", "vertical laser",
    "horizontal laser", "vertical optics", "horizontal optics",
    "vertical mirror", "horizontal mirror",
]


def _v2_temperature(tempraw: np.ndarray) -> np.ndarray:
    """`:162-163` -- DOUBLE throughout, FLOAT-literal coefficients widened;
    ``^3.`` and ``^(-1.)`` are C ``pow`` calls, evaluated element by element
    with :func:`math.pow` (numpy's ``**`` may take a multiply fast path)."""
    import math

    a = float(np.float32(1.1117024e-3))
    b = float(np.float32(237.02702e-6))
    c = float(np.float32(75.78814e-9))
    k0 = float(np.float32(6.5536e9))
    t0 = float(np.float32(-273.15))
    out = np.empty(tempraw.shape, dtype=np.float64)
    flat_in = tempraw.astype(np.float64).ravel()
    flat_out = out.ravel()
    for i, v in enumerate(flat_in):
        with np.errstate(divide="ignore", invalid="ignore"):
            rt = float(np.float64(k0) * (1.0 - np.float64(v) / 65536.0) / (5.0 * np.float64(v)))
        lr = math.log(rt) if rt > 0 else (math.inf if rt == math.inf else math.nan)
        if math.isnan(lr):
            flat_out[i] = math.nan
            continue
        inner = a + b * lr + c * (math.pow(lr, 3.0) if math.isfinite(lr) else lr)
        flat_out[i] = t0 + (math.pow(inner, -1.0) if inner != math.inf else 0.0)
    return out


def process_hk(op: dict, y: SpecIndex | None = None) -> HouseData:
    """`spec_process_hk`, both versions. `op` goes through `update_op`
    first (`:9`). ``op.subformat != 0`` is version 2 (3VCPI/Hawkeye/HVPS4/
    Fast2DS): the HK data come from ``op.fn + 'HK'`` indexed by
    :func:`spec_index_hk`, and ``y`` is ignored, as the IDL ignores it.

    Source: ``spec_process_hk.pro`` (SODA-2); bare line references here are into that file."""
    op = update_op(op)
    version = 2 if int(op.get("subformat", 0)) != 0 else 1

    fn = op["fn"]
    fn_list = list(fn) if isinstance(fn, (list, tuple)) else [fn]
    hkindex: SpecIndex | SpecIndexHK
    if version == 2:
        # :16-25.
        fn0 = str(fn_list[0]) + "HK"
        if not os.path.exists(fn0):
            raise ProcessHKStop(
                f"spec_process_hk.pro:17-20: stop -- Housekeeping file not "
                f"found: {fn0}")
        hkindex = spec_index_hk(fn0)
        # :25 -- DOUBLE + the caller's own type (FLOAT from update_op).
        hkindex.bufftime = hkindex.bufftime + np.float64(op["timeoffset"])
    if len(fn_list) > 1:
        raise ValueError(
            "spec_process_hk.pro:42 stop,'Multiple SPEC raw files not "
            "supported, concatenate first'")
    if version == 1:
        fn0 = fn_list[0]
        if y is None:
            built = buildindex(fn0, op)
            # buildindex's return type is SpecIndex | GenericIndex in general
            # (it also serves the SEA/CIP generic walk), but this function is
            # only ever reached for op["format"] == "SPEC" -- the same
            # invariant process_2d.py:837 asserts at its own call site -- so
            # buildindex(fn0, op) here always takes its SPEC branch and never
            # returns GenericIndex. Asserted, not just declared, so a caller
            # that broke the invariant would fail loudly here rather than
            # deeper in with an AttributeError.
            assert not isinstance(built, GenericIndex)
            hkindex = built
        else:
            # :29 `hkindex=y` copies the IDL struct; the caller's `y` is not
            # mutated by anything below. Deep-copy so this port cannot mutate
            # it either (hk_y_unmutated).
            hkindex = copy.deepcopy(y)

    starttime = float(op["starttime"])
    stoptime = float(op["stoptime"])
    rate = float(op["rate"])
    numrecords = _idiv(stoptime - starttime, rate) + 1  # :32
    time = starttime + rate * np.arange(numrecords, dtype=np.float64)  # :33

    numfields = 83 if version == 2 else 49  # :34-35
    hk = np.zeros((numrecords, numfields), dtype=np.float32)
    hkraw = np.zeros((numrecords, numfields), dtype=np.float32)
    tas = np.zeros(numrecords, dtype=np.float32)
    nb = np.zeros(numrecords, dtype=np.float32)

    startdate = soda2_parsedate(op["date"]).julday  # :43
    if abs(int(hkindex.date[0]) - startdate) > 5:  # :44
        startdate = int(hkindex.date[0])  # :45
    hkindex.bufftime = hkindex.bufftime + 86400 * (hkindex.date - startdate)  # :49

    with open(fn0, "rb") as f:
        for hkp_i in hkindex.hkp:  # :57
            ge = hkindex.pointer < hkp_i
            buffind = int(np.max(np.where(ge)[0])) if np.any(ge) else -1
            buffind = max(buffind, 0)  # :59 `> 0`
            bufftime = float(hkindex.bufftime[buffind])
            itime = _idiv(bufftime - starttime, rate)  # :62, T2

            if 0 <= itime < numrecords:
                h = spec_read_hk(f, int(hkp_i), int(hkindex.buffsize), version=version)
                hk[itime, :] = hk[itime, :] + h.x
                # :78 adds `h.raw` into the `hkraw` row for `itime` -- h.raw is the
                # full 53-word record while hkraw's row is 49 wide (`hk`/
                # `hkraw` are both declared `fltarr(numrecords, numfields)`,
                # `numfields=49` for version 1). IDL's binary operators
                # silently truncate the larger array-operand to the
                # smaller's element count rather than erroring; reproduced
                # here by truncating `h.raw` to the first 49 words.
                hkraw[itime, :] = hkraw[itime, :] + h.raw[:numfields]
                tas[itime] = tas[itime] + h.tas
                nb[itime] = nb[itime] + 1

    probeid = str(op.get("probeid", "A0"))
    if version == 2:
        return _process_hk_v2(op, probeid, time, nb, tas, hk, hkraw, numrecords)

    # :75-81 -- averages; columns 33-35 and 40-48 stay sums.
    for i in range(numrecords):
        n = max(float(nb[i]), 1.0)
        hk[i, 0:33] = hk[i, 0:33] / n
        hk[i, 36:40] = hk[i, 36:40] / n
        tas[i] = tas[i] / n

    if probeid == "V":
        volts = hk[:, [4, 29, 30, 5, 31, 32, 6]]
        overloads = hk[:, 44]
        laservolts = hk[:, 37]
        counts = hk[:, 33]
    else:
        volts = hk[:, [1, 25, 26, 2, 27, 28, 3]]
        overloads = hk[:, 43]
        laservolts = hk[:, 36]
        counts = hk[:, 34]

    canpressure = hk[:, 24] * np.float32(68.9476)
    power = hk[:, [7, 8, 22, 23]]
    temperature = hk[:, 9:22]  # IDL 9:21 inclusive -> Python 9:22
    tempid = list(_TEMPID)

    _fill_tas(tas, time, numrecords)
    diodes = [0, 21, 42, 64, 85, 106, 127]
    return HouseData(op=op, time=time, nb=nb, arrayid=probeid, tas=tas,
                      diodes=diodes, volts=volts, canpressure=canpressure,
                      power=power, tempid=tempid, temp=temperature,
                      laservolts=laservolts, overloads=overloads,
                      counts=counts)


def _fill_tas(tas: np.ndarray, time: np.ndarray, numrecords: int) -> None:
    """:170-175 -- TAS gap fill, in place."""
    good = np.where(tas > 0)[0]
    if good.size:
        firstgood, lastgood = int(good.min()), int(good.max())
        idx = np.arange(numrecords)
        bad = np.where((tas == 0) & (idx > firstgood) & (idx < lastgood))[0]
        for b in bad:
            tas[b] = np.float32(_interpol(tas[good], time[good], float(time[b])))


def _process_hk_v2(op: dict, probeid: str, time: np.ndarray, nb: np.ndarray,
                   tas: np.ndarray, hk: np.ndarray, hkraw: np.ndarray,
                   numrecords: int) -> HouseData:
    """`:104-167`. **Every output is built from ``hkraw``, which is never
    averaged**: `:106-110` divide ``hk[i,2:53]`` by ``nb`` and nothing below
    reads ``hk`` again, so a record holding two HK buffers reports the
    *sum* of their volts, currents, counts, pressure and thermistor words --
    and a temperature computed from a summed raw word (bank ``phk_*``,
    ``NB`` = 2 in record 0). `:115` the CASE has no ELSE: a ``probeid``
    outside V/H/V50/V150/H50/H150 -- including ``update_op``'s own default
    ``'A0'`` -- halts ("CASE statement found no match", bank
    ``phk_A0_3VCPI``)."""
    for i in range(numrecords):  # :106-110
        n = max(float(nb[i]), 1.0)
        hk[i, 2:54] = hk[i, 2:54] / n
        tas[i] = tas[i] / n

    if probeid not in _V2_CASE:
        raise ProcessHKStop(
            f"spec_process_hk.pro:115: CASE statement found no match "
            f"(probeid={probeid!r})")
    vcols, ocol, lcol, ccol = _V2_CASE[probeid]
    f1 = np.float32(0.00244140625)  # :113
    volts = hkraw[:, vcols] * f1
    overloads = hkraw[:, ocol].copy()
    laservolts = hkraw[:, lcol].copy()
    counts = hkraw[:, ccol].copy()

    if str(op.get("probetype", "")) == "HVPS4":  # :157-161
        tempraw = hkraw[:, 9:22]
        tempid = list(_TEMPID)
    else:  # :154-156
        tempraw = hkraw[:, [2, 5, 7, 13, 14, 17, 19, 20, 21]]
        tempid = list(_V2_TEMPID)
    temperature = _v2_temperature(tempraw)

    power = hkraw[:, 34:36].copy()  # :165
    # :166 -- FLOAT column times FLOAT literals: three float32 roundings.
    canpressure = ((hkraw[:, 29] * np.float32(0.00572205)) - np.float32(3.75)) \
        * np.float32(68.9476)

    _fill_tas(tas, time, numrecords)
    diodes = [0, 21, 42, 64, 85, 106, 127]
    return HouseData(op=op, time=time, nb=nb, arrayid=probeid, tas=tas,
                      diodes=diodes, volts=volts, canpressure=canpressure,
                      power=power, tempid=tempid, temp=temperature,
                      laservolts=laservolts, overloads=overloads,
                      counts=counts)


def _idl_round(x: float) -> int:
    """IDL ``round``: half away from zero, to LONG."""
    return int(np.sign(x) * np.floor(abs(x) + 0.5))


def process_cip1d_sea(op: dict) -> dict:
    """``process_cip1d_sea.pro`` on the ``/nowrite`` path: returns ``data``.

    Bug-for-bug: the first-line REPEAT switches file on any EOF, the main
    WHILE only on an in-range record; a stamp earlier than ``starttime``
    gains +240000.0 (the midnight fix, which a zero stamp also triggers);
    a negative count zeroes all 62 bins; ``tas`` starts NaN and is
    overwritten for every record. Arrays are returned in IDL index order
    (record first); the arithmetic is FLOAT wherever the IDL is.
    """
    from .sea import SeaEOF, idl_sfm, readseabuffer_caps

    f32 = np.float32
    starttime = int(op["starttime"])
    stoptime: float = int(op["stoptime"])
    rate = int(op["rate"])
    if stoptime < starttime:
        stoptime = stoptime + 86400.0
    num = int((stoptime - starttime) // rate + 1)
    tag = int(np.atleast_1d(np.asarray(op["seatag"]))[1])
    timeoffset = float(op.get("timeoffset", 0.0))

    res = f32(op["res"])
    endbins = (res * (np.arange(63, dtype=f32) + f32(1)) + res / f32(2.0)).astype(f32)
    numbins = endbins.size - 1
    midbins = (endbins[0:numbins] + endbins[1:]).astype(np.float64) / 2.0
    binwidth = (endbins[1:] - endbins[0:numbins]).astype(f32)

    spec = np.zeros((num, numbins), f32)
    hk = np.zeros((num, 16), f32)
    nb = np.zeros(num, np.int32)
    endreject = np.zeros(num, np.int32)
    oversizereject = np.zeros(num, np.int32)
    dofreject = np.zeros(num, np.int32)
    particlecounter = np.zeros(num, np.int32)
    time = starttime + rate * np.arange(num, dtype=np.float64)

    fns = list(np.atleast_1d(np.asarray(op["fn"])))
    filenum = 0
    fh = open(str(fns[0]), "rb")

    def _read() -> tuple[object, float]:
        a = readseabuffer_caps(fh, tag=tag, probetype="CIP1D")
        if isinstance(a, SeaEOF):
            return a, float(int(a.starttime + timeoffset))
        return a, float(a.starttime) + timeoffset

    try:
        while True:                                     # REPEAT
            a, st = _read()
            if isinstance(a, SeaEOF):
                fh.close()
                filenum += 1
                fh = open(str(fns[filenum]), "rb")
            if idl_sfm(st) >= starttime:
                break
        while _idl_round(idl_sfm(st)) <= stoptime:
            i = (_idl_round(idl_sfm(st)) - starttime) // rate
            if 0 <= i < num:
                nb[i] += 1
                img = a.image                           # type: ignore[attr-defined]
                count = img["count"][0].copy()
                if count.min() < 0:
                    count[:] = 0
                spec[i, :] += count.astype(f32)
                hk[i, :] += img["housekeeping"][0].astype(f32)
                endreject[i] += int(img["endreject"][0])
                oversizereject[i] += int(img["oversizereject"][0])
                dofreject[i] += int(img["dofreject"][0])
                particlecounter[i] += int(img["particlecounter"][0])
                if isinstance(a, SeaEOF):
                    fh.close()
                    filenum += 1
                    fh = open(str(fns[filenum]), "rb")
            a, st = _read()
            if idl_sfm(st) < starttime:
                st = st + 240000.0
                if isinstance(a, SeaEOF):
                    st = float(int(st))
    finally:
        fh.close()

    nb = np.maximum(nb, 1)
    tas = np.full(num, np.nan, f32)
    for i in range(num):
        hk[i, :] = (hk[i, :] / f32(nb[i])).astype(f32)
        temp = (hk[i, 13] - f32(1024)) * f32(0.048828125)
        cp, cv, R, rcv = f32(0.24), f32(0.171), f32(0.0668557), f32(1.0)
        difprs = f32(68.9476) * f32(5) * hk[i, 3] / f32(4095)
        totprs = f32(68.9476) * f32(15) * hk[i, 4] / f32(4095)
        Tm = temp + f32(273.16)
        if difprs > 1 and totprs > 10:
            xmach = np.sqrt(f32(2) * (cv / R) * ((difprs / totprs + f32(1)) ** (R / cp) - f32(1)))
            Ta = Tm / (f32(1) + (rcv * (xmach * xmach)) * (cp / cv - f32(1)) / f32(2))
            tas[i] = xmach * f32(20.06) * np.sqrt(Ta)
        else:
            tas[i] = 0

    with np.errstate(divide="ignore", invalid="ignore"):
        volts = (hk[:, 0:3] * f32(20.0) / f32(4095)).astype(f32)
        dsp_temp = ((hk[:, 7] * f32(10.0) / f32(4095) - f32(1.49)) / f32(5e-3)) + f32(25)
        ambient_temp = (hk[:, 13] - f32(1024)) * f32(0.048828125)
        Rt = ((f32(4095) / hk[:, 10:13]) - f32(1)) * f32(15)
        # IDL's float alog is the C library's correctly rounded logf; numpy's
        # float32 log is a SIMD approximation one ulp off at some inputs
        # (record 10 of the golden window), so take the float64 log and round.
        lr = f32_via_f64(np.log, Rt)
        optional_temps = f32(1.0) / (f32(1.114e-3) + f32(236.43e-6) * lr
                                     + f32(74.03e-9) * (lr * (lr * lr))) - f32(273.3)
    alltemps = np.column_stack([dsp_temp, ambient_temp, optional_temps]).astype(f32)

    return {"spec1d": spec, "midbins": midbins, "time": time, "endbins": endbins,
            "binwidth": binwidth, "tas_pitot": tas,
            "pres": (f32(68.9476) * f32(15) * hk[:, 4] / f32(4095)).astype(f32),
            "diodes": np.array([1, 64, 32], np.int16), "volts": volts,
            "tempid": ["DSP", "Ambient", "Option1", "Option2", "Option3"],
            "temp": alltemps, "laser_current": (hk[:, 14] * f32(0.19536)).astype(f32),
            "laser_power": (hk[:, 15] * f32(0.407)).astype(f32), "dofreject": dofreject,
            "endreject": endreject, "oversizereject": oversizereject,
            "particlecounter": particlecounter, "op": op}
