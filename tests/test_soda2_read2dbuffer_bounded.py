# SPDX-License-Identifier: BSD-3-Clause
"""``read2dbuffer_spec``'s bounded EOF probe answers exactly as the unbounded one did.

A 2026-09-14 measurement found ``tail = f.read()`` at ``read2dbuffer.py:41`` reading
the whole remainder of the raw file on every buffer -- 7.3 s per buffer on a 622 MB
UND file -- where only ``len(tail)`` in {0, 1-15, >= 16} is ever used. The probe is
now ``f.read(16)``. Space: the port (speed that moves no written byte).

Two sides from two places: the port's function, and a verbatim copy of the pre-fix
body frozen below as the oracle. Both run at every buffer boundary of a synthetic
multi-buffer SPEC file, at every partial-header tail (1-15 bytes left) and at EOF,
and must agree on every ``Buffer2D`` field and dtype, on the error raised and its
message, and on where the file is left. IDL's semantics (``soda2_read2dbuffer.pro``
``:15-17``: ``IF eof(lun) THEN return, nullbuffer``, then ``:110``'s ``readu`` of
the 8-word header) are what both encode: EOF only exactly at end-of-file, a partial
header an error.
"""

from __future__ import annotations

import io
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2 import read2dbuffer
from arrayprobe_soda2.read2dbuffer import Buffer2D
from arrayprobe_soda2.spec_index import _read_header, julday

BUFFER_BYTES = 4114  # 8-word header + 2048 image words + the 2-byte checksum word


def _unbounded_oracle(f, op) -> Buffer2D:
    """``read2dbuffer_spec`` as it stood before 2026-09-15 -- verbatim, the oracle."""
    pointer = f.tell()  # :15
    start = f.tell()
    tail = f.read()
    f.seek(start)
    if len(tail) == 0:
        return Buffer2D(image=0, tas=np.int16(0), time=np.int16(0),
                        difftime=0.0, eof=1, pointer=pointer, overload=0,
                        date=0)
    if len(tail) < 16:
        raise EOFError(
            "soda2_read2dbuffer.pro:110 readu on a partial 8-word header "
            f"({len(tail)} bytes remain) -- IDL 'End of file encountered'.")
    year, month, _dummy, day, hour, minute, second, millisecond = _read_header(f)
    time = hour * 3600.0 + minute * 60.0 + second * 1.0 + millisecond / 1000.0
    date = julday(month, day, year) if year > 0 else 0
    fixedtas = op.get("fixedtas", np.float32(0.0))
    tas = float(fixedtas) if float(fixedtas) > 0 else 100.0
    offset = float(op.get("timeoffset", np.float32(0.0)))
    return Buffer2D(time=time + offset, image=0, difftime=0.0, eof=0,
                    tas=np.float32(tas), pointer=pointer, date=date, overload=0)


def _synthetic_file(path: Path, n_buffers: int, tail_bytes: int) -> None:
    rng = np.random.default_rng(20260915)
    with open(path, "wb") as out:
        for k in range(n_buffers):
            header = struct.pack("<8h", 2016, 9, 0, 14, 7 + k // 3600,
                                 (k // 60) % 60, k % 60, (37 * k) % 1000)
            body = rng.integers(0, 256, size=BUFFER_BYTES - 16, dtype=np.uint8).tobytes()
            out.write(header + body)
        out.write(b"\x07" * tail_bytes)


def _outcome(fn, f, op):
    try:
        b = fn(f, op)
        fields = {k: (repr(v), type(v).__name__) for k, v in vars(b).items()}
        return ("ok", fields, f.tell())
    except EOFError as exc:
        return ("EOFError", str(exc), f.tell())


class _CountingReader(io.RawIOBase):
    """Counts bytes handed out, to pin the probe as bounded."""

    def __init__(self, raw):
        self.raw, self.served = raw, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.raw.tell()

    def seek(self, pos, whence=0):
        return self.raw.seek(pos, whence)

    def read(self, n=-1):
        data = self.raw.read(n)
        self.served += len(data)
        return data


class BoundedProbeIsIdentical(unittest.TestCase):
    OPS = ({"format": "SPEC"},
           {"format": "SPEC", "fixedtas": np.float32(150.0), "timeoffset": np.float32(0.1)})

    def test_every_buffer_partial_tail_and_eof_agree_with_the_unbounded_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            for tail in (0, 1, 7, 15, 16, 17):
                path = Path(tmp) / f"syn_{tail}.2DS"
                _synthetic_file(path, n_buffers=12, tail_bytes=tail)
                size = path.stat().st_size
                positions = [k * BUFFER_BYTES for k in range(12)]
                positions += [size - r for r in range(0, 17)]  # EOF and every partial tail
                for op in self.OPS:
                    for pos in positions:
                        with self.subTest(tail=tail, pos=pos, op=op), \
                                open(path, "rb") as a, open(path, "rb") as b:
                            a.seek(pos)
                            b.seek(pos)
                            self.assertEqual(
                                _outcome(read2dbuffer.read2dbuffer_spec, a, op),
                                _outcome(_unbounded_oracle, b, op))

    def test_the_three_eof_answers_are_each_reached(self):
        """The comparison above means something only if all three branches fire."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "syn.2DS"
            _synthetic_file(path, n_buffers=2, tail_bytes=5)
            size = path.stat().st_size
            seen = set()
            with open(path, "rb") as f:
                for pos in (0, size - 5, size):
                    f.seek(pos)
                    kind, detail, _ = _outcome(read2dbuffer.read2dbuffer_spec, f,
                                               {"format": "SPEC"})
                    seen.add(kind if kind == "EOFError" else f"eof={detail['eof'][0]}")
        self.assertEqual(seen, {"eof=0", "eof=1", "EOFError"})

    def test_the_probe_reads_a_bounded_number_of_bytes(self):
        """The speed property itself: reverting to ``f.read()`` makes this fail."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.2DS"
            _synthetic_file(path, n_buffers=40, tail_bytes=0)
            with open(path, "rb", buffering=0) as raw:
                counter = _CountingReader(raw)
                read2dbuffer.read2dbuffer_spec(counter, {"format": "SPEC"})
                self.assertLessEqual(counter.served, 32)  # 16-byte probe + 16-byte header
                counter.served = 0
                raw.seek(0)
                _unbounded_oracle(counter, {"format": "SPEC"})
                self.assertGreater(counter.served, 30 * BUFFER_BYTES,
                                   "the oracle must be the unbounded read it claims to be")


if __name__ == "__main__":
    unittest.main()
