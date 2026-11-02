# SPDX-License-Identifier: BSD-3-Clause
"""The OAP 2D-S exporter, round-tripped through the independent OAP reader."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_uiops.export_oap import (
    BOUNDARY_WORD,
    ExportParticle,
    OapStamp,
    encode_slice,
    particles_from_canvas,
    write_oap_2ds,
)
from arrayprobe_uiops.oap_read import OAP_RECORD_BYTES, read_oap_2ds, split_oap_xml

STAMP = OapStamp(2016, 9, 6, 12, 34, 56, msec=250, tas=150)


def _particles(n: int, seed: int = 7) -> list[ExportParticle]:
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        n_s = int(rng.integers(1, 60))
        shaded = (rng.random((n_s, 128)) < 0.3).astype(np.uint8)
        timing = int(rng.integers(0, 2**32))
        out.append(ExportParticle(shaded, timing, OapStamp(2016, 9, 6, 12, 34, k % 60)))
    return out


class TestRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_own_convention_bits_and_timing_exact(self) -> None:
        parts = _particles(40)  # ~1200 slices: spans several records
        path = self.dir / "own.2d"
        rep = write_oap_2ds(parts, path, timing_convention="own")
        xml, headers, got = read_oap_2ds(path)
        self.assertGreater(rep.records, 1)
        self.assertEqual(len(headers), rep.records)
        self.assertEqual(len(got), len(parts))
        for p, g in zip(parts, got, strict=True):
            self.assertTrue(np.array_equal(g.shaded, p.shaded))
            self.assertEqual(g.timing, p.timing)

    def test_translate2ds_convention_sync_carries_next_time(self) -> None:
        parts = _particles(10, seed=3)
        path = self.dir / "t2ds.2d"
        write_oap_2ds(parts, path)
        _, _, got = read_oap_2ds(path)
        for p, g in zip(parts, got, strict=True):
            self.assertTrue(np.array_equal(g.shaded, p.shaded))
        expected = [p.timing for p in parts[1:]] + [parts[-1].timing]
        self.assertEqual([g.timing for g in got], expected)

    def test_layout_header_and_polarity(self) -> None:
        shaded = np.zeros((1, 128), dtype=np.uint8)
        shaded[0, 0] = 1  # diode 0 shaded -> byte 15 bit 7 cleared
        self.assertEqual(encode_slice(shaded[0]), b"\xff" * 15 + b"\x7f")
        path = self.dir / "one.2d"
        write_oap_2ds([ExportParticle(shaded, 0x89ABCDEF, STAMP)], path, project="P",
                      flight_number="RF05", probe_id=b"SV")
        raw = path.read_bytes()
        xml, offset = split_oap_xml(raw)
        self.assertIn('<probe id="SV" type="2DS" resolution="10" nDiodes="128"', xml)
        self.assertIn("<FlightDate>09/06/2016</FlightDate>", xml)
        self.assertEqual(len(raw) - offset, OAP_RECORD_BYTES)
        _, headers, got = read_oap_2ds(path, probe_id=b"SV")
        h = headers[0]
        self.assertEqual((h.hour, h.minute, h.second, h.year, h.month, h.day, h.tas, h.msec,
                          h.overload), (12, 34, 56, 2016, 9, 6, 150, 250, 0))
        self.assertEqual(got[0].timing, 0x89ABCDEF)
        sync = raw[offset + 20 + 16 : offset + 20 + 32]
        self.assertEqual(sync[4:8], b"\x00" * 4)  # 32-bit counter, upper bytes zero

    def test_bad_input_refused(self) -> None:
        with self.assertRaises(ValueError):
            write_oap_2ds([], self.dir / "x.2d", probe_id=b"C1")
        with self.assertRaises(ValueError):
            write_oap_2ds([], self.dir / "x.2d", timing_convention="later")
        with self.assertRaises(ValueError):
            write_oap_2ds([ExportParticle(np.zeros((2, 64)), 1, STAMP)], self.dir / "x.2d")


class TestCanvasSplit(unittest.TestCase):
    @staticmethod
    def _pack(bits: np.ndarray) -> np.ndarray:
        return np.packbits(bits.astype(np.uint8), bitorder="big").view(">u2").astype(np.int64)

    def test_canvas_to_oap_and_back(self) -> None:
        rng = np.random.default_rng(11)
        images = [(rng.random((n, 128)) < 0.4).astype(np.uint8) for n in (3, 1, 7)]
        timings = [0x00010002, 0xFFFFFFFF, 12345]
        cols = []
        for img, t in zip(images, timings, strict=True):
            cols += [self._pack(row) for row in img]
            cols.append(np.full(8, BOUNDARY_WORD, dtype=np.int64))
            header = np.zeros(8, dtype=np.int64)
            header[6], header[7] = t >> 16, t & 0xFFFF
            cols.append(header)
        canvas = np.zeros((8, 1700), dtype=np.int64)
        canvas[:, : len(cols)] = np.column_stack(cols)
        split = particles_from_canvas(canvas)
        self.assertEqual([t for _, t in split], timings)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.2d"
            write_oap_2ds([ExportParticle(s, t, STAMP) for s, t in split], path,
                          timing_convention="own")
            _, _, got = read_oap_2ds(path)
        for img, t, g in zip(images, timings, got, strict=True):
            self.assertTrue(np.array_equal(g.shaded, img))
            self.assertEqual(g.timing, t)


if __name__ == "__main__":
    unittest.main()
