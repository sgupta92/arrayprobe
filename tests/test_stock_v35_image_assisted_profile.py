# SPDX-License-Identifier: BSD-3-Clause
"""``stock-v3.5-image-assisted``: stock-v3.5 with only ``rej_hollow`` off.

The headline deliverable is the "image-assisted CIP processing chain" -- a run of
the v3.5 engine under a profile that isolates the hollow-rejection axis, which
the existing ``oracles-production-v3.5`` A/B could not (it moves ``rej_hollow``
**and** both aspect-ratio ceilings at once). See
``arrayprobe_uiops.measure.IMAGE_ASSISTED_V35_REJECT_CONFIG`` and
``arrayprobe.profiles.register_stock_v35_image_assisted`` for the full
evidence (the author's 200 triage labels) and the honest caveat this profile
does not resolve (not optimal at 55-105 um).

**Registered, not shipped -- and that is load-bearing, not a style choice.**
Unlike ``STOCK_V35``/``ORACLES_PRODUCTION_V35`` this profile is reached only
through the string registry (``PROFILES[name]`` / ``profile(name)``), the same
way a fork's own variant is, and is never a ``profiles.STOCK_V35_...``
module attribute. Two existing tests pin the module's *shipped* surface and
would have to be rewritten if this profile joined it:
``test_profile_registry.py::test_the_shipped_set_does_not_grow_with_registrations``
pins :data:`~arrayprobe.profiles.SHIPPED` to five names, and
``test_cli_engine_selection.py::
test_the_second_reason_names_the_v35_profiles_that_exist`` enumerates every
uppercase ``dir(profiles)`` name holding a ``FidelityProfile`` and pins that
list to exactly ``STOCK_V35``/``ORACLES_PRODUCTION_V35``. ``TestDoesNotJoinTheShippedSurface``
below is this test module's own record of why: it is not a chance omission.
"""

from __future__ import annotations

import dataclasses
import os
import unittest
from pathlib import Path

from tests._profile_registry_guard import module_hooks  # noqa: E402

from arrayprobe.profiles import (
    _BEHAVIOUR_FIELDS,
    ORACLES_PRODUCTION_V35,
    PROFILES,
    SHIPPED,
    STOCK_V35,
    STOCK_V314,
    is_v35_flavoured,
    profile,
    register_stock_v35_image_assisted,
)
from arrayprobe_uiops.measure import IMAGE_ASSISTED_V35_REJECT_CONFIG, STOCK_V35_REJECT_CONFIG

# Registrations made here are removed when the module finishes.
setUpModule, tearDownModule = module_hooks()



class TheProfileIsRegisteredAndFindable(unittest.TestCase):
    """"the profile is registered" -- the first of the three minimum checks."""

    def test_calling_it_returns_a_fidelity_profile(self):
        p = register_stock_v35_image_assisted()
        self.assertEqual(p.name, "stock-v3.5-image-assisted")

    def test_it_is_reachable_through_the_live_registry_view(self):
        register_stock_v35_image_assisted()
        self.assertIn("stock-v3.5-image-assisted", PROFILES)

    def test_the_lookup_function_finds_the_same_object(self):
        p = register_stock_v35_image_assisted()
        self.assertIs(profile("stock-v3.5-image-assisted"), p)

    def test_it_is_idempotent_rather_than_raising_already_registered(self):
        """A lane script or a test module may call this more than once per
        process; register_profile() itself would raise ValueError on a second
        registration of the same name, so this must not reach it twice."""
        p1 = register_stock_v35_image_assisted()
        p2 = register_stock_v35_image_assisted()
        self.assertIs(p1, p2)

    def test_a_description_is_present_and_names_its_origin(self):
        """register_profile() itself refuses an empty description; this checks
        the content says something a later reader can act on."""
        d = register_stock_v35_image_assisted().description
        self.assertIn("a project decision, from 200 triage", d)
        self.assertIn("rej_hollow", d)


class TheProfileIsV35Flavoured(unittest.TestCase):
    """"v3.5-flavoured" -- the second minimum check. Both conditions
    ``is_v35_flavoured`` requires, not just the field comparison alone (see
    ``test_v35_profile_gate.py::TheDeclarationIsLoadBearing`` for why a field
    comparison alone is not enough -- ``stock-v3.1.4`` is field-identical to
    ``stock-v3.5`` and must NOT be admitted)."""

    def test_is_v35_flavoured_admits_it(self):
        self.assertTrue(is_v35_flavoured(register_stock_v35_image_assisted()))

    def test_every_behaviour_field_equals_stock_v35(self):
        p = register_stock_v35_image_assisted()
        for f in _BEHAVIOUR_FIELDS:
            with self.subTest(field=f):
                self.assertEqual(getattr(p, f), getattr(STOCK_V35, f),
                                  f"{f} differs from stock-v3.5, so is_v35_flavoured "
                                  "would (correctly) refuse this profile")

    def test_stock_v314_is_not_accidentally_admitted_by_this_profiles_existence(self):
        """Registering a third v3.5-declared profile must not loosen the gate
        for an undeclared one -- is_v35_flavoured(STOCK_V314) stays False."""
        register_stock_v35_image_assisted()
        self.assertFalse(is_v35_flavoured(STOCK_V314))


