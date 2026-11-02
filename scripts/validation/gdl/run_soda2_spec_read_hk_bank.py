# SPDX-License-Identifier: BSD-3-Clause
r"""SPEC buffer decode: `spec_read_hk.pro` under GDL, unmodified, against a new
tracked synthetic HK fixture plus the real-layout HK record already inside
`tests/data/s2_spec_raw_fixture`.

`spec_read_hk` reads a 53-word (version 1, "2DS/HVPS3") housekeeping record:
channel 0 is the `'HK'` marker word itself, channels 1-48 are diode voltages
converted through a fixed coefficient table (`c0`/`c1`), channels 49-50 pack
a custom floating-point TAS encoding (mantissa bits extracted with
`dec2bin8`/`dec2bin16`, an exponent recovered with `ishft` -- "Only works
for positive exponents", the source's own comment -- and a **16-bit integer**
`2^exponent`, not a real float power), and channels 51-52 assemble a 32-bit
`time` word whose low half is read **signed** (`spec_readint(...,/signed)`)
and added to the shifted high half without re-masking, so any low word
>= 0x8000 makes `time` 65536 too small. `version` is never passed by either
caller in the vendored tree (`soda2_processbuffer.pro:285`,
`spec_process_hk.pro:65` passes `version=version` but that variable is only
ever 1 for the ORACLES 2D-S), so this bank never sets it either -- it is the
literal call shape production code uses.

**No shim needed.** Every one of the 12 cases below ran clean under GDL
1.1.2 in the planning session -- unlike `spec_read_frame`'s bank, nothing
here calls `ishft` on a value GDL disagrees with real IDL about in a way
that reaches a scalar-vs-array trap.

**The fixture** (`tests/data/soda2_spec_hk_fixture`, 3 x 4114-byte SPEC
buffers = 12342 bytes, synthetic, no campaign data) packs eleven hand-placed
53-word HK records end to end: an ordinary record (`plain`), one whose low
time word is >= 0x8000 (`time_lo_neg`, S4-g), one with a zero high time word
so the ULONG assembly wraps (`time_hi0_lo_neg`), three that drive the
16-bit-wrapped `2^exponent` through its interesting values -- 0.0 decoding
to 2.0 (`tas_zero_words`), a sub-2 m/s TAS decoding to 0.0 (`tas_lt2`,
exponent 128 -> 2^128 wraps to 0), and a value at 2^15 wrapping negative
(`tas_2p15_wrap`) -- one exercising the all-ones mantissa
(`tas_mantissa_all_ones`) and one showing the sign/exponent-MSB bits of
`x[49]` are ignored by construction (`tas_sign_ignored`), one with the
`XE` extremes vector in every `y` channel (`y_extremes`), one whose 53-word
read straddles the buffer-0/buffer-1 boundary (`straddle`), and one whose
read ends exactly on a buffer footer (`on_footer`). A twelfth case,
`s2_real`, reads the pre-existing `tests/data/s2_spec_raw_fixture` at byte
offset 8262, the real HK marker location measured by scanning that file for
the `'HK'` value 18507 -- this is S4-g's evidence on a real-layout record
(time words 1, 34464 -> 34464, where the words mean 100000).

`build_fixture()` is the single source of truth for the byte layout;
`POINTERS` names where each case starts.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_spec_read_hk_bank.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, run_pro  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

DATA = Path(__file__).resolve().parents[3] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_spec_read_hk_golden.json"
FIXTURE_RAW = DATA / "soda2_spec_hk_fixture"
S2_RAW = DATA / "s2_spec_raw_fixture"
S2_HK_POINTER = 8262

BUFSIZE = 4114
DATA_WORDS = 2048

#: Channels 1-48 (`x[1:49]`) as 1..48 -- an ordinary ramp so every coefficient
#: band in `c0`/`c1` gets a distinct, checkable value.
XA = list(range(1, 49))
#: Six INT16 extremes cycled across all 48 channels -- channel 24 (0-based
#: index 23 of this list) lands on `-1234`, the one `y` element whose
#: coefficient (`c1[24] = 0.018356`) is inexact in float32 (see M3 below).
XE = [32767, -32768, -1, 0, 1234, -1234] * 8


def hk_record(x1_48: list[int], tas_hi: int, tas_lo: int, t_hi: int,
              t_lo: int) -> list[int]:
    """53 words: marker (`'HK'` = 18507), 48 channels, TAS hi/lo, time hi/lo
    -- exactly what `x = spec_readint(lun, 53, /signed)` (`:14`) expects."""
    assert len(x1_48) == 48
    return [18507, *x1_48, tas_hi, tas_lo, t_hi, t_lo]


#: (name, buffer, data word, record) -- the byte layout, verbatim from the
#: plan this bank executes (section 1.4(b)).
LAYOUT: list[tuple[str, int, int, list[int]]] = [
    ("plain", 0, 0,
     hk_record(XA, 0x4332, 0x4000, 305, 1234)),                    # TAS 178.25, time lo < 0x8000
    ("time_lo_neg", 0, 53,
     hk_record(XA, 0x4332, 0x4000, 305, 40000)),                   # time lo >= 0x8000 (S4-g)
    ("time_hi0_lo_neg", 0, 106,
     hk_record(XA, 0x4332, 0x4000, 0, 32768)),                     # hi=0: the ULONG wrap
    ("tas_lt2", 0, 159,
     hk_record(XA, 0x3FC0, 0x0000, 1, 1)),                         # TAS 1.5 -> exp 128 -> 2^128=0
    ("tas_2p15_wrap", 0, 212,
     hk_record(XA, 0x4740, 0x0000, 1, 1)),                         # TAS 49152 -> 2^15 = -32768
    ("tas_mantissa_all_ones", 0, 265,
     hk_record(XA, 0x407F, 0xFFFF, 2, 2)),                         # x[50] = -1 signed
    ("tas_sign_ignored", 0, 318,
     hk_record(XA, 0xC332, 0x4000, 3, 3)),                         # IEEE -178.25, x[49] negative
    ("tas_zero_words", 0, 371,
     hk_record(XA, 0x0000, 0x0000, 4, 4)),                         # 0.0 decodes as 2.0
    ("y_extremes", 0, 424,
     hk_record(XE, 0x4248, 0x0000, 5, 5)),
    ("straddle", 0, 2000,
     hk_record(XA, 0x4332, 0x4000, 6, 60000)),                     # 48 words in buf 0, 5 in buf 1
    ("on_footer", 1, 1995,
     hk_record(XA, 0x4332, 0x4000, 7, 7)),                         # read ends on buffer 1's footer
]


def build_fixture() -> bytes:
    buffers: list[list[int]] = [[0] * DATA_WORDS for _ in range(3)]
    for name, b, dw, rec in LAYOUT:
        for k, w in enumerate(rec):
            bb, idx = b, dw + k
            while idx >= DATA_WORDS:
                bb += 1
                idx -= DATA_WORDS
            assert buffers[bb][idx] == 0, (name, bb, idx)  # no overlaps
            buffers[bb][idx] = w & 0xFFFF
    out = bytearray()
    for k, data in enumerate(buffers):
        header = [2016, 9, 2, 6, 6, 44, 3 + k, 250]
        for w in header + data + [0]:
            out += int(w & 0xFFFF).to_bytes(2, "little")
    assert len(out) == 3 * BUFSIZE
    return bytes(out)


POINTERS: dict[str, int] = {
    name: b * BUFSIZE + 16 + 2 * dw for name, b, dw, _ in LAYOUT
}


def write_fixture() -> bytes:
    raw = build_fixture()
    if FIXTURE_RAW.is_file():
        existing = FIXTURE_RAW.read_bytes()
        if existing != raw:
            raise SystemExit(
                f"{FIXTURE_RAW} exists and differs from build_fixture()'s output "
                "-- fixture drifted. Stopping rather than overwriting a tracked "
                "fixture; investigate before regenerating.")
        return existing
    FIXTURE_RAW.write_bytes(raw)
    return raw


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------

@dataclass
class Case:
    name: str
    fixture: str  # "hk" or "s2"
    pointer: int
    note: str = ""


CASES: list[Case] = [
    Case("plain", "hk", POINTERS["plain"],
         "ordinary record: TAS 178.25, time lo (1234) < 0x8000."),
    Case("time_lo_neg", "hk", POINTERS["time_lo_neg"],
         "time lo word (40000) >= 0x8000: `:40` reads it signed and adds it "
         "unmasked, so TIME comes out 65536 too small (S4-g)."),
    Case("time_hi0_lo_neg", "hk", POINTERS["time_hi0_lo_neg"],
         "time hi=0, lo=32768 (0x8000, i.e. INT -32768 signed): the ULONG "
         "assembly wraps to ~4.29e9 (S4-g, the zero-high-word case)."),
    Case("tas_lt2", "hk", POINTERS["tas_lt2"],
         "TAS words encode IEEE 1.5 (exponent field -> 128 after `:35`'s "
         "+1): `2^128` as a 16-bit INT wraps to 0, so TAS decodes to 0.0 "
         "(S4-h)."),
    Case("tas_2p15_wrap", "hk", POINTERS["tas_2p15_wrap"],
         "TAS words encode IEEE 49152.0 (exponent -> 15): `2^15` as a "
         "16-bit signed INT is -32768, so TAS decodes negative (S4-h)."),
    Case("tas_mantissa_all_ones", "hk", POINTERS["tas_mantissa_all_ones"],
         "x[50] = -1 (all 16 low mantissa bits set): `:36`'s `and 'ffff'x` "
         "masks a negative signed INT to its unsigned low word, so all 24 "
         "mantissa bits are 1 and TAS decodes to just under 4.0."),
    Case("tas_sign_ignored", "hk", POINTERS["tas_sign_ignored"],
         "x[49] is negative (IEEE -178.25's sign bit set): `:35`'s mask "
         "('3f80'x) and `:36`'s ('7f'x) both exclude bit 15, so the sign is "
         "silently dropped and TAS decodes as the positive value."),
    Case("tas_zero_words", "hk", POINTERS["tas_zero_words"],
         "TAS words both zero (IEEE 0.0): exponent field 0 -> `:35`'s +1 "
         "gives exponent=1, mantissa=1.0, `2^1`=2 -> TAS decodes to 2.0, "
         "not 0.0 (S4-h)."),
    Case("y_extremes", "hk", POINTERS["y_extremes"],
         "all 48 channels are INT16 extremes (XE): exercises every `c0`/"
         "`c1` coefficient band against the largest and smallest inputs, "
         "including channel 24's inexact 0.018356 coefficient against "
         "-1234 (M3's discriminating case)."),
    Case("straddle", "hk", POINTERS["straddle"],
         "the 53-word read starts inside buffer 0's last data words: 48 "
         "words before the boundary, 5 after -- `spec_readint`'s 1-crossing "
         "splice must fire with `signed=True`."),
    Case("on_footer", "hk", POINTERS["on_footer"],
         "the read ends exactly on buffer 1's footer -- `spec_readint`'s "
         "own post-read jump (`:46-47`) must fire so AFTER lands inside "
         "buffer 2's live data."),
    Case("s2_real", "s2", S2_HK_POINTER,
         "the pre-existing tracked SPEC fixture's own HK record (marker at "
         "byte 8262, scanned for the value 18507): TAS words 0x4248,0x0000 "
         "= 50.0; time words 1,34464 -- 34464 >= 0x8000, so this "
         "real-layout record is S4-g's evidence."),
]


_CASE_SCRIPT = """
hk = spec_read_hk(lun, {pointer}ULL)
point_lun, -lun, after
print, 'CASE={name} AFTER=', after, ' TIME=', hk.time, format='(A,I0,A,I0)'
print, 'TAS=', ulong(hk.tas,0), format='(A,Z08)'
print, 'TASDEC=', hk.tas, format='(A,E17.9)'
print, 'Y=' + strjoin(string(ulong(hk.x,0,49), format='(Z08)'), ','), format='(A)'
print, 'RAW=' + strjoin(strtrim(string(hk.raw),2), ','), format='(A)'
print, 'TN=' + size(hk.time,/tname) + ',' + size(hk.tas,/tname) + ',' + $
   size(hk.x,/tname) + ',' + size(hk.raw,/tname) + ',' + $
   strtrim(string(n_elements(hk.x)),2) + ',' + $
   strtrim(string(n_elements(hk.raw)),2), format='(A)'
