# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2 sample area: ``soda2_samplearea.pro``.

**The sample-area port reached doctrine layer 2 on 2026-09-12.** It was ported on 2026-09-10,
before GDL was installed, and stayed on layer 3 while every later SODA-2 file
got a real differential bank. A review named that as the port's largest hole
and predicted two costs; both were then measured, and both were real:

1. **Single precision.** ``:17-18``'s ``float()`` narrows, every literal in
   the chain is a bare decimal, and every field ``soda2_probespecs.pro`` feeds
   this routine is declared ``0.0``. The float64 port disagreed with GDL by
   1.4e-7 relative -- one float32 epsilon.
2. **The Lawson sentinel is type-sensitive**, and it costs a factor of
   **2.707**: ``:14`` compares against a FLOAT literal, so a DOUBLE
   ``0.785d-6`` misses the branch and ``dofconst`` stays at Knollenberg's 3.0.


The module now models IDL's types rather than assuming double, and
``AgainstTheGdlGolden`` below asserts it against
``gdl_oracle/run_soda2_sample_area_bank.py``'s output: **all 15 runnable cases
match bit-for-bit**, every field, no tolerance.

The layer-3 classes below are kept rather than replaced. They are written to
be *specifically* hard on the one thing a differential bank still misses when
a case is absent: the IDL ``<``/``>`` min-max operators (design record V1.3).

The rule followed here: **every clamp is driven past its boundary.** Inside
the boundary, reading ``dof < prht`` as a comparison and as a minimum can
produce the same answer by accident, so a nominal-value test proves nothing
about the thing most likely to be wrong.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.sample_area import (
    EAW_METHODS,
    UnsupportedSampleVolumeMethod,
    _as_idl,
    sample_area,
)

# The 2D-S Horizontal Array, read from soda2_probespecs.pro:940-956 -- the
# probe ORACLES actually flew, so the numbers below are the ones that matter.
TWODS = dict(
    res=10.0,
    armwidth=6.3,
    numdiodes=128.0,
    wavelength=0.785e-6,
)
PRHT_UM = 6.3 * 1e4  # armwidth in micrometres, = 63000


class TheDofClamp(unittest.TestCase):
    """``dof = dof < prht`` at :26 is a MINIMUM, not a comparison."""

    def test_a_large_particle_clamps_the_dof_to_the_arm_separation(self):
        # At 200 um on a 2D-S the computed DoF is ~207 mm, far beyond the
        # 63 mm between the arms -- so the clamp must bite.
        _sa, dof, _eff = sample_area(
            diam=200.0, eawmethod="centerin", **TWODS
        )
        self.assertAlmostEqual(float(dof), PRHT_UM, places=6)

    def test_the_unclamped_case_is_the_formula_not_the_clamp(self):
        # At 100 um the computed DoF (~51.7 mm) is inside the arms, so the
        # clamp must NOT bite -- otherwise a port that always returned prht
        # would pass the test above.
        diam = 100.0
        _sa, dof, _eff = sample_area(diam=diam, eawmethod="centerin", **TWODS)
        expected = (
            2 * 8.12 * ((diam / 1e6 / 2.0) ** 2 / TWODS["wavelength"]) * 1e6
        )
        _agrees_to_single_precision(self, float(dof), expected)
        self.assertLess(float(dof), PRHT_UM)

    def test_the_clamp_is_a_minimum_and_not_a_boolean(self):
        """The mutation this whole file exists to catch.

        Reading ``<`` as Python's comparison yields ``True``/``False``, which
        NumPy would happily carry forward as 1.0/0.0. Asserting the value is
        a real micrometre quantity, not 0 or 1, makes that reading fail.
        """
        _sa, dof, _eff = sample_area(diam=200.0, eawmethod="centerin", **TWODS)
        self.assertNotIn(float(dof), (0.0, 1.0))
        self.assertGreater(float(dof), 1e3)

    def test_it_clamps_elementwise_across_an_array(self):
        # 100 um is inside the arms, 200 um is beyond: one array, both sides
        # of the boundary, so a scalar-only clamp cannot pass.
        _sa, dof, _eff = sample_area(
            diam=[100.0, 200.0], eawmethod="centerin", **TWODS
        )
        self.assertLess(float(dof[0]), PRHT_UM)
        self.assertAlmostEqual(float(dof[1]), PRHT_UM, places=6)


