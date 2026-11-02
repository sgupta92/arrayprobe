# SPDX-License-Identifier: BSD-3-Clause
"""The OAP 2D-S reader on hand-built records, the S2 storage layout it will be
fed from. ``readers/pms.py`` skips 2D-S records (its tag filter accepts 'C1', 'C6', 'C4'
and 'P*' only), which is why a dedicated reader exists; that gap is pinned in
``tests/test_pms.py`` beside the v3.1.4 engine's own reader tests."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_uiops.oap_read import (
    OAP_RECORD_BYTES,
    SLICE_BYTES_2DS,
    read_oap_2ds,
    split_oap_xml,
)
from arrayprobe_uiops.spec import MARKER_2S, _pack_image, get_img_v35

BOUNDARY_WORD = 0b1010101010101010  # the alternating boundary slice, packed

XML = (b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<OAP version="1">\n'
       b'<probe id="SH" type="2DS" resolution="10" nDiodes="128" suffix="_2H"/>\n'
       b"</OAP>\n")


def _header(tag: bytes, hour: int = 12) -> bytes:
    return struct.pack(">2s9H", tag, hour, 34, 56, 2016, 9, 6, 150, 250, 0)


def _sync(timing: int) -> bytes:
    """Sync slice as translate2ds writes it: timing in bytes 0-7 little-endian
    (top two bytes zero), then 0xAAAAAA0000000000 little-endian."""
    return (timing & 0x0000FFFFFFFFFFFF).to_bytes(8, "little") + (
        0xAAAAAA0000000000).to_bytes(8, "little")


def _image_slice(shaded_diodes: list[int]) -> bytes:
    """One slice in process2d's diode order (diode 0 = byte 15 bit 7), 1 = clear."""
    bits = np.ones(128, dtype=np.uint8)
    bits[shaded_diodes] = 0
    return np.packbits(bits, bitorder="big").tobytes()[::-1]


def _records(tag: bytes, stream: bytes) -> list[bytes]:
    data_len = OAP_RECORD_BYTES - 20
    stream = stream + b"\x00" * (-len(stream) % data_len)
    return [_header(tag) + stream[i : i + data_len] for i in range(0, len(stream), data_len)]


def _write(path: Path, records: list[bytes], xml: bytes = XML) -> Path:
    path.write_bytes(xml + b"".join(records))
    return path


class TestReadOap2ds(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_diode_order_and_polarity_follow_process2d(self) -> None:
        stream = _image_slice([0, 5, 127]) + _sync(0x123456789A)
        _, headers, parts = read_oap_2ds(_write(self.dir / "a.2d", _records(b"SH", stream)))
        self.assertEqual(len(headers), 1)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].timing, 0x123456789A)
        self.assertEqual(np.flatnonzero(parts[0].shaded[0]).tolist(), [0, 5, 127])
        # Byte 15 bit 7 is diode 0: clearing it alone shades diode 0 only.
        raw = bytearray(b"\xff" * SLICE_BYTES_2DS)
        raw[15] &= 0x7F
        _, _, parts = read_oap_2ds(
            _write(self.dir / "b.2d", _records(b"SH", bytes(raw) + _sync(1))))
        self.assertEqual(np.flatnonzero(parts[0].shaded[0]).tolist(), [0])

    def test_particle_spanning_a_record_boundary_and_trailing_padding(self) -> None:
        per_record = (OAP_RECORD_BYTES - 20) // SLICE_BYTES_2DS  # 256
        first = [_image_slice([d % 128]) for d in range(per_record - 1)] + [_sync(7)]
        second = [_image_slice([3]), _image_slice([4]), _image_slice([5])]
        stream = b"".join(first + second) + _sync(9)
        _, headers, parts = read_oap_2ds(_write(self.dir / "c.2d", _records(b"SH", stream)))
        self.assertEqual(len(headers), 2)
        self.assertEqual([p.timing for p in parts], [7, 9])
        self.assertEqual(parts[0].bits.shape, (per_record - 1, 128))
        self.assertEqual(parts[1].bits.shape, (3, 128))
        self.assertEqual(parts[1].record, 1)
        # Zero padding after the last sync is not a particle.
        self.assertEqual(len(parts), 2)

    def test_other_probes_records_are_skipped(self) -> None:
        sh = _records(b"SH", _image_slice([1]) + _sync(11))
        c1 = [_header(b"C1") + b"\xaa" * (OAP_RECORD_BYTES - 20)]
        path = _write(self.dir / "d.2d", [c1[0], sh[0], c1[0]])
        _, headers, parts = read_oap_2ds(path)
        self.assertEqual([h.probe_id for h in headers], [b"SH"])
        self.assertEqual([p.timing for p in parts], [11])
        _, _, sv = read_oap_2ds(path, probe_id=b"SV")
        self.assertEqual(sv, [])

    def test_xml_split_and_ragged_body_refused(self) -> None:
        xml, offset = split_oap_xml(XML + b"rest")
        self.assertTrue(xml.endswith("</OAP>\n"))
        self.assertEqual(offset, len(XML))
        self.assertEqual(split_oap_xml(b"no preamble"), ("", 0))
        path = self.dir / "e.2d"
        path.write_bytes(XML + b"\x00" * 10)
        with self.assertRaises(ValueError):
            read_oap_2ds(path)
        with self.assertRaises(ValueError):
            read_oap_2ds(path, probe_id=b"C1")


class TestS2CanvasLayout(unittest.TestCase):
    """The storage facts the exporter will rely on, measured on the v3.5 decoder."""

    def test_polarity_boundary_and_header_timing(self) -> None:
        buf = np.zeros(4096, dtype=np.int64)
        shaded, clear = 5, 3  # rows 4-8 shaded
        timing = 0x89ABCDEF
        n_h = 3  # one run word + two timing words
        buf[:5] = [MARKER_2S, n_h, 0, 1, 1]
        buf[5:8] = [(shaded << 7) | clear, timing >> 16, timing & 0xFFFF]
        img_h, img_v, *_ = get_img_v35(buf, 123456)
        self.assertFalse(img_v.any())
        self.assertEqual(np.flatnonzero(img_h[:, 0]).tolist(), [3, 4, 5, 6, 7])  # 1 = shaded
        packed = _pack_image(img_h)
        self.assertTrue((packed[:, 1] == BOUNDARY_WORD).all())  # boundary after the image
        header = packed[:, 2]
        self.assertEqual(int(header[6]) << 16 | int(header[7]), timing)  # rows 97-128
        self.assertEqual(int(header[3]), n_h)  # rows 49-64: the packet's count word
        self.assertFalse(packed[:, 3:].any())


if __name__ == "__main__":
    unittest.main()
