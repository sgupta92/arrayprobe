# SPDX-License-Identifier: BSD-3-Clause
"""R6B: the SPEC pre-loop -- `timeconv`, `read2dbuffer`, `buildindex`,
`update_op`, `process_hk` -- against `gdl_soda2_preloop_golden.json`
(`gdl_oracle/run_soda2_preloop_bank.py`, GDL 1.1.2, unmodified vendored
source)."""
from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2 import buildindex, process_hk, read2dbuffer, timeconv, update_op

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = json.loads((DATA / "gdl_soda2_preloop_golden.json").read_text(encoding="utf-8"))
HK_FIX = DATA / "soda2_spec_hk_fixture"


def _f32hex(x: float) -> str:
    return struct.pack(">f", np.float32(x)).hex().upper()


def _base_op(**over) -> dict:
    op = dict(
        fn=str(HK_FIX), date="20160906", starttime=24240.0, stoptime=24250.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0, 1000], rate=1.0, timeoffset=np.float32(0.0),
        fixedtas=np.float32(0.0), numdiodes=128, probeid="H",
    )
    op.update(over)
    return op


class TestHms2sfm(unittest.TestCase):
    def test_cases_match_golden(self) -> None:
        cases = [
            ("hms_long", 64440),
            ("hms_double", 64440.5),
            ("hms_float", np.float32(64440.1)),
            ("hms_end", 235959.999),
            ("hms_neg", -1.0),
        ]
        for name, arg in cases:
            got = timeconv.hms2sfm(arg)
            want = float(GOLDEN[name]["V"])
            self.assertAlmostEqual(got, want, places=5, msg=name)

    def test_line_9_negative_truncates_toward_zero(self) -> None:
        # T9: hms2sfm(-1) truncates -1 -> 0 before the fraction is taken,
        # giving -1.0 exactly (not -0.999...).
        self.assertEqual(timeconv.hms2sfm(-1.0), -1.0)
        self.assertEqual(float(GOLDEN["hms_neg"]["V"]), -1.0)


class TestParsedate(unittest.TestCase):
    def test_ymd_and_mdy_match_golden(self) -> None:
        for name, date in (("pd_ymd", "20160906"), ("pd_mdy", "09062016")):
            got = timeconv.soda2_parsedate(date)
            g = GOLDEN[name]
            self.assertEqual(got.year, g["YEAR"])
            self.assertEqual(got.month, g["MONTH"])
            self.assertEqual(got.day, g["DAY"])
            self.assertEqual(got.yearnum, int(g["YN"]))
            self.assertEqual(got.monthnum, int(g["MN"]))
            self.assertEqual(got.daynum, int(g["DN"]))
            self.assertEqual(got.order, g["ORDER"])
            self.assertEqual(got.julday, int(g["JD"]))


class TestUpdateOp(unittest.TestCase):
    def test_min_defaults(self) -> None:
        op = update_op.update_op(dict(probetype="2DS", res=10.0,
                                       endbins=[0, 1000], format="SPEC", fn="x"))
        self.assertEqual(op["numdiodes"], 64)
        self.assertEqual(op["shortname"], "2DS")
        self.assertEqual(op["yres"], 10.0)
        self.assertEqual(list(op["dioderange"]), [0, 63])
        self.assertEqual(list(op["seatag"]), [33000, 0, 0])
        self.assertEqual(op["probeid"], "A0")

    def test_empty_defaults(self) -> None:
        op = update_op.update_op(None)
        self.assertEqual(op["probetype"], "")
        self.assertEqual(op["numdiodes"], 64)
        self.assertEqual(op["res"], 0)
        self.assertEqual(op["yres"], 0)

    def test_pip_becomes_cip(self) -> None:
        op = update_op.update_op(dict(probetype="PIP", res=10.0,
                                       endbins=[0, 1000], format="SPEC", fn="x"))
        self.assertEqual(op["probetype"], "CIP")

    def test_3vcpi_sets_subformat(self) -> None:
        op = update_op.update_op(dict(probetype="3VCPI", res=10.0,
                                       endbins=[0, 1000], format="SPEC", fn="x"))
        self.assertEqual(op["subformat"], 1)

    def test_line_41_50_dioderange_derived_after_numdiodes(self) -> None:
        # T8: dioderange default/zero-fixup both use the FINAL numdiodes.
        op = update_op.update_op(dict(probetype="2DS", res=10.0,
                                       endbins=[0, 1000], format="SPEC", fn="x",
                                       dioderange=[0, 0], numdiodes=64))
        self.assertEqual(list(op["dioderange"]), [0, 63])

    def test_txt_model_header_is_round_7(self) -> None:
        with self.assertRaises(NotImplementedError):
            update_op.update_op(dict(probetype="2DS", res=10.0,
                                      endbins=[0, 1000], format="SPEC",
                                      fn="model.txt"))


