# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``sizeDist.m:1121-1123``: a capped dead time leaves a zero sample volume.

When a 2D-S/HVPS second's overload dead time (``time_interval72``, ``:1115``) exceeds 1 s,
``:1123`` caps it at 1, so ``:1932``'s live time ``1 - time_interval72`` is exactly 0,
``:1978``'s sample volume is 0, and ``:1988``'s concentration is ``inf`` in every occupied bin
and ``0/0 = NaN`` in every empty one. The port reproduces that (preserved, not fixed). v3.1.4
``:945-948`` reset the same sum to 0 instead, i.e. a full 1 s live time.

Seen on ARM 2D-S data, 2017-07-03, seconds 38888, 38892, 39155; the transcribed
lines were also run under Octave (September 2026).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import PKG_ROOT, repo_only  # noqa: E402

from arrayprobe_uiops.sizedist import OVERLOAD_CAP_SEC, overload_dead_time

REPO = Path(__file__).resolve().parents[1]
V35 = _upstream.source("uiops35") / "sizeDist.m"
V314 = _upstream.source("uiops314") / "sizeDist.m"
PORT = PKG_ROOT / "src" / "arrayprobe_uiops" / "sizedist.py"


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops314")
    _upstream.require("uiops35")


class TheCapLeavesZeroLiveTime(unittest.TestCase):
    def test_a_second_over_one_second_of_dead_time_is_capped_to_exactly_one(self):
        int_arr = np.array([0.4, 0.5, 0.3])
        flags = np.array([1, 1, 1])
        t72 = overload_dead_time(int_arr, flags, probetype=2)
        self.assertEqual(t72, 1.0)
        self.assertEqual(1 - t72, 0.0)

    def test_zero_volume_gives_inf_in_occupied_bins_and_nan_in_empty_ones(self):
        # :1932, :1978, :1981, :1988 on one second, two bins (counts 5 and 0).
        t72 = overload_dead_time(np.array([0.4, 0.5, 0.3]), np.ones(3), probetype=2)
        time_interval200 = 1 - t72
        svol = np.array([50.0, 50.0]) * (1e-3) ** 2 * time_interval200 * 100.0 * 100 ** 3
        with np.errstate(divide="ignore", invalid="ignore"):
            conc = np.array([5.0, 0.0]) / svol
        self.assertTrue(np.isposinf(conc[0]))
        self.assertTrue(np.isnan(conc[1]))
        self.assertTrue(np.isnan(conc.sum()))

    def test_just_under_the_cap_is_finite(self):
        t72 = overload_dead_time(np.array([0.3, 0.4]), np.ones(2), probetype=2)
        self.assertAlmostEqual(1 - t72, 0.3)

    def test_probetype_1_is_not_capped(self):
        t72 = overload_dead_time(np.array([0.4, 0.5, 0.3]), np.ones(3), probetype=1)
        self.assertAlmostEqual(t72, 1.2)


class TheCitedLinesAreTheLiveOnes(unittest.TestCase):
    @repo_only
    def test_v35_caps_to_one(self):
        lines = V35.read_text(encoding="latin-1").splitlines()
        self.assertIn("if time_interval72(i)>1", lines[1120])
        self.assertIn("time_interval72(i) = 1;", lines[1122])
        self.assertIn("time_interval200=1-time_interval72'", lines[1931])
        self.assertIn("cip2_conc_minR  = particle_dist_minR./svol2'", lines[1987])
        self.assertEqual(OVERLOAD_CAP_SEC, 1.0)

    @repo_only
    def test_v314_reset_to_zero(self):
        lines = V314.read_text(encoding="latin-1").splitlines()
        self.assertIn("(time_interval72(i)>1)", lines[944])
        self.assertIn("time_interval72(i) = 0;", lines[947])

    def test_port_divides_without_guarding_zero_volume(self):
        src = PORT.read_text(encoding="utf-8")
        self.assertIn('conc_minR = store["dist_minR"] / svol2_t', src)
        self.assertIn("time_interval200 = 1 - time_interval72", src)


if __name__ == "__main__":
    unittest.main()
