# SPDX-License-Identifier: BSD-3-Clause
"""``soda2_export_ascii.pro:19-43`` (the 1D2D housekeeping columns): the GDL
golden is tracked and well-formed, and the port's written text equals every
case's GDL text byte for byte. The one unpinned input (non-integer edge
fields) is still refused by name."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.export_ascii import (
    OneD2DHousekeepingNotPorted,
    soda2_export_ascii,
)

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_export_ascii_1d2d_golden.json"
NAMES = {"modes_and_edges", "edge_sum_256", "house_one_tag", "no_house_tag"}
HOUSE_HEADER = ("ProbeMode", "EdgeReject")


def _load():
    return {r["name"]: r for r in json.loads(GOLDEN.read_text(encoding="utf-8"))}


def _house_columns(text: str) -> list[tuple[int, int]]:
    lines = text.splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.split()[:1] == ["Time"])
    cols = lines[head].split()
    pm, er = cols.index("ProbeMode"), cols.index("EdgeReject")
    return [(int(ln.split()[pm]), int(ln.split()[er])) for ln in lines[head + 1:]
            if ln.strip() and not ln.startswith("-")]


class GoldenIsWellFormed(unittest.TestCase):
    def test_every_case_is_present_and_ran(self):
        recs = _load()
        self.assertEqual(set(recs), NAMES)
        for name, rec in recs.items():
            self.assertEqual(rec["status"], "OK", name)
            self.assertTrue(rec["text"].strip(), name)

    def test_house_columns_appear_only_when_house_has_two_or_more_tags(self):
        recs = _load()
        for name in ("modes_and_edges", "edge_sum_256"):
            for col in HOUSE_HEADER:
                self.assertIn(col, recs[name]["text"], name)
        for name in ("house_one_tag", "no_house_tag"):
            for col in HOUSE_HEADER:
                self.assertNotIn(col, recs[name]["text"], name)

    def test_probe_mode_and_edge_flag_values(self):
        recs = _load()
        self.assertEqual(_house_columns(recs["modes_and_edges"]["text"]),
                         [(1, 0), (2, 1), (3, 1), (3, 1), (1, 1)])
        # byte(128+128) wraps to 0 before the <1 clip; byte(300) is 44, clipped to 1.
        self.assertEqual(_house_columns(recs["edge_sum_256"]["text"]), [(1, 0), (1, 1)])


ENDBINS = [50.0, 100.0, 150.0, 200.0, 300.0, 400.0, 600.0, 800.0, 1000.0]
NBINS = len(ENDBINS) - 1
MIDBINS = [(ENDBINS[i] + ENDBINS[i + 1]) / 2.0 for i in range(NBINS)]
ROW_C = [100.0, 500.0, 800.0, 600.0, 300.0, 100.0, 50.0, 10.0]
ROW_S = [10.0, 50.0, 80.0, 60.0, 30.0, 10.0, 5.0, 1.0]


class _Data:
    pass


def _make_data(ntimes: int, house: dict | None) -> _Data:
    """Mirrors the bank's ``_script_for`` (``_data_block`` with
    ``probetype`` set to ``'1D2D'``, plus ``house`` as INT fields)."""
    d = _Data()
    d.op = dict(
        probetype="1D2D", probeid="H", project="ORACLES", date="20160906",
        fn="raw.2DS", smethod="xsize", water=0, res=10.0,
        endbins=np.array(ENDBINS, dtype=np.float32), shortname="2DS",
        starttime=0.0, stoptime=10.0, rate=1.0, inttime_reject=1,
        dofconst=8.12, customdof=0.0,
    )
    d.time = np.array([0.5 + i for i in range(ntimes)])
    d.conc1d = np.array([ROW_C] * ntimes, dtype=np.float32)
    d.spec1d = np.array([ROW_S] * ntimes, dtype=np.float32)
    d.midbins = np.array(MIDBINS, dtype=np.float32)
    d.sa = np.full(NBINS, 1e-4, dtype=np.float32)
    d.date_processed = "2026-09-14T00:00:00"
    if house is not None:
        d.house = {k: np.array(v, dtype=np.int16) for k, v in house.items()}
    return d


def _port_text(data: _Data) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.txt"
        soda2_export_ascii(data, outfile=str(out))
        return out.read_bytes().decode("utf-8")


class PortMatchesGdlByteForByte(unittest.TestCase):
    def test_every_case_equals_the_gdl_text(self):
        recs = _load()
        for name in sorted(NAMES):
            rec = recs[name]
            with self.subTest(case=name):
                self.assertEqual(_port_text(_make_data(rec["ntimes"], rec["house"])),
                                 rec["text"])


class UnpinnedInputStillRefused(unittest.TestCase):
    def test_float_edge_fields_are_refused_by_name(self):
        d = _make_data(2, {"dofnumreject": [0, 0], "dofpercent": [0, 0],
                           "leftreject": [0, 1], "rightreject": [0, 1]})
        d.house["leftreject"] = d.house["leftreject"].astype(np.float32)
        with self.assertRaises(OneD2DHousekeepingNotPorted):
            soda2_export_ascii(d, outfile="unused.txt")


if __name__ == "__main__":
    unittest.main()
