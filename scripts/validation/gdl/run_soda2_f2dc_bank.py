# SPDX-License-Identifier: BSD-3-Clause
# ruff: noqa: E501  -- the GDL script lines are IDL source, kept one statement per line
r"""SODA-2 Fast-2DC (RAF ``.2d``): the real vendored
``soda2_processbuffer.pro`` run under GDL on synthetic F2DC buffers -- the
``(*pop).probetype eq 'F2DC' or 'F2DC_v2'`` branch (``:28-78``) and the
shared tail (``:612-747``).

``pop`` is the ``soda2_probespecs.pro:719-737`` entry "NCAR Fast-2DC_v2 [C4]
(25um)" (format RAF, subformat 3, probetype F2DC_v2, probeid C4, res 25,
yres 25, numdiodes 64, dioderange [0,63]) plus the processing options the
tail reads, all at their off values. ``pmisc`` is ``soda2_process_2d.pro:39``'s
literal (``f2d_remainder:ulon64arr(512)``, capacity 512). The F2DC branch reads
``buffer.image`` (uint64 slices, already byte-swapped), ``buffer.time`` and
``buffer.tas`` only.

Cases (synthetic, layer 2 only):

* ``A_v2`` -- syncs at 0, 10 (dof bit 44 set), 20; three particles.
* ``A_v1`` -- the same bytes as probetype ``F2DC`` (12 MHz, 40-bit mask).
* ``B1``/``B2`` -- Case A then a second buffer, **same pmisc**, so ``B2``
  consumes ``B1``'s 492-slice remainder (carry-over).
* ``C1``/``C2`` -- Case A then a 2-sync buffer: nullbuffer and
  ``f2d_remainder_slices`` cleared to 0 (``:40``).
* ``D`` -- syncs at 0, 10, 511: remainder of one (the blanked sync).
* ``E_dof`` -- every sync has the v2 dof bit: ``dofflag`` all 0 reaches the
  tail with ``dofreject=0``.
* ``F_overflow`` -- remainder 500 + syncs at 0,1,2 of the new buffer: ``:73``
  writes ``bufflength - 500 = 512`` slices... run in its own GDL call because
  IDL is expected to halt (out-of-range subscript) when ``nremainder > 512``.
  Construction: F1 leaves a 500-slice remainder; ``F2_PRE`` plants three syncs
  in that carried remainder's slices 0-2 and F2's own buffer has none, so
  ``max(sync_ind)=2`` and ``nremainder=1012-2=1010``. GDL halts at ``:73``
  (status ERROR); the port raises ``IndexError`` naming ``:73``.

Answers the bank settles: (a) the F2DC branch sets no ``overload``; the tail's
read is guarded at ``:648`` by ``n_elements``, so ``overloadflag`` is zeros
for F2DC. (b) ``:58``'s ``stopline > startline`` on unequal lengths is
truncated by GDL to the shorter operand (NSTART 4, NSTOP 3).
``tests/test_soda2_f2dc_gdl_golden.py`` matches all ten records exactly.

Each case prints the loop-level fields, the tail's ``diam/xsize/ysize/
areasize`` (hex), per-diode totals of ``bitimage`` (pins the
``dec2bin64`` column order) and the ``f2d_remainder`` state after the call.

Shims: the spec bank's ``erode.pro``, ``uniq.pro`` and ``dilate.pro`` (tail
only); none of them edits ``SODA2/``.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_f2dc_bank.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, run_pro  # noqa: E402
from run_soda2_aspect_ratio_bank import ERODE_EDGE_RULE, _erode_shim  # noqa: E402
from run_soda2_label_blobs_bank import _DILATE_SHIM  # noqa: E402
from run_soda2_processbuffer_spec_bank import UNIQ_SHIM  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

DATA = Path(__file__).resolve().parents[3] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_f2dc_golden.json"

M64 = (1 << 64) - 1
SYNC = 0xAAAA000000000000
DOF2 = 0x0000100000000000
BLANK = M64


def _shadow(mask: int) -> int:
    return (~mask) & M64


def case_a() -> dict[int, int]:
    s = {0: SYNC | 1000, 10: SYNC | DOF2 | 2000, 20: SYNC | 3000}
    for i in (1, 2, 3):
        s[i] = _shadow(0x7 << 30)
    for i in (11, 12):
        s[i] = _shadow(0x1 << 20)
    return s


def case_b2() -> dict[int, int]:
    s = {i: _shadow(0x3 << 40) for i in range(5)}
    s.update({5: SYNC | 4000, 30: SYNC | 5000, 100: SYNC | 6000})
    s[31] = _shadow(0xF << 10)
    return s


def case_c2() -> dict[int, int]:
    return {3: SYNC | 7000, 4: _shadow(1 << 5), 40: SYNC | 8000}


def case_d() -> dict[int, int]:
    s = case_a()
    del s[20]
    s[511] = SYNC | 3000
    return s


def case_e() -> dict[int, int]:
    s = case_a()
    for k in (0, 10, 20):
        s[k] |= DOF2
    return s


def case_f2() -> dict[int, int]:
    # No sync in the new buffer: the only syncs are planted in the carried
    # remainder's first three slices (F2_PRE), so max(sync_ind) = 2 and
    # nremainder = (500 + 512) - 2 = 1010 > 512 at :73.
    return {}


# Planted before F2's call, mirroring the Python S2 test: the remainder's
# first three slices become syncs (remainder slice 0 is the blanked sync).
F2_PRE = ("(*pmisc).f2d_remainder[0:2] = [" + ", ".join(
    f"{SYNC | t}ULL" for t in (100, 200, 300)) + "]")


def case_f1() -> dict[int, int]:
    # syncs at 0, 1, 12 -> remainder 512-12 = 500 slices for F2.
    s = {0: SYNC | 10, 1: SYNC | 20, 12: SYNC | 30}
    s[5] = _shadow(1 << 63)
    return s


# (case name, probetype, slice dict, buffer time, fresh pmisc?)
SEQUENCE: list[tuple[str, str, dict[int, int], float, bool, str]] = [
    ("A_v2", "F2DC_v2", case_a(), 18000.0, True, "plan Case A"),
    ("A_v1", "F2DC", case_a(), 18000.0, True, "Case A bytes, v1 masks/clock"),
    ("B1", "F2DC_v2", case_a(), 18000.0, True, "carry-over, buffer 1"),
    ("B2", "F2DC_v2", case_b2(), 18001.0, False, "carry-over, buffer 2 (B1's remainder)"),
    ("C1", "F2DC_v2", case_a(), 18000.0, True, "state clear, buffer 1"),
    ("C2", "F2DC_v2", case_c2(), 18001.0, False, "2 syncs -> nullbuffer, remainder cleared"),
    ("D", "F2DC_v2", case_d(), 18000.0, True, "last sync at 511 -> remainder 1"),
    ("E_dof", "F2DC_v2", case_e(), 18000.0, True, "all dof bits set, dofreject 0"),
]
OVERFLOW: list[tuple[str, str, dict[int, int], float, bool, str]] = [
    ("F1", "F2DC_v2", case_f1(), 18000.0, True, "remainder 500 for F2"),
    ("F2", "F2DC_v2", case_f2(), 18001.0, False,
     "syncs planted in the 500-slice remainder's slices 0-2, none in the buffer: nremainder 1010 > 512 at :73"),
]

_OP = ("op = {{probetype:'{pt}', subformat:3, probeid:'C4', format:'RAF', res:25.0, yres:25.0, "
       "armwidth:6.1, numdiodes:64, tau:0.051e-6, firstsliceskip:0, dofconst:3.0, "
       "wavelength:0.658e-6, dofreject:0, stretchcorrect:0, stuckbits:0, rakefix:0, "
       "greythresh:0, dioderange:[0,63], keeplargest:0, juelichfilter:0, strictcounter:0, "
       "timeoffset:0d, date:'03112024'}}\npop = ptr_new(op)")
_MISC = ("misc={f2d_remainder:ulon64arr(512), f2d_remainder_slices:0, lastbufftime:0D, "
         "aircrafttas:0.0, probetas:0.0, nimages:0, imagepointers:lon64arr(500), "
         "hkpointers:lon64arr(500), lastclock:0d, lastparticlecount:0L, maxsfm:0D, "
         "lastdhist:lonarr(op.numdiodes)}\npmisc=ptr_new(misc)")

_CALL = """
img = replicate('FFFFFFFFFFFFFFFF'xULL, 512)
{assign}
b = {{image:img, time:{time}d, tas:150.0}}
p = soda2_processbuffer(b, pop, pmisc)
print, 'CASE={name} REJECT=', p.rejectbuffer, format='(A,I0)'
IF p.rejectbuffer eq 0 THEN BEGIN
  print, 'STARTLINE=' + strjoin(strtrim(string(p.startline),2), ','), format='(A)'
  print, 'STOPLINE=' + strjoin(strtrim(string(p.stopline),2), ','), format='(A)'
  print, 'RAWTIME=' + strjoin(strtrim(string(p.rawtime),2), ','), format='(A)'
  print, 'DOF=' + strjoin(strtrim(string(fix(p.dofflag)),2), ','), format='(A)'
  print, 'PC=' + strjoin(strtrim(string(p.particlecounter),2), ','), format='(A)'
  print, 'PROBETIMEHEX=' + strjoin(string(ulong64(p.probetime,0,n_elements(p.probetime)), format='(Z016)'), ','), format='(A)'
  print, 'REFTIMEHEX=', string(ulong64(p.reftime,0,1), format='(Z016)'), format='(A,A)'
  print, 'INTTIMEHEX=' + strjoin(string(ulong64(p.inttime,0,n_elements(p.inttime)), format='(Z016)'), ','), format='(A)'
  print, 'CLOCKTASHEX=' + strjoin(string(ulong(p.clocktas,0,n_elements(p.clocktas)), format='(Z08)'), ','), format='(A)'
  print, 'NSLICES=', p.nslices, ' BITDIM=', strjoin(strtrim(string(size(p.bitimage,/dim)),2), ','), format='(A,I0,A,A)'
  print, 'TAIL_DIAM=' + strjoin(string(ulong(p.diam,0,n_elements(p.diam)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_XSIZEHEX=' + strjoin(string(ulong(p.xsize,0,n_elements(p.xsize)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_YSIZEHEX=' + strjoin(string(ulong(p.ysize,0,n_elements(p.ysize)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_AREASIZEHEX=' + strjoin(string(ulong(p.areasize,0,n_elements(p.areasize)), format='(Z08)'), ','), format='(A)'
  print, 'OVERLOADFLAG=' + strjoin(strtrim(string(fix(p.overloadflag)),2), ','), format='(A)'
  print, 'NSTART=', n_elements(p.startline), ' NSTOP=', n_elements(p.stopline), format='(A,I0,A,I0)'
  print, 'TAIL_ALLIN=' + strjoin(strtrim(string(fix(p.allin)),2), ','), format='(A)'
  print, 'DIODETOTAL=' + strjoin(strtrim(string(long(total(p.bitimage,2))),2), ','), format='(A)'
  print, 'TN=' + size(p.startline,/tname)+','+size(p.rawtime,/tname)+','+size(p.probetime,/tname)+','+size(p.dofflag,/tname)+','+size(p.bitimage,/tname), format='(A)'
ENDIF
n = (*pmisc).f2d_remainder_slices
print, 'REMN=', n, format='(A,I0)'
IF n gt 0 THEN print, 'REMHEAD=' + strjoin(string((*pmisc).f2d_remainder[0:(n<8)-1], format='(Z016)'), ','), format='(A)'
IF n gt 0 THEN print, 'REMNONBLANK=', long(total((*pmisc).f2d_remainder[0:n-1] ne 'FFFFFFFFFFFFFFFF'xULL)), format='(A,I0)'
print, 'LASTBUFFTIMEHEX=', string(ulong64((*pmisc).lastbufftime,0,1), format='(Z016)'), format='(A,A)'
"""


def _assign(slices: dict[int, int]) -> str:
    if not slices:
        return ""
    return "\n".join(f"img[{i}] = {v}ULL" for i, v in sorted(slices.items()))


def _script(seq: list) -> str:
    out: list[str] = []
    cur_pt = None
    for name, pt, slices, t, fresh, _note in seq:
        if fresh or pt != cur_pt:
            out.append(_OP.format(pt=pt))
            out.append(_MISC)
            cur_pt = pt
        if name == "F2":
            out.append(F2_PRE)
        out.append(_CALL.format(assign=_assign(slices), time=repr(float(t)), name=name))
    return "\n".join(out)


def _parse(stdout: str) -> dict[str, dict[str, Any]]:
    recs: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("CASE="):
            name, _, rej = line[5:].partition(" REJECT=")
            cur = {"REJECT": int(rej)}
            recs[name] = cur
        elif cur is None:
            continue
        elif line.startswith("NSLICES="):
            a, _, b = line[8:].partition(" BITDIM=")
            cur["NSLICES"] = int(a)
            cur["BITDIM"] = b.strip()
        elif line.startswith("NSTART="):
            a, _, b = line[7:].partition(" NSTOP=")
            cur["NSTART"] = int(a)
            cur["NSTOP"] = int(b)
        elif "=" in line:
            k, _, v = line.partition("=")
            cur[k] = v.strip()
    return recs


_INTS = ("OVERLOADFLAG", "STARTLINE", "STOPLINE", "RAWTIME", "DOF", "PC", "TAIL_ALLIN", "DIODETOTAL")
_HEX = ("PROBETIMEHEX", "INTTIMEHEX", "CLOCKTASHEX", "TAIL_DIAM", "TAIL_XSIZEHEX",
        "TAIL_YSIZEHEX", "TAIL_AREASIZEHEX", "REMHEAD")


def _records(seq: list, stdout: str, stderr: str) -> list[dict[str, Any]]:
    parsed = _parse(stdout)
    out = []
    for name, pt, slices, t, fresh, note in seq:
        rec: dict[str, Any] = {
            "name": name, "probetype": pt, "buffer_time": t,
            "fresh_pmisc": fresh, "note": note,
            "slices": {str(i): f"{v:016X}" for i, v in sorted(slices.items())},
        }
        v = parsed.get(name)
        if v is None or "REMN" not in v:
            rec.update(status="ERROR", stdout=stdout[-1500:], stderr=stderr[-1500:])
        else:
            rec["status"] = "OK"
            for k, val in v.items():
                if k in _INTS:
                    rec[k] = [int(x) for x in val.split(",")]
                elif k in _HEX:
                    rec[k] = val.split(",")
                elif k in ("REMN", "REMNONBLANK"):
                    rec[k] = int(val)
                else:
                    rec[k] = val
        print(f"{name}: {rec['status']} REJECT={rec.get('REJECT')} REMN={rec.get('REMN')}")
        out.append(rec)
    return out


def main() -> int:
    extra = {"erode.pro": _erode_shim(ERODE_EDGE_RULE), "uniq.pro": UNIQ_SHIM,
             "dilate.pro": _DILATE_SHIM}
    try:
        so, se = run_pro(_script(SEQUENCE), timeout=300, extra_files=extra)
        records = _records(SEQUENCE, so, se)
        so2, se2 = run_pro(_script(OVERFLOW), timeout=300, extra_files=extra)
        records += _records(OVERFLOW, so2, se2)
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2
    if not any(r["status"] == "OK" for r in records):
        print("refusing to write golden: every case errored")
        return 1
    hdr = {"oracle_shims": ["erode.pro (tail only)", "uniq.pro (tail only)",
                            "dilate.pro (tail only)"],
           "source": "SODA2/abansemer-soda2-afcea15/soda2_processbuffer.pro:28-78 + :612-747",
           "pop": "soda2_probespecs.pro:719-737 Fast-2DC_v2 [C4]",
           "pmisc": "soda2_process_2d.pro:39-41"}
    GOLDEN.write_text(json.dumps([hdr, *records], indent=1) + "\n", encoding="utf-8")
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {GOLDEN} -- {len(records)} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
