# SPDX-License-Identifier: BSD-3-Clause
r"""SPEC buffer decode: `spec_index.pro` (161 lines) and
`spec_absolutepointers.pro` (22 lines) under GDL, unmodified -- the SPEC
buffer walk that produces every pointer `spec_read_hk`/`spec_read_frame`
consume, and the one routine that turns a buffer index into absolute file
offsets.

`spec_index(lun, lite=, minimagesize=, pointerstart=, pointerstop=,
absolutepointer=, version=)` walks the file two buffers at a time (`b =
[thisbuffer, nextbuffer]`), decoding `'2S'` frame markers into image
pointers, `'HK'`/`'MK'` markers into housekeeping/mask pointers, and
carrying a within-buffer cursor `j` across the boundary. Its own buffer size
is **autodetected** from the position of the first repeat of the file's
first three 16-bit words (year, month, weekday) -- a data triple that
happens to equal the header's own gives a wrong `buffsize` and a
`FOR i=0L,numbuffs-2` loop that never walks the file's *last* buffer at all
(S4-i). `spec_absolutepointers(buffnum, p)` turns `numimages`/`firstp`/
`imagep`/`pointer` from that index into one flat array of absolute image
offsets, in `buffnum`'s own order.

**No shim needed.** Every case below ran clean under GDL 1.1.2 in the
planning session and again in this one -- `spec_index`/`spec_absolutepointers`
touch no MEX call and no netCDF I/O, only `readu`/`point_lun`/`fstat`.

**Two fixtures are new and tracked**: `tests/data/soda2_spec_index_fixture`
(6 x 4114-byte buffers + 100 trailing bytes = 24784 B) packs 22 hand-placed
items across every branch of the walk -- the `:71` carry across a buffer
boundary with two decoy markers planted to prove the carry is honoured, a
frame whose declared length lands past `ndataints` so `:139-140`'s "j gets
way too big" reset fires, a `'2S'` marker sitting on the very last data word
of a buffer so its own header+payload land entirely in the next one, a dual
H+V frame, two frames repeating the same particle counter (skipped), an
`'NL'` tag that ends a buffer's walk early, an unknown tag word, and a
particle in the file's sixth and final buffer -- which `:71`'s
`FOR i=0L,numbuffs-2` never walks (S4-i). `LAYOUT`, the byte-placement
table, is public (`bank.LAYOUT`) because the test derives an independent
third side from it. `tests/data/soda2_spec_index_triple_fixture` (3 x 4114 B
= 12342 B) plants the header's own `[year, month, dummy]` triple a second
time at data words 100-102 of buffer 0, so the autodetection at `:26-30`
locks onto it instead of the real buffer boundary (S4-k). Two more fixtures
are built in a temp directory and never tracked: `short` (one buffer --
`:30`'s `w=[0]` has no second element and IDL dies) and `badyear` (three
buffers, year 2051 throughout -- `:72`'s `stop, 'File misaligned'` fires on
the very first header).

**Halt handling differs from the `soda2_samplearea` bank.** There, `ELSE:
stop` blocked GDL for the full timeout. Here, under `run_pro` on this
machine, IDL's `stop` printed `File misaligned` and returned control (stdin
at EOF) within seconds rather than blocking -- both are treated as
`status="HALTED"`: a `subprocess.TimeoutExpired`, or stdout containing
`File misaligned` with no `CASE=` line for that case. `short`'s `%
SPEC_INDEX: Scalar subscript out of range` is `status="ERROR"` on the same
"no `CASE=` line" test. `triple_full`, `short` and `badyear` each get their
own `run_pro` call -- an uncaught GDL error or `stop` aborts the rest of a
compiled procedure, so any case placed after one of these in the same script
would silently never run.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_spec_index_bank.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, run_pro  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

DATA = Path(__file__).resolve().parents[3] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_spec_index_golden.json"
FIXTURE_MAIN = DATA / "soda2_spec_index_fixture"
FIXTURE_TRIPLE = DATA / "soda2_spec_index_triple_fixture"
S2_RAW = DATA / "s2_spec_raw_fixture"
FRAME_RAW = DATA / "soda2_spec_frame_fixture"
HK_RAW = DATA / "soda2_spec_hk_fixture"

BUFSIZE, DATA_WORDS = 4114, 2048


def frame(nh: int, nv: int, pc: int, ns: int = 1,
          payload: list[int] | None = None) -> list[int]:
    """[marker, nh, nv, particlecounter, numslices] + payload words --
    exactly what the `'2S'` branch (`:85-116`) expects at `b[j:j+5]`."""
    w = [12883, nh, nv, pc, ns]
    return w + ([0] * (nh + nv) if payload is None else payload)


def _place(buffers: list[list[int]], b: int, w: int, words: list[int]) -> None:
    """Word-granular placement that spills into the next buffer with no
    overlaps -- the single source of truth for every byte in `build_main()`."""
    for k, v in enumerate(words):
        bb, idx = b, w + k
        while idx >= DATA_WORDS:
            bb += 1
            idx -= DATA_WORDS
        assert buffers[bb][idx] == 0, (b, w, k)
        buffers[bb][idx] = v & 0xFFFF


def _pack(buffers: list[list[int]], headers: list[list[int]],
          trailing: int = 0) -> bytes:
    out = bytearray()
    for hdr, data in zip(headers, buffers, strict=True):
        for w in hdr + data + [0]:
            out += int(w & 0xFFFF).to_bytes(2, "little")
    return bytes(out) + bytes(trailing)


#: (buffer, data word, words, tag, indexed-under-default-minimagesize?) --
#: the byte layout AND the third side (`test_the_layout_table_predicts_the_golden`
#: imports this). Verbatim from the plan this bank executes
#: (section 1.4), itself byte-diffed against the planning session's GDL run.
LAYOUT: list[tuple[int, int, list[int], str, bool]] = [
    (0, 0,    [12883, 2100, 0, 1, 1],       "long_frame_pc1",     True),   # nh=2100 declared -> j=2105 -> carry 57 into buffer 1
    (0, 1000, frame(4, 0, 99),              "decoy_in_payload",   False),  # inside the long frame's declared payload
    (1, 10,   frame(4, 0, 98),              "decoy_before_carry", False),  # before word 57: skipped iff the carry is honoured
    (1, 60,   frame(4, 0, 2),               "h_pc2",              True),
    (1, 69,   frame(4, 5, 3),               "dual_pc3",           True),   # indexed once, as 'V'
    (1, 83,   frame(4, 0, 3),               "h_repeat_pc3",       False),  # same H counter -> deltacounter 0
    (1, 92,   frame(0, 5, 3),               "v_repeat_pc3",       False),  # same V counter
    (1, 102,  frame(1, 0, 4),               "nh1_too_small",      False),  # nh=1 < minimagesize=2; j still += 6
    (1, 108,  frame(0, 2, 4),               "v_nv2_pc4",          True),   # nv=2 >= 2 -> 'V'
    (1, 115,  [48813],                      "bead_word",          False),
    (1, 116,  [19787] + [0] * 22,           "mk",                 False),  # maskp 4362
    (1, 139,  [18507] + [0] * 52,           "hk1",                False),  # hkp 4408
    (1, 192,  frame(4, 0, 5),               "h_pc5_ihk0",         True),
    (1, 201,  [18507] + [0] * 52,           "hk2",                False),  # hkp 4532
    (1, 254,  frame(4, 0, 6),               "h_pc6_ihk1",         True),
    (1, 2000, [12883, 4095, 0, 7, 1],       "nh4095_pc7",         True),   # j=6100 -> 4052 >= 2048 -> :140 resets j=0
    (2, 10,   frame(4, 0, 8),               "h_pc8_after_reset",  True),
    (2, 2047, [12883, 4, 0, 9, 1, 12883, 4, 0, 97], "marker_at_last_word_pc9", True),  # nh/nv/pc/ns + decoy payload land in buffer 3 words 0-7
    (3, 8,    frame(4, 0, 10),              "h_pc10_at_carry8",   True),
    (3, 20,   frame(4, 0, 11),              "h_pc11",             True),
    (3, 30,   [20044],                      "nl",                 False),  # rest of buffer 3 skipped
    (3, 40,   frame(4, 0, 12),              "h_pc12_after_nl",    False),
    (4, 0,    frame(6, 6, 13),              "dual_pc13",          True),   # 'V'
    (4, 17,   frame(4, 0, 14),              "h_pc14",             True),
    (4, 30,   [4660],                       "unknown_tag",        False),
    (4, 31,   frame(3, 3, 15),              "dual_nh3_nv3_pc15",  True),   # both >= 2 -> 'V'; dropped at minimagesize=4
    (4, 42,   frame(4, 0, 16),              "h_pc16",             True),
    (5, 0,    frame(4, 0, 17),              "last_buffer_pc17",   False),  # buffer 5 is never walked (:71)
]
HEADERS_MAIN = [[2016, 9, 2, 6, 6, 44, 3 + k, 250] for k in range(5)] + [[1999, 9, 2, 7, 0, 0, 0, 100]]


def build_main() -> bytes:
    buffers = [[0] * DATA_WORDS for _ in range(6)]
    for b, w, words, _tag, _idx in LAYOUT:
        _place(buffers, b, w, words)
    return _pack(buffers, HEADERS_MAIN, trailing=100)  # 24784 B


def build_triple() -> bytes:
    """Data words 100-102 of buffer 0 = the header's own [year, month,
    dummy] triple, so `:26-30`'s autodetect locks onto them instead of the
    real 2057-word buffer boundary (S4-k)."""
    buffers = [[0] * DATA_WORDS for _ in range(3)]
    buffers[0][100:103] = [2016, 9, 2]
    return _pack(buffers, [[2016, 9, 2, 6, 6, 44, 3 + k, 250] for k in range(3)])


def build_short() -> bytes:
    """One buffer: the autodetect `where(...)` finds only the header's own
    first word (`w=[0]`), and `:30`'s `w[1]` is a scalar subscript out of
    range."""
    return _pack([[0] * DATA_WORDS], [[2016, 9, 2, 6, 6, 44, 3, 250]])


def build_badyear() -> bytes:
    """Three buffers, year 2051 throughout: `:72`'s range check fires on
    the very first header."""
    return _pack([[0] * DATA_WORDS for _ in range(3)],
                 [[2051, 9, 2, 6, 6, 44, 3 + k, 250] for k in range(3)])


def build_tiled3() -> bytes:
    """The `index_tiled3` fixture:
    the main fixture's five well-formed buffers three times, then
    its bad-year sixth -- `good*3 + last`, 65 824 B, byte-for-byte the bytes
    `tests/test_soda2_pointer_width.py::_tiled_fixture_bytes` builds. Built
    from the tracked main fixture at run time, **never tracked itself**.
    Tiling only the good buffers keeps the 1999 header off a tile boundary
    (tiling all six raises `SpecFileMisaligned`, measured in W2b)."""
    raw = FIXTURE_MAIN.read_bytes()
    assert len(raw) == 24784, "soda2_spec_index_fixture changed size"
    tiled = raw[: 5 * BUFSIZE] * 3 + raw[5 * BUFSIZE: 6 * BUFSIZE]
    assert len(tiled) == 65824, len(tiled)
    return tiled


#: `soda2_process_2d.pro:460` verbatim on the index just built, for every
#: image-bearing buffer: `LONG i * ULONG64 buffsize + INT imagep[...]`. The
#: loop variable is LONG because the driver's `FOR i=firstbuff,lastbuff`
#: takes `firstbuff`'s type (`max(where(...)) > 0`, LONG). This is the
#: expression whose int16 port wrapped silently at i = 7 and overflowed at
#: i >= 8 (W2b); GDL's own value and type are the second side the pointer-
#: width test's plain-int arithmetic never had.
_P460_SCRIPT = """
s460 = ''
tn460 = ''
FOR i=0L, idx.count-1 DO BEGIN
  IF idx.numimages[i] gt 0 THEN BEGIN
    v = i*idx.buffsize + idx.imagep[(idx.firstp[i]):(idx.firstp[i]+idx.numimages[i]-1)]
    IF strlen(s460) gt 0 THEN s460 = s460 + '|'
    s460 = s460 + strtrim(string(i),2) + ':' + strjoin(strtrim(string(v),2), ';')
    tn460 = size(v,/tname)
  ENDIF
