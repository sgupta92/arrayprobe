# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.intarr_plots`` -- ``IntArrAnalysis_time.m:220-291``'s contoured figure.

Deliberately does NOT do image comparison (the axis values, including the B8 NaN pattern, are
pinned directly against a real Octave run in ``test_intarr_s8_remainder.py``). What this file
checks: the module can be imported with no matplotlib installed, matplotlib is never imported as
a side effect of importing the core port, and the plotting call itself does not raise and places
the data it is handed onto the right axes/levels.
"""

from __future__ import annotations

import sys
import unittest

import numpy as np

try:
    import matplotlib  # noqa: F401
    _HAS_MATPLOTLIB = True
except ImportError:                     # pragma: no cover - depends on the env
    _HAS_MATPLOTLIB = False

try:
    import scipy  # noqa: F401   the fit underneath `analyse` needs it too.
    _HAS_SCIPY = True
except ImportError:                     # pragma: no cover - depends on the env
    _HAS_SCIPY = False


class ImportDecoupling(unittest.TestCase):
    """The contour plot must never be required to import the core port."""

    def test_intarr_analysis_does_not_import_matplotlib(self):
        # A fresh interpreter is the only honest way to check "not already imported by
        # something else in this test process" -- importing arrayprobe.intarr_analysis first
        # in-process would be contaminated by whatever test ran before it.
        import subprocess

        code = ("import sys, arrayprobe.intarr_analysis; "
                "sys.exit(1 if 'matplotlib' in sys.modules else 0)")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True)
        self.assertEqual(result.returncode, 0,
                         "importing arrayprobe.intarr_analysis must not pull in matplotlib")

    def test_intarr_plots_module_itself_imports_with_no_matplotlib_call(self):
        # Importing the module (as opposed to calling plot_intarr_contour) must not import
        # matplotlib either -- it is lazy, inside the one function that needs it.
        import subprocess

        code = ("import sys, arrayprobe.intarr_plots; "
                "sys.exit(1 if 'matplotlib' in sys.modules else 0)")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True)
        self.assertEqual(result.returncode, 0,
                         "importing arrayprobe.intarr_plots must not itself import matplotlib")


@unittest.skipUnless(_HAS_SCIPY, "scipy is an extra; the fit needs it to build test data")
@unittest.skipUnless(_HAS_MATPLOTLIB, "matplotlib is an extra; only the plot itself needs it")
class PlotIntarrContourTest(unittest.TestCase):
    def _build_result(self):
        from arrayprobe.intarr_analysis import analyse, inter_arrival

        rng = np.random.RandomState(20260913)
        gaps = np.concatenate([rng.exponential(2e-6, 150), rng.exponential(1e-2, 150)])
        seconds = np.cumsum(gaps)
        times = np.floor(np.linspace(63628, 123456, seconds.size))
        dates = np.full(seconds.size, 20160920.0)
        arr = inter_arrival(seconds)
        result = analyse(arr, times, n_blocks=3)
        return arr, times, dates, result

    def test_draws_without_raising_and_returns_a_figure_and_axes(self):
        from arrayprobe.intarr_plots import plot_intarr_contour

        arr, times, dates, result = self._build_result()
        fig, ax = plot_intarr_contour(
            arr, times, dates, result["threshold"], result["threshold_ww"],
            result["threshold_ak"], population_size=result["population_size"],
            date_string="20160920")
        try:
            self.assertEqual(ax.get_yscale(), "log", ":282 set(gca,'yscale','log')")
            ylim = ax.get_ylim()
            self.assertAlmostEqual(ylim[0], 1e-7, places=10)
            self.assertAlmostEqual(ylim[1], 1.0, places=10)
            self.assertEqual(len(ax.lines), 3, "three overlay lines: threshold/_ww/_ak")
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_fix_b8_option_also_draws_without_raising(self):
        from arrayprobe.intarr_plots import plot_intarr_contour

        arr, times, dates, result = self._build_result()
        fig, ax = plot_intarr_contour(
            arr, times, dates, result["threshold"], result["threshold_ww"],
            result["threshold_ak"], population_size=result["population_size"],
            date_string="20160920", fix_b8=True)
        try:
            self.assertIsNotNone(ax)
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_contour_uses_the_documented_fill_levels(self):
        from arrayprobe.intarr_analysis import CONTOUR_LEVELS
        from arrayprobe.intarr_plots import plot_intarr_contour

        arr, times, dates, result = self._build_result()
        fig, ax = plot_intarr_contour(
            arr, times, dates, result["threshold"], result["threshold_ww"],
            result["threshold_ak"], population_size=result["population_size"],
            date_string="20160920")
        try:
            self.assertEqual(len(CONTOUR_LEVELS), 20, "0.005:0.005:0.1 is 20 levels")
            np.testing.assert_allclose(CONTOUR_LEVELS[0], 0.005)
            np.testing.assert_allclose(CONTOUR_LEVELS[-1], 0.1)
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)


if __name__ == "__main__":
    unittest.main()
