# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.tas`` against a real Octave run of v3.5's own source.

The fixture is written by ``octave_oracle/run_v35_tas_bank.py``, which slices
``interp_tas`` out of the vendored ``UIOPS-v3.5/.../read_binary_SPEC.m`` and runs
*those lines*, so the oracle is the upstream source rather than a transcription
of it. ``test_the_oracle_ran_the_vendored_source`` re-slices the file and requires
it to still match what the fixture recorded, which is what makes a later upstream
re-vendor fail here instead of silently invalidating every case below.

``update_tas`` and ``tas_ratio`` are inline blocks of ``read_binary_SPEC``'s
``get_img`` subfunction, not callable functions, so they have no direct Octave
oracle; they are doctrine layer 3 -- documented semantics and pinned tests --
with the branch table asserted against the source's own line numbers.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe_uiops.tas import (
    SUSPECT_TAS,
    AmbiguousFlightTimeError,
    InterpTasError,
    interp_tas,
    tas_ratio,
    update_tas,
)

FIXTURE = Path(__file__).resolve().parent / "data" / "v35_tas_oracle.json"
V35_SPEC = (
    _upstream.source("uiops35") / "read_binary_SPEC.m"
)


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops314")
    _upstream.require("uiops35")


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestAgainstTheOctaveOracle(unittest.TestCase):
    """Every case the bank ran, reproduced exactly."""

    def setUp(self) -> None:
        self.bank = _load()

    @repo_only
    def test_the_oracle_ran_the_vendored_source(self) -> None:
        lines = V35_SPEC.read_text(encoding="utf-8", errors="replace").splitlines()
        start = next(
            (i for i, ln in enumerate(lines) if ln.startswith("function tasNew = interp_tas(")),
            None,
        )
        self.assertIsNotNone(start, "interp_tas is gone from the vendored v3.5 source")
        recovered = "\n".join(lines[start:]).rstrip() + "\n"
        self.assertEqual(
            recovered,
            self.bank["source"],
            "the vendored v3.5 interp_tas no longer matches the source the oracle ran; "
            "re-run octave_oracle/run_v35_tas_bank.py",
        )

    def test_every_oracle_case_is_reproduced(self) -> None:
        checked = 0
        for name, expected in self.bank["results"].items():
            values = self.bank["cases"][name]
            with self.subTest(case=name):
                if expected["status"] == "ERROR":
                    with self.assertRaises(InterpTasError):
                        interp_tas(values)
                else:
                    got = interp_tas(values)
                    want = [math.nan if v is None else float(v) for v in expected["value"]]
                    np.testing.assert_allclose(got, want, rtol=1e-12, equal_nan=True)
            checked += 1
        self.assertEqual(checked, 12, "the bank is 12 cases; a shorter fixture is a truncated run")

    def test_the_three_error_cases_are_the_ones_with_too_few_nodes(self) -> None:
        """Not just 'three errors' -- the right three, for the stated reason."""
        errored = {n for n, r in self.bank["results"].items() if r["status"] == "ERROR"}
        for name in errored:
            good = [v for v in self.bank["cases"][name] if v > 0]
            self.assertLess(len(good), 2, f"{name} errored but has {len(good)} good nodes")
        for name in set(self.bank["results"]) - errored:
            good = [v for v in self.bank["cases"][name] if v > 0]
            self.assertGreaterEqual(len(good), 2, f"{name} succeeded with {len(good)} good nodes")


class TestThePreservedQuirks(unittest.TestCase):
    """The three behaviours a reader of the source would not predict."""

    def test_a_negative_tas_is_neither_repaired_nor_used_as_a_node(self) -> None:
        # -999. is read_binary_SPEC.m:186's own uncorrectable-probe-TAS sentinel,
        # so this is reachable from real data, not a synthetic edge case.
        out = interp_tas([100.0, -999.0, 120.0, 0.0])
        self.assertEqual(out[1], -999.0, "the negative was repaired; upstream leaves it")
        self.assertTrue(math.isnan(out[3]), "the trailing zero was extrapolated; interp1 does not")

    def test_the_ends_are_never_repaired(self) -> None:
        out = interp_tas([0.0, 110.0, 120.0, float("nan")])
        self.assertTrue(math.isnan(out[0]))
        self.assertTrue(math.isnan(out[-1]))
        self.assertEqual(list(out[1:3]), [110.0, 120.0])

    def test_a_dead_tas_feed_raises_rather_than_degrading(self) -> None:
        with self.assertRaises(InterpTasError):
            interp_tas([0.0, 0.0, float("nan")])

    def test_interpolation_is_over_index_position_not_value(self) -> None:
        out = interp_tas([130.0, 0.0, 100.0, 120.0])
        self.assertEqual(out[1], 115.0, "115 is the mean of the neighbours by position")

    def test_a_clean_series_is_returned_unchanged(self) -> None:
        values = [100.0, 110.0, 120.0, 130.0]
        np.testing.assert_array_equal(interp_tas(values), values)


