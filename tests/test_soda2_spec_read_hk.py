# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.spec_read_hk`` against GDL running SODA-2's own
`.pro`, and against an independently-coded ``struct``-only recomputation.

Three sides, exactly as `test_soda2_spec_read_frame.py` does it: GDL
executing NCAR's own IDL (`gdl_oracle/run_soda2_spec_read_hk_bank.py`, 12
cases -- 11 on a new synthetic HK fixture plus one, ``s2_real``, on the
pre-existing tracked ``tests/data/s2_spec_raw_fixture``), this Python port,
and a ``struct``-based recomputation that imports neither the port nor
NumPy and derives ``tas`` from the IEEE bit fields directly rather than by
the source's own ``dec2bin`` loop. Float32 values are compared as 8-hex-digit
IEEE bit patterns with no tolerance and no decimal parsing.
"""
from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.spec_read_hk import spec_read_hk

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "gdl_soda2_spec_read_hk_golden.json"
FIXTURE_RAW = DATA / "soda2_spec_hk_fixture"
S2_RAW = DATA / "s2_spec_raw_fixture"

_BUFFSIZE = 4114
_HEADERSIZE = 9  # words: 1-word footer + 8-word header, at every boundary.

FIXTURES = {"hk": FIXTURE_RAW, "s2": S2_RAW}


def _hex32(v: float) -> str:
    """A Python float's nearest float32, as an 8-hex-digit bit pattern --
    the same convention the golden was recorded with (`ulong(v,0)`
    type-punning under GDL)."""
    return f"{struct.unpack('<I', struct.pack('<f', v))[0]:08X}"


def _f32(v: float) -> float:
    """Round ``v`` to the nearest float32, kept as a Python (double) float."""
    return struct.unpack('<f', struct.pack('<f', v))[0]


def tas_hex(q_tas) -> str:
    return f"{np.float32(q_tas).view(np.uint32):08X}"


# ---------------------------------------------------------------------------
# The third side: a struct-only recomputation, sharing no code with either
# arrayprobe_soda2.spec_readint/spec_read_hk or NumPy. Only the published
# boundary-crossing arithmetic is unavoidably shared, as the spec_read_frame
# test already says of its own `_read_words`.
# ---------------------------------------------------------------------------

def _read_words(raw: bytes, pointer: int, length: int) -> tuple[list[int], int]:
    """Re-derive `spec_readint`'s answer (SIGNED, default buffsize) straight
    from the raw bytes, including the `:46-47` post-read footer jump.
    Returns (words, after)."""
    m1 = pointer // _BUFFSIZE
    m2 = (pointer + length * 2) // _BUFFSIZE
    crossings = m2 - m1

    if crossings == 0:
        chunk = raw[pointer:pointer + length * 2]
        words = list(struct.unpack(f"<{length}h", chunk))
        after = pointer + length * 2
    elif crossings == 1:
        total = length + _HEADERSIZE
        chunk = raw[pointer:pointer + total * 2]
        x2 = list(struct.unpack(f"<{total}h", chunk))
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


def _wrap16(v: int) -> int:
    """``2^exponent`` as GDL's 16-bit signed INT `^` evaluates it (`:38`)."""
    p = v % 65536
    if p >= 32768:
        p -= 65536
    return p


# Coefficient table (`:16-30`), retyped from the IDL literals independently
# of `spec_read_hk._C0`/`_C1` -- every literal is rounded to float32 with
# `_f32`, not imported from the port.
_F1 = _f32(0.00244140625)
_C0: list[float] = [0.0] * 49
for _i in range(9, 22):
    _C0[_i] = _f32(1.6)
_C0[24] = _f32(-3.846)

_C1: list[float] = [1.0] * 49
for _i in range(1, 7):
    _C1[_i] = _F1
for _i in range(7, 9):
    _C1[_i] = _f32(_F1 * 2)
for _i in range(9, 22):
    _C1[_i] = _f32(_F1 * 10)
for _i in range(22, 24):
    _C1[_i] = _f32(_F1 * 2)
_C1[24] = _f32(0.018356)
for _i in range(25, 33):
    _C1[_i] = _F1
