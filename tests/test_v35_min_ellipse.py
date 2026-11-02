# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.min_ellipse`` -- no Octave/CGAL oracle exists for this
routine (doctrine layer 3), so these check the math directly: known point
sets whose centre and axis lengths are independently derivable by hand."""
from __future__ import annotations

import unittest

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe_uiops.min_ellipse import cgal_ellipse_size


class NoShadow(unittest.TestCase):
    def test_empty_image_is_all_zero_five_outputs(self):
        import numpy as np
        c = np.zeros((5, 5), dtype=bool)
        self.assertEqual(cgal_ellipse_size(c), (0.0, 0.0, 0.0, 0.0, 0.0))


class KnownCentre(unittest.TestCase):
    """A point set symmetric about a known centre must report that centre
    (plus v3.5's own "+1" 1-based-index bias) regardless of axis fitting
    details -- this is true for ANY centrally-symmetric point set, so it
    does not depend on trusting the Khachiyan fit's precision."""

    def test_a_square_ring_centres_on_its_own_midpoint(self):
        # A symmetric ring of (x, y) points around (10, 20) in 0-based diode
        # coords -- (x, y) here matches _shadow_points_xy's own (col, row)
        # convention, i.e. x is the column index, y is the row index.
        pts = [(10 + dx, 20 + dy) for dx in (-3, 3) for dy in (-3, 3)]
        pts += [(10 + dx, 20 + dy) for dx in (-3, 0, 3) for dy in (-3, 0, 3)]
        major, minor, angle, x, y = cgal_ellipse_size(_as_shadow_grid(pts))
        # places=2: _khachiyan_ellipsoid's own default tol is 1e-4 on the
        # Khachiyan stopping criterion, not on centre/axis coordinates
        # directly -- observed residual here is ~1e-3.
        self.assertAlmostEqual(x, 1.0 + 10.0, places=2)
        self.assertAlmostEqual(y, 1.0 + 20.0, places=2)
        # A square-symmetric point set's minimum enclosing ellipse is a
        # circle: major == minor.
        self.assertAlmostEqual(major, minor, places=2)

    @needs_v314_engine
    def test_major_minor_have_no_plus_one_bias_unlike_v314(self):
        """The documented v3.5 change: major/minor drop v3.1.4's "+1.",
        while x/y gain one instead."""
        from arrayprobe.geometry.min_ellipse import cgal_ellipse_size as v314
        pts = [(0, 0), (0, 4), (4, 0), (4, 4), (2, 2)]
        grid = _as_shadow_grid(pts)
        major_35, minor_35, _angle_35, x_35, y_35 = cgal_ellipse_size(grid)
        major_314, minor_314, _angle_314 = v314(grid)
        # v3.1.4's own major/minor already carry a "+1."; v3.5's must be
        # exactly 1.0 less (same underlying geometry, the bias is the only
        # documented difference for these two outputs).
        self.assertAlmostEqual(major_314, major_35 + 1.0, places=6)
        self.assertAlmostEqual(minor_314, minor_35 + 1.0, places=6)
        self.assertAlmostEqual(x_35, 1.0 + 2.0, places=2)
        self.assertAlmostEqual(y_35, 1.0 + 2.0, places=2)


def _as_shadow_grid(points):
    """A boolean grid (``True``=shadowed) large enough to hold every ``(x, y)``
    in ``points``. ``_shadow_points_xy`` reads a grid ``g`` via
    ``np.nonzero(shadow_mask(g))`` -> ``(rows, cols)`` and returns
    ``column_stack((cols, rows))`` -- i.e. its output ``(x, y)`` is
    ``(col, row)``. So to place a point at output ``(x, y)`` here, the pixel
    that must be set is ``grid[row=y, col=x]``."""
    import numpy as np
    max_x = max(p[0] for p in points) + 2
    max_y = max(p[1] for p in points) + 2
    grid = np.zeros((max_y, max_x), dtype=bool)
    for x, y in points:
        grid[y, x] = True
    return grid


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
