# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for ``export_ascii.py``'s own surprises and refusals -- the
GDL-golden comparison lives in ``test_soda2_export_ascii_gdl.py``."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.export_ascii import (
    MinsizeOutOfRange,
    OneD2DHousekeepingNotPorted,
    compute_bulk_simple,
    interpol,
    meandiam,
    mmdiam,
    mvdiam,
    soda2_export_ascii,
    unnormalize,
)
from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d

ENDBINS = [50.0, 100.0, 150.0, 200.0, 300.0, 400.0, 600.0, 800.0, 1000.0]
NBINS = len(ENDBINS) - 1
MIDBINS = [(ENDBINS[i] + ENDBINS[i + 1]) / 2.0 for i in range(NBINS)]
CONC_ROW = [100.0, 500.0, 800.0, 600.0, 300.0, 100.0, 50.0, 10.0]
SPEC_ROW = [10.0, 50.0, 80.0, 60.0, 30.0, 10.0, 5.0, 1.0]


class _Data:
    pass


def _make_data(conc_rows, spec_rows=None, time_vals=None, *, water=0, res=10.0,
                probetype="2DS"):
    d = _Data()
    d.op = dict(
        probetype=probetype, probeid="H", project="ORACLES", date="20160906",
        fn="raw.2DS", smethod="xsize", water=water, res=res,
        endbins=np.array(ENDBINS, dtype=np.float32), shortname="2DS",
        starttime=0.0, stoptime=10.0, rate=1.0, inttime_reject=1,
        dofconst=8.12, customdof=0.0,
    )
    n = len(conc_rows)
    d.time = np.array(time_vals if time_vals is not None else [float(i) + 0.5 for i in range(n)])
    d.conc1d = np.array(conc_rows, dtype=np.float32)
    d.spec1d = np.array(spec_rows if spec_rows is not None else [SPEC_ROW] * n, dtype=np.float32)
    d.midbins = np.array(MIDBINS, dtype=np.float32)
    d.sa = np.full(NBINS, 1e-4, dtype=np.float32)
    d.date_processed = "2026-09-14T00:00:00"
    return d


class InterpolExtrapolates(unittest.TestCase):
    def test_left_extrapolation_uses_the_first_segments_slope(self):
        # x=[0,1,2], v=[10,20,30] -- slope 10/unit; xout=-1 should extrapolate to 0.
        self.assertAlmostEqual(interpol([10, 20, 30], [0, 1, 2], -1.0), 0.0)

    def test_right_extrapolation_uses_the_last_segments_slope(self):
        self.assertAlmostEqual(interpol([10, 20, 30], [0, 1, 2], 3.0), 40.0)

    def test_numpy_interp_would_have_clamped_here_this_does_not(self):
        # A regression guard against reintroducing `np.interp` (which clamps).
        self.assertNotAlmostEqual(interpol([10, 20, 30], [0, 1, 2], 3.0),
                                   float(np.interp(3.0, [0, 1, 2], [10, 20, 30])))


