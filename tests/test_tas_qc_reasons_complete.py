# SPDX-License-Identifier: BSD-3-Clause
"""``tas_substituted_reasons`` must account for every substituted second.

Pass-5 item 9, 2026-09-26. ``tas_sources._reasons_text`` (``:489-494``) counts only the three
``TasPolicy.reason`` strings. The chain also substitutes with ``no-aircraft-sample``
(``:280``) and, on the probe tier, ``unsettled-duplicate`` and slash-joined multi-reason
strings such as ``above-cutoff/non-finite`` (``make_tas_file.py:469``, ``:478``). Those seconds
are in ``tas_substituted_count`` and ``tas_substituted_ranges`` but every reason reads 0, so
the record's own parts disagree, and ``merge_qc_records`` (``:603-607``) can never recover
them. Measured 2026-09-26 on synthetic chains: count 2, reasons all 0.

Fixed the same day: all five reasons are counted, a slash-joined reason under its first
component, so the reasons sum to ``tas_substituted_count``.
"""

from __future__ import annotations

import unittest

import numpy as np

from arrayprobe.tools import tas_sources as ts
from arrayprobe.tools.make_tas_file import TasPolicy


def _chain(tier, time, tas, substituted):
    return ts.ChainResult("auto", tier, "x", "p", np.asarray(time, float),
                          np.asarray(tas, float), TasPolicy(), [], substituted, [], {})


def _reason_total(rec):
    return sum(int(item.rsplit(":", 1)[1])
               for item in rec["tas_substituted_reasons"].split(";"))


class ReasonsCoverEverySubstitutedSecond(unittest.TestCase):
    def test_policy_reasons_are_counted(self):
        # Control: the three policy reasons do reach the record.
        c = _chain("aircraft", [120000, 120001], [170, 170],
                   [(120000, "above-cutoff"), (120001, "non-positive")])
        rec = ts.qc_record(c, TasPolicy(), [120000.0, 120001.0], [])
        self.assertEqual(rec["tas_substituted_count"], 2)
        self.assertEqual(_reason_total(rec), 2)

    def test_no_aircraft_sample_and_unsettled_duplicate_are_counted(self):
        c = _chain("aircraft", [120000, 120001, 120002], [100, 170, 170],
                   [(120001, "no-aircraft-sample"), (120002, "unsettled-duplicate")])
        rec = ts.qc_record(c, TasPolicy(), [120000.2, 120001.4, 120002.9], [])
        self.assertEqual(rec["tas_substituted_count"], 2)
        self.assertEqual(_reason_total(rec), rec["tas_substituted_count"])

    def test_slash_joined_probe_tier_reasons_are_counted(self):
        c = _chain("probe", [120000, 120001], [100, 170],
                   [(120001, "above-cutoff/non-finite")])
        rec = ts.qc_record(c, TasPolicy(), [120000.0, 120001.0], [])
        self.assertEqual(_reason_total(rec), 1)


if __name__ == "__main__":
    unittest.main()
