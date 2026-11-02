# SPDX-License-Identifier: BSD-3-Clause
r"""SODA-2 HVPS-4 slice A: ``hvps4_read_frame.pro`` under GDL on a synthetic
HVPS-4 packet stream, through an oracle-path shim of lines 39-40.

**Why a shim (measured 2026-10-03, AF2).** GDL 1.1.2 has no IDL 8.4+ string
methods: it parses ``id.substring(0,0)`` as a struct-field access and the
unmodified vendored file halts at its own line 39 (``Expression must be a
STRUCT in this context: ID``). The repository's oracle rule (Octave
differential oracle: shim a call the oracle cannot run with a file on
the oracle's path *ahead of* the vendored tree, never an edit, and label what
it reaches) is applied here: ``gdl_oracle/shims/hvps4_read_frame.pro`` is a
copy of the vendored file that differs **only** at lines 39-40, where
``id.substring(0,0)`` becomes ``strmid(id,0,1)`` and ``fix(id.substring(1,3))``
becomes ``fix(strmid(id,1,3))`` (IDL's ``substring(s,e)`` is inclusive of
``e`` and clamps at the string end, as ``strmid`` does).
``tests/test_soda2_hvps4_read_frame.py::TheOracleShimDiffersOnlyAtLines39And40``
diffs the shim against the vendored file so it cannot drift. The values the
shim reaches are ``array`` and ``res`` -- i.e. which block (if any) runs --
so every golden record carries ``"shim_derived": ["array", "res"]``.

The second shim is the existing one-line ``spec_decompress.pro`` shim
(``run_soda2_spec_read_frame_bank.decompress_shim``): GDL's ``ISHFT`` returns a
1-element array for a scalar, so ``overloadh`` (``:21``) would halt
``spec_decompress``'s loop limit. A no-op under IDL.

**The time assembly is an oracle difference, not a SODA-2 finding (decided 2026-10-03).**
``:48``/``:59`` assemble ``time`` as ``ishft(c[2],32) + ishft(c[1],16) + c[0]``
with ``c`` ULONG. GDL returns ``ishft(ULONG, 32)`` **unshifted** (the shift
count is taken mod 32, as an x86 ``shl`` does), so case ``high_counter``
(``c = [0xFFFF, 0xABCD, 3]``) gives ``TIME = 2882404354 = 0xABCDFFFF + 3``:
the high word is *added*. IDL's ISHFT page (nv5geospatialsoftware.com/docs/ISHFT,
read 2026-10-03) says only that a positive ``P2`` left-shifts with 0 bits
filling vacated positions; it states no result for a count >= the type's
width. Read literally, a ULONG shifted left 32 places is 0, so under IDL the
term would vanish and ``time`` be the low 32 bits, which is what
``soda2_processbuffer.pro:316-320``'s 4294967295 rollover expects. That
reading is *derived from the documentation*, not measured: no IDL run exists
here. The golden, and the port's ``_ishft_ulong``, carry GDL's value; the
two agree with IDL whenever ``c[2] == 0``, every other case in the bank.

**The V-block counter is a SODA-2 finding** (S9-n): ``:57-58`` index the
V block with no ``nh`` offset, so case ``dual_v50`` takes its counter from the
H words (``TIME = 16902 = 0x4206``). Plain indexing, so GDL and IDL agree.

**The fixture** (``tests/data/soda2_hvps4_frame_fixture``, one 4114-byte SPEC
buffer, synthetic, no campaign data) holds the frames in ``POINTERS``.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_hvps4_read_frame_bank.py
"""
from __future__ import annotations

import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, run_pro  # noqa: E402
from run_soda2_spec_read_frame_bank import decompress_shim  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

HERE = Path(__file__).resolve().parent
SHIM = HERE / "shims" / "hvps4_read_frame.pro"
DATA = HERE.parents[2] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_hvps4_read_frame_golden.json"
FIXTURE_RAW = DATA / "soda2_hvps4_frame_fixture"

