# SPDX-License-Identifier: BSD-3-Clause
"""The triage server's diode page -- its first view.

The plan's parenthesis is the reason this view exists: *"stuck diodes are
visible before any mask exists"*. They are visible nowhere else — `imgProc_sm`
judges each particle on its own silhouette, so a column dark in all of them
looks exactly like a stream of narrow particles. The page is the only place the
flight-scale signature shows.

So the tests here are mostly about the page not lying in the two ways a chart
can: a flight with a flat, low occupancy must not render as an empty box (that
would make "nothing to see" and "nothing measured" look identical), and a
flagged diode must carry the caveat about which half of the threshold was
transcribed and which was inferred — beside the flag, not beneath it.
"""

from __future__ import annotations

import unittest

import numpy as np

from arrayprobe.diode_report import SPEC_NOISY_DIODE, accumulate_occupancy
from arrayprobe.triage_server import render_occupancy_svg


class TheChartSaysWhatItPlots(unittest.TestCase):
    def test_a_bar_per_diode(self):
        svg = render_occupancy_svg([0.1, 0.2, 0.3])
        self.assertEqual(svg.count("<rect"), 3)

    def test_each_bar_carries_its_own_value_as_a_title(self):
        """Hover text, so a reader can read a number off the chart rather than
        estimating it from a bar."""
        svg = render_occupancy_svg([0.25, 0.5])
        self.assertIn("diode 1: 0.2500", svg)
        self.assertIn("diode 2: 0.5000", svg)

    def test_bars_scale_to_the_peak_not_to_one(self):
        """A flight whose highest occupancy is 0.04 must not render as an empty
        box: 'nothing to see' and 'nothing measured' must not look the same.
        """
        svg = render_occupancy_svg([0.01, 0.04])
        heights = [float(part.split("height='")[1].split("'")[0])
                   for part in svg.split("<rect")[1:]]
        self.assertGreater(max(heights), 100,
                           "the tallest bar of a low-occupancy flight collapsed")

    def test_the_scaling_is_stated_rather_than_left_to_be_inferred(self):
        svg = render_occupancy_svg([0.01, 0.04])
        self.assertIn("scale to the peak", svg)
        self.assertIn("peak 0.0400 at diode 2", svg)

    def test_a_flagged_diode_is_drawn_differently_and_labelled(self):
        svg = render_occupancy_svg([0.1, 0.9], flagged=[1])
        self.assertIn("(flagged)", svg)
        self.assertIn("var(--bad)", svg)
        self.assertIn("var(--accent)", svg)

    def test_no_particles_says_so_instead_of_drawing_nothing(self):
        self.assertIn("nothing to plot", render_occupancy_svg([]))

    def test_an_all_zero_flight_does_not_divide_by_zero(self):
        """Peak 0 is a real state -- a decode with no shadowed slice at all."""
        svg = render_occupancy_svg([0.0, 0.0, 0.0])
        self.assertEqual(svg.count("<rect"), 3)


class TheChartAgreesWithTheReportItPlots(unittest.TestCase):
    """Two sides from different places: the report computes, the chart draws."""

    def test_the_peak_the_chart_names_is_the_report_s_worst_diode(self):
        n_diodes = 12
        stuck = 7
        shadows = []
        rng = np.random.default_rng(3)
        for _ in range(40):
            shadow = np.zeros((5, n_diodes), dtype=bool)
            shadow[rng.integers(0, 5, 3), rng.integers(0, n_diodes, 3)] = True
            shadow[:, stuck] = True
            shadows.append(shadow)
        report = accumulate_occupancy(shadows)
        svg = render_occupancy_svg(report.occupancy)
        self.assertIn(f"at diode {stuck + 1}", svg)
        self.assertIn(f"diode {stuck + 1}", report.summary())


