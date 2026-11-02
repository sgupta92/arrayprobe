# SPDX-License-Identifier: BSD-3-Clause
"""S4-x/S5-f (``fixstuckbits.pro:17-20``'s no-match scalar index) --
``no_stuck_diode_fix.corrected_fixstuckbits``.

Golden loading and the ``n-8`` corruption case are the same ones
``test_soda2_fixstuckbits.py`` uses -- ``one_stuck_interior`` (a real
stuck diode, GDL-confirmed) for equivalence, and the port's own
``test_wide_image_with_no_stuck_diode_corrupts_n_minus_8`` construction
for the A/B (n=24, uniform ``h``, no diode crosses the threshold).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from arrayprobe_soda2.fixstuckbits import NoStuckBitsHalt, fixstuckbits

from arrayprobe_soda2_enhancements.no_stuck_diode_fix import (
    _any_diode_crosses_threshold,
    corrected_fixstuckbits,
)
from arrayprobe_soda2_enhancements.registry import PROTECTIVE, REGISTRY, resolve

GOLDEN = (Path(__file__).resolve().parents[2] / "tests" / "data"
          / "gdl_soda2_fixstuckbits_golden.json")


def _load_golden() -> dict[str, dict]:
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {r["name"]: r for r in records}


class Equivalence(unittest.TestCase):
    """A real stuck diode (GDL-confirmed) crosses the threshold, so the
    corrected and unmodified paths must agree bit for bit."""

    def test_matches_port_when_a_diode_is_genuinely_stuck(self):
        golden = _load_golden()
        case = golden["one_stuck_interior"]
        image = np.asarray(case["image"], dtype=np.uint8)
        h = np.asarray(case["h"], dtype=np.int64) if case["h"] is not None else None

        # Sanity: this case genuinely takes the "a diode is stuck" branch
        # (the port's output happens to equal the input here anyway,
        # because the stuck diode's left neighbour carries the same
        # pattern -- confirmed by checking the threshold test directly,
        # not by the output changing).
        self.assertTrue(_any_diode_crosses_threshold(image, h))

        port_out = fixstuckbits(image, h=h)
        got = corrected_fixstuckbits(image, h=h)
        np.testing.assert_array_equal(got, port_out)


class ABConsequence(unittest.TestCase):
    """No diode crosses the threshold: the port silently corrupts
    column n-8 (n>=8); the correction leaves the image unchanged."""

    def test_no_stuck_diode_wide_probe_leaves_image_unchanged(self):
        n = 24
        image = np.zeros((n, 2), dtype=np.uint8)
        image[n - 8, :] = 1  # distinctive at the corrupted index
        h = np.array([100] * n, dtype=np.int64)

        port_out = fixstuckbits(image, h=h)
        self.assertFalse(np.array_equal(port_out, image),
                          "sanity: the port's own S4-x corruption must fire")

        fixed = corrected_fixstuckbits(image, h=h)
        np.testing.assert_array_equal(fixed, image)

    def test_no_stuck_diode_narrow_probe_does_not_halt(self):
        image = np.ones((5, 2), dtype=np.uint8)
        h = np.array([100] * 5, dtype=np.int64)
        with self.assertRaises(NoStuckBitsHalt):
            fixstuckbits(image, h=h)

        fixed = corrected_fixstuckbits(image, h=h)
        np.testing.assert_array_equal(fixed, image)

    def test_the_input_array_is_not_mutated(self):
        n = 24
        image = np.zeros((n, 2), dtype=np.uint8)
        image[n - 8, :] = 1
        h = np.array([100] * n, dtype=np.int64)
        before = image.copy()
        corrected_fixstuckbits(image, h=h)
        np.testing.assert_array_equal(image, before)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("no_stuck_diode_fix", REGISTRY)
        spec = REGISTRY["no_stuck_diode_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-x")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_on_through_the_protective_set_false_when_opted_out(self):
        self.assertFalse(resolve({})["no_stuck_diode_fix"])
        self.assertTrue(resolve({}, protective=PROTECTIVE)["no_stuck_diode_fix"])
        self.assertFalse(
            resolve({"no_stuck_diode_fix": False}, protective=PROTECTIVE)["no_stuck_diode_fix"])
        self.assertFalse(resolve({"no_stuck_diode_fix": False})["no_stuck_diode_fix"])


if __name__ == "__main__":
    unittest.main()
