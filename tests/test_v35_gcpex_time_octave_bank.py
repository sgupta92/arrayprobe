# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 GCPEx-CIP time block (``imgProc_sm.m:976-1094``) against its Octave golden.

The golden is ``tests/data/v35_gcpex_time_octave_golden.json``, written by
``octave_oracle/run_v35_gcpex_time_bank.py`` from the block's own lines sliced
out of the vendored v3.5 file. Runs without Octave.

The port side is the three steps ``arrayprobe_uiops.imgproc._particle_time_dmt_v35``
takes on this branch: :func:`gcpex_cip_offsets`, the three ``(kk)`` additions
(``:1077-1079``) and :func:`_normalise_part_time` (``:1081-1093``). Every value is
a small integer, so equality is exact.

Each case is in the golden twice: ``hdr == "nc"`` gives the record header the
classes ``netcdf.getVar`` returns for ``read_binary_DMT.m:36-41``'s declared types
(int8 clock fields, int16 ``millisec``), ``hdr == "double"`` hands the same values
in as double. The pipeline only ever sees the ``nc`` classes, so the port
follows them: MATLAB's ``recTime + handles.millisec/1000.`` is double + int16,
which is int16 and saturates at 32767, so ``:980`` always takes the first
branch and ``:982-986`` are dead. :func:`gcpex_cip_offsets` emulates that
(pass 6; found in pass 5, item 2), so it equals every ``nc`` row and every
``double`` row except the 01/19 ones at or after 55660.09 s, which a double
header would route differently and which no ``getVar`` read can produce.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests import _upstream
from tests._repo import repo_only

from arrayprobe_uiops.imgproc import _normalise_part_time, _Record, gcpex_cip_offsets

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "data" / "v35_gcpex_time_octave_golden.json"
V35_IMGPROC = _upstream.source("uiops35") / "imgProc_sm.m"

#: The 01/19 threshold the int16 saturation makes unreachable (:980).
_SAT_THRESHOLD = 55660.09


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _load():
    return json.loads(GOLDEN.read_text())


def _port(case: dict) -> tuple[tuple[int, int, int], list, list, list]:
    rec = {k: float(case[k]) for k in ("month", "day", "hour", "minute", "second",
                                       "millisec")}
    acc = _Record()
    n = len(case["part_hour"])
    for i in range(n):
        acc.part_hour[i + 1] = float(case["part_hour"][i])
        acc.part_min[i + 1] = float(case["part_min"][i])
        acc.part_sec[i + 1] = float(case["part_sec"][i])
    kk = n
    d_h, d_m, d_s = gcpex_cip_offsets(rec)
    acc.part_hour[kk] = acc.part_hour[kk] + d_h                       # :1077
    acc.part_min[kk] = acc.part_min[kk] + d_m                         # :1078
    acc.part_sec[kk] = acc.part_sec[kk] + d_s                         # :1079
    _normalise_part_time(acc)                                         # :1081-1093
    return ((d_h, d_m, d_s), acc.part_hour.asarray().tolist(),
            acc.part_min.asarray().tolist(), acc.part_sec.asarray().tolist())


def _as_list(v):
    return list(v) if isinstance(v, list) else [v]


def _octave(result: dict):
    return (tuple(result["offsets"]), [float(x) for x in _as_list(result["part_hour"])],
            [float(x) for x in _as_list(result["part_min"])],
            [float(x) for x in _as_list(result["part_sec"])])


def _saturated(case: dict) -> bool:
    t = case["hour"] * 3600 + case["minute"] * 60 + case["second"] + case["millisec"] / 1000
    return (case["month"], case["day"]) == (1, 19) and t >= _SAT_THRESHOLD


@unittest.skipUnless(GOLDEN.is_file(), "GCPEx time Octave golden not present")
class TestGcpexTimeBlockAgainstOctave(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        g = _load()
        cls.golden = g
        cls.cases = {c["name"]: c for c in g["cases"]}
        cls.results = [(r, cls.cases[r["name"]]) for r in g["results"]]

    @repo_only
    def test_the_golden_was_sliced_from_the_vendored_file_as_it_stands(self):
        first, last = self.golden["block_lines"]
        _upstream.require("uiops35")
        lines = V35_IMGPROC.read_text(encoding="utf-8", errors="replace").splitlines()
        self.assertEqual("\n".join(lines[first - 1:last]) + "\n", self.golden["block_text"])

    def test_every_double_header_row_outside_the_saturated_range_matches(self):
        rows = [(r, c) for r, c in self.results if r["hdr"] == "double"]
        self.assertEqual(len(rows), len(self.cases))
        rows = [(r, c) for r, c in rows if not _saturated(c)]
        self.assertGreater(len(rows), 90)
        for r, c in rows:
            with self.subTest(case=c["name"]):
                self.assertEqual(_port(c), _octave(r))

    def test_every_nc_header_row_outside_the_saturated_range_matches(self):
        rows = [(r, c) for r, c in self.results if r["hdr"] == "nc" and not _saturated(c)]
        self.assertGreater(len(rows), 90)
        for r, c in rows:
            with self.subTest(case=c["name"]):
                self.assertEqual(r["millisec_class"], "int16")
                self.assertEqual(_port(c), _octave(r))

    def test_octave_saturates_the_0119_sum_at_int16_max(self):
        """What the finding rests on, read from the golden alone."""
        rows = [r for r, c in self.results if r["hdr"] == "nc" and _saturated(c)]
        self.assertEqual(len(rows), 9)
        for r in rows:
            with self.subTest(case=r["name"]):
                self.assertEqual(r["probe_t"], 32767)
                self.assertEqual(r["offsets"], [14, 40, 53])

    def test_nc_header_rows_in_the_saturated_range_match(self):
        """Pass 5 item 2 found the port taking ``:982-986`` for 01/19 records at
        or after 55660.09 s; MATLAB, with int16 ``handles.millisec``, never does.
        Minimal input: month=1, day=19, 15:27:40, millisec=90, one particle."""
        rows = [(r, c) for r, c in self.results if r["hdr"] == "nc" and _saturated(c)]
        self.assertEqual(len(rows), 9)
        for r, c in rows:
            self.assertEqual(_port(c), _octave(r), c["name"])


if __name__ == "__main__":
    unittest.main()
