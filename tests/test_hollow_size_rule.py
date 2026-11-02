# SPDX-License-Identifier: BSD-3-Clause
"""Tests for ``arrayprobe_uiops.hollow_size_rule``.

Four things the module must prove, each its own class below:

* :class:`TestBitIdenticalWhenOff` -- off by default, and a strict
  passthrough of ``ihollow`` (checked with ``np.array_equal``, never
  ``allclose``, as befits an opt-in,
  default-off addition).
* :class:`TestBoundaryBothDirections` -- the threshold applied at the
  boundary in both directions.
* :class:`TestThresholdIsAParameter` -- the threshold is a field callers
  set, not a literal baked into the comparison.
* :class:`TestThresholdIsAnEstimateNotAClaim` -- the module's own caveat ("155
  um is the best estimate, not a sharp boundary... that must travel with
  the number") is pinned in the code, both as prose (a drift guard) and as
  an independent recomputation of the two bracketing Wilson intervals from
  the raw counts (so a quietly-changed number fails here too, not only a
  quietly-deleted sentence).

No fixtures, no netCDF, no Octave: this module has its own named oracle
(the author's 480-particle labelling), not the vendored-tree
goldens the rest of ``arrayprobe_uiops`` is checked against.
"""
from __future__ import annotations

import dataclasses
import json
import math
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from arrayprobe_uiops import hollow_size_rule
from arrayprobe_uiops.hollow_size_rule import (
    DEFAULT_THRESHOLD_UM,
    LABELLED_EVIDENCE,
    HollowSizeRule,
    hollow_test_applies,
    resolve_ihollow,
    resolve_ihollow_array,
    size_um_from_minr,
    threshold_from_evidence,
)


class TestOffByDefault(unittest.TestCase):
    def test_default_rule_is_disabled(self):
        self.assertFalse(HollowSizeRule().enabled)

    def test_default_threshold_is_155(self):
        self.assertEqual(HollowSizeRule().threshold_um, 155.0)
        self.assertEqual(DEFAULT_THRESHOLD_UM, 155.0)


class TestBitIdenticalWhenOff(unittest.TestCase):
    """np.array_equal, never allclose."""

    def test_resolve_ihollow_no_rule_is_passthrough(self):
        sizes = (None, 0.0, 50.0, 105.0, 154.999, 155.0, 155.001, 305.0, 1e6)
        for ihollow in (0, 1):
            for size_um in sizes:
                self.assertEqual(resolve_ihollow(ihollow, size_um), int(ihollow))

    def test_resolve_ihollow_disabled_rule_is_passthrough(self):
        off = HollowSizeRule(enabled=False, threshold_um=90.0)
        for ihollow in (0, 1):
            for size_um in (None, 1.0, 90.0, 400.0):
                self.assertEqual(resolve_ihollow(ihollow, size_um, off), int(ihollow))

    def test_hollow_test_applies_is_always_true_when_off(self):
        off = HollowSizeRule(enabled=False, threshold_um=90.0)
        for size_um in (None, 0.0, 90.0, 90.0000001, 1e9):
            self.assertTrue(hollow_test_applies(off, size_um))
            self.assertTrue(hollow_test_applies(None, size_um))

    def test_array_bit_identical_when_off(self):
        rng = np.random.default_rng(294)
        ihollow = rng.integers(0, 2, size=2000)
        size_um = rng.uniform(20.0, 400.0, size=2000)
        size_um[::7] = np.nan  # a realistic mix of "no size established"
        off = HollowSizeRule(enabled=False)

        out_off = resolve_ihollow_array(ihollow, size_um, off)
        self.assertTrue(np.array_equal(out_off, ihollow))

        out_none = resolve_ihollow_array(ihollow, size_um, None)
        self.assertTrue(np.array_equal(out_none, ihollow))

    def test_array_output_is_not_the_same_object(self):
        # copy(), not the input array, so a caller mutating the result
        # cannot corrupt whatever produced `ihollow`.
        ihollow = np.array([0, 1, 0, 1])
        out = resolve_ihollow_array(ihollow, np.array([1.0, 2.0, 3.0, 4.0]), None)
        out[0] = 1
        self.assertEqual(ihollow[0], 0)


