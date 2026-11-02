# SPDX-License-Identifier: BSD-3-Clause
"""Write ``dmt_raw_synthetic.cip``: a seeded synthetic DMT CIP/PIP raw file.

Replaces the excluded real fixture (twelve 4112-byte records of a field
example file) for the DMT decode tests. No real bytes: every record is built
here from the layout :mod:`arrayprobe.readers.dmt` documents.

Record layout (4112 bytes): eight little-endian ``uint16`` (year, month, day,
hour, minute, second, millisecond, weekday), then a 4096-byte payload in the
DMT byte-level run-length scheme (``n``: n+1 literal bytes; ``0x80|n``: n+1
zero bytes; ``0x40|n``: n+1 0xFF bytes; a byte with bit 5 set is a marker).
The payload decompresses to: a sync slice (eight 0xAA, the boundary the reader
searches for), then per particle a header slice (the 64-bit CIP word with
slice count, time and particle counter) and its image slices, each particle
after the first preceded by another sync slice, and a trailing sync slice.
The unused tail is filled with 0x20 markers, so the never-read 4096th byte is
inert.

Deterministic (fixed seed): two runs write identical bytes.
``build()`` returns ``(raw_bytes, particles_per_record)``.

Run: ``python tests/data/make_dmt_raw_synthetic.py [out_path]``.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "dmt_raw_synthetic.cip"
SEED = 20261019
N_RECORDS = 12
RECORD_BYTES = 4112
PAYLOAD_BYTES = 4096
SYNC = b"\xAA" * 8


def _header_slice(nslices: int, h: int, m: int, s: int, ms: int, counter: int) -> bytes:
    w = ((nslices & 0x7F) << 57 | (h & 31) << 51 | (m & 63) << 45 | (s & 63) << 39
         | (ms & 1023) << 29 | (counter & 0xFFFF))
    return w.to_bytes(8, "little")


def _image(rng: np.random.Generator, nslices: int) -> bytes:
    """``nslices`` 8-byte slices of a blob (bit = 1 blank, 0 shadowed)."""
    img = np.ones((nslices, 64), dtype=np.uint8)
    c0 = int(rng.integers(6, 58))
    w = int(rng.integers(2, 7))
    for s in range(nslices):
        half = max(1, int(round(w * np.sin(np.pi * (s + 0.5) / nslices))))
        img[s, max(0, c0 - half):min(64, c0 + half)] = 0
    packed = np.packbits(img, axis=1, bitorder="little")
    return packed.tobytes()


def _encode(raw: bytes) -> bytes:
    """DMT run-length encoding: 0x00/0xFF runs, otherwise literal runs (max 32)."""
    out = bytearray()
    i, n = 0, len(raw)
    while i < n:
        b = raw[i]
        j = i
        if b in (0x00, 0xFF):
            while j < n and raw[j] == b and j - i < 32:
                j += 1
            out.append((0x80 if b == 0 else 0x40) | (j - i - 1))
        else:
            while j < n and raw[j] not in (0x00, 0xFF) and j - i < 32:
                j += 1
            out.append(j - i - 1)
            out += raw[i:j]
        i = j
    return bytes(out)


def _record(rng: np.random.Generator, k: int) -> tuple[bytes, int]:
    sec = k  # one record per second from 03:00:00
    n_part = int(rng.integers(3, 7))
    stream = bytearray(SYNC)
    for p in range(n_part):
        if p:
            stream += SYNC
        nsl = int(rng.integers(2, 9))
        hdr = _header_slice(nsl + 1, 3, 0, sec, 100 * p + 7, 100 * k + p)
        body = _image(rng, nsl)
        for i in range(0, len(body), 8):
            assert body[i:i + 8] != SYNC
        assert hdr != SYNC
        stream += hdr + body
    stream += SYNC
    payload = _encode(bytes(stream))
    if len(payload) > PAYLOAD_BYTES - 1:
        raise ValueError(f"record {k}: payload too long ({len(payload)})")
    payload += b"\x20" * (PAYLOAD_BYTES - len(payload))
    head = struct.pack("<8H", 2015, 6, 1, 3, 0, sec, 0, 1)
    return head + payload, n_part


def build() -> tuple[bytes, list[int]]:
    rng = np.random.default_rng(SEED)
    recs, counts = [], []
    for k in range(N_RECORDS):
        r, n = _record(rng, k)
        assert len(r) == RECORD_BYTES
        recs.append(r)
        counts.append(n)
    return b"".join(recs), counts


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else OUT
    raw, counts = build()
    out.write_bytes(raw)
    print(f"{out}: {N_RECORDS} records, {sum(counts)} particles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