def _agrees_to_single_precision(case, got: float, expected_f64: float) -> None:
    """`got` came out of the port's float32 chain; `expected_f64` is an
    independent recomputation in Python's float64.

    They cannot agree exactly and must not be asked to: `soda2_samplearea.pro`
    runs in **single** precision -- `:17-18` cast `diam` and `res` with IDL's
    `float()`, every literal in the chain is a bare decimal (FLOAT), and every
    probespecs field it is fed is declared `0.0`. Measured under GDL on
    2026-09-12; the port matches the golden bit-for-bit on all 15 runnable
    bank cases, and this file's own recomputations then sit one float32
    epsilon away by construction.

    The tolerance is derived, not tuned. An earlier version of these four
    assertions used `places=3`/`places=4` picked to make float64 arithmetic
    pass, which silently accepted anything within 5e-4 of a number near 1e4 --
    four orders of magnitude looser than single precision actually is.
    """
    tol = 4 * float(np.finfo(np.float32).eps) * max(abs(expected_f64), 1.0)
    case.assertLessEqual(
        abs(got - expected_f64), tol,
        f"{got!r} vs {expected_f64!r}: differ by more than 4 float32 eps")


class TheNegativeAreaClamp(unittest.TestCase):
    """``sa = (...) > 0`` at :36 is a MAXIMUM, not a comparison."""

    def test_allin_past_the_array_width_gives_zero_not_a_negative_area(self):
        # 'allin' effective width is res*(numdiodes-1) - diam = 1270 - diam,
        # so any particle wider than 1270 um drives it negative.
        sa, _dof, eff = sample_area(diam=2000.0, eawmethod="allin", **TWODS)
        self.assertLess(float(eff), 0.0, "the width itself is negative")
        self.assertEqual(float(sa), 0.0, "but the area must be clamped to 0")

    def test_the_clamp_is_a_maximum_and_not_a_boolean(self):
        # A normal positive area must come back as a real m^2 quantity. Read
        # as a comparison, `(...) > 0` would collapse it to True.
        sa, _dof, _eff = sample_area(diam=100.0, eawmethod="centerin", **TWODS)
        self.assertNotIn(float(sa), (0.0, 1.0))
        self.assertGreater(float(sa), 0.0)
        self.assertLess(float(sa), 1.0)


class TheDofConstSentinel(unittest.TestCase):
    """``IF dofconst eq 0`` at :11 -- zero means unset, not a value."""

    def test_a_spec_wavelength_selects_the_lawson_2006_constant(self):
        _sa, dof, _eff = sample_area(diam=50.0, eawmethod="centerin", **TWODS)
        r2overlam = (50.0 / 1e6 / 2.0) ** 2 / TWODS["wavelength"]
        _agrees_to_single_precision(self, float(dof), 2 * 8.12 * r2overlam * 1e6)

    def test_any_other_wavelength_falls_back_to_knollenberg_1970(self):
        probe = dict(TWODS, wavelength=0.658e-6)  # the CIP wavelength
        _sa, dof, _eff = sample_area(diam=50.0, eawmethod="centerin", **probe)
        r2overlam = (50.0 / 1e6 / 2.0) ** 2 / probe["wavelength"]
        _agrees_to_single_precision(self, float(dof), 2 * 3.0 * r2overlam * 1e6)

    def test_an_explicit_dofconst_overrides_both(self):
        _sa, dof, _eff = sample_area(
            diam=50.0, eawmethod="centerin", dofconst=5.0, **TWODS
        )
        r2overlam = (50.0 / 1e6 / 2.0) ** 2 / TWODS["wavelength"]
        _agrees_to_single_precision(self, float(dof), 2 * 5.0 * r2overlam * 1e6)


class TheSuppliedDofPath(unittest.TestCase):
    """``IF total(dof) eq 0`` at :23 tests the TOTAL, which is load-bearing."""

    def test_a_supplied_dof_is_used_rather_than_computed(self):
        _sa, dof, _eff = sample_area(
            diam=50.0, eawmethod="centerin", dof=[1000.0], **TWODS
        )
        self.assertAlmostEqual(float(dof[0]), 1000.0, places=6)

    def test_a_mixed_array_with_a_nonzero_total_is_kept_whole(self):
        """Preserved as written: the zeros are NOT filled in.

        The source tests ``total(dof) eq 0``, not each element, so an array
        that is partly zero keeps its zeros. A port that tested elementwise
        would silently compute values the IDL never produces.
        """
        _sa, dof, _eff = sample_area(
            diam=[50.0, 50.0], eawmethod="centerin", dof=[0.0, 1000.0], **TWODS
        )
        self.assertEqual(float(dof[0]), 0.0)
        self.assertAlmostEqual(float(dof[1]), 1000.0, places=6)


