# SPDX-License-Identifier: BSD-3-Clause
"""Interarrival remainder (author-directed): the contour plot's data, the ``.mat`` dump, and the
two thresholds ``IntArrAnalysis_time.m`` computes but never writes -- all opt-in, default OFF.

``src/arrayprobe/intarr_plots.py`` (matplotlib) has its own test file,
``test_intarr_plots.py``; this one covers everything that stays in
:mod:`arrayprobe.intarr_analysis` (numpy only).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe import intarr_analysis
from arrayprobe.intarr_analysis import (
    CONTOUR_BINS,
    HIST_BINS,
    analyse,
    contour_data,
    contour_time_axis,
    expand_tau_per_particle,
    overlay_time_axis,
    write_extra_thresholds_sidecar,
    write_mat_workspace,
)

try:  # scipy is an *extra* (pip install "arrayprobe[extra]"), not a core dependency:
    import scipy  # noqa: F401   the fit and the .mat dump both need it.
    _HAS_SCIPY = True
except ImportError:                     # pragma: no cover - depends on the env
    _HAS_SCIPY = False


def setUpModule():
    """Same reasoning as test_intarr_analysis.py's own setUpModule: skip cleanly, don't error,
    when the optional scipy extra is absent."""
    if not _HAS_SCIPY:
        raise unittest.SkipTest(
            "scipy is not installed; it is an extra (pip install \"arrayprobe[extra]\") "
            "and the interarrival fits/.mat dump need it")


_B8_GOLDEN = Path(__file__).parent / "data" / "intarr_b8_time_octave_golden.json"


def _deterministic_tau(centres, h, width, beta0=None):
    """A stand-in for ``fit_bimodal_intarr`` that is a pure function of its inputs.

    The byte-identity claim below is about the ``collect_histograms`` flag, not about the
    fit: ``analyse()``'s real fit is NOT bit-reproducible call to call on a degenerate block
    (see ``FitReproducibilityIsMeasuredNotAssumed``), so comparing two real fits would test
    scipy's allocation history, not this module. Differs per block (through ``h.sum()``),
    never NaN, and keeps ``block_thresholds``' ``between.any()`` branch live.
    """
    return np.array([2.0e-3, 1.5e-6, 0.4]) * (1 + 1e-3 * (float(np.asarray(h).sum()) % 7))


def _assert_flag_adds_only_hist2dc(before, after, *, expect_hist2dc):
    """The one comparison both byte-identity tests and their mutation test share."""
    base_keys = {"threshold", "threshold_ww", "threshold_ak", "tau",
                 "block_starts", "population_size"}
    if set(before.keys()) != base_keys:
        raise AssertionError(f"default return changed: {sorted(before.keys())}")
    extra = set(after.keys()) - set(before.keys())
    if extra != ({"hist2dc"} if expect_hist2dc else set()):
        raise AssertionError(f"unexpected keys added: {sorted(extra)}")
    for key in before:
        np.testing.assert_array_equal(before[key], after[key], err_msg=key)


class ByteIdentityDefaults(unittest.TestCase):
    """The stage's own condition: every new option defaults OFF, and OFF must leave every existing
    output byte-for-byte what it was before this stage's remainder was ported.

    The fit is stubbed (``_deterministic_tau``) so that this is a statement about the flag's
    code path (``intarr_analysis.py:201-207``) and nothing else -- with the real fit, two
    identical calls can differ at 1e-14 on a degenerate block, which is a property of the
    fit and is tested as such in ``FitReproducibilityIsMeasuredNotAssumed``.
    """

    def setUp(self):
        patcher = mock.patch.object(intarr_analysis, "fit_bimodal_intarr", _deterministic_tau)
        patcher.start()
        self.addCleanup(patcher.stop)
        rng = np.random.RandomState(20260913)
        self.arr = np.concatenate([rng.exponential(2e-6, 200), rng.exponential(1e-2, 200)])
        self.times = np.arange(400, dtype=float)

    def test_analyse_default_return_is_unaffected_by_the_new_flag(self):
        before = analyse(self.arr, self.times, n_blocks=4)
        after_explicit_false = analyse(self.arr, self.times, n_blocks=4, collect_histograms=False)
        _assert_flag_adds_only_hist2dc(before, after_explicit_false, expect_hist2dc=False)

    def test_opting_in_adds_exactly_one_key_and_changes_no_existing_value(self):
        before = analyse(self.arr, self.times, n_blocks=4)
        with_hist = analyse(self.arr, self.times, n_blocks=4, collect_histograms=True)
        _assert_flag_adds_only_hist2dc(before, with_hist, expect_hist2dc=True)
        self.assertEqual(with_hist["hist2dc"].shape,
                         (with_hist["block_starts"].size, len(HIST_BINS) - 1))

    def test_the_stub_is_really_in_place(self):
        """A patch on the wrong name would leave the real fit running and the two tests above
        testing scipy again -- so assert the stub is what ``analyse`` reaches."""
        out = analyse(self.arr, self.times, n_blocks=4)
        tau3 = out["tau"][:, 2]
        self.assertTrue(np.all((tau3 >= 0.4) & (tau3 <= 0.4 * 1.006)), tau3)  # the stub's range
        self.assertFalse(np.any(tau3 == 1.0), "the real fit gives tau3 == 1.0 on block 2")

    def test_the_byte_identity_guard_fires_on_a_one_ulp_change(self):
        """Mutation test: the comparison must fail on a one-ulp change to an existing value
        and on an unexpected extra key -- otherwise the two tests above guard nothing."""
        before = analyse(self.arr, self.times, n_blocks=4)
        moved = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in before.items()}
        moved["threshold"][100] = np.nextafter(moved["threshold"][100], np.inf)
        with self.assertRaises(AssertionError):
            _assert_flag_adds_only_hist2dc(before, moved, expect_hist2dc=False)
        leaked = dict(before)
        leaked["hist2dc"] = np.zeros((1, 1))
        with self.assertRaises(AssertionError):
            _assert_flag_adds_only_hist2dc(before, leaked, expect_hist2dc=False)

    def test_write_threshold_file_took_no_new_parameters(self):
        """The netCDF writer itself was not touched at all by this stage's remainder -- two
        identical calls still produce byte-identical files, same as before."""
        from arrayprobe.intarr_analysis import write_threshold_file

        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a.cdf"
            p2 = Path(tmp) / "b.cdf"
            kwargs = dict(probename="2DS", flight_date="20160906",
                         data_source="base....cdf", population_size=100,
                         creation_time="2000/01/01 00:00:00")
            write_threshold_file(str(p1), [64403.0, 64404.0], [1e-6, 2e-6], **kwargs)
            write_threshold_file(str(p2), [64403.0, 64404.0], [1e-6, 2e-6], **kwargs)
            self.assertEqual(p1.read_bytes(), p2.read_bytes())


class FitReproducibilityIsMeasuredNotAssumed(unittest.TestCase):
    """``analyse()``'s real fit is NOT bit-reproducible call to call on a degenerate block, and
    this test says so with the measured numbers rather than hiding it behind a stub.

    Measured 2026-09-13 (numpy 2.5.2, scipy 1.16.2, dispatch X86_V3): on this seed, block 2
    (particles 100-199) converges to ``tau3 == 1.0`` exactly, so population 1's weight
    ``1 - tau3`` is 0 and ``tau1`` is unconstrained by the data; two identical calls in one
    process then returned ``tau1`` differing by 6e-13 relative and ``tau2`` by 1.2e-14, in
    exactly two variants whose choice depends on what was allocated before (the same script
    gives four identical results in a fresh process). ``np.geterr()``, the warnings filters
    and the MSVC FP control word were constant across the flip. Blocks 1, 3 and 4 never
    differ. This is a property of an ill-posed fit -- MATLAB's ``nlinfit`` has no oracle here
    and would be equally ill-posed -- not a preserved bug and not something the port may
    "fix" by changing the algorithm. Tolerance 1e-11 is 16x the measured spread.
    """

    def test_a_degenerate_block_reproduces_to_1e_11_not_bitwise(self):
        rng = np.random.RandomState(20260913)
        arr = np.concatenate([rng.exponential(2e-6, 200), rng.exponential(1e-2, 200)])
        times = np.arange(400, dtype=float)
        first = analyse(arr, times, n_blocks=4)
        second = analyse(arr, times, n_blocks=4)
        self.assertEqual(first["tau"][1][2], 1.0,
                         "block 2 is expected to be degenerate (tau3 == 1.0); if this changed, "
                         "the docstring's measurement is stale -- re-measure before editing")
        np.testing.assert_allclose(second["tau"], first["tau"], rtol=1e-11, atol=0)
        np.testing.assert_allclose(second["threshold"], first["threshold"], rtol=1e-11, atol=0)
        for key in ("threshold_ww", "threshold_ak", "block_starts"):
            np.testing.assert_array_equal(second[key], first[key])


class ContourDataTest(unittest.TestCase):
    """``:220-236``."""

    def test_shape_matches_the_block_count_and_contour_bin_count(self):
        arr = np.full(10, 1e-6)
        times = np.arange(10, dtype=float) + 100.0
        dates = np.full(10, 20160920.0)
        hist, new_time, new_date = contour_data(arr, times, dates, 4)
        self.assertEqual(hist.shape, (3, len(CONTOUR_BINS) - 1))
        self.assertEqual(new_time.size, 3)
        self.assertEqual(new_date.size, 3)

    def test_last_block_time_and_date_are_overwritten_by_the_final_particle(self):
        """``:235-236`` -- a fixup specific to the LAST block, not the others."""
        arr = np.full(10, 1e-6)
        times = np.arange(10, dtype=float) + 100.0
        dates = np.concatenate([np.full(9, 20160920.0), [20160921.0]])
        hist, new_time, new_date = contour_data(arr, times, dates, 4)
        self.assertEqual(new_time[0], times[0], "block starts keep their own start time")
        self.assertEqual(new_time[-1], times[-1], ":235 overwrites only the last block")
        self.assertEqual(new_date[-1], dates[-1], ":236 overwrites only the last block")

    def test_rejects_empty_or_zero_size(self):
        with self.assertRaises(ValueError):
            contour_data([], [], [], 4)
        with self.assertRaises(ValueError):
            contour_data([1.0], [1.0], [1.0], 0)


class ExpandTauPerParticleTest(unittest.TestCase):
    """``:162-164``'s ``tau_all(j,:) = tau_std``."""

    def test_broadcasts_each_blocks_tau_to_every_particle_in_it(self):
        tau_blocks = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        out = expand_tau_per_particle(tau_blocks, block_starts=[0, 3], population_size=3, n=6)
        np.testing.assert_array_equal(out[:3], np.tile([1.0, 2.0, 3.0], (3, 1)))
        np.testing.assert_array_equal(out[3:], np.tile([4.0, 5.0, 6.0], (3, 1)))

    def test_a_nan_block_broadcasts_nan_not_a_gap(self):
        """The inner `for j` loop in the source runs unconditionally -- a failed fit's NaN row
        reaches every particle in its block exactly like a successful one's real tau does."""
        tau_blocks = np.array([[np.nan, np.nan, np.nan], [1.0, 2.0, 0.5]])
        out = expand_tau_per_particle(tau_blocks, block_starts=[0, 2], population_size=2, n=4)
        self.assertTrue(np.isnan(out[:2]).all())
        np.testing.assert_array_equal(out[2:], np.tile([1.0, 2.0, 0.5], (2, 1)))


