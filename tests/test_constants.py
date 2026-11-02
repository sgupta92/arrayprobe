# SPDX-License-Identifier: BSD-3-Clause
"""Tests for ``arrayprobe.constants``.

The configuration tables are pure transcription, so the tests are pinned literals
plus the structural invariants that catch a transcription slip: every case has
``num_bins + 1`` bin edges, every bin ladder is strictly increasing, and the three
upstream defects are still defects.
"""

import unittest

import numpy as np

from arrayprobe import constants as C


class TestImgProcTable(unittest.TestCase):
    def test_all_seven_probes_present(self):
        """imgProc_sm.m:117-193 -- seven cases, and NO otherwise branch."""
        self.assertEqual(
            sorted(C.IMGPROC_CONFIG),
            ["2DC", "2DP", "2DS", "CIP", "Fast2DC", "HVPS", "PIP"],
        )

    def test_boundary_words(self):
        """imgProc_sm.m:119,139,158,187 -- 0xFF, 0xAA and 0xAAAA, and Fast2DC's
        boundary is THREE words while every other probe's is four or eight."""
        self.assertEqual(C.imgproc_config("2DC").boundary, (255,) * 4)
        self.assertEqual(C.imgproc_config("2DP").boundary, (255,) * 4)
        self.assertEqual(C.imgproc_config("CIP").boundary, (170,) * 8)
        self.assertEqual(C.imgproc_config("PIP").boundary, (170,) * 8)
        self.assertEqual(C.imgproc_config("HVPS").boundary, (43690,) * 8)
        self.assertEqual(C.imgproc_config("2DS").boundary, (43690,) * 8)
        self.assertEqual(C.imgproc_config("Fast2DC").boundary, (170, 170, 170))

    def test_boundarytime(self):
        """imgProc_sm.m:120,140,159 -- 85 for PMS, 0 for SPEC, NaN for DMT."""
        self.assertEqual(C.imgproc_config("2DC").boundarytime, 85.0)
        self.assertEqual(C.imgproc_config("2DS").boundarytime, 0.0)
        self.assertTrue(np.isnan(C.imgproc_config("CIP").boundarytime))
        self.assertTrue(np.isnan(C.imgproc_config("Fast2DC").boundarytime))

    def test_byteperslice(self):
        """imgProc_sm.m:196 -- byteperslice = diodenum/8."""
        self.assertEqual(C.imgproc_config("2DS").byteperslice, 16)
        self.assertEqual(C.imgproc_config("CIP").byteperslice, 8)
        self.assertEqual(C.imgproc_config("2DC").byteperslice, 4)

    def test_only_spec_probes_need_a_tas_file(self):
        """imgProc_sm.m:167-170,180-185 -- 2DS and HVPS read varargin{1}."""
        need = {p for p, cfg in C.IMGPROC_CONFIG.items() if cfg.needs_tas_file}
        self.assertEqual(need, {"2DS", "HVPS"})

    def test_unknown_probe_fails_because_there_is_no_otherwise(self):
        with self.assertRaises(C.MatlabUndefinedVariable) as ctx:
            C.imgproc_config("HVPS4")
        self.assertIn("no otherwise branch", str(ctx.exception).replace("and no ", "no "))


