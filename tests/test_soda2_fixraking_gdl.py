# SPDX-License-Identifier: BSD-3-Clause
"""``fixraking`` against GDL running ``fixraking.pro`` unmodified
(``gdl_oracle/run_soda2_fixraking_bank.py``, golden
``tests/data/gdl_soda2_fixraking_golden.json``).

GDL confirms the nothing-crosses rule (``where`` gives -1 and the last
element is set) and the edge-mirror border on every case: the low edge
mirrors without repeating, the high edge repeats. The unmasked
even-modetype (4, 6) cases pinned the low diode edge.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.fixraking import (
    FixrakingIncompatibleDimensions,
    FixrakingUndefinedKernel,
    fixraking,
)

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_fixraking_golden.json"


def _cases() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _port_flat(case: dict) -> np.ndarray:
    img = np.array(case["image"], dtype=np.uint8)
    if img.shape[1] == 1:                       # IDL bytarr(n, 1) is 1-D
        img = img[:, 0]
    return fixraking(img, case["modetype"]).ravel(order="F")


class FixrakingAgainstGdl(unittest.TestCase):
    def test_every_case_ran_under_gdl(self):
        cases = _cases()
        halts = {c["name"] for c in cases if c["status"] != "OK"}
        self.assertEqual(halts, {"halt_random_8x7_modetype_7", "halt_random_8x7_modetype_8",
                                 "one_d_8_modetype_3", "one_d_8_modetype_5"})

    def test_regimes_present(self):
        names = {c["name"] for c in _cases()}
        for m in range(1, 7):
            self.assertTrue(any(n.endswith(f"modetype_{m}") for n in names), m)
        for tag in ("odd_diodes", "edge_mirror", "nothing_crosses"):
            self.assertTrue(any(tag in n for n in names), tag)

    def test_port_equals_gdl(self):
        for c in _cases():
            if c["status"] != "OK":
                continue
            with self.subTest(c["name"]):
                np.testing.assert_array_equal(_port_flat(c), np.array(c["FLAT"]))

    def test_port_raises_where_gdl_halts(self):
        for c in _cases():
            if c["status"] == "OK":
                continue
            with self.subTest(c["name"]):
                gdl_text = c.get("stdout", "") + c.get("stderr", "")
                if "Variable is undefined: KERNEL" in gdl_text:
                    exc, msg = FixrakingUndefinedKernel, "Variable is undefined: KERNEL"
                else:
                    self.assertIn("Incompatible dimensions for Array and Kernel", gdl_text)
                    exc, msg = (FixrakingIncompatibleDimensions,
                                "Incompatible dimensions for Array and Kernel")
                with self.assertRaisesRegex(exc, msg):
                    _port_flat(c)

    def test_nothing_crosses_sets_the_last_element_in_gdl(self):
        for c in _cases():
            if c["name"].startswith("nothing_crosses_6x5"):
                flat = np.array(c["FLAT"])
                self.assertEqual(int(flat.sum()), 1)
                self.assertEqual(int(flat[-1]), 1)

    def test_every_case_is_compared(self):
        self.assertEqual(len(_cases()), 31)


if __name__ == "__main__":
    unittest.main()
