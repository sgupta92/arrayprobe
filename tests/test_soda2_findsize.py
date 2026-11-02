# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.findsize`` against GDL running SODA-2's own `.pro`.

The golden is real output from `soda2_findsize.pro` run unmodified under GDL
(`gdl_oracle/run_soda2_findsize_bank.py`), 22 cases, 12 of them needing no
shim at all.

Ten cases have more than two slices, which sends `aspect_ratio` into IDL's
`ERODE`; GDL 1.1.2 has none, so those run against the bank's unconfirmed
4-connected shim and are labelled `zero_outside_shim_unconfirmed` in the
golden. `TheShimmedCasesAreLabelled` below asserts the labelling itself, so a
future reader cannot mistake a shimmed case for layer-2 evidence.
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.findsize import (
    RESHAPES_CALLER_INPUT,
    FindSizeResult,
    soda2_findsize,
)

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_findsize_golden.json"

#: The eleven float fields, and the four integer ones. Listed rather than
#: introspected: a field silently dropped from the result class should fail
#: this suite, and `dataclasses.fields()` would follow the drop.
FLOAT_FIELDS = ["diam", "xsize", "ysize", "areasize", "ar", "arfilled",
                "aspr", "orientation", "xextent", "oned", "twod"]
INT_FIELDS = ["allin", "centerin", "edgetouch", "perimeterarea"]