class TestBoundaryBothDirections(unittest.TestCase):
    def test_below_threshold_keeps_stock(self):
        rule = HollowSizeRule(enabled=True, threshold_um=155.0)
        self.assertEqual(resolve_ihollow(1, 154.999, rule), 1)
        self.assertTrue(hollow_test_applies(rule, 100.0))

    def test_at_threshold_is_disabled(self):
        # The threshold's own value is on the disabled side -- it is the
        # left edge of the 155-205 um bin, where the labels say hollow is
        # already more often wrong than right (60 % real).
        rule = HollowSizeRule(enabled=True, threshold_um=155.0)
        self.assertEqual(resolve_ihollow(1, 155.0, rule), 0)
        self.assertFalse(hollow_test_applies(rule, 155.0))

    def test_above_threshold_is_disabled(self):
        rule = HollowSizeRule(enabled=True, threshold_um=155.0)
        self.assertEqual(resolve_ihollow(1, 200.0, rule), 0)
        self.assertFalse(hollow_test_applies(rule, 200.0))

    def test_never_manufactures_a_rejection(self):
        # ihollow == 0 (stock says "not hollow") must stay 0 on both sides
        # of the boundary -- this rule only ever narrows stock's rejections.
        rule = HollowSizeRule(enabled=True, threshold_um=155.0)
        self.assertEqual(resolve_ihollow(0, 50.0, rule), 0)
        self.assertEqual(resolve_ihollow(0, 500.0, rule), 0)

    def test_unknown_size_falls_back_to_stock(self):
        rule = HollowSizeRule(enabled=True, threshold_um=155.0)
        self.assertEqual(resolve_ihollow(1, None, rule), 1)
        self.assertTrue(hollow_test_applies(rule, None))


class TestThresholdIsAParameter(unittest.TestCase):
    def test_moving_the_threshold_changes_the_verdict(self):
        size_um = 180.0
        default_rule = HollowSizeRule(enabled=True)  # 155 um
        widened_rule = HollowSizeRule(enabled=True, threshold_um=200.0)
        self.assertEqual(resolve_ihollow(1, size_um, default_rule), 0)
        self.assertEqual(resolve_ihollow(1, size_um, widened_rule), 1)

    def test_threshold_is_a_field_not_a_literal_in_the_branch(self):
        # If the comparison were hardcoded to 155 anywhere in the module,
        # one of these arbitrary thresholds would fail at its own boundary.
        for threshold in (50.0, 100.0, 155.0, 250.0, 999.0):
            rule = HollowSizeRule(enabled=True, threshold_um=threshold)
            self.assertEqual(resolve_ihollow(1, threshold - 0.001, rule), 1)
            self.assertEqual(resolve_ihollow(1, threshold, rule), 0)

    def test_rejects_a_nonpositive_threshold(self):
        with self.assertRaises(ValueError):
            HollowSizeRule(enabled=True, threshold_um=0.0)
        with self.assertRaises(ValueError):
            HollowSizeRule(enabled=True, threshold_um=-10.0)

    def test_rejects_a_non_finite_threshold(self):
        with self.assertRaises(ValueError):
            HollowSizeRule(enabled=True, threshold_um=float("nan"))
        with self.assertRaises(ValueError):
            HollowSizeRule(enabled=True, threshold_um=float("inf"))

    def test_rule_is_frozen(self):
        rule = HollowSizeRule()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            rule.threshold_um = 200.0  # type: ignore[misc]


class TestSizeUmFromMinr(unittest.TestCase):
    def test_matches_the_image_diam_minr_derivation(self):
        # imgproc.py:1365 -- image_diam_minR = minR * ds (mm); this helper
        # does the same multiplication and converts mm to um (* 1000).
        minr = 12.5
        diodesize_mm = 0.010
        mm = minr * diodesize_mm
        self.assertAlmostEqual(size_um_from_minr(minr, diodesize_mm), mm * 1000.0)

    def test_realistic_probe_resolution_lands_near_the_switch_point(self):
        # A 10 um/diode probe, minR ~15.5 diodes -> ~155 um: a sanity check
        # that the unit conversion is the right one and not off by 1000.
        size_um = size_um_from_minr(minr=15.5, diodesize_mm=0.010)
        self.assertAlmostEqual(size_um, 155.0)


