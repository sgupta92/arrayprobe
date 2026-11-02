# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for ``dropsize.py`` -- the decisions, not the numbers.

``test_dropsize_oracle.py`` already asserts the numbers against Octave running
the unmodified MATLAB, which is a stronger check than anything here could be.
This module covers what an oracle cannot: that each preserved defect is
preserved *for the stated reason*, so that a later "cleanup" fails a test that
names the behaviour rather than merely shifting a golden value.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError

import numpy as np

from arrayprobe.dropsize import (
    DIODES_ADDED_TO_HEIGHT,
    DIODES_ADDED_TO_LENGTH,
    HORIZONTAL_CHORD_ESD,
    HORIZONTAL_CHORDS,
    MAX_HORIZONTAL_CHORDS,
    MAX_VERTICAL_CHORDS,
    OVERSIZE,
    VERTICAL_CHORD_ESD,
    VERTICAL_CHORDS,
    DropSize,
    dropsize,
    horizontal_chord_to_spherical_dia,
    vertical_chord_to_spherical_dia,
)
from arrayprobe.matlab_compat import MatlabIndexError

DS = 0.010
DIODENUM = 128


class TestTables(unittest.TestCase):
    """The tables are the module's whole content; transcription errors are the
    single most likely defect, so they get checked structurally as well as
    against the oracle."""

    def test_lengths_match_the_max_constants(self):
        self.assertEqual(MAX_HORIZONTAL_CHORDS, len(HORIZONTAL_CHORDS))
        self.assertEqual(MAX_HORIZONTAL_CHORDS, len(HORIZONTAL_CHORD_ESD))
        self.assertEqual(MAX_VERTICAL_CHORDS, len(VERTICAL_CHORDS))
        self.assertEqual(MAX_VERTICAL_CHORDS, len(VERTICAL_CHORD_ESD))

    def test_chord_axes_are_exact_tenths(self):
        for table in (HORIZONTAL_CHORDS, VERTICAL_CHORDS):
            np.testing.assert_array_equal(
                table, np.array([round(0.1 * k, 10) for k in range(len(table))])
            )

    def test_diameters_are_monotone(self):
        """A non-monotone entry would be a typo; both tables are physical."""
        for table in (HORIZONTAL_CHORD_ESD, VERTICAL_CHORD_ESD):
            self.assertTrue(np.all(np.diff(table) > 0))

    def test_small_chords_are_the_identity(self):
        """Below ~0.3 mm a drop is spherical, so chord == diameter."""
        self.assertEqual(0.3, HORIZONTAL_CHORD_ESD[3])
        self.assertEqual(0.2, VERTICAL_CHORD_ESD[2])

    def test_horizontal_esd_is_below_chord_and_vertical_above(self):
        """The physical signature of an oblate drop, and a cheap check that the
        two tables have not been swapped: a big drop is wider than it is tall,
        so its horizontal chord overstates the equivalent sphere and its
        vertical chord understates it."""
        self.assertTrue(np.all(HORIZONTAL_CHORD_ESD[10:] < HORIZONTAL_CHORDS[10:]))
        self.assertTrue(np.all(VERTICAL_CHORD_ESD[10:] > VERTICAL_CHORDS[10:]))


class TestLookupIsExactAtGridPoints(unittest.TestCase):
    """``dropsize.m:198-201`` -- the off-by-one that cancels.

    ``i = round(chord * 10)`` is one below the index of the entry for that
    chord, and ``chord - chords(i)`` is correspondingly one grid step too large.
    At a grid point the two errors cancel exactly and the lookup returns the
    table value.  This is why the defect went unnoticed: on any test using round
    numbers it is invisible.
    """

    def test_horizontal_grid_points_return_table_values(self):
        for k in range(1, MAX_HORIZONTAL_CHORDS - 1):
            with self.subTest(chord=HORIZONTAL_CHORDS[k]):
                self.assertAlmostEqual(
                    HORIZONTAL_CHORD_ESD[k],
                    horizontal_chord_to_spherical_dia(HORIZONTAL_CHORDS[k]),
                    places=12,
                )

    def test_vertical_grid_points_return_table_values(self):
        for k in range(1, MAX_VERTICAL_CHORDS - 1):
            with self.subTest(chord=VERTICAL_CHORDS[k]):
                self.assertAlmostEqual(
                    VERTICAL_CHORD_ESD[k],
                    vertical_chord_to_spherical_dia(VERTICAL_CHORDS[k]),
                    places=12,
                )


