# SPDX-License-Identifier: BSD-3-Clause
"""S4-i (``spec_index.pro:71``'s ``FOR i=0L, numbuffs-2``) --
``last_buffer_index_fix.corrected_spec_index``.

A minimal, self-built two-buffer SPEC file (the same word-level
construction ``gdl_oracle/run_soda2_spec_index_bank.py`` uses, cut
down to what this test needs) makes the equivalence and A/B cases each
turn on nothing but whether the file's *last* buffer carries a real
frame -- rather than relying on the tracked ``s2_spec_raw_fixture``'s
own last-buffer content, which is a different, unrelated case (used
directly in ``tests/test_soda2_spec_index.py::
TheLastBufferIsNeverWalked``).
"""
from __future__ import annotations

import io
import unittest

from arrayprobe_soda2.spec_index import SpecIndex, spec_index

from arrayprobe_soda2_enhancements.last_buffer_index_fix import (
    LiteNotSupported,
    corrected_spec_index,
)
from arrayprobe_soda2_enhancements.registry import PROTECTIVE, REGISTRY, resolve

DATA_WORDS = 2048


def _header(year: int = 2016, month: int = 9, day: int = 2) -> list[int]:
    return [year, month, 2, day, 6, 6, 3, 250]  # dummy=2, matched across buffers


def _frame(nh: int, nv: int, pc: int, ns: int = 1) -> list[int]:
    return [12883, nh, nv, pc, ns] + [0] * (nh + nv)


def _buffer(words: list[int]) -> list[int]:
    data = [0] * DATA_WORDS
    for i, w in enumerate(words):
        data[i] = w
    return data


def _pack_two_buffers(buf0_words: list[int], buf1_words: list[int]) -> bytes:
    out = bytearray()
    for hdr, data in ((_header(), _buffer(buf0_words)),
                       (_header(), _buffer(buf1_words))):
        for w in hdr + data + [0]:
            out += int(w & 0xFFFF).to_bytes(2, "little")
    return bytes(out)


class Equivalence(unittest.TestCase):
    """The file's last buffer is blank (no '2S'/'HK'/'MK' markers) --
    the extra scan the correction adds finds nothing, so the two
    functions must agree on every field."""

    def test_matches_port_when_the_last_buffer_is_blank(self):
        raw = _pack_two_buffers(_frame(4, 0, 1), [])
        f_port, f_fixed = io.BytesIO(raw), io.BytesIO(raw)
        port_out = spec_index(f_port)
        fixed_out = corrected_spec_index(f_fixed)

        self.assertIsInstance(port_out, SpecIndex)
        self.assertEqual(fixed_out.count, port_out.count)
        self.assertEqual(fixed_out.buffsize, port_out.buffsize)
        self.assertEqual(list(fixed_out.numimages), list(port_out.numimages))
        self.assertEqual(list(fixed_out.firstp), list(port_out.firstp))
        self.assertEqual(list(fixed_out.imagep), list(port_out.imagep))
        self.assertEqual(list(fixed_out.ibuffer), list(port_out.ibuffer))
        self.assertEqual(list(fixed_out.particlecounter), list(port_out.particlecounter))
        self.assertEqual(list(fixed_out.arrayid), list(port_out.arrayid))
        self.assertEqual(list(fixed_out.date), list(port_out.date))
        self.assertEqual(list(fixed_out.bufftime), list(port_out.bufftime))
        # sanity: buffer 0's real frame was actually indexed by both
        self.assertEqual(int(port_out.numimages[0]), 1)


class ABConsequence(unittest.TestCase):
    """The file's last buffer carries a real frame: the port never
    scans it (S4-i); the correction does."""

    def test_a_real_frame_in_the_last_buffer_is_recovered(self):
        raw = _pack_two_buffers(_frame(4, 0, 1), _frame(4, 0, 17))
        f_port, f_fixed = io.BytesIO(raw), io.BytesIO(raw)
        port_out = spec_index(f_port)
        fixed_out = corrected_spec_index(f_fixed)

        last = port_out.count - 1
        self.assertEqual(last, 1)
        self.assertEqual(int(port_out.numimages[last]), 0, "the port's own S4-i gap")
        self.assertEqual(int(port_out.firstp[last]), -1)

        self.assertEqual(int(fixed_out.numimages[last]), 1)
        self.assertNotEqual(int(fixed_out.firstp[last]), -1)
        self.assertIn(17, list(fixed_out.particlecounter))
        self.assertIn(1, list(fixed_out.ibuffer))

        # Buffer 0's own indexing is untouched by the fix.
        self.assertEqual(int(fixed_out.numimages[0]), int(port_out.numimages[0]))
        self.assertEqual(int(fixed_out.firstp[0]), int(port_out.firstp[0]))


class Refusals(unittest.TestCase):
    def test_lite_is_refused_by_name(self):
        raw = _pack_two_buffers(_frame(4, 0, 1), [])
        with self.assertRaises(LiteNotSupported):
            corrected_spec_index(io.BytesIO(raw), lite=True)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("last_buffer_index_fix", REGISTRY)
        spec = REGISTRY["last_buffer_index_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-i")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_on_through_the_protective_set_false_when_opted_out(self):
        self.assertFalse(resolve({})["last_buffer_index_fix"])
        self.assertTrue(resolve({}, protective=PROTECTIVE)["last_buffer_index_fix"])
        self.assertFalse(
            resolve({"last_buffer_index_fix": False}, protective=PROTECTIVE)["last_buffer_index_fix"])
        self.assertFalse(resolve({"last_buffer_index_fix": False})["last_buffer_index_fix"])


if __name__ == "__main__":
    unittest.main()
