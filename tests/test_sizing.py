# SPDX-License-Identifier: BSD-3-Clause
"""The size-definition registry, and the phase guard it exists for.

The binding directive (2026-08-19) says ``dropsize`` stays behind the
registry and never becomes the universal sizing path.  These tests are what make
that a property of the code rather than a paragraph in a document -- a future
stage that wires ``dropsize`` into a generic path fails here.
"""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import dropsize as dropsize_module
from arrayprobe.sizing import (
    PhaseMismatchError,
    SizeDefinition,
    available_size_definitions,
    get_size_definition,
    register_size_definition,
    universal_size_definition,
)


class TestDropsizeRegistration(unittest.TestCase):
    def test_dropsize_is_registered(self):
        self.assertIn("dropsize", available_size_definitions())

    def test_it_is_registered_as_liquid_only(self):
        self.assertEqual("liquid", get_size_definition("dropsize").phase)

    def test_it_cannot_be_used_as_the_universal_path(self):
        """The whole point of the seam."""
        with self.assertRaises(PhaseMismatchError) as ctx:
            universal_size_definition("dropsize")
        self.assertIn("phase-neutrality", str(ctx.exception))

    def test_it_is_reachable_when_named_deliberately(self):
        definition = get_size_definition("dropsize")
        self.assertIs(dropsize_module.dropsize, definition.func)

    def test_it_declares_its_seven_outputs(self):
        self.assertEqual(
            (
                "center_in", "axis_ratio", "diameter_circle_fit",
                "diameter_horiz_chord", "diameter_vert_chord",
                "diameter_horiz_mean", "diameter_spheroid",
            ),
            get_size_definition("dropsize").outputs,
        )

    def test_it_carries_matlab_provenance(self):
        self.assertIn("dropsize.m", get_size_definition("dropsize").provenance)
        self.assertIn("imgProc_sm.m", get_size_definition("dropsize").provenance)

    def test_importing_arrayprobe_dropsize_is_what_registers_it(self):
        """Registration is an import side effect, so a lazily-imported module
        would leave the registry empty.  Named here so SPEC 1 lazy loading (S0
        amendment) cannot silently break the seam."""
        self.assertIs(
            dropsize_module.dropsize, available_size_definitions()["dropsize"].func
        )


class TestRegistryMechanics(unittest.TestCase):
    def setUp(self):
        self.key = "test_only_definition"

    def tearDown(self):
        from arrayprobe import sizing
        sizing._REGISTRY.pop(self.key, None)
        sizing._REGISTRY.pop("test_only_neutral", None)

    def _definition(self, key, phase):
        return SizeDefinition(
            key=key, func=lambda: None, phase=phase,
            description="test", provenance="test",
        )

    def test_a_neutral_definition_passes_the_universal_accessor(self):
        register_size_definition(self._definition("test_only_neutral", "any"))
        self.assertEqual("any", universal_size_definition("test_only_neutral").phase)

    def test_an_ice_definition_is_barred_too(self):
        """The guard is symmetric: it is about phase *assumptions*, not about
        liquid specifically.  An ice-only mass-dimension size would be just as
        wrong applied to a raindrop."""
        register_size_definition(self._definition(self.key, "ice"))
        with self.assertRaises(PhaseMismatchError):
            universal_size_definition(self.key)

    def test_duplicate_keys_are_rejected(self):
        register_size_definition(self._definition(self.key, "any"))
        with self.assertRaises(ValueError):
            register_size_definition(self._definition(self.key, "any"))

    def test_unknown_key_lists_what_is_registered(self):
        with self.assertRaises(KeyError) as ctx:
            get_size_definition("no_such_definition")
        self.assertIn("dropsize", str(ctx.exception))

    def test_invalid_phase_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            SizeDefinition(key="x", func=lambda: None, phase="mixed",
                           description="", provenance="")

    def test_available_returns_a_copy(self):
        available_size_definitions()["injected"] = None
        self.assertNotIn("injected", available_size_definitions())

    def test_definitions_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            get_size_definition("dropsize").phase = "any"


class TestUniversalDefinitionsArrivedWithS4(unittest.TestCase):
    """Until S4 there was deliberately **no** universal sizing path at all.

    That was the safer state, and this class asserted it: a stage that needed a
    generic size definition failed loudly rather than silently sizing ice
    crystals as raindrops.  S4 ported ``sizeDist.m`` and with it the six
    ``d_choice`` definitions, which is where a universal path was always meant
    to come from -- so the assertion now names *which* six may be universal
    instead of forbidding all of them.  ``dropsize`` must still not be among
    them; that is the part that was ever load-bearing.
    """

    #: ``sizeDist.m:755-767``, registered by :mod:`arrayprobe.sizedist`.
    S4_UNIVERSAL = {
        "sizedist_length", "sizedist_width", "sizedist_mean",
        "sizedist_hypot", "sizedist_max", "sizedist_minR",
    }

    def test_every_registered_definition_declares_a_phase(self):
        for key, definition in available_size_definitions().items():
            with self.subTest(key=key):
                self.assertIn(definition.phase, {"any", "liquid", "ice"})

    @needs_v314_engine
    def test_only_the_six_d_choice_definitions_are_universal(self):
        import arrayprobe.sizedist  # noqa: F401 -- registers the six

        universal = {
            k for k, d in available_size_definitions().items() if d.phase == "any"
        }
        self.assertEqual(
            self.S4_UNIVERSAL, universal,
            "the set of universal size definitions changed -- if something new "
            "claims phase='any', check it is not dropsize by another name",
        )

    def test_dropsize_remains_liquid_only(self):
        self.assertEqual(get_size_definition("dropsize").phase, "liquid")


if __name__ == "__main__":
    unittest.main()