class TestLookupExtrapolatesBetweenGridPoints(unittest.TestCase):
    """The consequence of the same off-by-one, measured.

    Above a grid point the slope comes from the segment *below* the chord rather
    than the one containing it, so the result is a first-order extrapolation.
    The vertical table is convex, so it always reads low; the horizontal table
    is nearly straight, so its error is negligible.  Both bounds are asserted so
    that a change in either direction is visible.
    """

    @staticmethod
    def _worst(chords, diameters, func, top):
        c = np.arange(0.051, top, 0.001)
        got = np.array([func(x) for x in c])
        want = np.interp(c, chords, diameters)
        return got - want

    def test_horizontal_error_is_negligible(self):
        err = self._worst(HORIZONTAL_CHORDS, HORIZONTAL_CHORD_ESD,
                          horizontal_chord_to_spherical_dia, 11.5)
        self.assertLess(np.abs(err).max(), 5e-4, "horizontal lookup error grew")

    def test_vertical_error_reaches_23_microns_and_is_always_low(self):
        err = self._worst(VERTICAL_CHORDS, VERTICAL_CHORD_ESD,
                          vertical_chord_to_spherical_dia, 5.3)
        self.assertLess(np.abs(err).max(), 2.5e-2)
        self.assertGreater(np.abs(err).max(), 2.0e-2)
        self.assertTrue(np.all(err <= 1e-12), "the convex table must read low")

    def test_function_is_discontinuous_at_half_grid_chords(self):
        """Two chords a nanometre apart can differ by 23 microns, because
        ``round`` switches table segments at the half-grid point."""
        g = VERTICAL_CHORDS[52] + 0.05
        jump = abs(vertical_chord_to_spherical_dia(g + 1e-9)
                   - vertical_chord_to_spherical_dia(g - 1e-9))
        self.assertGreater(jump, 1e-3)


class TestLastTableEntryIsUnreachable(unittest.TestCase):
    """``dropsize.m:199,220`` -- ``i + 1 < max`` where ``<=`` is still in range.

    The final entry of each table can never be returned, and the oversize
    sentinel takes over one grid step early.
    """

    def test_horizontal_top_entry_never_returned(self):
        self.assertEqual(8.9998, HORIZONTAL_CHORD_ESD[-1])
        self.assertAlmostEqual(8.96442, horizontal_chord_to_spherical_dia(11.54), places=5)
        self.assertEqual(OVERSIZE, horizontal_chord_to_spherical_dia(11.55))
        self.assertEqual(OVERSIZE, horizontal_chord_to_spherical_dia(11.6))

    def test_vertical_top_entry_never_returned(self):
        self.assertEqual(8.9230, VERTICAL_CHORD_ESD[-1])
        self.assertAlmostEqual(8.65028, vertical_chord_to_spherical_dia(5.34), places=5)
        self.assertEqual(OVERSIZE, vertical_chord_to_spherical_dia(5.35))
        self.assertEqual(OVERSIZE, vertical_chord_to_spherical_dia(5.4))

    def test_the_unreachable_diameters_are_named(self):
        """Stated as values so the consequence is legible: no drop is ever
        sized between these numbers and the 9.1 sentinel."""
        h = [horizontal_chord_to_spherical_dia(11.5 + 0.001 * k) for k in range(50)]
        self.assertLess(max(x for x in h if x != OVERSIZE), HORIZONTAL_CHORD_ESD[-1])


class TestZeroAndOversizeSentinels(unittest.TestCase):
    def test_below_half_a_grid_step_is_zero(self):
        """``i == 0`` -> 0, the documented "uncalculated" marker."""
        self.assertEqual(0.0, horizontal_chord_to_spherical_dia(0.0))
        self.assertEqual(0.0, horizontal_chord_to_spherical_dia(0.049))
        self.assertNotEqual(0.0, horizontal_chord_to_spherical_dia(0.05))

    def test_zero_is_ambiguous_with_a_real_measurement(self):
        """0.0 means both "chord below 0.05 mm" and "area < 1", and the sentinel
        is indistinguishable from a genuine zero-diameter answer.  Asserted so
        that downstream code is never written assuming 0 is a valid size."""
        self.assertEqual(0.0, horizontal_chord_to_spherical_dia(0.02))
        small = dropsize(10, 5, 0, 3, 2, DS, DS, DIODENUM)
        self.assertEqual(0.0, small.diameter_circle_fit)


