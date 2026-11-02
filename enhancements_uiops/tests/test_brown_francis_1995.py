# SPDX-License-Identifier: BSD-3-Clause
"""Brown & Francis (1995) mass-diameter power law.

The paper (Eq. 3, p. 411; confirmed p. 413) gives no single worked
(D, M) example in its text -- it validates the fit against an IWC ratio
over a size distribution (Figs. 3-4), not a lookup value. So the check here
is that the module's transcribed coefficients (a = 7.38e-11, b = 1.9, D in
microns, M in grams) reproduce values computed independently from those same
printed numbers -- i.e. that the transcription into code matches the
equation as printed, at several diameters spanning the paper's own
"25 to 400 microns" evaluation range and beyond it into the millimetre
particles the introduction calls out (p. 410, "Crystals of around 1 mm in
diameter are commonly observed").
"""
from __future__ import annotations

import unittest

from arrayprobe_enhancements import brown_francis_1995 as bf95


class TheCoefficientsAreTranscribedCorrectly(unittest.TestCase):
    def test_a_and_b_match_the_paper(self):
        """Eq. 3 / p. 413's confirming sentence, verbatim."""
        self.assertEqual(bf95.A_COEFFICIENT_G_UM, 7.38e-11)
        self.assertEqual(bf95.B_EXPONENT, 1.9)

    def test_small_crystal_sphere_regime_matches_the_paper(self):
        """p. 411: below 100 microns, solid ice spheres (rho_ice), a=4.82e-13,
        b=3 exactly -- not a separate fit."""
        self.assertEqual(bf95.SMALL_CRYSTAL_SPHERE_A, 4.82e-13)
        self.assertEqual(bf95.SMALL_CRYSTAL_SPHERE_B, 3.0)


class MassAtSeveralDiametersMatchesTheEquationAsPrinted(unittest.TestCase):
    """Independently computed a*D**b at each diameter, D in microns, M in
    grams -- the units the paper states, checked explicitly rather than
    assumed, since a diameter in the wrong unit (e.g. this port's usual
    centimetres) would silently give a mass wrong by many orders of
    magnitude with no error raised.
    """

    def test_at_100_microns(self):
        # a * 100**1.9 = 7.38e-11 * 6309.5734... = 4.656465...e-7 g
        self.assertAlmostEqual(bf95.mass_bf95(100.0), 4.656465202263825e-07,
                               delta=1e-15)

    def test_at_200_microns(self):
        self.assertAlmostEqual(bf95.mass_bf95(200.0), 1.7378542630621044e-06,
                               delta=1e-13)

    def test_at_500_microns(self):
        self.assertAlmostEqual(bf95.mass_bf95(500.0), 9.910586811290034e-06,
                               delta=1e-13)

    def test_at_1000_microns_the_1mm_crystal_the_introduction_names(self):
        """p. 410: "Crystals of around 1 mm in diameter are commonly
        observed in cirrus clouds"."""
        self.assertAlmostEqual(bf95.mass_bf95(1000.0), 3.6987617841692673e-05,
                               delta=1e-12)

    def test_at_2000_microns(self):
        self.assertAlmostEqual(bf95.mass_bf95(2000.0), 0.00013804267089861884,
                               delta=1e-10)

    def test_the_mass_is_monotonically_increasing_with_diameter(self):
        """A power law with a positive exponent -- a basic sanity property
        of the transcription, independent of the exact numeric values above.
        """
        diameters = [100.0, 150.0, 250.0, 400.0, 1000.0, 3000.0]
        masses = [bf95.mass_bf95(d) for d in diameters]
        self.assertEqual(masses, sorted(masses))


class TheSubHundredMicronRegimeIsNotSilentlySwitchedTo(unittest.TestCase):
    def test_below_100_microns_raises_rather_than_silently_using_the_wrong_regime(self):
        with self.assertRaises(ValueError) as caught:
            bf95.mass_bf95(99.999)
        self.assertIn("100", str(caught.exception))

    def test_exactly_100_microns_is_the_aggregate_regime_not_the_sphere_one(self):
        """p. 411 states the sphere assumption for D < 100 microns; 100 itself
        is therefore the aggregate branch's lower edge, not the sphere's."""
        # Would raise if the boundary were miscoded as strict '<=' instead of '<'.
        bf95.mass_bf95(100.0)


class RegisteredInTheMDRegistry(unittest.TestCase):
    """This module exists to close the `brown_francis_1995` gap in
    `md_relations.py` -- confirm the two agree rather than drifting apart."""

    def test_md_relations_points_at_this_module(self):
        from arrayprobe_enhancements import md_relations as md
        relation = md.get("brown_francis_1995")
        self.assertIn("brown_francis_1995", relation.implementation)
        self.assertEqual(relation.established, "transcribed")

    def test_brown_francis_1995_is_no_longer_a_declared_gap(self):
        from arrayprobe_enhancements import md_relations as md
        self.assertNotIn(
            "brown_francis_1995", {g.key for g in md.DECLARED_GAPS},
            "the paper has been read and registered; leaving the gap entry "
            "in place would let the registry and its own gap list disagree")


if __name__ == "__main__":
    unittest.main()