for _i in range(36, 38):
    _C1[_i] = _f32(_F1 / 2)


def _independent_expected(raw: bytes, pointer: int) -> dict:
    """Re-implement `spec_read_hk.pro`'s version-1 arithmetic (`:13-40`) in
    plain Python, deriving `tas` from the IEEE bit fields of the
    reconstructed 32-bit word rather than the source's own `dec2bin8`/
    `dec2bin16` bit-array loop -- a genuinely different method, checked
    against the same golden."""
    words, after = _read_words(raw, pointer, 53)
    hi = words[49]
    lo = words[50]

    y_hex = []
    for i in range(49):
        t = _f32(words[i] * _C1[i])       # INT * FLOAT -> FLOAT (:32)
        y_hex.append(_hex32(_f32(t + _C0[i])))  # + FLOAT -> FLOAT, 2nd rounding

    # `tas` from the IEEE fields of the reconstructed 32-bit word, not from
    # dec2bin8/dec2bin16 (U4 in the plan: a disagreement here on
    # tas_sign_ignored/tas_mantissa_all_ones would indict this bit
    # extraction, not the port).
    bits = ((hi & 0xFFFF) << 16) | (lo & 0xFFFF)
    frac = (bits & 0x7FFFFF) / 2 ** 23
    k = ((bits >> 23) & 0x7F) + 1
    p = _wrap16(pow(2, k))
    # (1 + frac) * p is exact in double (a dyadic fraction times a power of
    # two, or zero, or -32768), so packing it to float32 is the ONLY rounding.
    tas_bits = struct.pack('<f', (1 + frac) * p)
    tas_hx = f"{struct.unpack('<I', tas_bits)[0]:08X}"

    time_hi = words[51]  # distinct from hi=words[49], the TAS high word
    time = ((time_hi & 0xFFFF) << 16) + words[52]
    time &= 0xFFFFFFFF

    return {"after": after, "time": time, "tas": tas_hx, "y": y_hex,
            "raw": words}


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking the port against IDL.")
        for path in FIXTURES.values():
            if not path.is_file():
                raise AssertionError(f"{path} is missing: a tracked fixture "
                                     "this bank depends on.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.raw = {k: v.read_bytes() for k, v in FIXTURES.items()}

    def _run(self, case: dict):
        with open(FIXTURES[case["fixture"]], "rb") as f:
            q = spec_read_hk(f, case["pointer"])
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
                self.assertEqual(q.time, case["TIME"], case["note"])
                self.assertEqual(tas_hex(q.tas), case["TAS"], case["note"])
                self.assertEqual(q.x.dtype, np.float32)
                self.assertEqual(q.x.shape, (49,))
                got_y = [f"{np.float32(v).view(np.uint32):08X}" for v in q.x]
                self.assertEqual(got_y, case["Y"], case["note"])
                self.assertEqual(q.raw.dtype, np.int16)
                self.assertEqual(list(map(int, q.raw)), case["RAW"], case["note"])
            checked += 1
        self.assertGreaterEqual(checked, 12)

    def test_the_generator_still_builds_the_tracked_fixture(self):
        gdl_oracle = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"
        if str(gdl_oracle) not in sys.path:
            sys.path.insert(0, str(gdl_oracle))
        import run_soda2_spec_read_hk_bank as bank
        self.assertEqual(bank.build_fixture(), FIXTURE_RAW.read_bytes())
        # The s2 fixture's own HK marker (18507 little-endian) must still be
        # where S4-g's evidence expects it -- if this ever moved, the whole
        # s2_real case would be reading something else entirely.
        self.assertEqual(self.raw["s2"][8262:8264], b"\x4b\x48")

    def test_every_case_also_matches_an_independent_struct_recomputation(self):
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            expected = _independent_expected(self.raw[case["fixture"]],
                                              case["pointer"])
            with self.subTest(case=case["name"]):
                self.assertEqual(expected["after"], case["AFTER"],
                                 f"{case['name']}: struct recomputation "
                                 f"disagrees with the GDL golden")
                self.assertEqual(expected["time"], case["TIME"])
                self.assertEqual(expected["tas"], case["TAS"])
                self.assertEqual(expected["y"], case["Y"])
                self.assertEqual(expected["raw"], case["RAW"])

                q, after = self._run(case)
                self.assertEqual(after, expected["after"],
                                 f"{case['name']}: port disagrees with the "
                                 f"independent struct recomputation")
                self.assertEqual(q.time, expected["time"])
                self.assertEqual(tas_hex(q.tas), expected["tas"])
                got_y = [f"{np.float32(v).view(np.uint32):08X}" for v in q.x]
                self.assertEqual(got_y, expected["y"],
                                 f"{case['name']}: port's x disagrees with "
                                 f"the independent struct recomputation")
            checked += 1
        self.assertGreaterEqual(checked, 12)

    def test_the_bank_reaches_every_branch(self):
        cases = self.cases
        self.assertTrue(
            any(c["RAW"][-1] < 0 and c["TIME"] < (c["RAW"][-2] << 16)
                for c in cases),
            "no case with RAW[52]<0 and TIME < RAW[51]<<16 (S4-g fired)")
        self.assertTrue(any(c["TIME"] > 2 ** 31 for c in cases),
                        "no TIME > 2**31 case (the ULONG wrap)")
        self.assertTrue(any(c["TAS"] == "00000000" for c in cases),
                        'no TAS=="00000000" case')
        self.assertTrue(any(c["TAS"] == "40000000" for c in cases),
                        'no TAS=="40000000" case')
        self.assertTrue(any(c["TAS"].startswith("C") for c in cases),
                        "no negative (0xC...) TAS case")
        self.assertTrue(any(c["RAW"][-4] < 0 for c in cases),
                        "no case with RAW[49]<0 (x[49] negative)")
        self.assertTrue(any(c["RAW"][-3] < 0 for c in cases),
                        "no case with RAW[50]<0 (x[50] negative)")
        self.assertTrue(
            any(c["pointer"] < _BUFFSIZE and c["AFTER"] > _BUFFSIZE
                for c in cases),
            "no case whose pointer starts before one buffer and AFTER lands "
            "past it (the straddling read)")
        self.assertTrue(any(c["AFTER"] % _BUFFSIZE == 16 for c in cases),
                        "no AFTER%%4114==16 case (the footer jump)")
        self.assertTrue(any(c["fixture"] == "s2" for c in cases),
                        'no fixture=="s2" case')


class TheVersionGate(unittest.TestCase):
    def test_an_unknown_version_is_refused_and_version_1_is_the_default(self):
        # Version 2 is ported: `test_soda2_spec_read_hk_v2`.
        with open(FIXTURE_RAW, "rb") as f:
            pointer = 16  # "plain"'s pointer

            # The port checks `version` before it ever seeks (`:8-14` in the
            # docstring's line-by-line), so a refusal must leave the file
            # position exactly where the call found it -- not at `pointer`.
            before = f.tell()
            with self.assertRaises(ValueError):
                spec_read_hk(f, pointer, version=3)
            self.assertEqual(f.tell(), before)

            default_q = spec_read_hk(f, pointer)
            explicit_q = spec_read_hk(f, pointer, version=1)
            self.assertEqual(default_q.time, explicit_q.time)
            self.assertEqual(tas_hex(default_q.tas), tas_hex(explicit_q.tas))
            np.testing.assert_array_equal(default_q.x, explicit_q.x)
            np.testing.assert_array_equal(default_q.raw, explicit_q.raw)


class TheSignedLowTimeWord(unittest.TestCase):
    """S4-g, isolated from the golden: the s2 fixture's own real-layout HK
    record has a low time word >= 0x8000, so `time` comes out 65536 low."""

    def test_line_40_reads_the_s2_records_time_65536_low(self):
        with open(S2_RAW, "rb") as f:
            q = spec_read_hk(f, 8262)
        self.assertEqual(q.time, 34464)
        # written out so the reader sees the intended value next to the
        # reproduced one: the raw words say 1, 34464 -> 100000, but S4-g
        # makes the assembled time 65536 short.
        self.assertEqual((1 << 16) + 34464, 100000)


if __name__ == "__main__":
    unittest.main()