class TestNegativeChordDies(unittest.TestCase):
    """``dropsize.m:221`` indexes with ``round(chord * 10)`` and never checks the
    sign, so MATLAB dies.  Reproduced rather than clamped: a port that returned
    a number where the original crashed would turn a failed run into output."""

    def test_negative_horizontal_chord_raises(self):
        with self.assertRaises(MatlabIndexError):
            horizontal_chord_to_spherical_dia(-5.0)

    def test_negative_vertical_chord_raises(self):
        with self.assertRaises(MatlabIndexError):
            vertical_chord_to_spherical_dia(-1.0)

    def test_message_names_the_index_matlab_reaches_first(self):
        """``D(i+1)`` is evaluated before ``D(i)`` at ``:221``, so ``i+1`` is the
        subscript MATLAB's error names.  Verified against Octave, which reports
        ``(-49)`` for a chord of -5."""
        with self.assertRaises(MatlabIndexError) as ctx:
            horizontal_chord_to_spherical_dia(-5.0)
        self.assertIn("(-49)", str(ctx.exception))

    def test_tiny_negative_chord_also_raises(self):
        """``round(-0.5) == -1`` away from zero, so ``i + 1 == 0`` and MATLAB
        still dies -- there is no small-negative escape."""
        with self.assertRaises(MatlabIndexError):
            horizontal_chord_to_spherical_dia(-0.05)


class TestEarlyReturn(unittest.TestCase):
    """``dropsize.m:116-125``."""

    def test_area_below_one_returns_zeros_with_axis_ratio_one(self):
        got = dropsize(10, 5, 0.5, 3, 2, DS, DS, DIODENUM)
        self.assertEqual(0, got.center_in)
        self.assertEqual(1.0, got.axis_ratio)
        for field in ("diameter_circle_fit", "diameter_horiz_chord",
                      "diameter_vert_chord", "diameter_horiz_mean",
                      "diameter_spheroid"):
            self.assertEqual(0.0, getattr(got, field), field)

    def test_axis_ratio_one_is_a_sentinel_not_a_measurement(self):
        """The early return reports a *circular* particle for an image too small
        to measure, which is the same value a genuinely circular drop would get
        from the 0-edge branch.  Asserted because the two are indistinguishable
        downstream."""
        unmeasurable = dropsize(10, 5, 0, 3, 2, DS, DS, DIODENUM)
        self.assertEqual(1.0, unmeasurable.axis_ratio)
        circular = dropsize(10, 10, 50, 0, 0, DS, DS, DIODENUM)
        self.assertEqual(1.0, circular.axis_ratio)

    def test_area_one_is_not_early(self):
        self.assertNotEqual(0.0, dropsize(10, 5, 1, 3, 2, DS, DS, DIODENUM).diameter_circle_fit)

    def test_early_return_ignores_the_scaling_factor(self):
        """``:117-121`` assigns the ``:114`` initialiser, never the scaled value
        from ``:132``, so the result is 0.0 whatever the diode sizes are."""
        got = dropsize(10, 5, 0, 3, 2, DS, 0.030, DIODENUM)
        self.assertEqual(0.0, got.diameter_circle_fit)