class TheEffectiveArrayWidthMethods(unittest.TestCase):
    """The three-branch CASE at :29-33."""

    def test_reconstruct_adds_the_heymsfield_parrish_term(self):
        diam = 100.0
        _sa, _dof, eff = sample_area(
            diam=diam, eawmethod="reconstruct", **TWODS
        )
        self.assertAlmostEqual(float(eff), 10.0 * 128 + 0.72 * diam, places=6)

    def test_centerin_is_the_bare_array_width(self):
        _sa, _dof, eff = sample_area(diam=100.0, eawmethod="centerin", **TWODS)
        self.assertAlmostEqual(float(eff), 10.0 * 128, places=6)

    def test_allin_subtracts_the_particle_and_one_diode(self):
        diam = 100.0
        _sa, _dof, eff = sample_area(diam=diam, eawmethod="allin", **TWODS)
        self.assertAlmostEqual(float(eff), 10.0 * 127 - diam, places=6)

    def test_the_three_methods_order_as_the_physics_requires(self):
        # Reconstruction accepts the most particles, all-in the fewest, for
        # the same particle -- a relation independent of the constants, so it
        # would catch a branch swapped between methods.
        widths = [
            float(sample_area(diam=100.0, eawmethod=m, **TWODS)[2])
            for m in ("allin", "centerin", "reconstruct")
        ]
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])


class TheUnsupportedMethodDivergence(unittest.TestCase):
    def test_an_unknown_method_raises_where_the_idl_halts(self):
        with self.assertRaises(UnsupportedSampleVolumeMethod):
            sample_area(diam=100.0, eawmethod="notamethod", **TWODS)

    def test_every_advertised_method_is_actually_accepted(self):
        for method in EAW_METHODS:
            with self.subTest(method=method):
                sa, _dof, _eff = sample_area(
                    diam=100.0, eawmethod=method, **TWODS
                )
                self.assertTrue(np.isfinite(sa).all())


class TheUnits(unittest.TestCase):
    def test_a_2ds_sample_area_lands_in_the_documented_order_of_magnitude(self):
        """The source's header states m^2, and the scale is checkable.

        A 100 um particle on a 2D-S: DoF ~51.7 mm, effective width ~1.35 mm,
        so the area is ~7e-5 m^2. Getting a unit conversion wrong moves this
        by orders of magnitude, which this bracket catches even though it
        does not pin an exact value.
        """
        sa, _dof, _eff = sample_area(
            diam=100.0, eawmethod="reconstruct", **TWODS
        )
        self.assertGreater(float(sa), 1e-6)
        self.assertLess(float(sa), 1e-3)


GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_sample_area_golden.json"


def _idl_typed(value, name, double_args):
    """Rebuild the case's argument at the IDL type the bank wrote it as.

    The bank writes each argument as a FLOAT literal unless the case names it
    in ``double_args``; this mirrors that, so the port is fed exactly what GDL
    was fed. Getting this wrong is not a small error -- it is the difference
    between comparing two implementations and comparing two different problems,
    which is what invalidated the first ``princomp`` bank.
    """
    if name not in double_args:
        return value
    if isinstance(value, list):
        return [np.float64(v) for v in value]
    return np.float64(value)


class TheIdlTypeRule(unittest.TestCase):
    """``_as_idl``: a plain Python value is IDL FLOAT; an explicit NumPy dtype
    is whatever the caller said.

    Pinned directly rather than through the differential class, because
    deleting the list branch it guards changes nothing on NumPy 2.5 --
    ``np.float32([...])`` returns a float32 array there by coincidence, so the
    obvious mutation does not fire. Stated in the module beside the branch too.
    """

    def test_a_plain_python_float_is_float(self):
        self.assertEqual(np.asarray(_as_idl(6.3)).dtype, np.float32)

    def test_a_plain_python_list_is_float(self):
        self.assertEqual(np.asarray(_as_idl([1.0, 2.0])).dtype, np.float32)

    def test_an_explicit_float64_stays_double(self):
        self.assertEqual(np.asarray(_as_idl(np.float64(6.3))).dtype, np.float64)

    def test_an_explicit_float64_array_stays_double(self):
        arr = np.asarray([1.0, 2.0], dtype=np.float64)
        self.assertEqual(np.asarray(_as_idl(arr)).dtype, np.float64)

    def test_a_supplied_dof_list_does_not_promote_the_result(self):
        """The path the differential bank caught: `np.asarray(list)` defaults
        to float64, which promoted every downstream value and made `sa`
        disagree with GDL by 2.4e-8."""
        sa, dof, _e = sample_area([1.0, 10.0], 10.0, 6.3, 128, "centerin",
                                  0.785e-6, dof=[100.0, 200.0])
        self.assertEqual(np.asarray(dof).dtype, np.float32)
        self.assertEqual(np.asarray(sa).dtype, np.float32)