class B8AxisAgainstOctave(unittest.TestCase):
    """``overlay_time_axis``/``contour_time_axis`` against a real Octave run of
    ``IntArrAnalysis_time.m:243-250``/``:258-269`` -- not a hand-transcription check, a measured
    one (``octave_oracle/intarr_b8_time_bank.py``, ``intarr_b8_time_oracle.m``)."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(_B8_GOLDEN.read_text(encoding="utf-8"))

    def _times_and_dates(self, case):
        times = np.asarray(case["timehhmmss"], dtype=float)
        dates = np.full(times.size, case["date"], dtype=float)
        return times, dates

    def test_overlay_time_axis_reproduces_b8s_nan_pattern_exactly(self):
        case = self.doc["mixed_crosses_10am"]
        times, dates = self._times_and_dates(case)
        got = overlay_time_axis(times, dates)
        got_is_nan = np.isnan(got).tolist()
        expected_is_nan = [v is None for v in case["octave_time_axis"]]
        self.assertEqual(got_is_nan, expected_is_nan,
                         "the NaN pattern must match Octave's real num2str/str2double run")

    def test_overlay_time_axis_non_nan_values_match_octave(self):
        case = self.doc["mixed_crosses_10am"]
        times, dates = self._times_and_dates(case)
        got = overlay_time_axis(times, dates)
        for g, e in zip(got, case["octave_time_axis"], strict=True):
            if e is None:
                self.assertTrue(np.isnan(g))
            else:
                self.assertAlmostEqual(g, e, places=6)

    def test_overlay_time_axis_has_no_nan_when_nothing_crosses_10am(self):
        """B8's own writeup: 'files entirely before 10:00 are unaffected'."""
        case = self.doc["control_all_before_10am"]
        times, dates = self._times_and_dates(case)
        got = overlay_time_axis(times, dates)
        self.assertFalse(np.isnan(got).any())
        for g, e in zip(got, case["octave_time_axis"], strict=True):
            self.assertAlmostEqual(g, e, places=6)

    def test_fix_b8_matches_octaves_own_non_bugged_formula(self):
        """``fix_b8=True`` recovers the real value -- checked against Octave's :258-269 formula,
        which (unlike :243-250) already gets this case right."""
        case = self.doc["mixed_crosses_10am"]
        times, dates = self._times_and_dates(case)
        fixed = overlay_time_axis(times, dates, fix_b8=True)
        for g, e in zip(fixed, case["octave_x_axis"], strict=True):
            self.assertAlmostEqual(g, e, places=6)
        self.assertFalse(np.isnan(fixed).any(), "the fix must remove every NaN gap")

    def test_contour_time_axis_is_not_b8_affected(self):
        case = self.doc["mixed_crosses_10am"]
        times, dates = self._times_and_dates(case)
        got = contour_time_axis(times, dates)
        self.assertFalse(np.isnan(got).any(), ":258-269 is a different, width-aware formula")
        for g, e in zip(got, case["octave_x_axis"], strict=True):
            self.assertAlmostEqual(g, e, places=6)

    def test_contour_time_axis_matches_octave_on_the_control_case_too(self):
        case = self.doc["control_all_before_10am"]
        times, dates = self._times_and_dates(case)
        got = contour_time_axis(times, dates)
        for g, e in zip(got, case["octave_x_axis"], strict=True):
            self.assertAlmostEqual(g, e, places=6)

    def test_mismatched_shapes_raise(self):
        with self.assertRaises(ValueError):
            overlay_time_axis([1.0, 2.0], [1.0])
        with self.assertRaises(ValueError):
            contour_time_axis([1.0, 2.0], [1.0])


