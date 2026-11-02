# SPDX-License-Identifier: BSD-3-Clause
"""The 2D-S/HVPS crossover diagnostic.

Three kinds of evidence, kept apart:

* **Statistics** -- synthetic probe pairs whose true concentrations are known, so
  the flag is checked against the answer: equal concentrations flag at the chance
  rate the result itself predicts (seeded Poisson draws), a real excess is flagged
  in the right direction.
* **Reading both engines' output** -- the tracked v3.1.4 and v3.5 ``sd`` files,
  with the diagnostic's per-bin concentration checked against ``netCDF4`` reading
  the same variables by dimension name (a different route from ``ncio``'s), and a
  combined product built by :func:`arrayprobe.combine.combine_sizedist` from a
  tracked ``sd`` file read back to the same numbers.
* **What is not measured here** -- no tracked fixture holds a 2D-S and an HVPS
  file for one interval, so the real-data consequence rests on the gitignored
  2016-09-06 pair, recorded in ``enhancements_uiops/README.md`` and skipped here when
  that data is absent.
"""

from __future__ import annotations

import math
import os
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements import probe_crossover as pc

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tests" / "data"
SD_V314 = DATA / "s4_sizedist_octave_golden.nc"
SD_V35 = DATA / "v35_sizedist" / "main.nc"
#: The same default and override as tests/test_reference_data.py.
REFDIR = Path(os.environ.get("ARRAYPROBE_REFERENCE_DATA",
                             ROOT / "arrayprobe-local-data" / "old-stuff-data"))
HELD = REFDIR / "old_oracles_data"
HELD_2DS = HELD / "2DS_H_current" / "base160906064017.combined.H.2DS_2.cdf"
HELD_HVPS = HELD / "HVPS" / "base160906064017.combined.V.HVPS_2.cdf"


def _probe(edges, conc, count, time=None, kind="hhmmss"):
    edges = np.asarray(edges, dtype=np.float64)
    conc = np.atleast_2d(np.asarray(conc, dtype=np.float64))
    count = np.atleast_2d(np.asarray(count, dtype=np.float64))
    if time is None:
        time = 120000 + np.arange(conc.shape[0])
    return pc.ProbeSizeDistribution(time=np.asarray(time, dtype=np.float64), time_kind=kind,
                                    bin_min=edges[:-1], bin_max=edges[1:],
                                    conc=conc, count=count, source_format="sd")


# ORACLES' own ladders (measured on the 2016-09-06 products): the 2D-S at 10 um
# from 0.005 mm, the HVPS at 150 um from 0.075 mm.
EDGES_2DS = 0.005 + 0.01 * np.arange(129)
EDGES_HVPS = 0.075 + 0.15 * np.arange(71)


class Weights(unittest.TestCase):
    def test_aligned_edges_give_exact_zero_or_one(self):
        w = pc.overlap_weights(EDGES_HVPS[:-1], EDGES_HVPS[1:], 0.525, 1.275)
        self.assertTrue(set(np.unique(w)) <= {0.0, 1.0})
        self.assertEqual(int(w.sum()), 5)

    def test_a_cut_bin_gets_its_fraction(self):
        w = pc.overlap_weights([0.0, 1.0], [1.0, 2.0], 0.5, 1.25)
        np.testing.assert_allclose(w, [0.5, 0.25])

    def test_the_oracles_ladders_share_every_hvps_edge_up_to_1_275_mm(self):
        a = _probe(EDGES_2DS, np.zeros((1, 128)), np.zeros((1, 128)))
        b = _probe(EDGES_HVPS, np.zeros((1, 70)), np.zeros((1, 70)))
        np.testing.assert_allclose(pc.common_edges(a, b), 0.075 + 0.15 * np.arange(9))
        lo, hi = pc.default_size_range(a, b)
        self.assertAlmostEqual(lo, 0.075)
        self.assertAlmostEqual(hi, 1.275)

    def test_no_shared_edge_falls_back_to_the_raw_overlap(self):
        a = _probe([0.005, 0.5, 1.285], [[0, 0]], [[0, 0]])
        b = _probe([0.2, 0.7, 30.0], [[0, 0]], [[0, 0]])
        self.assertEqual(pc.default_size_range(a, b), (0.2, 1.285))

    def test_disjoint_ladders_are_refused(self):
        a = _probe([0.0, 1.0], [[1]], [[1]])
        b = _probe([2.0, 3.0], [[1]], [[1]])
        with self.assertRaises(ValueError):
            pc.default_size_range(a, b)


