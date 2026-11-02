# SPDX-License-Identifier: BSD-3-Clause
"""Tests for arrayprobe_enhancements.field2006_shatter, the Process2D-derived Field et al. (2006) fit.

Synthetic inter-arrival streams are drawn, seeded, from a known double-Poisson
(two-exponential) mixture. The transcription oracle against compiled
process2d.cpp is a later slice; these pin the statistics and Process2D's own
edge handling.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from arrayprobe_enhancements import field2006_shatter as f6

LAM1 = 1.0e2  # natural inter-arrival rate, s^-1
LAM2 = 1.0e5  # shattering burst rate, s^-1


def _mixture(seed: int, p: float, n: int = f6.NITQ) -> np.ndarray:
    rng = np.random.default_rng(seed)
    first = rng.random(n) < p
    return np.where(first, rng.exponential(1.0 / LAM1, n),
                    rng.exponential(1.0 / LAM2, n))


def _filled_state(gaps: np.ndarray) -> f6.Field2006State:
    st = f6.Field2006State()
    for g in gaps:
        st.push(float(g))
    return st


class TestBins(unittest.TestCase):
    def test_endpoints_span_1e_7_to_10_s_in_0_2_decades(self):
        ep = f6.bin_endpoints()
        self.assertEqual(ep.dtype, np.float32)
        self.assertEqual(ep.size, 41)
        self.assertAlmostEqual(float(ep[0]), 1e-7, delta=1e-13)
        self.assertEqual(float(ep[35]), 1.0)
        self.assertAlmostEqual(float(ep[40]), 10.0, places=5)

    def test_midpoints_are_half_a_bin_up(self):
        mp = f6.bin_midpoints()
        self.assertEqual(mp.size, 40)
        self.assertAlmostEqual(float(mp[0]), 10 ** (-34.5 / 5), delta=1e-12)

    def test_histogram_has_no_lower_bound_and_drops_10_s(self):
        h = f6.histogram(np.array([0.0, 1e-12, 5e-8, 10.0, 11.0, 2e-7]))
        self.assertEqual(int(h[0]), 3)  # 0, 1e-12, 5e-8 all land in bin 0
        self.assertEqual(int(h.sum()), 4)  # 10 s and 11 s dropped

    def test_fresh_queue_quirk_399_zeros_in_bin_0(self):
        # process2d.cpp:726 ``double itq[nitq]={1}``; 1.0 is not > ep[35]=1.0
        h = f6.histogram(f6.Field2006State().itq)
        self.assertEqual(int(h[0]), 399)
        self.assertEqual(int(h[34]), 1)


class TestRecoversKnownMixture(unittest.TestCase):
    """400 samples: a1 within 20 % of LAM1 on each seeded stream (statistical)."""

    SEEDS = (1, 2, 3, 4, 5)

    def test_a1_recovered_and_cutoff_between_modes(self):
        for p in (0.8, 0.95):
            for seed in self.SEEDS:
                with self.subTest(p=p, seed=seed):
                    st = _filled_state(_mixture(seed, p))
                    a0, a1, a2, pc, cf = st.fit_second()
                    self.assertLess(abs(a1 / LAM1 - 1.0), 0.20, (a0, a1, a2))
                    self.assertLess(1.0 / LAM2, pc)
                    self.assertLess(pc, 1.0 / LAM1)
                    self.assertAlmostEqual(pc, 0.05 / st.bestfit[1],
                                           delta=1e-6 * pc)

    def test_corrfac_is_the_constant_1_1142_for_any_successful_fit(self):
        expected = 1.0 / (2 * math.exp(-0.05) - 1)
        for seed in self.SEEDS:
            st = _filled_state(_mixture(seed, 0.9))
            *_, cf = st.fit_second()
            self.assertAlmostEqual(cf, expected, delta=1e-6)


class TestProcess2DEdgeHandling(unittest.TestCase):
    def test_low_counts_return_minus_one_and_leave_a_untouched(self):
        a = np.array([0.5, 123.0, 4.0e5])
        y = np.zeros(40, dtype=np.float32)
        y[20] = 9  # sum 9 < 10 (process2d.cpp:236)
        r = f6.dpoisson_fit(f6.bin_midpoints(), y, a)
        self.assertEqual(r, -1.0)
        np.testing.assert_array_equal(a, [0.5, 123.0, 4.0e5])

    def test_fresh_queue_fit_diverges_to_nan_as_process2d_does(self):
        # Not a difference from Process2D: the compiled harness reports the
        # initial queue's fit as not finite, and so does this transcription.
        # itq = {1}: 399 zeros in bin 0 and one entry in bin 34, ysum = 400 >= 10,
        # so the fit runs from a1 = 1/x[0] ~ 7.9e6. JJt is near-singular
        # (det ~1e-32 .. 1e-40); the third damped step drives a1 negative
        # (~ -1.5e8), exp(-a1*x) overflows at the large midpoints, det is
        # inf - inf = NaN, and NaN carries through every parameter.
        a = np.zeros(3)
        h = f6.histogram(f6.Field2006State().itq).astype(np.float32)
        with np.errstate(all="ignore"):
            ret = f6.dpoisson_fit(f6.bin_midpoints(), h, a)
        self.assertTrue(math.isnan(ret))
        self.assertTrue(np.isnan(a).all())
        pc = f6.cutoff(float(a[1]))
        cf = f6.correction_factor(pc, float(a[1]))
        self.assertTrue(math.isnan(pc) and math.isnan(cf))
        # A NaN cutoff rejects nothing (every ``t < NaN`` is false) and the
        # factor applies as 1 (process2d.cpp:1075-1079); the NaN does not
        # persist, because the next fit with ysum >= 10 overwrites ``a``
        # with its own first guess (process2d.cpp:239-242).
        self.assertEqual(f6.applied_corrfac(np.array([cf])).tolist(), [1.0])
        with np.errstate(all="ignore"):
            res = f6.apply(np.array([1e-9, 1e-9, 1e-9]), np.array([0, 0, 0]))
        self.assertTrue(np.isnan(res.cutoff_s[0]))
        self.assertFalse(res.rejected.any())

    def test_no_fit_ever_gives_infinite_cutoff_and_nan_corrfac(self):
        pc = f6.cutoff(0.0)
        self.assertTrue(math.isinf(pc))
        self.assertTrue(math.isnan(f6.correction_factor(pc, 0.0)))

    def test_single_mode_stream_still_fits_and_cuts_below_it(self):
        rng = np.random.default_rng(11)
        st = _filled_state(rng.exponential(1.0 / LAM1, f6.NITQ))
        a0, a1, a2, pc, _ = st.fit_second()
        self.assertTrue(np.isfinite([a0, a1, a2, pc]).all())
        self.assertLess(abs(a1 / LAM1 - 1.0), 0.20)

    def test_queue_wraps_at_400(self):
        st = f6.Field2006State()
        for i in range(f6.NITQ + 3):
            st.push(float(i))
        self.assertEqual(st.iitq, 3)
        self.assertEqual(st.itq[2], float(f6.NITQ + 2))
        self.assertEqual(st.itq[3], 3.0)


if __name__ == "__main__":
    unittest.main()


class TestApply(unittest.TestCase):
    """The per-second pair rule and diagnostics over a synthetic particle stream."""

    def _stream(self):
        gaps = np.concatenate([_mixture(7, 0.9), _mixture(8, 0.9), _mixture(9, 0.9)])
        sec = np.repeat([100, 101, 102], f6.NITQ)
        return gaps, sec

    def test_one_fit_per_second_present(self):
        gaps, sec = self._stream()
        r = f6.apply(gaps, sec)
        np.testing.assert_array_equal(r.seconds, [100, 101, 102])
        self.assertEqual(r.rejected.shape, gaps.shape)
        for a1 in r.a1[1:]:
            self.assertLess(abs(a1 - LAM1) / LAM1, 0.25)

    def test_first_particle_of_next_second_is_in_the_fit(self):
        gaps, sec = self._stream()
        r = f6.apply(gaps, sec)
        st = f6.Field2006State()
        for g in gaps[:f6.NITQ + 1]:
            st.push(float(g))
        self.assertEqual(st.fit_second()[3], r.cutoff_s[0])

    def test_pair_rule_is_strict_and_crosses_the_boundary(self):
        gaps, sec = self._stream()
        r = f6.apply(gaps, sec)
        g = gaps.copy()
        # last particle of second 100: long own gap, so only the next particle's
        # (first of 101) gap can reject it, judged against second 100's cutoff
        i = f6.NITQ - 1
        g[i] = 1.0
        g[i + 1] = 1e-9  # far below any cutoff
        r1 = f6.apply(g, sec)
        self.assertTrue(r1.rejected[i])
        self.assertLess(g[i + 1], r1.cutoff_s[0])
        g[i + 1] = 1.0
        r2 = f6.apply(g, sec)
        self.assertFalse(r2.rejected[i])
        self.assertFalse(r.rejected[i] and gaps[i] >= r.cutoff_s[0]
                         and gaps[i + 1] >= r.cutoff_s[0])

    def test_gap_equal_to_cutoff_is_kept(self):
        # strict '<' on the own gap: build the cutoff first, then place a gap on it
        gaps, sec = self._stream()
        pc = f6.apply(gaps, sec).cutoff_s[2]
        g = gaps.copy()
        j = 2 * f6.NITQ + 5  # inside the last second; refit sees one changed gap
        g[j] = pc
        g[j + 1] = 1.0
        r = f6.apply(g, sec)
        if r.cutoff_s[2] == pc:
            self.assertFalse(r.rejected[j])
        else:
            self.assertEqual(bool(r.rejected[j]), pc < r.cutoff_s[2])

    def test_rejected_matches_the_rule(self):
        gaps, sec = self._stream()
        r = f6.apply(gaps, sec)
        pc = np.repeat(r.cutoff_s, f6.NITQ)
        want = gaps < pc
        want[:-1] |= gaps[1:] < pc[:-1]
        np.testing.assert_array_equal(r.rejected, want)
        self.assertTrue(r.rejected.any())
        self.assertFalse(r.rejected.all())

    def test_corrfac_constant_and_applied_before_volume(self):
        gaps, sec = self._stream()
        r = f6.apply(gaps, sec)
        expect = 1.0 / (2 * math.exp(-0.05) - 1)
        np.testing.assert_allclose(r.corrfac, expect, rtol=1e-6)
        counts = np.ones((3, 4))
        np.testing.assert_allclose(f6.corrected_counts(counts, r.corrfac), expect, rtol=1e-6)

    def test_nan_corrfac_applies_as_one(self):
        np.testing.assert_array_equal(f6.applied_corrfac(np.array([np.nan, 2.0])), [1.0, 2.0])

    def test_refuses_out_of_order_seconds(self):
        with self.assertRaises(ValueError):
            f6.apply(np.array([0.1, 0.1]), np.array([2, 1]))

    def test_empty_stream(self):
        r = f6.apply(np.array([]), np.array([]))
        self.assertEqual(r.rejected.size, 0)
        self.assertEqual(r.seconds.size, 0)

    def test_align_fills_absent_seconds_with_nan(self):
        gaps, sec = self._stream()
        r = f6.apply(gaps, sec)
        out = f6.align_to_axis(r, np.array([99, 100, 101, 102, 103]))
        self.assertTrue(np.isnan(out["field2006_a1"][0]))
        self.assertTrue(np.isnan(out["field2006_corrfac"][4]))
        self.assertEqual(out["field2006_cutoff_s"][1], r.cutoff_s[0])


class TestWriteDiagnostics(unittest.TestCase):
    def test_existing_variables_unchanged_and_new_ones_added(self):
        import os
        import tempfile

        import netCDF4

        gaps, sec = TestApply()._stream()
        r = f6.apply(gaps, sec)
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "sd.nc")
            dst = os.path.join(d, "sd_field2006.nc")
            with netCDF4.Dataset(src, "w", format="NETCDF3_CLASSIC") as nc:
                nc.createDimension("time", 4)
                nc.createDimension("bin", 3)
                v = nc.createVariable("conc_minR", "f4", ("bin", "time"))
                v.units = "cm-4"
                v[:] = np.arange(12, dtype=np.float32).reshape(3, 4)
                nc.setncattr("Creation Time", "x")
            diag = f6.align_to_axis(r, np.array([99, 100, 101, 102]))
            f6.write_diagnostics(src, dst, "time", diag)
            with netCDF4.Dataset(src) as a, netCDF4.Dataset(dst) as b:
                np.testing.assert_array_equal(a["conc_minR"][:], b["conc_minR"][:])
                self.assertEqual(a["conc_minR"].units, b["conc_minR"].units)
                self.assertEqual(b.getncattr("Creation Time"), "x")
                self.assertIn("process2d-derived", b.field2006_stamp)
                for name in f6.DIAGNOSTIC_VARIABLES:
                    self.assertIn("Process2D-derived", b[name].source)
                got = np.ma.filled(b["field2006_a1"][:], np.nan)
                self.assertTrue(np.isnan(got[0]))
                self.assertEqual(float(got[1]), float(np.float32(r.a1[0])))
            with self.assertRaises(ValueError):
                f6.write_diagnostics(dst, dst, "time", diag)
