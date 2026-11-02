# SPDX-License-Identifier: BSD-3-Clause
"""Regression for the ``int16 + Python int`` overflow/silent-wrap class at
``process_2d.py:585-588`` (`misc.imagepointers`, W2b).

``soda2_process_2d.pro:460`` is IDL ``LONG * ULONG64 + INT[]`` -> ULONG64,
stored into the LON64 field ``imagepointers`` (`:40`). IDL's integer rule
(same-width wraps, mixed-width promotes to the wider type, documented in
``spec_read_hk.py:68`` and ``particlesort.py:43``) never wraps or raises at
this line -- the mathematically exact absolute file offset is always the
right answer. NumPy 2's NEP-50 "weak scalar" rule instead keeps the
expression in the array's own ``int16`` dtype, giving two wrong regimes
(listed next):

- ``i*buffsize <= 32767`` (``i <= 7`` on a 4114-byte buffer): the cast
  succeeds and the sum **wraps silently** once ``i*buffsize + imagep >
  32767`` -- wrong particle pointers, no exception. W2's real-data run never
  saw this regime because it crashed at ``i = 9`` first.
- ``i*buffsize > 32767`` (``i >= 8``): ``OverflowError``. This is W2's
  crash (seen at ``i = 9`` with 37026).

Fixture: built in ``tempfile`` from the tracked ``soda2_spec_index_fixture``
(24 784 bytes; 6 buffers, ``buffsize=4114``, buffer 5 is a deliberate
bad-year header, S4-i) -- **not** a new tracked file. ``good = raw[:5*4114]``
(the five well-formed buffers), ``last = raw[5*4114:6*4114]`` (the bad-year
sixth); the test fixture is ``good*3 + last`` (65 824 bytes), tiling only
the well-formed buffers so the bad year never lands at a tile boundary
(tiling the whole 6-buffer file instead puts the 1999 header at ``i = 5``
of the next tile and ``spec_index`` raises ``SpecFileMisaligned`` --
measured). All pointer values below were measured this
session (2026-09-14) against exactly those bytes; they are the golden, not
derived.
"""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d
from arrayprobe_soda2.spec_index import _trim, spec_index

DATA = Path(__file__).resolve().parent / "data"
INDEX_FIXTURE = DATA / "soda2_spec_index_fixture"

#: Measured 2026-09-14 on `good*3 + last` -- the exact
#: absolute pointers for every image-bearing buffer, computed as
#: `i*buffsize + int(p)` in plain Python-int arithmetic.
_EXPECTED_EXACT_POINTERS: dict[int, list[int]] = {
    0: [16],
    1: [4250, 4268, 4346, 4514, 4638, 8130],
    2: [8264, 12338],
    3: [12374, 12398],
    4: [16472, 16506, 16534, 16556],
    5: [20586],
    6: [24820, 24838, 24916, 25084, 25208, 28700],
    7: [28834, 32908],
    8: [32944, 32968],
    9: [37042, 37076, 37104, 37126],
    10: [41156],
    11: [45390, 45408, 45486, 45654, 45778, 49270],
    12: [49404, 53478],
    13: [53514, 53538],
    14: [57612, 57646, 57674, 57696],
}

#: Measured 2026-09-14: the pre-fix expression (`i*buffsize + imagep_slice`,
#: plain Python `i*buffsize` against the fixture's own int16 `imagep`
#: array) on the two regimes described in the module docstring.
_OLD_EXPRESSION_SILENT_WRAP = {7: [28834, -32628]}
_OLD_EXPRESSION_OVERFLOWS = (8, 9)


def _tiled_fixture_bytes() -> bytes:
    raw = INDEX_FIXTURE.read_bytes()
    assert len(raw) == 24784, "soda2_spec_index_fixture changed size"
    good = raw[: 5 * 4114]
    last = raw[5 * 4114 : 6 * 4114]
    tiled = good * 3 + last
    assert len(tiled) == 65824
    return tiled


class ExactPointerMath(unittest.TestCase):
    """Assertion 1: the fixed expression, computed
    independently in plain Python-int arithmetic, matches the measured
    golden for every image-bearing buffer."""

    def setUp(self) -> None:
        self.y = spec_index(io.BytesIO(_tiled_fixture_bytes()))

    def test_sixteen_buffers_indexed(self) -> None:
        self.assertEqual(self.y.count, 16)
        self.assertEqual(self.y.buffsize, 4114)

    def test_every_image_bearing_buffer_matches_the_measured_golden(self) -> None:
        for i, expected in _EXPECTED_EXACT_POINTERS.items():
            n = int(self.y.numimages[i])
            self.assertGreater(n, 0, f"buffer {i} expected to carry images")
            fp = int(self.y.firstp[i])
            exact = [i * self.y.buffsize + int(p) for p in self.y.imagep[fp : fp + n]]
            self.assertEqual(exact, expected, f"buffer {i}")

    def test_i_equals_7_silent_wrap_regime(self) -> None:
        n = int(self.y.numimages[7])
        fp = int(self.y.firstp[7])
        exact = [7 * self.y.buffsize + int(p) for p in self.y.imagep[fp : fp + n]]
        self.assertEqual(exact, [28834, 32908])

    def test_i_equals_9_overflow_regime(self) -> None:
        n = int(self.y.numimages[9])
        fp = int(self.y.firstp[9])
        exact = [9 * self.y.buffsize + int(p) for p in self.y.imagep[fp : fp + n]]
        self.assertEqual(exact, [37042, 37076, 37104, 37126])


