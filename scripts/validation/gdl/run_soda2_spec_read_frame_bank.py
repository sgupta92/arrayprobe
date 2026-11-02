# SPDX-License-Identifier: BSD-3-Clause
r"""SPEC buffer decode: `spec_read_frame.pro` under GDL, unmodified, against a new
tracked synthetic frame fixture -- plus one GDL-oracle shim for `spec_decompress.pro`
(never a port change, see below).

`spec_read_frame` reads a frame header (`spec_readint(lun, 3)`), decodes the
`H`/`V` presence flags and lengths packed into that header, reads the rest of
the frame, assembles a `time`/`timetrunc` word pair, recurses up to two levels
to stitch a particle split across "missing time word" fragments, and finally
calls `spec_decompress` (already ported) on the concatenated raw words.

**The fixture** (`tests/data/soda2_spec_frame_fixture`, 3 x 4114-byte SPEC
buffers = 12342 bytes, synthetic, no campaign data) packs 17 hand-placed
frames end to end: an ordinary H frame, an ordinary V frame (also read back
as the wrong array on purpose), a frame with both H and V present, an
overload frame, a FIFO-flag frame, two frames too short to count as a real
H block (`nh<=3`), a frame that straddles the buffer-0/buffer-1 boundary, a
three-fragment "missing time word" chain capped by the recursion depth limit
(`recursioncount lt 2`), a `version=1` H frame with the reversed counter
order, a `version=1` V frame (added beyond the 16 GDL-measured cases; not
independently measured against IDL semantics by hand, so GDL's own answer is
the golden here, not a hand derivation), and a frame whose own 3-word header
read lands exactly on a buffer footer. `build_fixture()` is the single source
of truth for the byte layout; `POINTERS` names where each case starts.

**The GDL trap this bank works around, not a SODA-2 finding.** GDL 1.1.2's
`ISHFT` returns a **1-element array** for a scalar operand (measured:
`size(ishft(0L,-15),/n_dim)` is 1 under GDL, 0 under real IDL). `overload` at
`spec_read_frame.pro:22` is built with `ishft`, so it reaches
`spec_decompress.pro:23-25`'s `skip=overload*2` / `FOR i=0,n-1-skip` as a
1-element array, and GDL halts with `SPEC_DECOMPRESS: Loop LIMIT must be a
scalar in this context`. The existing `spec_decompress` bank never saw this
because it passed `{overload}L` literals straight into the function.

The fix is the established shim pattern (`run_soda2_aspect_ratio_bank.py`'s
`erode.pro`, via `locate.run_pro`'s `extra_files=`): a **copy** of the
vendored `spec_decompress.pro` with exactly one line inserted after its line
8 (`n=n_elements(cimage)`), placed on `GDL_PATH` *ahead of* the vendored
tree so GDL resolves the shim instead of the real file for the duration of
this bank's `run_pro` calls. Nothing is ever written into `SODA2/`; the
vendored tree is never touched (`tests/test_upstream_tree_is_unmodified.py`
sweeps it, and `TheOracleShimIsOneLine` in this stage's test module asserts
the shim differs from the real file by exactly that one inserted line).
`overload[0]` on an IDL scalar is legal and a no-op, so the shim changes
nothing under real IDL -- it exists only for GDL's own quirk, and is
recorded in the golden and the design record as an oracle limitation, never
as a SODA-2 finding.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_spec_read_frame_bank.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import SODA2_TREE, GDLUnavailable, run_pro  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

DATA = Path(__file__).resolve().parents[3] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_spec_read_frame_golden.json"
FIXTURE_RAW = DATA / "soda2_spec_frame_fixture"

BUFSIZE = 4114
HEADER_WORDS = 8
DATA_WORDS = 2048

#: The three plain compressed-image word groups reused throughout the
#: fixture, exactly as `spec_decompress`'s own bank already validated them --
#: none sets the timeslice (0x8000), startslice-plus-overflow, or overload
#: bits in a way this bank cares about; they are just image payload.
A = [0x4505, 0x0403]
B = [0x4202, 0x0301, 0x4600]
C = [0x4a0a, 0x0785, 0x4489, 0x01a8]


def frame(hwords: list[int], vwords: list[int], pc: int, ns: int,
          hflags: int = 0, vflags: int = 0) -> list[int]:
    """One `spec_read_frame`-shaped word list: `[marker, nh|hflags, nv|vflags,
    pc, ns] + hwords + vwords`, `nh=len(hwords)`, `nv=len(vwords)` -- exactly
    what `buff = spec_readint(lun, 2+nh+nv)` (`:26`) expects to find after the
    3-word `x = spec_readint(lun, 3)` (`:13`) that reads the first three words."""
    nh, nv = len(hwords), len(vwords)
    assert nh <= 0xFFF and nv <= 0xFFF
    return [12883, nh | hflags, nv | vflags, pc, ns, *hwords, *vwords]


POINTERS: dict[str, int] = {
    "h_plain": 16,
    "v_plain": 34,
    "dual": 54,
    "overload": 82,
    "fifo": 104,
    "tw_only": 122,
    "nh3": 136,
    "cross_buff": 4098,
    "mtw_then_v_then_h": 4138,
    "v_in_chain": 4156,
    "h_completes": 4176,
    "chain_m1": 4194,
    "chain_m2": 4212,
    "chain_m3": 4230,
    "chain_m4": 4248,
    "v1_h": 4266,
    "v1_v": 4286,
    "x_on_footer": 8220,
}


def build_fixture() -> bytes:
    """3 buffers x 4114 bytes, little-endian uint16 throughout (header,
    data, footer alike) -- the same convention as `s2_spec_raw_fixture`
    (`octave_oracle/run_s2_spec_bank.py`). Frames are placed contiguously
    from data word 0 of buffer 0;
    the tail frame straddles the buffer-0/buffer-1 boundary and
    `x_on_footer` straddles buffer-1/buffer-2, on purpose."""
    buffers: list[list[int]] = [[0] * DATA_WORDS for _ in range(3)]

    def place(buf_idx: int, word_idx: int, words: list[int]) -> None:
        buf = buffers[buf_idx]
        end = word_idx + len(words)
        assert end <= DATA_WORDS, (buf_idx, word_idx, len(words))
        buf[word_idx:end] = words

    # ---- Buffer 0 ----------------------------------------------------
    place(0, 0, frame(A + [1, 0], [], 7, 2))                              # h_plain @16
    place(0, 9, frame([], B + [2, 5], 8, 3))                              # v_plain @34
    place(0, 19, frame(A + [3, 10], B + [3, 11], 9, 2))                   # dual @54
    place(0, 33, frame(A + B[:2] + [4, 0], [], 10, 4, hflags=0x8000))     # overload @82
    place(0, 44, frame(A + [5, 0], [], 11, 2, hflags=0x4000))             # fifo @104
    place(0, 53, frame([5, 7], [], 12, 0))                                # tw_only @122 (nh=2)
    place(0, 60, frame([0x4505, 6, 0], [], 13, 1))                        # nh3 @136 (nh=3)
    tail = frame(A + C[:2] + [14, 1], [], 14, 4)                         # 11 words, split
    assert len(tail) == 11
    place(0, 2041, tail[:7])                                             # cross_buff @4098

    # ---- Buffer 1 ------------------------------------------------------
    place(1, 0, tail[7:])                                                 # tail's remainder
    place(1, 4, frame(A + [7, 0], [], 15, 2, hflags=0x1000))              # mtw_then_v_then_h @4138
    place(1, 13, frame([], B + [7, 1], 16, 3))                            # v_in_chain @4156
    place(1, 23, frame(C[:2] + [8, 3], [], 17, 2))                        # h_completes @4176
    place(1, 32, frame(A + [21, 0], [], 18, 2, hflags=0x1000))            # chain_m1 @4194
    place(1, 41, frame(B[:2] + [22, 0], [], 19, 2, hflags=0x1000))        # chain_m2 @4212
    place(1, 50, frame(C[:2] + [23, 9], [], 20, 2, hflags=0x1000))        # chain_m3 @4230
    place(1, 59, frame(A + [24, 0], [], 21, 2))                          # chain_m4 @4248
    place(1, 68, frame(A + [30, 31, 99], [], 22, 2))                      # v1_h @4266 (version=1)
    place(1, 78, frame([], B + [32, 33, 99], 23, 3))                      # v1_v @4286 (version=1)
    place(1, 2045, [12883, 4, 0])                                        # x_on_footer @8220 (start)

    # ---- Buffer 2 --------------------------------------------------------
    place(2, 0, [15, 2, 0x4505, 0x0403, 40, 41])                          # x_on_footer's remainder

    out = bytearray()
    for k, data_words in enumerate(buffers):
        header = [2016, 9, 2, 6, 6, 44, 3 + k, 250]
        assert len(header) == HEADER_WORDS
        words = header + data_words + [0]  # footer
        assert len(words) == HEADER_WORDS + DATA_WORDS + 1
        for w in words:
            out += int(w & 0xFFFF).to_bytes(2, "little")
    raw = bytes(out)
    assert len(raw) == 3 * BUFSIZE, len(raw)
    return raw


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
    scrub_output(FIXTURE_RAW)  # path prefixes -> <repo>, <tmp>, ~
    return raw


# --------------------------------------------------------------------------
# The one-line GDL-oracle shim for spec_decompress.pro (never a port change)
# --------------------------------------------------------------------------

SHIM_INSERTED_LINE = (
    "   overload = overload[0]   ; GDL-oracle shim: GDL 1.1.2's ISHFT returns "
    "a 1-element array for a scalar operand; IDL returns a scalar. No-op "
    "under IDL."
)


def decompress_shim() -> str:
    vendored = (SODA2_TREE / "spec_decompress.pro").read_text(encoding="utf-8")
    lines = vendored.splitlines()
    shimmed = lines[:8] + [SHIM_INSERTED_LINE] + lines[8:]
    return "\n".join(shimmed) + "\n"


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------

@dataclass
class Case:
    name: str
    pointer: int
    id: str
    version: int
    note: str = ""


CASES: list[Case] = [
    Case("h_plain", POINTERS["h_plain"], "H", 0,
         "ordinary H frame, nh=4."),
    Case("v_plain", POINTERS["v_plain"], "V", 0,
         "ordinary V frame, nv=5."),
    Case("v_plain_wrong_array", POINTERS["v_plain"], "H", 0,
         "the SAME frame read as 'H': nh=0 there, so no block runs -- "
         "error=1, imageraw stays the 0b scalar, but the file pointer still "
         "advances past the whole frame (spec_readint doesn't care what id "
         "asked for)."),
    Case("dual_h", POINTERS["dual"], "H", 0,
         "a frame with both nh>3 and nv>3 populated, read as H."),
    Case("dual_v", POINTERS["dual"], "V", 0,
         "the same frame, read as V."),
    Case("overload", POINTERS["overload"], "H", 0,
         "hflags=0x8000 (overloadh): OVL=1, and spec_decompress's overload "
         "skip changes NSL (still counts the startslice bit of the skipped "
         "words, S4-a's +3 is unaffected)."),
    Case("fifo", POINTERS["fifo"], "H", 0,
         "hflags=0x4000 (fifoh): decoded and silently discarded (S4-f) -- "
         "output-identical to h_plain except its own counter/pc."),
    Case("tw_only", POINTERS["tw_only"], "H", 0,
         "nh=2 (<=3): the H block never runs, error=1, imageraw is the "
         "initial 0b scalar (S4-e evidence)."),
    Case("nh3", POINTERS["nh3"], "H", 0,
         "nh=3 (<=3): same as tw_only, boundary value."),
    Case("cross_buff", POINTERS["cross_buff"], "H", 0,
         "starts inside buffer 0's last data words; spec_readint's own "
         "boundary splice must fire twice inside this one spec_read_frame "
         "call (the 3-word header read, then the buff read)."),
    Case("mtw_then_v_then_h", POINTERS["mtw_then_v_then_h"], "H", 0,
         "hflags=0x1000 (missingtwh) but the very next frame at the current "
         "file position is a V frame ('v_in_chain'), not an H fragment -- "
         "the REPEAT...UNTIL q.error eq 0 loop (:76-79) must skip over it "
         "and land on 'h_completes'."),
    Case("v_in_chain", POINTERS["v_in_chain"], "V", 0,
         "read directly as V (not via recursion): an ordinary frame that "
         "also happens to sit inside the H recursion chain above."),
    Case("chain_m1", POINTERS["chain_m1"], "H", 0,
         "three missingtw-flagged H frames in a row (chain_m1..chain_m3) "
         "followed by a complete one (chain_m4): recursioncount lt 2 caps "
         "the recursion at 3 fragments total, so chain_m4 is never read -- "
         "AFTER lands on its start (S4-d)."),
    Case("v1_h", POINTERS["v1_h"], "H", 1,
         "version=1: nh-- inside the H block (:39), and the counter order "
         "is reversed (:69) relative to version 0."),
    Case("v1_v", POINTERS["v1_v"], "V", 1,
         "version=1 V frame -- not measured by the planner by hand "
         "(U1 in the plan); this bank's own GDL run is the first-hand "
         "measurement, not a derivation."),
    Case("x_on_footer", POINTERS["x_on_footer"], "H", 0,
         "the 3-word `x = spec_readint(lun,3)` header read ends exactly on "
         "buffer 1's footer; spec_readint's own post-read jump (:46-47 "
         "there) must fire so the SECOND read (buff) resumes inside "
         "buffer 2's live data, not its footer/header dead zone."),
    Case("h_plain_lowercase_id", POINTERS["h_plain"], "h", 0,
         "id='h' (lower-case): IDL's `eq` is case-sensitive, so neither "
         "block's `id eq 'H'`/`id eq 'V'` test ever matches -- error=1, "
         "same as an absent array, even though a perfectly good H frame "
         "sits right there."),
]


_CASE_SCRIPT = """
q = spec_read_frame(lun, {pointer}ULL, '{id}', version={version})
point_lun, -lun, after
print, 'CASE={name} AFTER=', after, ' ERROR=', q.error, ' OVL=', q.overload, $
   ' PC=', q.particlecount, ' TIME=', q.time, ' TT=', q.timetrunc, $
   ' NSL=', n_elements(q.image)/128, $
   format='(A,I0,A,I0,A,I0,A,I0,A,I0,A,I0,A,I0)'
