# SPDX-License-Identifier: BSD-3-Clause
"""The m-D registry.

An m-D relation is a handful of coefficients that change every mass, IWC and
mass-weighted diameter computed downstream, and two published relations
routinely differ by a factor of two. So the tests that matter here are not
about lookup; they are about the registry's refusal to hold a number whose
origin nobody can check, and about the five relations this project has NOT read
staying visibly unread.

That second point is the one worth stating plainly. The plan names Brown &
Francis, Heymsfield 2010, Erfani & Mitchell, Leroy and Finlon. **Updated
2026-09-14**: Brown & Francis (1995) has now been read
(`arrayprobe_enhancements.brown_francis_1995`, citing Eq. 3 p. 411) and is
registered; the other four remain unread or unrepresentable and stay declared
gaps carrying no coefficients. Typing their coefficients from recollection
would have produced a registry that looks complete and cannot be trusted
anywhere -- the invention would survive review precisely because it is
plausible. These tests keep the remaining four that way.
"""

from __future__ import annotations

import dataclasses
import unittest

from arrayprobe_enhancements import md_relations as md


class AnEntryMustSayWhereItCameFrom(unittest.TestCase):
    """The refusal, in each of the ways it can be attempted."""

    def _relation(self, **overrides):
        base = dict(
            key="test_relation", description="d", form="power_law_diameter",
            source="Someone et al. 2020", provenance="read from p. 7",
            established="transcribed")
        base.update(overrides)
        return md.MassRelation(**base)

    def tearDown(self):
        md.REGISTRY.pop("test_relation", None)

    def test_a_relation_with_no_source_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            md.register(self._relation(source=""))
        self.assertIn("source", str(caught.exception))

    def test_a_relation_with_no_provenance_is_refused(self):
        """Source says where it was published; provenance says how THIS
        repository established it. Both are required, and they are different
        questions."""
        with self.assertRaises(ValueError) as caught:
            md.register(self._relation(provenance="   "))
        self.assertIn("provenance", str(caught.exception))

    def test_remembered_is_not_an_allowed_establishment(self):
        with self.assertRaises(ValueError) as caught:
            md.register(self._relation(established="remembered"))
        self.assertIn("remembered", str(caught.exception))

    def test_a_well_formed_relation_registers(self):
        md.register(self._relation())
        self.assertIn("test_relation", md.available())

    def test_overwriting_must_be_asked_for(self):
        """Silently replacing a relation changes every mass downstream of it
        with nothing in the record to say so."""
        md.register(self._relation())
        with self.assertRaises(ValueError):
            md.register(self._relation(description="different"))
        md.register(self._relation(description="different"), replace=True)
        self.assertEqual(md.get("test_relation").description, "different")


class TheGapsStayGaps(unittest.TestCase):
    """The five relations the plan names and this project has not read."""

    def test_every_declared_gap_carries_no_coefficients(self):
        """A Gap has nowhere to put a number -- asserted, not assumed.

        If a future edit gives Gap a coefficient field, this fails, and the
        conversation that follows is the right one to have.
        """
        numeric_fields = [
            f.name for f in dataclasses.fields(md.Gap)
            if f.type not in ("str", "tuple") and f.name != "fields"
        ]
        self.assertEqual(numeric_fields, [],
                         f"Gap has gained fields that could hold coefficients: "
                         f"{numeric_fields}")

    def test_the_five_the_plan_names_are_all_accounted_for(self):
        """Either registered (read and verified) or declared as a gap --
        never simply missing. brown_francis_1995 moved from the gap set to
        the registry 2026-09-14; the other four remain gaps."""
        expected = {"brown_francis_1995", "heymsfield_2010",
                    "erfani_mitchell_2016", "leroy_2016", "finlon_2019"}
        declared = {g.key for g in md.DECLARED_GAPS}
        registered = set(md.available())
        accounted_for = declared | registered
        self.assertEqual(expected - accounted_for, set(),
                         "a relation the plan names is neither registered nor "
                         "declared as a gap, so it has simply gone missing")

    def test_a_gap_says_what_closing_it_requires(self):
        """A gap that only says 'not done' is a shrug; one that says what to do
        is a task."""
        for gap in md.DECLARED_GAPS:
            with self.subTest(gap=gap.key):
                self.assertTrue(gap.citation.strip())
                self.assertTrue(gap.why_not_yet.strip())
                self.assertTrue(len(gap.to_close.strip()) > 40,
                                f"{gap.key}'s to_close is too thin to act on")

    def test_registering_a_declared_gap_is_refused(self):
        """The ratchet: reading the paper means removing the gap in the same
        change, so the two accounts cannot disagree.

        heymsfield_2010 remains a declared gap (source not held, searched
        2026-09-14); brown_francis_1995 moved out of DECLARED_GAPS the same
        day, which is what makes it the wrong key for this test now."""
        with self.assertRaises(ValueError) as caught:
            md.register(md.MassRelation(
                key="heymsfield_2010", description="d",
                form="power_law_diameter", source="Heymsfield et al. 2010",
                provenance="typed from memory", established="transcribed"))
        self.assertIn("DECLARED_GAPS", str(caught.exception))

    def test_asking_for_a_gap_by_key_explains_rather_than_KeyErrors_blankly(self):
        with self.assertRaises(KeyError) as caught:
            md.get("heymsfield_2010")
        message = str(caught.exception)
        self.assertIn("declared gap", message)
        self.assertIn("To close it", message)

    def test_no_key_is_both_registered_and_a_gap(self):
        self.assertEqual(set(md.available()) & {g.key for g in md.DECLARED_GAPS},
                         set())


class WhatIsRegisteredIsWhatWasVerified(unittest.TestCase):
    def test_the_four_verified_relations_are_present(self):
        self.assertEqual(set(md.available()),
                         {"uiops_single_mass", "baker_lawson_2006_area",
                          "doc0223_effective_density", "brown_francis_1995"})

    def test_every_entry_names_the_code_that_already_applies_it(self):
        """Registering a relation must never mean writing a second copy of it."""
        for key in md.available():
            with self.subTest(relation=key):
                self.assertTrue(md.get(key).implementation.strip())

    def test_every_entry_provenance_is_checkable(self):
        """A provenance that cannot be followed is decoration.

        Each must name either a file (with or without a line) or a document
        with a table/page -- checked crudely on purpose: the point is that a
        reader has somewhere to go, not that this test can parse citations.
        """
        for key in md.available():
            with self.subTest(relation=key):
                prov = md.get(key).provenance
                self.assertTrue(
                    any(marker in prov for marker in (".m", ".py", "Table", "p. ")),
                    f"{key}'s provenance names nothing a reader can open: {prov}")

    def test_the_ported_ones_say_ported(self):
        self.assertEqual(md.get("uiops_single_mass").established, "ported")
        self.assertEqual(md.get("baker_lawson_2006_area").established, "ported")

    def test_unstated_bounds_are_none_not_infinity(self):
        """An unstated validity range must not become an unbounded one.

        `single_mass.m` states no diameter range; recording (0, inf) would
        claim the source says something it does not.
        """
        low, high = md.get("uiops_single_mass").diameter_range_mm
        self.assertIsNone(low)
        self.assertIsNone(high)

    def test_an_unknown_key_lists_what_is_available(self):
        with self.assertRaises(KeyError) as caught:
            md.get("no_such_relation")
        self.assertIn("uiops_single_mass", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