BUFSIZE = 4114
HEADER_WORDS = 8
DATA_WORDS = 2048

A = [0x4505, 0x0403]
B = [0x4202, 0x0301, 0x4600]

RES50 = 0x4000  # bit 14: 1 = 50 um array (`:19-20`)


def frame(hwords: list[int], vwords: list[int], pc: int, ns: int,
          hflags: int = 0, vflags: int = 0) -> list[int]:
    """``[marker, nh|hflags, nv|vflags, pc, ns] + hwords + vwords``: the 3-word
    header ``:12`` reads, then the ``2+nh+nv`` words ``:25`` reads."""
    nh, nv = len(hwords), len(vwords)
    return [0x3448, nh | hflags, nv | vflags, pc, ns, *hwords, *vwords]


#: (name, word offset in buffer 0's data, words)
FRAMES: list[tuple[str, list[int]]] = [
    ("h50", frame(A + [0x0001, 0x0002, 0x0000], [], 7, 2, hflags=RES50)),
    ("h150", frame(B + [0x1234, 0x0005, 0x0000], [], 8, 3)),
    ("v150", frame([], A + [0x0010, 0x0020, 0x0000], 9, 2)),
    ("dual", frame(A + [0x0003, 0x0004, 0x0000],
                   B + [0x0030, 0x0040, 0x0000], 10, 2, vflags=RES50)),
    ("mtw", frame(A + [0x0006, 0x0007, 0x0000], [], 11, 2,
                  hflags=RES50 | 0x1000)),
    ("overload", frame(A + B[:2] + [0x0008, 0x0009, 0x0000], [], 12, 4,
                       hflags=RES50 | 0x8000)),
    ("nh3", frame([0x4505, 0x0001, 0x0002], [], 13, 1, hflags=RES50)),
    ("high_counter", frame(A + [0xFFFF, 0xABCD, 0x0003], [], 14, 2,
                           hflags=RES50)),
]


def _layout() -> tuple[list[int], dict[str, int]]:
    words = [0] * DATA_WORDS
    pointers: dict[str, int] = {}
    at = 0
    for name, w in FRAMES:
        pointers[name] = 2 * (HEADER_WORDS + at)
        words[at:at + len(w)] = w
        at += len(w)
    return words, pointers


POINTERS: dict[str, int] = _layout()[1]


def build_fixture() -> bytes:
    """One SPEC buffer: 8 header words, 2048 data words, 1 footer word,
    little-endian uint16 (the ``soda2_spec_frame_fixture`` convention)."""
    words = [0] * HEADER_WORDS + _layout()[0] + [0]
    raw = struct.pack(f"<{len(words)}H", *words)
    assert len(raw) == BUFSIZE
    return raw


def write_fixture() -> bytes:
    raw = build_fixture()
    FIXTURE_RAW.write_bytes(raw)
    scrub_output(FIXTURE_RAW)  # path prefixes -> <repo>, <tmp>, ~
    return raw


@dataclass
class Case:
    name: str
    frame: str
    id: str
    note: str = ""


CASES: list[Case] = [
    Case("h50", "h50", "H50", "ordinary 50 um H frame, nh=5."),
    Case("h50_read_as_h150", "h50", "H150",
         "bit 14 says 50 um, id asks 150: no block runs, error=1."),
    Case("h150", "h150", "H150", "ordinary 150 um H frame (bit 14 clear)."),
    Case("v150", "v150", "V150", "ordinary V frame with nh=0."),
    Case("dual_v50", "dual", "V50",
         "nh=5 and nv=6: the V block reads image and counter from buff[2:] "
         "with no nh offset (:57-58, a SODA-2 finding), i.e. from the H words."),
    Case("dual_h150", "dual", "H150", "the same frame, read as H150."),
    Case("mtw", "mtw", "H50",
         "missing-time-word flag: decoded, then error=1 (:51); no stitching."),
    Case("overload", "overload", "H50", "bit 15 set: overload=1."),
    Case("nh3", "nh3", "H50", "nh=3: the H block needs nh gt 3, error=1."),
    Case("high_counter", "high_counter", "H50",
         "hcounter[2]=3, hcounter[1]=0xABCD: measures ishft(ULONG,32) (an oracle difference)."),
    Case("h50_lowercase", "h50", "h50",
         "id 'h50': `array eq 'H'` is case-sensitive, error=1."),
    Case("h50_read_as_v50", "h50", "V50", "nv=0: no block runs."),
]

