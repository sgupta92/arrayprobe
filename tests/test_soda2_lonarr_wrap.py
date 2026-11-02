# SPDX-License-Identifier: BSD-3-Clause
"""``soda2_buildindex.pro:43`` stores a LONG64 file pointer into a ``lonarr``;
GDL wraps it two's-complement without error. ``lonarr_store`` must match the
GDL golden (``gdl_oracle/run_soda2_lonarr_wrap_bank.py``).

Seek with the wrapped value, measured under GDL 2026-10-04 on a 4096-byte file
(banked as ``negative_seek`` in the golden): ``point_lun`` with -2147483648 from
position 100 raised no error, left the position at 100 and the next ``readu``
returned byte 100. So the negative seek is ignored, not moved to 0, and
``soda2_process_2d.pro:451`` silently reads from wherever the pointer was for a
buffer stored past 2 GiB. The port's bug-for-bug seek is ``buildindex.point_lun``.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from arrayprobe_soda2.buildindex import lonarr_store, point_lun

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_lonarr_wrap_golden.json"


class TestLonarrStoreMatchesGDL(unittest.TestCase):
    def test_every_golden_case(self) -> None:
        cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 5)
        for case in cases:
            with self.subTest(assigned=case["assigned"]):
                self.assertEqual(lonarr_store(case["assigned"]), case["stored"])

    def test_gdl_raised_no_error(self) -> None:
        self.assertEqual(json.loads(GOLDEN.read_text(encoding="utf-8"))["stderr"], "")

    def test_negative_seek_is_ignored_like_gdl(self) -> None:
        import io
        g = json.loads(GOLDEN.read_text(encoding="utf-8"))["negative_seek"]
        self.assertEqual(g["stderr"], "")
        f = io.BytesIO(bytes(i % 256 for i in range(4096)))
        f.seek(g["start"])
        point_lun(f, g["pointer"])
        self.assertEqual(f.tell(), g["cur_ptr_after"])
        self.assertEqual(f.read(1)[0], g["next_byte"])

    def test_in_range_values_pass_through(self) -> None:
        for v in (0, 1, 157, 2**31 - 1):
            self.assertEqual(lonarr_store(v), v)


if __name__ == "__main__":
    unittest.main()