class TestThresholdIsAnEstimateNotAClaim(unittest.TestCase):
    """'155 um is the best estimate, not a sharp boundary... and
    that must travel with the number' -- not only in the ledger. This pins
    BOTH the prose (an edit that quietly deletes the caveat fails here) and
    the arithmetic behind it (an edit that quietly changes the counts so
    the two bins no longer overlap also fails here)."""

    @staticmethod
    def _wilson_95(successes: int, n: int) -> tuple[float, float]:
        z = 1.959963984540054  # two-sided 95 %, standard normal quantile
        p = successes / n
        denom = 1.0 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return centre - margin, centre + margin

    def test_docstring_states_the_estimate_and_overlap_caveat(self):
        doc = (hollow_size_rule.__doc__ or "") + (HollowSizeRule.__doc__ or "")
        self.assertIn("155", doc)
        self.assertIn("best estimate", doc)
        self.assertIn("not a sharp boundary", doc)
        self.assertIn("overlap", doc)

    def test_the_two_bracketing_intervals_independently_overlap(self):
        # 105-155 um: 45 % of n=40 = 18/40 real. 155-205 um: 60 % of n=40 =
        # 24/40 real.
        lo_105_155 = self._wilson_95(18, 40)
        lo_155_205 = self._wilson_95(24, 40)

        # Independently reproduces the ledger's own rounded bounds -- if
        # this drifts, the docstring's transcription of the counts (not
        # just the overlap conclusion) has gone stale.
        rounded_105_155 = (round(lo_105_155[0] * 100), round(lo_105_155[1] * 100))
        rounded_155_205 = (round(lo_155_205[0] * 100), round(lo_155_205[1] * 100))
        self.assertEqual(rounded_105_155, (31, 60))
        self.assertEqual(rounded_155_205, (45, 74))

        overlap_lo = max(lo_105_155[0], lo_155_205[0])
        overlap_hi = min(lo_105_155[1], lo_155_205[1])
        self.assertLess(overlap_lo, overlap_hi, "the two Wilson intervals must overlap")


class TestTheDocstringTableIsTheConstant(unittest.TestCase):
    """The five-row table in the module docstring must be a rendering of
    :data:`LABELLED_EVIDENCE`, not an independent statement of it.

    Until 2026-09-21 the table lived only in prose while the threshold was a
    typed ``155.0``. The figure audit named that as the reason Section 6's
    figure could not be drawn honestly: **the number was machine-readable and
    its justification was not**, so the two could drift apart with nothing
    failing. This test closes that by parsing the prose back out and holding it
    against the computed values -- editing either alone fails here.
    """

    ROW = re.compile(
        r"^\s*(\d+)-(\d+) um\s+(\d+) %\s+\[(\d+), (\d+)\]\s+n=(\d+)\s*$", re.M
    )

    def setUp(self):
        self.rows = self.ROW.findall(hollow_size_rule.__doc__ or "")

    def test_the_table_is_present_and_has_one_row_per_bin(self):
        """Guard the guard: a renamed heading or a reflowed table would make
        every assertion below vacuous rather than failing."""
        self.assertEqual(
            len(self.rows), len(LABELLED_EVIDENCE),
            f"parsed {len(self.rows)} table rows from the module docstring but "
            f"LABELLED_EVIDENCE has {len(LABELLED_EVIDENCE)} bins. If the table "
            f"moved or was reformatted, move this parser with it -- do not "
            f"delete the check.")

    def test_every_number_in_the_prose_table_matches_the_counts(self):
        # strict=True: the sibling test asserts the two are the same length, but that is a
        # different test -- if it ever fails, this one must raise rather than quietly
        # comparing a truncated pair and passing.
        for (lo, hi, pct, ci_lo, ci_hi, n), b in zip(
            self.rows, sorted(LABELLED_EVIDENCE, key=lambda x: x.band_lo_um), strict=True
        ):
            with self.subTest(bin=f"{lo}-{hi}"):
                w_lo, w_hi = b.wilson_95
                self.assertEqual(
                    (int(lo), int(hi), int(pct), int(ci_lo), int(ci_hi), int(n)),
                    (int(b.band_lo_um), int(b.band_hi_um),
                     round(b.fraction_real * 100), round(w_lo * 100),
                     round(w_hi * 100), b.n),
                    "the docstring table disagrees with LABELLED_EVIDENCE. The "
                    "counts are the source; regenerate the prose row from them.")


