# SPDX-License-Identifier: BSD-3-Clause
"""`arrayprobe_soda2.probespecs` against GDL's own evaluation of `soda2_probespecs.pro`.

Golden: `tests/data/gdl_soda2_probespecs_golden.json`, written by
`gdl_oracle/run_soda2_probespecs_bank.py` from the unmodified `.pro`. The
port's table was transcribed mechanically from the same `.pro`; this file is
what makes that transcription a claim rather than a hope -- every field of
every probe, value **and** IDL type, is compared exactly (float32 to float32,
no tolerance). The probe count is also read from the `.pro` text itself, so the
golden cannot silently cover fewer probes than the source defines.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe_soda2 import probespecs
from arrayprobe_soda2.probespecs import PROBE_NAMES, SOURCE_LINES, TAGS, soda2_probespecs

HERE = Path(__file__).resolve().parent
GOLDEN = json.loads((HERE / "data" / "gdl_soda2_probespecs_golden.json")
                    .read_text(encoding="utf-8"))
PRO = (_upstream.source("soda2") / "soda2_probespecs.pro")

#: IDL type code -> the numpy dtype the port must carry (None: a Python str).
_DTYPE_OF_CODE = {7: None, 2: np.dtype(np.int16), 3: np.dtype(np.int32),
                  4: np.dtype(np.float32)}


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("soda2")


def _assert_field(tc: unittest.TestCase, got, code: int, want, where: str) -> None:
    """One field: IDL type `code`, GDL value `want` (scalar or list)."""
    dtype = _DTYPE_OF_CODE[code]
    if dtype is None:
        tc.assertIsInstance(got, str, where)
        tc.assertEqual(got, want, where)
        return
    arr = np.atleast_1d(np.asarray(got))
    tc.assertEqual(arr.dtype, dtype, f"{where}: dtype")
    expect = np.atleast_1d(np.asarray(want)).astype(dtype)
    tc.assertEqual(arr.shape, expect.shape, f"{where}: shape")
    # Exact: GDL printed FLOAT at 9 significant digits, which round-trips float32.
    tc.assertTrue(np.array_equal(arr, expect), f"{where}: {arr!r} != {expect!r}")


def _assert_row(tc: unittest.TestCase, probe: dict, row: list, where: str = "") -> None:
    """A table row: the 18 tags in `base`'s order, each value and type GDL's."""
    tags, codes = GOLDEN["tags"], GOLDEN["types"]
    tc.assertEqual(list(probe), [t.lower() for t in tags], where)
    for tag, code, want in zip(tags, codes, row, strict=True):
        _assert_field(tc, probe[tag.lower()], code, want, f"{where}.{tag.lower()}")


class TestTableAgainstGDL(unittest.TestCase):
    @repo_only
    def test_the_golden_covers_every_block_in_the_source(self):
        # Independent of both the port and the golden: count `x=base` in the .pro.
        blocks = [ln for ln in PRO.read_text(encoding="latin-1").splitlines()
                  if re.fullmatch(r"\s*x=base\s*", ln)]
        self.assertEqual(len(blocks), 72)
        self.assertEqual(GOLDEN["n"], len(blocks))
        self.assertEqual(len(GOLDEN["rows"]), len(blocks))
        self.assertEqual(len(PROBE_NAMES), len(blocks))

    def test_tags_and_their_idl_types(self):
        self.assertEqual([t.lower() for t in GOLDEN["tags"]], list(TAGS))
        codes = {"STRING": 7, "INT": 2, "LONG": 3, "FLOAT": 4}
        self.assertEqual([codes[probespecs.IDL_TYPES[t]] for t in TAGS], GOLDEN["types"])
        self.assertEqual(GOLDEN["nvals"][TAGS.index("seatag")], 3)
        self.assertEqual(GOLDEN["nvals"][TAGS.index("dioderange")], 2)

    def test_every_field_of_every_probe(self):
        table = soda2_probespecs()
        self.assertIsInstance(table, list)
        self.assertEqual(len(table), len(GOLDEN["rows"]))
        for i, (probe, row) in enumerate(zip(table, GOLDEN["rows"], strict=True)):
            with self.subTest(i=i, probe=row[0]):
                _assert_row(self, probe, row, where=f"all[{i}]")

    @repo_only
    def test_2ds_wavelength_at_line_955_is_float32_785nm(self):
        # Z21 took the 2D-S laser wavelength from this line. The golden
        # is GDL's reading of it; the source line is read from the .pro.
        lines = PRO.read_text(encoding="latin-1").splitlines()
        self.assertEqual(lines[955 - 1].strip(), "x.wavelength=0.785e-6")
        self.assertEqual(SOURCE_LINES["2D-S Horizontal Array"], 939)
        i = PROBE_NAMES.index("2D-S Horizontal Array")
        gdl = GOLDEN["rows"][i][TAGS.index("wavelength")]
        port = soda2_probespecs(name="2D-S Horizontal Array")["wavelength"]
        self.assertIsInstance(port, np.float32)
        self.assertEqual(port, np.float32(gdl))
        self.assertEqual(port, np.float32(0.785e-6))
        # ... and not the double: the FLOAT sentinel in soda2_samplearea.pro:14
        # matches it, a double 0.785e-6 would not.
        self.assertNotEqual(float(port), 0.785e-6)

    def test_a_short_seatag_fills_the_leading_elements(self):
        # :156 `x.seatag=[33000, 32000]`, :496 `x.seatag=[33000]` (GDL-measured).
        wmi = soda2_probespecs(name="WMI CIP (SEA M300)")["seatag"]
        nrc = soda2_probespecs(name="NRC CIP (SEA M300)")["seatag"]
        np.testing.assert_array_equal(wmi, [33000, 32000, 0])
        np.testing.assert_array_equal(nrc, [33000, 0, 0])
        self.assertEqual(GOLDEN["rows"][PROBE_NAMES.index("NRC CIP (SEA M300)")]
                         [TAGS.index("seatag")], [33000, 0, 0])

    def test_numdiodes_is_float_here_and_int_in_update_ops_default(self):
        from arrayprobe_soda2.update_op import update_op
        self.assertEqual(soda2_probespecs(name="HVPS-3")["numdiodes"].dtype, np.float32)
        self.assertEqual(update_op({"probetype": "HVPS3", "res": np.float32(150),
                                    "endbins": np.array([0, 1]), "format": "SPEC",
                                    "fn": "x"})["numdiodes"].dtype, np.int16)


def _call(key: str):
    """The bank's `call`, as port keyword arguments."""
    return {
        "id_0": {"id": 0}, "id_71": {"id": 71}, "id_72": {"id": 72},
        "id_neg1": {"id": -1}, "id_array": {"id": [3, 5]},
        "id_array_oob": {"id": [0, 72]}, "id_array_neg": {"id": [-1, 2]},
        "name_miss": {"name": "nope"},
        "name_case": {"name": "2d-s horizontal array"},
        "name_trailing_blank": {"name": "2D-S Horizontal Array "},
        "name_array_1_miss": {"name": ["2D-S Horizontal Array"]},
        "name_array_1_hit": {"name": ["NASA Langley CAPS"]},
        "name_array_2": {"name": ["NASA Langley CAPS", "CAPS-Grey"]},
        "name_and_id": {"name": "HVPS-3", "id": 0},
        "fn_without_simulation": {"name": "HVPS-3", "fn": "x.dat"},
        "simulation_no_fn": {"name": "Simulation"},
        "simulation_fn_dat": {"name": "Simulation", "fn": "sim.dat"},
        "simulation_fn_txt": {"name": "Simulation", "fn": "no_such_model.txt"},
    }[key]


