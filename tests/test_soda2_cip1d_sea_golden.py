# SPDX-License-Identifier: BSD-3-Clause
"""The GDL golden for SODA-2's CIP-1D record (``readseabuffer_caps.pro:26-28``,
``:40-41``), banked by ``gdl_oracle/run_soda2_cip1d_sea_bank.py`` for the gap
port of SEA CIP runs with two or more ``seatag`` entries (slice 1). The
second side of each check is the fixture's own bytes, walked here directly."""
from __future__ import annotations

import base64
import json
import struct
import unittest
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "gdl_soda2_cip1d_sea_golden.json"
FIXTURE = DATA / "soda2_sea_cip_fixture.sea"


def _arr(node: dict) -> np.ndarray:
    raw = base64.b64decode(node.get("b64") or node.get("hex"))
    return np.frombuffer(raw, dtype=node["dtype"]).reshape(node["shape"])


def _fixture_cip1d_payloads() -> list[bytes]:
    """Every tag-32000 payload, in file order, from the SEA directory walk."""
    buf = FIXTURE.read_bytes()
    out, pos = [], 0
    while pos < len(buf):
        k, total, recs = pos, None, []
        while True:
            tag, off, nb = struct.unpack_from("<HHH", buf, k)
            k += 16
            if tag == 999:
                total = off
                break
            recs.append((tag, off, nb))
        out += [buf[pos + off: pos + off + nb] for tag, off, nb in recs if tag == 32000]
        pos += total
    return out


class TestCip1dRecordGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rec = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"][
            "cip1d_decode_one_record"]
        cls.payloads = _fixture_cip1d_payloads()

    def test_one_record_per_tag_32000_payload(self) -> None:
        self.assertEqual(len(self.payloads), 8)
        self.assertEqual(_arr(self.rec["count"]).shape, (8, 62))

    def test_idl_types(self) -> None:
        self.assertEqual(_arr(self.rec["count"]).dtype, np.int16)
        self.assertEqual(_arr(self.rec["housekeeping"]).dtype, np.int16)
        tn = self.rec["tnames"]
        tn = tn if isinstance(tn, str) else tn.get("value", str(tn))
        self.assertIn("INT,INT,UINT,DOUBLE,DOUBLE", str(tn))

    def test_count_is_bytes_6_to_130_as_int16(self) -> None:
        want = np.stack([np.frombuffer(p[6:130], "<i2") for p in self.payloads])
        self.assertTrue(np.array_equal(_arr(self.rec["count"]), want))

    def test_housekeeping_and_particlecounter_offsets(self) -> None:
        hk = np.stack([np.frombuffer(p[134:166], "<i2") for p in self.payloads])
        self.assertTrue(np.array_equal(_arr(self.rec["housekeeping"]), hk))
        pc = [struct.unpack_from("<H", p, 166)[0] for p in self.payloads]
        self.assertEqual(_arr(self.rec["particlecounter"]).tolist(), pc)

    def test_probetime_of_nonzero_hourmin_and_secmsec(self) -> None:
        # The fixture packs secmsec and hourmin at 168/170; GDL's `:40-41`
        # decode is compared against `_decode_cip1d` on the same bytes.
        from arrayprobe_soda2.read2dbuffer import _decode_cip1d
        hm = [struct.unpack_from("<h", p, 170)[0] for p in self.payloads]
        self.assertEqual(_arr(self.rec["hourmin"]).tolist(), hm)
        self.assertNotIn(0, hm)
        gdl = _arr(self.rec["probetime"]).tolist()
        self.assertTrue(all(t != 0.0 for t in gdl))
        self.assertEqual([_decode_cip1d(p)["probetime"] for p in self.payloads], gdl)


class TestDecodeCip1dAgainstGolden(unittest.TestCase):
    """The port's `_decode_cip1d` against the GDL golden, record by record."""

    @classmethod
    def setUpClass(cls) -> None:
        from arrayprobe_soda2.read2dbuffer import _decode_cip1d
        cls.rec = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"][
            "cip1d_decode_one_record"]
        cls.out = [_decode_cip1d(p) for p in _fixture_cip1d_payloads()]

    def test_count_and_housekeeping(self) -> None:
        self.assertTrue(np.array_equal(
            np.stack([o["count"] for o in self.out]), _arr(self.rec["count"])))
        self.assertTrue(np.array_equal(
            np.stack([o["housekeeping"] for o in self.out]), _arr(self.rec["housekeeping"])))

    def test_particlecounter_secmsec_hourmin_probetime(self) -> None:
        for key in ("particlecounter", "secmsec", "hourmin", "probetime"):
            self.assertEqual([o[key] for o in self.out], _arr(self.rec[key]).tolist(), key)

    def test_probetime_decode_of_nonzero_fields(self) -> None:
        # Hand computation of `:40-41`: hourmin 12:34 packed as (12<<6)|34,
        # secmsec 56.789 s packed as (56<<10)|789.
        from arrayprobe_soda2.read2dbuffer import _decode_cip1d
        p = bytearray(180)
        struct.pack_into("<Hh", p, 168, (56 << 10) | 789, (12 << 6) | 34)
        self.assertAlmostEqual(_decode_cip1d(bytes(p))["probetime"], 123456.789, places=9)

    def test_short_record_is_refused(self) -> None:
        from arrayprobe_soda2.read2dbuffer import _decode_cip1d
        with self.assertRaises(ValueError):
            _decode_cip1d(bytes(179))


if __name__ == "__main__":
    unittest.main()