class AgainstTheGdlGolden(unittest.TestCase):
    """The differential layer: GDL running ``soda2_samplearea.pro`` unmodified."""

    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking S1 against IDL, "
                "which is the state it was in until 2026-09-12.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def _run(self, case):
        dbl = set(case["double_args"])
        return sample_area(
            _idl_typed(case["diam"], "diam", dbl),
            _idl_typed(case["res"], "res", dbl),
            _idl_typed(case["armwidth"], "armwidth", dbl),
            case["numdiodes"],
            case["eawmethod"],
            _idl_typed(case["wavelength"], "wavelength", dbl),
            dofconst=_idl_typed(case["dofconst_in"], "dofconst", dbl),
            dof=_idl_typed(case["dof_in"], "dof", dbl),
        )

    def test_the_bank_reaches_the_branches_that_matter(self):
        """A bank missing any of these would prove much less than it looks.

        Names are asserted rather than a count: a count grows when someone
        adds a duplicate geometry, and says nothing about coverage.
        """
        names = {c["name"] for c in self.cases}
        for needed in ("twods_reconstruct", "twods_centerin", "twods_allin",
                       "wavelength_float_lawson", "wavelength_double_lawson",
                       "wavelength_not_lawson", "dofconst_supplied",
                       "dof_clamped_by_arms", "dof_supplied_mixed_zeros",
                       "dof_supplied_sums_to_zero", "armwidth_double_only",
                       "unsupported_method"):
            self.assertIn(needed, names)

    def test_every_runnable_case_matches_idl_exactly(self):
        """Exactly: no tolerance, no ``places=``.

        Both sides are single precision by the same rule now, so equality is
        the honest assertion. A tolerance here would hide the next promotion
        bug the way the float64 port hid this one.
        """
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                sa, dof, eff = self._run(case)
                for label, got, want in (("SA", sa, case["SA"]),
                                         ("DOF", dof, case["DOF"]),
                                         ("EW", eff, case["EW"])):
                    flat = np.atleast_1d(np.asarray(got)).ravel()
                    self.assertEqual(
                        len(flat), len(want),
                        f"{label}: port returned {len(flat)} value(s), IDL "
                        f"{len(want)} -- a shape divergence, not a rounding one")
                    for i, (g, w) in enumerate(zip(flat, want, strict=True)):
                        self.assertEqual(
                            float(g), w,
                            f"{label}[{i}]: got {float(g)!r}, IDL {w!r}")
            checked += 1
        self.assertGreaterEqual(checked, 15)

    def test_the_port_computes_in_single_precision(self):
        """The property behind every exact match above, asserted directly
        rather than inferred from them."""
        sa, dof, eff = sample_area([1.0, 105.0], 10.0, 6.3, 128,
                                   "reconstruct", 0.785e-6)
        for name, arr in (("sa", sa), ("dof", dof), ("eff_wid", eff)):
            self.assertEqual(np.asarray(arr).dtype, np.float32, name)

    def test_a_float64_wavelength_misses_the_lawson_branch_as_idl_does(self):
        """Finding S1-a, pinned from the port's side.

        The same physical wavelength written as an IDL DOUBLE takes the
        Knollenberg branch instead of Lawson's -- a factor of 8.12/3.0 in the
        depth of field, silently. ``np.isclose`` here would be a fix, and
        fixing it is exactly what this port must not do.
        """
        _sa_f, dof_float, _ef = sample_area(50.0, 10.0, 6.3, 128, "centerin",
                                            0.785e-6)
        _sa_d, dof_double, _ed = sample_area(50.0, 10.0, 6.3, 128, "centerin",
                                             np.float64(0.785e-6))
        self.assertAlmostEqual(float(dof_float) / float(dof_double),
                               8.12 / 3.0, places=5)

    def test_a_single_double_argument_promotes_the_whole_chain(self):
        """``armwidth`` alone is enough: ``prht = armwidth*1.0e4`` goes DOUBLE
        and ``dof < prht`` carries it into everything downstream. Measured
        under GDL as ``armwidth_double_only``, and the reason this bank's own
        first run recorded double-precision answers production never computes.
        """
        sa_single, _d, _e = sample_area([1.0], 10.0, 6.3, 128, "centerin",
                                        0.785e-6)
        sa_promoted, _d, _e = sample_area([1.0], 10.0, np.float64(6.3), 128,
                                          "centerin", 0.785e-6)
        self.assertEqual(np.asarray(sa_single).dtype, np.float32)
        self.assertEqual(np.asarray(sa_promoted).dtype, np.float64)

    def test_the_unsupported_method_case_halts_idl_and_raises_here(self):
        """The one case with no golden values, and the golden says why: IDL's
        ``ELSE: stop`` drops to the interactive prompt and blocks, measured by
        killing GDL after 20 s. The port raises instead -- a divergence its
        own docstring names.
        """
        halted = [c for c in self.cases if c["status"] == "HALTED"]
        self.assertEqual([c["name"] for c in halted], ["unsupported_method"])
        with self.assertRaises(UnsupportedSampleVolumeMethod):
            sample_area(100.0, 10.0, 6.3, 128, "wobble", 0.785e-6)


if __name__ == "__main__":
    unittest.main()
