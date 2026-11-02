# SPDX-License-Identifier: BSD-3-Clause
# ruff: noqa: E501  (the GDL script literal is long by nature)
r"""Gap port, SEA CIP with two or more ``seatag`` entries, slice 1: the
GDL record-level golden for the CIP-1D record that ``process_cip1d_sea.pro``
reads under ``op.seatag[1]``.

Case ``cip1d_decode_one_record``: the unmodified ``readseabuffer_caps``
(``probetype='CIP1D'``, ``readseabuffer_caps.pro:26-28``, ``:40-41``) walked
over every tag-32000 record of the tracked synthetic fixture
``tests/data/soda2_sea_cip_fixture.sea`` (``make_soda2_sea_cip_fixture.py``,
which already writes a CIP-1D record beside each image record), keeping every
record field -- ``count`` (62), ``housekeeping`` (16), ``particlecounter``,
``secmsec``, ``hourmin`` -- and the buffer ``starttime`` / ``probetime``. The
existing ``run_soda2_cip_bank`` keeps only totals; this golden is what the
port's CIP-1D decode is asserted against.

Run from the repository root::

    .venv/Scripts/python.exe gdl_oracle/run_soda2_cip1d_sea_bank.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import run_pro  # noqa: E402
from run_soda2_cip_bank import FIXTURE, _plain, op_literal  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import _upstream  # noqa: E402
from scrub_paths import scrub_output  # noqa: E402

HERE = Path(__file__).resolve().parent
GOLDEN = HERE.parents[2] / "tests" / "data" / "gdl_soda2_cip1d_sea_golden.json"


def _script(fn: str, tmp: str) -> str:
    t = tmp.replace("\\", "/")
    return op_literal(fn) + f"""
openr, 2, op.fn[0]
c = 0L
st = dblarr(1000) & pt = dblarr(1000) & pcnt = lonarr(1000) & sm = lonarr(1000) & hm = lonarr(1000)
cnt = intarr(62, 1000) & hk = intarr(16, 1000)
REPEAT BEGIN
   a = readseabuffer_caps(2, probetype='CIP1D', tag=op.seatag[1])
   IF a.eof eq 0 THEN BEGIN
      st[c] = a.starttime & pt[c] = a.probetime & pcnt[c] = a.image.particlecounter
      sm[c] = a.image.secmsec & hm[c] = a.image.hourmin
      cnt[*, c] = a.image.count & hk[*, c] = a.image.housekeeping
      tn = size(a.image.count, /tname) + ',' + size(a.image.housekeeping, /tname) + ',' + size(a.image.particlecounter, /tname) + ',' + size(a.probetime, /tname) + ',' + size(a.starttime, /tname)
      c++
   ENDIF
ENDREP UNTIL (a.eof eq 1) or (c ge 1000)
close, 2
r = {{starttime:st[0:c-1], probetime:pt[0:c-1], particlecounter:pcnt[0:c-1], secmsec:sm[0:c-1], hourmin:hm[0:c-1], count:cnt[*, 0:c-1], housekeeping:hk[*, 0:c-1], tnames:tn}}
save, file='{t}/cip1d.sav', r
print, 'BANKDONE', c
"""


#: Slice 7: the unmodified ``process_cip1d_sea.pro`` over the same fixture.
#: Window 25800-25830 s (07:10:00-07:10:30); the fixture's buffer times are
#: 71005..71010, a zero stamp (read by the loop as the midnight crossing,
#: ``:84``, which ends it) and 71013.
def _script_process(fn: str, tmp: str) -> str:
    t = tmp.replace("\\", "/")
    lit = op_literal(fn, starttime=25800.0, stoptime=25830.0)
    return lit + f"""