_CASE_SCRIPT = """
q = hvps4_read_frame(lun, {pointer}ULL, '{id}')
point_lun, -lun, after
print, 'CASE={name} AFTER=', after, ' ERROR=', q.error, ' OVL=', q.overload, $
   ' PC=', q.particlecount, ' TIME=', q.time, ' NSL=', n_elements(q.image)/128, $
   format='(A,I0,A,I0,A,I0,A,I0,A,I0,A,I0)'
print, 'TN=' + size(q.overload,/tname) + ',' + size(q.error,/tname) + ',' + $
   size(q.time,/tname) + ',' + size(q.particlecount,/tname) + ',' + size(q.image,/tname)
nsl = n_elements(q.image)/128
for k = 0, nsl - 1 do $
   print, 'SLICE=', k, ':', strjoin(strtrim(string(fix(q.image[*,k])),2)), $
      format='(A,I0,A,A)'
"""


def _script(path: str) -> str:
    lines = [f"openr, lun, '{path}', /get_lun"]
    for c in CASES:
        lines.append(_CASE_SCRIPT.format(pointer=POINTERS[c.frame], id=c.id,
                                         name=c.name))
    lines.append("free_lun, lun")
    return "\n".join(lines)


def _parse(stdout: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cur: dict | None = None
    keys = ("AFTER", "ERROR", "OVL", "PC", "TIME", "NSL")
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("CASE="):
            name, _, tail = line[5:].partition(" ")
            cur = {"SLICES": []}
            for tok in tail.split():
                k, _, v = tok.partition("=")
                if k in keys:
                    cur[k] = int(v)
            out[name] = cur
        elif line.startswith("TN=") and cur is not None:
            cur["TN"] = line[3:].strip()
        elif line.startswith("SLICE=") and cur is not None:
            cur["SLICES"].append(line.partition(":")[2].strip())
    return out


def main() -> int:
    write_fixture()
    script = _script(FIXTURE_RAW.resolve().as_posix())
    try:
        stdout, stderr = run_pro(script, timeout=60, extra_files={
            "hvps4_read_frame.pro": SHIM.read_text(encoding="utf-8"),
            "spec_decompress.pro": decompress_shim(),
        })
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2
    parsed = _parse(stdout)
    records = []
    required = ("AFTER", "ERROR", "OVL", "PC", "TIME", "NSL", "TN", "SLICES")
    for c in CASES:
        rec: dict = {"name": c.name, "frame": c.frame, "pointer": POINTERS[c.frame],
                     "id": c.id, "note": c.note,
                     "shim_derived": ["array", "res"],
                     "oracle_shims": [
                         "gdl_oracle/shims/hvps4_read_frame.pro (lines 39-40: "
                         "strmid for id.substring)",
                         "spec_decompress.pro +1 line (overload=overload[0])"]}
        vals = parsed.get(c.name)
        if vals is None or not all(k in vals for k in required):
            rec.update(status="ERROR", stdout=stdout[-1200:], stderr=stderr[-600:])
        else:
            rec.update(status="OK", **{k: vals[k] for k in required})
        print(c.name, rec["status"], {k: rec.get(k) for k in required[:-1]})
        records.append(rec)
    ok = sum(r["status"] == "OK" for r in records)
    if ok == 0:
        print("refusing to write a golden in which every case errored")
        print(stdout[-2000:], stderr[-1000:])
        return 1
    GOLDEN.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {GOLDEN} -- {len(records)} cases, {ok} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
