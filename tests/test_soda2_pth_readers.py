# SPDX-License-Identifier: BSD-3-Clause
"""``soda2_process_2d.pro:147-172`` -- the ASCII/CSV and netCDF PTH readers
against GDL running those lines verbatim
(``gdl_oracle/run_soda2_pth_readers_bank.py``, golden
``tests/data/gdl_soda2_pth_readers_golden.json``, fixtures
``tests/data/soda2_pth_*``, all synthetic)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import needs_file, repo_only  # noqa: E402

from arrayprobe_soda2.pth_readers import (
    PthReaderHalt,
    read_pth,
    read_pth_ascii,
    read_pth_ncdf,
)

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "gdl_soda2_pth_readers_golden.json"
GDL_ORACLE = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"


def _bank():
    if str(GDL_ORACLE) not in sys.path:
        sys.path.insert(0, str(GDL_ORACLE))
    import run_soda2_pth_readers_bank as bank
    return bank


def _numrecords(case: dict) -> int:
    return int((case["stoptime"] - case["starttime"]) / case["rate"] + 1)


def _hex(a: np.ndarray) -> list[str]:
    return [f"{v:08X}" for v in np.asarray(a, dtype=np.float32).view(np.uint32)]


def _run(case: dict) -> tuple[np.ndarray, int]:
    suffix = case["fixture"].rsplit(".", 1)[-1]
    return read_pth(DATA / case["fixture"], suffix, float(case["starttime"]),
                    float(case["stoptime"]), float(case["rate"]),
                    _numrecords(case))


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(f"{GOLDEN} is missing -- a tracked fixture")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_every_ok_case_matches_gdl_bit_for_bit(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                pth_tas, got_pth = _run(case)
                self.assertEqual(got_pth, case["GOT"], case["note"])
                self.assertEqual(pth_tas.dtype, np.float32)
                self.assertEqual(case["TN"], f"FLOAT,{_numrecords(case)}")
                self.assertEqual(_hex(pth_tas), case["TAS"], case["note"])
            checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_every_halted_case_raises_by_name(self):
        halted = [c for c in self.cases if c["status"] != "OK"]
        self.assertEqual([c["name"] for c in halted], ["nc_notasx"])
        for case in halted:
            with self.subTest(case=case["name"]):
                self.assertIn("TASX is undefined", case["stderr"])
                with self.assertRaises(PthReaderHalt) as ctx:
                    _run(case)
                self.assertIn("soda2_process_2d.pro:167", str(ctx.exception))

    def test_all_three_formats_are_banked(self):
        suffixes = {c["fixture"].rsplit(".", 1)[-1] for c in self.cases
                    if c["status"] == "OK"}
        self.assertEqual(suffixes, {"txt", "csv", "nc"})


class TheBankItself(unittest.TestCase):
    def test_the_text_fixtures_are_what_the_generator_writes(self):
        for name, blob in _bank().TEXT_FIXTURES.items():
            with self.subTest(fixture=name):
                self.assertEqual((DATA / name).read_bytes(), blob)

    @repo_only
    @needs_file("SODA2/abansemer-soda2-afcea15/soda2_process_2d.pro")
    def test_the_banked_lines_are_still_the_vendored_pth_block(self):
        block = _bank()._vendored_block()
        self.assertIn("readf,lun,v", block)
        self.assertIn("restorenc, op.pth, varlist=['TIME','TASX']", block)
        self.assertIn("(fields[1] lt 500)", block)

    def test_every_fixture_is_tiny(self):
        for case in json.loads(GOLDEN.read_text(encoding="utf-8")):
            self.assertLess((DATA / case["fixture"]).stat().st_size, 20_000)


class TheFindings(unittest.TestCase):
    """Behaviours the bank measured, pinned by name so a 'fix' fails here."""

    def test_line_161_sets_got_pth_even_when_no_row_was_accepted(self):
        pth_tas, got_pth = read_pth(DATA / "soda2_pth_allbad.csv", "csv",
                                    100.0, 102.0, 1.0, 3)
        self.assertEqual(got_pth, 1)
        np.testing.assert_array_equal(pth_tas, np.zeros(3, np.float32))

    def test_line_156_bounds_tas_at_500_not_the_400_of_lines_135_and_167(self):
        tas = read_pth_ascii(DATA / "soda2_pth_mixed.csv", 100.0, 1.0, 7)
        self.assertEqual(float(tas[2]), 450.0)

    def test_line_154_clamps_a_row_before_starttime_to_record_0(self):
        tas = read_pth_ascii(DATA / "soda2_pth_window.csv", 100.0, 1.0, 5)
        self.assertEqual(float(tas[0]), 111.0)

    def test_line_153_parses_as_float32_before_round(self):
        tas = read_pth_ascii(DATA / "soda2_pth_float32.txt", 36000.0, 1.0, 5)
        self.assertEqual(float(tas[1]), 100.0)  # a DOUBLE parse would give 200
        self.assertEqual(float(tas[2]), 200.0)

    def test_line_167_where_minus_one_lets_a_rejected_tas_through(self):
        tas = read_pth_ncdf(DATA / "soda2_pth_nogood.nc", 100.0, 104.0, 1.0, 5)
        np.testing.assert_array_equal(tas, np.array([0, 0, 0, 600, 600], np.float32))


class TheRefusals(unittest.TestCase):
    def test_a_two_dimensional_tasx_is_refused_by_name(self):
        from netCDF4 import Dataset
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "hirate.nc"
            with Dataset(p, "w", format="NETCDF3_CLASSIC") as ds:
                ds.createDimension("Time", 2)
                ds.createDimension("sps25", 25)
                ds.createVariable("Time", "i4", ("Time",))[:] = [100, 101]
                v = ds.createVariable("TASX", "f4", ("Time", "sps25"))
                v[:, :] = np.full((2, 25), 150.0, dtype=np.float32)
            # Ported since the high-rate GDL golden: no longer refused.
            got = read_pth_ncdf(p, 100.0, 101.0, 1.0, 2)
        self.assertEqual(got.tolist(), [150.0, 150.0])

    def test_an_unknown_suffix_is_not_this_modules(self):
        with self.assertRaises(ValueError):
            read_pth(DATA / "soda2_pth_plain.txt", "sav", 100.0, 105.0, 1.0, 6)


class TheSuffixIsStrsplitsLastToken(unittest.TestCase):
    """``soda2_process_2d.pro:129`` ``suffix=(strsplit(op.pth,'.',/extract))[-1]``:
    ``strsplit`` drops empty tokens, and a name with no ``.`` is one token.
    Measured under GDL with its own ``strsplit.pro`` (each pair below is its
    printed ``[in] -> [out]``). A trailing dot matters on Windows, which
    resolves ``tas.nc.`` to ``tas.nc``: IDL reads it as netCDF."""

    GDL = {"a.nc": "nc", "a.nc.": "nc", "nc": "nc", "dir.v2/file": "v2/file",
           "...": "", "a..csv": "csv", ".sav": "sav", "x": "x"}

    def test_every_measured_case(self):
        from arrayprobe_soda2.pth_readers import pth_suffix
        for pth, want in self.GDL.items():
            with self.subTest(pth=pth):
                self.assertEqual(pth_suffix(pth), want)

    def test_the_driver_and_the_export_record_use_it(self):
        import inspect

        from arrayprobe_soda2 import export_ncdf, process_2d
        for mod in (process_2d, export_ncdf):
            with self.subTest(module=mod.__name__):
                src = inspect.getsource(mod)
                self.assertIn("pth_suffix(", src)
                self.assertNotIn('rsplit(".", 1)[-1]', src)


if __name__ == "__main__":
    unittest.main()
