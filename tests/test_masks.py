# SPDX-License-Identifier: BSD-3-Clause
"""Stuck-diode masks: the assignment, the lookup, and the two silent failures.

``c(:,shadow_diode)='1'`` is three tokens of MATLAB and the widest-reaching
divergence in this port -- it edits the particle image before habit,
rejection, sizing and the enclosing circle all read it.  Most of what can go
wrong with it goes wrong *quietly*, so the quiet paths are what is pinned here:

* a mask file under a name the loader does not construct is simply not found,
  and the run proceeds unmasked with nothing recorded either way;
* an empty mask is written under a *different* name again
  (``...<orientation>empty.mat``), so it is not found either -- same outcome,
  reached by a second route;
* a diode number past the end of the array does not raise, it **widens** the
  image, and the width guard then ends the run part-way through the file.

Both silent paths are real for the ORACLES data, not hypothetical: the recovered
09/06/2016 masks are named ``diode.<date><time>.mat``, without the orientation
letter ``imgProc_sm.m:288`` appends, and their ``shadow_diode`` is empty.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe.masks import (
    MaskFileError,
    ShadowDiodeMask,
    find_shadow_diode_mask,
    load_shadow_diode_mask,
    matlab_mask_filename,
    orientation_from_infile,
    reilluminate,
)
from arrayprobe.matlab_compat import MatlabIndexError

DATA = Path(__file__).parent / "data"
FIXTURE = DATA / "shadow_diode_fixture.mat"
EMPTY_FIXTURE = DATA / "shadow_diode_empty_fixture.mat"

_LIT = ord("1")
_SHADOWED = ord("0")


def image(rows, cols, fill=_SHADOWED):
    return np.full((rows, cols), fill, dtype=np.uint8)


class ReilluminateTest(unittest.TestCase):
    def test_sets_whole_columns_lit(self):
        c = image(4, 8)
        out = reilluminate(c, [2, 5])
        np.testing.assert_array_equal(out[:, 1], np.full(4, _LIT))
        np.testing.assert_array_equal(out[:, 4], np.full(4, _LIT))
        # Everything else untouched.
        untouched = [k for k in range(8) if k not in (1, 4)]
        np.testing.assert_array_equal(out[:, untouched], image(4, len(untouched)))

    def test_indices_are_one_based(self):
        # MATLAB's shadow_diode holds 1-based diode numbers. Off by one here
        # would re-illuminate the neighbouring photodiode, which is both wrong
        # and entirely plausible-looking in the output.
        out = reilluminate(image(2, 4), [1])
        self.assertEqual(out[0, 0], _LIT)
        self.assertEqual(out[0, 1], _SHADOWED)

    def test_empty_mask_is_a_no_op(self):
        # `c(:,[])='1'` changes nothing, which is what makes an empty mask
        # indistinguishable from no mask -- the ORACLES 2D-S case.
        c = image(3, 6)
        np.testing.assert_array_equal(reilluminate(c, []), image(3, 6))
        np.testing.assert_array_equal(
            reilluminate(image(3, 6), np.zeros(0)), image(3, 6)
        )

    def test_accepts_a_mask_object(self):
        mask = load_shadow_diode_mask(FIXTURE)
        c = reilluminate(image(2, 128), mask)
        diodes = sorted(int(d) for d in np.asarray(mask.diodes).ravel())
        for d in diodes:                     # 1-based diode numbers
            self.assertEqual(c[0, d - 1], _LIT)
        other = next(k for k in range(1, 129) if k not in diodes)
        self.assertEqual(c[0, other - 1], _SHADOWED)

    def test_out_of_range_widens_instead_of_raising(self):
        # Measured in Octave: c=['0101';'1010']; c(:,[2 6])='1' returns a 2x6
        # char array whose fifth column is char(0). MATLAB grows the array; it
        # does not error. imgProc_sm.m:272-276 then finds the width wrong,
        # prints and RETURNS, so a single bad diode number truncates the run.
        out = reilluminate(image(2, 4), [2, 6])
        self.assertEqual(out.shape, (2, 6))
        np.testing.assert_array_equal(out[:, 5], np.full(2, _LIT))
        np.testing.assert_array_equal(out[:, 4], np.zeros(2, dtype=np.uint8))

    def test_zero_and_negative_and_fractional_raise(self):
        for bad in ([0], [-1], [2.5]):
            with self.subTest(index=bad), self.assertRaises(MatlabIndexError):
                reilluminate(image(2, 4), bad)

    def test_column_and_row_vectors_agree(self):
        col = reilluminate(image(2, 8), np.array([[3], [5]], dtype=float))
        row = reilluminate(image(2, 8), np.array([3, 5], dtype=float))
        np.testing.assert_array_equal(col, row)


class MaskLoadingTest(unittest.TestCase):
    def test_loads_diodes_and_provenance(self):
        m = load_shadow_diode_mask(FIXTURE)
        self.assertEqual(len(m), 9)
        self.assertTrue(m)
        self.assertEqual(m.date, "151205")
        self.assertEqual(m.time, "000000")
        self.assertTrue(m.matches("151205", "000000"))
        self.assertFalse(m.matches("160906", "064403"))

    def test_empty_mask_is_falsey(self):
        # Deliberately mirrors MATLAB's isempty(shadow_diode) test rather than
        # "an object exists", so `if mask:` means what it means in the MATLAB.
        m = load_shadow_diode_mask(EMPTY_FIXTURE)
        self.assertEqual(len(m), 0)
        self.assertFalse(m)

    def test_missing_shadow_diode_variable_is_named(self):
        # A valid MAT-file that simply lacks the variable imgProc_sm.m:289
        # loads by name. Built by dropping the third compressed element from
        # the fixture -- MATLAB writes one per variable, so the truncation is a
        # well-formed file containing only `date` and `time`.
        raw = FIXTURE.read_bytes()
        head, rest = raw[:128], raw[128:]
        pos, kept = 0, 0
        while kept < 2:
            nbytes = int.from_bytes(rest[pos + 4:pos + 8], "little")
            pos += 8 + nbytes
            kept += 1
        partial = DATA / "_tmp_no_shadow_diode.mat"
        partial.write_bytes(head + rest[:pos])
        try:
            with self.assertRaises(MaskFileError) as cm:
                load_shadow_diode_mask(partial)
            self.assertIn("shadow_diode", str(cm.exception))
        finally:
            partial.unlink()

    def test_mask_object_can_be_built_directly(self):
        m = ShadowDiodeMask(diodes=np.array([1.0, 2.0]), date=None, time=None,
                            source=None)
        self.assertEqual(len(m), 2)


class MaskLookupTest(unittest.TestCase):
    """``exist([path '/' 'diode.' flight file '.' infile(end-4) '.mat'],'file')``."""

    def test_filename_matches_matlab(self):
        self.assertEqual(
            matlab_mask_filename("160906", "064403", "V"),
            "diode.160906064403.V.mat",
        )

    def test_orientation_is_the_fifth_character_from_the_end(self):
        self.assertEqual(orientation_from_infile("base160906064403.V.cdf"), "V")
        self.assertEqual(orientation_from_infile("base160906064403.H.cdf"), "H")
        # It is a position, not a parse: on a name that does not end in X.cdf it
        # returns whatever sits there, and the lookup then quietly finds nothing.
        # "something.nc4" -> the fifth character from the end is 'g'.
        self.assertEqual(orientation_from_infile("something.nc4"), "g")

    def test_found_when_named_exactly(self):
        work = DATA / "_tmp_masklookup"
        work.mkdir(exist_ok=True)
        try:
            target = work / "diode.151205000000.V.mat"
            target.write_bytes(FIXTURE.read_bytes())
            m = find_shadow_diode_mask(work, "151205", "000000",
                                       "base151205000000.V.cdf")
            self.assertIsNotNone(m)
            self.assertEqual(len(m), 9)
        finally:
            for p in work.iterdir():
                p.unlink()
            work.rmdir()

    def test_missing_file_returns_none_silently(self):
        m = find_shadow_diode_mask(DATA, "999999", "999999",
                                   "base999999999999.V.cdf")
        self.assertIsNone(m)

    def test_the_two_naming_traps_both_miss(self):
        """Neither name the ORACLES chain actually produced is found.

        ``find_shadow_diodes.m:104,106`` writes
        ``diode.<date><time>.<orientation>.mat`` for a non-empty mask and
        ``diode.<date><time>.<orientation>empty.mat`` for an empty one -- and
        the recovered 09/06/2016 files use a third form with no orientation
        letter at all.  Only the first is ever loaded.
        """
        work = DATA / "_tmp_naming"
        work.mkdir(exist_ok=True)
        try:
            for name in ("diode.151205000000.mat",       # no orientation
                         "diode.151205000000.Vempty.mat"):  # the empty branch
                (work / name).write_bytes(FIXTURE.read_bytes())
            self.assertIsNone(
                find_shadow_diode_mask(work, "151205", "000000",
                                       "base151205000000.V.cdf"),
                "a mask under either of these names must NOT be found -- that "
                "silence is the behaviour being reproduced",
            )
        finally:
            for p in work.iterdir():
                p.unlink()
            work.rmdir()


if __name__ == "__main__":
    unittest.main()
