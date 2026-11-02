# SPDX-License-Identifier: BSD-3-Clause
"""arrayprobe.tools.probe_comparison on synthetic netCDF and synthetic count series.

Every file is built in a temporary directory from arithmetic; no measurement is read.
"""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.tools import probe_comparison as pc

MODULE = Path(pc.__file__)
T0 = 7 * 3600   # 07:00:00 UT


def _hhmmss(ut):
    return (ut // 3600) * 10000 + ((ut % 3600) // 60) * 100 + ut % 60


def write_sd(path, ut, nd_per_bin, counts, bmin_mm, dd_mm):
    """sizeDist layout: conc_minR in cm-4, (Time, CIPcorrlen) on disk."""
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("Time", len(ut))
        d.createDimension("CIPcorrlen", len(bmin_mm))
        d.createVariable("time", "f8", ("Time",))[:] = _hhmmss(ut)
        d.createVariable("bin_min", "f8", ("CIPcorrlen",))[:] = bmin_mm
        d.createVariable("bin_max", "f8", ("CIPcorrlen",))[:] = bmin_mm + dd_mm
        d.createVariable("bin_dD", "f8", ("CIPcorrlen",))[:] = dd_mm
        d.createVariable("conc_minR", "f8", ("Time", "CIPcorrlen"))[:] = nd_per_bin * 10.0 / dd_mm
        d.createVariable("count", "f8", ("Time", "CIPcorrlen"))[:] = counts
        d.createVariable("n", "f8", ("Time",))[:] = np.nansum(nd_per_bin, 1)


class TestRebin(unittest.TestCase):
    def test_ten_10um_bins_sum_exactly_to_the_100um_bin(self):
        bmin = 5.0 + 10.0 * np.arange(128)
        w = pc.rebin_weights(bmin, bmin + 10.0, pc.COMMON_EDGES_UM)
        self.assertTrue(np.all((w == 0.0) | (w == 1.0)))
        np.testing.assert_array_equal(w.sum(0), [5] + [10] * 9)
        x = np.arange(128, dtype=np.float64)[None, :]
        got = pc.rebin(x, w)[0]
        self.assertEqual(got[1], float(np.sum(np.arange(10, 20))))  # 105-205 = native bins 11-20

    def test_straddling_bin_is_apportioned_by_width(self):
        w = pc.rebin_weights(np.array([87.5]), np.array([112.5]), pc.COMMON_EDGES_UM)
        self.assertAlmostEqual(w[0, 0], 0.7)
        self.assertAlmostEqual(w[0, 1], 0.3)

    def test_rebin_keeps_nan_where_every_contributor_is_nan(self):
        bmin = 5.0 + 10.0 * np.arange(128)
        w = pc.rebin_weights(bmin, bmin + 10.0, pc.COMMON_EDGES_UM)
        x = np.full((1, 128), np.nan)
        self.assertTrue(np.all(np.isnan(pc.rebin(x, w))))

    def test_align_keeps_only_shared_seconds(self):
        common, xa, xb = pc.align(np.array([1, 2, 3]), np.array([10., 20., 30.]),
                                  np.array([2, 3, 4]), np.array([200., 300., 400.]))
        np.testing.assert_array_equal(common, [2, 3])
        np.testing.assert_array_equal(xa, [20., 30.])
        np.testing.assert_array_equal(xb, [200., 300.])


class TestEmptySeconds(unittest.TestCase):
    def test_zero_empty_rows_zeroes_nan_bins_of_a_finite_total_and_keeps_a_gap(self):
        x = np.array([[np.nan, np.nan], [np.nan, np.nan], [1.0, np.nan]])
        n_tot = np.array([0.0, np.nan, 1.0])
        got = pc.zero_empty_rows(x, n_tot)
        np.testing.assert_array_equal(got[0], [0.0, 0.0])
        self.assertTrue(np.all(np.isnan(got[1])))
        np.testing.assert_array_equal(got[2], [1.0, 0.0])
        self.assertIs(pc._zero_empty_rows, pc.zero_empty_rows)

    def test_load_sd_reads_nan_bins_in_a_zero_total_second_as_zero(self):
        ut = T0 + np.arange(4)
        bmin = 0.0125 + 0.025 * np.arange(3)
        dd = np.full(3, 0.025)
        nd = np.array([[1.0, 2.0, 0.0], [np.nan] * 3, [0.5, 0.0, 0.0], [0.0, 0.0, 3.0]])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "b.nc"
            write_sd(p, ut, nd, np.nan_to_num(nd) * 10.0, bmin, dd)
            got = pc.load_sd([p])
        np.testing.assert_array_equal(got["ut"], ut)
        np.testing.assert_array_equal(got["nd"][1], [0.0, 0.0, 0.0])
        np.testing.assert_allclose(got["nd"][0], [1.0, 2.0, 0.0], rtol=1e-12)
        np.testing.assert_allclose(got["bmin"], bmin * 1000.0)

    def test_load_sd_keeps_the_first_of_a_repeated_second(self):
        bmin = np.array([0.0125])
        dd = np.array([0.025])
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2 = Path(tmp) / "1.nc", Path(tmp) / "2.nc"
            write_sd(p1, np.array([T0, T0 + 1]), np.array([[1.0], [2.0]]),
                     np.array([[1.0], [2.0]]), bmin, dd)
            write_sd(p2, np.array([T0 + 1, T0 + 2]), np.array([[9.0], [3.0]]),
                     np.array([[9.0], [3.0]]), bmin, dd)
            got = pc.load_sd([p1, p2])
        np.testing.assert_array_equal(got["ut"], [T0, T0 + 1, T0 + 2])
        np.testing.assert_allclose(got["nd"][:, 0], [1.0, 2.0, 3.0], rtol=1e-12)


class TestCoincidence(unittest.TestCase):
    def test_coincidence_recovers_a_known_lag(self):
        rng = np.random.default_rng(3)
        n = 4000
        ut_a = np.arange(n)
        shared = rng.random(n) < 0.02
        c_a = rng.poisson(0.05, n).astype(np.float64) + shared * rng.poisson(6.0, n)
        c_b = rng.poisson(0.05, n).astype(np.float64) + shared * rng.poisson(6.0, n)
        ut_b = ut_a + 7          # the same shared events, stamped 7 s later on b's own clock
        lags = list(range(-15, 16)) + [-600, 600]
        res = pc.coincidence_vs_lag(ut_a, c_a, ut_b, c_b, gate_a=2.0, gate_b=2.0, lags=lags)
        self.assertEqual(res["peak_lag_s"], 7)
        i600 = res["lags_s"].index(600)
        lo, hi = res["wilson_b_given_a"][i600]
        self.assertIsNotNone(res["unconditional_b"])
        self.assertIsNotNone(lo)
        self.assertLessEqual(lo - 1e-9, res["unconditional_b"])
        self.assertGreaterEqual(hi + 1e-9, res["unconditional_b"])

    def test_coincidence_on_independent_series_has_no_peak(self):
        rng = np.random.default_rng(5)
        n = 3000
        ut_a = np.arange(n)
        c_a = rng.poisson(0.3, n).astype(np.float64)
        c_b = rng.poisson(0.3, n).astype(np.float64)   # unrelated draw, same marginal rate
        lags = list(range(-20, 21))
        res = pc.coincidence_vs_lag(ut_a, c_a, ut_a, c_b, gate_a=1.0, gate_b=1.0, lags=lags)
        peak_i = res["lags_s"].index(res["peak_lag_s"])
        lo, hi = res["wilson_b_given_a"][peak_i]
        self.assertIsNotNone(res["unconditional_b"])
        self.assertIsNotNone(lo)
        self.assertLessEqual(lo - 1e-9, res["unconditional_b"])
        self.assertGreaterEqual(hi + 1e-9, res["unconditional_b"])

    def test_lag_list_is_dense_near_zero_then_coarse(self):
        lags = pc.build_lag_list(600)
        self.assertEqual(lags[:3], [-600, -450, -300])
        self.assertTrue(set(range(-30, 31)) <= set(lags))
        self.assertEqual(lags, sorted(set(lags)))


class TestWindowBins(unittest.TestCase):
    def test_zero_seconds_are_zeros_in_window_means(self):
        ut = np.arange(300)
        nd = np.zeros((300, 2))
        counts = np.zeros((300, 2))
        res = pc._window_bins(ut, nd, counts, 300, 270, np.ones(300, dtype=bool))
        self.assertEqual(len(res["bins"]), 1)
        b = res["bins"][0]
        self.assertTrue(b["kept"])
        self.assertEqual(b["n_valid"], 300)
        self.assertEqual(b["mean_N"], [0.0, 0.0])

    def test_combined_windows_carry_both_sides(self):
        ut = np.arange(300)
        mask = np.ones(300, dtype=bool)
        wa = pc._window_bins(ut, np.ones((300, 1)), np.ones((300, 1)), 300, 270, mask)
        wb = pc._window_bins(ut, 2 * np.ones((300, 1)), np.ones((300, 1)), 300, 270, mask)
        row = pc._combine_windows(wa, wb)["bins"][0]
        self.assertEqual(row["mean_N_a"], [1.0])
        self.assertEqual(row["mean_N_b"], [2.0])
        self.assertEqual(row["sum_C_a"], [300.0])


class TestRowTotal(unittest.TestCase):
    def test_nan_only_where_every_unmasked_bin_is_nan(self):
        x = np.array([[1.0, np.nan], [np.nan, np.nan], [np.nan, 2.0]])
        np.testing.assert_array_equal(pc.row_total(x)[[0, 2]], [1.0, 2.0])
        self.assertTrue(np.isnan(pc.row_total(x)[1]))
        masked = pc.row_total(x, np.array([False, True]))
        self.assertTrue(np.isnan(masked[0]))
        self.assertEqual(masked[2], 2.0)


class TestScatterStats(unittest.TestCase):
    def test_same_particles_give_rma_slope_one(self):
        x = np.array([10., 20., 5., 50., 100., 8., 30.])
        res = pc.scatter_stats(x, x.copy(), gate=(1.0, 1.0))
        self.assertAlmostEqual(res["rma_slope_log10"], 1.0, delta=0.05)
        self.assertAlmostEqual(res["median_ratio_gated"], 1.0, places=9)

    def test_rma_is_symmetric(self):
        x = np.array([1., 2., 4., 8., 16., 32., 64.])
        y = x ** 1.5
        fwd = pc.scatter_stats(x, y, gate=(0.0, 0.0))
        rev = pc.scatter_stats(y, x, gate=(0.0, 0.0))
        self.assertAlmostEqual(fwd["rma_slope_log10"], 1.5, places=6)
        self.assertAlmostEqual(fwd["rma_slope_log10"] * rev["rma_slope_log10"], 1.0, places=6)

    def test_gate_x_gate_y_gate_a_different_array_than_the_one_correlated(self):
        """Window means are correlated but gated on summed counts; reusing the means as the
        gate would compare a concentration against a counts threshold it never crosses."""
        x = np.array([0.01, 0.02, 0.03, 0.05, 0.08])
        y = np.array([0.02, 0.04, 0.05, 0.09, 0.16])
        counts_x = np.array([50.0, 80.0, 120.0, 150.0, 200.0])
        counts_y = np.array([10.0, 15.0, 25.0, 30.0, 40.0])
        self.assertEqual(pc.scatter_stats(x, y, gate=(100.0, 20.0))["n_gated"], 0)
        by_counts = pc.scatter_stats(x, y, gate=(100.0, 20.0), gate_x=counts_x, gate_y=counts_y)
        self.assertEqual(by_counts["n_gated"], 3)
        self.assertIsNotNone(by_counts["rma_slope_log10"])

    def test_no_raw_pearson_key_anywhere_in_scatter_output(self):
        stats = pc.scatter_stats(np.array([1., 2., 3.]), np.array([3., 1., 2.]), gate=(0.0, 0.0))
        for k in stats:
            if "pearson" in k:
                self.assertTrue(k.endswith("_log1p") or k.endswith("_log_gated"),
                                f"unexpected raw-sounding correlation key {k!r}")

    def test_raw_pearson_is_misleading_where_log1p_and_spearman_are_not(self):
        """Mostly-zero counts plus one dominating, disagreeing second wreck raw Pearson while
        the bulk trend is monotonic."""
        rng = np.random.default_rng(1)
        n = 2000
        x = np.zeros(n)
        y = np.zeros(n)
        dense = rng.random(n) < 0.08
        base = rng.gamma(2.0, 3.0, int(dense.sum()))
        x[dense] = base
        y[dense] = base * rng.uniform(0.85, 1.15, int(dense.sum()))
        x[0], y[0] = 1600.0, 0.0
        raw_r = float(np.corrcoef(x, y)[0, 1])
        res = pc.scatter_stats(x, y, gate=(1.0, 1.0))
        self.assertLess(raw_r, 0.3)
        self.assertGreater(res["pearson_log1p"], 0.6)
        self.assertGreater(res["spearman"], 0.6)


class TestPoissonRatioCI(unittest.TestCase):
    def test_interval_brackets_the_ratio_and_refuses_zero_counts(self):
        lo, hi = pc.poisson_ratio_ci(1.0, 100.0, 100.0)
        self.assertLess(lo, 1.0)
        self.assertGreater(hi, 1.0)
        self.assertEqual(pc.poisson_ratio_ci(1.0, 0.0, 100.0), (None, None))


class TestModuleImports(unittest.TestCase):
    """The helper ships in the core package: it imports no v3.1.4 engine module and nothing
    from the development ``scripts/`` directory."""

    V314 = ("arrayprobe.reject", "arrayprobe.habit", "arrayprobe.imgproc", "arrayprobe.sizedist",
            "arrayprobe.particle_physics", "arrayprobe.readers")

    def _imported(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names.append("." * node.level + (node.module or ""))
        return names

    def test_imports_no_v314_engine_module_and_no_script(self):
        names = self._imported()
        self.assertTrue(names, "the sweep found no import at all")
        for name in names:
            self.assertFalse(name.startswith("."), f"relative import {name!r}")
            for bad in self.V314:
                self.assertFalse(name == bad or name.startswith(bad + "."), name)
            for bad in ("scripts", "compare_cip_2ds", "compare_cip_2ds_figures",
                        "engine_scope_guard"):
                self.assertFalse(name == bad or name.startswith(bad + "."), name)

    def test_text_names_no_script_path(self):
        text = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("sys.path", text)
        self.assertNotIn("scripts/", text)


def _pair_products(tmp):
    """The same synthetic particles written on a 10-um ladder (a) and a 50-um ladder (b) whose
    edges are a subset of a's, so both sum to identical totals on the common grid."""
    rng = np.random.default_rng(7)
    ut = T0 + np.arange(900)
    nd10 = rng.poisson(2.0, size=(len(ut), 128)).astype(np.float64)
    bmin10 = (5.0 + 10.0 * np.arange(128)) / 1000.0
    pa = str(Path(tmp) / "a.nc")
    write_sd(pa, ut, nd10, nd10 * 10.0, bmin10, np.full(128, 0.010))
    nd50 = np.stack([nd10[:, 5 + 5 * k:10 + 5 * k].sum(1) for k in range(20)], axis=1)
    bmin50 = (55.0 + 50.0 * np.arange(20)) / 1000.0
    pb = str(Path(tmp) / "b.nc")
    write_sd(pb, ut, nd50, nd50 * 10.0, bmin50, np.full(20, 0.050))
    return pc.load_sd([pa]), pc.load_sd([pb])


class TestComparePair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.a, cls.b = _pair_products(tmp)

    def test_same_particles_give_R_1_in_every_common_bin(self):
        res = pc.compare_pair(self.a, self.b)
        self.assertEqual(res["overlap_seconds"], 900)
        self.assertEqual(len(res["bins"]), len(pc.COMMON_EDGES_UM) - 1)
        for row in res["bins"]:
            self.assertAlmostEqual(row["R_b_over_a"], 1.0, places=12)
            lo, hi = row["R_ci95"]
            self.assertLess(lo, 1.0)
            self.assertGreater(hi, 1.0)

    def test_exclude_from_totals_drops_the_bin_from_sums_but_keeps_its_row(self):
        full = pc.compare_pair(self.a, self.b)
        excl = pc.compare_pair(self.a, self.b, exclude_from_totals=[(55.0, 105.0)])
        self.assertEqual(len(excl["bins"]), len(full["bins"]))
        self.assertFalse(excl["bins"][0]["comparable"])
        self.assertTrue(all(r["comparable"] for r in excl["bins"][1:]))
        self.assertTrue(all(r["comparable"] for r in full["bins"]))
        self.assertEqual(excl["bins"][0]["R_b_over_a"], full["bins"][0]["R_b_over_a"])
        w_full = [w for w in full["windows"]["bins"] if w["kept"]]
        w_excl = [w for w in excl["windows"]["bins"] if w["kept"]]
        self.assertEqual(len(w_full), len(w_excl))
        mask = pc._exclusion_mask(pc.COMMON_EDGES_UM, [(55.0, 105.0)])
        self.assertFalse(mask[0])
        self.assertLess(pc._comparable_sum(w_excl[0]["mean_N_a"], mask),
                        pc._comparable_sum(w_full[0]["mean_N_a"], None))
        self.assertNotEqual(full["scatter_1hz"], excl["scatter_1hz"])
        self.assertEqual(excl["excluded_from_totals_um"], [[55.0, 105.0]])

    def test_edge_shift_zero_equals_the_unshifted_ratio(self):
        res = pc.compare_pair(self.a, self.b, edge_shift_um=0.0)
        for row in res["bins"]:
            for v in row["R_edge_shift"].values():
                self.assertEqual(v, row["R_b_over_a"])

    def test_no_raw_pearson_key_anywhere_in_compare_pair_output(self):
        res = pc.compare_pair(self.a, self.b)

        def keys(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from keys(v)
            elif isinstance(o, list):
                for v in o:
                    yield from keys(v)

        for k in keys(res):
            if "pearson" in str(k):
                self.assertIn("log", k, f"raw Pearson key {k!r} in compare_pair output")

    def test_size_distributions_agree_on_the_common_grid(self):
        res = pc.compare_pair(self.a, self.b)
        ca = res["size_distributions"]["a"]["common"]["dNdD_cm3_um"]
        cb = res["size_distributions"]["b"]["common"]["dNdD_cm3_um"]
        np.testing.assert_allclose(ca, cb, rtol=1e-12)

    def test_window_means_wrapper_matches_the_two_private_calls(self):
        ut = T0 + np.arange(600)
        nd = np.ones((600, 2))
        bf = np.ones(600, dtype=bool)
        got = pc.window_means(ut, nd, nd, 2 * nd, nd, window_s=300, min_cover=270,
                              both_finite=bf)
        want = pc._combine_windows(pc._window_bins(ut, nd, nd, 300, 270, bf),
                                   pc._window_bins(ut, 2 * nd, nd, 300, 270, bf))
        self.assertEqual(got, want)

    def test_bin_stats_names_its_columns_a_and_b(self):
        nd = np.ones((3, 2))
        rows = pc.bin_stats(nd, nd, 2 * nd, nd, np.ones(3, dtype=bool))
        self.assertEqual(set(rows[0]), {"n_seconds", "counts_a", "counts_b", "sumN_a_cm3s",
                                        "sumN_b_cm3s", "R_b_over_a", "R_ci95"})
        self.assertEqual(rows[0]["R_b_over_a"], 2.0)


if __name__ == "__main__":
    unittest.main()