class TestRead2dBuffer(unittest.TestCase):
    def test_buffer0_and_buffer1_match_golden(self) -> None:
        op = _base_op()
        with open(HK_FIX, "rb") as f:
            f.seek(0)
            b0 = read2dbuffer.read2dbuffer_spec(f, op)
        g0 = GOLDEN["r2d_hk_b0"]
        self.assertAlmostEqual(b0.time, float(g0["TIME"]), places=5)
        self.assertAlmostEqual(float(b0.tas), float(g0["TAS"]), places=5)
        self.assertEqual(b0.date, int(g0["DATE"]))
        self.assertEqual(b0.eof, int(g0["EOF"]))

        with open(HK_FIX, "rb") as f:
            f.seek(4114)
            b1 = read2dbuffer.read2dbuffer_spec(f, op)
        g1 = GOLDEN["r2d_hk_b1"]
        self.assertAlmostEqual(b1.time, float(g1["TIME"]), places=5)

    def test_line_16_17_eof_dtypes_are_int(self) -> None:
        # T6: nullbuffer's tas/time are INT, not FLOAT/DOUBLE.
        op = _base_op()
        size = HK_FIX.stat().st_size
        with open(HK_FIX, "rb") as f:
            f.seek(size)
            b = read2dbuffer.read2dbuffer_spec(f, op)
        self.assertEqual(b.eof, 1)
        g = GOLDEN["r2d_eof"]
        self.assertEqual(g["TN"], "INT,INT")
        self.assertIsInstance(b.tas, np.int16)
        self.assertIsInstance(b.time, np.int16)

    def test_fixedtas_overrides_100(self) -> None:
        op = _base_op(fixedtas=np.float32(150.0))
        with open(HK_FIX, "rb") as f:
            f.seek(0)
            b = read2dbuffer.read2dbuffer_spec(f, op)
        self.assertAlmostEqual(float(b.tas), float(GOLDEN["r2d_fixedtas"]["TAS"]), places=5)

    def test_line_116_float_timeoffset_widens_like_idl(self) -> None:
        # T7: a FLOAT32 timeoffset of 0.1 widens to ~0.10000000149...
        op = _base_op(timeoffset=np.float32(0.1))
        with open(HK_FIX, "rb") as f:
            f.seek(0)
            b = read2dbuffer.read2dbuffer_spec(f, op)
        want = float(GOLDEN["r2d_offset_f"]["TIME"])
        self.assertAlmostEqual(b.time, want, places=9)

    def test_non_spec_format_is_round_7(self) -> None:
        with self.assertRaises(NotImplementedError):
            with open(HK_FIX, "rb") as f:
                read2dbuffer.read2dbuffer(f, _base_op(format="SEA"))


class TestBuildIndex(unittest.TestCase):
    def test_count_matches_golden(self) -> None:
        op = _base_op()
        idx = buildindex.buildindex(HK_FIX, op)
        self.assertEqual(idx.count, int(GOLDEN["bi_hk"]["COUNT"]))

    def test_non_spec_is_round_7(self) -> None:
        with self.assertRaises(NotImplementedError):
            buildindex.buildindex(HK_FIX, _base_op(format="SEA"))


class TestProcessHk(unittest.TestCase):
    def test_hk_base_nb_and_counts_match_golden(self) -> None:
        d = process_hk.process_hk(_base_op())
        g = GOLDEN["hk_base"]
        want_nb = [float(x) for x in g["NB"].split(",")]
        self.assertEqual(list(np.round(d.nb, 5)), [round(x, 5) for x in want_nb])
        want_counts = [float(x) for x in g["COUNTS"].split(",")]
        self.assertEqual([round(float(c), 3) for c in d.counts],
                          [round(c, 3) for c in want_counts])

    def test_line_84_probeid_A0_and_H_agree(self) -> None:
        # T4 / S5-k: every probeid other than 'V' takes the same (H) columns.
        d_h = process_hk.process_hk(_base_op(probeid="H"))
        d_a0 = process_hk.process_hk(_base_op(probeid="A0"))
        np.testing.assert_array_equal(d_h.counts, d_a0.counts)
        np.testing.assert_array_equal(d_h.volts, d_a0.volts)

    def test_line_77_79_counts_are_summed_not_averaged(self) -> None:
        # T3: hk_base has 10 records in one second; the counts column (34)
        # is their SUM, not their mean -- 306 for buffer 0's ten records.
        d = process_hk.process_hk(_base_op())
        self.assertAlmostEqual(float(d.counts[3]), 306.0, places=1)

    def test_multi_fn_refuses(self) -> None:
        with self.assertRaises(ValueError):
            process_hk.process_hk(_base_op(fn=["a", "b"]))

    def test_subformat_nonzero_wants_the_separate_hk_file(self) -> None:
        # Version 2 is ported (test_soda2_spec_read_hk_v2):
        # it reads `op.fn + 'HK'` and stops when that file is absent
        # (spec_process_hk.pro:17-20), which it is for this v1 fixture.
        with self.assertRaises(process_hk.ProcessHKStop):
            process_hk.process_hk(_base_op(subformat=1))

    def test_process_hk_does_not_mutate_y(self) -> None:
        op = _base_op()
        y = buildindex.buildindex(HK_FIX, op)
        before = y.bufftime.copy()
        process_hk.process_hk(op, y=y)
        np.testing.assert_array_equal(y.bufftime, before)

    def test_line_60_where_empty_floors_at_zero(self) -> None:
        # T1: hkp's max(where(...)) > 0 clamp -- buffind never negative.
        d = process_hk.process_hk(_base_op())
        self.assertTrue(np.all(d.nb >= 0))


class TestImports(unittest.TestCase):
    def test_imports_neither_uiops_port(self) -> None:
        import sys
        for mod in (timeconv, read2dbuffer, buildindex, update_op, process_hk):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            self.assertNotIn("import arrayprobe\n", src)
            self.assertNotIn("from arrayprobe ", src)
            self.assertNotIn("arrayprobe_uiops", src)
        del sys


if __name__ == "__main__":
    unittest.main()