class TestTheUpdateGate(unittest.TestCase):
    """``read_binary_SPEC.m:406-414``, every branch."""

    def test_an_unchanged_reading_keeps_the_previous_value(self) -> None:
        self.assertEqual(update_tas(120.0, 120.0, 0, 0), 120.0)

    def test_a_changed_and_trustworthy_reading_is_taken(self) -> None:
        self.assertEqual(update_tas(125.0, 120.0, 0, 0), 125.0)

    def test_the_suspect_value_is_refused(self) -> None:
        self.assertEqual(update_tas(SUSPECT_TAS, 120.0, 0, 0), 120.0)

    def test_a_holdover_or_overload_refuses_the_reading(self) -> None:
        self.assertEqual(update_tas(125.0, 120.0, 1, 0), 120.0)
        self.assertEqual(update_tas(125.0, 120.0, 0, 1), 120.0)
        self.assertEqual(update_tas(125.0, 120.0, 3, 4), 120.0)

    def test_the_suspect_value_is_only_suspect_when_it_is_a_change(self) -> None:
        """It is tested inside the `tasTemp ~= tasPrev` branch, not outside it."""
        self.assertEqual(update_tas(SUSPECT_TAS, SUSPECT_TAS, 0, 0), SUSPECT_TAS)


class TestTheRatio(unittest.TestCase):
    """``read_binary_SPEC.m:176-193``."""

    TIMES = [120000.0, 120001.0, 120002.0]
    FIXED = [200.0, 250.0, 400.0]

    def test_a_matched_second_divides_probe_by_aircraft(self) -> None:
        self.assertAlmostEqual(tas_ratio(100.0, self.TIMES, self.FIXED, 12, 0, 1), 0.4)

    def test_an_unmatched_second_assumes_the_probe_is_right(self) -> None:
        self.assertEqual(tas_ratio(100.0, self.TIMES, self.FIXED, 12, 0, 9), 1.0)

    def test_a_nan_aircraft_value_assumes_the_probe_is_right(self) -> None:
        fixed = [200.0, float("nan"), 400.0]
        self.assertEqual(tas_ratio(100.0, self.TIMES, fixed, 12, 0, 1), 1.0)

    def test_the_uncorrectable_probe_sentinel_gives_unity(self) -> None:
        self.assertEqual(tas_ratio(-999.0, self.TIMES, self.FIXED, 12, 0, 1), 1.0)

    def test_the_date_crossover_looks_up_the_shifted_hour(self) -> None:
        times = [235959.0, 250000.0]
        fixed = [200.0, 250.0]
        # 01:00:00 with a series running past 240000 is looked up as 25:00:00.
        self.assertAlmostEqual(tas_ratio(125.0, times, fixed, 1, 0, 0), 0.5)

    def test_the_crossover_does_not_fire_after_noon(self) -> None:
        times = [235959.0, 250000.0]
        self.assertEqual(tas_ratio(125.0, times, [200.0, 250.0], 13, 0, 0), 1.0)

    def test_a_negative_repaired_aircraft_tas_yields_a_negative_ratio(self) -> None:
        """The consequence of quirk 1, at the call site rather than in isolation."""
        fixed = interp_tas([200.0, -999.0, 400.0])
        self.assertAlmostEqual(tas_ratio(100.0, self.TIMES, fixed, 12, 0, 1), -100.0 / 999.0)

    def test_duplicate_flight_times_refuse_rather_than_guess(self) -> None:
        times = [120001.0, 120001.0]
        with self.assertRaises(AmbiguousFlightTimeError):
            tas_ratio(100.0, times, [200.0, 250.0], 12, 0, 1)


@repo_only
class TestNoneOfThisIsInV314(unittest.TestCase):
    """The claim the module docstring opens with, checked rather than asserted."""

    def test_the_v314_reader_has_no_tas_machinery(self) -> None:
        v314 = (
            _upstream.source("uiops314") / "read_binary_SPEC.m"
        )
        text = v314.read_text(encoding="utf-8", errors="replace")
        for token in ("interp_tas", "tasRatio", "tasPrev"):
            self.assertNotIn(
                token, text, f"{token} is in v3.1.4 after all; the port's premise is wrong"
            )


if __name__ == "__main__":
    unittest.main()