class OnlyRejHollowDiffersFromStockV35(unittest.TestCase):
    """"its fields equal STOCK_V35's in every respect except rej_hollow" --
    the third minimum check, read directly off the instruction."""

    def test_reject_thresholds_is_the_named_image_assisted_constant(self):
        p = register_stock_v35_image_assisted()
        self.assertIs(p.reject_thresholds, IMAGE_ASSISTED_V35_REJECT_CONFIG)

    def test_rej_hollow_is_off_where_stock_v35_is_on(self):
        p = register_stock_v35_image_assisted()
        self.assertFalse(p.reject_thresholds.rej_hollow)
        self.assertTrue(STOCK_V35.reject_thresholds.rej_hollow)

    def test_every_other_reject_field_equals_stock_v35_exactly(self):
        """max_edge_img_ar stays 6, max_comp_img_ar stays 5 -- explicitly the
        two fields the request says NOT to move, unlike oracles-production-v3.5
        which moves both of those too."""
        p = register_stock_v35_image_assisted()
        mine = dataclasses.asdict(p.reject_thresholds)
        stock = dataclasses.asdict(STOCK_V35.reject_thresholds)
        del mine["rej_hollow"]
        del stock["rej_hollow"]
        self.assertEqual(mine, stock)
        self.assertEqual(p.reject_thresholds.max_edge_img_ar, 6)
        self.assertEqual(p.reject_thresholds.max_comp_img_ar, 5)

    def test_the_reject_config_object_is_a_distinct_constant_not_an_alias(self):
        """Guards against a refactor that makes STOCK_V35_REJECT_CONFIG and
        IMAGE_ASSISTED_V35_REJECT_CONFIG alias each other (test_profile_
        reject_thresholds.py has the same guard for the v3.1.4 pair)."""
        self.assertIsNot(IMAGE_ASSISTED_V35_REJECT_CONFIG, STOCK_V35_REJECT_CONFIG)
        self.assertNotEqual(IMAGE_ASSISTED_V35_REJECT_CONFIG, STOCK_V35_REJECT_CONFIG)

    def test_this_confounds_only_one_axis_unlike_oracles_production_v35(self):
        """oracles-production-v3.5 moves rej_hollow AND both aspect-ratio
        ceilings; this profile isolates rej_hollow alone -- the entire reason
        a new profile was requested instead of reusing that one."""
        prod_v35 = ORACLES_PRODUCTION_V35.reject_thresholds
        mine = register_stock_v35_image_assisted().reject_thresholds
        self.assertNotEqual(mine.max_edge_img_ar, prod_v35.max_edge_img_ar)
        self.assertNotEqual(mine.max_comp_img_ar, prod_v35.max_comp_img_ar)
        self.assertEqual(mine.rej_hollow, prod_v35.rej_hollow)  # the one shared axis


class TheEngineGateAcceptsIt(unittest.TestCase):
    """"the --engine 3.5 gate accepts it". ``scripts/run_flight.py``'s gate at the
    ``ENGINE == "3.5"`` branch is exactly ``if not is_v35_flavoured(PROFILE): ...
    return 2`` -- the same test ``test_v35_profile_gate.py`` uses for the two
    shipped v3.5 profiles, applied here to the new one. The acceptance half is
    ``TheProfileIsV35Flavoured.test_is_v35_flavoured_admits_it`` above (this
    class carried a byte-identical copy until 2026-09-27; it is in
    ``archive/retired_tests/``)."""

    def test_the_v314_profiles_are_still_refused_by_the_same_gate(self):
        for p in (STOCK_V314,):
            with self.subTest(profile=p.name):
                self.assertFalse(is_v35_flavoured(p))