class TestThresholdIsDerivedNotTyped(unittest.TestCase):
    """``DEFAULT_THRESHOLD_UM`` must be read off the labels, so that moving a
    label moves the threshold. A constant that merely *agrees* with the
    evidence today is the failure mode this module was audited for."""

    def test_the_shipped_default_is_what_the_labels_give(self):
        self.assertEqual(DEFAULT_THRESHOLD_UM, threshold_from_evidence())
        self.assertEqual(DEFAULT_THRESHOLD_UM, 155.0)

    def test_it_is_the_first_bin_at_or_above_the_half(self):
        below = [b for b in LABELLED_EVIDENCE if b.band_lo_um < DEFAULT_THRESHOLD_UM]
        at_or_above = [
            b for b in LABELLED_EVIDENCE if b.band_lo_um >= DEFAULT_THRESHOLD_UM
        ]
        self.assertTrue(below and at_or_above, "the threshold must split the bins")
        for b in below:
            self.assertLess(b.fraction_real, 0.5, f"{b.band_lo_um}-{b.band_hi_um}")
        self.assertGreaterEqual(at_or_above[0].fraction_real, 0.5)

    def test_moving_a_label_moves_the_threshold(self):
        """The point of the derivation. Flip four artifacts to real in the
        105-155 bin (18/40 -> 22/40 = 55 %) and the threshold must fall to 105
        on its own."""
        moved = tuple(
            dataclasses.replace(b, n_real=22, n_artifact=18)
            if b.band_lo_um == 105.0 else b
            for b in LABELLED_EVIDENCE
        )
        self.assertEqual(threshold_from_evidence(moved), 105.0)

    def test_evidence_that_supports_no_threshold_refuses_to_supply_one(self):
        """If no bin crosses the half, there is no threshold to read off, and
        silently defaulting 155.0 would be an invented justification."""
        flat = tuple(
            dataclasses.replace(b, n_real=1, n_artifact=99) for b in LABELLED_EVIDENCE
        )
        with self.assertRaises(ValueError):
            threshold_from_evidence(flat)


@unittest.skipUnless(
    (Path(__file__).resolve().parent / "data" / "cip_hollow_labels.json").exists(),
    "checks hand labels of real particle images, which this release does not distribute")
class TestEvidenceMatchesTheLabelStore(unittest.TestCase):
    """The counts must equal a recount of the author's verdict store.

    Two sides from different places: the module's tuple on
    one, and on the other a recount of the triage server's own per-particle
    verdicts. The tracked fixture is that recount, extracted 2026-09-21 and
    carrying its provenance; when the gitignored store itself is present
    locally, it is recounted live as well, so the fixture cannot quietly stop
    describing it.
    """

    FIXTURE = Path(__file__).resolve().parent / "data" / "cip_hollow_labels.json"
    STORE = (
        Path(__file__).resolve().parents[1]
        / "_decoded" / "cip160906" / "triage_verdicts" / "sea_s2.json"
    )

    @staticmethod
    def _elementary(queues):
        """The five disputed bins the module lists, dropping the control cells
        and the two wider round-1 bands (105-205, 205-305), which are supersets
        and would double-count every particle in them."""
        wide = {(105, 205), (205, 305)}
        return {
            (q["band_lo_um"], q["band_hi_um"]): q
            for q in queues
            if q["cell"] == "stock_rejects"
            and (q["band_lo_um"], q["band_hi_um"]) not in wide
        }

    def test_the_fixture_is_the_labels_the_module_claims(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["_provenance"]["total_records"], 480,
                         "the hollow-test label set is 480 labels; the fixture describes "
                         "a different set")
        counted = self._elementary(data["queues"])
        self.assertEqual(len(counted), len(LABELLED_EVIDENCE))
        for b in LABELLED_EVIDENCE:
            with self.subTest(bin=f"{b.band_lo_um:.0f}-{b.band_hi_um:.0f}"):
                q = counted[(int(b.band_lo_um), int(b.band_hi_um))]
                self.assertEqual((b.n_real, b.n_artifact),
                                 (q["n_real"], q["n_artifact"]))

    def test_the_fixture_still_describes_the_live_verdict_store(self):
        if not self.STORE.exists():
            self.skipTest(
                "the hand-label store is not part of this release; the check above still ran")
        records = json.loads(self.STORE.read_text(encoding="utf-8"))
        tallies: dict[str, Counter] = defaultdict(Counter)
        for rec in records.values():
            tallies[rec["queue"]][rec["verdict"]] += 1
        for b in LABELLED_EVIDENCE:
            queue = f"CIP-{b.band_lo_um:.0f}_{b.band_hi_um:.0f}um__stock_rejects"
            with self.subTest(queue=queue):
                self.assertIn(queue, tallies)
                self.assertEqual(
                    (b.n_real, b.n_artifact),
                    (tallies[queue]["real"], tallies[queue]["artifact"]),
                    f"{queue} has been relabelled since the fixture was "
                    f"extracted; re-extract it rather than editing either side")


if __name__ == "__main__":
    unittest.main()
