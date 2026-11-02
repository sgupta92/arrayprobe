# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``sizeDist.m:984-1045`` interarrival block against its Octave golden.

The golden is ``tests/data/v35_interarrival_octave_golden.json``, written by
``octave_oracle/run_v35_interarrival_bank.py`` from the block's own lines sliced
out of the vendored v3.5 file. Runs without Octave.

The port side is what ``arrayprobe_uiops.sizedist._run`` does with the block:
:func:`arrayprobe_uiops.sizedist._interarrival` followed by the ``'I'`` mark and the
clamp (``:1044-1045``). Every case is a single block that is both the file's first
and its last, so no netCDF read is reached on either side (``f`` is ``None``).

Tolerance: exact for every value but the two rollover sums, where Octave's
``jsonencode`` prints 15 significant digits (measured: ``379.4967295`` for
``(2^32-1)*1e-7 - 50``), so those are compared to 1e-12 relative. The arithmetic
itself is the same IEEE-754 expression on both sides.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from tests import _upstream
from tests._repo import repo_only

from arrayprobe_uiops.sizedist import _interarrival

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "data" / "v35_interarrival_octave_golden.json"
V35_SIZEDIST = _upstream.source("uiops35") / "sizeDist.m"


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _vec(v) -> np.ndarray:
    return np.array(v if isinstance(v, list) else [v], dtype=float)


def _port(case: dict):
    tis = np.array(case["tis"], dtype=float)
    n = tis.size
    int_arr, _int_arr2, int_arr3 = _interarrival(
        None, None, 1, n, 1, tis, case["probetype"], case["res"], case["tasMax"],
        bool(case["reaccpt"]))
    auto_reject = np.full(n, ord("0"), dtype=float)
    auto_reject[int_arr < 0] = ord("I")                                # :1044
    int_arr[int_arr < 0] = 0                                           # :1045
    return int_arr, int_arr3, auto_reject


@unittest.skipUnless(GOLDEN.is_file(), "interarrival Octave golden not present")
class TestInterarrivalBlockAgainstOctave(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        g = json.loads(GOLDEN.read_text())
        cls.golden = g
        cls.pairs = list(zip(g["results"], g["cases"], strict=True))

    @repo_only
    def test_the_golden_was_sliced_from_the_vendored_file_as_it_stands(self):
        first, last = self.golden["block_lines"]
        _upstream.require("uiops35")
        lines = V35_SIZEDIST.read_text(encoding="utf-8", errors="replace").splitlines()
        self.assertEqual("\n".join(lines[first - 1:last]) + "\n", self.golden["block_text"])

    def test_every_case_matches(self):
        self.assertEqual(len(self.pairs), 10)
        for r, c in self.pairs:
            with self.subTest(case=c["name"]):
                int_arr, int_arr3, auto_reject = _port(c)
                np.testing.assert_allclose(int_arr, _vec(r["int_arr"]), rtol=1e-12, atol=0)
                np.testing.assert_array_equal(auto_reject, _vec(r["auto_reject"]))
                if r["has_int_arr3"]:
                    np.testing.assert_array_equal(int_arr3, _vec(r["int_arr3"]))
                else:
                    self.assertIsNone(int_arr3)

    def test_b8_the_last_block_arms(self):
        """``:1011-1014``: one particle gives ``0``; more give ``[diff; diff(end)]``."""
        by = {c["name"]: r for r, c in self.pairs}
        self.assertEqual(by["b8_last_block_one_particle"]["int_arr3"], 0)
        self.assertEqual(by["b8_last_block_three_particles"]["int_arr3"], [0.25, 0.5, 0.5])

    def test_b9_probetype_1_gets_no_rollover_only_an_I(self):
        """``:1025-1029`` has no probetype-1 arm, so a 5 s step back is marked ``'I'``
        (73) and clamped, never corrected."""
        r = next(r for r, c in self.pairs if c["name"] == "b9_pt1_steps_back_5s")
        self.assertEqual(r["auto_reject"], [48, 48, 73, 48])
        self.assertEqual(r["int_arr"], [0, 1, 0, 1])


if __name__ == "__main__":
    unittest.main()