class UnnormalizeMmdiamMvdiamMeandiam(unittest.TestCase):
    def test_unnormalize_matches_binwidth_times_1e6_scaling(self):
        endbins = np.array([0.0, 10.0, 30.0])
        spectra = np.array([[2.0, 3.0]])
        got = unnormalize(spectra, endbins)
        np.testing.assert_array_equal(got, [[2.0 * 10 / 1e6, 3.0 * 20 / 1e6]])

    def test_unnormalize_keeps_float_spectra_float(self):
        """``spec_un = spectra*0.0`` (`:7`) and the FLOAT literal ``1.0e6``
        keep a FLOAT spectrum FLOAT -- the port used to return float64."""
        endbins = np.array([0.0, 10.0, 30.0], dtype=np.float32)
        spectra = np.array([[2.0, 3.0]], dtype=np.float32)
        got = unnormalize(spectra, endbins)
        self.assertEqual(got.dtype, np.float32)
        want = spectra * np.array([10.0, 20.0], dtype=np.float32) / np.float32(1.0e6)
        np.testing.assert_array_equal(got, want)

    def test_mmdiam_zero_mass_row_is_null(self):
        result = mmdiam(np.zeros((1, 3)), [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(result[0], 0.0)

    def test_mmdiam_nan_keyword_gives_nan_for_zero_mass(self):
        result = mmdiam(np.zeros((1, 3)), [0.0, 1.0, 2.0, 3.0], nan=True)
        self.assertTrue(np.isnan(result[0]))

    def test_mvdiam_midbins_is_the_ordinary_midpoint_average(self):
        # mvdiam.pro:13's `(endbins[1:*]+endbins)/2.0` (different-length
        # arrays truncated to the smaller size by IDL) is algebraically the
        # ordinary consecutive-midpoint formula; a zero-concentration row
        # gives tvolume==0 -> nullvalue, independent of the midpoint values,
        # so this only needs to run without error and return 0.
        result = mvdiam(np.zeros((1, 3)), [0.0, 10.0, 30.0, 60.0])
        self.assertEqual(result[0], 0.0)

    def test_meandiam_rejects_endbins_length_by_the_ported_guard(self):
        # meandiam.pro:16's `stop` guard -- passing endbins (n+1) instead of
        # midbins (n) must raise, matching the source's own defensive check.
        with self.assertRaises(ValueError):
            meandiam(np.ones((1, 3)), midbins=[0.0, 1.0, 2.0, 3.0])

    def test_meandiam_minimum_nulls_low_total_rows(self):
        conc = np.array([[0.01, 0.01], [10.0, 10.0]])
        result = meandiam(conc, midbins=[1.0, 2.0], minimum=1.0, nan=True)
        self.assertTrue(np.isnan(result[0]))
        self.assertFalse(np.isnan(result[1]))


class ComputeBulkSimpleWaterSwitch(unittest.TestCase):
    def test_water_coefficient_switch_replaces_mass_with_mass_lwc(self):
        # `:46`: acoeff > 0.52 and bcoeff == 3.0 silently switches to the
        # water mass-diameter relation -- read-only finding S<TBD>-f.
        conc1d = np.array([CONC_ROW], dtype=np.float32)
        endbins = np.array(ENDBINS, dtype=np.float32)
        default = compute_bulk_simple(conc1d.copy(), endbins)
        switched = compute_bulk_simple(conc1d.copy(), endbins, acoeff=0.6, bcoeff=3.0)
        np.testing.assert_array_equal(switched["massparam"], switched["massparamlwc"])
        self.assertFalse(np.allclose(default["massparam"], default["massparamlwc"]))

    def test_ice_mass_never_exceeds_zero_point_nine_one_of_water_mass(self):
        conc1d = np.array([CONC_ROW], dtype=np.float32)
        endbins = np.array(ENDBINS, dtype=np.float32)
        bulk = compute_bulk_simple(conc1d, endbins)
        self.assertTrue(np.all(bulk["massparam"] <= bulk["massparamlwc"] * np.float32(0.91)))


class SodaExportAsciiRefusalsAndSurprises(unittest.TestCase):
    def test_1d2d_float_edge_fields_are_refused_by_name(self):
        data = _make_data([CONC_ROW], probetype="1D2D")
        data.house = {"dofnumreject": np.array([0]), "dofpercent": np.array([0]),
                      "leftreject": np.array([1.0]), "rightreject": np.array([0])}
        with self.assertRaises(OneD2DHousekeepingNotPorted):
            soda2_export_ascii(data, tempfile.mktemp(suffix=".txt"))

    def test_minsize_above_every_bin_edge_raises(self):
        data = _make_data([CONC_ROW] * 3)
        with self.assertRaises(MinsizeOutOfRange):
            soda2_export_ascii(data, tempfile.mktemp(suffix=".txt"), minsize=2000.0)

    def test_numbins_over_500_is_refused_not_silently_wrapped(self):
        n = 501
        endbins = np.linspace(0.0, 5000.0, n + 1).astype(np.float32)
        midbins = (endbins[:-1] + endbins[1:]) / 2.0
        data = _Data()
        data.op = dict(
            probetype="2DS", probeid="H", project="ORACLES", date="20160906",
            fn="raw.2DS", smethod="xsize", water=0, res=10.0, endbins=endbins,
            shortname="2DS", starttime=0.0, stoptime=10.0, rate=1.0,
            inttime_reject=1, dofconst=8.12, customdof=0.0,
        )
        data.time = np.array([0.5])
        data.conc1d = np.ones((1, n), dtype=np.float32)
        data.spec1d = np.ones((1, n), dtype=np.float32)
        data.midbins = midbins
        data.sa = np.full(n, 1e-4, dtype=np.float32)
        data.date_processed = "2026-09-14T00:00:00"
        with self.assertRaises(ValueError):
            soda2_export_ascii(data, tempfile.mktemp(suffix=".txt"))

    def test_the_export_mutates_the_callers_conc1d_array_in_place(self):
        """Surprise 2, GDL-confirmed (``nan_conc_side_effect``:
        finite_before=23, finite_after=24 for a 3x8 array): the caller's own
        ``data.conc1d`` is rewritten, not a private copy."""
        data = _make_data([[float("nan")] + CONC_ROW[1:]] + [CONC_ROW] * 2)
        caller_array = data.conc1d
        self.assertEqual(int(np.sum(np.isfinite(caller_array))), 23)
        soda2_export_ascii(data, tempfile.mktemp(suffix=".txt"))
        self.assertIs(data.conc1d, caller_array)
        self.assertEqual(int(np.sum(np.isfinite(caller_array))), 24)
        self.assertEqual(float(caller_array[0, 0]), 0.0)

    def test_a_and_b_default_to_compute_bulk_simples_own_values_when_unset(self):
        """Surprise 1: the header line prints the callee's own defaults
        (0.00294, 1.9) when the caller passes neither ``a`` nor ``b``."""
        data = _make_data([CONC_ROW] * 3)
        outfile = tempfile.mktemp(suffix=".txt")
        soda2_export_ascii(data, outfile)
        text = Path(outfile).read_text(encoding="utf-8")
        self.assertIn("a=  2.94e-03, b=1.90", text)


class WiredIntoProcessTwoD(unittest.TestCase):
    """``soda2_process_2d.pro:722-726`` -- ``op.asciipsdfile == 1`` writes
    the ``.txt`` via a real driver run, replacing the placeholder refusal
    the netCDF writer shipped."""

    DATA = Path(__file__).resolve().parent / "data"
    S2_FIXTURE = DATA / "s2_spec_raw_fixture"

    def _base_op(self, **overrides):
        op = dict(
            fn=str(self.S2_FIXTURE), date="20160906", starttime=24240.0,
            stoptime=24250.0, format="SPEC", subformat=0, probetype="2DS",
            res=10.0, endbins=[0.0, 50.0, 100.0, 200.0, 500.0],
            arendbins=[0.0, 0.5, 1.0], rate=1.0, smethod="xy", pth="",
            particlefile=0, inttime_reject=0, stuckbits=0, water=0,
            fixedtas=0.0, timeoffset=0.0, armwidth=6.3, numdiodes=128,
            greythresh=0, probeid="H", eawmethod="centerin",
            wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0,
            asciipsdfile=0, project="ORACLES", shortname="2DS",
            savfile=0,  # this test is about the `.txt` only
        )
        op.update(overrides)
        return op

    def test_asciipsdfile_writes_the_txt_alongside_the_returned_data(self):
        if not self.S2_FIXTURE.exists():
            self.skipTest("Tracked SPEC fixture is not distributed with the package")
        import tempfile as _tf
        outdir = _tf.mkdtemp()
        data = soda2_process_2d(self._base_op(asciipsdfile=1, outdir=outdir + "/"))
        self.assertIsInstance(data, ProcessData)
        written = list(Path(outdir).glob("*.txt"))
        self.assertEqual(len(written), 1, f"expected exactly one .txt, got {written}")


if __name__ == "__main__":
    unittest.main()
