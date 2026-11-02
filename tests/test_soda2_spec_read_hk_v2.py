# SPDX-License-Identifier: BSD-3-Clause
"""Version 2 housekeeping (3VCPI/Hawkeye/HVPS-4):
``spec_read_hk.pro:43-65``, ``spec_index_hk.pro`` and
``spec_process_hk.pro:14-25,104-167`` against GDL running them unmodified
(``gdl_oracle/run_soda2_spec_read_hk_bank.py --v2``, golden
``tests/data/gdl_soda2_spec_read_hk_v2_golden.json``) on a synthetic
2DSCPIHK file whose layout is derived from ``spec_index_hk.pro:11,44-52``."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.process_hk import ProcessHKStop, process_hk, spec_index_hk
from arrayprobe_soda2.spec_read_hk import spec_read_hk

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "gdl_soda2_spec_read_hk_v2_golden.json"
FIXTURE = DATA / "soda2_spec_v2_2DSCPIHK"
NOHK = DATA / "soda2_spec_v2_nohk_2DSCPIHK"
GDL_ORACLE = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"

_PHK = [("H", "3VCPI"), ("V", "3VCPI"), ("V50", "3VCPI"), ("V150", "3VCPI"),
        ("H50", "3VCPI"), ("H150", "3VCPI"), ("H", "HVPS4")]


def _hex32(a) -> str:
    a = np.asarray(a).ravel(order="F").astype(np.float32)
    # glibc's log(negative) returns the sign-bit-set quiet NaN (FFC00000); MSVC's
    # and GDL's golden carry 7FC00000. A NaN's sign is a payload, not a value, so
    # it is canonicalised here and every finite bit is still compared exactly.
    a = np.where(np.isnan(a), np.float32(np.nan), a).astype(np.float32)
    return ",".join(f"{v:08X}" for v in a.view(np.uint32))


def _hex64(a) -> str:
    a = np.asarray(a).ravel(order="F").astype(np.float64)
    return ",".join(f"{v:016X}" for v in a.view(np.uint64))


def _op(fn: Path, probeid: str, probetype: str) -> dict:
    # The bank's `_V2_OP`, field for field (rate a FLOAT literal there).
    return dict(fn=str(fn)[:-2], date="20160914", starttime=25200.0,
                stoptime=25204.0, format="SPEC", subformat=1,
                probetype=probetype, res=10.0, endbins=[0, 1000],
                arendbins=[0, 1], rate=np.float32(1.0), probeid=probeid,
                numdiodes=128)


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for p in (GOLDEN, FIXTURE, NOHK):
            if not p.is_file():
                raise AssertionError(f"{p} is missing -- a tracked fixture")
        g = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.hkp = g["hkp"]
        cls.rec = {r["name"]: r for r in g["records"]}

    def test_spec_read_hk_version_2_matches_every_channel(self):
        for name in ("r0", "r1", "r2", "r3"):
            r = self.rec[f"read_{name}"]
            with self.subTest(record=name), open(FIXTURE, "rb") as f:
                h = spec_read_hk(f, self.hkp[name], 0, version=2)
                self.assertEqual(r["TN"], "ULONG,FLOAT,FLOAT,INT")
                self.assertEqual(h.time, int(r["TIME"]))
                self.assertEqual(f"{h.tas.view(np.uint32):08X}", r["TAS"])
                self.assertEqual(h.x.shape, (83,))
                self.assertEqual(_hex32(h.x), r["Y"])
                self.assertEqual(",".join(map(str, h.raw)), r["RAW"])

    def test_spec_index_hk_matches(self):
        r = self.rec["index"]
        ix = spec_index_hk(str(FIXTURE))
        self.assertEqual(r["TN"], "LONG,DOUBLE,LONG,LONG64,LONG64")
        self.assertEqual(",".join(map(str, ix.date)), r["DATE"])
        self.assertEqual(_hex64(ix.bufftime), r["BUFFTIME"])
        self.assertEqual(",".join(map(str, ix.pointer)), r["POINTER"])
        self.assertEqual(",".join(map(str, ix.hkp)), r["HKP"])
        self.assertEqual(",".join(map(str, ix.maskp)), r["MASKP"])
        self.assertEqual(ix.buffsize, int(r["BUFFSIZE"]))

    def _check_house(self, d, r):
        self.assertEqual(",".join(f"{v:.5f}" for v in d.nb), r["NB"])
        for key, attr in (("TAS", "tas"), ("VOLTS", "volts"),
                          ("OVERLOADS", "overloads"), ("LASERVOLTS", "laservolts"),
                          ("COUNTS", "counts"), ("CANPRESSURE", "canpressure"),
                          ("POWER", "power")):
            self.assertEqual(_hex32(getattr(d, attr)), r[key], key)
        self.assertEqual(_hex64(d.temp), r["TEMP"])
        self.assertEqual(",".join(map(str, d.temp.shape)), r["TEMPDIMS"])
        self.assertEqual(",".join(map(str, d.volts.shape)), r["VOLTSDIMS"])
        self.assertEqual("|".join(d.tempid), r["TEMPID"])

    def test_spec_process_hk_version_2_matches_for_every_probeid(self):
        for pid, ptype in _PHK:
            r = self.rec[f"phk_{pid}_{ptype}"]
            with self.subTest(probeid=pid, probetype=ptype):
                self.assertEqual(r["status"], "OK")
                self._check_house(process_hk(_op(FIXTURE, pid, ptype)), r)

    def test_a_file_with_no_hk_buffer_reads_a_phantom_record_at_byte_0(self):
        r = self.rec["phk_nohk"]
        d = process_hk(_op(NOHK, "H", "3VCPI"))
        self._check_house(d, r)
        self.assertEqual(float(d.nb[0]), 1.0)  # spec_index_hk.pro:59 `hkp=[0]`

    def test_the_default_probeid_halts_the_version_2_case(self):
        self.assertIn("CASE statement found no match", self.rec["phk_A0_3VCPI"]["stderr"])
        with self.assertRaises(ProcessHKStop) as ctx:
            process_hk(_op(FIXTURE, "A0", "3VCPI"))
        self.assertIn("spec_process_hk.pro:115", str(ctx.exception))

    def test_a_missing_hk_file_stops(self):
        self.assertIn("Stop encountered", self.rec["phk_missing"]["stderr"])
        with self.assertRaises(ProcessHKStop) as ctx:
            process_hk(_op(DATA / "soda2_spec_v2_2DSCPI_missingHK", "H", "3VCPI"))
        self.assertIn("spec_process_hk.pro:17-20", str(ctx.exception))


class TheFindings(unittest.TestCase):
    def test_line_64_adds_the_high_time_word_unshifted(self):
        with open(FIXTURE, "rb") as f:
            h = spec_read_hk(f, 600, 0, version=2)  # r3: x[72:74] = 2, 3, 4
        self.assertEqual(h.time, 2 + (3 << 16) + 4)

    def test_line_49_five_times_x_wraps_at_16_bits(self):
        with open(FIXTURE, "rb") as f:
            h = spec_read_hk(f, 16, 0, version=2)  # r0: x[6] = 6554 -> 5*x < 0
        self.assertTrue(np.isnan(h.x[6]))
        self.assertFalse(np.isnan(h.x[5]))  # 6553: 5*x = 32765, no wrap

    def test_version_2_outputs_are_sums_not_averages(self):
        d = process_hk(_op(FIXTURE, "H", "3VCPI"))
        self.assertEqual(float(d.nb[0]), 2.0)
        self.assertEqual(float(d.counts[0]), 57.0 + 57.0)  # hkraw[*,57], never divided


class TheBankItself(unittest.TestCase):
    def test_the_generator_still_builds_the_tracked_fixtures(self):
        if str(GDL_ORACLE) not in sys.path:
            sys.path.insert(0, str(GDL_ORACLE))
        import run_soda2_spec_read_hk_bank as bank
        raw, hkp = bank.build_v2_fixture()
        self.assertEqual(raw, FIXTURE.read_bytes())
        self.assertEqual(bank.build_v2_nohk_fixture(), NOHK.read_bytes())
        g = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(hkp, g["hkp"])


if __name__ == "__main__":
    unittest.main()
