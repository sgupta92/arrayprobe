# SPDX-License-Identifier: BSD-3-Clause
"""The synthetic inputs behind ``tests/data/reader_edge_octave_golden.npz``.

One builder per case, shared by the Octave bank that made the golden
(``octave_oracle/run_reader_edge_bank.py``) and by the tests that compare the
port with it (``tests/test_reader_edge_octave.py``), so both sides read the same
bytes; the golden also stores each input's SHA-256. It lives under ``tests/`` so
it travels with the test suite.

The SPEC cases start from ``tests/data/s2_spec_raw_fixture`` (six records,
built by ``octave_oracle/run_s2_spec_bank.py``); the packet helpers repeat that
bank's layout rules, read from ``read_binary_SPEC.m``'s ``get_img``.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent / "data"
S2_FIXTURE = DATA / "s2_spec_raw_fixture"

# --------------------------------------------------------------------------
# SPEC
# --------------------------------------------------------------------------

RECORD_WORDS = 2057  # 8 header words, 2048 data words, 1 discarded
RECORD_BYTES = 2 * RECORD_WORDS
MARKER_2S, MARKER_HK = 12883, 18507


def _run_word(aa: int, bb: int, new_slice: bool = False) -> int:
    """``aa`` shadowed diodes after ``bb`` clear ones; bit 14 starts a slice."""
    return (0x4000 if new_slice else 0) | (aa << 7) | bb


def _image_packet(runs, n_s, t_particle, pc=7):
    """An H-channel ``'2S'`` packet with its two-word particle time."""
    payload = [*runs, (t_particle >> 16) & 0xFFFF, t_particle & 0xFFFF]
    return [MARKER_2S, len(payload), 0, pc, n_s, *payload]


def _hk_packet(tas_words, n_hol, t_hi, t_lo):
    """A 53-word ``'KH'`` packet: TAS words at 50/51, time at 52/53, counts at
    34/35 and 42-45, end-diode voltages at 2-7 (1-based from the marker)."""
    w = [0] * 53
    w[0] = MARKER_HK
    w[1:7] = [1001, 1002, 1003, 1004, 1005, 1006]
    w[33], w[34] = 66, 77
    w[40], w[41], w[42], w[43], w[44] = 11, 22, 33, n_hol, 0
    w[49], w[50] = tas_words
    w[51], w[52] = t_hi, t_lo
    return w


def _raw(records) -> bytes:
    out = np.zeros((len(records), RECORD_WORDS), dtype="<u2")
    for i, (header, data) in enumerate(records):
        out[i, :8] = header
        out[i, 8:8 + len(data)] = data
    return out.tobytes()


def _spec_full() -> bytes:
    return S2_FIXTURE.read_bytes()


def _spec_tas(kind: str) -> bytes:
    """Records whose housekeeping packets exercise the v3.5 airspeed gate's class.

    ``types``: a rejected reading (hold-over count), an accepted one, a rejected
    one after it, a record with no packet, another accepted one; millisecond
    stamps and 32-bit ``time`` counters that single precision cannot hold.
    ``nan``: accepted NaN, +Inf and -Inf readings.
    """
    def f32(value):
        bits = int(np.float32(value).view(np.uint32))
        return [bits >> 16, bits & 0xFFFF]

    def header(s, ms):
        return [2016, 9, 2, 6, 12, 34, s, ms]

    runs = [_run_word(10, 5, new_slice=True), _run_word(8, 3)]

    def img(k):
        return _image_packet(runs, 2, 0x10000 * k)

    if kind == "types":
        recs = [
            (header(50, 789), img(1) + _hk_packet(f32(111.1), 3, 0x0123, 0x4567)),
            (header(51, 333), img(2) + _hk_packet(f32(123.4), 0, 0x0123, 0x4569)),
            (header(52, 777), img(3) + _hk_packet(f32(99.9), 2, 0x0123, 0x456B)),
            (header(53, 1), img(4)),
            (header(54, 999), img(5) + _hk_packet(f32(88.8), 0, 0x0FFF, 0xFFFF)),
            (header(55, 5), img(6)),
        ]
    else:
        recs = [
            (header(50, 789), img(1) + _hk_packet([0x7FC0, 0], 0, 0x0123, 0x4567)),
            (header(51, 333), img(2) + _hk_packet([0x7F80, 0], 0, 0x0123, 0x4569)),
            (header(52, 777), img(3) + _hk_packet([0xFF80, 0], 0, 0x0123, 0x456B)),
            (header(53, 1), img(4)),
        ]
    return _raw(recs)


SPEC_CASES = {
    "spec_p1": lambda: _spec_full()[:5 * RECORD_BYTES + 1],
    "spec_p17": lambda: _spec_full()[:5 * RECORD_BYTES + 17],
    "spec_p2000": lambda: _spec_full()[:5 * RECORD_BYTES + 2000],
    "spec_p4113": lambda: _spec_full()[:5 * RECORD_BYTES + 4113],
    "spec_one_plus_2000": lambda: _spec_full()[:RECORD_BYTES + 2000],
    "spec_zero_plus_4113": lambda: _spec_full()[:4113],
    "spec_zero_plus_2000": lambda: _spec_full()[:2000],
    "spec_zero_plus_17": lambda: _spec_full()[:17],
    "spec_empty": lambda: b"",
    "spec_tas_types": lambda: _spec_tas("types"),
    "spec_tas_nan": lambda: _spec_tas("nan"),
}

# --------------------------------------------------------------------------
# DMT / SEA
# --------------------------------------------------------------------------

AA = [0xAA] * 8


def compress(chunks) -> bytes:
    """A 4096-byte DMT/SEA payload: ``('lit', bytes)``, ``('zero', n)``,
    ``('fill', n)`` runs, padded with marker bytes that decode to nothing."""
    pay: list[int] = []
    for kind, v in chunks:
        if kind == "lit":
            v = list(v)
            while v:
                c, v = v[:32], v[32:]
                pay += [len(c) - 1, *c]
        else:
            top = 0x80 if kind == "zero" else 0x40
            while v > 0:
                c = min(v, 32)
                v -= c
                pay.append(top | (c - 1))
    assert len(pay) <= 4096, len(pay)
    return bytes(pay + [0x20] * (4096 - len(pay)))


def groups(n: int, seed: int) -> list[int]:
    """``n`` 8-byte groups of bytes below 0xA0, so none is a sync byte."""
    rng = np.random.default_rng(seed)
    return [int(x) for x in rng.integers(0, 0xA0, size=8 * n)]


def dmt_record(chunks, second=44) -> bytes:
    head = np.asarray((2016, 9, 2, 6, 6, second, 250, 5), dtype="<u2").tobytes()
    return head + compress(chunks)


def _dmt_base() -> bytes:
    return dmt_record([("lit", AA + groups(20, 1))], second=1)


DMT_CASES = {
    "dmt_control": lambda: _dmt_base() * 2,
    "dmt_nibble_before_sentinel": lambda: dmt_record([("lit", [0x11, 0xA3] + AA + groups(20, 2))]),
    "dmt_eight_high_nibble_a": lambda: dmt_record(
        [("lit", [0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8] + groups(3, 3) + AA
          + groups(20, 4))]),
    "dmt_over_1700": lambda: _dmt_base() + dmt_record(
        [("lit", AA + groups(2, 5)), ("zero", 1800 * 8)], second=2),
    "dmt_exactly_1700": lambda: _dmt_base() + dmt_record([("lit", AA), ("zero", 1700 * 8)],
                                                         second=2),
    "dmt_over_1700_first": lambda: dmt_record([("lit", AA), ("zero", 1800 * 8)],
                                              second=3) + _dmt_base(),
    "dmt_over_1700_chain": lambda: (
        _dmt_base() + dmt_record([("lit", AA), ("zero", 1800 * 8)], second=2)
        + dmt_record([("lit", AA), ("zero", 1750 * 8)], second=3)
        + dmt_record([("lit", AA + groups(9, 9))], second=4)),
    "dmt_three_groups": lambda: dmt_record([("lit", AA + groups(3, 6))]),
    "dmt_zero_groups": lambda: dmt_record([("lit", AA + [1, 2, 3])]),
    "dmt_tail_19": lambda: _dmt_base() + b"\x00" * 19,
    "dmt_tail_20": lambda: _dmt_base() + b"\x00" * 20,
    "dmt_tail_2000": lambda: _dmt_base() + _dmt_base()[:2000],
    "dmt_tail_4110": lambda: _dmt_base() + _dmt_base()[:4110],
    "dmt_tail_4111": lambda: _dmt_base() + _dmt_base()[:4111],
    "dmt_empty": lambda: b"",
    "dmt_low_nibble_a_only": lambda: dmt_record([("lit", [0x1A] * 8 + groups(5, 7))]),
}


def _sea_dir(tag, offset=0, nbytes=0) -> bytes:
    return struct.pack("<5H4BH", tag, offset, nbytes, 0, 0, 0, 0, 0, 0, 0)


def sea_cip(chunks, second) -> bytes:
    """A 33000/4098 CIP record whose 999 successor skips its time and payload."""
    g = struct.pack("<9H", 2016, 9, 6, 7, 8, second, 123, 0, 0)
    return (_sea_dir(33000, 0, 4098) + _sea_dir(999, 36 + 4098) + g + g
            + compress(chunks) + b"\x00\x00")


def sea_file(*recs) -> bytes:
    return b"".join(_sea_dir(1, 0) + r for r in recs)


def _sea_ctl() -> bytes:
    return sea_cip([("lit", AA + groups(20, 1))], 1)


SEA_CASES = {
    "sea_control": lambda: sea_file(_sea_ctl()),
    "sea_nibble_before": lambda: sea_file(sea_cip([("lit", [0x11, 0xA3] + AA + groups(20, 2))], 2)),
    "sea_run_at_end": lambda: sea_file(_sea_ctl(), sea_cip([("lit", groups(3, 3) + AA)], 3)),
    "sea_three_groups": lambda: sea_file(sea_cip([("lit", AA + groups(3, 4))], 4)),
    "sea_zero_groups": lambda: sea_file(sea_cip([("lit", AA + [1, 2, 3])], 5)),
    "sea_seven_groups": lambda: sea_file(sea_cip([("lit", AA + groups(7, 5))], 5)),
    "sea_eight_groups": lambda: sea_file(sea_cip([("lit", AA + groups(8, 5))], 5)),
    "sea_over_1700": lambda: sea_file(_sea_ctl(), sea_cip(
        [("lit", AA + groups(2, 6)), ("zero", 1800 * 8)], 6)),
    "sea_exactly_1700": lambda: sea_file(_sea_ctl(), sea_cip([("lit", AA), ("zero", 1700 * 8)],
                                                             7)),
    "sea_empty": lambda: b"",
    "sea_three_bytes": lambda: b"\x01\x00\x00",
    "sea_outer_partial_999": lambda: _sea_dir(999, 0)[:10],
    "sea_outer_partial_other": lambda: _sea_dir(7, 0)[:10],
    "sea_payload_4097": lambda: sea_file(_sea_ctl())[:-1],
    "sea_payload_4096": lambda: sea_file(_sea_ctl())[:-2],
}

# --------------------------------------------------------------------------
# PMS
# --------------------------------------------------------------------------

_XML = b'<?xml version="1.0"?>\n<OAP>\n<Probe id="C1"/>\n</OAP>\n'


def pms_record(tag=b"C1", second=5) -> bytes:
    head = struct.pack(">9H", 6, 7, second, 2016, 9, 6, 100, 250, 3)
    return tag + head + (np.arange(4096) % 251).astype(np.uint8).tobytes()


PMS_CASES = {
    "pms_two": lambda: _XML + pms_record() + pms_record(second=6),
    "pms_header_only": lambda: _XML,
    "pms_header_no_newline": lambda: _XML.rstrip(b"\n"),
    "pms_first_partial_c1": lambda: _XML + pms_record()[:100],
    "pms_first_partial_unknown": lambda: _XML + pms_record(tag=b"XX")[:100],
    "pms_first_partial_1byte": lambda: _XML + b"C",
    "pms_tail_partial": lambda: _XML + pms_record() + pms_record()[:100],
}

CASES = {**SPEC_CASES, **DMT_CASES, **SEA_CASES, **PMS_CASES}


def case_bytes(case: str) -> bytes:
    """The input for one case."""
    return CASES[case]()