class Statistics(unittest.TestCase):
    def test_integrated_count_is_the_plain_sum_when_bins_share_a_sample_volume(self):
        count = np.array([[40.0, 60.0, 900.0]])
        conc = count / 50.0                         # one sample volume, 50 cm3
        n, var = pc.integrate_range(conc, count, np.array([1.0, 1.0, 0.0]))
        self.assertAlmostEqual(n[0], 2.0)
        self.assertAlmostEqual(pc.effective_count(n, var)[0], 100.0)

    def test_equal_concentrations_agree_with_z_zero(self):
        ratio, z, status = pc.compare([2.0], [400.0], [2.0], [25.0])
        self.assertEqual(status[0], "agree")
        self.assertEqual(z[0], 0.0)
        self.assertEqual(ratio[0], 1.0)

    def test_z_is_the_log_ratio_over_its_delta_method_error(self):
        _, z, status = pc.compare([3.0], [100.0], [1.0], [100.0])
        self.assertAlmostEqual(z[0], math.log(3.0) / math.sqrt(0.02))
        self.assertEqual(status[0], "a_higher")
        _, z, status = pc.compare([1.0], [100.0], [3.0], [100.0])
        self.assertEqual(status[0], "b_higher")

    def test_too_few_particles_is_insufficient_not_agreement(self):
        _, z, status = pc.compare([1.0, 1.0], [9.0, 500.0], [5.0, 5.0], [500.0, 0.0])
        self.assertEqual(list(status), ["insufficient", "insufficient"])
        self.assertTrue(np.isnan(z).all())

    def test_nan_is_missing(self):
        _, _, status = pc.compare([np.nan], [100.0], [1.0], [100.0])
        self.assertEqual(status[0], "missing")

    def test_equal_true_concentrations_flag_at_the_predicted_chance_rate(self):
        """Seeded Poisson draws from ONE concentration seen through two sample
        volumes: the flag count must sit near ``expected_false_flags``."""
        rng = np.random.default_rng(20260914)
        n_sec, true_conc, v_a, v_b = 40000, 2.0, 60.0, 400.0
        c_a = rng.poisson(true_conc * v_a, size=(n_sec, 1)).astype(float)
        c_b = rng.poisson(true_conc * v_b, size=(n_sec, 1)).astype(float)
        a = _probe([0.5, 1.0], c_a / v_a, c_a, time=np.arange(n_sec), kind="datenum_seconds")
        b = _probe([0.5, 1.0], c_b / v_b, c_b, time=np.arange(n_sec), kind="datenum_seconds")
        r = pc.crossover_diagnostic(a, b)
        self.assertEqual(r.n_tested, n_sec)
        expected = r.expected_false_flags             # 40000 * 0.0027 = 108
        self.assertAlmostEqual(expected, n_sec * math.erfc(3 / math.sqrt(2)))
        self.assertLess(abs(r.n_flagged - expected), 5 * math.sqrt(expected))

    def test_a_real_hvps_excess_is_flagged_as_b_higher(self):
        rng = np.random.default_rng(7)
        n_sec = 500
        c_a = rng.poisson(2.0 * 60.0, size=(n_sec, 1)).astype(float)
        c_b = rng.poisson(3.0 * 400.0, size=(n_sec, 1)).astype(float)   # 1.5x excess
        a = _probe([0.5, 1.0], c_a / 60.0, c_a, time=np.arange(n_sec), kind="datenum_seconds")
        b = _probe([0.5, 1.0], c_b / 400.0, c_b, time=np.arange(n_sec), kind="datenum_seconds")
        r = pc.crossover_diagnostic(a, b)
        self.assertGreater(r.counts_by_status()["b_higher"], 0.5 * n_sec)
        self.assertEqual(r.counts_by_status()["a_higher"], 0)
        self.assertAlmostEqual(r.median_ratio, 2.0 / 3.0, delta=0.05)


