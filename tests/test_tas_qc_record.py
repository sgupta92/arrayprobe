# SPDX-License-Identifier: BSD-3-Clause
"""TAS-gap metadata, step 1: ``tas_sources.qc_record`` and the ``.tasqc.json`` sidecar helpers.


"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe.tools import tas_sources
from arrayprobe.tools.make_tas_file import TasPolicy


def _chain(seconds, substituted=()):
    seconds = np.asarray(seconds, dtype=np.float64)
    return tas_sources.ChainResult(
        mode="auto", tier="aircraft", source="oracles-p3-merge", path="fake.nc",
        time=seconds, tas=np.full(seconds.shape, 100.0), policy=TasPolicy(), steps=[],
        substituted=list(substituted), lines=[], provenance={})


class FloorRoundResidual(unittest.TestCase):
    """A probe sample at ``x.6`` floors to ``x`` but rounds to ``x+1``; when the
    chain has ``x+1`` and not ``x``, that second is absent only because the axis is floored."""

    def test_floor_round(self):
        chain = _chain([120001, 120002, 120004])
        probe_t = [120000.6, 120001.2, 120003.6, 120004.0, 120010.3]
        _t, _v, missing = tas_sources.series_for_sizedist(
            probe_t, chain.time, chain.tas, chain.policy)
        self.assertEqual(missing, [120000, 120003, 120010])
        rec = tas_sources.qc_record(chain, chain.policy, probe_t, missing)
        self.assertEqual(rec["tas_missing_absent_count"], 3)
        # 120000.6 -> 120001 and 120003.6 -> 120004 are in the chain; 120010.3 -> 120010 is not.
        self.assertEqual(rec["tas_floor_round_residual_count"], 2)
        self.assertEqual(rec["tas_floor_round_residual_ranges"], "120000,120003")


class CountsAddUp(unittest.TestCase):

    def test_counts_add_up(self):
        chain = _chain([120000, 120001, 120002], substituted=[(120001, "above-cutoff")])
        probe_t = [120000.0, 120001.0, 120002.0, 120003.0]
        missing = [120003]
        legacy = [(120002, -999.0, "non-positive"), (130000, np.nan, "non-finite")]
        rec = tas_sources.qc_record(chain, chain.policy, probe_t, missing, legacy)
        self.assertEqual(rec["tas_seconds_total"], 4)
        self.assertEqual(rec["tas_substituted_count"], 2)   # 130000 is off the axis
        self.assertEqual(rec["tas_substituted_ranges"], "120001-120002")
        self.assertEqual(rec["tas_substituted_reasons"],
                         "above-cutoff:1;non-finite:0;non-positive:1;no-aircraft-sample:0;unsettled-duplicate:0")
        self.assertEqual(rec["tas_missing_count"], 1)
        defaulted = rec["tas_substituted_count"] + rec["tas_missing_count"]
        self.assertAlmostEqual(rec["tas_defaulted_fraction"], defaulted / 4)
        self.assertTrue(rec["tas_uncertainty"].startswith("3 of 4 seconds (75.00 %)"),
                        rec["tas_uncertainty"])


class UncertaintyText(unittest.TestCase):

    def test_uncertainty_text_none(self):
        chain = _chain([120000, 120001])
        rec = tas_sources.qc_record(chain, chain.policy, [120000.0, 120001.0], [])
        self.assertTrue(rec["tas_uncertainty"].startswith("none: "), rec["tas_uncertainty"])
        self.assertIn(chain.policy.token(), rec["tas_uncertainty"])
        self.assertEqual(rec["tas_chain_used"], "aircraft:oracles-p3-merge")

    def test_chain_used_names_the_source_kind(self):
        pol = TasPolicy()
        self.assertEqual(tas_sources.qc_record(None, pol, [1.0], [], [])["tas_chain_used"],
                         "tas-file")
        self.assertEqual(tas_sources.qc_record(None, pol, [1.0], [])["tas_chain_used"], "none")


class Sidecar(unittest.TestCase):

    def test_round_trip_sorted_and_absent(self):
        with tempfile.TemporaryDirectory() as d:
            product = Path(d) / "sd.x.H.nc"
            self.assertIsNone(tas_sources.read_qc_sidecar(product))
            rec = tas_sources.qc_record(_chain([1]), TasPolicy(), [1.0], [])
            path = tas_sources.write_qc_sidecar(product, rec)
            self.assertEqual(path.name, "sd.x.H.nc.tasqc.json")
            self.assertEqual(tas_sources.read_qc_sidecar(product), rec)
            text = path.read_text(encoding="utf-8")
            self.assertLess(text.index('"tas_chain_used"'), text.index('"tas_uncertainty"'))
            self.assertFalse(path.with_name(path.name + ".partial").exists())

    def test_foreign_convention_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            product = Path(d) / "sd.x.H.nc"
            tas_sources.write_qc_sidecar(product, {"tas_qc_convention": "other"})
            with self.assertRaises(ValueError):
                tas_sources.read_qc_sidecar(product)


class MergeForCombine(unittest.TestCase):
    """Step 5: a combined product's record is its parts' records summed, not the first part's."""

    def _parts(self):
        chain = _chain([120001, 120002, 120004], substituted=[(120002, "above-cutoff")])
        probe_a = [120000.6, 120001.2, 120002.0, 120003.6]
        _t, _v, miss_a = tas_sources.series_for_sizedist(probe_a, chain.time, chain.tas,
                                                         chain.policy)
        rec_a = tas_sources.qc_record(chain, chain.policy, probe_a, miss_a)
        probe_b = [120004.0, 120010.3, 120011.1]
        _t, _v, miss_b = tas_sources.series_for_sizedist(probe_b, chain.time, chain.tas,
                                                         chain.policy)
        rec_b = tas_sources.qc_record(chain, chain.policy, probe_b, miss_b)
        return [("sd.a.H.nc", rec_a), ("sd.b.H.nc", rec_b)]

    def test_counts_summed_and_parts_listed(self):
        parts = self._parts()
        (_, a), (_, b) = parts
        rec = tas_sources.merge_qc_records(parts)
        self.assertEqual(rec["tas_qc_parts"], "sd.a.H.nc,sd.b.H.nc")
        for key in ("tas_seconds_total", "tas_substituted_count", "tas_missing_count",
                    "tas_missing_absent_count", "tas_floor_round_residual_count"):
            self.assertEqual(rec[key], a[key] + b[key], key)
        self.assertEqual(rec["tas_missing_ranges"],
                         ",".join(r for r in (a["tas_missing_ranges"], b["tas_missing_ranges"])
                                  if r))
        self.assertEqual(rec["tas_missing_count"], 4)
        self.assertEqual(rec["tas_substituted_reasons"],
                         "above-cutoff:1;non-finite:0;non-positive:0;no-aircraft-sample:0;unsettled-duplicate:0")
        n_default = rec["tas_substituted_count"] + rec["tas_missing_count"]
        self.assertAlmostEqual(rec["tas_defaulted_fraction"],
                               n_default / rec["tas_seconds_total"])
        self.assertTrue(rec["tas_uncertainty"].startswith(
            f"{n_default} of {rec['tas_seconds_total']} seconds"))
        self.assertEqual(rec["tas_qc_convention"], tas_sources.QC_CONVENTION)

    def test_disagreeing_policies_refused(self):
        (na, a), (nb, b) = self._parts()
        b = dict(b, tas_policy=TasPolicy(cutoff_mps=250.0, default_mps=150.0).token())
        with self.assertRaises(ValueError):
            tas_sources.merge_qc_records([(na, a), (nb, b)])


if __name__ == "__main__":
    unittest.main()
