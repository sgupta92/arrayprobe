# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``read_binary_SPEC.m:176-193`` ``tasRatio`` block against its Octave golden.

The golden is ``tests/data/v35_tas_ratio_octave_golden.json``, written by
``octave_oracle/run_v35_tas_ratio_bank.py`` from the block's own lines sliced out
of the vendored v3.5 file. Runs without Octave. The port side is
:func:`arrayprobe_uiops.tas.tas_ratio`; a ratio is one IEEE-754 division on both
sides, so equality is exact. Since pass 6 the bank hands ``imgTAS`` in as
``single``, the class ``get_img``'s ``typecast`` gives it (``:391``), so a real
ratio is a single-precision quotient, as the port computes it.

With an empty aircraft series ``:177``'s ``fltTime(end)`` raises in Octave; the
port returned ``1.0`` until pass 6 (audit item 1A, D3) and now raises too.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from tests import _upstream
from tests._repo import repo_only

from arrayprobe_uiops.tas import tas_ratio

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "data" / "v35_tas_ratio_octave_golden.json"
V35_SPEC = _upstream.source("uiops35") / "read_binary_SPEC.m"


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _port(c: dict) -> float:
    fixed = [math.nan if n else v for v, n in zip(c["fltTAS_fixed"], c["tas_nan"], strict=True)]
    return tas_ratio(c["imgTAS"], c["fltTime"], fixed, c["hour"], c["minute"], c["second"])


@unittest.skipUnless(GOLDEN.is_file(), "tasRatio Octave golden not present")
class TestTasRatioBlockAgainstOctave(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        g = json.loads(GOLDEN.read_text())
        cls.golden = g
        cls.pairs = list(zip(g["results"], g["cases"], strict=True))

    @repo_only
    def test_the_golden_was_sliced_from_the_vendored_file_as_it_stands(self):
        first, last = self.golden["block_lines"]
        _upstream.require("uiops35")
        lines = V35_SPEC.read_text(encoding="utf-8", errors="replace").splitlines()
        self.assertEqual("\n".join(lines[first - 1:last]) + "\n", self.golden["block_text"])

    def test_every_case_octave_completes_matches_exactly(self):
        done = [(r, c) for r, c in self.pairs if r["status"] == "OK"]
        self.assertEqual(len(done), 7)
        for r, c in done:
            with self.subTest(case=c["name"]):
                self.assertEqual(r["n"], 1)
                self.assertEqual(_port(c), r["tasRatio"])

    def test_octave_errors_on_an_empty_flight_series(self):
        r, _ = next(p for p in self.pairs if p[1]["name"] == "b11_empty_flight_series")
        self.assertEqual(r["status"], "ERROR")
        self.assertIn("fltTime(0)", r["message"])

    def test_b11_the_port_errors_on_an_empty_flight_series_like_matlab(self):
        """Item 1A D3: minimal input ``tas_ratio(100.0, [], [], 10, 0, 0)``
        returned 1.0 where ``:177`` raises."""
        _, c = next(p for p in self.pairs if p[1]["name"] == "b11_empty_flight_series")
        with self.assertRaises((ValueError, IndexError)):
            _port(c)


if __name__ == "__main__":
    unittest.main()