class Alignment(unittest.TestCase):
    def test_only_shared_seconds_are_compared(self):
        a = _probe([0.5, 1.0], [[1.0]] * 3, [[100.0]] * 3, time=[120000, 120001, 120002])
        b = _probe([0.5, 1.0], [[1.0]] * 2, [[100.0]] * 2, time=[120001, 120005])
        r = pc.crossover_diagnostic(a, b)
        np.testing.assert_array_equal(r.time, [120001])

    def test_mixing_an_sd_file_with_a_combined_product_is_refused(self):
        a = _probe([0.5, 1.0], [[1.0]], [[100.0]], kind="hhmmss")
        b = _probe([0.5, 1.0], [[1.0]], [[100.0]], kind="datenum_seconds")
        with self.assertRaises(ValueError):
            pc.crossover_diagnostic(a, b)

    def test_hhmmss_blocks_count_real_seconds_across_a_minute(self):
        self.assertEqual(pc._seconds(np.array([60659.0]), "hhmmss")[0], 6 * 3600 + 6 * 60 + 59)
        self.assertEqual(pc._seconds(np.array([60700.0]), "hhmmss")[0], 6 * 3600 + 7 * 60)

    def test_a_window_pools_seconds_too_sparse_to_test_alone(self):
        times = [120058, 120059, 120100, 120101]          # four real seconds
        a = _probe([0.5, 1.0], [[0.1]] * 4, [[6.0]] * 4, time=times)
        b = _probe([0.5, 1.0], [[0.1]] * 4, [[6.0]] * 4, time=times)
        self.assertEqual(pc.crossover_diagnostic(a, b).counts_by_status()["insufficient"], 4)
        r = pc.crossover_diagnostic(a, b, window_s=4)
        self.assertEqual(list(r.status), ["agree"])
        self.assertAlmostEqual(r.k_a[0], 24.0)
        self.assertAlmostEqual(r.n_a[0], 0.1)

    def test_a_missing_second_inside_a_window_is_dropped_from_both_probes(self):
        times = [0, 1, 2, 3]
        a = _probe([0.5, 1.0], [[1.0], [np.nan], [1.0], [1.0]], [[50.0]] * 4, time=times,
                   kind="datenum_seconds")
        b = _probe([0.5, 1.0], [[9.0], [1.0], [1.0], [1.0]], [[50.0]] * 4, time=times,
                   kind="datenum_seconds")
        r = pc.crossover_diagnostic(a, b, window_s=2)
        self.assertAlmostEqual(r.n_b[0], 9.0)     # second 1 dropped from b as well
        self.assertAlmostEqual(r.k_b[0], 50.0)


def _read_by_dimension(path, name):
    """Side B: netCDF4 directly, oriented by the dimension NAMES, not by ncio."""
    with netCDF4.Dataset(str(path)) as ds:
        ds.set_auto_mask(False)
        v = ds.variables[name]
        arr = np.asarray(v[:], dtype=np.float64)
        time_axis = [d.lower() for d in v.dimensions].index("time")
        return np.moveaxis(arr, time_axis, 0)


@unittest.skipUnless(SD_V314.is_file() and SD_V35.is_file(),
                     "The two sizeDist outputs is not distributed with the package; this test "
                     "runs in the development repository")