class TestLookupsAgainstGDL(unittest.TestCase):
    def test_every_name_returns_its_row(self):
        for rec in GOLDEN["by_name"]:
            i = rec["index"]
            with self.subTest(name=PROBE_NAMES[i]):
                self.assertEqual(rec["n"], 1)
                self.assertEqual(rec.get("equals_row"), i)
                got = soda2_probespecs(name=PROBE_NAMES[i])
                self.assertIsInstance(got, dict)
                _assert_row(self, got, GOLDEN["rows"][i], where=PROBE_NAMES[i])

    def test_every_banked_case(self):
        errors = {"name_array_2": ValueError, "simulation_fn_txt": NotImplementedError}
        for case in GOLDEN["cases"]:
            key = case["key"]
            with self.subTest(case=key):
                kwargs = _call(key)
                if case["status"] != "OK":
                    self.assertIn(key, errors, f"GDL {case['status']}: {case.get('error')}")
                    with self.assertRaises(errors[key]):
                        soda2_probespecs(**kwargs)
                    continue
                got = soda2_probespecs(**kwargs)
                items = got if isinstance(got, list) else [got]
                self.assertEqual(len(items), case["n"])
                # Under GDL a field read through a 1-element result is a scalar
                # (res_ndim 0); the port's dict is that reading.
                shape = case["field_shape"]
                self.assertEqual(isinstance(got, dict), shape["res_ndim"] == 0)
                self.assertEqual(shape["res_n"], len(items))
                if "row_indices" in case:
                    rows = [GOLDEN["rows"][j] for j in case["row_indices"]]
                    for probe, row in zip(items, rows, strict=True):
                        _assert_row(self, probe, row, where=key)
                else:
                    for probe, row in zip(items, case["rows"], strict=True):
                        self._assert_whole(probe, case["tags"], case["types"], row, key)

    def _assert_whole(self, probe: dict, tags, codes, row, where: str) -> None:
        self.assertEqual(set(probe), {t.lower() for t in tags}, where)
        for tag, code, want in zip(tags, codes, row, strict=True):
            _assert_field(self, probe[tag.lower()], code, want, f"{where}.{tag.lower()}")

    def test_the_case_map_matches_the_bank_exactly(self):
        keys = [c["key"] for c in GOLDEN["cases"]]
        for key in keys:
            _call(key)                    # KeyError if a bank case has no port call
        self.assertEqual(len(keys), 18)

    def test_the_two_stops_are_where_gdl_stops(self):
        by_key = {c["key"]: c for c in GOLDEN["cases"]}
        self.assertEqual(by_key["name_array_2"]["halted_at"], "SODA2_PROBESPECS 1465")
        self.assertEqual(by_key["simulation_fn_txt"]["halted_at"], "SODA2_UPDATE_OP 58")

    def test_a_miss_is_base_and_dofconst_is_its_only_nonzero(self):
        b = soda2_probespecs(name="nope")
        self.assertEqual(b["dofconst"], np.float32(3.0))
        self.assertEqual(b["probename"], "")
        np.testing.assert_array_equal(b["seatag"], [0, 0, 0])

    def test_a_lookup_returns_a_copy(self):
        a = soda2_probespecs(name="HVPS-3")
        a["res"] = np.float32(1.0)
        a["seatag"][0] = 7
        b = soda2_probespecs(name="HVPS-3")
        self.assertEqual(b["res"], np.float32(150.0))
        self.assertEqual(int(b["seatag"][0]), 0)


if __name__ == "__main__":
    unittest.main()
