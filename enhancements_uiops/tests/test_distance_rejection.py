# SPDX-License-Identifier: BSD-3-Clause
"""``distance_rejection.py`` -- the Korolev & Field 2015 distance alternative
to a fixed inter-arrival time threshold."""
from __future__ import annotations

import unittest

import numpy as np

from arrayprobe_enhancements.distance_rejection import (
    distance_from_time,
    is_shattered_by_distance,
    threshold_to_distance,
)


class DistanceFromTime(unittest.TestCase):
    def test_is_time_times_airspeed(self):
        self.assertEqual(distance_from_time(2.0, 100.0), 200.0)

    def test_broadcasts_over_arrays(self):
        int_arr = np.array([1.0, 2.0, 3.0])
        tas = np.array([100.0, 100.0, 100.0])
        np.testing.assert_allclose(distance_from_time(int_arr, tas), [100.0, 200.0, 300.0])


class ThresholdToDistance(unittest.TestCase):
    def test_is_time_threshold_times_reference_tas(self):
        self.assertEqual(threshold_to_distance(ia_thresh=6e-6, reference_tas=150.0), 6e-6 * 150.0)


class IsShatteredByDistance(unittest.TestCase):
    """The property that actually matters: agreement with the time-only test AT the
    reference airspeed, and divergence away from it -- otherwise this module would
    just be the time test in a longer form."""

    def test_agrees_with_the_time_only_test_at_the_reference_tas(self):
        ia_thresh = 6e-6
        reference_tas = 150.0
        threshold_distance = threshold_to_distance(ia_thresh, reference_tas)

        int_arr = np.array([5e-6, 6e-6, 7e-6])
        tas_at_reference = np.full(3, reference_tas)

        by_distance = is_shattered_by_distance(int_arr, tas_at_reference, threshold_distance)
        by_time = int_arr < ia_thresh
        np.testing.assert_array_equal(by_distance, by_time)

    def test_diverges_from_the_time_only_test_when_tas_has_drifted(self):
        """The whole point: a particle pair the time test would flag can be
        physically far apart (and vice versa) once TAS has moved away from the
        value the threshold was calibrated at."""
        ia_thresh = 6e-6
        reference_tas = 150.0
        threshold_distance = threshold_to_distance(ia_thresh, reference_tas)

        # Same inter-arrival TIME as the reference case, but flown much faster:
        # physically farther apart, so the distance test should NOT flag it even
        # though the time-only test still would.
        int_arr = np.array([5.5e-6])
        fast_tas = np.array([300.0])
        self.assertTrue(bool(int_arr[0] < ia_thresh))  # the time-only test flags this
        self.assertFalse(bool(is_shattered_by_distance(int_arr, fast_tas, threshold_distance)[0]))

    def test_a_slow_particle_can_be_flagged_when_time_alone_would_not(self):
        ia_thresh = 6e-6
        reference_tas = 150.0
        threshold_distance = threshold_to_distance(ia_thresh, reference_tas)

        # Longer inter-arrival TIME than ia_thresh (time test would NOT flag it),
        # but flown slowly enough that the physical separation is still small.
        int_arr = np.array([7e-6])
        slow_tas = np.array([50.0])
        self.assertFalse(bool(int_arr[0] < ia_thresh))  # the time-only test does not flag this
        self.assertTrue(bool(is_shattered_by_distance(int_arr, slow_tas, threshold_distance)[0]))