class NoExistingProfileWasModified(unittest.TestCase):
    """"Add only -- do not modify any existing profile's fields." Frozen
    dataclasses make a mutation impossible, but a construction bug (e.g.
    accidentally replacing INTO stock35 instead of building a new object)
    could still leave the wrong object registered under the wrong name."""

    def test_stock_v35_still_has_rej_hollow_on(self):
        register_stock_v35_image_assisted()
        self.assertTrue(STOCK_V35.reject_thresholds.rej_hollow)
        self.assertIs(STOCK_V35.reject_thresholds, STOCK_V35_REJECT_CONFIG)

    def test_stock_v35_and_the_new_profile_are_different_objects(self):
        p = register_stock_v35_image_assisted()
        self.assertIsNot(p, STOCK_V35)
        self.assertNotEqual(p.name, STOCK_V35.name)

    def test_oracles_production_v35_is_unaffected(self):
        self.assertFalse(ORACLES_PRODUCTION_V35.reject_thresholds.rej_hollow)
        self.assertEqual(ORACLES_PRODUCTION_V35.reject_thresholds.max_edge_img_ar, 4)
        self.assertEqual(ORACLES_PRODUCTION_V35.reject_thresholds.max_comp_img_ar, 4)


class TheProfileModuleSideEffectResolvesInAFreshProcess(unittest.TestCase):
    """``arrayprobe_uiops.register_image_assisted`` -- the module named by
    the CIP lane scripts' ``PROFILE_MODULE``/``PROFILE_MODULES`` so a fresh
    ``run_flight.py --_run-chunk`` worker subprocess can resolve
    ``PROFILES["stock-v3.5-image-assisted"]``.

    **This is a real regression, not a hypothetical.** The first
    chunk-parallel S3 launch of this profile (2026-09-18, 14:15:58) failed all
    11 workers within 3 seconds: ``s3_v35_chunks.py`` set
    ``PROFILE_MODULE = ""`` (correct for the two SHIPPED v3.5 profiles, wrong
    for this registered one), so every worker hit ``KeyError:
    'stock-v3.5-image-assisted'`` at ``run_flight.py``'s
    ``PROFILE = PROFILES[profile_name]``, before writing a single record.
    Run in a real subprocess -- a same-process import proves nothing here,
    because the whole bug was that a FRESH process's registry starts empty
    for anything not shipped."""

    def test_importing_the_module_alone_makes_the_profile_resolvable(self):
        import subprocess
        import sys as _sys

        src = str(Path(__file__).resolve().parents[1] / "src")
        code = (
            "import importlib; "
            "importlib.import_module('arrayprobe_uiops.register_image_assisted'); "
            "from arrayprobe.profiles import PROFILES; "
            "p = PROFILES['stock-v3.5-image-assisted']; "
            "print('rej_hollow=' + str(p.reject_thresholds.rej_hollow))"
        )
        out = subprocess.run(
            [_sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[1]),
            env={**os.environ, "PYTHONPATH": src},
            capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("rej_hollow=False", out.stdout)

    def test_it_is_the_module_the_lane_scripts_actually_name(self):
        """Pins the exact string the lane scripts pass as PROFILE_MODULE --
        a typo here would reproduce the 2026-09-18 failure with a different
        traceback (ModuleNotFoundError instead of KeyError)."""
        lane = (Path(__file__).resolve().parents[1] / "_decoded" / "cip160906"
                / "s3_v35_chunks.py")
        if not lane.is_file():
            self.skipTest(f"lane script not present in this checkout: {lane}")
        text = lane.read_text(encoding="utf-8")
        self.assertIn(
            '"stock-v3.5-image-assisted": "arrayprobe_uiops.register_image_assisted"', text)


class TheNewProfileDoesNotJoinTheShippedSurface(unittest.TestCase):
    """Documents the deliberate design choice (see module docstring): this
    profile is registered, not shipped, specifically so it does not trip the
    two tests named above. If either assertion here ever fails, the reasoning
    in ``register_stock_v35_image_assisted``'s docstring needs re-reading
    before "fixing" it by editing those other tests."""

    def test_it_is_not_in_shipped(self):
        register_stock_v35_image_assisted()
        self.assertNotIn("stock-v3.5-image-assisted", SHIPPED)
        # And SHIPPED itself is untouched: still exactly the five names it was.
        self.assertEqual(SHIPPED, frozenset(
            {STOCK_V314.name, "oracles-2016", "oracles-production",
             STOCK_V35.name, "oracles-production-v3.5"}))

    def test_it_is_not_a_module_attribute(self):
        import arrayprobe.profiles as p
        register_stock_v35_image_assisted()
        self.assertFalse(hasattr(p, "STOCK_V35_IMAGE_ASSISTED"))
        self.assertNotIn("STOCK_V35_IMAGE_ASSISTED", dir(p))


if __name__ == "__main__":
    unittest.main()
