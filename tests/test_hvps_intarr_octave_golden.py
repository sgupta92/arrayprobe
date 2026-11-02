# SPDX-License-Identifier: BSD-3-Clause
"""HVPS inter-arrival thresholds: the port against MATLAB-under-Octave, per block.

The golden ``tests/data/octave_hvps_intarr_thresholds_golden.json`` records the per-block
thresholds the unmodified ``IntArrAnalysis_time.m`` writes under GNU Octave 11.3 (two shims:
``netcdf.open``'s default mode and ``histcounts``), beside the port's ``intarr-threshold
--blocks 5`` output for the same HVPS proc files (2016-09-06 and 2017-08-26).

The proc files and the port's threshold files are decoded output and are not tracked, so this
module cannot recompute the port's side. It asserts the golden's own record: the agreeing blocks
agree within the stated tolerance, the one differing block (2016-09-06 block 1) differs by the
recorded amount and carries its attribution, the block boundaries follow ``ceil(n/5)``, and no
block holds the default threshold.
"""

import json
import math
import unittest
from pathlib import Path

GOLDEN = Path(__file__).parent / "data" / "octave_hvps_intarr_thresholds_golden.json"


def _load():
    with GOLDEN.open(encoding="utf-8") as fh:
        return json.load(fh)


class TestGoldenRecord(unittest.TestCase):
    def setUp(self):
        self.g = _load()
        self.tol = self.g["rel_tolerance"]

    def test_provenance_names_octave_version_and_shims(self):
        self.assertEqual(self.g["octave"]["version"], "GNU Octave 11.3.0")
        self.assertIn("unmodified", self.g["octave"]["source"])
        for shim in ("+netcdf/open.m", "histcounts.m"):
            self.assertIn(shim, self.g["octave"]["shims"])
        self.assertIn("Robust", self.g["octave"]["oracle_caveat"])

    def test_blocks_follow_ceil_n_over_5(self):
        for f in self.g["flights"]:
            n = f["particles"]
            size = math.ceil(n / 5)
            self.assertEqual(len(f["blocks"]), 5, f["flight"])
            for b in f["blocks"]:
                k = b["block"] - 1
                self.assertEqual(b["first"], k * size, (f["flight"], b["block"]))
                self.assertEqual(b["last"], min((k + 1) * size, n) - 1, (f["flight"], b["block"]))

    def test_agreeing_blocks_agree_within_tolerance(self):
        n_agree = 0
        for f in self.g["flights"]:
            for b in f["blocks"]:
                if b["agrees"]:
                    n_agree += 1
                    self.assertTrue(
                        math.isclose(b["port"], b["octave"], rel_tol=self.tol),
                        (f["flight"], b["block"], b["port"], b["octave"]),
                    )
        self.assertEqual(n_agree, 9)

    def test_170826_agrees_in_all_five_blocks(self):
        f = next(x for x in self.g["flights"] if x["flight"] == "170826073738")
        self.assertTrue(all(b["agrees"] for b in f["blocks"]))

    def test_160906_block_1_is_the_one_attributed_difference(self):
        f = next(x for x in self.g["flights"] if x["flight"] == "160906064343")
        differing = [b for b in f["blocks"] if not b["agrees"]]
        self.assertEqual([b["block"] for b in differing], [1])
        b = differing[0]
        self.assertEqual(b["octave"], 2.56535e-4)
        self.assertEqual(b["port"], 4.12125e-4)
        self.assertFalse(math.isclose(b["port"], b["octave"], rel_tol=self.tol))
        self.assertIn("does not explain", b["attribution"])
        self.assertTrue(all(b2["agrees"] for b2 in f["blocks"][1:]))

    def test_no_block_holds_the_default_threshold(self):
        default = self.g["default_threshold_s"]
        self.assertFalse(self.g["default_held_by_any_block"])
        for f in self.g["flights"]:
            for b in f["blocks"]:
                for side in ("port", "octave"):
                    self.assertFalse(
                        math.isclose(b[side], default, rel_tol=self.tol),
                        (f["flight"], b["block"], side),
                    )


if __name__ == "__main__":
    unittest.main()
