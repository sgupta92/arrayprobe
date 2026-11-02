# SPDX-License-Identifier: BSD-3-Clause
"""``tas_sources.write_soda2_pth_csv`` across midnight: fixed under the midnight convention
(UIOOPS's unwrapped
24xxxx-hours convention throughout, decided 2026-09-28).

The writer prints each sample as ``<seconds of day>,<tas>`` sorted from 0
(``tas_sources.py:678``). SODA-2's own clock does not wrap
(``arrayprobe_soda2.process_2d`` adds 86400 s per day since the start date to ``bufftime``),
and ``read_pth_ascii`` fills each accepted row forward from index
``(t - starttime) / rate``, clipped at 0. Before the fix, a flight crossing midnight fed this
writer *wrapped* post-midnight HHMMSS (``read_aircraft``'s own ``np.mod(..., 86400)``, since
withdrawn) so those rows' seconds-of-day landed before ``starttime`` and were clipped to index
0, overwriting the first row -- every post-midnight second silently took the last pre-midnight
speed instead of its own.

**The writer itself needed no change.** Under the unwrapped convention the builder now hands
it 240000 and later (``read_aircraft``/``check_tas_series``, fixed the same day in
``test_tas_chain_midnight_second.py``), which ``_hhmmss_to_sod`` already converts to 86400 s
and later -- past every pre-midnight second's seconds-of-day, so nothing collides. The test
below feeds the writer exactly what the fixed chain now produces (240000, 240001, ...) rather
than the old wrapped values, and was the one that failed before the chain fix landed (the chain
handed it 0.0/1.0, colliding with the pre-midnight rows). A test that pinned that collision
for a caller still passing wrapped values was retired 2026-10-02 to
``archive/retired_tests/test_soda2_pth_midnight__what_the_writer_does_today.txt``: it
asserted a defect outside the port as correct behaviour.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe.tools import tas_sources
from arrayprobe_soda2.pth_readers import read_pth_ascii


class Soda2PthAcrossMidnight(unittest.TestCase):

    def test_post_midnight_rows_keep_their_own_speed(self):
        # What the fixed chain now hands the writer: unwrapped HHMMSS past midnight.
        t = [235958.0, 235959.0, 240000.0, 240001.0]
        v = [100.0, 101.0, 200.0, 201.0]
        with tempfile.TemporaryDirectory() as d:
            pth = tas_sources.write_soda2_pth_csv(Path(d) / "p.csv", t, v)
            got = read_pth_ascii(pth, starttime=86398.0, rate=1.0, numrecords=4)
        self.assertEqual(got.tolist(), [100.0, 101.0, 200.0, 201.0])

    def test_a_series_within_one_day_is_written_in_time_order(self):
        with tempfile.TemporaryDirectory() as d:
            pth = tas_sources.write_soda2_pth_csv(Path(d) / "p.csv", [120001.0, 120000.0],
                                                  [2.0, 1.0])
            self.assertEqual(pth.read_text(), "43200,1.0\n43201,2.0\n")


if __name__ == "__main__":
    unittest.main()