"""


def _script_for_all(hk_path: str, s2_path: str) -> str:
    lines = [f"openr, lun, '{hk_path}', /get_lun"]
    for case in CASES:
        if case.fixture != "hk":
            continue
        lines.append(_CASE_SCRIPT.format(pointer=case.pointer, name=case.name))
    lines.append("free_lun, lun")
    lines.append(f"openr, lun, '{s2_path}', /get_lun")
    for case in CASES:
        if case.fixture != "s2":
            continue
        lines.append(_CASE_SCRIPT.format(pointer=case.pointer, name=case.name))
    lines.append("free_lun, lun")
    return "\n".join(lines)


def _parse(stdout: str) -> dict[str, dict]:
    records: dict[str, dict] = {}
    current: dict | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("CASE="):
            # 'CASE=name AFTER=.. TIME=..'
            rest = line[len("CASE="):]
            name, _, tail = rest.partition(" AFTER=")
            current = {"name": name}
            after_str, _, time_str = tail.partition(" TIME=")
            current["AFTER"] = int(after_str)
            current["TIME"] = int(time_str)
            records[name] = current
        elif line.startswith("TAS=") and current is not None:
            current["TAS"] = line[len("TAS="):].strip()
        elif line.startswith("TASDEC=") and current is not None:
            current["TASDEC"] = line[len("TASDEC="):].strip()
        elif line.startswith("Y=") and current is not None:
            text = line[len("Y="):].strip()
            current["Y"] = text.split(",")
        elif line.startswith("RAW=") and current is not None:
            text = line[len("RAW="):].strip()
            current["RAW"] = [int(v) for v in text.split(",")]
        elif line.startswith("TN=") and current is not None:
            current["TN"] = line[len("TN="):].strip()
    return records


# --------------------------------------------------------------------------
# Version 2 -- `spec_read_hk.pro:43-65`, `spec_index_hk.pro`
# (whole file) and `spec_process_hk.pro:14-25,104-167` -- written to its own
# golden, `gdl_soda2_spec_read_hk_v2_golden.json`, so the twelve v1 records
# above stay byte-identical.
#
# The layout is derived from source alone: `spec_index_hk.pro:11` declares
# the 2DSCPIHK buffer header as eight INTs (year, month, dummy, day, hour,
# minute, second, millisecond) and a UINT `buffertype`, 18 bytes; `:43-47`
# record an HK buffer (`buffertype eq 18507`) at `ip*2 + headersize - 2`,
# i.e. AT its `buffertype` word -- so `spec_read_hk`'s 83-word read starts
# with that word as `x[0]`, exactly as v1's does with the 'HK' marker. The
# file has no 4114-byte framing (`:67` returns `buffsize = 0`, which
# `spec_readint.pro:11-16` takes as "read straight through"). Which of the
# 83 words mean what is `spec_read_hk.pro:48-64`'s and
# `spec_process_hk.pro:117-166`'s own indexing; nothing else is assumed.
# --------------------------------------------------------------------------

V2_FIXTURE = DATA / "soda2_spec_v2_2DSCPIHK"
V2_NOHK_FIXTURE = DATA / "soda2_spec_v2_nohk_2DSCPIHK"
V2_GOLDEN = DATA / "gdl_soda2_spec_read_hk_v2_golden.json"

#: `x[2:28]`, the 27 thermistor words (`:49-50`): zero, negative, and values
#: either side of 6553/6554, where `5*x` (INT times INT) first overflows 16
#: bits, plus 13108 (`5*x` wraps back to +4) and 20000/30000 (wrap negative
#: and positive).
V2_THERM = [0, -1, 1000, 6553, 6554, 10000, 13108, 20000, 30000, 32767,
            -32768, 12345, 25000, 16000, 8000, 4000, 2000, 100, 1, 31000,
            22222, 11111, 5555, 7777, 9999, 15000, 18000]
#: `x[34:53]`, the 20 volt words (`:56`).
V2_VOLTS = [-32768, -1, 0, 1, 100, 1000, 4096, 8191, 16384, 32767, 2048,
            3000, 12000, -500, 777, 65, 9, 4000, 20000, 1234]


def v2_record(k: int, t3: tuple[int, int, int], tas2: tuple[int, int]) -> list[int]:
    """83 words from `buffertype` on. `k` offsets the thermistor/volt words
    so records summed into one `hkraw` row stay distinguishable."""
    x = [0] * 83
    x[0] = 18507
    x[1] = 7
    x[2:29] = [(v + 3 * k) for v in V2_THERM]
    x[29] = 10000 + k
    x[30:34] = [30, 31, 32, 33]
    x[34:54] = [(v + k) for v in V2_VOLTS]
    x[54:72] = list(range(54, 72))
    x[72:75] = list(t3)
    x[75:77] = list(tas2)
    x[77:83] = list(range(77, 83))
    return x


def _v2_header(h: int, m: int, s: int, ms: int, buffertype: int) -> list[int]:
    return [2016, 9, 0, 14, h, m, s, ms, buffertype]


#: (name, header words incl. buffertype, payload after buffertype).
V2_LAYOUT: list[tuple[str, list[int], list[int]]] = [
    ("r0", _v2_header(7, 0, 0, 0, 18507)[:8],
     v2_record(0, (0, 5, 1234), (0x4332, 0x4000))),          # TAS 178.25
    ("r1", _v2_header(7, 0, 0, 500, 18507)[:8],
     v2_record(1, (1, 0, 40000), (0x4348, 0x0000))),         # same second as r0; x[72]=1
    ("mask", _v2_header(7, 0, 1, 0, 19787), [11] * 10),      # 'MK' buffer
    ("r2", _v2_header(7, 0, 2, 250, 18507)[:8],
     v2_record(2, (0, 0, 32768), (0x3FC0, 0x0000))),         # TAS 1.5 decodes 0.0 (S4-h)
    ("r3", _v2_header(7, 0, 3, 0, 18507)[:8],
     v2_record(3, (2, 3, 4), (0x4316, 0x0000))),             # TAS 150.0
]


def build_v2_fixture() -> tuple[bytes, dict[str, int]]:
    """The 2DSCPIHK bytes and each HK record's `hkp` (its buffertype word)."""
    out = bytearray()
    hkp: dict[str, int] = {}
    for name, header, payload in V2_LAYOUT:
        words = header + payload
        if name != "mask":
            hkp[name] = len(out) + 16
        for w in words:
            out += int(w & 0xFFFF).to_bytes(2, "little")
    for w in [0] * 8:  # trailing pad so the last record's scan window fits
        out += int(w).to_bytes(2, "little")
    return bytes(out), hkp


