# SPDX-License-Identifier: BSD-3-Clause
"""S5-k (``spec_process_hk.pro:84``'s implicit-horizontal-else) --
``hk_probeid_columns.corrected_process_hk``.

``_base_op`` is duplicated from ``test_soda2_preloop.py`` rather than
imported across the package boundary (the stage 2/3 convention).
"""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
from arrayprobe_soda2 import process_hk

from arrayprobe_soda2_enhancements.hk_probeid_columns import (
    UnrecognizedProbeid,
    corrected_process_hk,
)
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
HK_FIX = DATA / "soda2_spec_hk_fixture"


def _base_op(**over) -> dict:
    op = dict(
        fn=str(HK_FIX), date="20160906", starttime=24240.0, stoptime=24250.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0, 1000], rate=1.0, timeoffset=np.float32(0.0),
        fixedtas=np.float32(0.0), numdiodes=128, probeid="H",
    )
    op.update(over)
    return op


class Equivalence(unittest.TestCase):
    """A recognized probeid ('H') never triggers the refusal --
    corrected_process_hk must match the real process_hk exactly."""

    def test_matches_port_for_recognized_probeid_h(self):
        port_out = process_hk.process_hk(_base_op(probeid="H"))
        got = corrected_process_hk(_base_op(probeid="H"))
        np.testing.assert_array_equal(got.volts, port_out.volts)
        np.testing.assert_array_equal(got.overloads, port_out.overloads)
        np.testing.assert_array_equal(got.laservolts, port_out.laservolts)
        np.testing.assert_array_equal(got.counts, port_out.counts)

    def test_matches_port_for_recognized_probeid_v(self):
        port_out = process_hk.process_hk(_base_op(probeid="V"))
        got = corrected_process_hk(_base_op(probeid="V"))
        np.testing.assert_array_equal(got.volts, port_out.volts)
        np.testing.assert_array_equal(got.counts, port_out.counts)


class ABConsequence(unittest.TestCase):
    """A misspelling of 'V' (lowercase 'v'): the port's own
    process_hk silently takes the horizontal channel's columns
    (identical to probeid='H', measured directly below); the
    correction refuses instead of silently choosing a channel."""

    def test_lowercase_v_silently_takes_horizontal_in_the_port(self):
        port_v_lower = process_hk.process_hk(_base_op(probeid="v"))
        port_h = process_hk.process_hk(_base_op(probeid="H"))
        np.testing.assert_array_equal(port_v_lower.volts, port_h.volts)
        np.testing.assert_array_equal(port_v_lower.overloads, port_h.overloads)

        with self.assertRaises(UnrecognizedProbeid):
            corrected_process_hk(_base_op(probeid="v"))

    def test_an_unrelated_string_is_also_refused(self):
        with self.assertRaises(UnrecognizedProbeid):
            corrected_process_hk(_base_op(probeid="XYZ"))


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("hk_probeid_columns", REGISTRY)
        spec = REGISTRY["hk_probeid_columns"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S5-k")
        self.assertEqual(spec.reachability, "flagged")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["hk_probeid_columns"])
        self.assertTrue(resolve({"hk_probeid_columns": True})["hk_probeid_columns"])
        self.assertFalse(resolve({"hk_probeid_columns": False})["hk_probeid_columns"])


if __name__ == "__main__":
    unittest.main()
