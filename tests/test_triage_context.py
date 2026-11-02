# SPDX-License-Identifier: BSD-3-Clause
"""Tests for arrayprobe.triage_context: what the triage pages add beside a particle."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe.triage_context import (
    REJECT_OUTCOMES,
    MetFolder,
    particle_parts,
    piece_groups,
    reject_outcome,
    shape_test_habit,
)
from arrayprobe_uiops.sizedist_core import GOOD_REJECT_CODES


class RejectOutcomes(unittest.TestCase):
    def test_the_kept_codes_are_exactly_sizedists(self):
        # sizeDist.m:1460 (v3.5) / :1209 (v3.1.4): the same five letters.
        self.assertEqual(set(REJECT_OUTCOMES), set(GOOD_REJECT_CODES))

    def test_only_H_is_corrected(self):
        corrected = {c for c, (kind, _) in REJECT_OUTCOMES.items() if kind == "corrected"}
        self.assertEqual(corrected, {"H"})

    def test_every_other_code_is_rejected(self):
        for code in "apszAiDIStf":
            self.assertEqual(reject_outcome(code)[0], "rejected", code)

    def test_no_code_gives_none(self):
        self.assertIsNone(reject_outcome(None))
        self.assertIsNone(reject_outcome(""))


class ShapeTest(unittest.TestCase):
    def test_fewer_than_25_pixels_is_tiny(self):
        c = np.zeros((10, 128), dtype=bool)
        c[3:6, 40:44] = True                       # 12 pixels
        self.assertEqual(shape_test_habit(c, 0.01), "t")

    def test_an_empty_image_is_zero_image(self):
        self.assertEqual(shape_test_habit(np.zeros((4, 128), dtype=bool), 0.01), "M")

    def test_a_filled_disc_is_not_tiny(self):
        yy, xx = np.mgrid[0:30, 0:128]
        c = (yy - 15) ** 2 + (xx - 60) ** 2 <= 100   # radius 10 px, ~314 pixels
        self.assertNotIn(shape_test_habit(c, 0.01), ("t", "M"))


class Parts(unittest.TestCase):
    def test_pieces_are_numbered_along_the_flight(self):
        c = np.zeros((20, 40), dtype=bool)
        c[12:15, 2:5] = True       # met second (later slices)
        c[1:4, 30:33] = True       # met first
        parts = particle_parts(c)
        self.assertEqual([p["n"] for p in parts], [1, 2])
        self.assertEqual(parts[0]["rows"], (1, 3))
        self.assertEqual(parts[1]["rows"], (12, 14))
        self.assertEqual([p["pixels"] for p in parts], [9, 9])

    def test_diagonal_neighbours_are_one_piece(self):
        c = np.zeros((4, 4), dtype=bool)
        c[0, 0] = c[1, 1] = c[2, 2] = True
        self.assertEqual(len(particle_parts(c)), 1)

    def test_empty_image_has_no_pieces(self):
        self.assertEqual(particle_parts(np.zeros((3, 3), dtype=bool)), [])

    def _two_blobs(self, gap):
        c = np.zeros((10, 30), dtype=bool)
        c[3:6, 2:5] = True
        c[3:6, 5 + gap:8 + gap] = True     # ``gap`` empty diodes between them
        return c

    def test_blobs_one_diode_apart_merge_from_gap_1(self):
        c = self._two_blobs(1)
        self.assertEqual(len(particle_parts(c, gap=0)), 2)
        for g in (1, 2, 7):
            parts = particle_parts(c, gap=g)
            self.assertEqual(len(parts), 1, g)
            self.assertEqual((parts[0]["pixels"], parts[0]["cols"]), (18, (2, 8)))

    def test_blobs_ten_diodes_apart_stay_separate(self):
        c = self._two_blobs(10)
        for g in range(0, 10):
            self.assertEqual(len(particle_parts(c, gap=g)), 2, g)
        self.assertEqual(len(particle_parts(c, gap=10)), 1)

    def test_gap_is_chebyshev_diagonal_too(self):
        c = np.zeros((12, 12), dtype=bool)
        c[0, 0] = c[4, 4] = True           # Chebyshev distance 4, three empty diodes between
        self.assertEqual(len(particle_parts(c, gap=2)), 2)
        self.assertEqual(len(particle_parts(c, gap=3)), 1)

    def test_default_gap_is_the_measured_one(self):
        from arrayprobe.triage_context import PIECE_GAP_DIODES
        self.assertEqual(PIECE_GAP_DIODES, 8)
        self.assertEqual(len(particle_parts(self._two_blobs(8))), 1)
        self.assertEqual(len(particle_parts(self._two_blobs(9))), 2)


class SizeScaledGap(unittest.TestCase):
    """``scale="larger"`` joins two pieces only when their gap is at most
    ``min(cap, extent of the larger)``; the constant default is unchanged."""

    def test_two_small_pieces_far_apart_join_only_under_constant(self):
        c = np.zeros((10, 30), dtype=bool)
        c[4:6, 2:4] = True                  # extent 2
        c[4:6, 9:11] = True                 # extent 2, five empty diodes between
        self.assertEqual(len(particle_parts(c, gap=8)), 1)
        self.assertEqual(len(particle_parts(c, gap=8, scale="larger")), 2)
        self.assertEqual(len(particle_parts(c, gap=12, scale="larger")), 2)

    def test_fragment_near_a_big_body_joins_under_both(self):
        c = np.zeros((30, 40), dtype=bool)
        c[5:25, 2:22] = True                # extent 20
        c[14, 27] = True                    # one-pixel fragment, five empty diodes away
        self.assertEqual(len(particle_parts(c, gap=8)), 1)
        self.assertEqual(len(particle_parts(c, gap=12, scale="larger")), 1)
        # The cap still binds: a gap above it never joins, however large the body.
        self.assertEqual(len(particle_parts(c, gap=4, scale="larger")), 2)

    def test_threshold_is_the_larger_extent_inclusive(self):
        c = np.zeros((10, 30), dtype=bool)
        c[3:6, 2:5] = True                  # extent 3
        c[4, 8] = True                      # extent 1, three empty diodes away
        self.assertEqual(len(piece_groups(c, 12, "larger")), 1)
        c[4, 8] = False
        c[4, 9] = True                      # four empty diodes: above extent 3
        self.assertEqual(len(piece_groups(c, 12, "larger")), 2)

    def test_single_linkage_chains(self):
        c = np.zeros((10, 40), dtype=bool)
        c[3:6, 2:5] = True
        c[3:6, 7:10] = True                 # 2 empty from the first
        c[3:6, 12:15] = True                # 2 empty from the second, 7 from the first
        self.assertEqual(len(piece_groups(c, 12, "larger")), 1)

    def test_constant_default_is_unchanged(self):
        rng = np.random.default_rng(688)
        for _ in range(20):
            c = rng.random((25, 25)) < 0.08
            for g in (0, 3, 8):
                a = piece_groups(c, g)
                b = piece_groups(c, g, "constant")
                self.assertEqual(len(a), len(b))
                for x, y in zip(a, b, strict=True):
                    self.assertTrue(np.array_equal(x, y))

    def test_unknown_scale_is_refused(self):
        with self.assertRaises(ValueError):
            piece_groups(np.ones((2, 2), dtype=bool), 8, "smaller")

    def test_masks_partition_the_image(self):
        rng = np.random.default_rng(1002)
        c = rng.random((30, 30)) < 0.1
        groups = piece_groups(c, 12, "larger")
        total = np.zeros_like(c, dtype=int)
        for m in groups:
            total += m
        self.assertTrue(np.array_equal(total, c.astype(int)))


def _write_merged(folder: Path, name: str, units: str, seconds, temps):
    import netCDF4

    with netCDF4.Dataset(folder / name, "w") as ds:
        ds.createDimension("time", len(seconds))
        t = ds.createVariable("time", "f8", ("time",))
        t.units = units
        t[:] = seconds
        v = ds.createVariable("ambient_temp", "f4", ("time",))
        v.units = "degC"
        v[:] = temps


class Temperature(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_row_at_the_records_second(self):
        _write_merged(self.dir, "enaaafmergedF1.c1.20180215.125953.nc",
                      "seconds since 2018-02-15 00:00:00 0:00",
                      [51741.0, 51742.0], [-12.5, -12.75])
        met = MetFolder(self.dir)
        self.assertEqual(len(met), 1)
        t, name = met.temperature_at(20180215, 142222)   # 14:22:22 = 51742 s
        self.assertAlmostEqual(t, -12.75, places=5)
        self.assertEqual(name, "enaaafmergedF1.c1.20180215.125953.nc")

    def test_missing_second_date_or_value_gives_none(self):
        _write_merged(self.dir, "enaaafmergedF1.c1.20180215.125953.nc",
                      "seconds since 2018-02-15 00:00:00 0:00", [51741.0, 51742.0],
                      [-9999.0, -12.0])
        met = MetFolder(self.dir)
        self.assertIsNone(met.temperature_at(20180215, 142221))   # -9999 is missing
        self.assertIsNone(met.temperature_at(20180215, 142223))   # no row
        self.assertIsNone(met.temperature_at(20180216, 142222))   # no file of that date

    def test_a_time_axis_on_another_date_is_refused(self):
        _write_merged(self.dir, "enaaafmergedF1.c1.20180215.125953.nc",
                      "seconds since 1970-01-01 00:00:00", [51742.0], [-12.0])
        self.assertIsNone(MetFolder(self.dir).temperature_at(20180215, 142222))


if __name__ == "__main__":
    unittest.main()
