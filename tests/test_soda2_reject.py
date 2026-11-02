# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.reject`` against GDL running SODA-2's own `.pro`.

The golden is real output from `soda2_reject.pro` run unmodified under GDL
(`gdl_oracle/run_soda2_reject_bank.py`), 31 cases.

The layer-3 classes below the differential one are not redundant with it.
They pin the two things a bank of fixed cases cannot state: that the bits
**sum** rather than compete, and that three of the criteria treat NaN
differently from each other on purpose.
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.reject import (
    REJECT_BITS,
    Particle,
    RejectOptions,
    soda2_reject,
)

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_reject_golden.json"


def _f(value):
    """The golden writes IDL's NaN as JSON null."""
    return float("nan") if value is None else float(value)


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking the port against IDL.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def _run(self, case):
        a = case["a"]
        pop = case["pop"]
        return soda2_reject(
            Particle(arearatio=_f(a["arearatio"]),
                     arearatiofilled=_f(a["arearatiofilled"]),
                     allin=a["allin"], centerin=a["centerin"],
                     diam=_f(a["diam"]), dofflag=a["dofflag"]),
            _f(case["inttime"]), _f(case["nextinttime"]), _f(case["cutoff"]),
            case["clustercount"], _f(case["binningsize"]),
            RejectOptions(endbins=pop["endbins"], eawmethod=pop["eawmethod"],
                          water=pop["water"], res=_f(pop["res"]),
                          dofreject=pop["dofreject"],
                          clusterthresh=_f(pop["clusterthresh"])),
        )

    def test_the_bank_reaches_every_bit_and_the_accepted_case(self):
        """Eight bits and a control. A bank missing the control would pass a
        port that rejected everything."""
        fired = set()
        has_control = False
        for case in self.cases:
            if case["status"] != "OK":
                continue
            if case["REJECT"] == 0:
                has_control = True
            for bit in REJECT_BITS:
                if case["REJECT"] & bit:
                    fired.add(bit)
        self.assertTrue(has_control, "no case in the bank is ACCEPTED")
        self.assertEqual(fired, set(REJECT_BITS),
                         f"bits never exercised: {sorted(set(REJECT_BITS) - fired)}")

    def test_every_case_matches_idl_exactly(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                got = self._run(case)
                self.assertEqual(got.reject, case["REJECT"],
                                 f"reasons: {got.reasons()}")
                self.assertEqual(got.idl_type, case["IDL_TYPE"])
            checked += 1
        self.assertGreaterEqual(checked, 30)

    def test_the_boundaries_are_where_idl_puts_them(self):
        """Named explicitly, because `lt` against `le` is what a reader gets
        wrong and a midpoint test never catches. Each of these four is a
        golden case, asserted here by name so that deleting one from the bank
        fails rather than shrinking the check.
        """
        by_name = {c["name"]: c["REJECT"] for c in self.cases}
        self.assertEqual(by_name["bit1_arearatio_exactly_0p10"], 0)
        self.assertEqual(by_name["bit1_arearatio_exactly_one"], 0)
        self.assertEqual(by_name["bit4_at_first_bin"], 0)
        self.assertEqual(by_name["bit4_at_last_bin"], 4)


class TheWaterSizeThresholdIsAFloatProduct(unittest.TestCase):
    """``soda2_reject.pro:20`` and ``:29`` compare ``a.diam`` with
    ``(*pop).res*10.0``, FLOAT times a FLOAT literal. Measured under GDL with
    ``res:2.3`` and ``diam:23.0`` (``2.3*10.0`` prints 2.30000000000000000e+01
    there): ``water=1`` with ``arearatiofilled`` 0.45 returns **0** (23.0 is
    not above 23.0) and ``water=-1`` with ``arearatio`` 0.45 returns **64**.
    The FLOAT ``res`` (``numpy.float32(2.3)``, 2.2999999523) times 10 in
    double is 22.9999995, which gives 32 and 0."""

    def _reject(self, water, ar, arf):
        return soda2_reject(
            Particle(arearatio=ar, arearatiofilled=arf, allin=1, centerin=1,
                     diam=23.0, dofflag=1),
            1.0, 1.0, 0.0, 0, 30.0,
            RejectOptions(endbins=[10.0, 50.0, 100.0], eawmethod="centerin",
                          water=water, res=float(np.float32(2.3)), dofreject=0,
                          clusterthresh=0.0),
        ).reject

    def test_water_1_diam_equal_to_float_product_is_not_above_it(self):
        self.assertEqual(self._reject(1, 0.8, 0.45), 0)

    def test_water_minus_1_diam_equal_to_float_product_is_at_most_it(self):
        self.assertEqual(self._reject(-1, 0.45, 0.45), 64)


class TheBitsSumRatherThanCompete(unittest.TestCase):
    """The source calls its criteria "in increasing order of importance",
    which describes a priority. The code adds."""

    def _opts(self, **kw):
        base = dict(endbins=[5.0, 2000.0], eawmethod="centerin", water=0,
                    res=10.0, dofreject=0, clusterthresh=0.0)
        base.update(kw)
        return RejectOptions(**base)

    def _particle(self, **kw):
        base = dict(arearatio=0.5, arearatiofilled=0.6, allin=1, centerin=1,
                    diam=100.0, dofflag=1)
        base.update(kw)
        return Particle(**base)

    def test_two_criteria_give_their_sum_and_not_the_larger(self):
        got = soda2_reject(self._particle(arearatio=0.05), 1e-7, 1.0, 1e-6,
                           0, 100.0, self._opts())
        self.assertEqual(got.reject, 3, "1 + 2, not 2")

    def test_water_and_out_of_range_both_fire_on_an_oversize_particle(self):
        """`binningsize gt 6000` is inside the water block, and the same
        particle is also outside the bin ladder. 32 + 4."""
        got = soda2_reject(self._particle(), 1.0, 1.0, 1e-6, 0, 7000.0,
                           self._opts(water=1))
        self.assertEqual(got.reject, 36)

    def test_255_is_unreachable_because_32_and_64_exclude_each_other(self):
        """One needs `water` positive, the other `water` negative. The
        ceiling is 223, and even that needs an area ratio that trips bit 64
        while staying inside bit 1's accepted band -- so the highest value
        actually reachable is 222."""
        worst = self._particle(arearatio=0.8, centerin=0, dofflag=0)
        got = soda2_reject(worst, 1e-7, 1e-7, 1e-6, 3, 1.0,
                           self._opts(water=-1, dofreject=1,
                                      clusterthresh=1e-5))
        self.assertEqual(got.reject, 222)
        self.assertEqual(got.reject & 32, 0, "the water bit cannot also fire")

    def test_reasons_decodes_the_sum(self):
        got = soda2_reject(self._particle(arearatio=0.05), 1e-7, 1.0, 1e-6,
                           0, 100.0, self._opts())
        self.assertEqual(got.reasons(),
                         ["low area ratio", "below interarrival"])


class NanIsNotTreatedUniformly(unittest.TestCase):
    """Three criteria, three different answers, and all three are preserved.

    Finding S3-b. Written as its own class because a port that "tidied" this
    into one consistent rule would still pass every finite case in the bank.
    """

    def _opts(self, **kw):
        base = dict(endbins=[5.0, 2000.0], eawmethod="centerin", water=0,
                    res=10.0, dofreject=0, clusterthresh=0.0)
        base.update(kw)
        return RejectOptions(**base)

    def _particle(self, **kw):
        base = dict(arearatio=0.5, arearatiofilled=0.6, allin=1, centerin=1,
                    diam=100.0, dofflag=1)
        base.update(kw)
        return Particle(**base)

    def test_a_nan_area_ratio_is_accepted(self):
        got = soda2_reject(self._particle(arearatio=math.nan), 1.0, 1.0, 1e-6,
                           0, 100.0, self._opts())
        self.assertEqual(got.reject & 1, 0,
                         "IDL's lt/gt are both false for NaN")

    def test_a_nan_interarrival_time_is_accepted(self):
        got = soda2_reject(self._particle(), math.nan, 1.0, 1e-6, 0, 100.0,
                           self._opts())
        self.assertEqual(got.reject & 2, 0)

    def test_a_nan_binning_size_is_rejected(self):
        """The one criterion with an explicit `finite()` test."""
        got = soda2_reject(self._particle(), 1.0, 1.0, 1e-6, 0, math.nan,
                           self._opts())
        self.assertEqual(got.reject & 4, 4)

    def test_the_three_answers_really_do_differ(self):
        """Asserted together, so a change that made them uniform in either
        direction fails here rather than in one of the three above."""
        ratio = soda2_reject(self._particle(arearatio=math.nan), 1.0, 1.0,
                             1e-6, 0, 100.0, self._opts()).reject
        size = soda2_reject(self._particle(), 1.0, 1.0, 1e-6, 0, math.nan,
                            self._opts()).reject
        self.assertNotEqual(bool(ratio), bool(size))


class TheEawMethodGate(unittest.TestCase):
    def _opts(self, method):
        return RejectOptions(endbins=[5.0, 2000.0], eawmethod=method,
                             water=0, res=10.0, dofreject=0,
                             clusterthresh=0.0)

    def _bad(self):
        return Particle(arearatio=0.5, arearatiofilled=0.6, allin=0,
                        centerin=0, diam=100.0, dofflag=1)

    def test_reconstruct_can_never_set_bit_8(self):
        """Two `IF`s and no ELSE, so 'reconstruct' falls off the end. Correct
        -- a reconstructed particle is meant to be partial -- and reached by
        omission rather than by an explicit branch."""
        got = soda2_reject(self._bad(), 1.0, 1.0, 1e-6, 0, 100.0,
                           self._opts("reconstruct"))
        self.assertEqual(got.reject, 0)

    def test_each_method_consults_only_its_own_flag(self):
        allin_only = Particle(arearatio=0.5, arearatiofilled=0.6, allin=0,
                              centerin=1, diam=100.0, dofflag=1)
        centerin_only = Particle(arearatio=0.5, arearatiofilled=0.6, allin=1,
                                 centerin=0, diam=100.0, dofflag=1)
        self.assertEqual(
            soda2_reject(allin_only, 1.0, 1.0, 1e-6, 0, 100.0,
                         self._opts("centerin")).reject, 0)
        self.assertEqual(
            soda2_reject(centerin_only, 1.0, 1.0, 1e-6, 0, 100.0,
                         self._opts("allin")).reject, 0)
        self.assertEqual(
            soda2_reject(allin_only, 1.0, 1.0, 1e-6, 0, 100.0,
                         self._opts("allin")).reject, 8)
        self.assertEqual(
            soda2_reject(centerin_only, 1.0, 1.0, 1e-6, 0, 100.0,
                         self._opts("centerin")).reject, 8)

    def test_an_unknown_method_is_not_an_error_here(self):
        """The IDL has no validation on this path; `soda2_samplearea` is where
        an unrecognised method halts. Reproduced rather than improved: raising
        here would reject particles the original accepts."""
        got = soda2_reject(self._bad(), 1.0, 1.0, 1e-6, 0, 100.0,
                           self._opts("wobble"))
        self.assertEqual(got.reject, 0)


class TheReturnTypeVariesWithTheAnswer(unittest.TestCase):
    """Finding S3-a. `reject=0b` is BYTE; every `+=` adds an untyped IDL
    literal, which is INT. Measured under GDL rather than derived."""

    def _opts(self):
        return RejectOptions(endbins=[5.0, 2000.0], eawmethod="centerin")

    def test_accepted_is_byte_and_rejected_is_int(self):
        good = Particle(0.5, 0.6, 1, 1, 100.0, 1)
        bad = Particle(0.05, 0.6, 1, 1, 100.0, 1)
        self.assertEqual(
            soda2_reject(good, 1.0, 1.0, 1e-6, 0, 100.0, self._opts()).idl_type,
            "BYTE")
        self.assertEqual(
            soda2_reject(bad, 1.0, 1.0, 1e-6, 0, 100.0, self._opts()).idl_type,
            "INT")


if __name__ == "__main__":
    unittest.main()