def build_v2_nohk_fixture() -> bytes:
    """A 2DSCPIHK file holding only a mask buffer: `spec_index_hk.pro:59`
    then returns `hkp=[0]` (`(hkc-1)>0`), a phantom HK record at byte 0."""
    words = _v2_header(7, 0, 0, 0, 19787) + [11] * 100
    return b"".join(int(w & 0xFFFF).to_bytes(2, "little") for w in words)


def _write_tracked(path: Path, raw: bytes) -> None:
    if path.is_file() and path.read_bytes() != raw:
        raise SystemExit(f"{path} exists and differs -- fixture drifted")
    if not path.is_file():
        path.write_bytes(raw)


_V2_OP = ("{{fn:'{fn}', date:'20160914', starttime:25200d, stoptime:25204d, "
          "format:'SPEC', subformat:1, probetype:'{ptype}', res:10.0, "
          "endbins:[0,1000], arendbins:[0,1], rate:1.0, smethod:'xy', pth:'', "
          "particlefile:0, inttime_reject:0, reconstruct:1, stuckbits:0, "
          "water:0, fixedtas:0.0, outdir:'', project:'x', timeoffset:0.0, "
          "armwidth:6.3, numdiodes:128, greythresh:0, probeid:'{pid}'}}")

_V2_PRINT_HK = """
print, 'CASE={name}', format='(A)'
print, 'NB=' + strjoin(strtrim(string(d.nb),2), ','), format='(A)'
print, 'TAS=' + strjoin(string(ulong(d.tas,0,n_elements(d.tas)), format='(Z08)'), ','), format='(A)'
print, 'VOLTS=' + strjoin(string(ulong(d.volts,0,n_elements(d.volts)), format='(Z08)'), ','), format='(A)'
print, 'OVERLOADS=' + strjoin(string(ulong(d.overloads,0,n_elements(d.overloads)), format='(Z08)'), ','), format='(A)'
print, 'LASERVOLTS=' + strjoin(string(ulong(d.laservolts,0,n_elements(d.laservolts)), format='(Z08)'), ','), format='(A)'
print, 'COUNTS=' + strjoin(string(ulong(d.counts,0,n_elements(d.counts)), format='(Z08)'), ','), format='(A)'
print, 'CANPRESSURE=' + strjoin(string(ulong(d.canpressure,0,n_elements(d.canpressure)), format='(Z08)'), ','), format='(A)'
print, 'POWER=' + strjoin(string(ulong(d.power,0,n_elements(d.power)), format='(Z08)'), ','), format='(A)'
print, 'TEMP=' + strjoin(string(ulong64(d.temp,0,n_elements(d.temp)), format='(Z016)'), ','), format='(A)'
print, 'TEMPDIMS=' + strjoin(strtrim(string(size(d.temp,/dim)),2), ','), format='(A)'
print, 'VOLTSDIMS=' + strjoin(strtrim(string(size(d.volts,/dim)),2), ','), format='(A)'
print, 'TEMPID=' + strjoin(d.tempid, '|'), format='(A)'
print, 'TN=' + size(d.tas,/tname) + ',' + size(d.volts,/tname) + ',' + size(d.temp,/tname) + ',' + size(d.canpressure,/tname) + ',' + size(d.power,/tname), format='(A)'
"""  # noqa: E501 - IDL print lines, kept one statement per line

