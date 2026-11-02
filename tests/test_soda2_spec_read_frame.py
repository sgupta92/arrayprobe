# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.spec_read_frame`` against GDL running SODA-2's own
`.pro`, and against an independently-coded ``struct``-only recomputation.

Three sides, not two, exactly as `test_soda2_spec_readint.py` does it: GDL
executing NCAR's own IDL (`gdl_oracle/run_soda2_spec_read_frame_bank.py`,
17 cases on a new synthetic frame fixture), this Python port (a real file
handle, NumPy dtypes, recursion through the same function), and a
``struct``-based recomputation straight off the fixture's raw bytes that
imports neither the port nor NumPy. A fixture compared with itself tests
nothing; this way the port has to agree with two differently-built answers.
"""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import needs_file, repo_only  # noqa: E402

from arrayprobe_soda2.spec_read_frame import spec_read_frame

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_spec_read_frame_golden.json"
RAW = Path(__file__).resolve().parent / "data" / "soda2_spec_frame_fixture"

_HEADERSIZE = 9  # words: 1-word footer + 8-word header, at every 4114-byte boundary.
_BUFFSIZE = 4114


# ---------------------------------------------------------------------------
# The third side: a struct-only recomputation, sharing no code with either
# arrayprobe_soda2.spec_readint/spec_read_frame or NumPy. Only the published
# boundary-crossing arithmetic is unavoidably shared, as in the readint test.
# ---------------------------------------------------------------------------

def _read_words(raw: bytes, pointer: int, length: int) -> tuple[list[int], int]:
    """Re-derive `spec_readint`'s answer (unsigned, default buffsize) straight
    from the raw bytes, and the file position after the read including the
    `:46-47` post-read footer jump. Returns (words, after)."""
    m1 = pointer // _BUFFSIZE
    m2 = (pointer + length * 2) // _BUFFSIZE
    crossings = m2 - m1

    if crossings == 0:
        chunk = raw[pointer:pointer + length * 2]
        words = list(struct.unpack(f"<{length}H", chunk))
        after = pointer + length * 2
    elif crossings == 1:
        total = length + _HEADERSIZE
        chunk = raw[pointer:pointer + total * 2]
        x2 = list(struct.unpack(f"<{total}H", chunk))
        div = (_BUFFSIZE - (pointer % _BUFFSIZE)) // 2 - 1
        if div > 0:
            words = x2[0:div] + x2[div + _HEADERSIZE:length + _HEADERSIZE]
        else:
            words = x2[div + _HEADERSIZE:length + _HEADERSIZE]
        after = pointer + total * 2
    else:  # pragma: no cover -- not exercised by this bank's cases
        total = length + crossings * _HEADERSIZE
        words = [0] * total
        after = pointer + total * 2

    if (after % _BUFFSIZE) == (_BUFFSIZE - 2):
        after += _HEADERSIZE * 2
    return words, after


def _independent_expected(raw: bytes, pointer: int, id_: str, version: int,
                          recursioncount: int = 0) -> dict:
    """Re-implement `spec_read_frame.pro`'s own arithmetic (`:11-97`) in
    plain Python, including the recursion, sharing no code with the port."""
    x, after1 = _read_words(raw, pointer, 3)
    nh = x[1] & 0xFFF
    nv = x[2] & 0xFFF
    missingtwh = (x[1] & 0x1000) >> 12
    missingtwv = (x[2] & 0x1000) >> 12
    overloadh = (x[1] & 0x8000) >> 15
    overloadv = (x[2] & 0x8000) >> 15

    buff, after2 = _read_words(raw, after1, 2 + nh + nv)
    particlecount = buff[0]

    imageraw: list[int] | str = "SCALAR:0"
    time = timetrunc = 0
    error = 1
    overload = 0
    gotframe = False
    nn = None
    counter = None
    missingtw = 0

    if nh > 3 and id_ == "H":
        if version == 1:
            nh -= 1
        imageraw = buff[2:nh]
        counter = buff[nh:nh + 2]
        overload = overloadh
        missingtw = missingtwh
        nn = nh
        gotframe = True

    if nv > 3 and id_ == "V":
        if version == 1:
            nv -= 1
        imageraw = buff[nh + 2:nh + nv]
        counter = buff[nh + nv:nh + nv + 2]
        overload = overloadv
        missingtw = missingtwv
        nn = nv
        gotframe = True

    after = after2
    if gotframe:
        if version == 0:
            time = (counter[0] << 16) + counter[1]
            timetrunc = counter[1]
        if version == 1:
            time = (counter[1] << 16) + counter[0]
            timetrunc = counter[0]

        if missingtw > 0 and recursioncount < 2:
            while True:
                q = _independent_expected(raw, after, id_, version,
                                          recursioncount + 1)
                after = q["after"]
                if q["error"] == 0:
                    break
            imageraw = (imageraw if isinstance(imageraw, list) else []) + (
                q["imageraw"] if isinstance(q["imageraw"], list) else [])
            time = q["time"]
            timetrunc = q["timetrunc"]
            overload = q["overload"]

        error = 0
        if overload == 0 and nn == 2:
            error = 1

    return {
        "after": after, "error": error, "overload": overload,
        "particlecount": particlecount, "time": time, "timetrunc": timetrunc,
        "imageraw": imageraw,
    }


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking the port against IDL.")
        if not RAW.is_file():
            raise AssertionError(f"{RAW} is missing: the tracked SPEC frame "
                                 "fixture both this port and its golden depend on.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.raw = RAW.read_bytes()

    def _run(self, case: dict):
        with open(RAW, "rb") as f:
            q = spec_read_frame(f, case["pointer"], case["id"],
                               version=case["version"])
            after = f.tell()
        return q, after

    def test_every_case_matches_idl_exactly(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                q, after = self._run(case)
                self.assertEqual(after, case["AFTER"], case["note"])
                self.assertEqual(q.error, case["ERROR"], case["note"])
                self.assertEqual(q.overload, case["OVL"], case["note"])
                self.assertEqual(q.particlecount, case["PC"], case["note"])
                self.assertEqual(q.time, case["TIME"], case["note"])
                self.assertEqual(q.timetrunc, case["TT"], case["note"])
                self.assertEqual(q.image.dtype, np.uint8)
                self.assertEqual(q.image.shape, (case["NSL"], 128))
                got_slices = ["".join(str(int(v)) for v in row)
                             for row in q.image]
                self.assertEqual(got_slices, case["SLICES"], case["note"])
                if case["IMRAW"] == "SCALAR:BYTE:0" or (
                        isinstance(case["IMRAW"], str)
                        and case["IMRAW"].startswith("SCALAR:")):
                    self.assertIsInstance(q.imageraw, np.uint8)
                    self.assertEqual(int(q.imageraw), 0)
                else:
                    self.assertEqual(list(int(v) for v in q.imageraw),
                                     case["IMRAW"], case["note"])
                    self.assertEqual(np.asarray(q.imageraw).dtype, np.uint16)
            checked += 1
        self.assertGreaterEqual(checked, 15)

    def test_the_generator_still_builds_the_tracked_fixture(self):
        gdl_oracle = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"
        if str(gdl_oracle) not in sys.path:
            sys.path.insert(0, str(gdl_oracle))
        import run_soda2_spec_read_frame_bank as bank
        self.assertEqual(bank.build_fixture(), RAW.read_bytes())

    def test_every_case_also_matches_an_independent_struct_recomputation(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            expected = _independent_expected(self.raw, case["pointer"],
                                              case["id"], case["version"])
            with self.subTest(case=case["name"]):
                self.assertEqual(expected["after"], case["AFTER"],
                                 f"{case['name']}: struct recomputation "
                                 f"disagrees with the GDL golden")
                self.assertEqual(expected["error"], case["ERROR"])
                self.assertEqual(expected["overload"], case["OVL"])
                self.assertEqual(expected["particlecount"], case["PC"])
                self.assertEqual(expected["time"], case["TIME"])
                self.assertEqual(expected["timetrunc"], case["TT"])

                q, after = self._run(case)
                self.assertEqual(after, expected["after"],
                                 f"{case['name']}: port disagrees with the "
                                 f"independent struct recomputation")
                self.assertEqual(q.error, expected["error"])
                self.assertEqual(q.overload, expected["overload"])
                self.assertEqual(q.time, expected["time"])
                self.assertEqual(q.timetrunc, expected["timetrunc"])
            checked += 1
        self.assertGreaterEqual(checked, 15)

    def test_the_bank_reaches_every_branch(self):
        cases = self.cases
        self.assertTrue(any(c["OVL"] == 1 for c in cases), "no OVL==1 case")
        self.assertTrue(any(c["id"] == "V" and c["ERROR"] == 0 for c in cases),
                         "no id=='V', ERROR==0 case")
        self.assertTrue(any(c["ERROR"] == 1 for c in cases), "no ERROR==1 case")
        self.assertTrue(any(c["version"] == 1 for c in cases), "no version==1 case")
        self.assertTrue(
            any(c["pointer"] < 4114 and c["status"] == "OK" and c["AFTER"] > 4114
                for c in cases),
            "no case whose pointer starts before 4114 and AFTER lands past it")
        self.assertTrue(
            any(isinstance(c["IMRAW"], list) and len(c["IMRAW"]) >= 6
                for c in cases),
            "no case with >=6 IMRAW words (the depth-capped chain)")


class TheOracleShimIsOneLine(unittest.TestCase):
    """The shim in `run_soda2_spec_read_frame_bank.py` must be the vendored
    `spec_decompress.pro` plus exactly one inserted line, never an edit to
    the vendored tree itself (`test_upstream_tree_is_unmodified.py` sweeps
    `SODA2/` separately; this asserts the shim's own construction)."""

    @repo_only
    @needs_file("SODA2/abansemer-soda2-afcea15/spec_decompress.pro")
    def test_shim_is_the_vendored_file_plus_exactly_one_line(self):
        gdl_oracle = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"
        if str(gdl_oracle) not in sys.path:
            sys.path.insert(0, str(gdl_oracle))
        import run_soda2_spec_read_frame_bank as bank
        from locate import SODA2_TREE

        vendored = (SODA2_TREE / "spec_decompress.pro").read_text(encoding="utf-8")
        vendored_lines = vendored.splitlines()
        shim_lines = bank.decompress_shim().splitlines()
        expected = (vendored_lines[:8] + [bank.SHIM_INSERTED_LINE]
                    + vendored_lines[8:])
        self.assertEqual(shim_lines, expected)
        self.assertEqual(vendored_lines[7].strip(), "n=n_elements(cimage)",
                         "the shim is inserted right after this line; if "
                         "the vendored source's line 8 has moved, U2 (the "
                         "plan's ranked uncertainty) applies")


class TheRecursionCap(unittest.TestCase):
    """S4-d, isolated from the golden: four contiguous `missingtw`-flagged
    fragments followed by a complete one -- the routine must stop after
    three fragments and report the third's own time, never reaching the
    fourth."""

    def _build(self, tmpdir: Path) -> tuple[Path, int]:
        gdl_oracle = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"
        if str(gdl_oracle) not in sys.path:
            sys.path.insert(0, str(gdl_oracle))
        from run_soda2_spec_read_frame_bank import A, frame

        f1 = frame(A + [1, 0], [], 100, 2, hflags=0x1000)
        f2 = frame(A + [2, 0], [], 101, 2, hflags=0x1000)
        f3 = frame(A + [3, 0], [], 102, 2, hflags=0x1000)
        f4 = frame(A + [4, 0], [], 103, 2)  # complete -- never read
        words = [0] * 8 + f1 + f2 + f3 + f4
        words += [0] * (2048 + 8 + 1 - len(words))
        raw = bytearray()
        for w in words:
            raw += int(w & 0xFFFF).to_bytes(2, "little")
        path = tmpdir / "chain.bin"
        path.write_bytes(bytes(raw))
        pointer = 16  # right after the 8-word header
        return path, pointer

    def test_line_74_stops_after_three_fragments_and_takes_time_from_the_third(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, pointer = self._build(Path(tmp))
            with open(path, "rb") as f:
                q = spec_read_frame(f, pointer, "H", version=0)
                after = f.tell()
            # Each fragment contributes 2 image words (A); three fragments.
            self.assertEqual(len(np.atleast_1d(q.imageraw)), 6)
            self.assertEqual(q.time, 3 << 16, "time must come from fragment 3")
            self.assertEqual(q.timetrunc, 0)
            # f1 is 9 words (18 bytes) starting at pointer 16 -> f2 @34,
            # f3 @52, f4 @70; AFTER must land on f4's start, never reading it.
            self.assertEqual(after, 16 + 3 * 18)


class TheNoFrameReturn(unittest.TestCase):
    """S4-e evidence, isolated from the golden: a frame too short to count
    (`nh<=3`) comes back `error=1` with the scalar `0b` initialiser, not an
    array -- and the file pointer still advances past the whole frame."""

    def test_a_short_frame_returns_error_1_with_the_int_initialiser(self):
        gdl_oracle = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"
        if str(gdl_oracle) not in sys.path:
            sys.path.insert(0, str(gdl_oracle))
        from run_soda2_spec_read_frame_bank import frame

        f1 = frame([5, 7], [], 50, 0)  # nh=2
        words = [0] * 8 + f1
        words += [0] * (2048 + 8 + 1 - len(words))
        raw = bytearray()
        for w in words:
            raw += int(w & 0xFFFF).to_bytes(2, "little")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.bin"
            path.write_bytes(bytes(raw))
            with open(path, "rb") as f:
                q = spec_read_frame(f, 16, "H", version=0)
                after = f.tell()
        self.assertEqual(q.error, 1)
        self.assertIsInstance(q.imageraw, np.uint8)
        self.assertEqual(int(q.imageraw), 0)
        self.assertEqual(q.image.shape, (1, 128))
        self.assertEqual(q.time, 0)
        self.assertEqual(after, 16 + len(f1) * 2, "the pointer must still "
                         "advance past the whole (too-short) frame")


if __name__ == "__main__":
    unittest.main()