class TestSizeDistTable(unittest.TestCase):
    def test_seventeen_cases(self):
        """sizeDist.m:107-511 -- 2 PECAN + 4 GPM + 3 SOCRATES + 7 otherwise."""
        self.assertEqual(len(C.SIZEDIST_CONFIG), 16)
        by_project = {}
        for project, probe in C.SIZEDIST_CONFIG:
            by_project.setdefault(project, []).append(probe)
        self.assertEqual(sorted(by_project["PECAN"]), ["CIP", "PIP"])
        self.assertEqual(sorted(by_project["GPM"]), ["2DC", "2DS", "CIP", "HVPS"])
        self.assertEqual(sorted(by_project["SOCRATES"]), ["2DS", "Fast2DC", "PIP"])
        self.assertEqual(
            sorted(by_project["otherwise"]),
            ["2DC", "2DP", "2DS", "CIP", "F2DC", "HVPS", "PIP"],
        )

    def test_every_case_has_num_bins_plus_one_edges(self):
        """kk is a ladder of EDGES; binwidth = diff(kk) has num_bins entries."""
        for key, cfg in C.SIZEDIST_CONFIG.items():
            with self.subTest(case=key):
                self.assertEqual(cfg.kk.size, cfg.num_bins + 1)
                self.assertEqual(cfg.binwidth.size, cfg.num_bins)

    def test_every_ladder_is_strictly_increasing(self):
        for key, cfg in C.SIZEDIST_CONFIG.items():
            with self.subTest(case=key):
                self.assertTrue(np.all(np.diff(cfg.kk) > 0))

    def test_unknown_project_falls_through_to_otherwise(self):
        """sizeDist.m:339 -- ORACLES, IMPACTS, anything unnamed lands here."""
        oracles = C.sizedist_config("ORACLES", "2DS")
        self.assertEqual(oracles.project, "otherwise")
        self.assertEqual(oracles.num_bins, 128)
        self.assertEqual(oracles.diodesize, 0.010)

    def test_unknown_probe_in_a_branch_is_an_error(self):
        with self.assertRaises(C.MatlabUndefinedVariable):
            C.sizedist_config("SOCRATES", "HVPS")

    def test_pinned_values_2ds_otherwise(self):
        """sizeDist.m:365-390 -- the case an ORACLES run actually takes."""
        cfg = C.sizedist_config("ORACLES", "2DS")
        self.assertEqual(cfg.num_diodes, 128)
        self.assertEqual(cfg.armdst, 63.0)
        self.assertEqual(cfg.probetype, 2)
        self.assertEqual(cfg.tas_max, 170.0)
        self.assertFalse(cfg.apply_int_arr_thresh)
        self.assertEqual(cfg.default_int_arr_thresh, 4e-6)
        self.assertFalse(cfg.reaccpt_shatrs)
        self.assertAlmostEqual(cfg.res, 10.0)
        # kk = diodesize/2 : diodesize : (num_bins+0.6)*diodesize
        self.assertAlmostEqual(cfg.kk[0], 0.005)
        self.assertAlmostEqual(cfg.kk[1], 0.015)
        self.assertAlmostEqual(cfg.kk[-1], 1.285)

    def test_pinned_values_gpm_2ds(self):
        """sizeDist.m:179-196 -- a 22-bin ladder starting at 40 microns."""
        cfg = C.sizedist_config("GPM", "2DS")
        self.assertEqual(cfg.num_bins, 22)
        self.assertAlmostEqual(cfg.kk[0], 0.040)
        self.assertAlmostEqual(cfg.kk[-1], 2.000)
        self.assertEqual(cfg.default_int_arr_thresh, 1e-6)

    def test_pinned_values_hvps(self):
        """sizeDist.m:341-364 -- 28 bins out to 30 mm."""
        cfg = C.sizedist_config("ORACLES", "HVPS")
        self.assertEqual(cfg.num_bins, 28)
        self.assertAlmostEqual(cfg.kk[0], 0.200)
        self.assertAlmostEqual(cfg.kk[-1], 30.0)
        self.assertEqual(cfg.diodesize, 0.150)
        self.assertAlmostEqual(cfg.res, 150.0)

    def test_pip_colon_ladder_has_65_edges(self):
        """sizeDist.m:143,420 -- kk = 0.05:0.1:6.46 is 65 edges for 64 bins."""
        for project in ("PECAN", "ORACLES"):
            cfg = C.sizedist_config(project, "PIP")
            with self.subTest(project=project):
                self.assertEqual(cfg.kk.size, 65)
                self.assertAlmostEqual(cfg.kk[0], 0.05)
                self.assertAlmostEqual(cfg.kk[-1], 6.45)

    def test_2dp_ladder_is_the_shared_one_times_eight(self):
        """sizeDist.m:483 -- the only case with a `*8/1000` scaling."""
        cfg = C.sizedist_config("ORACLES", "2DP")
        self.assertAlmostEqual(cfg.kk[0], 0.4)
        self.assertAlmostEqual(cfg.kk[-1], 16.0)

    def test_socrates_2ds_has_the_small_reaccept_diameter(self):
        """sizeDist.m:273 -- 0.05 mm, an order of magnitude below every other
        case's 0.5 mm. Easy to mis-transcribe, so pinned."""
        self.assertEqual(C.sizedist_config("SOCRATES", "2DS").reaccpt_d, 0.05)
        self.assertEqual(C.sizedist_config("SOCRATES", "Fast2DC").reaccpt_d, 0.15)


