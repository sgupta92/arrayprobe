# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.spec_readint`` against GDL running SODA-2's own `.pro`,
and against an independently-coded recomputation from the raw fixture bytes.

Three sides, not two, on purpose: GDL executing NCAR's own IDL
(`gdl_oracle/run_soda2_spec_readint_bank.py`), this Python port (going
through a real file handle, `f.tell()`/`f.seek()`, NumPy dtypes), and a
``struct``-based recomputation directly against the tracked fixture's bytes
(no file handle, no NumPy, no import of this port at all) for every
non-all-zero case. A fixture compared with itself tests nothing; this way
the port has to agree with two differently-built answers.
"""
from __future__ import annotations

import json
import struct
import unittest
import warnings
from pathlib import Path

import numpy as np

from arrayprobe_soda2.spec_readint import spec_readint

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_spec_readint_golden.json"
RAW = Path(__file__).resolve().parent / "data" / "s2_spec_raw_fixture"

_HEADERSIZE = 9  # words: 1-word footer + 8-word header, at every 4114-byte boundary.


def _independent_expected(raw: bytes, pointer: int, length: int,
                          buffsize: int, signed: bool) -> list[int]:
    """Re-derive `spec_readint`'s answer straight from the raw bytes with
    ``struct``, deliberately not sharing a single line of code with
    ``arrayprobe_soda2.spec_readint`` or with NumPy. Only the published
    boundary-crossing arithmetic is unavoidably shared -- there is exactly
    one way to compute "how many buffer boundaries does this span cross" for
    a routine being tested against its own specification.
    """
    code = "h" if signed else "H"
    if buffsize == 0:
        chunk = raw[pointer:pointer + length * 2]
        return list(struct.unpack(f"<{length}{code}", chunk))

    m1 = pointer // buffsize
    m2 = (pointer + length * 2) // buffsize
    crossings = m2 - m1

    if crossings == 0:
        chunk = raw[pointer:pointer + length * 2]
        return list(struct.unpack(f"<{length}{code}", chunk))
    if crossings == 1:
        total = length + _HEADERSIZE
        chunk = raw[pointer:pointer + total * 2]
        x2 = list(struct.unpack(f"<{total}{code}", chunk))
        div = (buffsize - (pointer % buffsize)) // 2 - 1
        if div > 0:
            return x2[0:div] + x2[div + _HEADERSIZE:length + _HEADERSIZE]
        return x2[div + _HEADERSIZE:length + _HEADERSIZE]
    # 2+ crossings: finding S4-b, the original returns zeros of this length.
    return [0] * (length + crossings * _HEADERSIZE)


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking the port against IDL.")
        if not RAW.is_file():
            raise AssertionError(f"{RAW} is missing: the tracked SPEC fixture "
                                 "both this port and its golden depend on.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.raw = RAW.read_bytes()

    def _run(self, case: dict) -> np.ndarray:
        buffsize = 4114 if case["buffsize"] is None else case["buffsize"]
        with open(RAW, "rb") as f:
            f.seek(case["pointer"])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                x = spec_readint(f, case["length"], buffsize=buffsize,
                                 signed=case["signed"])
            after = f.tell()
        return x, after

    def test_every_case_matches_idl_exactly(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                got, after = self._run(case)
                self.assertEqual(len(got), case["N"], case["note"])
                self.assertEqual(list(int(v) for v in got), case["X"], case["note"])
                self.assertEqual(after, case["AFTER"], case["note"])
                expected_dtype = np.int16 if case["signed"] else np.uint16
                self.assertEqual(got.dtype, expected_dtype)
            checked += 1
        self.assertGreaterEqual(checked, 6)

    def test_every_nonzero_case_also_matches_an_independent_recomputation(self):
        """The third side: struct against the raw bytes, no file handle, no
        NumPy, never calling into this port. Skipped only for the all-zero
        2+-crossings case, where "expected" is a property of the finding
        (S4-b), not of the bytes -- both sides already agree it is zeros of
        the golden's own stated length."""
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            buffsize = 4114 if case["buffsize"] is None else case["buffsize"]
            expected = _independent_expected(self.raw, case["pointer"],
                                              case["length"], buffsize,
                                              case["signed"])
            with self.subTest(case=case["name"]):
                self.assertEqual(expected, case["X"],
                                 f"{case['name']}: independent struct "
                                 f"recomputation disagrees with the GDL golden")
                got, _after = self._run(case)
                self.assertEqual(list(int(v) for v in got), expected,
                                 f"{case['name']}: port disagrees with the "
                                 f"independent struct recomputation")
            checked += 1
        self.assertGreaterEqual(checked, 6)

    def test_the_bank_reaches_every_branch(self):
        names = {c["name"] for c in self.cases}
        buffsizes = {c["buffsize"] for c in self.cases}
        signed_flags = {c["signed"] for c in self.cases}
        self.assertIn(0, buffsizes, "no case drives the buffsize=0 bypass")
        self.assertIn(True, signed_flags, "no case drives /signed")
        self.assertTrue(
            any(c["N"] > c["length"] for c in self.cases if c["status"] == "OK"),
            "no case drives the 2+-crossings over-length return (S4-b)")
        self.assertIn("one_crossing_div_zero", names)


class TheTwoOrMoreCrossingsCaseWarnsAndOverreads(unittest.TestCase):
    """Finding S4-b, isolated from the golden: the returned array is longer
    than requested, every element is zero, a warning fires, and -- the part
    a naive port could get wrong without any test noticing on value alone --
    the file pointer still advances past the FULL over-length span, not just
    `length` words."""

    def test_two_crossings_returns_zeros_longer_than_asked_and_warns(self):
        buf = bytearray(3 * 4114)
        # Put a nonzero canary at the very start of the requested span so a
        # port that "fixed" this into reading real bytes would fail loudly.
        buf[16] = 0xFF
        buf[17] = 0xFF
        with open(io_path := _tmp_file(bytes(buf)), "rb") as f:
            f.seek(16)
            with self.assertWarns(UserWarning):
                x = spec_readint(f, 4200, buffsize=4114, signed=False)
            after = f.tell()
        self.assertEqual(len(x), 4200 + 2 * 9)
        self.assertTrue((x == 0).all(), "S4-b: every element must be zero")
        self.assertEqual(after, 16 + (4200 + 2 * 9) * 2,
                         "the file pointer must advance past the WHOLE "
                         "over-length span, matching the original readu")
        io_path.unlink()


def _tmp_file(data: bytes) -> Path:
    import tempfile
    fd, name = tempfile.mkstemp(suffix=".bin")
    path = Path(name)
    with open(fd, "wb") as f:
        f.write(data)
    return path


if __name__ == "__main__":
    unittest.main()
