# SPDX-License-Identifier: BSD-3-Clause
"""Tests for spot_edge_fix.py."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements.spot_edge_fix import (
    EDGE_0,
    SPOT_EDGE,
    SPOT_EDGE_FIXED,
    Z_D,
    _find_last,
    correct_part_z_size_factor,
)

# NOTE 2026-08-28: the ".stockreject" proc, deliberately. This enhancement corrects
# hollow-block OUTPUTS (part_z / edge_at_max_hole / max_hole_diameter). The production
# reject config (reject.py, ORACLES_PRODUCTION_REJECT_CONFIG) sets rej_hollow=0, which
# skips that block entirely, so a proc built under it carries only constant fall-through
# values and this test's "some differing particles" premise cannot hold on it -- the
# enhancement is INERT under that config (BACKLOG_STATUS.md). The stock-reject proc is
# kept on disk as evidence of the pre-fix state and is the input this test was written for.
_REAL_PROC = Path(__file__).resolve().parent.parent.parent / "_decoded"


class TableTests(unittest.TestCase):
    def test_only_index_146_differs_from_the_original_table(self):
        diff = np.flatnonzero(SPOT_EDGE_FIXED != SPOT_EDGE)
        self.assertEqual(list(diff), [146])
        self.assertEqual(SPOT_EDGE[146], 757.0)
        self.assertEqual(SPOT_EDGE_FIXED[146], 0.757)

    def test_original_table_is_untouched(self):
        # Guards against the fixed table being a view that mutated the
        # port's own SPOT_EDGE rather than a copy.
        self.assertEqual(SPOT_EDGE[146], 757.0)


class CorrectionMechanicsTests(unittest.TestCase):
    def test_particle_not_in_korolev_branch_passes_through_unchanged(self):
        # stored_part_z == 0 (never reached the branch) and == -1 (a
        # different early-out) must both be left alone.
        max_hole = np.array([5.0, 5.0])
        edge = np.array([10.0, 10.0])
        part_z = np.array([0.0, -1.0])
        corrected_z, corrected_f = correct_part_z_size_factor(max_hole, edge, part_z)
        np.testing.assert_array_equal(corrected_z, part_z)
        self.assertTrue(np.all(np.isnan(corrected_f)))

    def test_reproduces_the_original_buggy_result_when_ratio_is_outside_the_vulnerable_band(self):
        # A ratio nowhere near 0.757-0.763 must give the identical part_z
        # under both tables -- the fix should be a no-op almost everywhere.
        # raw columns are swapped (C5), so pass true values through the swap
        # to build a realistic raw fixture: raw_max_hole holds true_edge.
        true_max_hole, true_edge = 3.0, 10.0  # ratio = 0.3, far from the band
        raw_max_hole = np.array([true_edge])
        raw_edge = np.array([true_max_hole])
        ratio = true_max_hole / true_edge
        original_part_z = np.array([float(Z_D[_find_last(SPOT_EDGE < ratio)])])

        corrected_z, corrected_f = correct_part_z_size_factor(raw_max_hole, raw_edge, original_part_z)
        self.assertEqual(float(corrected_z[0]), float(original_part_z[0]))

    def test_vulnerable_ratio_gets_one_grid_step_higher_part_z(self):
        # Construct a ratio that lands in (0.757, 0.763] -- the exact band
        # the typo makes the buggy table skip.
        ratio = 0.760
        true_max_hole, true_edge = ratio * 100.0, 100.0
        raw_max_hole, raw_edge = true_edge, true_max_hole  # C5-swapped on disk

        buggy_part_z = float(Z_D[_find_last(SPOT_EDGE < ratio)])
        fixed_part_z = float(Z_D[_find_last(SPOT_EDGE_FIXED < ratio)])
        self.assertAlmostEqual(fixed_part_z - buggy_part_z, 0.05, places=9)

        corrected_z, corrected_f = correct_part_z_size_factor(
            np.array([raw_max_hole]), np.array([raw_edge]), np.array([buggy_part_z]),
        )
        self.assertAlmostEqual(float(corrected_z[0]), fixed_part_z, places=9)
        expected_factor = float(EDGE_0[_find_last(Z_D <= fixed_part_z)])
        self.assertAlmostEqual(float(corrected_f[0]), expected_factor, places=9)


class V35TableParity(unittest.TestCase):
    """S4 plan step 3: ``spot_edge_fix`` needs no code change for v3.5 -- it is
    table-only, and the table it corrects is the SAME table under both engines
    (``arrayprobe_uiops/reject.py:404-442``, a second literal copy of the v3.1.4
    values per that module's own docstring, not a re-export). The whole v3.5
    proof for a table-only module is that the two copies still agree."""

    def test_the_three_tables_are_the_same_on_both_engines(self):
        from arrayprobe_uiops.reject import _EDGE_0, _SPOT_EDGE, _Z_D

        np.testing.assert_array_equal(np.asarray(_SPOT_EDGE), SPOT_EDGE)
        np.testing.assert_array_equal(np.asarray(_EDGE_0), EDGE_0)
        # Z_D is bit-identical, measured 2026-10-13 (np.array_equal True, max
        # |difference| 0.0 over 164 entries): arrayprobe.reject builds it as
        # `np.arange(164) * 0.05` and arrayprobe_uiops/reject.py:448 as
        # `[i * 0.05 for i in range(164)]`, both i * 0.05 in float64, as
        # MATLAB's colon `0:.05:8.15` is (Octave-measured, reject.py:444-447).
        # Index 3 is 0.15000000000000002 in both. The earlier v3.5
        # `round(i * 0.05, 10)` construction, which differed, is gone.
        np.testing.assert_array_equal(np.asarray(_Z_D), Z_D)

    def test_spot_edge_147_is_757_on_v35_too(self):
        from arrayprobe_uiops.reject import _SPOT_EDGE

        self.assertEqual(_SPOT_EDGE[146], 757)


@unittest.skipUnless(
    (_REAL_PROC / "proc.base160906064403.H.stockreject.nc").exists(),
    f"real decoded flight not present: {_REAL_PROC}",
)
class RealDataTests(unittest.TestCase):
    """The design doc's actual validation: recomputing through the UNFIXED
    table (starting from raw, C5-swapped columns) must reproduce every
    stored part_z exactly -- proof the ratio-recovery mechanism is right,
    independent of whether the A3 fix itself changes anything. Then check
    what the missing decimal in spot_edge fix actually changes on real data (nothing, on the six
    flights validated so far -- see the design doc)."""

    def test_mechanism_reproduces_stored_part_z_via_unfixed_table(self):
        import netCDF4

        with netCDF4.Dataset(_REAL_PROC / "proc.base160906064403.H.stockreject.nc") as ds:
            raw_max_hole = ds.variables["max_hole_diameter"][:]
            raw_edge = ds.variables["edge_at_max_hole"][:]
            stored_part_z = ds.variables["part_z"][:]

        idx = np.flatnonzero(stored_part_z > 0)
        self.assertGreater(len(idx), 0, "fixture flight should have Korolev-branch particles")

        from arrayprobe_enhancements.hole_edge_swap import correct_hole_edge_swap

        true_max_hole, true_edge = correct_hole_edge_swap(raw_max_hole, raw_edge)
        ratio = np.where(true_edge[idx] <= 0, 0.0, true_max_hole[idx] / true_edge[idx])
        reproduced = np.array([float(Z_D[_find_last(SPOT_EDGE < r)]) for r in ratio])
        np.testing.assert_allclose(reproduced, stored_part_z[idx])

    def test_no_particles_affected_on_the_validated_campaign(self):
        import netCDF4

        with netCDF4.Dataset(_REAL_PROC / "proc.base160906064403.H.stockreject.nc") as ds:
            raw_max_hole = ds.variables["max_hole_diameter"][:]
            raw_edge = ds.variables["edge_at_max_hole"][:]
            stored_part_z = ds.variables["part_z"][:]

        corrected_z, _ = correct_part_z_size_factor(raw_max_hole, raw_edge, stored_part_z)
        np.testing.assert_allclose(corrected_z, stored_part_z)


if __name__ == "__main__":
    unittest.main()