class TestPreservedUpstreamDefects(unittest.TestCase):
    """Three upstream bugs, transcribed rather than repaired. These tests must
    FAIL if someone "fixes" the table."""

    def test_sizeDist_465_2DP_never_assigns_tasMax(self):
        """sizeDist.m:465-489 -- the 2DP case omits tasMax entirely, so MATLAB
        raises 'Undefined function or variable' at sizeDist.m:968. Defaulting it
        to a number here would turn a crash into silently wrong output."""
        cfg = C.sizedist_config("ORACLES", "2DP")
        self.assertIsNone(cfg.tas_max)
        with self.assertRaises(C.MatlabUndefinedVariable) as ctx:
            _ = cfg.tasMax
        self.assertIn("sizeDist.m:968", str(ctx.exception))

    def test_every_other_case_does_assign_tasMax(self):
        for key, cfg in C.SIZEDIST_CONFIG.items():
            if key == ("otherwise", "2DP"):
                continue
            with self.subTest(case=key):
                self.assertIsInstance(cfg.tasMax, float)

    def test_sizeDist_GPM_cases_never_assign_intar_threshold(self):
        """sizeDist.m:179-253 -- GPM's 2DS, CIP and HVPS cases omit
        intar_threshold. The first two switch inter-arrival thresholding ON, so
        sizeDist.m:1135 would fail on the undefined variable."""
        missing = {
            key for key, cfg in C.SIZEDIST_CONFIG.items()
            if not cfg.sets_intar_threshold
        }
        self.assertEqual(
            missing, {("GPM", "2DS"), ("GPM", "CIP"), ("GPM", "HVPS")}
        )
        for probe in ("2DS", "CIP"):
            self.assertTrue(C.sizedist_config("GPM", probe).apply_int_arr_thresh)

    def test_2DC_diodesize_disagrees_between_the_two_modules(self):
        """imgProc_sm.m:123 sizes 2DC images with 0.025 mm; sizeDist.m:186,344,443
        bins them with 0.030 mm. A faithful port reproduces both, so the two
        tables must stay separate."""
        self.assertEqual(C.imgproc_config("2DC").ds, 0.025)
        self.assertEqual(C.sizedist_config("ORACLES", "2DC").diodesize, 0.03)
        self.assertEqual(C.DIODESIZE_DISAGREEMENTS["2DC"], (0.025, 0.03))

    def test_no_other_probe_disagrees(self):
        """If a later transcription introduces a second disagreement, it should be
        a deliberate entry in the table, not a surprise."""
        found = {}
        for probe, img in C.IMGPROC_CONFIG.items():
            for (_project, sd_probe), sd in C.SIZEDIST_CONFIG.items():
                if sd_probe == probe and sd.diodesize != img.ds:
                    found[probe] = (img.ds, sd.diodesize)
        self.assertEqual(found, dict(C.DIODESIZE_DISAGREEMENTS))

    def test_pecan_cases_need_a_function_that_does_not_exist(self):
        """sizeDist.m:127,157 call getPECANparams, which is absent from the
        UIOOPS v3.1.4 tree. S4 raises NotImplementedError on this branch."""
        need = {k for k, cfg in C.SIZEDIST_CONFIG.items() if cfg.needs_pecan_params}
        self.assertEqual(need, {("PECAN", "CIP"), ("PECAN", "PIP")})


class TestCrossTableConsistency(unittest.TestCase):
    def test_probetype_agrees_between_the_two_modules(self):
        """A probetype mismatch would send imgProc and sizeDist down different
        branches for the same run -- worth catching at transcription time."""
        alias = {"F2DC": "Fast2DC"}
        for (_project, probe), sd in C.SIZEDIST_CONFIG.items():
            img_name = alias.get(probe, probe)
            with self.subTest(probe=probe):
                self.assertEqual(sd.probetype, C.imgproc_config(img_name).probetype)

    def test_diode_count_agrees_between_the_two_modules(self):
        alias = {"F2DC": "Fast2DC"}
        for (_project, probe), sd in C.SIZEDIST_CONFIG.items():
            img_name = alias.get(probe, probe)
            with self.subTest(probe=probe):
                self.assertEqual(sd.num_diodes, C.imgproc_config(img_name).diodenum)

    def test_probe_naming_differs_between_the_modules(self):
        """imgProc_sm.m calls it 'Fast2DC'; sizeDist.m calls it 'Fast2DC' under
        SOCRATES but 'F2DC' under otherwise. Both spellings must resolve."""
        self.assertIn(("SOCRATES", "Fast2DC"), C.SIZEDIST_CONFIG)
        self.assertIn(("otherwise", "F2DC"), C.SIZEDIST_CONFIG)
        self.assertNotIn(("otherwise", "Fast2DC"), C.SIZEDIST_CONFIG)

    def test_tables_are_immutable(self):
        """A stray write into a shared config would be an invisible fidelity bug."""
        with self.assertRaises(TypeError):
            C.SIZEDIST_CONFIG[("GPM", "2DS")] = None
        with self.assertRaises(AttributeError):
            C.sizedist_config("GPM", "2DS").num_bins = 99


if __name__ == "__main__":
    unittest.main()
