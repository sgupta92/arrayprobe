# SPDX-License-Identifier: BSD-3-Clause
"""The synthetic v3.5 sizeDist proc carries the features its banks exercise."""

import importlib.util
import os
import tempfile
import unittest

import numpy as np
from netCDF4 import Dataset

_GEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                    "make_v35_sizedist_synthetic.py")
_spec = importlib.util.spec_from_file_location("make_v35_sizedist_synthetic", _GEN)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class TestSyntheticV35SizedistProc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = gen.write(os.path.join(cls.tmp.name, "a.nc"))
        with Dataset(cls.path) as ds:
            cls.fmt = ds.data_model
            cls.v = {k: np.asarray(ds.variables[k][:]) for k in ds.variables}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_format_and_variable_contract(self):
        self.assertEqual(self.fmt, "NETCDF3_CLASSIC")
        self.assertEqual(list(self.v), [s.name for s in gen._variables()])

    def test_several_seconds_far_from_midnight(self):
        t = np.unique(self.v["Time"])
        self.assertEqual(t.size, gen.N_SECONDS)
        self.assertTrue(np.all(np.diff(self.v["Time_in_seconds"]) >= 0))
        self.assertTrue(np.all((t > 1000) & (t < 230000)))

    def test_shattering_clusters_below_6us(self):
        short = np.count_nonzero(np.diff(self.v["Time_in_seconds"]) < 6e-6)
        expected = gen.N_SECONDS * gen.CLUSTERS_PER_SECOND * (gen.CLUSTER_SIZE - 1)
        self.assertGreaterEqual(short, expected)

    def test_two_habits_and_some_rejects(self):
        self.assertEqual(set(np.unique(self.v["holroyd_habit"])), set(gen.HABITS))
        # imgProc_sm writes an accepted particle as the character '0' (48), not a numeric 0.
        self.assertTrue(np.any(self.v["image_auto_reject"] != ord("0")))
        self.assertTrue(np.any(self.v["image_auto_reject"] == ord("0")))

    def test_area_ratio_spread(self):
        d = self.v["image_diam_minR"]
        ar = self.v["image_area"] / (np.pi / 4.0 * d ** 2)
        for anchor in gen.AREA_RATIO_ANCHORS:
            self.assertTrue(np.any(np.isclose(ar, anchor)), anchor)
        self.assertLess(ar.min(), 0.05)
        self.assertGreater(ar.max(), 0.9)

    def test_deterministic(self):
        a, b = gen.particles(), gen.particles()
        for k in a:
            np.testing.assert_array_equal(a[k], b[k])


if __name__ == "__main__":
    unittest.main()