_V2_READ = """
h = spec_read_hk(lun, {hkp}ULL, 0, version=2)
print, 'CASE={name}', format='(A)'
print, 'TIME=', h.time, format='(A,I0)'
print, 'TAS=', ulong(h.tas,0), format='(A,Z08)'
print, 'Y=' + strjoin(string(ulong(h.x,0,83), format='(Z08)'), ','), format='(A)'
print, 'RAW=' + strjoin(strtrim(string(h.raw),2), ','), format='(A)'
print, 'TN=' + size(h.time,/tname) + ',' + size(h.tas,/tname) + ',' + size(h.x,/tname) + ',' + size(h.raw,/tname), format='(A)'
"""  # noqa: E501 - IDL print lines, kept one statement per line


def _v2_scripts(fixture: Path, nohk: Path, hkp: dict[str, int]) -> list[tuple[str, str]]:
    """(label, script) pairs, one GDL process each, so a halting case cannot
    take the others down."""
    fx = fixture.resolve().as_posix()
    base = fx[:-2]  # op.fn; `spec_process_hk.pro:16` appends 'HK'
    reads = [f"openr, lun, '{fx}', /get_lun"]
    for name in ("r0", "r1", "r2", "r3"):
        reads.append(_V2_READ.format(hkp=hkp[name], name=f"read_{name}"))
    reads.append("free_lun, lun")
    reads.append(f"""
ix = spec_index_hk('{fx}')
print, 'CASE=index', format='(A)'
print, 'DATE=' + strjoin(strtrim(string(ix.date),2), ','), format='(A)'
print, 'BUFFTIME=' + strjoin(string(ulong64(ix.bufftime,0,n_elements(ix.bufftime)), format='(Z016)'), ','), format='(A)'
print, 'POINTER=' + strjoin(strtrim(string(ix.pointer),2), ','), format='(A)'
print, 'HKP=' + strjoin(strtrim(string(ix.hkp),2), ','), format='(A)'
print, 'MASKP=' + strjoin(strtrim(string(ix.maskp),2), ','), format='(A)'
print, 'BUFFSIZE=', ix.buffsize, format='(A,I0)'
print, 'TN=' + size(ix.date,/tname) + ',' + size(ix.bufftime,/tname) + ',' + size(ix.pointer,/tname) + ',' + size(ix.hkp,/tname) + ',' + size(ix.maskp,/tname), format='(A)'
""")  # noqa: E501 - IDL print lines, kept one statement per line
    out = [("reads", "\n".join(reads))]
    for pid, ptype in (("H", "3VCPI"), ("V", "3VCPI"), ("V50", "3VCPI"),
                       ("V150", "3VCPI"), ("H50", "3VCPI"), ("H150", "3VCPI"),
                       ("H", "HVPS4")):
        name = f"phk_{pid}_{ptype}"
        op = _V2_OP.format(fn=base, ptype=ptype, pid=pid)
        out.append((name, f"op={op}\nspec_process_hk, op, /nosav, data=d\n"
                    + _V2_PRINT_HK.format(name=name)))
    op = _V2_OP.format(fn=base, ptype="3VCPI", pid="A0")
    out.append(("phk_A0_3VCPI", f"op={op}\nprint, 'CASE=phk_A0_3VCPI', format='(A)'\n"
                "spec_process_hk, op, /nosav, data=d\nprint, 'RETURNED=1', format='(A)'\n"))
    nb = nohk.resolve().as_posix()[:-2]
    op = _V2_OP.format(fn=nb, ptype="3VCPI", pid="H")
    out.append(("phk_nohk", f"op={op}\nspec_process_hk, op, /nosav, data=d\n"
                + _V2_PRINT_HK.format(name="phk_nohk")))
    op = _V2_OP.format(fn=base + "_missing", ptype="3VCPI", pid="H")
    out.append(("phk_missing", f"op={op}\nprint, 'CASE=phk_missing', format='(A)'\n"
                "spec_process_hk, op, /nosav, data=d\nprint, 'RETURNED=1', format='(A)'\n"))
    return out