class PreFixExpressionFailsBothWays(unittest.TestCase):
    """Assertion 2: the check draws its two sides from
    different places -- the *old* expression (plain Python-int arithmetic
    against the fixture's own int16 `imagep` array, exactly as
    `process_2d.py` computed it before the fix) against the
    fixture's own measured numbers, not against the port's current
    (fixed) code."""

    def setUp(self) -> None:
        self.y = spec_index(io.BytesIO(_tiled_fixture_bytes()))

    def test_i_equals_7_wraps_silently_to_a_negative_offset(self) -> None:
        i = 7
        n = int(self.y.numimages[i])
        fp = int(self.y.firstp[i])
        sl = self.y.imagep[fp : fp + n]
        old = i * self.y.buffsize + sl  # the pre-fix expression
        self.assertEqual(list(old), _OLD_EXPRESSION_SILENT_WRAP[7])

    def test_i_equals_8_and_9_raise_overflow_error(self) -> None:
        for i in _OLD_EXPRESSION_OVERFLOWS:
            n = int(self.y.numimages[i])
            fp = int(self.y.firstp[i])
            sl = self.y.imagep[fp : fp + n]
            with self.assertRaises(OverflowError, msg=f"i={i}"):
                i * self.y.buffsize + sl  # the pre-fix expression


def _base_op(**overrides) -> dict:
    op = dict(
        fn="", date="20000101", starttime=24243.0, stoptime=24248.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0.0, 50.0, 100.0, 200.0, 500.0], arendbins=[0.0, 0.5, 1.0],
        rate=1.0, smethod="xy", pth="", particlefile=0, inttime_reject=0,
        stuckbits=0, water=0, fixedtas=0.0, timeoffset=0.0, armwidth=6.3,
        numdiodes=128, greythresh=0, probeid="H", eawmethod="centerin",
        wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0, asciipsdfile=0,
        savfile=0,  # no SAVE file (it would need `outdir`)
    )
    op.update(overrides)
    return op


class EndToEndThroughTheDriver(unittest.TestCase):
    """Assertion 3: the tiled bytes run through the
    whole driver -- not just `spec_index` -- with no `OverflowError`, and
    the accepted total cannot be less than one tile's (the 6-buffer run's
    own total). `date="20000101"` is more than 5 days off the file's own
    embedded date, so `:410-418` silently adopts the file's date (S6-b,
    already covered by `TraceLine410DateMismatch` in
    `test_soda2_process_2d.py`) rather than requiring this test to know
    the file's calendar date. Numbers below are measured 2026-09-14, not
    derived."""

    def test_tiled_run_has_no_overflow_and_accepts_at_least_as_much(self) -> None:
        raw = INDEX_FIXTURE.read_bytes()
        tiled = _tiled_fixture_bytes()
        with tempfile.TemporaryDirectory() as td:
            base_fn = os.path.join(td, "base.raw")
            tiled_fn = os.path.join(td, "tiled.raw")
            with open(base_fn, "wb") as fh:
                fh.write(raw)
            with open(tiled_fn, "wb") as fh:
                fh.write(tiled)

            d_base = soda2_process_2d(_base_op(fn=base_fn))
            d_tiled = soda2_process_2d(_base_op(fn=tiled_fn))  # must not raise OverflowError

        self.assertIsInstance(d_base, ProcessData)
        self.assertIsInstance(d_tiled, ProcessData)
        # Measured 2026-09-14: base (6-buffer) run accepts 5 buffers total,
        # 0 particles; the tiled (16-buffer, 3x the well-formed buffers)
        # run accepts 15 buffers, still >= the base run on both counts.
        self.assertEqual(int(d_base.numbuffsaccepted.sum()), 5)
        self.assertEqual(int(d_tiled.numbuffsaccepted.sum()), 15)
        self.assertGreaterEqual(
            int(d_tiled.numbuffsaccepted.sum()), int(d_base.numbuffsaccepted.sum()))
        self.assertGreaterEqual(
            int(d_tiled.count_accepted.sum()), int(d_base.count_accepted.sum()))


class TrimWrapsInsteadOfRaising(unittest.TestCase):
    """`spec_index._trim`'s over-range
    relative offsets wrap the way IDL's own assignment into a fixed-width
    array does (`spec_index.pro:96`), instead of raising under NumPy 2's
    NEP-50 rules. `40000` is out of `int16` range (max 32767); wrapped:
    `40000 - 65536 = -25536`, matching two's-complement/IDL INT truncation."""

    def test_over_range_value_wraps_like_idl_int_assignment(self) -> None:
        result = _trim([40000], np.int16)
        self.assertEqual(list(result), [-25536])

    def test_in_range_values_pass_through_unchanged(self) -> None:
        result = _trim([1, 2, 3], np.int16)
        self.assertEqual(list(result), [1, 2, 3])

    def test_empty_values_still_yield_the_zero_sentinel(self) -> None:
        result = _trim([], np.int16)
        self.assertEqual(list(result), [0])


if __name__ == "__main__":
    unittest.main()
