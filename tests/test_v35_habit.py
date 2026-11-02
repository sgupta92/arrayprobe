# SPDX-License-Identifier: BSD-3-Clause
"""arrayprobe_uiops.habit against a real Octave run of UIOOPS v3.5's
``holroyd.m``, ``holroyd_new.m`` and ``holroyd_new_HVPS.m``.

WHAT THIS PROTECTS. Three MATLAB functions with eleven interacting habit
codes across two structurally different decision trees (the module docstring
has the measured diffs: which thresholds are pure unit-generalizations,
which one is not, and the real -- not tuning-only -- differences between the
2D-S and HVPS "new scheme" files). Confirmed by running the real v3.5
sources under Octave 11.3.0 across four function-configurations
(``holroyd_2ds``/``holroyd_hvps`` -- the same ``holroyd.m`` at each probe's
diode size; ``holroyd_new_2ds``/``holroyd_new_hvps``) and ~185 particle
images per configuration: degenerate shapes, a size/aspect-ratio sweep,
45-degree diagonals, gapped and edge-touching rectangles, rings/
checkerboards, and 130 seeded random blobs. Bank:
``octave_oracle/run_v35_habit_bank.py``; driver: ``run_v35_habit_oracle.m``.
The golden is tracked, so this runs on a clone with no Octave installed.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_uiops.habit import (
    HolroydNewResult,
    ZeroSlicesUnassignedOutputs,
    holroyd,
    holroyd_new,
    holroyd_new_hvps,
)

GOLDEN = Path(__file__).resolve().parent / "data" / "v35_habit_octave_golden.json"

DIODESIZE_2DS = 0.010
DIODESIZE_HVPS = 0.150
TAS_RATIO = 1.0


def _load():
    return json.loads(GOLDEN.read_text())


def _image(rec: dict) -> np.ndarray:
    """Rebuild the case as the char array the port's ``shadow_mask`` reads."""
    flat, rows, cols = rec["img"], rec["rows"], rec["cols"]
    if rows == 0 or cols == 0:
        return np.empty((rows, cols), dtype="<U1")
    assert len(flat) == rows * cols, rec["name"]
    return np.array(list(flat)).reshape(rows, cols)


def _isclose(a, b, tol=1e-6) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


class TestAgainstOctaveGoldenOldScheme(unittest.TestCase):
    """``holroyd`` (v3.5's generalized-resolution original scheme)."""

    @classmethod
    def setUpClass(cls):
        cls.records = _load()

    def _check(self, fn, probe_resolution):
        recs = [r for r in self.records if r["fn"] == fn and r["status"] == "OK"]
        self.assertGreaterEqual(len(recs), 150, f"{fn}: bank too small to trust")
        for rec in recs:
            with self.subTest(rec["name"]):
                habit, f_fine_detail = holroyd(_image(rec), probe_resolution)
                self.assertEqual(habit, rec["habit"])
                self.assertTrue(_isclose(f_fine_detail, rec["F"]),
                                 f"F: got {f_fine_detail}, oracle {rec['F']}")

    def test_matches_octave_at_2ds_resolution(self):
        self._check("holroyd_2ds", DIODESIZE_2DS)

    def test_matches_octave_at_hvps_resolution(self):
        self._check("holroyd_hvps", DIODESIZE_HVPS)

    def test_never_emits_C(self):
        """v3.5 deleted the ``parabola_fit_center_is_in`` gate outright, so
        unlike the v3.1.4 port's ``holroyd`` (dead 'C' branch), this
        function's source has no 'C' branch to be dead -- measured across
        both probe resolutions, not merely read off the source."""
        for fn in ("holroyd_2ds", "holroyd_hvps"):
            habits = {r["habit"] for r in self.records
                      if r["fn"] == fn and r["status"] == "OK"}
            self.assertNotIn("C", habits, fn)


class TestAgainstOctaveGoldenNewScheme(unittest.TestCase):
    """``holroyd_new`` and ``holroyd_new_hvps`` (the Schima et al. 2024 scheme)."""

    @classmethod
    def setUpClass(cls):
        cls.records = _load()

    def _check(self, fn, port_fn, probe_resolution):
        recs = [r for r in self.records if r["fn"] == fn and r["status"] == "OK"]
        self.assertGreaterEqual(len(recs), 150, f"{fn}: bank too small to trust")
        fields = ("F", "w_l_p", "c_r", "e_d_r", "m_g", "O", "a_r", "p")
        for rec in recs:
            with self.subTest(rec["name"]):
                result: HolroydNewResult = port_fn(
                    _image(rec), probe_resolution=probe_resolution, tas_ratio=TAS_RATIO
                )
                self.assertEqual(result.holroyd_habit, rec["habit"])
                for field in fields:
                    got = getattr(result, field)
                    with self.subTest(field=field):
                        self.assertTrue(
                            _isclose(got, rec[field]),
                            f"{field}: got {got}, oracle {rec[field]}",
                        )

    def test_matches_octave_2ds(self):
        self._check("holroyd_new_2ds", holroyd_new, DIODESIZE_2DS)

    def test_matches_octave_hvps(self):
        self._check("holroyd_new_hvps", holroyd_new_hvps, DIODESIZE_HVPS)

    def test_zero_slices_raises_matching_matlabs_own_error(self):
        """``imgProc_sm.m`` always requests all 9 outputs; MATLAB itself
        errors on a zero-slice call with "element number 9 undefined in
        return list" (measured, recorded as the bank's one ERROR record per
        new-scheme function). This port raises rather than inventing values
        for the 8 unassigned outputs."""
        for fn, port_fn, res in (
            ("holroyd_new_2ds", holroyd_new, DIODESIZE_2DS),
            ("holroyd_new_hvps", holroyd_new_hvps, DIODESIZE_HVPS),
        ):
            rec = next(r for r in self.records
                       if r["fn"] == fn and r["name"] == "empty_0x128")
            self.assertEqual(rec["status"], "ERROR")
            self.assertIn("element number 9", rec["message"])
            with self.subTest(fn):
                with self.assertRaises(ZeroSlicesUnassignedOutputs):
                    port_fn(_image(rec), probe_resolution=res, tas_ratio=TAS_RATIO)

    def test_hvps_never_emits_h(self):
        """``holroyd_new_HVPS.m``'s decision tree has no branch that returns
        'h' at all (measured directly by diffing it against
        ``holroyd_new.m``, which does) -- this is the bank confirming that
        reading."""
        habits = {r["habit"] for r in self.records
                  if r["fn"] == "holroyd_new_hvps" and r["status"] == "OK"}
        self.assertNotIn("h", habits)

    def test_coverage_is_broad_not_degenerate(self):
        """A bank that only ever produced two or three habit codes would not
        be exercising the decision trees it claims to."""
        for fn, minimum in (
            ("holroyd_new_2ds", 6),
            ("holroyd_new_hvps", 6),
        ):
            habits = {r["habit"] for r in self.records
                      if r["fn"] == fn and r["status"] == "OK"}
            self.assertGreaterEqual(len(habits), minimum, f"{fn}: only {habits}")


if __name__ == "__main__":
    unittest.main()
