# SPDX-License-Identifier: BSD-3-Clause
"""The GDL golden for the high-rate (2-D) PTH netCDF case of
`soda2_process_2d.pro:164-172` (`gdl_oracle/run_soda2_pth_highrate_bank.py`):
these tests pin what the unmodified IDL does, and that the port meets it."""
from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "gdl_soda2_pth_highrate_golden.json"


def _floats(hexes):
    return [struct.unpack(">f", bytes.fromhex(h))[0] for h in hexes]


class HighRatePthGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = {r["name"]: r for r in json.loads(GOLDEN.read_text(encoding="utf-8"))}

    def test_fixtures_are_tracked(self):
        for r in self.recs.values():
            self.assertTrue((DATA / r["fixture"]).is_file(), r["fixture"])

    def test_both_cases_ran_to_completion(self):
        self.assertEqual(set(self.recs), {"nc_hirate_tasx2d", "nc_hirate_both2d"})
        for r in self.recs.values():
            self.assertEqual(r["status"], "OK")
            self.assertEqual(r["GOT"], 1)

    def test_1d_time_2d_tasx_pairs_time_with_the_first_second_samples(self):
        # `:167`'s `and` truncates to the shorter (4) operand, and the 4x4
        # TASX flattens with sps fastest: times 100..103 pair with second
        # 100's four samples (150..153); the last record is forward-filled.
        r = self.recs["nc_hirate_tasx2d"]
        self.assertEqual(r["TN"], "FLOAT,5")
        self.assertEqual(_floats(r["TAS"]), [150.0, 151.0, 152.0, 153.0, 153.0])

    def test_both_2d_rounds_half_seconds_and_last_written_wins(self):
        # Flattened times 100, 100.5, ... 102.5 round half away from zero;
        # a later sample overwrites from its index onward.
        r = self.recs["nc_hirate_both2d"]
        self.assertEqual(r["TN"], "FLOAT,4")
        self.assertEqual(_floats(r["TAS"]), [150.0, 160.0, 170.0, 175.0])

    def test_port_equals_gdl_bit_for_bit(self):
        # Slice 2: `read_pth_ncdf` ports the 2-D path, so both cases match
        # the GDL float32 bit patterns exactly.
        from arrayprobe_soda2.pth_readers import read_pth_ncdf
        for r in self.recs.values():
            n = int(r["TN"].split(",")[1])
            got = read_pth_ncdf(DATA / r["fixture"], r["starttime"],
                                r["stoptime"], r["rate"], n)
            self.assertEqual([struct.pack(">f", x).hex().upper() for x in got],
                             [h.upper() for h in r["TAS"]], r["name"])


if __name__ == "__main__":
    unittest.main()
