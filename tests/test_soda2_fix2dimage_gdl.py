# SPDX-License-Identifier: BSD-3-Clause
"""``fix2dimage`` against GDL running ``fix2dimage.pro`` unmodified
(``gdl_oracle/run_soda2_fix2dimage_bank.py``, golden
``tests/data/gdl_soda2_fix2dimage_golden.json``): every output word equal, and the
output type ULONG, on every case.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.fix2dimage import fix2dimage

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_fix2dimage_golden.json"


def _cases() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


class Fix2dimageAgainstGdl(unittest.TestCase):
    def test_every_case_ran_under_gdl(self):
        cases = _cases()
        self.assertGreaterEqual(len(cases), 16)
        self.assertEqual([c["name"] for c in cases if c["status"] != "OK"], [])
        self.assertEqual({c["TN"] for c in cases}, {"ULONG"})

    def test_port_equals_gdl(self):
        for c in _cases():
            with self.subTest(c["name"]):
                got = fix2dimage(np.array(c["image"], dtype=np.uint32))
                self.assertEqual(got.dtype, np.uint32)
                np.testing.assert_array_equal(got, np.array(c["OUT"], dtype=np.uint32))

    def test_regimes_are_exercised(self):
        """The early returns and the rewrite path each occur in the golden."""
        by = {c["name"]: c for c in _cases()}
        self.assertEqual(by["fewer_than_five"]["OUT"], by["fewer_than_five"]["image"])
        self.assertEqual(by["no_blank_two_back"]["OUT"], by["no_blank_two_back"]["image"])
        self.assertNotEqual(by["ncar_canonical"]["OUT"], by["ncar_canonical"]["image"])
        # `:26` subscript -1 is clipped to 0, never wrapped to the last slice.
        z = by["index_zero_only"]
        self.assertEqual(z["OUT"][-1], z["image"][-1])
        self.assertEqual(z["OUT"][0] >> 24, 0x55)


if __name__ == "__main__":
    unittest.main()
