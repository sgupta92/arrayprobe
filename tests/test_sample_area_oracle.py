# SPDX-License-Identifier: BSD-3-Clause
"""``calc_sa_randombins`` against the value the REAL MATLAB file produced.

**This closes the first of the two direct-oracle gaps** that stood open
from S0 onward: ``calc_sa_randombins.m`` and ``ParticlePerimeter.m`` were the
last pure-MATLAB files in the pipeline never run against their port.

Why it mattered here in particular. ``tests/test_sample_area.py`` -- which
stays, because its cases document intent -- is entirely hand-computed: each
test re-derives the same arithmetic ``calc_sa_randombins`` performs and asserts
the two agree. A check whose two sides come from the same place is testing
nothing but the transcription of a formula into two files. This module is the
second side: every number asserted below came out of Octave running the
unmodified MATLAB.

``calc_sa_randombins.m`` is byte-identical in stock v3.1.4, the ORACLES variant
tree, ``uioops_testing/`` and upstream v3.5, so these values speak for every
version. Bank: ``octave_oracle/run_sample_area_bank.py``. The golden is tracked
so this runs on a clone with no Octave -- the standing rule that a test which
can silently skip is a test that will.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from arrayprobe.sample_area import calc_sa_randombins

GOLDEN = Path(__file__).resolve().parent / "data" / "sample_area_octave_golden.json"


def _load():
    return json.loads(GOLDEN.read_text())


class SampleAreaOracleTest(unittest.TestCase):
    """Every assertion here compares against a value MATLAB's own code produced."""

    @classmethod
    def setUpClass(cls):
        cls.records = _load()
        cls.ok = [r for r in cls.records if r["status"] == "OK"]
        cls.errors = [r for r in cls.records if r["status"] == "ERROR"]

    def test_bank_is_present_and_covers_both_outcomes(self):
        self.assertGreaterEqual(len(self.ok), 20)
        self.assertGreaterEqual(len(self.errors), 2)

    def test_every_case_is_bit_identical_to_octave(self):
        """Not ``assertAlmostEqual``: the port reproduces these to the last bit.

        The arithmetic is a handful of multiplications and one division by a
        constant, so there is no reason for a difference, and asserting equality
        rather than closeness is what makes a future regression visible. If a
        platform ever fails this, that is the finding -- ``massBL`` and ``vt``
        already showed that a fractional power resolves to the platform's own
        ``pow()`` -- and the answer is to record the platform, not to loosen the
        assertion silently.
        """
        for rec in self.ok:
            with self.subTest(rec["name"]):
                got = calc_sa_randombins(
                    rec["bins_mid"], rec["res"], rec["armdst"],
                    rec["num_diodes"], rec["sa_method"], rec["probetype"])
                self.assertEqual(len(got), len(rec["sa"]))
                for i, (expected, actual) in enumerate(zip(rec["sa"], got, strict=True)):
                    if math.isnan(expected):
                        self.assertTrue(math.isnan(actual), f"bin {i}")
                    else:
                        self.assertEqual(actual, expected, f"bin {i}")

    def test_the_live_oracles_calls_are_in_the_bank(self):
        """The bank must contain the arguments ORACLES actually processed with.

        ``sizeDist.m:1562`` is the only call site, and ``cip2_binmid`` is built
        from each probe block's ``kk`` in millimetres. A bank of only synthetic
        inputs could be green while the real call diverged.
        """
        names = {r["name"] for r in self.ok}
        for required in ("2ds_sa0_pt2", "2ds_sa1_pt2", "2ds_sa2_pt2",
                         "hvps_sa0_pt2", "hvps_sa1_pt2", "hvps_sa2_pt2"):
            self.assertIn(required, names)
        ds = next(r for r in self.ok if r["name"] == "2ds_sa0_pt2")
        self.assertEqual(len(ds["sa"]), 128)
        self.assertEqual(ds["res"], 10)
        self.assertEqual(ds["armdst"], 63)

    def test_both_probetype_branches_are_measured(self):
        """``if probetype==2`` is the only branch on probetype.

        0 and 1 share the ``else``, and the bank proves that rather than
        assuming it; probetype 2 must differ, or the case would be measuring
        nothing.
        """
        by_name = {r["name"]: r for r in self.ok}
        self.assertEqual(by_name["cip_sa2_pt0"]["sa"], by_name["cip_sa2_pt1"]["sa"])
        self.assertNotEqual(by_name["2ds_sa0_pt1"]["sa"],
                            by_name["2ds_sa0_pt2"]["sa"])

    def test_the_dof_clamp_keeps_a_value_exactly_equal_to_armdst(self):
        """``DOF(DOF > armdst) = armdst`` is strict, so DOF == armdst survives.

        ``min(dof, armdst)`` agrees only because the two are equal; this pins
        the boundary rather than the general case.
        """
        rec = next(r for r in self.ok if r["name"] == "dof_exactly_armdst")
        got = calc_sa_randombins(rec["bins_mid"], rec["res"], rec["armdst"],
                                 rec["num_diodes"], rec["sa_method"],
                                 rec["probetype"])
        self.assertEqual(got, rec["sa"])

    def test_a_nan_bin_survives_both_clamps_exactly_as_matlab(self):
        """Neither ``EAWci < 0`` nor ``DOF > armdst`` selects a NaN.

        A NaN bin therefore passes through untouched. Python's ``max``/``min``
        happen to agree, which is a fact about CPython's comparison order and
        not an obvious one -- so it is measured rather than reasoned about.
        """
        for name in ("nan_bin", "nan_bin_sa0"):
            rec = next(r for r in self.ok if r["name"] == name)
            got = calc_sa_randombins(rec["bins_mid"], rec["res"], rec["armdst"],
                                     rec["num_diodes"], rec["sa_method"],
                                     rec["probetype"])
            with self.subTest(name):
                self.assertTrue(math.isnan(got[1]))
                self.assertEqual([got[0], got[2]], [rec["sa"][0], rec["sa"][2]])

    def test_matlab_dies_where_the_port_raises(self):
        """The ``switch`` has no ``otherwise`` clause.

        An unsupported ``SAmethod`` leaves ``EAWri`` undefined and MATLAB errors
        at ``:49``. The port raises ``ValueError`` instead of reproducing that
        NameError-shaped failure. It is a documented deviation, not an accident,
        and it is only defensible because the original is *measured* to fail
        here too -- which is what these two records hold.
        """
        self.assertTrue(self.errors)
        for rec in self.errors:
            with self.subTest(rec["name"]):
                self.assertIn("EAWri", rec["message"])
                with self.assertRaises(ValueError):
                    calc_sa_randombins(rec["bins_mid"], rec["res"],
                                       rec["armdst"], rec["num_diodes"],
                                       rec["sa_method"], rec["probetype"])


