# SPDX-License-Identifier: BSD-3-Clause
"""``particle_perimeter`` against the value the REAL MATLAB file produced.

**This closes the second of the two direct-oracle gaps** that stood from
S0 onward. ``ParticlePerimeter.m`` is pure base MATLAB -- no netCDF, no MEX, no
toolbox -- so Octave has always been able to run it unmodified; it simply never
had been.

What the port had instead. ``tests/test_particle_perimeter.py`` hand-traces a
dozen small shapes and cross-checks two independently written implementations,
``particle_perimeter`` (a line-by-line transcription) against
``particle_perimeter_setbased`` (a coordinate-set re-derivation). Two
implementations disagreeing would have been informative; two agreeing says
nothing about whether either matches the original. Both are asserted against
the original here, because a shim that reproduces the port's own reading of
MATLAB is not an oracle.

What the real input is. ``imgProc_sm.m:846`` calls ``ParticlePerimeter(c)``,
and ``c`` is built by ``dec2bin`` at ``:556-563``: a CHAR matrix of ``'0'``
(48, shadowed) and ``'1'`` (49, background). The bank feeds char matrices for
that reason, and the golden stores each one row-major so the shape can be
rebuilt here exactly.

``ParticlePerimeter.m`` is byte-identical in stock v3.1.4, the ORACLES variant
tree and upstream v3.5, so these values speak for every version. Bank:
``octave_oracle/run_perimeter_bank.py``. The golden is tracked so this runs on
a clone with no Octave installed.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from arrayprobe.particle_perimeter import (
    BACKGROUND,
    SHADOWED,
    particle_perimeter,
    particle_perimeter_from_mask,
    particle_perimeter_setbased,
)

GOLDEN = (Path(__file__).resolve().parent / "data"
          / "particle_perimeter_octave_golden.json")


def _load():
    return json.loads(GOLDEN.read_text())


def _image(rec: dict) -> list[list[int]]:
    """Rebuild the case as ASCII codes, the form the port's API takes."""
    flat, rows, cols = rec["img"], rec["rows"], rec["cols"]
    assert len(flat) == rows * cols, rec["name"]
    return [[ord(flat[i * cols + j]) for j in range(cols)] for i in range(rows)]


class ParticlePerimeterOracleTest(unittest.TestCase):
    """Every assertion here compares against a value MATLAB's own code produced."""

    @classmethod
    def setUpClass(cls):
        cls.records = _load()
        cls.ok = [r for r in cls.records if r["status"] == "OK"]

    def test_bank_is_present_and_substantial(self):
        self.assertGreaterEqual(len(self.ok), 50)
        self.assertEqual(len(self.ok), len(self.records))  # nothing errors here

    def test_the_transcription_matches_the_original_on_every_case(self):
        for rec in self.ok:
            with self.subTest(rec["name"]):
                self.assertEqual(particle_perimeter(_image(rec)),
                                 int(rec["perimeter"]))

    def test_the_independent_implementation_matches_it_too(self):
        """``particle_perimeter_setbased`` exists to be a second opinion.

        Until this module it only ever agreed with its sibling. Asserting it
        against MATLAB is what makes it a second opinion about the original
        rather than about the transcription.
        """
        for rec in self.ok:
            with self.subTest(rec["name"]):
                self.assertEqual(particle_perimeter_setbased(_image(rec)),
                                 int(rec["perimeter"]))

    def test_the_mask_wrapper_agrees_wherever_the_image_is_binary(self):
        """``particle_perimeter_from_mask`` maps True to ``SHADOWED``.

        It can only be asserted on cases whose codes are exactly 48 and 49; the
        deliberate non-binary case below is excluded by construction, and
        skipping it silently is what this filter avoids doing.
        """
        checked = 0
        for rec in self.ok:
            img = _image(rec)
            if any(v not in (SHADOWED, BACKGROUND) for row in img for v in row):
                continue
            mask = [[v == SHADOWED for v in row] for row in img]
            with self.subTest(rec["name"]):
                self.assertEqual(particle_perimeter_from_mask(mask),
                                 int(rec["perimeter"]))
            checked += 1
        self.assertGreaterEqual(checked, 50)

    def test_the_degenerate_shapes_are_in_the_bank_and_return_zero(self):
        """0x0, 3x0 and 0x5 -- where a transcription diverges silently.

        MATLAB pads to ``(m+2) x (n+2)`` and then loops ``2:m+1`` by ``2:n+1``,
        so an empty dimension makes the loop empty and the answer 0. The port
        reaches the same answer by a different route (it derives ``n`` from the
        first row and so calls a 0x5 image 0x0), which is why the equality is
        measured rather than argued from the code.
        """
        by_name = {r["name"]: r for r in self.ok}
        for name in ("empty_0x0", "zero_columns_3x0", "zero_rows_0x5"):
            rec = by_name[name]
            with self.subTest(name):
                self.assertEqual(int(rec["perimeter"]), 0)
                self.assertEqual(particle_perimeter(_image(rec)), 0)

    def test_a_hole_is_not_counted_and_an_enclosed_pixel_is_not_boundary(self):
        """The two properties that make this a perimeter rather than an area.

        ``ring_5x5`` is a 5x5 frame: all 16 pixels touch background, and the
        3x3 hole contributes nothing. ``ring_7x7_with_core`` is the only case
        in the bank with a pixel enclosed on all four sides, so it is the only
        one that can catch an implementation that counts every shadowed pixel.
        """
        by_name = {r["name"]: r for r in self.ok}
        self.assertEqual(int(by_name["ring_5x5"]["perimeter"]), 16)
        core = by_name["ring_7x7_with_core"]
        shadowed = sum(1 for row in _image(core) for v in row if v == SHADOWED)
        self.assertLess(int(core["perimeter"]), shadowed)

    def test_a_code_other_than_48_counts_as_background(self):
        """The port's docstring claims "any other value is background".

        ``non_binary_char_50`` puts a ``'2'`` at the centre of a solid 5x5
        block. If 50 were treated as shadowed the answer would be 16 (the
        centre enclosed); as background it is 20, because the eight pixels
        around it all gain a background neighbour. This is the claim checked
        against the original instead of restated.
        """
        rec = next(r for r in self.ok if r["name"] == "non_binary_char_50")
        self.assertEqual(int(rec["perimeter"]), 20)
        self.assertEqual(particle_perimeter(_image(rec)), 20)

    def test_full_width_probe_slices_are_covered(self):
        """128 diodes is the real slice width for both ORACLES probes.

        Every case that reaches ``:846`` in a real run is this shape, so a bank
        of small hand-drawn shapes alone would leave the live geometry untested.
        """
        by_name = {r["name"]: r for r in self.ok}
        for name in ("wide_particle_20x128", "edge_touching_12x128",
                     "full_slice_3x128"):
            with self.subTest(name):
                self.assertEqual(by_name[name]["cols"], 128)
                self.assertEqual(particle_perimeter(_image(by_name[name])),
                                 int(by_name[name]["perimeter"]))

    def test_the_random_blobs_are_not_all_trivial(self):
        """A bank of empty or saturated blobs would pass without measuring.

        The seeded shapes must span a real range of perimeters, or the thirty
        random cases are thirty copies of the same assertion.
        """
        randoms = [int(r["perimeter"]) for r in self.ok
                   if r["name"].startswith("random_")]
        self.assertGreaterEqual(len(randoms), 30)
        self.assertGreater(max(randoms), 4 * min(randoms))
