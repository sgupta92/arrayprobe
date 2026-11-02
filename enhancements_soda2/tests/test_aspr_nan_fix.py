# SPDX-License-Identifier: BSD-3-Clause
"""S2-d (final ``aspr`` clamp, ``aspect_ratio.pro:105``) -- ``aspr_nan_fix.corrected_aspr``.

The AB case mirrors ``test_soda2_aspect_ratio.py::TheMinMaxOperatorsAreClamps::
test_a_nonfinite_diameter_clamps_to_one_with_no_warning`` -- a synthetic circle with a NaN
``diam``, which drives the port's ``aspr`` non-finite before its own clamp silently reads it
as 1.0.
"""

from __future__ import annotations

import json
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from arrayprobe_soda2.aspect_ratio import axis_and_ratio

from arrayprobe_soda2_enhancements.aspr_nan_fix import corrected_aspr
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
    """On a geometry with a genuinely finite aspr, the passthrough flag has nothing to do --
    corrected_aspr must equal the real port's axis_and_ratio bit for bit."""

    def test_matches_port_when_aspr_is_finite(self):
        golden = _load_golden()
        case = golden["den_clamp_bites_tas025_float"]
        x_ind = _x_ind(case)
        y_adj = _y_adjusted(case)
        circle = _circle_from_case(case)

        port_aspr, port_orient = axis_and_ratio(x_ind, y_adj, circle)
        self.assertTrue(np.isfinite(float(port_aspr)))

        got_aspr, got_orient = corrected_aspr(x_ind, y_adj, circle)
        self.assertEqual(float(got_aspr), float(port_aspr))
        self.assertEqual(float(got_orient), float(port_orient))


class ABConsequence(unittest.TestCase):
    """A non-converged circle (NaN diam) is exactly the case S2-d names: the port silently
    reads it as aspr == 1.0 (a perfectly round particle); the correction returns NaN."""

    def test_nonfinite_diameter_stays_nonfinite_instead_of_clamping_to_one(self):
        x_ind = np.array([0, 6, 1], dtype=np.int32)
        y_ind = np.array([0, 0, 7], dtype=np.int32)
        circle = SimpleNamespace(diam=float("nan"), center=np.array([2.0, 2.0]),
                                  corners=[0, 1, 2])

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            port_aspr, _o = axis_and_ratio(x_ind, y_ind, circle)
        self.assertEqual(float(port_aspr), 1.0)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            fixed_aspr, _o2 = corrected_aspr(x_ind, y_ind, circle)
        self.assertTrue(np.isnan(float(fixed_aspr)))


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("aspr_nan_fix", REGISTRY)
        spec = REGISTRY["aspr_nan_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S2-d")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["aspr_nan_fix"])
        self.assertTrue(resolve({"aspr_nan_fix": True})["aspr_nan_fix"])
        self.assertFalse(resolve({"aspr_nan_fix": False})["aspr_nan_fix"])


if __name__ == "__main__":
    unittest.main()