class TheInterArrivalPanelShowsWhetherTheFitWorked(unittest.TestCase):
    """The panel's reason for existing, as tests.

    `block_thresholds` falls back to `DEFAULT_THRESHOLD` when the fit returns a
    NaN or when no bin lies between the two fitted taus -- and the output file
    records the number without recording that it is a fallback. So the one
    thing this panel must never do is draw something that makes a failed fit
    look like a successful one.
    """

    def _bimodal(self):
        from arrayprobe.intarr_analysis import HIST_BINS
        rng = np.random.default_rng(0)
        sample = np.concatenate([rng.exponential(2e-6, 4000),
                                 rng.exponential(2e-2, 6000)])
        counts, _ = np.histogram(sample, bins=HIST_BINS)
        centres = HIST_BINS[:-1] + np.diff(HIST_BINS) / 2
        return counts, centres

    def test_a_real_bimodal_population_is_fitted_and_drawn(self):
        """End to end through the project's own oracle-tested fit, not a stub."""
        from arrayprobe.intarr import bimodal_model
        from arrayprobe.intarr_analysis import block_thresholds
        from arrayprobe.triage_server import render_intarr_svg

        counts, centres = self._bimodal()
        threshold, _ww, _ak, tau = block_thresholds(counts)
        self.assertFalse(np.isnan(np.asarray(tau)).any(),
                         "the fixture stopped being bimodal enough to fit")
        # Both planted modes recovered: 2 us and 20 ms.
        self.assertAlmostEqual(float(np.min(tau[:2])), 2e-6, delta=1e-6)
        self.assertAlmostEqual(float(np.max(tau[:2])), 2e-2, delta=1e-2)
        svg = render_intarr_svg(counts, centres, bimodal_model(tau, centres),
                                [("threshold", threshold)])
        self.assertIn("<polyline", svg)
        self.assertIn("stroke-dasharray", svg)

    def test_a_failed_fit_draws_no_curve_and_says_why(self):
        """A flat line would read as 'the fit found nothing', which is a
        different claim from 'the fit did not converge'."""
        from arrayprobe.triage_server import render_intarr_svg

        counts, centres = self._bimodal()
        svg = render_intarr_svg(counts, centres, None, [])
        self.assertNotIn("<polyline", svg)
        self.assertIn("did not converge", svg)
        self.assertIn("DEFAULT_THRESHOLD", svg)

    def test_the_axis_is_logarithmic(self):
        """HIST_BINS spans seven decades; drawn linearly, six of them would be
        squeezed into the last few pixels."""
        from arrayprobe.triage_server import render_intarr_svg

        counts, centres = self._bimodal()
        svg = render_intarr_svg(counts, centres, None, [])
        xs = [float(part.split("x='")[1].split("'")[0])
              for part in svg.split("<rect")[1:]]
        # On a log axis the bin centres are evenly spaced; on a linear one the
        # first thirty would all sit within a pixel of zero.
        gaps = np.diff(xs)
        self.assertLess(float(gaps.std() / gaps.mean()), 0.05,
                        "bin spacing is not uniform, so the axis is not log")

    def test_a_threshold_outside_the_plotted_range_is_not_drawn(self):
        """Rather than clamped to an edge, where it would look like a real
        threshold sitting at the limit of the data."""
        from arrayprobe.triage_server import render_intarr_svg

        counts, centres = self._bimodal()
        svg = render_intarr_svg(counts, centres, None, [("absurd", 1e3)])
        self.assertNotIn("stroke-dasharray", svg)

    def test_mismatched_inputs_say_so_rather_than_drawing_nonsense(self):
        from arrayprobe.triage_server import render_intarr_svg

        self.assertIn("no inter-arrival histogram",
                      render_intarr_svg([1, 2, 3], [0.1, 0.2]))


class TheRatePanelDoesNotImplyACorrelation(unittest.TestCase):
    """Particles per second against TAS -- row 16's last named panel.

    A dual-axis plot is the easiest chart to mislead with: two series scaled
    independently will track each other by construction if you let the reader
    assume a shared axis. So the panel states both maxima and says the scales
    are independent, and these tests hold it to that.
    """

    def test_the_rate_series_is_drawn(self):
        from arrayprobe.triage_server import render_rate_svg
        svg = render_rate_svg([1, 2, 3], [10, 20, 5])
        self.assertEqual(svg.count("<polyline"), 1)
        self.assertIn("peaks at 20", svg)

    def test_tas_is_a_second_series_and_the_scales_are_declared_independent(self):
        from arrayprobe.triage_server import render_rate_svg
        svg = render_rate_svg([1, 2, 3], [10, 20, 5], [1, 2, 3], [100, 101, 99])
        self.assertEqual(svg.count("<polyline"), 2)
        self.assertIn("INDEPENDENT vertical scales", svg)
        self.assertIn("TAS (dashed) peaks at 101.0", svg)

    def test_a_missing_sidecar_says_missing_rather_than_drawing_flat(self):
        """A flat line would read as 'the aircraft was stationary'."""
        from arrayprobe.triage_server import render_rate_svg
        svg = render_rate_svg([1, 2, 3], [10, 20, 5])
        self.assertIn("missing rather than flat", svg)
        self.assertEqual(svg.count("<polyline"), 1)

    def test_tas_samples_outside_the_particle_window_are_not_drawn(self):
        """The sidecar routinely covers taxi and climb; stretching the axis to
        include them would squeeze the flight into a corner."""
        from arrayprobe.triage_server import render_rate_svg
        svg = render_rate_svg([10, 11], [1, 2], [0, 10, 11, 9999], [50, 100, 100, 50])
        self.assertEqual(svg.count("<polyline"), 2)
        drawn = svg.split("stroke-dasharray")[0].split("<polyline")[-1]
        self.assertNotIn("9999", drawn)

    def test_mismatched_series_say_so(self):
        from arrayprobe.triage_server import render_rate_svg
        self.assertIn("no per-second rate", render_rate_svg([1, 2, 3], [1, 2]))

    def test_an_all_zero_rate_does_not_divide_by_zero(self):
        from arrayprobe.triage_server import render_rate_svg
        self.assertIn("<polyline", render_rate_svg([1, 2], [0, 0]))


class TheCaveatTravelsWithTheFlag(unittest.TestCase):
    """What is transcribed and what is inferred must not part company."""

    def test_the_note_names_what_would_confirm_the_inference(self):
        self.assertIn("App. B", SPEC_NOISY_DIODE.m_definition_note)

    def test_the_page_source_prints_the_note_where_diodes_are_flagged(self):
        """Read from the source rather than by rendering a page, which would
        need a decoded flight this test has no business requiring.

        The property: the caveat appears inside the flagged branch, not in a
        footer that a reader who has just seen a flagged diode will skip.
        """
        import inspect

        from arrayprobe import triage_server

        source = inspect.getsource(triage_server.TriageServer._render_diodes)
        flagged_branch = source.split("flagged.size == 0")[1]
        self.assertIn("m_definition_note", flagged_branch)
        self.assertIn("under-reports", flagged_branch)


if __name__ == "__main__":
    unittest.main()