IF size(q.imageraw,/n_dim) eq 0 THEN $
   print, 'IMRAW=SCALAR:' + size(q.imageraw,/tname) + ':', q.imageraw, format='(A,I0)' $
ELSE $
   print, 'IMRAW=', strjoin(strtrim(string(q.imageraw),2), ','), format='(A,A)'
print, 'TN=' + size(q.overload,/tname) + ',' + size(q.error,/tname) + ',' + $
   size(q.time,/tname) + ',' + size(q.particlecount,/tname) + ',' + size(q.image,/tname)
nsl = n_elements(q.image)/128
for k = 0, nsl - 1 do $
   print, 'SLICE=', k, ':', strjoin(strtrim(string(fix(q.image[*,k])),2)), $
      format='(A,I0,A,A)'
"""


def _script_for_all(path: str) -> str:
    lines = [f"openr, lun, '{path}', /get_lun"]
    lines.append("print, 'ISHFT_SCALAR_NDIM=', size(ishft(0L,-15),/n_dim), "
                 "format='(A,I0)'")
    for case in CASES:
        lines.append(_CASE_SCRIPT.format(
            pointer=case.pointer, id=case.id, version=case.version,
            name=case.name))
    lines.append("free_lun, lun")
    return "\n".join(lines)


def _parse(stdout: str) -> dict[str, dict]:
    records: dict[str, dict] = {}
    current: dict | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("CASE="):
            # 'CASE=name AFTER=.. ERROR=.. OVL=.. PC=.. TIME=.. TT=.. NSL=..'
            rest = line[len("CASE="):]
            name, _, tail = rest.partition(" AFTER=")
            current = {"name": name}
            after_str, _, tail = tail.partition(" ERROR=")
            current["AFTER"] = int(after_str)
            error_str, _, tail = tail.partition(" OVL=")
            current["ERROR"] = int(error_str)
            ovl_str, _, tail = tail.partition(" PC=")
            current["OVL"] = int(ovl_str)
            pc_str, _, tail = tail.partition(" TIME=")
            current["PC"] = int(pc_str)
            time_str, _, tail = tail.partition(" TT=")
            current["TIME"] = int(time_str)
            tt_str, _, nsl_str = tail.partition(" NSL=")
            current["TT"] = int(tt_str)
            current["NSL"] = int(nsl_str)
            current["SLICES"] = []
            records[name] = current
        elif line.startswith("IMRAW=SCALAR:"):
            rest = line[len("IMRAW=SCALAR:"):]
            tname, _, _val = rest.partition(":")
            current["IMRAW"] = f"SCALAR:{tname}:0"
        elif line.startswith("IMRAW="):
            text = line[len("IMRAW="):].strip()
            current["IMRAW"] = [int(v) for v in text.split(",")] if text else []
        elif line.startswith("TN="):
            current["TN"] = line[len("TN="):].strip()
        elif line.startswith("SLICE="):
            rest = line[len("SLICE="):]
            _idx, _, bits = rest.partition(":")
            current["SLICES"].append(bits.strip())
    return records


def main() -> int:
    raw = write_fixture()
    assert len(raw) == 3 * BUFSIZE

    shim = decompress_shim()
    path = FIXTURE_RAW.resolve().as_posix()
    script = _script_for_all(path)

    records: list[dict] = []
    try:
        stdout, stderr = run_pro(
            script, timeout=60,
            extra_files={"spec_decompress.pro": shim})
        parsed = _parse(stdout)
        ishft_ndim = None
        for line in stdout.splitlines():
            if line.strip().startswith("ISHFT_SCALAR_NDIM="):
                ishft_ndim = int(line.strip()[len("ISHFT_SCALAR_NDIM="):])

        for case in CASES:
            vals = parsed.get(case.name)
            rec: dict = {
                "name": case.name,
                "pointer": case.pointer,
                "id": case.id,
                "version": case.version,
                "note": case.note,
                "oracle_shim": "spec_decompress.pro +1 line "
                               "(overload=overload[0]); GDL ISHFT returns "
                               "Array[1] for a scalar",
            }
            required = ("AFTER", "ERROR", "OVL", "PC", "TIME", "TT", "NSL",
                        "IMRAW", "TN", "SLICES")
            if vals is None or not all(k in vals for k in required):
                rec.update(status="ERROR",
                           stdout=stdout[-1200:], stderr=stderr[-600:])
                print(f"{case.name}: ERROR")
            else:
                rec.update(status="OK", **{k: vals[k] for k in required})
                print(f"{case.name}: AFTER={vals['AFTER']} ERROR={vals['ERROR']} "
                      f"OVL={vals['OVL']} PC={vals['PC']} TIME={vals['TIME']} "
                      f"TT={vals['TT']} NSL={vals['NSL']}")
            records.append(rec)
        if ishft_ndim is not None:
            print(f"ISHFT_SCALAR_NDIM (GDL) = {ishft_ndim} "
                  "(1 confirms the trap this bank's shim works around)")
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2

    ok = sum(1 for r in records if r["status"] == "OK")
    if ok == 0:
        print("refusing to write a golden in which every case errored")
        return 1
    GOLDEN.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    print(f"\nwrote {GOLDEN} -- {len(records)} cases, {ok} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
