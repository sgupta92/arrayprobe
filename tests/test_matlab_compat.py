# SPDX-License-Identifier: BSD-3-Clause
"""Tests for matlab_compat.

Three layers, per design doc section 2.7:
  1. Golden values  -- hard-coded MATLAB/Octave answers.
  2. Properties     -- invariants that must hold for all inputs.
  3. Call-site regressions -- one per preserved bug, named after the line it
     protects.  THESE MUST FAIL if someone later "cleans up" the behaviour.

Octave 11.3.0 was used as the license-free oracle on 2026-08-19; the values it
returned are quoted in the relevant docstrings.
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import matlab_compat as mc  # noqa: E402

# ---------------------------------------------------------------- layer 1 ---

class TestMround(unittest.TestCase):
    """MATLAB rounds half AWAY FROM ZERO; NumPy rounds half to even."""

    def test_half_integers_go_away_from_zero(self):
        # MATLAB: 1, 2, 3, -1, -3.  NumPy would give 0, 2, 2, -0, -2.
        for x, expected in [(0.5, 1), (1.5, 2), (2.5, 3), (-0.5, -1), (-2.5, -3)]:
            self.assertEqual(mc.mround(x), expected, f"round({x!r})")

    def test_differs_from_numpy_where_it_matters(self):
        self.assertNotEqual(mc.mround(2.5), np.round(2.5))
        self.assertNotEqual(mc.mround(0.5), np.round(0.5))

    def test_elementwise_and_nan_safe(self):
        out = mc.mround([0.5, -0.5, np.nan, np.inf])
        np.testing.assert_array_equal(out[:2], [1.0, -1.0])
        self.assertTrue(np.isnan(out[2]))
        self.assertTrue(np.isinf(out[3]))

    def test_the_addition_does_not_round(self):
        """A24: ``floor(x + 0.5)`` rounds in the addition itself, so the largest double
        below 0.5 and every odd integer above 2^52 came out one too high.  MATLAB and
        Octave give 0 and the integer."""
        below_half = 0.49999999999999994
        self.assertLess(below_half, 0.5)
        self.assertEqual(mc.mround(below_half), 0.0)
        self.assertEqual(mc.mround(-below_half), 0.0)
        self.assertEqual(mc.mint32(below_half), 0)
        self.assertEqual(mc.mint16(-below_half), 0)
        for odd in (2.0**52 + 1, 2.0**52 + 3, 2.0**53 - 1):
            self.assertEqual(mc.mround(odd), odd, repr(odd))
            self.assertEqual(mc.mround(-odd), -odd, repr(odd))

    def test_matches_octave_round_and_int16(self):
        """The Octave golden R10 took for the v3.5 helpers (``round``/``int16`` of 14
        values, 6 of which ``floor(x + 0.5)`` got wrong)."""
        import json
        from pathlib import Path
        golden = json.loads((Path(__file__).resolve().parent / "data"
                             / "v35_r10_particle_golden.json").read_text(encoding="utf-8"))
        for row in golden["round"]:
            with self.subTest(x=row["x"]):
                self.assertEqual(mc.mround(row["x"]), row["round"])
                self.assertEqual(int(mc.mint16(row["x"])), row["int16"])


class TestIntegerArithmetic(unittest.TestCase):
    """Design-doc trap T1, verified in Octave 11.3.0."""

    def test_octave_verified_values(self):
        self.assertEqual(mc.mmul(np.int16(37), 0.010), 0)       # Octave: 0
        self.assertEqual(mc.mmul(np.int16(50), 0.010), 1)       # Octave: 1
        self.assertEqual(mc.mmul(np.int16(-50), 0.010), -1)     # Octave: -1
        self.assertEqual(mc.mpow(np.int16(300), 2), 32767)      # Octave: 32767
        self.assertEqual(mc.mdiv(np.int16(5), np.int16(2)), 3)  # Octave: 3

    def test_integer_wins_over_double(self):
        """class(int16(37)*0.010) is int16, not double."""
        self.assertEqual(np.asarray(mc.mmul(np.int16(37), 0.010)).dtype, np.int16)

    def test_saturates_rather_than_wrapping(self):
        """int16(300)^2 is 32767 -- not 90000, and not the wrapped 24464."""
        self.assertEqual(mc.mpow(np.int16(300), 2), 32767)
        self.assertNotEqual(mc.mpow(np.int16(300), 2), 24464)

    def test_sqrt_promotes_to_double(self):
        """sqrt does NOT follow the saturating-integer rule.

        Octave: sqrt(int16(10)) -> 3.1623, class double.  This is why msqrt is
        separate from mmul/mpow; a uniform policy would break sizeDist.m:888.
        """
        out = mc.msqrt(np.int16(10))
        self.assertEqual(np.asarray(out).dtype, np.float64)
        self.assertAlmostEqual(float(out), 3.1622776601683795, places=12)

    def test_double_only_operands_stay_double(self):
        self.assertEqual(np.asarray(mc.mmul(37.0, 0.010)).dtype, np.float64)
        self.assertAlmostEqual(float(mc.mmul(37.0, 0.010)), 0.37)

    def test_a_bare_python_int_literal_is_wrongly_treated_as_matlab_integer(self):
        """The caller trap `_int_dtype_of`'s own docstring warns about, found
        2026-08-27 porting sizeDist.m:760 (`.../2 * diodesize`): a numeric
        literal in MATLAB source is `double`, but `np.asarray(2).dtype` is an
        integer dtype, so a bare Python `2` (not `2.0`) gets picked up here as
        though it were a MATLAB integer-typed operand -- even when the OTHER
        operand is genuinely double, with nothing MATLAB-integer about it at
        all. This is the mechanism itself, not the one call site that was
        fixed (sizedist.py's d_mean/_d_hypot now pass 2.0) -- a future call
        site reintroducing a bare int literal would pass silently without
        this test."""
        a = np.array([5.0, 7.0])            # genuinely double, no int16 anywhere
        wrong = mc.mdiv(a, 3)                # bare int -- misidentified as MATLAB-integer,
                                              # forcing round()-and-cast instead of true division
        right = mc.mdiv(a, 3.0)              # correct: MATLAB literal is double
        np.testing.assert_allclose(right, [5 / 3, 7 / 3])   # true double division, no rounding
        np.testing.assert_array_equal(wrong, [2.0, 2.0])    # rounded to the nearest integer
        self.assertFalse(np.allclose(wrong, right),
                         "bare-int and 3.0 divisors should disagree -- if they now agree, "
                         "the _int_dtype_of trap this test pins has been fixed and this "
                         "test (not the source) should be updated")


class TestDec2Bin(unittest.TestCase):

    def test_pads_to_width(self):
        self.assertEqual(mc.dec2bin([5], 8).tobytes(), b"00000101")

    def test_width_is_a_minimum_not_a_maximum(self):
        """imgProc_sm.m:568-571 guards against exactly this, and RETURNS from
        the whole function on mismatch.  Masking to N bits would make that
        guard dead code and silently change control flow."""
        self.assertEqual(mc.dec2bin([300], 8).shape[1], 9)

    def test_rejects_negative(self):
        """MATLAB errors; reachable at imgProc_sm.m:562 via 65535 - data."""
        with self.assertRaises(ValueError):
            mc.dec2bin([-1], 8)

    def test_matrix_shape_matches_matlab(self):
        self.assertEqual(mc.dec2bin([1, 2, 3], 8).shape, (3, 8))

    def test_concat_builds_the_particle_image(self):
        """imgProc_sm.m:559-560 -- 8 columns x 8 bits = 64 diodes (2DS)."""
        cols = np.zeros((5, 8), dtype=np.int64)
        self.assertEqual(mc.dec2bin_concat(cols, 8).shape, (5, 64))

    def test_hvps_width_is_128(self):
        """imgProc_sm.m:563-564 -- 8 columns x 16 bits."""
        cols = np.zeros((3, 8), dtype=np.int64)
        self.assertEqual(mc.dec2bin_concat(cols, 16).shape, (3, 128))


class TestBin2Dec(unittest.TestCase):

    def test_scalar_row(self):
        self.assertEqual(mc.bin2dec("00000101"), 5.0)

    def test_returns_double(self):
        self.assertIsInstance(mc.bin2dec("1010"), float)

    def test_imgProc_659_time_field_slices(self):
        """imgProc_sm.m:655-662 splits a 1x40 row with 1-based inclusive
        slices 1:5, 6:11, 12:17, 18:27, 28:40."""
        row = "1" * 40
        self.assertEqual(mc.bin2dec(row[0:5]), 31.0)       # 1:5   -> 5 bits
        self.assertEqual(mc.bin2dec(row[5:11]), 63.0)      # 6:11  -> 6 bits
        self.assertEqual(mc.bin2dec(row[11:17]), 63.0)     # 12:17 -> 6 bits
        self.assertEqual(mc.bin2dec(row[17:27]), 1023.0)   # 18:27 -> 10 bits
        self.assertEqual(mc.bin2dec(row[27:40]), 8191.0)   # 28:40 -> 13 bits


class TestNanReductions(unittest.TestCase):

    def test_nansum_of_all_nan_is_zero(self):
        self.assertEqual(mc.nansum([np.nan, np.nan]), 0.0)

    def test_nansum_of_empty_is_zero(self):
        self.assertEqual(mc.nansum([]), 0.0)

    def test_nanmean_of_all_nan_is_nan(self):
        self.assertTrue(np.isnan(mc.nanmean([np.nan, np.nan])))

    def test_nanmean_of_empty_is_nan(self):
        self.assertTrue(np.isnan(mc.nanmean([])))

    def test_msum_2d_empty_along_a_sibling_axis_preserves_shape(self):
        """Real finding, 2026-08-27: the old empty-array check fired on
        `a.size == 0` before checking which axis was actually empty, so a
        (0, 5) array reducing along axis 2 (the length-5 one) silently
        collapsed to a bare scalar 0.0 instead of MATLAB's shape-preserving
        `sum(zeros(0,5), 2)` == a (0, 1) array. Reachable in production:
        sizedist.py's (n_sec, num_bins) accumulators under a degenerate
        zero-second window."""
        a = np.zeros((0, 5))
        result = mc.msum(a, dim=2)
        self.assertEqual(result.shape, (0,))

    def test_msum_2d_empty_along_the_reduced_axis_preserves_shape(self):
        a = np.zeros((3, 0))
        result = mc.msum(a, dim=2)
        np.testing.assert_array_equal(result, np.zeros(3))

    def test_nanmean_2d_empty_along_a_sibling_axis_preserves_shape(self):
        a = np.zeros((0, 5))
        result = mc.nanmean(a, dim=2)
        self.assertEqual(result.shape, (0,))

    def test_nanmean_2d_empty_along_the_reduced_axis_preserves_shape(self):
        a = np.zeros((3, 0))
        result = mc.nanmean(a, dim=2)
        self.assertEqual(result.shape, (3,))
        self.assertTrue(np.all(np.isnan(result)))

    def test_nanmean_emits_no_warning(self):
        """MATLAB is silent; NumPy would flood the sizeDist bin loop with
        RuntimeWarning: Mean of empty slice."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertTrue(np.isnan(mc.nanmean([np.nan, np.nan])))

    def test_nansum_keeps_inf(self):
        """Octave 11.3, statistics pkg, 2026-09-23: nansum([Inf NaN 1]) = Inf,
        nansum([Inf -Inf NaN]) = NaN, nansum([realmax realmax]) = Inf.
        np.nan_to_num had mapped Inf to realmax, writing v3.5's
        zero-live-time `n` as 1.8e307 instead of Inf."""
        self.assertEqual(mc.nansum([np.inf, np.nan, 1.0]), np.inf)
        self.assertTrue(np.isnan(mc.nansum([np.inf, -np.inf, np.nan])))
        big = np.finfo(np.float64).max
        with np.errstate(over="ignore"):
            self.assertEqual(mc.nansum([big, big]), np.inf)
        np.testing.assert_array_equal(
            mc.nansum(np.array([[np.inf, 1.0], [np.nan, 2.0]]), 2),
            [np.inf, 2.0])

    def test_ordinary_values(self):
        self.assertEqual(mc.nansum([1.0, np.nan, 2.0]), 3.0)
        self.assertEqual(mc.nanmean([1.0, np.nan, 3.0]), 2.0)


class TestDatenum(unittest.TestCase):

    def test_pinned_serial_number(self):
        """MATLAB datenum(2015,12,5) == 736303."""
        self.assertEqual(mc.datenum(2015, 12, 5), 736303.0)

    def test_epoch_anchor(self):
        """MATLAB datenum(1,1,1) == 367."""
        self.assertEqual(mc.datenum(1, 1, 1), 367.0)

    def test_out_of_range_seconds_normalise(self):
        """secFromMidnight can exceed 86400 after the +240000 midnight fix at
        sizeDist.m:98; IntArrAnalysis.m:302-306 relies on normalisation."""
        self.assertEqual(mc.datenum(2015, 12, 5, 0, 0, 90000),
                         mc.datenum(2015, 12, 5) + 90000.0 / 86400.0)

    def test_date_vector_form(self):
        """IntArrAnalysis.m:304-306 passes an (N,6) matrix."""
        vec = np.array([[2015, 12, 5, 0, 0, 0], [2015, 12, 6, 0, 0, 0]])
        np.testing.assert_array_equal(mc.datenum(vec), [736303.0, 736304.0])


class TestMchar(unittest.TestCase):

    def test_reject_code_coercion(self):
        self.assertEqual(mc.mchar("S"), 83)
        self.assertEqual(mc.mchar("R"), 82)
        self.assertEqual(mc.mchar("z"), 122)

    def test_table_matches_coercion(self):
        for ch, code in mc.REJECT_CODES.items():
            self.assertEqual(mc.mchar(ch), code, f"REJECT_CODES[{ch!r}]")

    def test_imgProc_897_touching_edge_arithmetic(self):
        """imgProc_sm.m:897 computes images.image_touching_edge - '0'."""
        self.assertEqual(mc.mchar("1") - mc.mchar("0"), 1)
        self.assertEqual(mc.mchar("0") - mc.mchar("0"), 0)


class TestMGrowVector(unittest.TestCase):

    def test_zero_fills_skipped_indices(self):
        """MATLAB fills gaps with 0; list.append would not."""
        v = mc.MGrowVector()
        v[1] = 7.0
        v[4] = 9.0
        np.testing.assert_array_equal(v.asarray(), [7.0, 0.0, 0.0, 9.0])

    def test_intarr_growth_idiom(self):
        """IntArrAnalysis.m:37-38: intarr(1)=0; intarr(2:N)=diff(t)."""
        t = np.array([0.0, 1.0, 3.0, 6.0])
        v = mc.MGrowVector()
        v[1] = 0.0
        v[2:len(t)] = np.diff(t)
        np.testing.assert_array_equal(v.asarray(), [0.0, 1.0, 2.0, 3.0])


# ---------------------------------------------------------------- layer 2 ---

class TestProperties(unittest.TestCase):

    def test_dec2bin_bin2dec_roundtrip(self):
        rng = np.random.default_rng(20260819)
        vals = rng.integers(0, 65536, size=200)
        np.testing.assert_array_equal(
            mc.bin2dec(mc.dec2bin(vals, 16)), vals.astype(np.float64))

    def test_dec2bin_width_rule(self):
        for v in [0, 1, 5, 255, 256, 300, 65535]:
            for w in [1, 8, 16]:
                needed = max(1, int(v).bit_length())
                self.assertEqual(mc.dec2bin([v], w).shape[1], max(w, needed))

    def test_mround_odd_symmetry(self):
        rng = np.random.default_rng(1)
        x = rng.normal(scale=100, size=500)
        np.testing.assert_array_equal(mc.mround(x), -mc.mround(-x))

    def test_mround_half_integers_always_go_up_in_magnitude(self):
        for n in range(0, 50):
            self.assertEqual(mc.mround(n + 0.5), n + 1)
            self.assertEqual(mc.mround(-(n + 0.5)), -(n + 1))

    def test_mmul_never_exceeds_int16_range(self):
        rng = np.random.default_rng(2)
        a = rng.integers(-32768, 32768, size=300).astype(np.int16)
        out = np.asarray(mc.mmul(a, 1000.0))
        self.assertTrue(np.all(out >= -32768) and np.all(out <= 32767))

    def test_mcolon_collapses_to_first_element(self):
        self.assertTrue(np.array_equal(mc.mcolon([3, 7, 9], 10), mc.mcolon(3, 10)))
        self.assertTrue(np.array_equal(mc.mcolon(5, [8, 2]), mc.mcolon(5, 8)))


# ---------------------------------------------------------------- layer 3 ---

class TestPreservedBugs(unittest.TestCase):
    """One test per deliberately preserved UIOOPS bug.

    If a future change "fixes" the behaviour, these fail.  That is the point.
    """

    def test_mcolon_uses_only_the_first_element(self):
        """MATLAB a:b collapses a vector operand to a(1).  Cause of the two
        rollover bugs and the two reacceptance bugs below."""
        np.testing.assert_array_equal(mc.mcolon([3, 7, 9], 10), np.arange(3, 11))

    def test_mcolon_empty_operand_is_a_silent_noop(self):
        """sizeDist.m:98-99 and :657-658: an empty find() makes the whole
        assignment a no-op rather than an error."""
        self.assertEqual(mc.mcolon([], 10).size, 0)
        self.assertEqual(mc.mcolon(5, []).size, 0)

    def test_mcolon_descending_range_is_empty(self):
        """sizeDist.m:1036/:1169 -- an event that ends before the first one
        begins yields an empty loop, leaving eIndex == [] so that
        auto_reject([])='R' is a no-op."""
        self.assertEqual(mc.mcolon(5, 3).size, 0)

    def test_sizeDist_98_midnight_rollover_only_applies_once(self):
        """sizeDist.m:98-99.

        find() returns ALL decrease points but the colon uses only the first,
        so a flight that crosses the rollover condition twice gets the +240000
        applied as one contiguous block from the FIRST decrease onward.  The
        second rollover is never separately corrected.
        """
        t = np.array([230000, 235959, 1000, 2000, 235000, 500], dtype=np.int64)
        idx = mc.mcolon(mc.mfind(np.diff(t) < 0) + 1, len(t))
        out = t.copy()
        out[mc.to0(idx)] += 240000
        np.testing.assert_array_equal(
            out, [230000, 235959, 241000, 242000, 475000, 240500])
        # 475000 is the artefact: that sample got the blanket +240000 despite
        # not needing it, and the genuine second rollover got no separate fix.

    def test_sizeDist_1036_reacceptance_scans_only_first_event(self):
        """sizeDist.m:1036 -- for iEvent = find(rBegin):find(rEnd).

        Two shattering events are marked, but only the span from the first
        begin to the first end is scanned; the second event is skipped.
        """
        r_begin = np.array([0, 1, 0, 0, 0, 1, 0], dtype=bool)
        r_end = np.array([0, 0, 1, 0, 0, 0, 1], dtype=bool)
        scanned = mc.mcolon(mc.mfind(r_begin), mc.mfind(r_end))
        np.testing.assert_array_equal(scanned, [2, 3])
        self.assertNotIn(6, scanned.tolist())   # the second event, skipped

    @needs_v314_engine
    def test_imgProc_577_particle_num_modulus_is_66536(self):
        """imgProc_sm.m:577 -- mod(kk, 66536).

        Almost certainly a typo for 65536 (2^16), written to the particle_num
        variable declared at imgProc_sm.m:291.  Preserved verbatim: changing it
        would change output.
        """
        # Read from the port, not restated here: with a local literal this test
        # stayed green when imgproc's constant was mutated to 65536 (2026-09-27).
        from arrayprobe import imgproc
        modulus = imgproc.PARTICLE_NUM_MODULUS
        self.assertEqual(modulus, 66536)
        self.assertNotEqual(modulus, 65536)
        self.assertEqual(65600 % modulus, 65600)
        self.assertEqual(66536 % modulus, 0)

    def test_sizeDist_882_int16_diameter_collapses_to_zero(self):
        """sizeDist.m:882-890 with the 2DS diodesize of 0.010.

        image_length is int16 (declared 'short' at imgProc_sm.m:295,299), so
        the multiply stays int16 and almost every particle diameter rounds to
        zero.  NumPy's float64 would silently fix this.
        """
        im_length = np.array([10, 37, 49, 50, 51, 149, 150], dtype=np.int16)
        diam = mc.mmul(im_length, 0.010)
        np.testing.assert_array_equal(diam, [0, 0, 0, 1, 1, 1, 2])
        self.assertEqual(np.asarray(diam).dtype, np.int16)

    def test_sizeDist_888_method4_escapes_collapse_but_saturates(self):
        """sizeDist.m:888 -- sqrt(im_width.^2 + im_length.^2) * diodesize.

        Because sqrt promotes to double (Octave-verified), d_choice 4 does NOT
        collapse to integer zeros.  It instead carries int16 saturation inside
        the radicand, which bites once a dimension exceeds 181 diodes.
        """
        w = np.int16(200)
        h = np.int16(200)
        radicand = mc.madd(mc.mpow(w, 2), mc.mpow(h, 2))
        self.assertEqual(radicand, 32767)                  # saturated, not 80000
        out = mc.mmul(mc.msqrt(radicand), 0.010)
        self.assertEqual(np.asarray(out).dtype, np.float64)   # stays double
        self.assertAlmostEqual(float(out), np.sqrt(32767) * 0.010, places=12)

    def test_sizeDist_984_area_ratio_inherits_the_integer_type(self):
        """sizeDist.m:984 -- area ./ (pi/4 .* diameter.^2) with an int16
        diameter yields int16, which then drives auto_reject at :985."""
        diam = np.int16(3)
        ratio = mc.mdiv(2.0, mc.mmul(np.pi / 4.0, mc.mpow(diam, 2)))
        self.assertEqual(np.asarray(ratio).dtype, np.int16)


if __name__ == "__main__":
    unittest.main(verbosity=2)
