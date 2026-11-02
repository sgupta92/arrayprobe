# SPDX-License-Identifier: BSD-3-Clause
# ruff: noqa: E501  (golden field lists mirror the bank's own long lines)
"""CIP-1: the SODA-2
driver's SEA/CIP route through ``soda2_process_2d``, asserted against the
composition-level GDL golden the same run must beat --
``gdl_oracle/run_soda2_cip_bank.py --driver`` running the real, unmodified
``soda2_process_2d.pro`` end to end (never the sub-function walk
``test_soda2_cip_gdl.py`` already covers, 12/12 OK -- that bank is this
lane's bisector: if a per-buffer field disagreed there, this would not be a
driver defect).

Two cases in the golden, one compared bit-for-bit here:

- ``cip_single_tag`` (``seatag:[33000]``) -- the case the port must match.
- ``cip_und_tags`` (``seatag:[33000, 32000, 0]``) -- recorded now for CIP-2
  (``process_cip1d_sea`` is not ported; this port refuses it by name).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d  # noqa: E402
from test_soda2_process_2d import (  # noqa: E402
    _P2D_FLOAT_FIELDS,
    _P2D_INT_FIELDS,
    _flat_f,
    _hex32,
    _hex64,
)

DATA = HERE / "data"
FIXTURE = DATA / "soda2_sea_cip_fixture.sea"
DRIVER_GOLDEN = DATA / "gdl_soda2_cip_driver_golden.json"

#: The op ``run_soda2_cip_bank.py --driver`` built,
#: mirrored field for field; only ``seatag`` varies between the two cases.
_CIP_DRIVER_BASE: dict = dict(
    fn=str(FIXTURE), date="09062016", starttime=25800.0, stoptime=25830.0,
    format="SEA", subformat=1, probetype="CIP", res=25.0, yres=25.0, armwidth=6.0,
    numdiodes=64, probeid="", shortname="CIP", greythresh=0, wavelength=0.658e-6,
    dofconst=3.0,
    endbins=[25, 50, 75, 100, 125, 150, 200, 250, 300, 350, 400, 475, 550, 625,
             700, 800, 900, 1000, 1200, 1400, 1600],
    # IDL bare decimal literals are FLOAT: `arendbins` must arrive as a
    # float32 array so `_psopts`'s float64 widen reproduces IDL's rounding
    # (0.7 as FLOAT is 0.69999999..., not exact) -- a plain Python-float list
    # skips that rounding and puts a bin edge ~1e-8 away from IDL's, which
    # flipped one particle's `asprbin` (SPEC2DASPR/HIST3D) before this fix.
    # Measured, not a port defect: `_base_op`'s own SPEC goldens never hit an
    # edge value sensitive to it ([0.0, 0.5, 1.0] round exactly).
    arendbins=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
                       dtype=np.float32),
    rate=1, smethod="fastcircle", pth="", particlefile=0, inttime_reject=0,
    stuckbits=0, water=0, fixedtas=np.float32(0.0), project="", timeoffset=0.0,
    eawmethod="centerin", savfile=0,
)


def _cip_op(seatag: list[int]) -> dict:
    op = dict(_CIP_DRIVER_BASE)
    op["seatag"] = np.array(seatag, dtype=np.int32)
    return op


def _load_driver_golden() -> dict[str, dict]:
    records = json.loads(DRIVER_GOLDEN.read_text(encoding="utf-8"))
    return {r["name"]: r for r in records}


class AgainstTheCipDriverGolden(unittest.TestCase):
    """The discriminating case."""
    golden: Any  # assigned in setUpClass/setUp; see there for the value

    # Decide in setUpClass, raise in setUp: a SkipTest from setUpClass skips the whole class
    # invisibly -- the suite reports one fewer TEST rather than one more SKIP, so a missing
    # golden becomes indistinguishable from a class nobody wrote
    # (tests/test_class_level_skips_are_visible.py).
    @classmethod
    def setUpClass(cls) -> None:
        cls.golden = _load_driver_golden() if DRIVER_GOLDEN.is_file() else None

    def setUp(self) -> None:
        if self.golden is None:
            self.skipTest(
                f"{DRIVER_GOLDEN} missing -- run "
                "scripts/validation/gdl/run_soda2_cip_bank.py --driver first")

    def test_cip_single_tag_matches_idl_bit_for_bit(self) -> None:
        rec = self.golden.get("cip_single_tag")
        if rec is None:
            self.fail("cip_single_tag missing from the driver golden")
        if rec["status"] == "HALTED":
            self.skipTest(f"cip_single_tag: GDL halted -- {rec.get('message')} "
                          f"@ {rec.get('halt_at')}")
        self.assertEqual(rec["status"], "OK", rec)

        d = soda2_process_2d(_cip_op([33000]))
        self.assertIsInstance(d, ProcessData)
        assert isinstance(d, ProcessData)
        self.assertEqual(int(d.time.size), rec["NUMRECORDS"], "NUMRECORDS")

        for hexkey, field_name in _P2D_FLOAT_FIELDS.items():
            if hexkey not in rec:
                continue
            value = getattr(d, field_name)
            hexer = _hex64 if np.asarray(value).dtype == np.float64 else _hex32
            got = [hexer(v) for v in _flat_f(value)]
            with self.subTest(key=hexkey):
                self.assertEqual(got, rec[hexkey], f"cip_single_tag/{hexkey}")

        if "TIMEHEX" in rec:
            got = [_hex64(v) for v in _flat_f(d.time)]
            with self.subTest(key="TIMEHEX"):
                self.assertEqual(got, rec["TIMEHEX"], "cip_single_tag/TIMEHEX")

        for key, field_name in _P2D_INT_FIELDS.items():
            if key not in rec:
                continue
            got = [int(v) for v in _flat_f(getattr(d, field_name))]
            with self.subTest(key=key):
                self.assertEqual(got, rec[key], f"cip_single_tag/{key}")

        # `house={op:op}` (`soda2_process_2d.pro:394`) -- the placeholder
        # this port's SeaHouse mirrors; no time/tas/nb tag to compare.
        self.assertEqual(rec.get("HOUSETAGS"), "OP")
        self.assertEqual(list(d.house.__dataclass_fields__), ["op"])

    def test_cip_und_tags_golden_is_banked_for_cip_2(self) -> None:
        rec = self.golden.get("cip_und_tags")
        if rec is None:
            self.fail("cip_und_tags missing from the driver golden -- CIP-2 "
                      "would start with no oracle")
        self.assertIn("status", rec)


class SeatagMultiTag(unittest.TestCase):
    """`soda2_process_2d.pro:397-398`: `n_elements(op.seatag) ge 2` fires
    `process_cip1d_sea, op, /nowrite, data=house`, so the run completes and
    `data.house` is that routine's struct (GDL-matched field by field in
    `test_soda2_cip1d_sea_golden.py`)."""

    def _assert_house_is_cip1d_sea(self, op: dict) -> None:
        from arrayprobe_soda2.process_hk import process_cip1d_sea
        from arrayprobe_soda2.update_op import update_op
        d = soda2_process_2d(op)
        self.assertIsInstance(d, ProcessData)
        assert isinstance(d, ProcessData)
        self.assertIsInstance(d.house, dict)
        want = process_cip1d_sea(update_op(dict(op)))
        self.assertEqual(sorted(d.house), sorted(want))
        for k in ("time", "spec1d", "tas_pitot", "particlecounter"):
            with self.subTest(field=k):
                np.testing.assert_array_equal(np.asarray(d.house[k]),
                                              np.asarray(want[k]))

    def test_cip_und_tags_runs_process_cip1d_sea(self) -> None:
        self._assert_house_is_cip1d_sea(_cip_op([33000, 32000, 0]))

    def test_seatag_default_runs_process_cip1d_sea(self) -> None:
        """`update_op` defaults `seatag` to the 3-element `[33000,0,0]`
        (`update_op.py:66`), so a bare CIP op takes the same branch and
        reaches `readseabuffer_caps.pro:5`'s own `stop` on tag 0."""
        from arrayprobe_soda2.sea import SeaReadError
        op = dict(_CIP_DRIVER_BASE)
        op.pop("seatag", None)
        with self.assertRaises(SeaReadError):
            soda2_process_2d(op)

    def test_multi_tag_split_run_equals_serial(self) -> None:
        """`jobs=2` on a multi-tag SEA run: `house` is built in the parent
        before the loop (`process_2d.py`, `:397-398`) and the split reads it
        only for SPEC's probetas, so the result must equal serial exactly --
        every array field and every `house` field, `np.array_equal`.

        The split must be real, or this compares serial with serial: the parts
        are read from `process_2d_parallel.chunk_bounds`, the function
        `run_parallel_loop` itself calls to partition `[firstbuff, lastbuff]`
        (wrapped here, so it still computes the same result), and the test
        fails unless that call happened and returned at least two non-empty
        parts. A fixture too small to split fails here rather than passing
        vacuously."""
        import dataclasses
        from unittest import mock

        from arrayprobe_soda2 import process_2d_parallel as p2p
        op = _cip_op([33000, 32000, 0])
        a = soda2_process_2d(dict(op), jobs=1)
        seen: list[list[tuple[int, int]]] = []
        real_bounds = p2p.chunk_bounds

        def _spy(firstbuff: int, lastbuff: int, nchunks: int) -> list[tuple[int, int]]:
            out = real_bounds(firstbuff, lastbuff, nchunks)
            seen.append(out)
            return out

        with mock.patch.object(p2p, "chunk_bounds", _spy):
            b = soda2_process_2d(dict(op), jobs=2)
        self.assertEqual(len(seen), 1,
                         "jobs=2 never reached run_parallel_loop's partition: the run was serial")
        parts = [(lo, hi) for lo, hi in seen[0] if hi > lo]
        self.assertGreaterEqual(
            len(parts), 2,
            f"fixture does not split at jobs=2 (parts={seen[0]}): the equality below would be "
            "serial against serial")
        assert isinstance(a, ProcessData) and isinstance(b, ProcessData)
        self.assertEqual(sorted(a.house), sorted(b.house))
        for k in a.house:
            with self.subTest(house=k):
                va, vb = a.house[k], b.house[k]
                if isinstance(va, np.ndarray) or isinstance(vb, np.ndarray):
                    self.assertTrue(np.array_equal(np.asarray(va), np.asarray(vb),
                                                   equal_nan=True))
                elif k != "op":
                    self.assertEqual(va, vb)
        for f in dataclasses.fields(a):
            va, vb = getattr(a, f.name), getattr(b, f.name)
            if isinstance(va, np.ndarray):
                with self.subTest(field=f.name):
                    self.assertTrue(np.array_equal(va, vb, equal_nan=True))

    def test_cipg_probetype_refused(self) -> None:
        with self.assertRaises(NotImplementedError):
            soda2_process_2d(_cip_op([33000]) | {"probetype": "CIPG"})


if __name__ == "__main__":
    unittest.main()