class ReadsBothEngines(unittest.TestCase):
    def test_v314_and_v35_sd_files_give_the_written_concentration_per_bin(self):
        for path in (SD_V314, SD_V35):
            with self.subTest(path=path.name):
                p = pc.read_probe(path)
                with netCDF4.Dataset(str(path)) as ds:
                    dD = np.asarray(ds.variables["bin_dD"][:], dtype=np.float64)
                np.testing.assert_array_equal(
                    p.conc, _read_by_dimension(path, "conc_minR") / 10.0 * dD[None, :])
                np.testing.assert_array_equal(p.count, _read_by_dimension(path, "count"))
                self.assertEqual(p.conc.shape, (p.time.size, p.bin_min.size))

    def test_the_diagnostic_runs_end_to_end_on_a_v314_and_a_v35_file(self):
        """The two tracked goldens are ONE input through the two engines, with
        different bin ladders -- not two probes. What this checks is that both
        files open, align and integrate; the physics check is the synthetic pair."""
        r = pc.crossover_diagnostic(SD_V314, SD_V35)
        a, b = pc.read_probe(SD_V314), pc.read_probe(SD_V35)
        lo, hi = r.size_range
        self.assertEqual((lo, hi), (0.2, 1.285))      # no shared edge: raw overlap
        self.assertFalse(r.edges_aligned)
        np.testing.assert_array_equal(r.time, np.intersect1d(a.time, b.time))
        wa = pc.overlap_weights(a.bin_min, a.bin_max, lo, hi)
        # sizeDist writes a whole row NaN for a second with no sample volume
        # (0/0); those seconds, and only those, are "missing".
        empty = np.isnan(a.conc).all(axis=1) | np.isnan(b.conc).all(axis=1)
        self.assertEqual(int(empty.sum()), 4)
        np.testing.assert_array_equal(r.status == "missing", empty)
        np.testing.assert_allclose(r.n_a[~empty], (a.conc * wa).sum(axis=1)[~empty])
        self.assertTrue(set(r.status) <= set(pc.STATUSES))

    def test_a_combined_product_reads_back_to_its_sd_file(self):
        from arrayprobe.combine import combine_sizedist
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "combined.cdf"
            combine_sizedist([SD_V314], out, flight_date="20160906",
                             summary_time="16_09_06_16_41_00")
            comb = pc.read_probe(out)
            sd = pc.read_probe(SD_V314)
        self.assertEqual(comb.source_format, "combined")
        # 16:41:00 summary time, data from 16:41:28: 28 padding rows, then the
        # six sd seconds, one per whole second.
        n = sd.time.size
        self.assertEqual(comb.time.size, 28 + n)
        np.testing.assert_array_equal(np.diff(comb.time[-n:]), np.ones(n - 1))
        np.testing.assert_array_equal(comb.conc[-n:], sd.conc)     # NaN == NaN here
        np.testing.assert_array_equal(comb.count[-n:], sd.count)


@unittest.skipUnless(HELD_2DS.is_file() and HELD_HVPS.is_file(),
                     "The 2016-09-06 2D-S/HVPS combined products are not held here is not "
                     "distributed with the package; this test runs in the development repository")
class HeldOraclesPair(unittest.TestCase):
    """The figures quoted in enhancements_uiops/README.md, re-measured when the data is present."""

    def test_the_full_overlap_is_dominated_by_the_hvps_one_pixel_bin(self):
        r = pc.crossover_diagnostic(HELD_2DS, HELD_HVPS)
        self.assertTrue(r.edges_aligned)
        self.assertEqual(r.counts_by_status(), {"missing": 24367, "insufficient": 4140,
                                                "agree": 3, "a_higher": 287, "b_higher": 0})

    def test_above_375_um_the_flight_average_agrees_within_counting(self):
        r = pc.crossover_diagnostic(HELD_2DS, HELD_HVPS, size_range=(0.375, 1.275),
                                    window_s=100000)
        self.assertEqual(list(r.status), ["agree"])
        self.assertAlmostEqual(r.ratio[0], 1.634, places=3)


if __name__ == "__main__":
    unittest.main()