class ThePaperPrintsThisEquationWrong(unittest.TestCase):
    """Guard against a future reader "correcting" this module to match the paper.

    Korolev & Field (2015) prints the conversion as a DIVISION by airspeed, twice --
    p. 765 ("the inter-particle distance Delta-x = Delta-t/u will be used instead of
    Delta-t") and p. 766 ("chi* = tau*/u will be used instead of phi(Delta-t) and
    tau*, respectively"). Both are dimensionally impossible: a time divided by a speed
    has units of s^2/m, not metres. The intended operation is multiplication.

    That makes this the rare case where the primary source is the hazard. Someone who
    obtains the PDF, reads the printed equation and "fixes" the code to match it would
    shift every distance by eight orders of magnitude with the paper apparently
    supporting them. A comment would not stop that; this test does.

    The evidence is in ``enhancements_uiops/docs/distance_rejection_design.md``, including
    the decisive one: the same paper writes the identical relation CORRECTLY in the
    inverse direction on p. 764 (``Delta-t_sh = L_sh/u``, a duration from a "spatial
    length... along the flight direction"), so it contradicts itself rather than using
    an unusual convention.
    """

    #: Read off the axes of the paper's own Fig. 5 (p. 766), which plots measured
    #: inter-particle distance -- and the cut-off chi* on the same axis -- in METRES,
    #: spanning about 1e-3 to 1e2 m. Any conversion whose output cannot land in this
    #: band for realistic OAP inputs could not have produced that figure.
    FIG5_METRES_LO, FIG5_METRES_HI = 1e-3, 1e2

    def test_realistic_inputs_land_on_the_paper_s_own_distance_axis(self):
        """Typical OAP inter-arrival times at aircraft speed must give Fig. 5 metres."""
        # Inter-arrival times spanning the range the port actually fits thresholds over
        # (the 2D-S default ia_thresh is 6e-6 s), at a representative aircraft TAS.
        int_arr = np.array([1e-5, 1e-4, 1e-3, 1e-2])
        tas = np.full_like(int_arr, 100.0)

        distance = distance_from_time(int_arr, tas)

        self.assertTrue(
            np.all((distance >= self.FIG5_METRES_LO) & (distance <= self.FIG5_METRES_HI)),
            f"got {distance} m, outside Fig. 5's own {self.FIG5_METRES_LO}-"
            f"{self.FIG5_METRES_HI} m axis. If this failed because the conversion was "
            "changed to DIVIDE by airspeed to match the equation printed on pp. 765-766: "
            "that printed form is a dimensional error in the published paper. See "
            "enhancements_uiops/docs/distance_rejection_design.md -- the paper writes the same "
            "relation correctly as Delta-t_sh = L_sh/u on p. 764, and its Fig. 5 axes "
            "cannot be reproduced by the printed form.")

    def test_dividing_by_airspeed_would_miss_that_axis_entirely(self):
        """The other side of the check: show the printed form really is unusable.

        Without this, the test above could pass for a conversion that happened to be
        in range for some other reason. Drawing the two sides from different places is
        this project's standing rule for a check that tests anything.
        """
        int_arr = np.array([1e-5, 1e-4, 1e-3, 1e-2])
        tas = np.full_like(int_arr, 100.0)

        as_printed = int_arr / tas  # Delta-t/u, exactly as pp. 765-766 print it

        self.assertTrue(
            np.all(as_printed < self.FIG5_METRES_LO),
            "the paper's printed Delta-t/u form was expected to fall entirely below "
            "Fig. 5's axis, which is the arithmetic showing it cannot be what produced "
            f"that figure; got {as_printed}")

    def test_the_cut_off_distance_is_tau_star_times_u(self):
        """chi* is the cut-off DISTANCE -- the distance analogue of the cut-off time.

        Fig. 5 draws chi* on a metre axis, which is what rules out the alternative
        reading (that chi* might be some dimensionless ratio) considered before the
        paper was read directly.

        The band asserted here is NOT Fig. 5's axis: this port's own 2D-S default
        tau* (6e-6 s, ``defaultIntArrThresh``) at a typical TAS gives 0.9 mm, which
        sits just below that figure's 1e-3 m floor -- Fig. 5 is an OAP-2DC at 25 um
        in a different campaign, so its plotted range is not a bound on every probe's
        cut-off. The anchor used instead is one this project can state exactly.
        """
        tau_star, u = 6e-6, 150.0
        chi_star = threshold_to_distance(tau_star, u)
        self.assertAlmostEqual(chi_star, tau_star * u)

        # A cut-off DISTANCE below one pixel would be meaningless: the probe cannot
        # resolve a separation finer than its own pixel resolution (10 um on the 2D-S,
        # 25 um on the OAP-2DC of the paper's Fig. 5). Multiplication gives 0.9 mm --
        # tens of pixels, a physically sensible fragment separation. The paper's
        # printed division gives 4e-8 m, roughly 1/250 of a single 2D-S pixel.
        finest_pixel_m = 10e-6
        self.assertGreater(
            chi_star, finest_pixel_m,
            "a cut-off distance finer than one probe pixel cannot be meaningful; see "
            "enhancements_uiops/docs/distance_rejection_design.md for why the division form "
            "printed on pp. 765-766 of Korolev & Field (2015) is a typo in the paper")
        self.assertLess(tau_star / u, finest_pixel_m)  # the printed form, for contrast


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
