# SPDX-License-Identifier: BSD-3-Clause
"""airspeed and size-dependent depth of field -- published depth of field (Gurganus & Lawson 2018; Baumgardner & Korolev 1997).

Equivalence (OFF is byte-identical to the engine), the A/B consequence on both demo references
(measured, not asserted from the arithmetic), the refusals, and a mutation that shows the A/B
check is not vacuous.
"""

from __future__ import annotations

import shutil
import sys as _sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_sys.path.insert(0, str(Path(__file__).resolve().parent))
import netCDF4
import numpy as np
from arrayprobe.sample_area import calc_sa_randombins

import _upstream  # noqa: E402
from arrayprobe_enhancements import published_dof as pd
from arrayprobe_enhancements.registry import REGISTRY, resolve

_REPO = Path(__file__).resolve().parents[2]
_DATA = _REPO / "tests" / "data"
_V314_SD = _DATA / "demo_flight_v314_sd.nc"
_V35_SD = _DATA / "demo_flight_v35_sd.nc"
_SODA2_SPECS = _upstream.source("soda2") / "soda2_probespecs.pro"
_ARMDST_2DS = 63.0   # sizeDist.m 2DS blocks; arrayprobe_uiops.sizedist_tables.probe_defaults
_TAS = 150.0         # inside G&L's 190 m/s envelope; supplied by the test


def _vars(path):
    with netCDF4.Dataset(path) as ds:
        out = {}
        for name, var in ds.variables.items():
            var.set_auto_mask(False)
            out[name] = np.asarray(var[:])
        return out


class Constants(unittest.TestCase):
    def test_the_published_constants(self):
        self.assertEqual((pd.GL2018_C, pd.GL2018_C_SIGMA), (8.0, 0.2))     # G&L p. 1534
        self.assertEqual(pd.GL2018_TAS_MAX_MS, 190.0)                        # G&L p. 1550
        self.assertEqual(pd.GL2018_FIT_DIAMETER_UM, (29.0, 67.0))            # G&L p. 1534
        self.assertEqual(pd.BK1997_DOF_MAX_MM, 61.0)                         # B&K p. 1228

    def test_the_2ds_wavelength_is_the_one_soda2_ships_for_the_2ds(self):
        """Two sides from two places: the module's constant vs. SODA-2's own probe table."""
        _upstream.require("soda2")
        lines = _SODA2_SPECS.read_text(encoding="latin-1").splitlines()
        block = "\n".join(lines[938:956])      # the '2D-S Horizontal Array' block, :939-:956
        self.assertIn("x.probename='2D-S Horizontal Array'", block)
        self.assertIn(f"x.wavelength={pd.SPEC_2DS_WAVELENGTH_UM}e-6", block)

    def test_the_engine_constant_is_read_from_the_matlab(self):
        _upstream.require("uiops314")
        src = (_upstream.source("uiops314") / "calc_sa_randombins.m").read_text(encoding="latin-1")
        self.assertIn("DOF =20.52*radius.^2*1000;", src)
        self.assertEqual(pd.ENGINE_PT2_COEFF_PER_MM, 20.52 * 1000)


