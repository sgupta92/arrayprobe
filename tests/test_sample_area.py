# SPDX-License-Identifier: BSD-3-Clause
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from arrayprobe.sample_area import calc_sa_randombins


class TestCalcSaRandombins(unittest.TestCase):
    def test_method0_center_in_hand_computed(self):
        bins_mid = [10.0]
        res, armdst, num_diodes, probetype = 25.0, 10.0, 64, 1

        res_mm = res * 1e-3
        radius = bins_mid[0] / 2
        eaw = num_diodes * res_mm
        lambda_mm = 680e-6
        dof = min(6 * radius ** 2 / lambda_mm, armdst)
        expected = dof * eaw

        result = calc_sa_randombins(bins_mid, res, armdst, num_diodes, 0, probetype)
        self.assertAlmostEqual(result[0], expected)

    def test_method1_entire_in_hand_computed(self):
        bins_mid = [10.0]
        res, armdst, num_diodes, probetype = 25.0, 10.0, 64, 1

        res_mm = res * 1e-3
        radius = bins_mid[0] / 2
        eaw = (num_diodes - (bins_mid[0] / res_mm) + 1) * res_mm
        eaw = max(eaw, 0)
        lambda_mm = 680e-6
        dof = min(6 * radius ** 2 / lambda_mm, armdst)
        expected = dof * eaw

        result = calc_sa_randombins(bins_mid, res, armdst, num_diodes, 1, probetype)
        self.assertAlmostEqual(result[0], expected)

    def test_method1_clamps_negative_width_to_zero(self):
        # Choose a bin large enough (relative to num_diodes*res) that
        # the raw EAWci would go negative before clamping.
        bins_mid = [100000.0]
        res, armdst, num_diodes, probetype = 25.0, 10.0, 8, 1
        result = calc_sa_randombins(bins_mid, res, armdst, num_diodes, 1, probetype)
        self.assertEqual(result[0], 0.0)

    def test_method2_with_correction_hand_computed(self):
        bins_mid = [10.0]
        res, armdst, num_diodes, probetype = 25.0, 10.0, 64, 1

        res_mm = res * 1e-3
        radius = bins_mid[0] / 2
        diameter = 2 * radius
        eaw = num_diodes * res_mm + 0.72 * diameter
        lambda_mm = 680e-6
        dof = min(6 * radius ** 2 / lambda_mm, armdst)
        expected = dof * eaw

        result = calc_sa_randombins(bins_mid, res, armdst, num_diodes, 2, probetype)
        self.assertAlmostEqual(result[0], expected)

    def test_probetype2_alternate_dof_formula(self):
        bins_mid = [10.0]
        # armdst well above both unclamped DOF values
        res, armdst, num_diodes = 25.0, 1_000_000.0, 64
        radius = bins_mid[0] / 2

        result_default = calc_sa_randombins(bins_mid, res, armdst, num_diodes, 0, 1)
        result_probetype2 = calc_sa_randombins(bins_mid, res, armdst, num_diodes, 0, 2)

        self.assertNotAlmostEqual(result_default[0], result_probetype2[0])

        expected_dof_probetype2 = 20.52 * radius ** 2 * 1000
        res_mm = res * 1e-3
        eaw = num_diodes * res_mm
        self.assertAlmostEqual(result_probetype2[0], expected_dof_probetype2 * eaw)

    def test_dof_clamped_to_arm_distance(self):
        bins_mid = [100000.0]  # huge radius -> DOF would far exceed armdst
        res, armdst, num_diodes, probetype = 25.0, 5.0, 64, 1
        result = calc_sa_randombins(bins_mid, res, armdst, num_diodes, 0, probetype)
        res_mm = res * 1e-3
        eaw = num_diodes * res_mm
        # DOF should be clamped to armdst exactly.
        self.assertAlmostEqual(result[0], armdst * eaw)

    def test_multiple_bins_processed_independently(self):
        bins_mid = [5.0, 10.0, 20.0]
        result = calc_sa_randombins(bins_mid, 25.0, 10.0, 64, 0, 1)
        self.assertEqual(len(result), 3)
        # Larger bins should (monotonically, for method 0/probetype 1) give
        # larger or equal DOF-driven sample area up to the armdst clamp.
        self.assertLessEqual(result[0], result[1])

    def test_invalid_sa_method_raises(self):
        with self.assertRaises(ValueError):
            calc_sa_randombins([10.0], 25.0, 10.0, 64, 3, 1)


if __name__ == "__main__":
    unittest.main()