class TestBranchOutputMap(unittest.TestCase):
    """Which of the seven returns each branch fills -- the table in
    :class:`~arrayprobe.dropsize.DropSize`, asserted.

    The blanks matter: ``axis_ratio`` is 0 for every edge-touching particle, so
    reading it as a shape statistic across a whole flight mostly reads a branch
    indicator.
    """

    def test_two_edges_center_in(self):
        got = dropsize(20, 5, 50, 8, 6, DS, DS, DIODENUM)
        self.assertEqual(1, got.center_in)
        self.assertEqual(0.0, got.axis_ratio)
        self.assertGreater(got.diameter_circle_fit, 0)
        self.assertEqual(got.diameter_circle_fit, got.diameter_horiz_chord)
        self.assertEqual(0.0, got.diameter_vert_chord)
        self.assertEqual(0.0, got.diameter_horiz_mean)
        self.assertEqual(0.0, got.diameter_spheroid)

    def test_two_edges_center_out_leaves_horiz_chord_zero(self):
        got = dropsize(5, 5, 50, 8, 6, DS, DS, DIODENUM)
        self.assertEqual(0, got.center_in)
        self.assertGreater(got.diameter_circle_fit, 0)
        self.assertEqual(0.0, got.diameter_horiz_chord)

    def test_one_edge_center_out_leaves_horiz_chord_zero(self):
        got = dropsize(5, 5, 50, 8, 0, DS, DS, DIODENUM)
        self.assertEqual(0, got.center_in)
        self.assertGreater(got.diameter_circle_fit, 0)
        self.assertEqual(0.0, got.diameter_horiz_chord)

    def test_zero_edges_fills_everything(self):
        got = dropsize(20, 5, 50, 0, 0, DS, DS, DIODENUM)
        self.assertEqual(1, got.center_in)
        for field in ("axis_ratio", "diameter_circle_fit", "diameter_horiz_chord",
                      "diameter_vert_chord", "diameter_horiz_mean",
                      "diameter_spheroid"):
            self.assertGreater(getattr(got, field), 0, field)

    def test_axis_ratio_is_zero_whenever_an_edge_is_touched(self):
        for largest, smallest in ((8, 6), (8, 0), (60, 60)):
            with self.subTest(largest=largest, smallest=smallest):
                got = dropsize(20, 5, 50, largest, smallest, DS, DS, DIODENUM)
                self.assertEqual(0.0, got.axis_ratio)


class TestCircleFitIsGeometricallyCorrect(unittest.TestCase):
    """``dropsize.m:155-156`` against the closed-form circle through two chords.

    This is the one check in the module that is *independent* of both MATLAB and
    Octave: it asks whether the formula is right, not whether the port copied it
    faithfully.  Worth having, because the line carries the comment
    "+ is replaced by -, Will 10/17/2013" -- a sign fix, and a sign fix is
    exactly the kind of edit that is easy to get half-right.

    Derivation.  Put the two edge chords, of full lengths ``L`` and ``S``, at
    positions 0 and ``N`` across the array, and the circle's centre at ``c``::

        R^2 = (S/2)^2 + c^2 = (L/2)^2 + (N - c)^2
        =>  2 N c = N^2 + (L^2 - S^2) / 4
        =>  2 c   = N + (L^2 - S^2) / (4 N)          <- the MATLAB's ``temp``
        =>  2 R   = sqrt((2c)^2 + S^2)               <- the MATLAB's ``sqrt``

    So ``horizontal_size`` is the circle's diameter in diode units, and the
    formula is exact.  With ``+`` in place of the ``-`` it would not be.
    """

    @staticmethod
    def _diameter_through_two_chords(L, S, N):
        """The two-chord circle diameter, derived independently above."""
        c2 = N + (L * L - S * S) / (4 * N)
        return math.sqrt(c2 * c2 + S * S)

    def test_matches_a_circle_constructed_from_its_own_radius(self):
        """Round trip: build a circle, measure the chords it would cast at two
        rows ``N`` apart, feed them back in, recover the diameter."""
        for radius in (12.0, 40.0, 75.0):
            for offset in (0.0, 5.0, 15.0):
                N = 64.0
                # Chord half-lengths at distances `offset` and `N - offset`
                # from the centre, for a circle big enough to span both rows.
                d1, d2 = offset, N - offset
                if radius <= max(d1, d2):
                    continue
                S = 2 * math.sqrt(radius**2 - d1**2)
                L = 2 * math.sqrt(radius**2 - d2**2)
                with self.subTest(radius=radius, offset=offset):
                    self.assertAlmostEqual(
                        2 * radius,
                        self._diameter_through_two_chords(L, S, N),
                        places=9,
                    )

    def test_dropsize_uses_that_formula(self):
        """The port's two-edge branch reproduces the derived diameter."""
        L, S, N, ds = 30.0, 20.0, 128.0, DS
        got = dropsize(200, 5, 500, L, S, ds, ds, N)
        expected_chord = self._diameter_through_two_chords(L, S, N) * ds
        self.assertAlmostEqual(
            horizontal_chord_to_spherical_dia(expected_chord),
            got.diameter_circle_fit,
            places=12,
        )

    def test_equal_chords_give_the_symmetric_answer(self):
        """The simplest case, where the answer is checkable by inspection:
        equal chords put the centre midway, so the diameter is the hypotenuse of
        the array width and the chord."""
        N, S = 128.0, 20.0
        self.assertAlmostEqual(
            math.hypot(N, S),
            self._diameter_through_two_chords(S, S, N),
            places=12,
        )

    def test_chord_separation_is_taken_as_N_not_N_minus_1(self):
        """An observation rather than a defect, pinned so it stays visible.

        The two chords lie on diode 1 and diode ``N``, whose centres are
        ``N - 1`` pitches apart, but the formula uses ``N``.  Which is right
        depends on whether a diode is treated as a point or as a cell of unit
        width -- the array's outer extent really is ``N`` pitches.  The
        consequence is bounded and small: about 0.8% on a 128-diode array, and
        only for the two-edge branch.
        """
        N, S = 128.0, 20.0
        with_n = self._diameter_through_two_chords(S, S, N)
        with_n_minus_1 = self._diameter_through_two_chords(S, S, N - 1)
        self.assertLess(abs(with_n - with_n_minus_1) / with_n, 0.01)
        self.assertGreater(abs(with_n - with_n_minus_1) / with_n, 0.005)