class Equivalence(unittest.TestCase):
    """OFF -> exactly the engine."""

    def test_sample_area_off_is_the_engines_list(self):
        mids = [0.005 + 0.01 * i for i in range(128)]
        for probetype, armdst in ((2, 63.0), (2, 161.0), (0, 61.0), (1, 100.0)):
            for sa_method in (0, 1, 2):
                self.assertEqual(
                    pd.published_sample_area(mids, 10, armdst, 128, sa_method, probetype,
                                             probe="2DS"),
                    calc_sa_randombins(mids, 10, armdst, 128, sa_method, probetype))

    def test_engine_dof_is_what_calc_sa_randombins_multiplies(self):
        mids = np.array([0.005 + 0.01 * i for i in range(128)])
        sa = np.array(calc_sa_randombins(list(mids), 10, 63.0, 128, 0, 2))
        np.testing.assert_allclose(sa / (128 * 10e-3), pd.engine_dof_mm(mids, 63.0, 2),
                                   rtol=1e-14)

    def test_sd_file_off_is_byte_identical_on_both_demo_references(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for src in (_V314_SD, _V35_SD):
            dst = pd.corrected_sd_file(src, tmp / src.name, armdst=_ARMDST_2DS, tas=_TAS)
            a, b = _vars(src), _vars(dst)
            self.assertEqual(set(a), set(b))
            for name in a:
                self.assertEqual(a[name].tobytes(), b[name].tobytes(), name)

    def test_the_registry_leaves_it_off_until_a_config_names_it(self):
        """the 2026-09-16 cold-start usability audit supersedes the earlier opt-out default for this row. That default (author, 2026-09-15)
        flipped it ON by default under the then-current opt-out scheme; the cold-start
        usability audit measured that scheme applying ``published_dof`` -- which rescales
        the sd file's volume-normalised variables, so it moves numbers -- to a run whose
        config named only ``outoffocus``. Under opt-in there is no per-module ON default
        left to hold, so this row is reachable exactly by ``published_dof = true``. The
        module's own ``enabled=False`` keyword is unchanged (tested above)."""
        self.assertFalse(REGISTRY["published_dof"].default_on)
        for engine in ("3.1.4", "3.5"):
            self.assertFalse(resolve(None, engine=engine)["published_dof"])
            self.assertTrue(resolve({"published_dof": True}, engine=engine)["published_dof"])


class Consequence(unittest.TestCase):
    """A/B on the two demo references, recorded as a measurement (CORRECTIONS.md airspeed and size-dependent depth of field)."""

    #: 16 / (0.785e-3 * 20520): G&L's total width over the engine's, for an uncapped bin.
    RATIO = 2 * 8.0 / (0.785e-3 * 20.52e3)

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = {}
        for src in (_V314_SD, _V35_SD):
            cls.out[src.name] = pd.corrected_sd_file(
                src, cls.tmp / src.name, armdst=_ARMDST_2DS, tas=_TAS, enabled=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_uncapped_ratio(self):
        mids = np.array([0.01, 0.05, 0.1])
        np.testing.assert_allclose(pd.dof_ratio(mids, 63.0, probe="2DS", tas=_TAS),
                                   self.RATIO, rtol=1e-15)
        self.assertAlmostEqual(self.RATIO, 0.993283, places=6)

    def test_v314_demo_is_particle_free_so_only_sample_vol_moves(self):
        """Measured: both tracked demo sd references have ``count`` == 0 everywhere, so the
        concentration A/B is vacuous there; the 11 uncapped bins' sample_vol moves."""
        a, b = _vars(_V314_SD), _vars(self.out[_V314_SD.name])
        self.assertEqual(int(np.count_nonzero(a["count"])), 0)
        mid = a["bin_mid"]
        uncapped = pd.engine_dof_mm(mid, _ARMDST_2DS, 2) < _ARMDST_2DS
        self.assertEqual(int(uncapped.sum()), 11)                   # bin_mid <= 0.11 mm
        self.assertAlmostEqual(float(mid[uncapped].max()), 0.11, places=12)
        np.testing.assert_allclose(b["sample_vol"][:, uncapped] / a["sample_vol"][:, uncapped],
                                   self.RATIO, rtol=1e-13)
        self.assertEqual(a["sample_vol"][:, ~uncapped].tobytes(),
                         b["sample_vol"][:, ~uncapped].tobytes())

    @unittest.skipUnless((_DATA / "s4_sizedist_octave_golden.nc").exists(),
                         "s4_sizedist_octave_golden.nc is real-data derived and not distributed")
    def test_oracles_excerpt_two_populated_bins_gain_0_68_percent(self):
        """The non-vacuous A/B: ``s4_sizedist_octave_golden.nc`` (6 s of ORACLES 2D-S, the
        Octave-built v3.1.4 sd golden) has particles in bins 0, 1 (10, 20 um -- uncapped) and
        122 (capped). Measured: bins 0-1 x 1/0.993283, bin 122 byte-identical."""
        src = _DATA / "s4_sizedist_octave_golden.nc"
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        dst = pd.corrected_sd_file(src, tmp / "g.nc", armdst=_ARMDST_2DS, tas=_TAS,
                                   enabled=True)
        a, b = _vars(src), _vars(dst)
        populated = np.nonzero(np.nansum(a["count"], 0))[0]
        self.assertEqual(populated.tolist(), [0, 1, 122])
        mid = a["bin_mid"]
        uncapped = pd.engine_dof_mm(mid, _ARMDST_2DS, 2) < _ARMDST_2DS
        for name in ("conc_minR", "conc_AreaR", "mass", "massBL", "total_area"):
            with np.errstate(invalid="ignore", divide="ignore"):
                r = b[name] / a[name]
            finite = np.isfinite(r) & (a[name] != 0)
            np.testing.assert_allclose(r[:, uncapped][finite[:, uncapped]], 1 / self.RATIO,
                                       rtol=1e-13, err_msg=name)
            self.assertEqual(a[name][:, ~uncapped].tobytes(), b[name][:, ~uncapped].tobytes(),
                             name)
        np.testing.assert_allclose(b["sample_vol"][:, uncapped] / a["sample_vol"][:, uncapped],
                                   self.RATIO, rtol=1e-13)
        for name in ("count", "re", "ar", "Reject_ratio", "mean_perimeter", "bin_mid"):
            self.assertEqual(a[name].tobytes(), b[name].tobytes(), name)
        # n: the engine's own formula reproduces the stored value, then moves
        np.testing.assert_allclose(np.nansum(a["conc_minR"] * a["bin_dD"], 1) / 10, a["n"],
                                   rtol=1e-12)
        self.assertTrue(np.all(b["n"] >= a["n"]))
        self.assertEqual(int(np.sum(b["n"] > a["n"])), 2)
        conc_changed = np.nan_to_num(b["conc_minR"]) != np.nan_to_num(a["conc_minR"])
        self.assertEqual(sorted(set(np.nonzero(conc_changed)[1].tolist())), [0, 1])

    def test_v35_demo_moves_only_the_occupied_bins_below_the_arm_cap(self):
        """The v3.5 demo sd is sized on the 2D-S 128-bin ladder (10 um bins from 0.01 mm), so
        the 11 bins with 20520 r^2 < 63 mm (bin_mid <= 0.11 mm) are uncapped and the rest sit
        at armdst. Measured 2026-10-05 on the regenerated reference: particles occupy bin 4
        (50 um, minR sizing) and bin 2 (area-equivalent sizing), both uncapped, so exactly
        those bins move -- conc_minR, conc_AreaR, area, total_area, mass, massBL, habitsd,
        habitmsd, vt, Prec_rate, Calcd_area -- conc_minR and ``n`` by 1/0.993283; every capped
        bin and every other variable is byte-identical."""
        a, b = _vars(_V35_SD), _vars(self.out[_V35_SD.name])
        with netCDF4.Dataset(_V35_SD) as ds:
            dims = {name: var.dimensions for name, var in ds.variables.items()}
        mid = a["bin_mid"]
        self.assertEqual(mid.size, 128)
        self.assertAlmostEqual(float(mid[0]), 0.01, places=12)
        uncapped = pd.engine_dof_mm(mid, _ARMDST_2DS, 2) < _ARMDST_2DS
        self.assertEqual(int(uncapped.sum()), 11)                   # bin_mid <= 0.11 mm
        occupied = (np.nansum(a["conc_minR"], 0) != 0) | (np.nansum(a["conc_AreaR"], 0) != 0)
        self.assertTrue(occupied.any())                             # not particle-free
        capped = np.nonzero(~uncapped)[0]
        moved = np.zeros(mid.size, dtype=bool)
        binned = [n for n in a if "CIPcorrlen" in dims[n] and len(dims[n]) > 1]
        for name in binned:
            ax = dims[name].index("CIPcorrlen")
            diff = np.nan_to_num(a[name]) != np.nan_to_num(b[name])
            moved |= diff.any(axis=tuple(i for i in range(diff.ndim) if i != ax))
            self.assertEqual(np.take(a[name], capped, axis=ax).tobytes(),
                             np.take(b[name], capped, axis=ax).tobytes(), name)
        self.assertEqual(np.nonzero(moved)[0].tolist(),
                         np.nonzero(uncapped & occupied)[0].tolist())
        for name in ("conc_minR", "conc_AreaR", "mass"):
            self.assertNotEqual(a[name].tobytes(), b[name].tobytes(), name)
        hit = a["conc_minR"] != 0
        np.testing.assert_allclose(b["conc_minR"][hit] / a["conc_minR"][hit], 1 / self.RATIO,
                                   rtol=1e-13)
        np.testing.assert_allclose(b["n"] / a["n"], 1 / self.RATIO, rtol=1e-12)
        for name in a:
            if name not in binned and name != "n":
                self.assertEqual(a[name].tobytes(), b[name].tobytes(), name)

    def test_the_c_uncertainty_band(self):
        lo = pd.dof_ratio([0.01], 63.0, probe="2DS", tas=_TAS, c=8.0 - pd.GL2018_C_SIGMA)[0]
        hi = pd.dof_ratio([0.01], 63.0, probe="2DS", tas=_TAS, c=8.0 + pd.GL2018_C_SIGMA)[0]
        self.assertAlmostEqual(lo, 0.968451, places=6)
        self.assertAlmostEqual(hi, 1.018115, places=6)


class Refusals(unittest.TestCase):
    def test_probes_neither_paper_covers(self):
        for probe in ("HVPS", "CIP", "PIP", "2DC", "Fast2DC"):
            with self.assertRaises(pd.ProbeNotCovered) as caught:
                pd.dof_ratio([0.01], 100.0, probe=probe, tas=_TAS)
            self.assertIn(probe, str(caught.exception))

    def test_tas_above_the_envelope_and_missing_tas(self):
        with self.assertRaisesRegex(pd.ProbeNotCovered, "190"):
            pd.dof_ratio([0.01], 63.0, probe="2DS", tas=[150.0, 190.5])
        with self.assertRaises(pd.ProbeNotCovered):
            pd.dof_ratio([0.01], 63.0, probe="2DS", tas=[])
        with self.assertRaises(pd.ProbeNotCovered):
            pd.published_sample_area([0.01], 10, 63.0, 128, 0, 2, probe="2DS", tas=None,
                                     enabled=True)

    def test_a_refused_sd_file_writes_nothing(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        with self.assertRaises(pd.ProbeNotCovered):
            pd.corrected_sd_file(_V314_SD, tmp / "x.nc", armdst=63.0, tas=200.0, enabled=True)
        self.assertFalse((tmp / "x.nc").exists())


class BaumgardnerKorolevTables(unittest.TestCase):
    def test_only_tabulated_airspeeds(self):
        self.assertEqual(sorted(pd.BK1997_TABLE2_50PCT), list(range(20, 161, 20)))
        self.assertEqual(sorted(pd.BK1997_TABLE1_67PCT), list(range(20, 161, 20)))
        with self.assertRaisesRegex(pd.ProbeNotCovered, "no rule between rows"):
            pd.bk1997_dof_mm(100.0, 110, threshold=50)
        with self.assertRaises(ValueError):
            pd.bk1997_dof_mm(100.0, 100, threshold=60)

    def test_dof_falls_with_airspeed_as_fig5_shows(self):
        """A transcription check: a lost minus sign or a unit slip breaks monotonicity (e.g.
        Table 1's 80 m/s C0 read as -8.411 instead of 28.411 gives a negative DOF)."""
        for table, thr, diameters in ((pd.BK1997_TABLE2_50PCT, 50, (75, 100, 125)),
                                      (pd.BK1997_TABLE1_67PCT, 67, (100, 125))):
            for d in diameters:
                vals = []
                for v in sorted(table):
                    try:
                        vals.append(float(pd.bk1997_dof_mm(d, v, threshold=thr)))
                    except pd.ProbeNotCovered:     # above 61 mm at the slowest airspeeds
                        self.assertEqual(vals, [], (thr, d, v))
                self.assertGreaterEqual(len(vals), 4, (thr, d))
                self.assertEqual(vals, sorted(vals, reverse=True), (thr, d))

    def test_outside_61_mm_is_refused(self):
        with self.assertRaisesRegex(pd.ProbeNotCovered, "61"):
            pd.bk1997_dof_mm(150.0, 20, threshold=50)


class Mutation(unittest.TestCase):
    def test_the_ab_check_fails_when_the_correction_is_removed(self):
        """Patch the ratio to 1 (the enhancement doing nothing): the v3.1.4 A/B assertion that
        uncapped bins move must then fail -- so it is not vacuous."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        src = _V314_SD
        with mock.patch.object(pd, "dof_ratio", lambda mid, *a, **k: np.ones(len(mid))):
            dst = pd.corrected_sd_file(src, tmp / "m.nc", armdst=63.0, tas=_TAS, enabled=True)
        a, b = _vars(src), _vars(dst)
        # with the correction removed, the populated bins 0-1 no longer move, which is exactly
        # what test_oracles_excerpt_two_populated_bins_gain_0_68_percent asserts against
        self.assertEqual(a["conc_minR"][:, :2].tobytes(), b["conc_minR"][:, :2].tobytes())

    def test_half_width_mutation_is_caught(self):
        """If Eq. (1)'s ± were taken as the total width, the ratio would halve."""
        self.assertNotAlmostEqual(Consequence.RATIO / 2, 0.993283, places=2)
        np.testing.assert_allclose(pd.published_dof_mm([0.037], 63.0),
                                   2 * 8 * 0.0185 ** 2 / 0.785e-3, rtol=1e-15)


class PipelineAdapter(unittest.TestCase):
    def test_skips_by_name_without_a_tas_sidecar(self):
        from arrayprobe_enhancements import pipeline
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        outputs = pipeline._RunOutputs(out_dir=tmp, raw_stem="x", engine="3.5", image=None,
                                       proc=None, sd=_V35_SD, combined=None, tas_csv=None)
        with self.assertRaisesRegex(pipeline.ApplierSkip, "190 m/s"):
            pipeline._apply_published_dof(outputs)

    def test_applies_on_the_v314_demo_with_a_tas_sidecar(self):
        from arrayprobe_enhancements import pipeline
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        sd = tmp / "sd.x.nc"
        shutil.copyfile(_V314_SD, sd)
        tas_csv = tmp / "x.tas.csv"
        tas_csv.write_text("60640,150,0,0,0,0,0,0,0\n60641,151,0,0,0,0,0,0,0\n",
                           encoding="ascii")
        outputs = pipeline._RunOutputs(out_dir=tmp, raw_stem="x", engine="3.1.4", image=None,
                                       proc=None, sd=sd, combined=None, tas_csv=tas_csv)
        dst = pipeline._apply_published_dof(outputs)
        with netCDF4.Dataset(dst) as ds:
            self.assertIn("published_dof", ds.getncattr("enhancements_applied"))
        a, b = _vars(_V314_SD), _vars(dst)
        self.assertNotEqual(a["sample_vol"].tobytes(), b["sample_vol"].tobytes())


if __name__ == "__main__":
    unittest.main()
