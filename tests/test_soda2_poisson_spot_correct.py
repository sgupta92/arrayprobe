# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.poisson_spot_correct`` against GDL running SODA-2's own
`.pro`, and against an independently-coded cross-chain recomputation.

Three sides: GDL executing NCAR's own IDL
(`gdl_oracle/run_soda2_poisson_spot_correct_bank.py`), this Python port, and
a `bisect`-based recomputation over `arrayprobe.reject`'s independently
transcribed copy of the same Korolev (2007) table. Float32 outputs are
compared as 8-hex-digit IEEE bit patterns with no tolerance and no decimal
parsing (the `_hex32` convention in `test_soda2_spec_read_hk.py`).
"""
from __future__ import annotations

import bisect
import json
import struct
import unittest
import warnings
from pathlib import Path

import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe_soda2.poisson_spot_correct import (
    DEDGE_D0,
    DSPOT_DEDGE,
    ZEED,
    poisson_spot_correct,
)

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_poisson_spot_correct_golden.json"


def _hex32(v) -> str:
    return f"{struct.unpack('<I', struct.pack('<f', float(v)))[0]:08X}"


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it this "
                "suite would silently stop checking the port against IDL.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_the_bank_reaches_the_named_regimes(self):
        names = {c["name"] for c in self.cases}
        for needed in ("no_spot", "near_757", "above_table_top",
                       "fill_zero_orig_zero", "orig_negative"):
            self.assertIn(needed, names)

    def test_every_case_matches_idl_exactly(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                res = poisson_spot_correct(case["orig"], case["fill"])
                self.assertEqual(_hex32(res.correction), case["CORR"],
                                  f"correction mismatch for {case['name']}")
                self.assertEqual(_hex32(res.zd), case["ZD"],
                                  f"zd mismatch for {case['name']}")
            checked += 1
        self.assertGreaterEqual(checked, 12)


@needs_v314_engine
class CrossChainAgainstUiops(unittest.TestCase):
    """A *test* may import both packages; the port itself never does (the
    port's tables are transcribed independently from `poisson_spot_correct.pro`
    so this comparison is between two independent transcriptions of Korolev
    2007, not one value imported twice)."""

    @classmethod
    def setUpClass(cls):
        from arrayprobe.reject import EDGE_0, SPOT_EDGE, Z_D
        cls.EDGE_0, cls.SPOT_EDGE, cls.Z_D = EDGE_0, SPOT_EDGE, Z_D
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_all_three_tables_have_164_entries(self):
        self.assertEqual(DSPOT_DEDGE.size, 164)
        self.assertEqual(DEDGE_D0.size, 164)
        self.assertEqual(ZEED.size, 164)

    def test_dedge_d0_and_zeed_match_uiops_exactly(self):
        np.testing.assert_array_equal(DEDGE_D0.astype(np.float32),
                                       self.EDGE_0.astype(np.float32))
        np.testing.assert_array_equal(ZEED.astype(np.float32),
                                       self.Z_D.astype(np.float32))

    def test_dspot_dedge_matches_uiops_except_index_146(self):
        """SODA-2 has 0.757 at index 146; UIOOPS carries the preserved
        `calculate_reject_unified.m:54` typo, 757.0."""
        soda2 = DSPOT_DEDGE.astype(np.float32)
        uiops = self.SPOT_EDGE.astype(np.float32)
        mismatches = np.flatnonzero(soda2 != uiops)
        self.assertEqual(list(mismatches), [146])
        self.assertAlmostEqual(float(soda2[146]), 0.757, places=6)
        self.assertEqual(float(uiops[146]), 757.0)

    def test_independent_bisection_recomputation_agrees_with_the_port(self):
        """A corrected UIOOPS table (index 146 fixed to 0.757), searched by
        `bisect` instead of `flatnonzero` -- a different lookup mechanism
        entirely -- must land on the same `ip` as the port for every OK case."""
        # Cast to float32 first: the port's own table is float32, and the
        # golden's ratios are float32-rounded, so comparing against the
        # float64 UIOOPS literals directly misses at exact-boundary cases
        # (e.g. float32(0.95) != float64(0.95) by 1.2e-8 -- `last_entry_exact`).
        corrected = list(float(np.float32(v)) for v in self.SPOT_EDGE)
        corrected[146] = float(np.float32(0.757))
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                orig = np.float32(case["orig"])
                fill = np.float32(case["fill"])
                if not (orig >= 0 and fill >= 0):
                    ip = -1  # :26 untaken -- mirrors the port's branch guard,
                             # unclamped, exactly like the port's own `ip = -1`
                else:
                    with np.errstate(all="ignore"):
                        diff = np.float32(fill) - orig
                        ratio = float(np.sqrt(diff / fill))
                    if ratio != ratio:  # NaN: bisect over NaN is undefined,
                        ip = -1          # `where(x le NaN)` is empty in IDL too
                    else:
                        # bisect_right(table, ratio) - 1 == index of the last
                        # entry <= ratio -- a different lookup mechanism
                        # (bisection on a corrected table) from the port's
                        # `flatnonzero` on SODA-2's own table.
                        ip = bisect.bisect_right(corrected, ratio) - 1
                    ip = min(max(ip, 0), len(corrected) - 1)
                res = poisson_spot_correct(case["orig"], case["fill"])
                self.assertEqual(ip, res.ip, f"ip mismatch for {case['name']}")
            checked += 1
        self.assertGreaterEqual(checked, 12)


class PinnedSemantics(unittest.TestCase):
    def test_ratio_is_float32_end_to_end(self):
        res = poisson_spot_correct(60, 100)
        self.assertIsInstance(res.correction, np.float32)
        self.assertIsInstance(res.zd, np.float32)

    def test_an_empty_where_is_clamped_to_index_zero(self):
        res = poisson_spot_correct(12, 12)
        self.assertEqual(res.ip, 0)
        self.assertEqual(float(res.correction), 1.0)
        self.assertEqual(float(res.zd), 0.0)

    def test_a_nan_ratio_takes_the_same_clamp_and_returns_the_defaults(self):
        for orig, fill in ((0, 0), (100, 90)):
            with self.subTest(orig=orig, fill=fill):
                res = poisson_spot_correct(orig, fill)
                self.assertEqual(res.ip, 0)
                self.assertEqual(float(res.correction), 1.0)
                self.assertEqual(float(res.zd), 0.0)

    def test_the_untaken_branch_reports_ip_minus_one(self):
        res = poisson_spot_correct(-1, 10)
        self.assertEqual(res.ip, -1)
        self.assertEqual(float(res.correction), 1.0)
        self.assertEqual(float(res.zd), 0.0)

    @needs_v314_engine
    def test_the_index_146_entry_is_reached_where_uiops_stops_short(self):
        """ratio ~0.7616 (orig=42, fill=100): SODA-2's ip is 146 (its own
        0.757 <= ratio, its own 0.763 > ratio). Reimplemented (not imported,
        `_find_last` is private) the UIOOPS `find(... , 1, 'last')` one-liner
        against the UNCORRECTED UIOOPS table: 757.0 at index 146 is never
        <= a physical ratio, so UIOOPS's own last-index-<=-ratio search for
        this same ratio stops one entry short, at **145** -- the exact
        divergence the plan (Sec 0) and `arrayprobe.reject.SPOT_EDGE`'s
        docstring describe. This is the demonstration, not a mismatch."""
        res = poisson_spot_correct(42, 100)
        self.assertEqual(res.ip, 146)
        from arrayprobe.reject import SPOT_EDGE
        ratio = float(np.sqrt(
            np.float32(np.float32(100) - np.float32(42)) / np.float32(100)))
        uiops_hits = np.flatnonzero(SPOT_EDGE.astype(np.float64) <= ratio)
        uiops_ip = int(uiops_hits[-1]) if uiops_hits.size else -1
        self.assertEqual(uiops_ip, 145,
                          "UIOPS's uncorrected table stops one entry short of SODA-2's")

    def test_no_numpy_warning_escapes_on_zero_fill(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            poisson_spot_correct(0, 0)
            poisson_spot_correct(5, 0)
            poisson_spot_correct(100, 90)


if __name__ == "__main__":
    unittest.main()
