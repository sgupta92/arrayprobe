# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2 RAF reader, `soda2_read2dbuffer.pro:19-66`."""
import os
import struct
import tempfile
import unittest

from arrayprobe_soda2.read2dbuffer import RafSubformatError, read2dbuffer

#: The real NCAR RAF file (20240311_051816_rf05.2d) is named only by the
#: environment, never by a folder in the repository (the author's download-folder rule).
REAL_ENV = "ARRAYPROBE_RAF_F2DC_RAW"
REAL = os.environ.get(REAL_ENV, "").strip()


def _rec(pid, hh, mm, ss, ms, tas, word):
    head = struct.pack(">BB9h", ord(pid[0]), ord(pid[1]), hh, mm, ss, 2024, 3, 11, tas, ms, 1500)
    return head + struct.pack(">1024I", *([word] * 1024))


def _file(tag):
    # :38-39 seek strpos(tag)+9, so the first record starts exactly there.
    lead = b"<PMS2D><x/>"
    pre = (lead + tag).ljust(len(lead) + 9, b" ")
    body = _rec("C4", 1, 2, 3, 400, 255, 7) + _rec("C6", 5, 6, 7, 800, 255, 9)
    return pre, pre + body + b"\0" * 1000


class RafReader(unittest.TestCase):
    def _read(self, data, **op):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.2d")
            with open(p, "wb") as fh:
                fh.write(data)
            with open(p, "rb") as fh:
                return read2dbuffer(fh, dict(format="RAF", probetype="2DC", **op))

    def test_selects_probe_skips_preamble_scales_tas(self):
        pre, data = _file(b"</PMS2D>")
        b = self._read(data, probeid="C6", subformat=0)
        self.assertEqual(b.eof, 0)
        self.assertEqual(int(b.image[0]), 9)
        self.assertEqual(b.image.size, 1024)
        self.assertAlmostEqual(float(b.tas), 125.0, places=4)          # :57
        self.assertAlmostEqual(b.time, 5 * 3600 + 6 * 60 + 7 + 0.8)    # :58
        self.assertAlmostEqual(float(b.overload), 1.5, places=6)       # :62

    def test_oap_subformat3_tas_raw(self):
        # </OAP> at 5: :42 seeks 12, so the record must start at byte 12.
        data = b"<OAP></OAP> " + _rec("C4", 1, 2, 3, 400, 180, 7) + b"\0" * 1000
        b = self._read(data, probeid="C4", subformat=3)
        self.assertEqual(int(b.tas), 180)
        self.assertEqual(int(b.image[0]), 7)

    def test_subformat_mismatch_raises(self):
        _, data = _file(b"</PMS2D>")
        with self.assertRaisesRegex(RafSubformatError, ":45"):
            self._read(data, probeid="C4", subformat=3)

    def test_missing_probe_is_nullbuffer(self):
        _, data = _file(b"</PMS2D>")
        self.assertEqual(self._read(data, probeid="P1", subformat=0).eof, 1)

    @unittest.skipUnless(REAL and os.path.isfile(REAL),
                         f"set {REAL_ENV} to the full path of the NCAR RAF file "
                         "20240311_051816_rf05.2d to run this smoke test")
    def test_smoke_real_file(self):
        with open(REAL, "rb") as fh:
            s = fh.read(1000)
            pos = s.find(b"</PMS2D>")
            start = pos + 9 if pos >= 0 else s.find(b"</OAP>") + 7
            fh.seek(start)
            ids = set()
            for _ in range(200):
                r = fh.read(4116)
                if len(r) < 4116:
                    break
                ids.add(r[:2].decode("latin-1"))
        print("RAF smoke probe ids:", sorted(ids), "tag", "PMS2D" if pos >= 0 else "OAP")
        self.assertTrue(ids)
