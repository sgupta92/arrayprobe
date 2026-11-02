# SPDX-License-Identifier: BSD-3-Clause
# ruff: noqa: E501  (the GDL script literal and golden paths are long lines by nature)
"""Write ``soda2_sea_cip_fixture.sea``: a tiny synthetic SEA M300 file with DMT
CIP image records, for the SODA-2 CIP GDL banks. No UND bytes.

Deterministic (fixed seed). Layout per SEA buffer: data directories (16 bytes
each: ``tagNumber, dataOffset, numberBytes, samples, bytesPerSample`` UINT,
``type, parameter1..3`` BYTE, ``address`` UINT), ended by tag ``999`` whose
``dataOffset`` is the buffer length; then the payloads. Tags used: ``0`` (the
36-byte time record: two 9-INT ``year, month, day, hh, mm, ss, frac_num,
frac_den, 0`` blocks, start then stop), ``33000`` (the 4098-byte compressed CIP
image), ``32000`` (the 180-byte CIP-1D record).

The compressed images are built by encoding particle images with the DMT
run-length scheme ``decompress_dmt3.pro`` reads (``0x80|n``: n+1 zero bytes,
``0x40|n``: n+1 0xFF bytes, ``n``: n+1 literal bytes), each particle a sync
slice (eight 0xAA) and a header slice, written as literal runs.

Buffers (each exercises a named branch; the bank's case table cites them):

0. 24 particles, consecutive counters, increasing times.
1. 2 particles only (``decompress_dmt3.pro:113``: ``sync_count le 2`` -> null).
2. 12 particles, particle 5's header slice count off by 3 (``good1`` rejects it),
   particle 8's counter repeated (``missed`` = 65535).
3. 10 particles, particle 4's time 0.5 s earlier than particle 3 (``good4``
   rejects both neighbours).
4. a buffer with no image tag (``seaimagepointers.pro:68`` skips it).
5. a buffer whose image tag has 50 bytes (``numberbytes lt 100``, skipped).
6. 16 particles; a literal run in particle 6 overruns the next sync
   (``decompress_dmt3.pro:43-46``: decompression error, revert).
7. 20 particles, start time beyond 320000 (``readseabuffer_caps.pro:38``
   zeroes it: ``soda2_buildindex.pro:42`` drops the buffer).
8. 20 particles, crossing a second boundary.
9-10. trailing buffers (the end-of-file guards at ``seaimagepointers.pro:62,64``).

Run from the repository root: ``.venv/Scripts/python.exe tests/data/make_soda2_sea_cip_fixture.py``.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "soda2_sea_cip_fixture.sea"
RNG = np.random.default_rng(20260915)


def _dir(tag: int, off: int, nbytes: int, p1: int = 0) -> bytes:
    return struct.pack("<HHHHHBBBBH", tag, off, nbytes, 0, 0, 0, p1, 0, 0, 0)


def _header(slice_count: int, dof: int, h: int, m: int, s: int, ms: int, counter: int,
            pc: int) -> bytes:
    w = ((slice_count & 0x7F) << 57 | (dof & 1) << 56 | (h & 31) << 51 | (m & 63) << 45
         | (s & 63) << 39 | (ms & 1023) << 29 | (counter & 8191) << 16 | (pc & 0xFFFF))
    return w.to_bytes(8, "little")


def _encode_bytes(raw: bytes) -> bytes:
    """DMT RLE of a byte string: runs of 0x00/0xFF, else literal runs (max 32)."""
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        b = raw[i]
        if b in (0x00, 0xFF):
            j = i
            while j < n and raw[j] == b and j - i < 32:
                j += 1
            run = j - i
            out.append((0x80 if b == 0 else 0x40) | (run - 1))
            i = j
        else:
            j = i
            while j < n and raw[j] not in (0x00, 0xFF) and j - i < 32:
                j += 1
            run = j - i
            out.append(run - 1)
            out += raw[i:j]
            i = j
    return bytes(out)


def _particle(nslices: int) -> bytes:
    """``nslices`` image slices (8 bytes each; bit 0 = shadowed): a blob."""
    img = np.full((nslices, 64), 1, dtype=np.uint8)   # 1 = blank
    c0 = int(RNG.integers(5, 55))
    w = int(RNG.integers(2, 9))
    for s in range(nslices):
        half = max(1, int(w * np.sin(np.pi * (s + 0.5) / nslices)))
        img[s, max(0, c0 - half): min(64, c0 + half)] = 0
    out = bytearray()
    for s in range(nslices):
        for k in range(8):
            byte = 0
            for b in range(8):
                byte |= int(img[s, 8 * k + b]) << b
            out.append(byte)
    return bytes(out)


def _image_record(particles: list[dict], overrun_at: int | None = None) -> bytes:
    """A 4098-byte compressed buffer from particle dicts."""
    out = bytearray()
    for k, p in enumerate(particles):
        out.append(0x07)
        out += b"\xAA" * 8
        hdr = _header(p["hdr_slices"], p.get("dof", 0), p["h"], p["m"], p["s"], p["ms"],
                      p["counter"], p["pc"])
        out.append(0x07)
        out += hdr
        body = _particle(p["nslices"])
        enc = bytearray(_encode_bytes(body))
        if overrun_at == k:
            # A literal header whose count runs past the next sync position.
            enc += bytes([31]) + bytes(RNG.integers(1, 254, 5, dtype=np.uint8))
        out += enc
    # A trailing sync so the last real particle is decompressed (:39).
    out.append(0x07)
    out += b"\xAA" * 8
    if len(out) > 4098:
        raise ValueError(f"image record too long: {len(out)}")
    out += b"\x20" * (4098 - len(out))   # dummy bytes (:54)
    return bytes(out)


def _particles(n: int, h: int, m: int, s: int, ms0: int, pc0: int, dt_ms: int = 7) -> list[dict]:
    ps = []
    ms = ms0
    for k in range(n):
        nsl = int(RNG.integers(2, 9))
        sec, msec = s + ms // 1000, ms % 1000
        ps.append({"nslices": nsl, "hdr_slices": nsl + 1, "h": h, "m": m, "s": sec,
                   "ms": msec, "counter": int(RNG.integers(0, 8000)), "pc": pc0 + k,
                   "dof": int(k % 3 == 0)})
        ms += dt_ms
    return ps


def _time(h: int, m: int, s: int, num: int, den: int) -> bytes:
    return struct.pack("<9h", 2016, 9, 6, h, m, s, num, den, 0)


def _buffer(entries: list[tuple[int, bytes]]) -> bytes:
    ndir = len(entries) + 1
    off = 16 * ndir
    dirs = bytearray()
    payload = bytearray()
    for tag, data in entries:
        dirs += _dir(tag, off + len(payload), len(data))
        payload += data
    total = off + len(payload)
    dirs += _dir(999, total, 0)
    return bytes(dirs + payload)


def _cip1d(pc: int, cip1d_time: bool = True) -> bytes:
    rec = bytearray(180)
    counts = RNG.integers(0, 40, 62).astype("<i2").tobytes()
    rec[6:6 + 124] = counts
    hk = RNG.integers(100, 3000, 16).astype("<i2").tobytes()
    rec[134:134 + 32] = hk
    struct.pack_into("<H", rec, 166, pc & 0xFFFF)
    # secmsec (168) and hourmin (170), `readseabuffer_caps.pro:40-41`: derived
    # from `pc` with no RNG draw, so no other fixture byte moves. Seconds of 32
    # and up set the INT's sign bit, exercising the negative-INT mask path.
    # ``cip1d_time=False`` leaves both zero: the file the Octave edge-case
    # golden (`s6_sea_edge_octave_golden.npz`) was measured on.
    if not cip1d_time:
        return bytes(rec)
    struct.pack_into("<H", rec, 168, ((pc % 60) << 10) | (pc % 1000))
    struct.pack_into("<h", rec, 170, (7 << 6) | 10)
    return bytes(rec)


def build(cip1d_time: bool = True) -> bytes:
    """The fixture; ``cip1d_time=False`` builds the pre-2026-10-04 zero-time file."""
    global RNG
    RNG = np.random.default_rng(20260915)  # each call reproduces the same draws
    bufs = []
    h, m = 7, 10
    specs = [
        ("b0", _particles(24, h, m, 5, 100, 1000)),
        ("b1", _particles(2, h, m, 6, 100, 1024)),
        ("b2", None),
        ("b3", None),
        ("b4", "noimage"),
        ("b5", "short"),
        ("b6", None),
        ("b7", _particles(20, h, m, 12, 0, 1200)),
        ("b8", _particles(20, h, m, 13, 900, 1300, dt_ms=11)),
    ]
    b2 = _particles(12, h, m, 7, 0, 1030)
    b2[5]["hdr_slices"] += 3
    b2[8]["pc"] = b2[7]["pc"]
    b3 = _particles(10, h, m, 8, 0, 1050)
    b3[4]["s"], b3[4]["ms"] = b3[3]["s"], max(0, b3[3]["ms"] - 500)
    if b3[3]["ms"] < 500:
        b3[4]["s"] = b3[3]["s"] - 1
        b3[4]["ms"] = b3[3]["ms"] + 500
    b6 = _particles(16, h, m, 10, 0, 1100)
    for name, parts in specs:
        sec = {"b0": 5, "b1": 6, "b2": 7, "b3": 8, "b4": 9, "b5": 9, "b6": 10, "b7": 12,
               "b8": 13}[name]
        start = _time(h, m, sec, 0, 100)
        stop = _time(h, m, sec, 90, 100)
        if name == "b7":
            start = struct.pack("<9h", 2016, 9, 6, 33, m, sec, 0, 100, 0)  # hh=33 -> >320000
        tbytes = start + stop
        if name == "b2":
            img = _image_record(b2)
        elif name == "b3":
            img = _image_record(b3)
        elif name == "b6":
            img = _image_record(b6, overrun_at=6)
        elif parts == "noimage":
            bufs.append(_buffer([(0, tbytes), (32000, _cip1d(1090, cip1d_time))]))
            continue
        elif parts == "short":
            bufs.append(_buffer([(0, tbytes), (33000, b"\x20" * 50)]))
            continue
        else:
            img = _image_record(parts)
        bufs.append(_buffer([(0, tbytes), (33000, img),
                            (32000, _cip1d(1000 + len(bufs), cip1d_time))]))
    # Two trailing buffers (end-of-file guards).
    for k in range(2):
        tb = _time(h, m, 20 + k, 0, 100) + _time(h, m, 20 + k, 50, 100)
        bufs.append(_buffer([(0, tb), (33000, _image_record(_particles(6, h, m, 20 + k, 0, 1400 + 10 * k)))]))
    return b"".join(bufs)


if __name__ == "__main__":
    data = build()
    OUT.write_bytes(data)
    print(f"wrote {OUT} ({len(data)} bytes)")
