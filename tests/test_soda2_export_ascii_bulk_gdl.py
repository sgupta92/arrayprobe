# SPDX-License-Identifier: BSD-3-Clause
"""``export_ascii.compute_bulk_simple`` against GDL, bit for bit and type for
type (bank ``gdl_oracle/run_soda2_compute_bulk_simple_bank.py``,
golden ``tests/data/gdl_soda2_compute_bulk_simple_golden.json``).

Every ``OK`` case compares all fifteen tags of the returned structure: the IDL
type code (4, FLOAT, for every tag) against the port's dtype, the number of
dimensions, and every element's raw 32-bit pattern. The mutation class puts
back each earlier port's arithmetic choice in turn and requires the golden to catch
it, so the exact comparison cannot pass by testing nothing.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe_soda2 import export_ascii
from arrayprobe_soda2.export_ascii import compute_bulk_simple

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_compute_bulk_simple_golden.json"

#: IDL ``size(/type)`` codes -> numpy dtypes.
_IDL_TYPE = {4: np.float32, 5: np.float64}

TAGS = ("iwc", "lwc", "dmass", "dmedianmass", "dmassw", "dmassmelted", "dbz",
        "dbzw", "nt", "mvd", "mnd", "msd", "msdnorm", "massparam", "massparamlwc")


def _floats(bits: list[int], shape: tuple[int, ...] | None = None) -> np.ndarray:
    arr = np.array(bits, dtype=np.int32).view(np.float32)
    return arr.reshape(shape, order="F") if shape else arr


def _inputs(case: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    conc = _floats(case["conc_bits"], tuple(case["conc_shape"]))
    endbins = _floats(case["endbins_bits"])
    kw: dict = {k: case[k] for k in ("binstart", "binstop") if k in case}
    for k in ("acoeff", "bcoeff"):
        if k + "_bits" in case:
            kw[k] = _floats([case[k + "_bits"]])[0]
    return conc, endbins, kw


def _load() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _ok_cases() -> list[dict]:
    return [c for c in _load()["cases"] if c["status"] == "OK"]


def _mismatches() -> int:
    """Total bit-pattern mismatches over every tag of every OK case."""
    bad = 0
    for case in _ok_cases():
        conc, endbins, kw = _inputs(case)
        out = compute_bulk_simple(conc.copy(), endbins, **kw)
        for tag, want in case["tags"].items():
            got = np.asarray(out[tag], dtype=np.float32).ravel(order="F").view(np.int32)
            wb = np.array(want["bits"], dtype=np.int32)
            bad += int(np.sum(got != wb)) if got.shape == wb.shape else wb.size
    return bad


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_compute_bulk_simple_bank.py first")
class TestEveryTagMatchesGdlBitForBit(unittest.TestCase):
    def test_bank_has_every_case_ok(self):
        cases = _load()["cases"]
        self.assertGreaterEqual(len(cases), 12)
        self.assertEqual([c["name"] for c in cases if c["status"] != "OK"], [])

    def test_type_dimensions_and_bits_of_every_tag(self):
        for case in _ok_cases():
            conc, endbins, kw = _inputs(case)
            out = compute_bulk_simple(conc.copy(), endbins, **kw)
            self.assertEqual(set(case["tags"]), set(TAGS))
            for tag in TAGS:
                want = case["tags"][tag]
                with self.subTest(case=case["name"], tag=tag):
                    got = np.asarray(out[tag])
                    self.assertEqual(got.dtype, _IDL_TYPE[want["idl_type"]])
                    self.assertEqual(got.ndim, want["n_dimensions"])
                    got_bits = got.ravel(order="F").view(np.int32).tolist()
                    self.assertEqual(got_bits, want["bits"])

    def test_the_comparison_has_non_trivial_values(self):
        """Guards the check: an all-zero golden would match anything zero."""
        nonzero = 0
        for case in _ok_cases():
            for tag in ("iwc", "nt", "mvd", "mnd", "dmedianmass"):
                vals = _floats(case["tags"][tag]["bits"])
                nonzero += int(np.count_nonzero(np.isfinite(vals) & (vals != 0)))
        self.assertGreater(nonzero, 40)


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_compute_bulk_simple_bank.py first")
class TestIdlTotalSemantics(unittest.TestCase):
    """The bank's ``semantics`` probe: ``total([1e8, 1 x16, -1e8])`` on FLOAT."""

    PROBE = np.array([1e8] + [1.0] * 16 + [-1e8], dtype=np.float32)

    def test_gdl_total_is_float_and_sequential(self):
        sem = _load()["semantics"]
        self.assertEqual(sem["total_type"], 4)
        self.assertEqual(sem["total_bits"], int(np.float32(0.0).view(np.int32)))
        self.assertEqual(sem["total_dim2_nan_bits"], sem["total_bits"])

    def test_idl_total_reproduces_it_where_float64_and_pairwise_do_not(self):
        got = export_ascii._idl_total(self.PROBE)
        self.assertEqual(got.dtype, np.float32)
        self.assertEqual(float(got), 0.0)
        self.assertEqual(float(np.sum(self.PROBE, dtype=np.float64)), 16.0)
        self.assertNotEqual(float(np.sum(self.PROBE)), 0.0)  # numpy's pairwise float32


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_compute_bulk_simple_bank.py first")
class TestMutationsAreCaught(unittest.TestCase):
    """Each earlier port's arithmetic choice, put back alone, must fail the golden."""

    def test_baseline_has_zero_mismatches(self):
        self.assertEqual(_mismatches(), 0)

    def test_pairwise_sums(self):
        def pairwise(x, nan=False):
            arr = np.asarray(x).ravel()
            return np.nansum(arr) if nan else np.sum(arr)

        with mock.patch.object(export_ascii, "_idl_total", pairwise):
            self.assertGreater(_mismatches(), 0)

    def test_float64_sums(self):
        def wide(x, nan=False):
            arr = np.asarray(x).ravel()
            s = np.nansum(arr, dtype=np.float64) if nan else np.sum(arr, dtype=np.float64)
            return arr.dtype.type(s)

        with mock.patch.object(export_ascii, "_idl_total", wide):
            self.assertGreater(_mismatches(), 0)

    def test_powf_cube(self):
        with mock.patch.object(export_ascii, "_idl_cube", lambda x: x ** 3):
            self.assertGreater(_mismatches(), 0)

    def test_float64_unnormalize(self):
        real = export_ascii.unnormalize

        def wide(spectra, endbins):
            return real(np.asarray(spectra, dtype=np.float64),
                        np.asarray(endbins, dtype=np.float64))

        with mock.patch.object(export_ascii, "unnormalize", wide):
            self.assertGreater(_mismatches(), 0)


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_compute_bulk_simple_bank.py first")
class TestCallerMutation(unittest.TestCase):
    """`:17`'s ``conc1d[bad]=0`` writes through a *bare variable* argument
    (by reference) but not through a structure field (by value), measured.
    Every vendored caller passes a field (``data.conc1d``, ``(*p1).conc1d``),
    so the port's private copy is the faithful reading."""

    def test_gdl_struct_field_is_by_value_bare_variable_by_reference(self):
        case = next(c for c in _ok_cases() if c["name"] == "nan_and_inf")
        before = case["bare_var_finite_before"]
        self.assertEqual(case["struct_field_finite_after"], before)
        self.assertEqual(case["bare_var_finite_after"], int(np.prod(case["conc_shape"])))
        self.assertGreater(case["bare_var_finite_after"], before)

    def test_port_leaves_the_callers_array_alone(self):
        case = next(c for c in _ok_cases() if c["name"] == "nan_and_inf")
        conc, endbins, kw = _inputs(case)
        before = conc.copy()
        compute_bulk_simple(conc, endbins, **kw)
        np.testing.assert_array_equal(conc, before)


if __name__ == "__main__":
    unittest.main()
