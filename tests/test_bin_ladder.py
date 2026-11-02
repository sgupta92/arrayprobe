# SPDX-License-Identifier: BSD-3-Clause
"""The 2D-S bin ladder must match MATLAB's colon operator bit for bit.

WHAT THIS PROTECTS.  ``sizeDist.m:134`` builds the ladder as
``kk = diodesize/2 : diodesize : (num_bins+0.6)*diodesize``.  MATLAB's colon
operator fills the result **from both ends toward the middle**: the lower half
as ``start + k*step``, the upper half as ``last - (m-k)*step``.  Those two
routes disagree in the last bit, so computing ``start + k*step`` throughout --
which is what the port did until 2026-09-03, and what ``np.arange`` and
Octave's colon both do -- gets the upper half of the ladder wrong by one ULP.

Measured when this was found: 34 of the 129 ORACLES 2D-S edges differed from
the archived product, each by 2.2e-16 mm, every one of them in the upper half.
Zero particles in ``proc.base160906064403.H.nc`` fell inside any of those
1-ULP intervals, so no binned count moved -- but the four edge variables the
port *writes* (``Bin Minimum``, ``Bin Maximum``, ``Bin Midpoints``,
``Bin Width``) were not byte-identical to MATLAB's, and this project's claim
is byte-identity.

THE TWO SIDES COME FROM DIFFERENT PLACES, which is the point.  One side is
the port's own construction; the other is a fixture lifted from the archived
MATLAB product's bytes (``data/make_bin_ladder_fixture.py``).  Recomputing the
port's formula on both sides would test nothing -- the failure this project
has a doctrine about.

**Octave cannot stand in for the product here.**  Octave's colon agrees with
the naive construction, so the project's usual differential oracle confirms
the defect rather than catching it.  This is the first measured case where
Octave and MATLAB disagree on a value the port writes.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe.constants import bin_edges, bin_width

_FIXTURE = Path(__file__).resolve().parent / "data" / "oracles_2ds_bin_ladder.txt"


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: oracles_2ds_bin_ladder.txt is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "oracles_2ds_bin_ladder.txt").exists():
    raise unittest.SkipTest(
        "Oracles_2ds_bin_ladder.txt is not distributed with the package")


def _load_fixture() -> np.ndarray:
    lines = _FIXTURE.read_text(encoding="utf-8").splitlines()
    return np.array([float(ln) for ln in lines if not ln.startswith("#")],
                    dtype=np.float64)


class TestOraclesBinLadder(unittest.TestCase):
    """The ORACLES 2D-S ladder, against MATLAB's own written edges."""

    def setUp(self) -> None:
        self.matlab_kk = _load_fixture()
        self.kk = np.asarray(bin_edges("otherwise", "2DS"), dtype=np.float64)

    def test_fixture_is_the_expected_ladder(self) -> None:
        """Guard the fixture itself, so a corrupted one fails loudly."""
        self.assertEqual(self.matlab_kk.size, 129)
        self.assertEqual(self.matlab_kk[0], 0.005)
        self.assertEqual(self.matlab_kk[-1], 1.285)

    def test_port_ladder_is_bit_identical_to_matlab(self) -> None:
        """Every one of the 129 edges, exactly -- not ``allclose``."""
        kk = self.kk
        self.assertEqual(kk.size, self.matlab_kk.size)
        bad = np.flatnonzero(kk != self.matlab_kk)
        self.assertEqual(
            bad.size, 0,
            f"{bad.size} of {kk.size} edges differ from the MATLAB product; "
            f"first at index {bad[0] if bad.size else '-'}: "
            f"port {kk[bad[0]]!r} vs MATLAB {self.matlab_kk[bad[0]]!r}"
            if bad.size else "",
        )

    def test_derived_edge_arrays_are_bit_identical(self) -> None:
        """bin_min/bin_max/binwidth are what the product actually carries."""
        kk = self.kk
        for name, got, want in (
            ("bin_min", kk[:-1], self.matlab_kk[:-1]),
            ("bin_max", kk[1:], self.matlab_kk[1:]),
            ("binwidth", bin_width("otherwise", "2DS"), np.diff(self.matlab_kk)),
        ):
            with self.subTest(name):
                self.assertTrue(np.array_equal(got, want),
                                f"{name} is not bit-identical to MATLAB's")

    def test_naive_construction_would_fail(self) -> None:
        """The bug this test exists for must actually be detectable.

        A test that passes against both the right and the wrong construction
        protects nothing.  Rebuild the ladder the naive way and assert it
        disagrees -- in the upper half, by one ULP, exactly as measured.
        """
        m = 128
        k = np.arange(m + 1, dtype=np.float64)
        naive = 0.005 + 0.010 * k
        bad = np.flatnonzero(naive != self.matlab_kk)
        self.assertEqual(bad.size, 34,
                         "the naive construction no longer differs as measured")
        self.assertTrue((bad > m // 2).all(),
                        "differences should all be in the upper half")
        self.assertLess(float(np.abs(naive - self.matlab_kk).max()), 1e-15)


if __name__ == "__main__":
    unittest.main()
