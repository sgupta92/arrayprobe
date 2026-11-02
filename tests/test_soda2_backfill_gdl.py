# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.backfill.soda2_backfill`` against the GDL golden
``tests/data/gdl_soda2_backfill_golden.json`` (``gdl_oracle/run_soda2_backfill_bank.py``).

The golden ran the vendored ``soda2_backfill.pro`` with an ``erode.pro``
STAND-IN (GDL has no ``ERODE``), so it confirms the routine's own logic --
early returns, the REPEAT loop, the origin ``x0`` per pass, the growing
element, the stopping rule and the returned IDL type -- not ``ERODE`` (layer 3).
Every comparison is exact: output values, dims, IDL type, and the sequence
of erosions (element length, origin value, origin IDL type)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe_soda2 import backfill as bf

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_backfill_golden.json"

_CTOR = {"bytarr": np.uint8, "fltarr": np.float32}
_TNAME = {np.dtype(np.uint8): "BYTE", np.dtype(np.float32): "FLOAT"}


def _x0_tname(x0: object) -> str:
    # The port mirrors IDL's literal types: x0=0 / x0=count are INT/LONG
    # scalars (Python int), x0=count/2.0 is FLOAT (Python float).
    return "FLOAT" if isinstance(x0, float) else "INT"


def _image(rec: dict) -> np.ndarray:
    dt = _CTOR[rec["ctor"]]
    nd, ns = rec["ndiodes"], rec["nslices"]
    if ns is None:
        img = np.zeros(nd, dtype=dt)
        for d in rec["pixels"].get("0", []):
            img[d] = 1
        return img
    img = np.zeros((ns, nd), dtype=dt)  # (slice, diode)
    for s, ds in rec["pixels"].items():
        for d in ds:
            img[int(s), d] = 1
    return img


class BackfillAgainstGdl(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        data = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.header, cls.records = data[0], data[1:]

    def test_header_names_the_shim_as_a_stand_in(self) -> None:
        self.assertIn("STAND-IN", self.header["oracle_shims"][0])
        self.assertEqual(self.header["erode_edge_rule"], "zero_outside_shim_unconfirmed")
        self.assertEqual(bf.ERODE_EDGE_RULE, "zero_outside")

    def test_every_case_ran(self) -> None:
        self.assertEqual(len(self.records), 16)
        self.assertTrue(all(r["status"] == "OK" for r in self.records))

    def test_the_bank_reaches_every_branch(self) -> None:
        tn = {c[2] for r in self.records for c in r["ERODE_CALLS"]}
        self.assertEqual(tn, {"INT", "FLOAT"})  # x0=0/count and x0=count/2.0
        self.assertTrue(any(len(r["ERODE_CALLS"]) >= 10 for r in self.records))
        self.assertTrue(any(not r["ERODE_CALLS"] for r in self.records))

    def test_every_output_exact(self) -> None:
        for rec in self.records:
            with self.subTest(case=rec["name"]):
                img = _image(rec)
                calls: list[list] = []
                real = bf._erode_1d

                def spy(orig, n, x0, _real=real, _calls=calls):
                    _calls.append([n, f"{float(x0):.4f}", _x0_tname(x0)])
                    return _real(orig, n, x0)

                with mock.patch.object(bf, "_erode_1d", side_effect=spy):
                    out = bf.soda2_backfill(img)
                self.assertEqual(calls, rec["ERODE_CALLS"], "erode call sequence")
                self.assertEqual(_TNAME[out.dtype], rec["TNAME"], "IDL type")
                dims = [out.shape[0]] if out.ndim == 1 else [out.shape[1], out.shape[0]]
                self.assertEqual(dims, rec["DIMS"], "dims [diode, slice]")
                self.assertEqual([f"{float(v):.4f}" for v in out.reshape(-1)], rec["OUT"],
                                 "values, IDL memory order")


if __name__ == "__main__":
    unittest.main()
