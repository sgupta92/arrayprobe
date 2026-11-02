# SPDX-License-Identifier: BSD-3-Clause
"""Which matrix axis does v3.5's ``CGAL_minR`` divide by ``tasRatio``?

Evidence bank for the V4 axis defect.
The fixture
``tests/data/v35_cgal_minr_nonsquare_golden.json`` was written by the REAL
v3.5 MEX under Octave (``octave_oracle/run_v35_cgal_minr_nonsquare_bank.py``)
on non-square grids with asymmetric particles, because the square bank
(``v35_cgal_minr_octave_golden.json``, 11x11 throughout) cannot see the axis:
a transposed feed and a swapped scaling axis cancel on a square.

The two sides of every assertion come from different places: the expected
centre is derived here from the PLACED geometry (the same 0-based (row, col)
rules the ``.m`` uses, re-checked against the image Octave wrote), never from
the port; the measured side is the MEX's own ``ctx``/``cty``/``diameter``.

**What the MEX does** (``CGAL_minR.cpp:75-84``, ``:115-120``): ``j`` (the ROW
index, ``mxGetM``) is divided by ``tasRatio`` and stored as ``p[0]``; ``i``
(the COLUMN index) is ``p[1]``; ``B[1]`` (= ``ctx``) is ``center[0]``. So
``ctx`` is the SCALED ROW centre and ``cty`` the UNSCALED COLUMN centre.

**The port agreed with none of these 60 records when this bank was written**:
it scaled index 1 (the column) and returned ``center_col`` as ``ctx``, i.e.
it was exactly ``MEX o transpose``. Fixed 2026-09-11 -- ``min_circle.py``
now scales index 0 and returns the row centre first, and
``test_v35_min_circle.py::_img_to_char_matrix`` no longer transposes its
feed. Those two changes are one fix: either alone turns the square bank red,
because on an 11x11 grid they cancel. This module is what holds the fix --
it is the only bank whose grids are non-square, so it is the only one that
can tell the two conventions apart.
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_uiops.min_circle import cgal_min_r_v35

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "v35_cgal_minr_nonsquare_golden.json"

GRIDS = [(8, 13), (13, 8), (4, 20), (20, 4)]
RATIOS = [0.7, 1.0, 1.4]
SHAPES = ["long_bar", "short_bar", "l_shape", "diagonal_1_2", "two_points"]


def shape_points(shape: str, m: int, n: int) -> list[tuple[int, int]]:
    """0-based (row, col) pixels; mirrors ``shape_points`` in
    ``run_v35_cgal_minr_nonsquare_oracle.m``. First and last entries are the
    two tips that fix the minimal enclosing circle (a segment, or the
    hypotenuse of a right angle -- Thales -- for the L)."""
    if shape == "long_bar":
        if n >= m:
            return [(1, c) for c in range(1, n - 1)]
        return [(r, 1) for r in range(1, m - 1)]
    if shape == "short_bar":
        if n >= m:
            return [(r, n - 2) for r in range(0, m - 1)]
        return [(m - 2, c) for c in range(0, n - 1)]
    if shape == "l_shape":
        vert = [(r, 1) for r in range(1, m - 1)]
        horz = [(1, c) for c in range(2, n - 1)]
        return list(reversed(vert)) + horz
    if shape == "diagonal_1_2":
        K = min(m - 1, (n - 1) // 2)
        return [(k, 2 * k) for k in range(K + 1)]
    if shape == "two_points":
        return [(0, 1), (m - 1, n - 2)]
    raise ValueError(shape)


def expected_circle(tips, tas, *, scaled_axis: str):
    """Centre and diameter of the circle on the two tips after dividing ONE
    axis by ``tas``. Returns ``(diameter, scaled_centre, unscaled_centre)``
    in the MEX's output order (scaled axis first, as ``ctx``)."""
    (r1, c1), (r2, c2) = tips
    if scaled_axis == "row":
        a1, a2, b1, b2 = r1 / tas, r2 / tas, c1, c2
    else:
        a1, a2, b1, b2 = c1 / tas, c2 / tas, r1, r2
    return 1.0 + math.hypot(a1 - a2, b1 - b2), (a1 + a2) / 2, (b1 + b2) / 2


def img_from_record(rec: dict) -> np.ndarray:
    """The matrix the MEX saw: ``img_rows`` is written row by row, so this
    reconstruction cannot depend on any flattening convention."""
    return np.array([list(r) for r in rec["img_rows"]], dtype="U1")


def parse_name(name: str):
    shape, grid, ratio = name.rsplit("_", 2)
    m, n = (int(x) for x in grid.split("x"))
    return shape, m, n, float(ratio[1:])