class TestDecodeCip1dEdgeRecords(unittest.TestCase):
    """Standalone records (review section 3): top bit set in hourmin and
    secmsec, particlecounter above 32767, and the `:38` reset above 320000."""

    @classmethod
    def setUpClass(cls) -> None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"))  # noqa: E501
        from run_soda2_cip1d_sea_bank import EDGE_TIMES, edge_payloads

        from arrayprobe_soda2.read2dbuffer import _decode_cip1d
        cls.rec = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"][
            "cip1d_decode_edge_records"]
        cls.out = [_decode_cip1d(p) for p in edge_payloads()]
        cls.times = EDGE_TIMES

    def test_types(self) -> None:
        self.assertEqual(self.rec["tnames"], "UINT,INT,DOUBLE")

    def test_edge_records_count_and_housekeeping(self) -> None:
        count = np.stack([o["count"] for o in self.out])
        house = np.stack([o["housekeeping"] for o in self.out])
        # The bank's three standalone edge records (top bit, counter > 32767, the reset).
        self.assertEqual(count.shape[0], 3)
        self.assertTrue(np.array_equal(count, _arr(self.rec["count"])))
        self.assertTrue(np.array_equal(house, _arr(self.rec["housekeeping"])))

    def test_particlecounter_above_32767(self) -> None:
        got = [o["particlecounter"] for o in self.out]
        self.assertEqual(got, _arr(self.rec["particlecounter"]).tolist())
        self.assertTrue(all(v > 32767 for v in got))

    def test_top_bit_hourmin_secmsec_and_probetime(self) -> None:
        for key in ("secmsec", "hourmin", "probetime"):
            self.assertEqual([o[key] for o in self.out], _arr(self.rec[key]).tolist(), key)

    def test_hhmmss_and_the_320000_reset(self) -> None:
        from arrayprobe_soda2.sea import _hhmmss
        pre = [_hhmmss(np.asarray(t, dtype=np.int16)) for t in self.times]
        self.assertEqual(pre, _arr(self.rec["hhmmss_pre"]).tolist())
        # sea.py's `:38` statement, applied as the port writes it.
        post = [0.0 if h > 320000 else h for h in pre]
        self.assertEqual(post, _arr(self.rec["hhmmss_post"]).tolist())


class TestProcessCip1dSeaGolden(unittest.TestCase):
    """GDL's process_cip1d_sea.pro output on the fixture's 25800-25830 s window.

    The port of process_cip1d_sea is not written yet; this pins the reference it will be
    asserted against, so a regenerated golden that changed shape fails here first.
    """

    @classmethod
    def setUpClass(cls):
        cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
        cls.out = cases["process_cip1d_sea_window_25800_25830"]

    def field(self, name):
        node = self.out[name]
        return _arr(node[0] if isinstance(node, list) else node)

    def test_one_row_per_second_of_the_window(self):
        time = self.field("TIME")
        self.assertEqual(time.shape, (31,))
        self.assertTrue(np.array_equal(np.diff(time), np.ones(30)))
        self.assertEqual(self.field("SPEC1D").shape, (62, 31))
        for name in ("TAS_PITOT", "PARTICLECOUNTER", "PRES", "DOFREJECT"):
            self.assertEqual(self.field(name).shape, (31,), name)

    def test_bins_are_62_wide_with_63_edges(self):
        self.assertEqual(self.field("MIDBINS").shape, (62,))
        self.assertEqual(self.field("BINWIDTH").shape, (62,))
        self.assertEqual(self.field("ENDBINS").shape, (63,))

    def test_counts_land_only_in_seconds_that_hold_records(self):
        spec = self.field("SPEC1D")
        filled = np.flatnonzero(spec.sum(axis=0) > 0)
        self.assertGreater(filled.size, 0)
        self.assertTrue(np.array_equal(filled, np.flatnonzero(self.field("TAS_PITOT") != 0)))


class TestProcessCip1dSeaPort(unittest.TestCase):
    """``process_cip1d_sea.pro`` (``/nowrite``) on window 25800-25830 s: the
    port equals every field GDL returned (IDL order, so the golden's
    reversed shape is transposed)."""

    @classmethod
    def setUpClass(cls) -> None:
        from arrayprobe_soda2.process_hk import process_cip1d_sea
        cls.g = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"][
            "process_cip1d_sea_window_25800_25830"]
        cls.d = process_cip1d_sea({
            "fn": [str(FIXTURE)], "starttime": 25800.0, "stoptime": 25830.0,
            "rate": 1, "res": np.float32(25.0), "seatag": [33000, 32000, 0],
            "timeoffset": np.float32(0.0)})

    def _golden(self, name: str) -> np.ndarray:
        node = self.g[name]
        node = node[0] if isinstance(node, list) else node
        return _arr(node)

    def test_every_numeric_field(self) -> None:
        for name in ("TIME", "SPEC1D", "MIDBINS", "BINWIDTH", "ENDBINS", "TAS_PITOT",
                     "PARTICLECOUNTER", "PRES", "LASER_CURRENT", "LASER_POWER",
                     "DOFREJECT", "ENDREJECT", "OVERSIZEREJECT", "VOLTS",
                     "DIODES"):
            with self.subTest(field=name):
                want = self._golden(name)
                got = np.asarray(self.d[name.lower()])
                if got.ndim == 2:
                    got = got.T
                self.assertEqual(got.dtype, want.dtype)
                np.testing.assert_array_equal(got, want)

    def test_temp_every_row(self) -> None:
        # Thermistor rows included: record 10's Option1 (111.38168) pins
        # alog as a correctly rounded float32 log, not numpy's float32 log.
        got = np.asarray(self.d["temp"]).T
        want = self._golden("TEMP")
        self.assertEqual(got.dtype, want.dtype)
        np.testing.assert_array_equal(got, want)

    def test_tempid(self) -> None:
        node = self.g["TEMPID"]
        want = node[0] if isinstance(node, list) and isinstance(node[0], list) else node
        self.assertEqual(self.d["tempid"], list(want))