def _image(rows: list[str]) -> np.ndarray:
    """`rows[slice][diode]` of '.' and '#' -> a `(slices, diodes)` array.

    That layout is the port's convention throughout and is the TRANSPOSE of
    IDL's own `img[x, y]`; getting it backwards is the first mistake this
    module made, and it failed loudly rather than quietly only because the
    bank's images are not square.
    """
    ny, nx = len(rows), len(rows[0])
    im = np.zeros((ny, nx), dtype=np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                im[y, x] = 1
    return im


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking the port against IDL.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def _run(self, case):
        im = _image(case["rows"])
        if case["pass_1d"]:
            im = im.reshape(im.shape[1])
        # An `integer_res` case is the point of finding S3-d and must be fed
        # integer resolutions; every other case gets FLOAT, which is what
        # probespecs holds.
        integer = case["name"].startswith("integer_resolution")
        cast = np.int32 if integer else np.float32
        return soda2_findsize(im, cast(case["xres"]), cast(case["yres"]),
                              voidarea=np.float32(case["voidarea"]))

    def test_the_bank_reaches_the_branches_that_matter(self):
        names = {c["name"] for c in self.cases}
        for needed in ("single_pixel", "two_pixels_one_slice",
                       "two_slices_square", "solid_block_5x3", "hollow_ring",
                       "hollow_ring_with_voidarea", "diagonal_streak",
                       "touching_left_edge", "touching_right_edge",
                       "touching_both_edges", "left_edge_but_narrow_extent",
                       "gap_makes_oned_and_twod_differ",
                       "tas_adjust_two_to_one", "tas_adjust_half",
                       "hvps_resolution", "empty_image",
                       "one_dimensional_input",
                       "integer_resolution_zeroes_everything",
                       "float_resolution_same_shape"):
            self.assertIn(needed, names)

    def test_every_case_matches_idl_exactly(self):
        """Exactly, on all fifteen fields plus the centre.

        No tolerance: the port models IDL's types, so equality is the honest
        assertion. It was NOT equal on the first attempt -- `x` was taken from
        the FLOAT struct copy rather than from `circle.center`'s DOUBLE, and
        the three edge-touching cases missed by one float32 ulp. A tolerance
        would have hidden that.
        """
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                out = self._run(case)
                for name in FLOAT_FIELDS:
                    got, want = float(getattr(out, name)), case[name]
                    if math.isnan(want):
                        self.assertTrue(math.isnan(got), name)
                    else:
                        self.assertEqual(got, want, name)
                for name in INT_FIELDS:
                    self.assertEqual(int(getattr(out, name)), case[name], name)
                self.assertEqual(float(out.c[0]), case["cx"])
                self.assertEqual(float(out.c[1]), case["cy"])
            checked += 1
        self.assertGreaterEqual(checked, 22)

    def test_the_shimmed_cases_are_labelled_as_such(self):
        """Twelve cases are real IDL and ten run against an unconfirmed
        ERODE shim. The distinction is the difference between layer 2 and
        layer 3 evidence, so it is asserted rather than left in prose."""
        unshimmed = [c["name"] for c in self.cases
                     if c["erode_source"] == "gdl"]
        shimmed = [c for c in self.cases if c["erode_source"] == "shim"]
        self.assertGreaterEqual(len(unshimmed), 10,
                                "too few cases are real, unshimmed IDL")
        for case in shimmed:
            with self.subTest(case=case["name"]):
                self.assertIn("unconfirmed", case["erode_rule"])
                self.assertGreater(len(case["rows"]), 2,
                                   "only >2-slice images should need the shim")


class TheSevenSizesAreDifferentQuestions(unittest.TestCase):
    """A port that computed one size and copied it into the others would pass
    a surprising number of the bank's cases. These say what each one means."""

    def _out(self, rows, xres=10.0, yres=10.0, voidarea=0.0):
        return soda2_findsize(_image(rows), np.float32(xres),
                              np.float32(yres), voidarea=np.float32(voidarea))

    def test_oned_latches_across_slices_and_twod_does_not(self):
        """`oned` counts every diode shadowed anywhere; `twod` takes the
        fullest single slice. Both ignore gaps, per Lyle Lilie 12/2020."""
        out = self._out(["#...#....",
                         ".##......"])
        self.assertEqual(float(out.oned), 40.0, "diodes 0,1,2,4 -> 4 * xres")
        self.assertEqual(float(out.twod), 20.0, "fullest slice holds 2")

    def test_xsize_is_inclusive_of_both_end_diodes(self):
        out = self._out(["..###...."])
        self.assertEqual(float(out.xsize), 30.0)

    def test_xextent_is_the_largest_span_within_one_slice(self):
        """Korolev's `Ly`, and NOT the same as `xsize`: it is per-slice, so a
        particle whose diodes are spread across different slices has a
        smaller `xextent` than `xsize`."""
        out = self._out(["#...#....",
                         ".##......"])
        self.assertEqual(float(out.xsize), 50.0, "diodes 0..4 overall")
        self.assertEqual(float(out.xextent), 50.0)

    def test_every_size_scales_with_the_resolution(self):
        """A port that hard-coded a 10 um pixel would pass most of the bank."""
        small = self._out(["..####..."])
        big = self._out(["..####..."], xres=150.0, yres=150.0)
        for name in ("xsize", "oned", "twod", "xextent", "diam"):
            with self.subTest(field=name):
                self.assertAlmostEqual(
                    float(getattr(big, name)) / float(getattr(small, name)),
                    15.0, places=4)

    def test_areasize_corrects_for_a_partial_image_and_diam_does_not(self):
        """`areasize = diam * sqrt(ar)`, and `ar` is what the truncation
        geometry adjusts. On an edge-touching particle they part company."""
        out = self._out(["###......",
                         "###......",
                         "###......"])
        self.assertEqual(out.allin, 0)
        self.assertLess(float(out.areasize), float(out.diam))


class TheZeroAreaEarlyReturn(unittest.TestCase):
    """Finding S3-e: `:13` hands back the predefined struct, whose declared
    defaults look like measurements."""

    def test_an_empty_image_reports_centerin_true_and_allin_false(self):
        out = soda2_findsize(_image(["........."]), np.float32(10.0),
                             np.float32(10.0))
        self.assertEqual(out.centerin, 1,
                         "the DEFAULT, not a measurement -- nothing was checked")
        self.assertEqual(out.allin, 0)
        for name in FLOAT_FIELDS:
            with self.subTest(field=name):
                self.assertEqual(float(getattr(out, name)), 0.0)

    def test_the_defaults_are_the_declared_struct(self):
        """Asserted against a freshly constructed result, so the early return
        cannot drift away from `:9-10`'s declaration without failing here."""
        empty = soda2_findsize(_image(["........."]), np.float32(10.0),
                               np.float32(10.0))
        fresh = FindSizeResult()
        for name in FLOAT_FIELDS + INT_FIELDS:
            with self.subTest(field=name):
                self.assertEqual(float(getattr(empty, name)),
                                 float(getattr(fresh, name)))


class AnIntegerResolutionZeroesEverything(unittest.TestCase):
    """Finding S3-d, and the reason it is not hypothetical: this bank's own
    generator hit it before it was a case."""

    ROWS = ["..###....", "..###...."]

    def test_integer_resolutions_take_the_zero_area_return(self):
        out = soda2_findsize(_image(self.ROWS), np.int32(10), np.int32(5))
        self.assertEqual(float(out.diam), 0.0)
        self.assertEqual(float(out.oned), 0.0)
        self.assertEqual(out.centerin, 1, "the default, on a real particle")

    def test_float_resolutions_on_the_identical_particle_do_not(self):
        out = soda2_findsize(_image(self.ROWS), np.float32(10.0),
                             np.float32(5.0))
        self.assertGreater(float(out.diam), 0.0)
        self.assertEqual(float(out.oned), 30.0)

    def test_one_float_operand_is_enough_to_rescue_it(self):
        """Which is exactly why `soda2_samplearea`'s `float()` casts work,
        and exactly what this routine is missing."""
        out = soda2_findsize(_image(self.ROWS), np.float32(10.0), np.int32(5))
        self.assertGreater(float(out.diam), 0.0)

    def test_an_integer_ratio_of_one_or_more_is_unharmed(self):
        """The defect only bites when `yres < xres`. A port that rejected all
        integer input would be wrong about the common case."""
        out = soda2_findsize(_image(self.ROWS), np.int32(10), np.int32(20))
        self.assertGreater(float(out.diam), 0.0)


class TheCallerInputIsNotMutated(unittest.TestCase):
    """Finding S3-c, from the port's side: IDL reforms `img` in place because
    a named variable is passed by reference. Measured under GDL -- a 1-D array
    of 9 goes in and comes back `9x1`. This port does not do that, and says so
    in a name rather than only in prose."""

    def test_the_flag_records_the_divergence(self):
        self.assertFalse(RESHAPES_CALLER_INPUT)

    def test_a_one_dimensional_input_is_left_alone(self):
        im = _image(["..###...."]).reshape(9)
        before = im.shape
        soda2_findsize(im, np.float32(10.0), np.float32(10.0))
        self.assertEqual(im.shape, before)

    def test_a_one_dimensional_input_still_gives_the_same_answer(self):
        """The reform is about the caller's variable, not about the result:
        1-D and its (1, n) equivalent must agree."""
        flat = soda2_findsize(_image(["..###...."]).reshape(9),
                              np.float32(10.0), np.float32(10.0))
        shaped = soda2_findsize(_image(["..###...."]), np.float32(10.0),
                                np.float32(10.0))
        self.assertEqual(float(flat.diam), float(shaped.diam))
        self.assertEqual(float(flat.oned), float(shaped.oned))


class CenterInIsDecidedByExtent(unittest.TestCase):
    """`:52` and `:58` use the y-EXTENT of the end diode, with the
    shadow-count version commented out directly above each. `ge`, not `gt`."""

    def _out(self, rows):
        return soda2_findsize(_image(rows), np.float32(10.0), np.float32(10.0))

    def test_a_touching_diode_with_the_greatest_extent_clears_centerin(self):
        out = self._out(["###......",
                         "###......",
                         "###......"])
        self.assertEqual(out.edgetouch, 1)
        self.assertEqual(out.centerin, 0)

    def test_edgetouch_is_a_two_bit_sum(self):
        left = self._out(["###......", "###......", "###......"])
        right = self._out(["......###", "......###", "......###"])
        both = self._out(["#########", "#########", "#########"])
        self.assertEqual((left.edgetouch, right.edgetouch, both.edgetouch),
                         (1, 2, 3))

    def test_the_tie_goes_against_the_particle(self):
        """`ge` means an end diode whose extent merely EQUALS the maximum
        clears `centerin`. With `gt` the same particle would be kept."""
        out = self._out(["#########",
                         "#########",
                         "#########"])
        self.assertEqual(out.centerin, 0)


class TheTruncationRunsInDouble(unittest.TestCase):
    """Finding S3-f. `:76` takes `x` from `circle.center[0]`, a DOUBLE, while
    the all-in branch has no DOUBLE operand and stays FLOAT."""

    def test_the_edge_touching_answer_needs_the_double_centre(self):
        """Pinned by value, against the golden's own number. Recomputing `ar`
        from the FLOAT struct copy gives 0.21490271389484406 instead of
        0.21490272879600525 -- one float32 ulp, and wrong."""
        im = np.zeros((2, 9), dtype=np.uint8)
        im[0, 0] = 1
        im[0, 4] = 1
        im[1, 1] = 1
        im[1, 2] = 1
        out = soda2_findsize(im, np.float32(10.0), np.float32(10.0))
        self.assertEqual(out.allin, 0)
        self.assertEqual(float(out.ar), 0.21490272879600525)

    def test_the_result_fields_are_single_precision_whatever_the_branch(self):
        """The struct declares `0.0`, so the answer is narrowed on assignment
        even when it was computed in double."""
        out = soda2_findsize(_image(["..###....", "..###...."]),
                             np.float32(10.0), np.float32(10.0))
        for name in ("diam", "ar", "areasize", "aspr"):
            with self.subTest(field=name):
                self.assertEqual(np.asarray(getattr(out, name)).dtype,
                                 np.float32)


if __name__ == "__main__":
    unittest.main()