ENDFOR
print, 'CASE={name} P460=' + s460 + ' P460TN=' + tn460, format='(A)'
"""


def write_fixture(path: Path, raw: bytes) -> bytes:
    """Write-if-absent, stop on drift -- never silently overwrite a tracked
    fixture (the same convention as `run_soda2_spec_read_hk_bank.write_fixture`)."""
    if path.is_file():
        existing = path.read_bytes()
        if existing != raw:
            raise SystemExit(
                f"{path} exists and differs from the generator's output -- "
                "fixture drifted. Stopping rather than overwriting a tracked "
                "fixture; investigate before regenerating.")
        return existing
    path.write_bytes(raw)
    return raw


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------

@dataclass
class Case:
    name: str
    fixture: str  # "idx" | "triple" | "s2" | "frame" | "hk"
    kind: str     # "index" | "lite" | "autodetect" | "abspointers"
    call: str = ""           # IDL text building the index (or, for
                              # abspointers, the index the pointer wraps)
    buffnum: str = ""        # abspointers only -- IDL literal, e.g. "[4,1]"
    note: str = ""


CASES: list[Case] = [
    # --- the new main fixture: every branch of the walk -------------------
    Case("main_rel", "idx", "index", "spec_index(lun)",
         note="the default call every vendored caller uses "
              "(soda2_buildindex.pro:12, soda2_browse.pro:141, "
              "soda2_imagedump.pro:49) -- relative imagep, minimagesize=2."),
    Case("main_abs", "idx", "index", "spec_index(lun, /absolutepointer)",
         note="same walk, absolute imagep (LONG64)."),
    Case("main_min3", "idx", "index", "spec_index(lun, minimagesize=3)",
         note="drops v_nv2_pc4 (nv=2 < 3); dual_nh3_nv3_pc15 (nh=nv=3) survives."),
    Case("main_min4", "idx", "index", "spec_index(lun, minimagesize=4)",
         note="also drops dual_nh3_nv3_pc15 (nh=nv=3 < 4)."),
    Case("main_v2", "idx", "index", "spec_index(lun, version=2)",
         note="hklength=83 instead of 53: hk1 (word 139) + 83 = word 222, "
              "past hk2's own marker at word 201 -- pc 5's ihk misreads and "
              "hk2 is swallowed as HK data, so only one HKP survives."),

    # --- the triple fixture: autodetection on a data triple ---------------
    Case("triple_autodetect", "triple", "autodetect",
         note="`:26-30` verbatim: the where() locks onto data words "
              "100-102 (S4-k), buffsize=216 instead of 4114."),
    # triple_full (HALTED), short (ERROR) and badyear (HALTED) run in their
    # own run_pro calls below -- see _run_halting_case.

    # --- the pre-existing s2 fixture ---------------------------------------
    Case("s2_rel", "s2", "index", "spec_index(lun)"),
    Case("s2_abs", "s2", "index", "spec_index(lun, /absolutepointer)"),
    Case("s2_lite", "s2", "lite", "spec_index(lun, /lite)"),
    Case("s2_min5", "s2", "index", "spec_index(lun, minimagesize=5)"),
    Case("s2_pstart", "s2", "index", "spec_index(lun, pointerstart=4114ULL)",
         note="S4-j: :78 seeks (i+1)*buffsize from the file start regardless "
              "of pointerstart, so buffer 1 is read twice."),
    Case("s2_pstop", "s2", "index", "spec_index(lun, pointerstop=3*4114ULL)",
         note="the walk covers buffers 0-1 only; no HK/MK record in range "
              "leaves hkp=[0], maskp=[0] (S4-l's sharper half)."),

    # --- the pre-existing frame fixture -------------------------------------
    Case("frame_rel", "frame", "index", "spec_index(lun)"),
    Case("frame_abs", "frame", "index", "spec_index(lun, /absolutepointer)"),
    Case("frame_min3", "frame", "index", "spec_index(lun, minimagesize=3)"),

    # --- the pre-existing hk fixture -----------------------------------------
    Case("hk_rel", "hk", "index", "spec_index(lun)",
         note="no '2S' marker anywhere -- the [0] sentinel for imagep/"
              "ibuffer/ihk/particlecounter/arrayid."),
    Case("hk_v2", "hk", "index", "spec_index(lun, version=2)",
         note="every second HK record is skipped by the 83-word step."),

    # --- spec_absolutepointers, on the main index (built without
    #     /absolutepointer unless the case says otherwise) -------------------
    Case("ap_main_1", "idx", "abspointers", "spec_index(lun)", "1"),
    Case("ap_main_41", "idx", "abspointers", "spec_index(lun)", "[4,1]",
         note="buffnum order, not sorted -- T8's discriminator against A1."),
    Case("ap_main_5_empty", "idx", "abspointers", "spec_index(lun)", "5",
         note="numimages[5]=0 (the never-walked last buffer) -> {ap:0, n:0}."),
    Case("ap_main_50", "idx", "abspointers", "spec_index(lun)", "[5,0]",
         note="buffer 5 contributes nothing; buffer 0 contributes 1."),
    Case("ap_main_all", "idx", "abspointers", "spec_index(lun)", "indgen(6)"),
    Case("ap_main_1_absindex", "idx", "abspointers",
         "spec_index(lun, /absolutepointer)", "1",
         note="feeding an absolute index double-counts pointer[1] -- latent, "
              "no caller does this (spec_absolutepointers.pro:85-86)."),
    Case("ap_s2_0", "s2", "abspointers", "spec_index(lun)", "0"),
    Case("ap_s2_10", "s2", "abspointers", "spec_index(lun)", "[1,0]"),
    Case("ap_s2_3_empty", "s2", "abspointers", "spec_index(lun)", "3"),

    # --- The 16-buffer tiled main fixture ------
    Case("index_tiled3", "tiled3", "index_p460", "spec_index(lun)",
         note="good*3 + last (65 824 B, built at run time from the tracked "
              "main fixture, never tracked): the index, plus "
              "soda2_process_2d.pro:460's pointer expression per "
              "image-bearing buffer -- i=7 is the int16 silent-wrap regime "
              "and i>=8 the OverflowError regime of the pre-W2b port."),
]

HALTING_CASES = ["triple_full", "short", "badyear"]


# --------------------------------------------------------------------------
# Script generation
# --------------------------------------------------------------------------

_INDEX_SCRIPT = """
idx = {call}
print, 'CASE={name} COUNT=', idx.count, ' BUFFSIZE=', idx.buffsize, ' NIMG=', n_elements(idx.imagep), ' NHK=', n_elements(idx.hkp), ' NMK=', n_elements(idx.maskp), ' ERR=', idx.error, format='(A,I0,A,I0,A,I0,A,I0,A,I0,A,I0)'
print, 'IMAGEP=' + strjoin(strtrim(string(idx.imagep),2), ','), format='(A)'
print, 'IBUFFER=' + strjoin(strtrim(string(idx.ibuffer),2), ','), format='(A)'
print, 'IHK=' + strjoin(strtrim(string(idx.ihk),2), ','), format='(A)'
print, 'PC=' + strjoin(strtrim(string(idx.particlecounter),2), ','), format='(A)'
print, 'ARRAYID=' + strjoin(strtrim(string(fix(idx.arrayid)),2), ','), format='(A)'
print, 'HKP=' + strjoin(strtrim(string(idx.hkp),2), ','), format='(A)'
print, 'MASKP=' + strjoin(strtrim(string(idx.maskp),2), ','), format='(A)'
print, 'POINTER=' + strjoin(strtrim(string(idx.pointer),2), ','), format='(A)'
print, 'FIRSTP=' + strjoin(strtrim(string(idx.firstp),2), ','), format='(A)'
print, 'NUMIMAGES=' + strjoin(strtrim(string(idx.numimages),2), ','), format='(A)'
print, 'DATE=' + strjoin(strtrim(string(idx.date),2), ','), format='(A)'
print, 'BUFFTIME=' + strjoin(string(idx.bufftime, format='(E25.17)'), ','), format='(A)'
print, 'BUFFTIMEHEX=' + strjoin(string(ulong64(idx.bufftime,0,n_elements(idx.bufftime)), format='(Z016)'), ','), format='(A)'
print, 'TN=' + size(idx.date,/tname)+','+size(idx.bufftime,/tname)+','+size(idx.pointer,/tname)+','+size(idx.firstp,/tname)+','+size(idx.imagep,/tname)+','+size(idx.hkp,/tname)+','+size(idx.maskp,/tname)+','+size(idx.count,/tname)+','+size(idx.numimages,/tname)+','+size(idx.buffsize,/tname)+','+size(idx.ibuffer,/tname)+','+size(idx.ihk,/tname)+','+size(idx.particlecounter,/tname)+','+size(idx.arrayid,/tname)+','+size(idx.error,/tname), format='(A)'
"""

_LITE_SCRIPT = """
lt1 = {call}
print, 'CASE={name} TAGS=' + strjoin(tag_names(lt1), ','), format='(A)'
print, 'LITE_FIRSTP=' + strjoin(strtrim(string(lt1.firstp),2), ','), format='(A)'
print, 'LITE_BUFFPOINT=' + strjoin(strtrim(string(lt1.buffpoint),2), ','), format='(A)'
print, 'LITE_BUFFTIMEHEX=' + strjoin(string(ulong64(lt1.bufftime,0,n_elements(lt1.bufftime)), format='(Z016)'), ','), format='(A)'
"""

_AUTODETECT_SCRIPT = """
f=fstat(lun)
point_lun,lun,0
x=intarr(10000<(f.size/2))
readu,lun,x
w=where((x eq x[0]) and (x[1:*] eq x[1]) and (x[2:*] eq x[2]))
print, 'CASE={name} W=' + strjoin(strtrim(string(w),2), ',') + ' BUFFSIZE=' + strtrim(string(w[1]*2ULL),2), format='(A)'
"""

_ABSPOINTERS_SCRIPT = """
p = ptr_new({call})
a = spec_absolutepointers({buffnum}, p)
print, 'CASE={name} AP=' + strjoin(strtrim(string(a.ap),2), ',') + ' N=' + strtrim(string(a.n),2) + ' TN=' + size(a.ap,/tname) + ',' + size(a.n,/tname) + ' NEL=' + strtrim(string(n_elements(a.ap)),2), format='(A)'
ptr_free, p
"""


def _script_for(case: Case) -> str:
    if case.kind == "index":
        return _INDEX_SCRIPT.format(call=case.call, name=case.name)
    if case.kind == "index_p460":
        # The P460 line re-opens the same record (a second `CASE=` line for
        # the same name); `_parse` merges it rather than replacing it.
        return (_INDEX_SCRIPT.format(call=case.call, name=case.name)
                + _P460_SCRIPT.format(name=case.name))
    if case.kind == "lite":
        return _LITE_SCRIPT.format(call=case.call, name=case.name)
    if case.kind == "autodetect":
        return _AUTODETECT_SCRIPT.format(name=case.name)
    if case.kind == "abspointers":
        return _ABSPOINTERS_SCRIPT.format(
            call=case.call, buffnum=case.buffnum, name=case.name)
    raise ValueError(case.kind)  # pragma: no cover


def _build_main_script(paths: dict[str, str]) -> str:
    by_fixture: dict[str, list[Case]] = {}
    for case in CASES:
        by_fixture.setdefault(case.fixture, []).append(case)

    lines: list[str] = []
    # idx fixture: index/autodetect/abspointers cases, in the order that
    # keeps ptr_new/ptr_free balanced.
    lines.append(f"openr, lun, '{paths['idx']}', /get_lun")
    for case in by_fixture.get("idx", []):
        if case.kind != "abspointers":
            lines.append(_script_for(case))
    for case in by_fixture.get("idx", []):
        if case.kind == "abspointers":
            lines.append(_script_for(case))
    lines.append("free_lun, lun")

    lines.append(f"openr, lun, '{paths['triple']}', /get_lun")
    for case in by_fixture.get("triple", []):
        lines.append(_script_for(case))
    lines.append("free_lun, lun")

    lines.append(f"openr, lun, '{paths['s2']}', /get_lun")
    for case in by_fixture.get("s2", []):
        if case.kind != "abspointers":
            lines.append(_script_for(case))
    for case in by_fixture.get("s2", []):
        if case.kind == "abspointers":
            lines.append(_script_for(case))
    lines.append("free_lun, lun")

    lines.append(f"openr, lun, '{paths['frame']}', /get_lun")
    for case in by_fixture.get("frame", []):
        lines.append(_script_for(case))
    lines.append("free_lun, lun")

    lines.append(f"openr, lun, '{paths['hk']}', /get_lun")
    for case in by_fixture.get("hk", []):
        lines.append(_script_for(case))
    lines.append("free_lun, lun")

    if by_fixture.get("tiled3"):
        lines.append(f"openr, lun, '{paths['tiled3']}', /get_lun")
        for case in by_fixture["tiled3"]:
            lines.append(_script_for(case))
        lines.append("free_lun, lun")

    # julday third side, U2's out-of-range measurement.
    lines.append(
        "print, 'JULDAY=', julday(9,6,2016), ',', julday(9,7,1999), ',', "
        "julday(1,1,2000), ',', julday(9,2,2016), ',', julday(9,0,2016), "
        "format='(A,I0,A,I0,A,I0,A,I0,A,I0)'")
    return "\n".join(lines)


_HALTING_SCRIPT = "idx = spec_index(lun)\nprint, 'CASE={name} COUNT=', idx.count, ' BUFFSIZE=', idx.buffsize, format='(A,I0,A,I0)'"


def _run_halting_case(name: str, path: str, timeout: int = 20) -> dict:
    script = f"openr, lun, '{path}', /get_lun\n" + _HALTING_SCRIPT.format(name=name)
    try:
        stdout, stderr = run_pro(script, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "HALTED", "stdout": "",
                "stderr": f"blocked, killed after {timeout}s"}
    if f"CASE={name}" in stdout:
        return {"name": name, "status": "OK",
                "stdout": stdout[-500:], "stderr": stderr[-500:]}
    if "File misaligned" in stdout:
        return {"name": name, "status": "HALTED",
                "stdout": stdout[-500:], "stderr": stderr[-500:]}
    return {"name": name, "status": "ERROR",
            "stdout": stdout[-500:], "stderr": stderr[-500:]}


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_KV = re.compile(r"(\w+)=(\S*)")


def _parse(stdout: str) -> dict[str, dict]:
    """Every `CASE=<name> ...` line starts a record; every following
    `KEY=value` line (up to the next `CASE=`) adds a field to it. Uniform
    across all four kinds -- each kind's distinguishing keys are just
    different `KEY=` tokens on the lines that follow."""
    records: dict[str, dict] = {}
    current: dict | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("CASE="):
            fresh: dict = {}
            for key, val in _KV.findall(line):
                fresh[key] = val
            name = fresh.pop("CASE")
            fresh["name"] = name
            # A second `CASE=` line for a name already seen (index_p460's
            # P460 line) adds to that record instead of replacing it.
            current = records.setdefault(name, {})
            current.update(fresh)
        elif current is not None and "=" in line:
            key, _, val = line.partition("=")
            current[key.strip()] = val.strip()
        elif line.startswith("JULDAY="):
            # Not tied to any Case -- a standalone U2 sanity measurement.
            records["__julday__"] = {"JULDAY": line[len("JULDAY="):]}
    return records


_INDEX_FIELDS = ("COUNT", "BUFFSIZE", "NIMG", "NHK", "NMK", "ERR", "IMAGEP",
                  "IBUFFER", "IHK", "PC", "ARRAYID", "HKP", "MASKP",
                  "POINTER", "FIRSTP", "NUMIMAGES", "DATE", "BUFFTIME",
                  "BUFFTIMEHEX", "TN")
_LITE_FIELDS = ("TAGS", "LITE_FIRSTP", "LITE_BUFFPOINT", "LITE_BUFFTIMEHEX")
_AUTODETECT_FIELDS = ("W", "BUFFSIZE")
_ABSPOINTERS_FIELDS = ("AP", "N", "TN", "NEL")

_FIELDS_BY_KIND = {
    "index": _INDEX_FIELDS,
    "index_p460": _INDEX_FIELDS + ("P460", "P460TN"),
    "lite": _LITE_FIELDS,
    "autodetect": _AUTODETECT_FIELDS,
    "abspointers": _ABSPOINTERS_FIELDS,
}


def main() -> int:
    raw_main = write_fixture(FIXTURE_MAIN, build_main())
    raw_triple = write_fixture(FIXTURE_TRIPLE, build_triple())
    assert len(raw_main) == 24784, len(raw_main)
    assert len(raw_triple) == 12342, len(raw_triple)
    for path in (S2_RAW, FRAME_RAW, HK_RAW):
        if not path.is_file():
            print(f"{path} is missing -- this bank needs it")
            return 2

    paths = {
        "idx": FIXTURE_MAIN.resolve().as_posix(),
        "triple": FIXTURE_TRIPLE.resolve().as_posix(),
        "s2": S2_RAW.resolve().as_posix(),
        "frame": FRAME_RAW.resolve().as_posix(),
        "hk": HK_RAW.resolve().as_posix(),
    }

    records: list[dict] = []
    tiled_dir = tempfile.TemporaryDirectory(prefix="soda2_tiled3_")
    tiled_path = Path(tiled_dir.name) / "soda2_spec_index_tiled3_fixture"
    tiled_path.write_bytes(build_tiled3())
    paths["tiled3"] = tiled_path.resolve().as_posix()
    try:
        stdout, stderr = run_pro(_build_main_script(paths), timeout=180)
        parsed = _parse(stdout)

        for case in CASES:
            vals = parsed.get(case.name)
            required = _FIELDS_BY_KIND[case.kind]
            rec: dict = {
                "name": case.name, "fixture": case.fixture, "kind": case.kind,
                "call": case.call, "buffnum": case.buffnum, "note": case.note,
            }
            if vals is None or not all(k in vals for k in required):
                rec.update(status="ERROR",
                           stdout=stdout[-800:], stderr=stderr[-500:])
                print(f"{case.name}: ERROR")
            else:
                rec.update(status="OK", **{k: vals[k] for k in required})
                print(f"{case.name}: OK")
            records.append(rec)

        if "__julday__" in parsed:
            print(f"julday sanity: {parsed['__julday__']['JULDAY']}")

        # The three cases that end their own run: an uncaught GDL error or
        # `stop` aborts the rest of a compiled procedure.
        with tempfile.TemporaryDirectory() as tmp:
            short_path = Path(tmp) / "short_fixture"
            badyear_path = Path(tmp) / "badyear_fixture"
            short_path.write_bytes(build_short())
            badyear_path.write_bytes(build_badyear())

            for name, path in (
                ("triple_full", paths["triple"]),
                ("short", short_path.resolve().as_posix()),
                ("badyear", badyear_path.resolve().as_posix()),
            ):
                rec = _run_halting_case(name, path)
                rec.update(fixture={"triple_full": "triple", "short": "short",
                                     "badyear": "badyear"}[name],
                           kind="index", call="spec_index(lun)", buffnum="",
                           note={
                               "triple_full": "the 216-byte autodetected "
                                   "'buffsize' makes the third real header "
                                   "look like data; :72 stops (S4-k).",
                               "short": ":30's w=[0] has no w[1]; IDL dies "
                                   "with a scalar-subscript error.",
                               "badyear": "year 2051 fails :72's range check "
                                   "on the very first header.",
                           }[name])
                print(f"{name}: {rec['status']}")
                records.append(rec)

    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2
    finally:
        tiled_dir.cleanup()

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
