# SPDX-License-Identifier: BSD-3-Clause
"""Acceptance: the port against Octave running the unmodified ``dropsize.m``.

``dropsize.m`` is pure base MATLAB -- no MEX, no netCDF, no toolbox, no graphics
-- so Octave runs it exactly as it stands, and this module asserts the port
reproduces its output on every case in the bank.  The workflow mirrors the habit/reject oracle's:

1. ``octave_oracle/make_dropsize_cases.py`` writes
   ``tests/data/s1c_dropsize_cases.txt``, 127 argument tuples chosen to reach
   every branch of the function and both ends of both lookup tables.
2. ``octave_oracle/run_s1c_oracle.m`` runs the MATLAB over them under Octave and
   writes ``tests/data/s1c_octave_golden.csv``.
3. This module asserts the Python reproduces every field, exactly.

Both fixtures are **tracked**, so the suite runs on a machine with no Octave --
the S0 lesson, where a gitignored oracle made the whole acceptance suite skip
silently on a fresh clone.

Exactness is the right bar.  ``dropsize`` is double arithmetic throughout, and
every operation in it -- ``round``, ``sqrt``, ``exp``, ``log``, and the four
arithmetic operators -- is IEEE-754 correctly rounded or specified to be, so a
transcription that agrees at all should agree in the last bit.  A tolerance here
would hide exactly the class of error this oracle exists to catch: a
misremembered table entry or an off-by-one in the index arithmetic changes the
result in the third decimal, not the seventeenth.
"""

from __future__ import annotations

import csv
import math
import unittest
from pathlib import Path

from arrayprobe.dropsize import dropsize
from arrayprobe.matlab_compat import MatlabIndexError

DATA = Path(__file__).parent / "data"
CASES = DATA / "s1c_dropsize_cases.txt"
GOLDEN = DATA / "s1c_octave_golden.csv"

#: The seven returns, in the order ``dropsize.m:1`` declares them and the order
#: the golden CSV carries them.
OUTPUTS = (
    "center_in",
    "axis_ratio",
    "diameter_circle_fit",
    "diameter_horiz_chord",
    "diameter_vert_chord",
    "diameter_horiz_mean",
    "diameter_spheroid",
)


def load_cases():
    """Read the input bank into ``{name: (eight arguments)}``."""
    cases = {}
    for line in CASES.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        cases[parts[0]] = tuple(float(p) for p in parts[1:])
    return cases


def load_golden():
    with GOLDEN.open(newline="") as fh:
        return {row["name"]: row for row in csv.DictReader(fh)}


class TestFixturesPresent(unittest.TestCase):
    """The fixtures are tracked; their absence is a failure, never a skip."""

    def test_both_fixtures_exist(self):
        self.assertTrue(CASES.is_file(), f"missing tracked fixture {CASES}")
        self.assertTrue(GOLDEN.is_file(), f"missing tracked fixture {GOLDEN}")

    def test_every_case_has_a_golden_row(self):
        cases, golden = load_cases(), load_golden()
        self.assertEqual(
            set(cases), set(golden),
            "the input bank and the golden output have drifted apart; "
            "regenerate both together",
        )

    def test_bank_is_not_trivially_small(self):
        self.assertGreaterEqual(len(load_cases()), 100)


class TestAgainstOctave(unittest.TestCase):
    """Every case, every output, bit-exact."""

    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()
        cls.golden = load_golden()

    def test_all_cases_bit_exact(self):
        mismatches = []
        n_ok = 0
        for name, args in sorted(self.cases.items()):
            row = self.golden[name]
            if row["status"] == "ERROR":
                continue
            got = dropsize(*args)
            n_ok += 1
            for field in OUTPUTS:
                want = float(row[field])
                mine = float(getattr(got, field))
                if math.isnan(want):
                    if not math.isnan(mine):
                        mismatches.append(f"{name}.{field}: want NaN, got {mine!r}")
                elif mine != want:
                    mismatches.append(
                        f"{name}.{field}: want {want!r}, got {mine!r} "
                        f"(delta {mine - want!r})"
                    )
        self.assertEqual([], mismatches, f"{len(mismatches)} mismatches over {n_ok} cases")
        self.assertGreater(n_ok, 100)

    def test_matlab_errors_are_reproduced_as_errors(self):
        """A case that kills MATLAB must raise here, not return a number.

        Returning something plausible where the original died is the failure
        mode the port most needs to avoid: it turns a run that never happened
        into output that looks real.
        """
        n_error = 0
        for name, args in sorted(self.cases.items()):
            if self.golden[name]["status"] != "ERROR":
                continue
            n_error += 1
            with self.assertRaises(MatlabIndexError, msg=f"{name} should have raised"):
                dropsize(*args)
        self.assertEqual(3, n_error, "expected the three negative-chord cases")

    def test_no_case_silently_raises(self):
        """The converse: a case MATLAB survived must not raise here."""
        for name, args in sorted(self.cases.items()):
            if self.golden[name]["status"] == "ERROR":
                continue
            try:
                dropsize(*args)
            except Exception as exc:  # noqa: BLE001 -- the point is to catch all
                self.fail(f"{name} raised {exc!r} where MATLAB returned a value")


class TestBranchCoverage(unittest.TestCase):
    """The bank must actually reach all six branches, not just claim to.

    Coverage is recomputed from the bank on every run, so a future edit that
    dropped a case would fail here instead of quietly narrowing the oracle.
    """

    def _branch_of(self, args):
        (L, V, area, largest, smallest, ds, corr, _n) = args
        if area < 1:
            return "area<1"
        scale = corr / ds
        edges = 0
        if largest > 0:
            edges = 1
            if smallest > 0:
                edges = 2
        elif smallest > 0:
            edges = 1
        center_in = 0 if L * scale <= largest else 1
        if edges == 2 and center_in:
            return "2edge_in"
        if edges == 2:
            return "2edge_out"
        if edges == 1 and center_in:
            return "1edge_in"
        if edges == 1:
            return "1edge_out"
        return "0edge"

    def test_all_six_branches_exercised(self):
        seen = {self._branch_of(a) for a in load_cases().values()}
        self.assertEqual(
            {"area<1", "2edge_in", "2edge_out", "1edge_in", "1edge_out", "0edge"},
            seen,
        )

    def test_dead_elseif_is_exercised_anyway(self):
        """``dropsize.m:143`` cannot be reached from ``imgProc_sm``.

        The caller passes ``largest = max(top, bottom)`` and
        ``smallest = min(top, bottom)``, so a positive smallest forces a
        positive largest and the ``elseif`` never runs.  The function is public,
        though, so the bank covers it regardless -- and this test is what stops
        that coverage being dropped as "unreachable".
        """
        cases = load_cases()
        reaching = [
            n for n, a in cases.items()
            if a[3] == 0 and a[4] > 0 and a[2] >= 1
        ]
        self.assertTrue(reaching, "no case reaches the dead :143 elseif")

    def test_oversize_sentinel_reached_in_both_tables(self):
        """9.1 is the documented oversize marker (``dropsize.m:11``)."""
        golden = load_golden()
        h = [n for n, r in golden.items()
             if r["status"] == "OK" and float(r["diameter_horiz_chord"]) == 9.1]
        v = [n for n, r in golden.items()
             if r["status"] == "OK" and float(r["diameter_vert_chord"]) == 9.1]
        self.assertTrue(h, "no case drives the horizontal table oversize")
        self.assertTrue(v, "no case drives the vertical table oversize")


if __name__ == "__main__":
    unittest.main()