class TestDeadElseif(unittest.TestCase):
    """``dropsize.m:143`` is unreachable from ``imgProc_sm.m:828-829``.

    The caller passes ``largest = max(top, bottom)``, ``smallest = min(...)``,
    so ``smallest > 0`` implies ``largest > 0`` and the ``elseif`` never runs.
    The function is public, so the behaviour is still pinned.
    """

    def test_caller_ordering_makes_it_unreachable(self):
        for top in range(0, 5):
            for bottom in range(0, 5):
                largest, smallest = max(top, bottom), min(top, bottom)
                with self.subTest(top=top, bottom=bottom):
                    self.assertFalse(smallest > 0 and not largest > 0)

    def test_behaviour_when_reached_directly(self):
        """largest == 0 forces ``center_in = 1`` for any positive length, so it
        lands in the one-edge centre-in branch."""
        got = dropsize(20, 5, 50, 0, 6, DS, DS, DIODENUM)
        self.assertEqual(1, got.center_in)
        self.assertGreater(got.diameter_horiz_chord, 0)


class TestLatentScalingDefects(unittest.TestCase):
    """Both call sites pass ``corrected_horizontal_diode_size == diode_size``
    (``imgProc_sm.m:826-827``, variant ``:409-410``), so neither of these fires
    in any real UIOOPS run.  They are pinned because the argument exists to be
    given a different value, and on that day the port must be wrong in the same
    way the MATLAB is.  Both values below are measured under Octave.
    """

    def test_correction_is_applied_twice(self):
        """``:131`` scales by ``corr / ds``; ``:177`` multiplies by ``corr``
        again, giving ``L * corr**2 / ds`` where ``L * corr`` was intended."""
        L, ds, corr = 3.0, 0.010, 0.020
        got = dropsize(L, 1.0, 10, 0, 0, ds, corr, DIODENUM)
        double_applied = L * corr * corr / ds
        intended = L * corr
        self.assertAlmostEqual(
            horizontal_chord_to_spherical_dia(double_applied),
            got.diameter_horiz_chord, places=12,
        )
        self.assertNotAlmostEqual(
            horizontal_chord_to_spherical_dia(intended),
            got.diameter_horiz_chord, places=6,
        )

    def test_center_in_compares_scaled_length_with_unscaled_edge(self):
        """``:150`` tests the scaled ``max_horizontal_length`` against the raw
        ``largest_edge_touching``.  Identical geometry, different verdict."""
        self.assertEqual(0, dropsize(10, 1.0, 50, 12, 0, 0.010, 0.010, DIODENUM).center_in)
        self.assertEqual(1, dropsize(10, 1.0, 50, 12, 0, 0.010, 0.020, DIODENUM).center_in)
        self.assertEqual(0, dropsize(10, 1.0, 50, 12, 0, 0.010, 0.005, DIODENUM).center_in)

    def test_no_effect_when_the_sizes_agree(self):
        """The masking condition itself, so that a change to the call site that
        broke it would fail here."""
        for ds in (0.010, 0.025, 0.150):
            with self.subTest(ds=ds):
                got = dropsize(20, 5, 50, 0, 0, ds, ds, DIODENUM)
                expected = horizontal_chord_to_spherical_dia(20 * ds)
                self.assertAlmostEqual(expected, got.diameter_horiz_chord, places=12)


