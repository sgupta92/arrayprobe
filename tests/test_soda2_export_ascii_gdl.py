# SPDX-License-Identifier: BSD-3-Clause
"""``export_ascii.py`` against the Y1s GDL golden
(``gdl_oracle/run_soda2_export_ascii_bank.py``,
``tests/data/gdl_soda2_export_ascii_golden.json``). Every ``OK`` case's
written ``.txt`` text is asserted byte-for-byte; the ``HALTED`` case
(``minsize_above_bins``) asserts the port raises."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.export_ascii import MinsizeOutOfRange, soda2_export_ascii

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_export_ascii_golden.json"

ENDBINS = [50.0, 100.0, 150.0, 200.0, 300.0, 400.0, 600.0, 800.0, 1000.0]
NBINS = len(ENDBINS) - 1
MIDBINS = [(ENDBINS[i] + ENDBINS[i + 1]) / 2.0 for i in range(NBINS)]
CONC_ROW = [100.0, 500.0, 800.0, 600.0, 300.0, 100.0, 50.0, 10.0]
SPEC_ROW = [10.0, 50.0, 80.0, 60.0, 30.0, 10.0, 5.0, 1.0]


class _Data:
    pass


def _make_data(conc_rows, spec_rows, time_vals, *, water=0, res=10.0):
    d = _Data()
    d.op = dict(
        probetype="2DS", probeid="H", project="ORACLES", date="20160906",
        fn="raw.2DS", smethod="xsize", water=water, res=res,
        endbins=np.array(ENDBINS, dtype=np.float32), shortname="2DS",
        starttime=0.0, stoptime=10.0, rate=1.0, inttime_reject=1,
        dofconst=8.12, customdof=0.0,
    )
    d.time = np.array(time_vals)
    d.conc1d = np.array(conc_rows, dtype=np.float32)
    d.spec1d = np.array(spec_rows, dtype=np.float32)
    d.midbins = np.array(MIDBINS, dtype=np.float32)
    d.sa = np.full(NBINS, 1e-4, dtype=np.float32)
    d.date_processed = "2026-09-14T00:00:00"
    return d


#: Mirrors ``run_soda2_export_ascii_bank.py``'s ``CASES`` exactly -- same
#: inputs, so the same golden text applies.
_CASE_BUILDERS = {
    "ice_default": lambda: _make_data([CONC_ROW] * 3, [SPEC_ROW] * 3, [0.5, 1.5, 2.5]),
    "defaults_only": lambda: _make_data([CONC_ROW] * 3, [SPEC_ROW] * 3, [0.5, 1.5, 2.5]),
    "water_1": lambda: _make_data([CONC_ROW] * 3, [SPEC_ROW] * 3, [0.5, 1.5, 2.5], water=1),
    "water_2": lambda: _make_data([CONC_ROW] * 3, [SPEC_ROW] * 3, [0.5, 1.5, 2.5], water=2),
    "counts_1": lambda: _make_data([CONC_ROW] * 3, [SPEC_ROW] * 3, [0.5, 1.5, 2.5]),
    "nan_conc_side_effect": lambda: _make_data(
        [[float("nan")] + CONC_ROW[1:], CONC_ROW, CONC_ROW], [SPEC_ROW] * 3,
        [0.5, 1.5, 2.5]),
    "fractional_time": lambda: _make_data([CONC_ROW], [SPEC_ROW], [3600.6]),
    "gappy_spectrum": lambda: _make_data(
        [[100.0, 0.0, 0.0, 600.0, 300.0, 100.0, 50.0, 10.0]] * 3, [SPEC_ROW] * 3,
        [0.5, 1.5, 2.5]),
    "res_gt_15": lambda: _make_data([CONC_ROW] * 3, [SPEC_ROW] * 3, [0.5, 1.5, 2.5], res=25.0),
}

_CASE_KWARGS = {"counts_1": {"counts": 1}}


def _load() -> dict[str, dict]:
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {r["name"]: r for r in records}


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_export_ascii_bank.py first")
class TestOkCasesAgainstGdl(unittest.TestCase):
    def test_every_ok_case_matches_byte_for_byte(self):
        records = _load()
        ok_cases = [name for name, r in records.items() if r.get("status") == "OK"]
        self.assertGreaterEqual(len(ok_cases), 9, "expected >= 9 OK bank cases")
        for name in ok_cases:
            with self.subTest(case=name):
                data = _CASE_BUILDERS[name]()
                outfile = Path(tempfile.mktemp(suffix=".txt"))
                try:
                    soda2_export_ascii(data, str(outfile), **_CASE_KWARGS.get(name, {}))
                    got = outfile.read_text(encoding="utf-8")
                finally:
                    outfile.unlink(missing_ok=True)
                want = records[name]["text"]
                self.assertEqual(got.rstrip("\n"), want.rstrip("\n"))


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_export_ascii_bank.py first")
class TestHaltedCasesRaise(unittest.TestCase):
    def test_minsize_above_bins_is_recorded_halted_and_the_port_raises(self):
        records = _load()
        self.assertEqual(records["minsize_above_bins"]["status"], "HALTED")
        data = _CASE_BUILDERS["ice_default"]()
        with self.assertRaises(MinsizeOutOfRange):
            soda2_export_ascii(data, tempfile.mktemp(suffix=".txt"), minsize=2000.0)


if __name__ == "__main__":
    unittest.main()