process_cip1d_sea, op, /nowrite, data=data
save, file='{t}/process.sav', data
print, 'BANKDONE', n_elements(data.time)
"""


def run_process() -> dict:
    from scipy.io import readsav
    with tempfile.TemporaryDirectory() as tmp:
        out, err = run_pro(_script_process(FIXTURE.as_posix(), tmp), timeout=300)
        if "BANKDONE" not in out:
            raise RuntimeError(f"GDL did not finish:\n{out}\n{err}")
        d = readsav(os.path.join(tmp, "process.sav"))["data"]
        rec = {k: _plain(d[k]) for k in d.dtype.names if k.lower() != "op"}
    return rec


#: Edge case ``cip1d_decode_edge_records`` (SODA2_PORT_REVIEW_0400 section 3):
#: standalone records, not the shared fixture -- top bit set in hourmin and
#: secmsec, particlecounter above 32767 -- read into the verbatim `:26-28`
#: struct and decoded by the verbatim `:39-41` statements; plus `:18` and the
#: `:38` reset (``hhmmss gt 320000``) on standalone ``time`` arrays.
PRO = _upstream.source("soda2") / "readseabuffer_caps.pro"
EDGE_TIMES = [[2016, 9, 6, 32, 0, 0, 1, 1, 0], [2016, 9, 6, 31, 59, 59, 999, 1000, 0],
              [2016, 9, 6, 32, 0, 0, 0, 1, 0], [2016, 9, 6, 99, 0, 0, 0, 1, 0]]


def edge_payloads() -> list[bytes]:
    """Three 180-byte CIP-1D records with the high-bit fields under test."""
    import struct
    out = []
    for i, (pc, sm, hm) in enumerate([(32768, 0x8000 | (23 << 10) | 999, 0x8000 | (23 << 6) | 59),
                                      (65535, (63 << 10) | 1023, 0xFFFF),
                                      (40000, 0xFC00, 0xF800 | (7 << 6) | 3)]):
        p = bytearray(180)
        struct.pack_into("<3h", p, 0, 0x1E1E, 180, -1 - i)
        struct.pack_into("<62H", p, 6, *[(k * 2111 + i * 977) & 0xFFFF for k in range(62)])
        struct.pack_into("<2h", p, 130, -2, 32767)
        struct.pack_into("<16H", p, 134, *[(k * 4099 + 0x8000 * (k % 2)) & 0xFFFF for k in range(16)])
        struct.pack_into("<HHH", p, 166, pc, sm, hm)
        struct.pack_into("<4h", p, 172, 7, 1, -3, 0x1E1E)
        out.append(bytes(p))
    return out


def _script_edge(tmp: str) -> str:
    t = tmp.replace("\\", "/")
    lines = PRO.read_text(encoding="utf-8", errors="replace").splitlines()
    struct_stmt = "\n".join(lines[25:28])            # :26-28, verbatim
    decode_stmt = "\n".join(lines[38:41])            # :39-41, verbatim
    hh_stmt, reset_stmt = lines[17], lines[37]       # :18, :38, verbatim
    assert "particlecounter:0us" in struct_stmt and "ishft(image.hourmin" in decode_stmt
    assert "hhmmss = time[3]" in hh_stmt and "hhmmss gt 320000" in reset_stmt
    tl = ", ".join("[" + ", ".join(str(v) for v in r) + "]" for r in EDGE_TIMES)
    return f"""
probetype = 'CIP1D'
n = 3
pt = dblarr(n) & pcnt = lonarr(n) & sm = lonarr(n) & hm = lonarr(n)
cnt = intarr(62, n) & hk = intarr(16, n)
openr, 2, '{t}/edge.bin'
FOR i = 0, n-1 DO BEGIN
{struct_stmt}
   readu, 2, image
{decode_stmt}
   pt[i] = probetime & pcnt[i] = image.particlecounter & sm[i] = image.secmsec & hm[i] = image.hourmin
   cnt[*, i] = image.count & hk[*, i] = image.housekeeping
   tn = size(image.particlecounter, /tname) + ',' + size(image.secmsec, /tname) + ',' + size(probetime, /tname)
ENDFOR
close, 2
tt = fix([{tl}])
nt = {len(EDGE_TIMES)}
pre = dblarr(nt) & post = dblarr(nt)
FOR j = 0, nt-1 DO BEGIN
   time = tt[*, j]
{hh_stmt}
   pre[j] = hhmmss
{reset_stmt}
   post[j] = hhmmss
ENDFOR
r = {{probetime:pt, particlecounter:pcnt, secmsec:sm, hourmin:hm, count:cnt, housekeeping:hk, tnames:tn, hhmmss_pre:pre, hhmmss_post:post}}
save, file='{t}/edge.sav', r
print, 'BANKDONE', n
"""


def run_edge() -> dict:
    from scipy.io import readsav
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "edge.bin").write_bytes(b"".join(edge_payloads()))
        out, err = run_pro(_script_edge(tmp), timeout=300)
        if "BANKDONE" not in out:
            raise RuntimeError(f"GDL did not finish:\n{out}\n{err}")
        return _plain(readsav(os.path.join(tmp, "edge.sav"))["r"])


def run() -> dict:
    from scipy.io import readsav
    with tempfile.TemporaryDirectory() as tmp:
        out, err = run_pro(_script(FIXTURE.as_posix(), tmp), timeout=300)
        if "BANKDONE" not in out:
            raise RuntimeError(f"GDL did not finish:\n{out}\n{err}")
        rec = _plain(readsav(os.path.join(tmp, "cip1d.sav"))["r"])
    return {"cases": {"cip1d_decode_one_record": rec,
                      "process_cip1d_sea_window_25800_25830": run_process()},
            "source": "readseabuffer_caps.pro:26-28,:40-41 under GDL, tag 32000; "
                      "process_cip1d_sea.pro whole, /nowrite"}


def main() -> int:
    g = run()
    GOLDEN.write_text(json.dumps(g, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {GOLDEN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