class SampleAreaUnitsTest(unittest.TestCase):
    """``bins_mid`` is in MILLIMETRES at the only call site, not diode numbers.

    ``sizeDist.m:1541-1543`` builds ``cip2_binmid`` from ``kk``, and every probe
    block defines ``kk`` in mm (the 2D-S as ``diodesize/2 : diodesize : ...``
    with ``diodesize = .010`` mm; the HVPS as an explicit micron list divided by
    1000). The source's own comment -- "you can use this one if you provide
    midpoint in doide number" -- describes the COMMENTED-OUT line, not the live
    one, and the port's docstring said the opposite until 2026-09-08.

    Nothing computed changes either way, which is exactly why it survived: the
    function does arithmetic on whatever it is handed, and the Octave bank above
    is bit-identical regardless of what the units are called. The claim that can
    be checked is that the formula is only dimensionally coherent in mm, and
    that is what this asserts.
    """

    def test_entire_in_width_falls_to_zero_at_the_array_width(self):
        """``EAWci = (num_diodes - bins_mid/res + 1) * res``, ``res`` in mm.

        ``bins_mid/res`` is therefore a diode COUNT, which is dimensionally
        sound only if ``bins_mid`` is a length in mm. At a bin exactly the width
        of the array the effective width collapses to one diode; one bin wider
        it clamps to zero. Read as diode numbers instead, a 128-diode bin would
        put ``bins_mid/res`` at 12,800 and the width would have clamped to zero
        a hundredfold earlier.
        """
        res_um, num_diodes = 10.0, 128
        res_mm = res_um * 1e-3
        at_full_array = num_diodes * res_mm          # 1.28 mm
        one_beyond = (num_diodes + 1) * res_mm

        sa = calc_sa_randombins([at_full_array, one_beyond], res_um,
                                63.0, num_diodes, 1, 2)
        self.assertGreater(sa[0], 0.0)
        self.assertEqual(sa[1], 0.0)
