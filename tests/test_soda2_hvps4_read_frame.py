# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.hvps4_read_frame`` against the GDL golden
(``gdl_oracle/run_soda2_hvps4_read_frame_bank.py``), plus the guard that the
GDL-oracle shim of ``hvps4_read_frame.pro`` differs from the vendored file at
lines 39-40 only. ``array``/``res`` in every golden case are shim-derived.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe_soda2.hvps4_read_frame import hvps4_read_frame

HERE = Path(__file__).resolve().parent
PORT = HERE.parent
GOLDEN = HERE / "data" / "gdl_soda2_hvps4_read_frame_golden.json"
FIXTURE = HERE / "data" / "soda2_hvps4_frame_fixture"
SHIM = PORT / "scripts" / "validation" / "gdl" / "shims" / "hvps4_read_frame.pro"
VENDORED = _upstream.source("soda2") / "hvps4_read_frame.pro"

_TNAME = {"uint32": "ULONG", "int32": "LONG", "int16": "INT", "uint16": "UINT"}


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("soda2")


def _cases() -> dict[str, dict]:
    return {r["name"]: r for r in json.loads(GOLDEN.read_text(encoding="utf-8"))}


def _run(case: dict):
    with FIXTURE.open("rb") as f:
        q = hvps4_read_frame(f, case["pointer"], case["id"])
        after = f.tell()
    return q, after


@repo_only
class TheOracleShimDiffersOnlyAtLines39And40(unittest.TestCase):
    def test_shim_equals_vendored_except_lines_39_40(self) -> None:
        shim = SHIM.read_text(encoding="utf-8").splitlines()
        vend = VENDORED.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(shim), len(vend))
        differing = [i + 1 for i, (a, b) in enumerate(zip(shim, vend, strict=True))
                     if a != b]
        self.assertEqual(differing, [39, 40])
        self.assertEqual(vend[38].strip(), "array=id.substring(0,0)")
        self.assertEqual(vend[39].strip(), "res=fix(id.substring(1,3))")
        self.assertTrue(shim[38].strip().startswith("array=strmid(id,0,1)"))
        self.assertTrue(shim[39].strip().startswith("res=fix(strmid(id,1,3))"))

    def test_every_golden_case_is_labelled_shim_derived(self) -> None:
        for name, case in _cases().items():
            self.assertEqual(case["shim_derived"], ["array", "res"], name)


class EveryGoldenCaseMatches(unittest.TestCase):
    def test_all_cases_ok(self) -> None:
        cases = _cases()
        self.assertEqual(len(cases), 12)
        for name, case in cases.items():
            self.assertEqual(case["status"], "OK", name)

    def test_field_by_field_with_types(self) -> None:
        for name, case in _cases().items():
            with self.subTest(name):
                q, after = _run(case)
                self.assertEqual(after, case["AFTER"])
                self.assertEqual(int(q.error), case["ERROR"])
                self.assertEqual(int(q.overload), case["OVL"])
                self.assertEqual(int(q.particlecount), case["PC"])
                self.assertEqual(int(q.time), case["TIME"])
                self.assertEqual(q.image.shape[0], case["NSL"])
                tn = ",".join([_TNAME[q.overload.dtype.name],
                               _TNAME[q.error.dtype.name],
                               _TNAME[q.time.dtype.name],
                               _TNAME[q.particlecount.dtype.name], "BYTE"])
                self.assertEqual(tn, case["TN"])
                slices = ["".join(str(int(v)) for v in row) for row in q.image]
                self.assertEqual(slices, case["SLICES"])


class PreservedBehaviour(unittest.TestCase):
    def test_hvps4_read_frame_55_58_v_block_reads_from_buff_2_even_when_nh_gt_0(self) -> None:
        # The no-nh-offset finding: nh=5, nv=6; the V block's counter is buff[5:7] = [4, 0, 0x4202],
        # words of the H array, not the V array's own [0x30, 0x40, 0].
        q, _ = _run(_cases()["dual_v50"])
        self.assertEqual(int(q.time), 0x4202 + 4)

    def test_hvps4_read_frame_51_missing_time_word_is_error_1_without_stitching(self) -> None:
        case = _cases()["mtw"]
        q, after = _run(case)
        self.assertEqual(int(q.error), 1)
        self.assertEqual(after, case["AFTER"])  # no further frame read

    def test_hvps4_read_frame_48_ishft_32_adds_the_high_word_under_gdl(self) -> None:
        q, _ = _run(_cases()["high_counter"])
        self.assertEqual(int(q.time), (0xABCD << 16) + 0xFFFF + 3)


if __name__ == "__main__":
    unittest.main()
