# SPDX-License-Identifier: BSD-3-Clause
"""Tests for hole_edge_swap.py (the upstream swapped hole variables)."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements.hole_edge_swap import correct_hole_edge_swap

#: The real decoded flight this finding was originally measured and
#: reconfirmed against. Not tracked (gitignored decoded output) -- present
#: only on a machine that has actually run the pipeline, so this test skips
#: gracefully rather than failing a fresh clone or CI.
# NOTE 2026-08-28: the ".stockreject" proc, deliberately. This enhancement corrects
# hollow-block OUTPUTS (part_z / edge_at_max_hole / max_hole_diameter). The production
# reject config (reject.py, ORACLES_PRODUCTION_REJECT_CONFIG) sets rej_hollow=0, which
# skips that block entirely, so a proc built under it carries only constant fall-through
# values and this test's "some differing particles" premise cannot hold on it -- the
# enhancement is INERT under that config (BACKLOG_STATUS.md). The stock-reject proc is
# kept on disk as evidence of the pre-fix state and is the input this test was written for.
_REAL_PROC = Path(__file__).resolve().parent.parent.parent / "_decoded" / "proc.base160906064403.H.stockreject.nc"


class SwapMechanicsTests(unittest.TestCase):
    def test_arrays_are_exchanged(self):
        max_hole = np.array([1.0, 2.0, 3.0])
        edge = np.array([10.0, 20.0, 30.0])
        new_max_hole, new_edge = correct_hole_edge_swap(max_hole, edge)
        np.testing.assert_array_equal(new_max_hole, edge)
        np.testing.assert_array_equal(new_edge, max_hole)

    def test_scalars_accepted(self):
        new_max_hole, new_edge = correct_hole_edge_swap(5.0, 12.0)
        self.assertEqual(float(new_max_hole), 12.0)
        self.assertEqual(float(new_edge), 5.0)

    def test_inputs_are_not_mutated(self):
        max_hole = np.array([1.0, 2.0])
        edge = np.array([10.0, 20.0])
        correct_hole_edge_swap(max_hole, edge)
        np.testing.assert_array_equal(max_hole, [1.0, 2.0])
        np.testing.assert_array_equal(edge, [10.0, 20.0])

    def test_double_swap_is_identity(self):
        max_hole = np.array([1.0, 2.0, 3.0])
        edge = np.array([10.0, 20.0, 5.0])
        once_max, once_edge = correct_hole_edge_swap(max_hole, edge)
        twice_max, twice_edge = correct_hole_edge_swap(once_max, once_edge)
        np.testing.assert_array_equal(twice_max, max_hole)
        np.testing.assert_array_equal(twice_edge, edge)


@unittest.skipUnless(_REAL_PROC.exists(), f"real decoded flight not present: {_REAL_PROC}")
class RealDataInvariantTests(unittest.TestCase):
    """The actual validation strategy from the design doc: no MATLAB oracle
    exists for "corrected" output, so the check is the physical invariant
    itself -- a hole cannot be wider than the particle containing it."""

    def test_invariant_restored_on_real_flight(self):
        import netCDF4

        with netCDF4.Dataset(_REAL_PROC) as ds:
            raw_max_hole = ds.variables["max_hole_diameter"][:]
            raw_edge = ds.variables["edge_at_max_hole"][:]

        differ = raw_max_hole != raw_edge
        self.assertGreater(int(differ.sum()), 0, "fixture should have some differing particles")

        # Before correction: the swap means the invariant runs backwards on
        # every differing particle (this is the finding itself, reconfirmed).
        self.assertTrue(bool((raw_max_hole[differ] > raw_edge[differ]).all()))

        corrected_max_hole, corrected_edge = correct_hole_edge_swap(raw_max_hole, raw_edge)
        self.assertTrue(
            bool((corrected_max_hole[differ] <= corrected_edge[differ]).all()),
            "max_hole_diameter must never exceed edge_at_max_hole after correction",
        )


if __name__ == "__main__":
    unittest.main()