class ExtraThresholdsSidecarTest(unittest.TestCase):
    """Opt-in persistence of the two unwritten thresholds -- a JSON sidecar, never a netCDF file."""

    def test_round_trips_and_is_not_a_netcdf_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2DS_extraThresholds_test.json"
            write_extra_thresholds_sidecar(
                str(path), [64403.0, 64404.0], [1.0e-6, 2.0e-6], [1.5e-6, 2.5e-6],
                threshold_ak=[1.2e-6, 2.2e-6])
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"CDF"), "must not be a netCDF3 file (magic 'CDF')")
            doc = json.loads(raw.decode("utf-8"))
            self.assertEqual(doc["particle_time"], [64403.0, 64404.0])
            self.assertEqual(doc["threshold"], [1.0e-6, 2.0e-6])
            self.assertEqual(doc["threshold_ww"], [1.5e-6, 2.5e-6])
            self.assertEqual(doc["threshold_ak"], [1.2e-6, 2.2e-6])

    def test_threshold_ak_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_ak.json"
            write_extra_thresholds_sidecar(str(path), [1.0], [2e-6], [3e-6])
            doc = json.loads(Path(path).read_text())
            self.assertNotIn("threshold_ak", doc)

    def test_mismatched_shapes_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            with self.assertRaises(ValueError):
                write_extra_thresholds_sidecar(str(path), [1.0, 2.0], [1e-6], [1e-6, 2e-6])


