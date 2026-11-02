# SPDX-License-Identifier: BSD-3-Clause
"""A regime carries the six S3 reject thresholds beside its two S4 ones (slice 1).


The two sides come from different places: the expected reject sets are read from
``profiles.PROFILES`` (each profile's own ``reject_thresholds``), the slot list from
``reject.RejectConfig``'s dataclass fields, and the resolved sets from
``regimes.resolve_reject``.
"""
from __future__ import annotations

import dataclasses
import unittest

from tests._profile_registry_guard import module_hooks

from arrayprobe import profiles, regimes
from arrayprobe.regimes import (
    INHERIT,
    REGIMES,
    REJECT_FIELDS,
    Inherit,
    Regime,
    UncitedRegimeField,
    regime_reject_sources,
    resolve_reject,
)
from arrayprobe_uiops.reject_core import (
    DEFAULT_REJECT_CONFIG,
    ORACLES_PRODUCTION_REJECT_CONFIG,
    RejectConfig,
)

setUpModule, tearDownModule = module_hooks()

_BASE = dict(name="test-slots", area_ratio_z=0.2, area_ratio_z_justification="x",
             default_int_arr_thresh=4e-6, default_int_arr_thresh_justification="x",
             provenance="x")


class TestSlotsMatchRejectConfig(unittest.TestCase):
    def test_the_six_slots_are_rejectconfigs_fields(self):
        self.assertEqual(REJECT_FIELDS,
                         tuple(f.name for f in dataclasses.fields(RejectConfig)))

    def test_each_slot_and_its_justification_is_a_regime_field(self):
        names = {f.name for f in dataclasses.fields(Regime)}
        for f in REJECT_FIELDS:
            self.assertIn(f, names)
            self.assertIn(f + "_justification", names)


class TestShippedRegimesInherit(unittest.TestCase):
    def test_every_shipped_regime_inherits_all_six_with_the_stated_reason(self):
        for name in ("liquid-warm", "ice", "mixed"):
            for f in REJECT_FIELDS:
                v = getattr(REGIMES[name], f)
                self.assertIs(v, INHERIT, (name, f))
                self.assertEqual(
                    v.reason, "inherits the profile's reject set; no regime-specific datum")

    def test_inherit_reproduces_every_profiles_reject_set_exactly(self):
        self.assertGreaterEqual(len(profiles.PROFILES), 4)
        for pname, prof in profiles.PROFILES.items():
            for rname in ("liquid-warm", "ice", "mixed"):
                with self.subTest(profile=pname, regime=rname):
                    got = resolve_reject(REGIMES[rname], prof.reject_thresholds)
                    self.assertEqual(got, prof.reject_thresholds)
                    for f in REJECT_FIELDS:
                        self.assertEqual(getattr(got, f), getattr(prof.reject_thresholds, f))
                    self.assertEqual(regime_reject_sources(REGIMES[rname]), {})

    def test_no_regime_returns_the_profile_set(self):
        self.assertIs(resolve_reject(None, ORACLES_PRODUCTION_REJECT_CONFIG),
                      ORACLES_PRODUCTION_REJECT_CONFIG)
        self.assertEqual(regime_reject_sources(None), {})


class TestCitedValueOverrides(unittest.TestCase):
    def test_a_cited_value_replaces_only_its_own_field(self):
        r = Regime(**_BASE, max_edge_img_ar=4,
                   max_edge_img_ar_justification="uioops_testing/calculate_reject_unified.m:76")
        got = resolve_reject(r, DEFAULT_REJECT_CONFIG)
        self.assertEqual(got, dataclasses.replace(DEFAULT_REJECT_CONFIG, max_edge_img_ar=4))
        self.assertEqual(regime_reject_sources(r), {"max_edge_img_ar": "regime:test-slots"})

    def test_a_cited_bool_overrides(self):
        r = Regime(**_BASE, rej_hollow=False,
                   rej_hollow_justification="uioops_testing/calculate_reject_unified.m:73")
        self.assertFalse(resolve_reject(r, DEFAULT_REJECT_CONFIG).rej_hollow)

    def test_an_inherit_with_its_own_reason_inherits(self):
        r = Regime(**_BASE, shadowed_area=Inherit("no datum on this probe"))
        self.assertEqual(resolve_reject(r, DEFAULT_REJECT_CONFIG), DEFAULT_REJECT_CONFIG)


class TestRefusals(unittest.TestCase):
    def test_an_uncited_value_is_refused(self):
        with self.assertRaises(UncitedRegimeField):
            Regime(**_BASE, max_comp_img_ar=4)
        with self.assertRaises(UncitedRegimeField):
            Regime(**_BASE, max_comp_img_ar=4, max_comp_img_ar_justification="   ")

    def test_an_inherit_without_a_reason_is_refused(self):
        with self.assertRaises(UncitedRegimeField):
            Inherit("")
        with self.assertRaises(UncitedRegimeField):
            Inherit("  ")

    def test_a_wrong_type_is_refused_even_when_cited(self):
        with self.assertRaises(UncitedRegimeField):
            Regime(**_BASE, shadowed_area=True, shadowed_area_justification="a:1")
        with self.assertRaises(UncitedRegimeField):
            Regime(**_BASE, rej_split=1, rej_split_justification="a:1")
        with self.assertRaises(UncitedRegimeField):
            Regime(**_BASE, max_edge_img_ar="4", max_edge_img_ar_justification="a:1")

    def test_an_unknown_slot_name_is_refused(self):
        with self.assertRaises(TypeError):
            Regime(**_BASE, max_img_ar=4)  # type: ignore[call-arg]

    def test_replace_on_a_shipped_regime_is_checked_too(self):
        with self.assertRaises(UncitedRegimeField):
            dataclasses.replace(REGIMES["ice"], name="x", rej_hollow=False)


class TestRegisterRegimeStillWorks(unittest.TestCase):
    def test_a_fork_registers_a_regime_with_a_cited_reject_slot(self):
        name = "test-fork-regime-slots"
        fresh = Regime(**{**_BASE, "name": name}, max_edge_img_ar=4,
                       max_edge_img_ar_justification="uioops_testing/calculate_reject_unified.m:76")
        try:
            self.assertIs(regimes.register_regime(fresh), fresh)
            self.assertIs(REGIMES[name], fresh)
            got = resolve_reject(REGIMES[name], DEFAULT_REJECT_CONFIG)
            self.assertEqual(got.max_edge_img_ar, 4)
        finally:
            regimes._REGIMES.pop(name, None)


if __name__ == "__main__":
    unittest.main()
