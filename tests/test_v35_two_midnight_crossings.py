# SPDX-License-Identifier: BSD-3-Clause
"""v3.5's particle-time rollover on a series crossing midnight twice or more.

``sizeDist.m``'s more-than-one-decrease arm adds 240000 after the first
genuine crossover and then leaves the loop, so every later crossover goes
unshifted. The golden ``tests/data/v35_two_midnight_crossings_octave.json`` is
that block, sliced verbatim from the vendored v3.5 file and run under GNU
Octave (``octave_oracle/run_v35_two_midnight_crossings.py``). The port
reproduces the behaviour on purpose; these tests pin it to Octave's output.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from tests import _upstream
from tests._repo import repo_only

from arrayprobe_uiops import sizedist as v35s

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GOLDEN_PATH = HERE / "data" / "v35_two_midnight_crossings_octave.json"
V35_SIZEDIST = _upstream.source("uiops35") / "sizeDist.m"

with GOLDEN_PATH.open(encoding="utf-8") as fh:
    GOLDEN = json.load(fh)


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


class TestGoldenIsTheVendoredSource(unittest.TestCase):
    @repo_only
    def test_the_sliced_block_still_matches_the_vendored_file(self):
        _upstream.require("uiops35")
        lines = V35_SIZEDIST.read_text(encoding="utf-8", errors="replace").splitlines()
        block = GOLDEN["block"]
        live = "\n".join(lines[block["start_line"] - 1 : block["end_line"]]) + "\n"
        self.assertEqual(live, block["text"])

    def test_the_block_leaves_the_loop_after_the_first_crossover(self):
        self.assertIn("break;", GOLDEN["block"]["text"])


class TestPortMatchesOctave(unittest.TestCase):
    def test_every_case_ran_under_octave(self):
        for name, rec in GOLDEN["octave"].items():
            with self.subTest(case=name):
                self.assertEqual(rec["status"], "OK", rec.get("message"))

    def test_port_equals_octave_on_every_case(self):
        for name, series in GOLDEN["cases"].items():
            with self.subTest(case=name):
                got, applied = v35s.fix_multiday_particle_times(np.array(series, dtype=float))
                self.assertTrue(applied)
                np.testing.assert_array_equal(
                    got, np.array(GOLDEN["octave"][name]["image_time_hhmmssall"], dtype=float)
                )

    def test_second_crossing_is_left_one_rollover_short(self):
        # Two genuine crossings: the tail after the second one should read
        # 480000 above its raw value for the times to keep increasing; Octave
        # and the port both leave it at 240000 above.
        out = GOLDEN["octave"]["two_genuine_crossings"]["image_time_hhmmssall"]
        self.assertEqual(out, [235000, 235959, 240010, 360000, 475958, 240020, 240030])
        self.assertTrue(np.any(np.diff(out) < 0))


if __name__ == "__main__":
    unittest.main()