@unittest.skipUnless(GOLDEN.is_file(), f"{GOLDEN} is not distributed with the package")
class TheBankIsWhatItClaims(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_sixty_ok_records_over_four_nonsquare_grids_and_three_ratios(self):
        self.assertEqual(len(self.cases), 60)
        self.assertTrue(all(rec["status"] == "OK" for rec in self.cases))
        self.assertEqual({(r["rows"], r["cols"]) for r in self.cases}, set(GRIDS))
        self.assertEqual({r["tas_ratio"] for r in self.cases}, set(RATIOS))
        self.assertTrue(all(r["rows"] != r["cols"] for r in self.cases))

    def test_the_written_image_is_the_placed_geometry(self):
        for rec in self.cases:
            with self.subTest(name=rec["name"]):
                shape, m, n, tas = parse_name(rec["name"])
                self.assertEqual((m, n, tas), (rec["rows"], rec["cols"], rec["tas_ratio"]))
                want = np.full((m, n), "1", dtype="U1")
                for r, c in shape_points(shape, m, n):
                    want[r, c] = "0"
                np.testing.assert_array_equal(img_from_record(rec), want)

    def test_reshape_img_transpose_flattens_row_major(self):
        """Octave's ``reshape(img', 1, [])`` -- the ``img`` field of BOTH v3.5
        banks -- is the ROW-major flatten of ``img``, measured against the
        rows Octave wrote one by one. ``test_v35_min_circle._img_to_char_matrix``
        documents it as column-major and undoes it with
        ``.reshape(cols, rows).T``: on a square that is a TRANSPOSE of the
        image the MEX saw; on these grids it would be garbage. The correct
        reconstruction is ``.reshape(rows, cols)`` with no transpose."""
        for rec in self.cases:
            with self.subTest(name=rec["name"]):
                self.assertEqual(rec["img"], "".join(rec["img_rows"]))
                rows, cols = rec["rows"], rec["cols"]
                flat = np.array(list(rec["img"]), dtype="U1")
                np.testing.assert_array_equal(flat.reshape(rows, cols), img_from_record(rec))
                self.assertFalse(np.array_equal(flat.reshape(cols, rows).T, img_from_record(rec)))


@unittest.skipUnless(GOLDEN.is_file(), f"{GOLDEN} is not distributed with the package")
class WhichAxisTheRealMexScales(unittest.TestCase):
    """Measured: the MEX divides the ROW index by tasRatio and reports that
    scaled row centre as ``ctx``; ``cty`` is the unscaled column centre."""

    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_ctx_is_the_scaled_ROW_centre_and_cty_the_unscaled_COLUMN_centre(self):
        for rec in self.cases:
            with self.subTest(name=rec["name"]):
                shape, m, n, tas = parse_name(rec["name"])
                pts = shape_points(shape, m, n)
                diam, ctx, cty = expected_circle((pts[0], pts[-1]), tas, scaled_axis="row")
                self.assertAlmostEqual(rec["diameter"], diam, places=9)
                self.assertAlmostEqual(rec["ctx"], ctx, places=9)
                self.assertAlmostEqual(rec["cty"], cty, places=9)

    def test_the_column_convention_is_rejected_by_every_record(self):
        """Decisiveness: the alternative (scale the column, report it as ctx)
        disagrees with the MEX on every one of the 60 records in at least
        one of the three outputs."""
        rejected = 0
        for rec in self.cases:
            shape, m, n, tas = parse_name(rec["name"])
            pts = shape_points(shape, m, n)
            diam, ctx, cty = expected_circle((pts[0], pts[-1]), tas, scaled_axis="col")
            agree = (math.isclose(rec["diameter"], diam, abs_tol=1e-9)
                     and math.isclose(rec["ctx"], ctx, abs_tol=1e-9)
                     and math.isclose(rec["cty"], cty, abs_tol=1e-9))
            if not agree:
                rejected += 1
        self.assertEqual(rejected, 60)


@unittest.skipUnless(GOLDEN.is_file(), f"{GOLDEN} is not distributed with the package")
class ThePortAgainstTheNonSquareMex(unittest.TestCase):
    """``cgal_min_r_v35`` fed the matrix the MEX saw (no transpose)."""

    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_port_matches_the_mex_on_every_nonsquare_record(self):
        """This is the test the V4 axis fix had to turn green. It failed on
        60 of 60 records before it, and it is the only bank that could fail
        at all -- every other v3.5 min-circle record is square."""
        checked = 0
        for rec in self.cases:
            with self.subTest(name=rec["name"]):
                diameter, ctx, cty = cgal_min_r_v35(img_from_record(rec), rec["tas_ratio"])
                self.assertAlmostEqual(diameter, rec["diameter"], places=9)
                self.assertAlmostEqual(ctx, rec["ctx"], places=9)
                self.assertAlmostEqual(cty, rec["cty"], places=9)
            checked += 1
        self.assertEqual(checked, 60)

    def test_the_transposed_feed_now_disagrees(self):
        """The mutation this fix removes, pinned in the other direction: the
        port fed the TRANSPOSE -- what ``_img_to_char_matrix`` used to build
        -- must now disagree. Without this, reverting either half of the fix
        alone would be caught only by the square bank going red, which reads
        as an unrelated regression rather than as this."""
        disagreed = 0
        for rec in self.cases:
            img = img_from_record(rec)
            if img.shape[0] == img.shape[1]:
                continue
            diameter, ctx, cty = cgal_min_r_v35(img.T, rec["tas_ratio"])
            if not (
                math.isclose(diameter, rec["diameter"], abs_tol=1e-9)
                and math.isclose(ctx, rec["ctx"], abs_tol=1e-9)
                and math.isclose(cty, rec["cty"], abs_tol=1e-9)
            ):
                disagreed += 1
        self.assertEqual(disagreed, 60)


if __name__ == "__main__":
    unittest.main()
