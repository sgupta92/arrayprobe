# SPDX-License-Identifier: BSD-3-Clause
"""``matlab_compat.datenum`` against Octave's own ``datenum``, bit for bit.

The golden is written by ``octave_oracle/run_datenum_bank.py`` (Octave 11.3.0):
the zero-date idiom ``datenum(0,0,0,H,M,S)``, months below 1, day 0, negative
and overflowing fields, years 0 and below, fractional months and years, vector
and date-vector forms, and 200 seeded in-range instants.
"""

from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

import numpy as np

from arrayprobe import matlab_compat as mc
from arrayprobe.intarr_analysis import _time_of_day_fraction

GOLDEN = Path(__file__).resolve().parent / "data" / "datenum_octave_golden.json"


def _hex(h):
    return struct.unpack(">d", bytes.fromhex(h))[0]


def _arg(a):
    x = np.array(a["v"], dtype=np.float64).reshape(a["r"], a["c"], order="F")
    return float(x[0, 0]) if x.size == 1 else x


class TestDatenumMatchesOctave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(GOLDEN.read_text())["cases"]

    def test_bank_is_large_and_all_ok(self):
        self.assertGreaterEqual(len(self.cases), 50)
        self.assertTrue(all(c["status"] == "OK" for c in self.cases))

    def test_every_case_is_bit_identical(self):
        for c in self.cases:
            with self.subTest(c["name"]):
                exp = np.array([_hex(h) for h in c["hex"]])
                got = np.asarray(mc.datenum(*[_arg(a) for a in c["args"]]), dtype=np.float64)
                if got.ndim == 2:
                    self.assertEqual(list(got.shape), c["size"])
                    got = got.reshape(-1, order="F")
                got = np.atleast_1d(got)
                self.assertEqual(got.shape, exp.shape)
                np.testing.assert_array_equal(got.view(np.uint64), exp.view(np.uint64))

    def test_zero_date_idiom_is_the_time_of_day(self):
        self.assertEqual(mc.datenum(0, 0, 0, 0, 0, 0), 0.0)
        self.assertEqual(mc.datenum(0, 0, 0, 12, 0, 0), 0.5)

    def test_month_below_one_is_set_to_one(self):
        self.assertEqual(mc.datenum(2016, 0, 1), mc.datenum(2016, 1, 1))
        self.assertEqual(mc.datenum(2016, -3, 5), mc.datenum(2016, 1, 5))

    def test_scalar_path_equals_array_path(self):
        rng = np.random.default_rng(7)
        f = [rng.uniform(lo, hi, 500) for lo, hi in
             [(-50, 3000), (-3, 15), (-40, 70), (-5, 30), (-90, 90), (-100, 100000)]]
        f[1][::3] = np.round(f[1][::3])
        f[0][::2] = np.round(f[0][::2])
        arr = mc.datenum(*f)
        for k in range(500):
            self.assertEqual(struct.pack("<d", mc.datenum(*[x[k] for x in f])),
                             struct.pack("<d", arr[k]))

    def test_date_vector_needs_three_to_six_columns(self):
        with self.assertRaises(ValueError):
            mc.datenum(np.zeros((2, 2)))


class TestInterArrivalTimeOfDayUsesDatenum(unittest.TestCase):
    """The inter-arrival analysis's time-of-day term is ``datenum(0,0,0,H,M,S)``
    itself, so every per-particle sum equals the old ``H/24 + M/1440 + S/86400``
    form bit for bit on every real date: the two terms differ by at most one ulp
    of a number below 1, which is absorbed when added to a whole-day datenum in
    [2**18, 2**20) (years 718-2870), whose rounding then depends on the term alone."""

    def test_every_integer_field_combination_sums_identically(self):
        h, m, s = (g.ravel() for g in np.meshgrid(np.arange(100.0), np.arange(100.0),
                                                   np.arange(100.0), indexing="ij"))
        old = h / 24.0 + m / 1440.0 + s / 86400.0
        new = _time_of_day_fraction(h, m, s)
        for base in (2.0 ** 18, mc.datenum(2016, 9, 6), mc.datenum(2869, 1, 1), 2.0 ** 20 - 1):
            with self.subTest(base=base):
                np.testing.assert_array_equal((base + new).view(np.uint64),
                                              (base + old).view(np.uint64))

    def test_term_is_datenum_zero_date(self):
        self.assertEqual(_time_of_day_fraction(6.0, 36.0, 28.0), mc.datenum(0, 0, 0, 6, 36, 28))


if __name__ == "__main__":
    unittest.main()
