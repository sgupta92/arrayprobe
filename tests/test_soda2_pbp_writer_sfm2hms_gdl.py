# SPDX-License-Identifier: BSD-3-Clause
"""``pbp_writer.sfm2hms`` and its three renderings against GDL, both sides of
midnight (bank ``gdl_oracle/run_soda2_sfm2hms_bank.py``, golden
``tests/data/gdl_soda2_sfm2hms_golden.json``).

``sfm2hms.pro`` has no ``mod 86400``: GDL returns LONG ``240001`` for 86401 s,
``soda2_filename`` writes ``..._240001_...`` (and ``******`` once the value
no longer fits ``i06``), and the ``HH:MM:SS`` builder writes ``24:00:01``.
The earlier port wrapped (``000001`` / ``00:00:01``). Each golden row is
compared for the integer (IDL type LONG), the filename and the string; the
``.pbp.nc`` ``TimeInterval`` and ``soda2_export_ncdf``'s ``idl_sfm2hms`` are
checked through the same rows; and the earlier wrap, put back, must fail.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe_soda2 import pbp_writer as pw
from arrayprobe_soda2.export_ncdf import idl_sfm2hms

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_sfm2hms_golden.json"

_IDL_LONG = 3


def _load() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _sfm(row: dict) -> float:
    """The value GDL was given: DOUBLE, or its FLOAT rounding."""
    v = row["sfm"]
    return float(np.float32(v)) if row["idl_type"] == "float" else float(v)


def _op(sfm: float) -> dict:
    return {"outdir": "", "date": "09062016", "starttime": sfm,
            "probetype": "2DS", "probeid": "H"}


def _wrapping_sfm2hms(sfm: float) -> int:
    """The earlier port, verbatim: ``% 86400`` and Python's floor divmod."""
    total_seconds = int(sfm) % 86400
    hh, rem = divmod(total_seconds, 3600)
    mm, ss = divmod(rem, 60)
    return hh * 10000 + mm * 100 + ss


def _mismatches() -> int:
    bad = 0
    for row in _load():
        sfm = _sfm(row)
        bad += pw.sfm2hms(sfm) != row["hms"]
        bad += pw.pbp_filename(_op(sfm), "S", extension=".x") != row["filename"]
        bad += pw._idl_hms_string(pw.sfm2hms(sfm)) != row["hms_string"]
    return int(bad)


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_sfm2hms_bank.py first")
class TestEveryRowMatchesGdl(unittest.TestCase):
    def test_the_golden_spans_midnight(self):
        """Guards the check: rows on both sides of 86400 s, and at least one
        past the ``i06`` limit, or the comparison below proves nothing."""
        sfms = [r["sfm"] for r in _load()]
        self.assertTrue(any(0 <= s < 86400 for s in sfms))
        self.assertTrue(any(s > 86400 for s in sfms))
        self.assertIn(86400.0, sfms)
        self.assertTrue(any(r["filename"].count("******") for r in _load()))

    def test_integer_type_and_value(self):
        for row in _load():
            with self.subTest(sfm=row["sfm"], idl_type=row["idl_type"]):
                got = pw.sfm2hms(_sfm(row))
                self.assertEqual(row["hms_type"], _IDL_LONG)
                self.assertIsInstance(got, int)
                self.assertTrue(-2**31 <= got < 2**31)  # fits an IDL LONG
                self.assertEqual(got, row["hms"])

    def test_soda2_filename(self):
        for row in _load():
            with self.subTest(sfm=row["sfm"]):
                self.assertEqual(pw.pbp_filename(_op(_sfm(row)), "S", extension=".x"),
                                 row["filename"])

    def test_hh_mm_ss_string(self):
        for row in _load():
            with self.subTest(sfm=row["sfm"]):
                self.assertEqual(pw._idl_hms_string(pw.sfm2hms(_sfm(row))), row["hms_string"])

    def test_export_ncdf_uses_the_same_routine(self):
        for row in _load():
            self.assertEqual(idl_sfm2hms(_sfm(row)), row["hms"])

    def test_pbp_ncdf_time_interval_across_midnight(self):
        """`soda2_process_2d.pro:253-257`'s ``TimeInterval`` on the ``.pbp.nc``."""
        rows = {r["sfm"]: r for r in _load() if r["idl_type"] == "double"}
        start, stop = rows[86399.0], rows[90061.5]
        with tempfile.TemporaryDirectory() as tmp:
            ds = pw.open_pbp_ncdf(str(Path(tmp) / "t.pbp.nc"),
                                  {"starttime": 86399.0, "stoptime": 90061.5},
                                  {"month": "09", "day": "06", "year": "2016"})
            try:
                self.assertEqual(ds.TimeInterval,
                                 f"{start['hms_string']}-{stop['hms_string']}")
                self.assertEqual(ds.TimeInterval, "23:59:59-25:01:01")
            finally:
                ds.close()


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_sfm2hms_bank.py first")
class TestMutationIsCaught(unittest.TestCase):
    def test_baseline_has_zero_mismatches(self):
        self.assertEqual(_mismatches(), 0)

    def test_the_midnight_wrap_put_back_fails_the_golden(self):
        with mock.patch.object(pw, "sfm2hms", _wrapping_sfm2hms):
            self.assertGreater(_mismatches(), 0)

    def test_python_width_formatting_put_back_fails_the_golden(self):
        """``f'{v:06d}'`` writes 7 digits where IDL's ``i06`` writes ``******``."""
        with mock.patch.object(pw, "_idl_six_digit_int", lambda v: f"{int(v):06d}"):
            self.assertGreater(_mismatches(), 0)


if __name__ == "__main__":
    unittest.main()
