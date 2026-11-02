# SPDX-License-Identifier: BSD-3-Clause
"""S2-f (``den`` clamp, ``aspect_ratio.pro:66``) -- ``den_clamp_fix.corrected_aspr``.

Golden cases are the real ones finding S2-f cites
(``den_clamp_bites_tas025_float`` / ``den_unclamped_tas025_float``,
``tests/data/gdl_soda2_aspect_ratio_golden.json``), loaded the same way
``test_soda2_aspect_ratio.py`` does (helpers duplicated here rather than imported across the
package boundary, since they are ~15 lines of pure fixture plumbing, not port logic).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from arrayprobe_soda2.aspect_ratio import axis_and_ratio

from arrayprobe_soda2_enhancements.den_clamp_fix import corrected_aspr
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve

GOLDEN = (Path(__file__).resolve().parents[2] / "tests" / "data"
          / "gdl_soda2_aspect_ratio_golden.json")


def _load_golden() -> dict[str, dict]:
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {r["name"]: r for r in records}


def _x_ind(case: dict) -> np.ndarray:
    return np.asarray(case["XI"], dtype=np.int32)


def _y_adjusted(case: dict) -> np.ndarray:
    yi = np.asarray(case["YI"], dtype=np.int64)
    tas_kind = case["tas_kind"]
    if tas_kind == "none":
        return yi.astype(np.int32)
    if tas_kind == "float":
        return (yi.astype(np.float32) * np.float32(case["tas_value"])).astype(np.float32)
    if tas_kind == "double":
        return yi.astype(np.float64) * np.float64(case["tas_value"])
    raise ValueError(tas_kind)


def _circle_from_case(case: dict) -> SimpleNamespace:
    return SimpleNamespace(
        diam=float(case["DIAM"]),
        center=np.array([case["CX"], case["CY"]], dtype=np.float64),
        corners=list(case["CORNERS"]),
    )


class Equivalence(unittest.TestCase):
    """On a geometry where the clamp is not exercised (den already > 1 unclamped, so the
    zero-guard and the port's own `> 1` clamp agree), corrected_aspr must equal the real
    port's axis_and_ratio bit for bit."""

    def test_matches_port_when_den_is_not_clamped(self):
        golden = _load_golden()
        case = golden["two_slice_tas0p1_float"]
        x_ind = _x_ind(case)
        y_adj = _y_adjusted(case)
        circle = _circle_from_case(case)

        port_aspr, port_orient = axis_and_ratio(x_ind, y_adj, circle)
        got_aspr, got_orient = corrected_aspr(x_ind, y_adj, circle)

        self.assertEqual(float(got_aspr), float(port_aspr))
        self.assertEqual(float(got_orient), float(port_orient))


class ABConsequence(unittest.TestCase):
    """On the golden geometry S2-f names, the correction recovers the unclamped ASPR
    (0.7272727272727273) where the port's own axis_and_ratio returns the clamped
    (0.6136363636363636) one -- both numbers transcribed from the finding."""

    def test_recovers_the_unclamped_aspr_on_the_named_golden_case(self):
        golden = _load_golden()
        case = golden["den_clamp_bites_tas025_float"]
        unclamped = golden["den_unclamped_tas025_float"]
        x_ind = _x_ind(case)
        y_adj = _y_adjusted(case)
        circle = _circle_from_case(case)

        port_aspr, _o = axis_and_ratio(x_ind, y_adj, circle)
        self.assertAlmostEqual(float(port_aspr), 0.6136363636363636, places=9)
        self.assertAlmostEqual(float(port_aspr), case["ASPR"], places=9)

        fixed_aspr, _o2 = corrected_aspr(x_ind, y_adj, circle)
        self.assertAlmostEqual(float(fixed_aspr), 0.7272727272727273, places=9)
        self.assertAlmostEqual(float(fixed_aspr), unclamped["ASPR_UNCLAMPED"], places=9)

        self.assertNotAlmostEqual(float(fixed_aspr), float(port_aspr), places=6)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("den_clamp_fix", REGISTRY)
        spec = REGISTRY["den_clamp_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S2-f")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["den_clamp_fix"])
        self.assertTrue(resolve({"den_clamp_fix": True})["den_clamp_fix"])
        self.assertFalse(resolve({"den_clamp_fix": False})["den_clamp_fix"])


if __name__ == "__main__":
    unittest.main()