def _parse_generic(stdout: str) -> dict[str, dict]:
    records: dict[str, dict] = {}
    current: dict | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("CASE="):
            current = {"name": line[len("CASE="):]}
            records[current["name"]] = current
        elif current is not None and "=" in line and line.split("=", 1)[0].isupper():
            key, val = line.split("=", 1)
            current[key] = val
    return records


def main_v2() -> int:
    raw, hkp = build_v2_fixture()
    _write_tracked(V2_FIXTURE, raw)
    _write_tracked(V2_NOHK_FIXTURE, build_v2_nohk_fixture())
    interpol = (Path(os.environ.get("USERPROFILE", "")) / "tools" / "gdl" / "share"
                / "gnudatalanguage" / "lib" / "utilities" / "interpol.pro")
    extra = {"interpol.pro": interpol.read_text(encoding="utf-8")}
    records: list[dict] = []
    for label, script in _v2_scripts(V2_FIXTURE, V2_NOHK_FIXTURE, hkp):
        try:
            stdout, stderr = run_pro(script, timeout=60, extra_files=extra)
        except GDLUnavailable as exc:
            print(f"GDL unavailable: {exc}")
            return 2
        except subprocess.TimeoutExpired as exc:  # an IDL `stop` waiting on stdin
            stdout = exc.output if isinstance(exc.output, str) else ""
            stderr = "TIMEOUT " + (exc.stderr if isinstance(exc.stderr, str) else "")
        parsed = _parse_generic(stdout)
        if not parsed:
            parsed = {label: {"name": label}}
        for name, rec in parsed.items():
            complete = "TN" in rec
            rec["status"] = "OK" if complete else "HALTED"
            if not complete:
                rec["stderr"] = stderr[-600:]
            records.append(rec)
            print(f"{name}: {rec['status']} {rec.get('stderr', '')[-200:]}")
    V2_GOLDEN.write_text(json.dumps({"hkp": hkp, "records": records}, indent=2) + "\n",
                         encoding="utf-8")
    ok = sum(r["status"] == "OK" for r in records)
    print(f"\nwrote {V2_GOLDEN} -- {len(records)} records, {ok} OK")
    scrub_output(V2_GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    return 0


def main() -> int:
    if "--v2" in sys.argv:
        return main_v2()
    raw = write_fixture()
    assert len(raw) == 3 * BUFSIZE
    if not S2_RAW.is_file():
        print(f"{S2_RAW} is missing -- the s2_real case needs it")
        return 2

    hk_path = FIXTURE_RAW.resolve().as_posix()
    s2_path = S2_RAW.resolve().as_posix()
    script = _script_for_all(hk_path, s2_path)

    records: list[dict] = []
    try:
        stdout, stderr = run_pro(script, timeout=180)
        parsed = _parse(stdout)

        required = ("AFTER", "TIME", "TAS", "TASDEC", "Y", "RAW", "TN")
        for case in CASES:
            vals = parsed.get(case.name)
            rec: dict = {
                "name": case.name,
                "fixture": case.fixture,
                "pointer": case.pointer,
                "note": case.note,
            }
            if vals is None or not all(k in vals for k in required):
                rec.update(status="ERROR",
                           stdout=stdout[-1200:], stderr=stderr[-600:])
                print(f"{case.name}: ERROR")
            else:
                rec.update(status="OK", **{k: vals[k] for k in required})
                print(f"{case.name}: AFTER={vals['AFTER']} TIME={vals['TIME']} "
                      f"TAS={vals['TAS']} TASDEC={vals['TASDEC']}")
            records.append(rec)
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2

    ok = sum(1 for r in records if r["status"] == "OK")
    if ok == 0:
        print("refusing to write a golden in which every case errored")
        return 1
    GOLDEN.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {GOLDEN} -- {len(records)} cases, {ok} OK")
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
