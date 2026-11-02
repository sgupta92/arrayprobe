# SPDX-License-Identifier: BSD-3-Clause
"""The triage server shows a particle at its true shape, whatever the window size.

The author, labelling particles on 2026-10-01: *"the actual particle image looks very different
based on the window size and could change the recommendation because it impacts the aspect ratio
of the image I'm seeing ... there need to be axis labels and the aspect ratio cannot be distorted
by screen size."*

Two causes, each with its check here:

1. **The PNG.** The image was drawn with ``aspect="auto"`` inside a figure with a minimum size,
   so a small particle filled a 1.2 x 0.8 inch box whatever its shape. ``particle_figure`` draws
   one diode and one slice the same length; the check renders a figure and measures the drawn
   axes in device pixels against the particle's own extent.
2. **The page.** The image sat in a flex row whose default ``align-items: stretch`` set its height
   to the height of the text column beside it, which changes with window width. The check reads
   the stylesheet the server sends.
"""

from __future__ import annotations

import re
import unittest

import numpy as np

from arrayprobe import triage_server as ts

try:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
except ImportError:  # matplotlib is an optional extra
    Figure = None


def drawn_aspect_error(fig, c=None) -> float:
    """Largest relative error, over every panel holding an image, between the panel's drawn
    width/height in device pixels and its image's own width/height in data units; 0 when
    one diode and one slice are drawn the same length. ``c`` is used only by the old
    renderer, whose image carries no extent."""
    FigureCanvasAgg(fig)
    fig.canvas.draw()
    worst = 0.0
    for ax in fig.axes:
        if not ax.images:
            continue
        box = ax.get_window_extent()
        x0, x1, y0, y1 = ax.images[0].get_extent()
        if c is not None and not ax.axison:  # the old renderer: pixels, no axes
            n_slices, n_diodes = c.shape
            want = n_diodes / n_slices
        else:
            want = abs(x1 - x0) / abs(y1 - y0)
        worst = max(worst, abs((box.width / box.height) / want - 1.0))
    return worst


def old_figure(c):
    """The renderer as it was before 2026-10-01, kept here only to show the check fires."""
    fig = Figure(figsize=(max(1.2, c.shape[1] / 25), max(0.8, c.shape[0] / 25)), dpi=110)
    ax = fig.add_subplot(111)
    ax.imshow(c, cmap="Greys", aspect="auto", interpolation="nearest")
    ax.axis("off")
    fig.tight_layout(pad=0.1)
    return fig


SHAPES = [(1, 1), (3, 12), (12, 3), (40, 40), (200, 5), (5, 128), (1700, 10)]


@unittest.skipIf(Figure is None, "matplotlib (the [extra] install) is not installed")
class TheImageIsDrawnAtTrueAspect(unittest.TestCase):

    def test_every_shape_is_drawn_with_square_pixels(self):
        for shape in SHAPES:
            c = np.zeros(shape, dtype=bool)
            c[0, 0] = c[-1, -1] = True
            fig = ts.particle_figure(c, 10.0, Figure)
            with self.subTest(shape=shape):
                self.assertLess(drawn_aspect_error(fig), 0.02)

    def test_a_small_particle_in_a_wide_record_gets_a_close_up_and_the_whole_record(self):
        c = np.zeros((13, 128), dtype=bool)
        c[2:11, 80:88] = True
        fig = ts.particle_figure(c, 10.0, Figure)
        close, whole = [ax for ax in fig.axes if ax.images]
        # the close-up keeps absolute micrometres: diodes 78-90 and slices 0-13, margin 2
        self.assertEqual(tuple(close.images[0].get_extent()), (780.0, 900.0, 130.0, 0.0))
        self.assertEqual(tuple(whole.images[0].get_extent()), (0.0, 1280.0, 130.0, 0.0))
        self.assertEqual(len(whole.patches), 1)  # the box marking the close-up
        self.assertLess(drawn_aspect_error(fig), 0.02)

    def test_the_axes_are_in_micrometres_and_say_which_way_is_which(self):
        c = np.ones((3, 12), dtype=bool)
        fig = ts.particle_figure(c, 10.0, Figure)
        self.assertEqual(len(fig.axes), 1)  # the particle fills its record: no second panel
        ax = fig.axes[0]
        self.assertEqual(ax.get_aspect(), 1.0)
        self.assertEqual(tuple(ax.images[0].get_extent()), (0.0, 120.0, 30.0, 0.0))
        self.assertIn("across the array (µm", ax.get_xlabel())
        self.assertIn("along the flight (µm)", ax.get_ylabel())
        self.assertIn("12 diodes × 3 slices", ax.get_title())

    def test_the_hvps_diode_size_reaches_the_axis(self):
        c = np.ones((2, 2), dtype=bool)
        fig = ts.particle_figure(c, ts.IMGPROC_CONFIG["HVPS"].ds * 1000.0, Figure)
        self.assertEqual(fig.axes[0].images[0].get_extent()[1], 300.0)

    def test_the_check_fires_on_the_old_renderer(self):
        """The measurement is not vacuous: the pre-fix renderer stretched these shapes."""
        for shape in [(1, 1), (3, 12), (12, 3)]:
            c = np.ones(shape, dtype=bool)
            with self.subTest(shape=shape):
                self.assertGreater(drawn_aspect_error(old_figure(c), c), 0.2)


class ThePageNeverStretchesTheImage(unittest.TestCase):

    @staticmethod
    def rule(selector: str) -> str:
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", ts.STYLE)
        assert m, f"no CSS rule for {selector!r}"
        return re.sub(r"\s+", "", m.group(1))

    def test_the_flex_row_does_not_stretch_its_children(self):
        self.assertIn("align-items:flex-start", self.rule(".detail"))

    def test_the_full_size_image_keeps_its_own_aspect(self):
        r = self.rule(".detail img, .pimg img")
        self.assertIn("width:auto", r)
        self.assertIn("height:auto", r)
        self.assertIn("object-fit:contain", r)
        self.assertNotRegex(r, r"(?<!max-)height:\d")

    def test_thumbnails_are_contained_not_stretched(self):
        for sel in (".pcard img", ".ccard img"):
            with self.subTest(sel=sel):
                self.assertIn("object-fit:contain", self.rule(sel))

    def test_every_full_size_particle_image_carries_the_true_aspect_note(self):
        import inspect
        src = inspect.getsource(ts)
        full = re.findall(r"<img src=['\"]/image/[^'\"]*crop=0['\"][^>]*>", src)
        self.assertGreaterEqual(len(full), 3)
        for tag in full:
            i = src.index(tag)
            with self.subTest(tag=tag):
                # The image sits inside a figure.pimg (the reject code and air temperature
                # are drawn above it inside the same figure since 2026-10-02), and
                # that figure's caption is the true-aspect note.
                opening = src.rindex("<figure", 0, i)
                self.assertIn("pimg", src[opening:opening + 40])
                self.assertNotIn("</figure>", src[opening:i])
                closing = src.index("</figure>", i)
                self.assertIn("TRUE_ASPECT_NOTE", src[i:closing])


if __name__ == "__main__":
    unittest.main()