class TestDocumentedButAbsentDiodeAddition(unittest.TestCase):
    """``dropsize.m:10,15`` document "one diode added to
    max_horizontal_length for missing first slice", but ``:56`` sets
    ``diodes_added_to_length = 0``, so no branch adds it."""

    def test_length_addition_is_zero(self):
        self.assertEqual(0.0, DIODES_ADDED_TO_LENGTH)

    def test_height_addition_is_one_but_used_as_a_half(self):
        self.assertEqual(1.0, DIODES_ADDED_TO_HEIGHT)

    def test_chord_equals_length_times_diode_size_exactly(self):
        """If the documented +1 were applied, this would be off by one diode."""
        got = dropsize(20, 5, 50, 0, 0, DS, DS, DIODENUM)
        self.assertAlmostEqual(
            horizontal_chord_to_spherical_dia(20 * DS),
            got.diameter_horiz_chord, places=12,
        )

    def test_vertical_chord_uses_the_length_addition_not_the_height_one(self):
        """``:180`` reads ``diodes_added_to_length``, not ``_to_height``."""
        got = dropsize(20, 5, 50, 0, 0, DS, DS, DIODENUM)
        self.assertAlmostEqual(
            vertical_chord_to_spherical_dia(5 * DS),
            got.diameter_vert_chord, places=12,
        )


class TestDegenerateGeometry(unittest.TestCase):
    def test_zero_lengths_give_nan_axis_ratio(self):
        """0/0 is NaN in MATLAB, not an exception."""
        got = dropsize(0, 0, 5, 0, 0, DS, DS, DIODENUM)
        self.assertTrue(math.isnan(got.axis_ratio))

    def test_zero_lengths_give_zero_spheroid_not_an_exception(self):
        """``exp(log(0)/3)`` is 0 in MATLAB; Python's ``math.log`` would raise."""
        self.assertEqual(0.0, dropsize(0, 0, 5, 0, 0, DS, DS, DIODENUM).diameter_spheroid)

    def test_one_edge_center_out_survives_zero_height(self):
        """``:172`` adds 0.5 before ``:173`` divides, so the denominator cannot
        be zero for a non-negative height."""
        self.assertGreater(dropsize(5, 0, 50, 8, 0, DS, DS, DIODENUM).diameter_circle_fit, 0)


class TestReturnShape(unittest.TestCase):
    def test_unpacks_in_matlab_order(self):
        got = dropsize(20, 5, 50, 0, 0, DS, DS, DIODENUM)
        center_in, axis_ratio, cf, hc, vc, hm, sp = got
        self.assertEqual(got.center_in, center_in)
        self.assertEqual(got.axis_ratio, axis_ratio)
        self.assertEqual(got.diameter_spheroid, sp)
        self.assertEqual((cf, hc, vc, hm),
                         (got.diameter_circle_fit, got.diameter_horiz_chord,
                          got.diameter_vert_chord, got.diameter_horiz_mean))

    def test_is_immutable(self):
        got = dropsize(20, 5, 50, 0, 0, DS, DS, DIODENUM)
        with self.assertRaises(FrozenInstanceError):
            got.axis_ratio = 2.0

    def test_center_in_is_an_int_not_a_float(self):
        """``imgProc_sm`` writes it to a netCDF ``'short'``; keeping it an int
        here means the S3 writer cannot be handed a 1.0 that rounds oddly."""
        self.assertIsInstance(dropsize(20, 5, 50, 0, 0, DS, DS, DIODENUM).center_in, int)
        self.assertIsInstance(DropSize(0, 1.0, 0, 0, 0, 0, 0).center_in, int)


if __name__ == "__main__":
    unittest.main()