class MatWorkspaceDumpTest(unittest.TestCase):
    """``:331``'s bare ``save(...)`` -- a real scipy.io round trip, not just "it writes a file"."""

    def _write(self, tmp, n_blocks=3):
        rng = np.random.RandomState(20260913)
        gaps = np.concatenate([rng.exponential(2e-6, 150), rng.exponential(1e-2, 150)])
        seconds = np.cumsum(gaps)
        times = np.floor(np.linspace(63628, 235959, seconds.size))
        dates = np.full(seconds.size, 20160920.0)
        dmax = rng.uniform(0.1, 1.0, seconds.size)
        path = Path(tmp) / "2DS_IntArrAnalysis.20160920_000000_230000.mat"
        write_mat_workspace(str(path), timehhmmss=times, date=dates, time_in_seconds=seconds,
                            dmax=dmax, probe_name="2DS", date_string="20160920",
                            infile="base160920063628.H_1.cdf", n_blocks=n_blocks)
        return path, times, dates, seconds, dmax

    def test_round_trips_every_named_variable_with_matlab_shapes(self):
        import scipy.io

        with tempfile.TemporaryDirectory() as tmp:
            path, times, dates, seconds, dmax = self._write(tmp)
            data = scipy.io.loadmat(str(path))

            expected_keys = {
                "hist2dc", "NEWtime2dc", "NEWdate2dc", "threshhold", "threshhold_ww",
                "threshhold_ak", "tau_all", "hist2dc_contour", "histsum", "x", "time",
                "bins", "binsCenter", "width", "num_particles", "numparticles",
                "timehhmmss", "date", "int_arr", "intarr", "Dmax", "n",
                "dateString", "probeName", "infile",
            }
            for key in expected_keys:
                self.assertIn(key, data, f"{key} missing from the .mat dump")

            # column vectors, matching the source's own Nx1 shapes
            self.assertEqual(data["timehhmmss"].shape, (times.size, 1))
            self.assertEqual(data["date"].shape, (dates.size, 1))
            self.assertEqual(data["int_arr"].shape, (seconds.size, 1))
            self.assertEqual(data["intarr"].shape, (seconds.size, 1))
            self.assertEqual(data["Dmax"].shape, (dmax.size, 1))
            self.assertEqual(data["x"].shape[1], 1)

            # row vectors
            self.assertEqual(data["NEWtime2dc"].shape[0], 1)
            self.assertEqual(data["NEWdate2dc"].shape[0], 1)
            self.assertEqual(data["bins"].shape, (1, len(CONTOUR_BINS)))
            self.assertEqual(data["binsCenter"].shape, (1, len(CONTOUR_BINS) - 1))
            self.assertEqual(data["time"].shape[0], 1)
            self.assertEqual(data["time"].shape[1], times.size)

            # matrices: one row per block
            n_blocks_written = data["NEWtime2dc"].shape[1]
            n_contour_bins = len(CONTOUR_BINS) - 1
            self.assertEqual(data["hist2dc"].shape[0], n_blocks_written)
            self.assertEqual(data["hist2dc_contour"].shape, (n_blocks_written, n_contour_bins))
            self.assertEqual(data["histsum"].shape, data["hist2dc_contour"].shape)
            self.assertEqual(data["tau_all"].shape, (times.size, 3))

            # scalars round-trip as 1x1
            self.assertEqual(data["num_particles"].shape, (1, 1))
            self.assertEqual(float(data["num_particles"][0, 0]), float(data["numparticles"][0, 0]))

    def test_time_axis_reproduces_b8_inside_the_dump(self):
        """The dump's own `time` variable is :func:`overlay_time_axis`'s default (buggy) output --
        the source's own workspace would contain the same NaNs, not a cleaned-up version."""
        import scipy.io

        with tempfile.TemporaryDirectory() as tmp:
            path, times, dates, seconds, dmax = self._write(tmp)
            data = scipy.io.loadmat(str(path))
            time_row = data["time"][0]
            # this fixture's times span 06:36:28 to 23:59:59, i.e. crosses 10:00:00
            pre_10am = times < 100000
            self.assertTrue(pre_10am.any())
            self.assertTrue(np.isnan(time_row[pre_10am]).any(),
                            "the .mat dump's own `time` must show B8's NaN gaps by default")

    def test_excluded_variables_documented_as_scratch_are_absent(self):
        import scipy.io

        with tempfile.TemporaryDirectory() as tmp:
            path, *_ = self._write(tmp)
            data = scipy.io.loadmat(str(path))
            for scratch in ("bimodalfit", "ncid", "file", "y", "k", "indicies", "arr", "h"):
                self.assertNotIn(scratch, data)


if __name__ == "__main__":
    unittest.main()
