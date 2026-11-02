# SPDX-License-Identifier: BSD-3-Clause
# ruff: noqa: E501  -- the GDL script lines are IDL source, kept one statement per line
r"""SODA-2 2DC (RAF ``.2d``): the real vendored ``soda2_processbuffer.pro`` run
under GDL on synthetic 32-diode ULONG buffers -- the
``(*pop).probetype eq '2DC'`` branch (``:80-127``) and the shared tail.

``pop`` is the F2DC bank's option set with probetype ``2DC``, numdiodes 32,
dioderange [0,31]; ``pmisc`` the same ``soda2_process_2d.pro:39`` literal
(``lastclock:0d``). The buffer struct carries ``stoptime`` so ``:82``/``:124``
can be read back from ``b`` after the call (IDL passes ``b`` by reference).

The branch sets ``restore_slice=1``, so each ROI goes through
``soda2_backfill.pro`` in the tail (ported, ``arrayprobe_soda2.backfill``). Every
particle's first recorded slice holds one shaded pixel, so ``soda2_backfill``
returns at its ``origtot lt 2`` guard and calls no ``erode``.
``tests/test_soda2_2dc_gdl.py`` compares the branch's locals and the tail's
``diam`` and ``areasize``.

Cases (synthetic, layer 2 only):

* ``A_raf`` -- four 0x55 (time, sync) pairs; RAF.
* ``A_sea`` -- the same bytes, format SEA (``:123-126``).
* ``B1``/``B2`` -- RAF back-to-back, **same pmisc**: ``B2``'s first inttime
  is from ``B1``'s ``lastclock`` (``:119-121``).
* ``C_fix`` -- no 0x55 words: five 0xFF000000 sync slices after plain
  timelines; ``fix2dimage`` rewrites four of them and the retry (``:86-91``) finds
  four particles.
* ``D_null`` -- two pairs and nothing ``fix2dimage`` can rewrite: nullbuffer.
* ``E_short`` -- 1000 slices: nullbuffer at ``:83``.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_2dc_bank.py
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
GOLDEN = DATA / "gdl_soda2_2dc_golden.json"

M32 = 0xFFFFFFFF
BLANK = M32


def _shadow(mask: int) -> int:
    return (~mask) & M32


def _particles(starts: list[int]) -> dict[int, int]:
    # first recorded slice: one pixel (soda2_backfill's origtot<2 guard);
    # then two slices of three pixels.
    s: dict[int, int] = {}
    for k, st in enumerate(starts):
        s[st + 1] = _shadow(1 << (10 + k))
        s[st + 2] = _shadow(0x7 << (9 + k))
        s[st + 3] = _shadow(0x7 << (9 + k))
    return s


def case_a(t0: int = 0) -> dict[int, int]:
    s = _particles([0, 21, 41, 61])
    for i, (k, t) in enumerate([(20, 300), (40, 500), (60, 700), (80, 900)]):
        s[k - 1] = 0x55000000 | (t + t0 + i)
        s[k] = 0x55000000 | 0xAAAA
    return s


def case_c() -> dict[int, int]:
    s = _particles([0, 11, 21, 41, 61])
    for t in (11, 21, 41, 61, 81):
        s[t - 1] = 0x00000400 + t      # plain timeline, top byte 0
        s[t] = 0xFF000000              # fix2dimage.pro:9 candidate
    return s


def case_d() -> dict[int, int]:
    s = _particles([0, 21])
    s[19], s[20] = 0x55000123, 0x55000000 | 0xAAAA
    s[39], s[40] = 0x55000456, 0x55000000 | 0xAAAA
    return s


# (name, format, slices, buffer time, fresh pmisc?, nslices, note)
SEQUENCE: list[tuple[str, str, dict[int, int], float, bool, int, str]] = [
    ("A_raf", "RAF", case_a(), 36000.0, True, 1024, "four 0x55 pairs"),
    ("A_sea", "SEA", case_a(), 36000.0, True, 1024, "same bytes, SEA override :123-126"),
    ("B1", "RAF", case_a(), 36000.0, True, 1024, "lastclock carry, buffer 1"),
    ("B2", "RAF", case_a(50), 36000.5, False, 1024, "lastclock carry, buffer 2"),
    ("C_fix", "RAF", case_c(), 36001.0, True, 1024, "fix2dimage retry :86-91"),
    ("D_null", "RAF", case_d(), 36002.0, True, 1024, "two pairs, unfixable: nullbuffer :93"),
    ("E_short", "RAF", case_a(), 36003.0, True, 1000, "1000 slices: nullbuffer :83"),
]

_OP = ("op = {{probetype:'2DC', subformat:0, probeid:'C1', format:'{fmt}', res:25.0, yres:25.0, "
       "armwidth:6.1, numdiodes:32, tau:0.051e-6, firstsliceskip:0, dofconst:3.0, "
       "wavelength:0.658e-6, dofreject:0, stretchcorrect:0, stuckbits:0, rakefix:0, "
       "greythresh:0, dioderange:[0,31], keeplargest:0, juelichfilter:0, strictcounter:0, "
       "timeoffset:0d, date:'03112024'}}\npop = ptr_new(op)")
_MISC = ("misc={f2d_remainder:ulon64arr(512), f2d_remainder_slices:0, lastbufftime:0D, "
         "aircrafttas:0.0, probetas:0.0, nimages:0, imagepointers:lon64arr(500), "
         "hkpointers:lon64arr(500), lastclock:0d, lastparticlecount:0L, maxsfm:0D, "
         "lastdhist:lonarr(op.numdiodes)}\npmisc=ptr_new(misc)")

_CALL = """
img = replicate('FFFFFFFF'xUL, {n})
{assign}
b = {{image:img, time:{time}d, stoptime:0d, tas:150.0}}
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
  print, 'OVERLOADFLAG=' + strjoin(strtrim(string(fix(p.overloadflag)),2), ','), format='(A)'
  print, 'MISSED=', long(p.missed), format='(A,I0)'
  print, 'NSLICES=', p.nslices, ' BITDIM=', strjoin(strtrim(string(size(p.bitimage,/dim)),2), ','), format='(A,I0,A,A)'
  print, 'DIODETOTAL=' + strjoin(strtrim(string(long(total(p.bitimage,2))),2), ','), format='(A)'
  print, 'SLICETOTAL=' + strjoin(strtrim(string(long(total(p.bitimage,1))),2), ','), format='(A)'
  print, 'TAIL_DIAM=' + strjoin(string(ulong(p.diam,0,n_elements(p.diam)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_AREASIZEHEX=' + strjoin(string(ulong(p.areasize,0,n_elements(p.areasize)), format='(Z08)'), ','), format='(A)'
  print, 'TN=' + size(p.startline,/tname)+','+size(p.rawtime,/tname)+','+size(p.probetime,/tname)+','+size(p.dofflag,/tname)+','+size(p.bitimage,/tname)+','+size(p.particlecounter,/tname), format='(A)'
ENDIF
print, 'LASTCLOCKHEX=', string(ulong64((*pmisc).lastclock,0,1), format='(Z016)'), format='(A,A)'
print, 'STOPTIMEHEX=', string(ulong64(b.stoptime,0,1), format='(Z016)'), format='(A,A)'
"""


def _assign(slices: dict[int, int]) -> str:
    return "\n".join(f"img[{i}] = {v}UL" for i, v in sorted(slices.items()))


def _script(seq: list) -> str:
    out: list[str] = []
    cur_fmt = None
    for name, fmt, slices, t, fresh, n, _note in seq:
        if fresh or fmt != cur_fmt:
            out.append(_OP.format(fmt=fmt))
            out.append(_MISC)
            cur_fmt = fmt
        out.append(_CALL.format(assign=_assign({k: v for k, v in slices.items() if k < n}),
                                time=repr(float(t)), name=name, n=n))
    return "\n".join(out)


_INTS = ("OVERLOADFLAG", "STARTLINE", "STOPLINE", "RAWTIME", "DOF", "PC", "DIODETOTAL",
         "SLICETOTAL")
_HEX = ("PROBETIMEHEX", "INTTIMEHEX", "CLOCKTASHEX", "TAIL_DIAM", "TAIL_AREASIZEHEX")


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
        elif "=" in line:
            k, _, v = line.partition("=")
            v = v.strip()
            if k in _INTS:
                cur[k] = [int(x) for x in v.split(",")]
            elif k in _HEX:
                cur[k] = v.split(",")
            elif k == "MISSED":
                cur[k] = int(v)
            else:
                cur[k] = v
    return recs


def main() -> int:
    extra = {"erode.pro": _erode_shim(ERODE_EDGE_RULE), "uniq.pro": UNIQ_SHIM,
             "dilate.pro": _DILATE_SHIM}
    try:
        so, se = run_pro(_script(SEQUENCE), timeout=300, extra_files=extra)
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2
    parsed = _parse(so)
    records = []
    for name, fmt, slices, t, fresh, n, note in SEQUENCE:
        rec: dict[str, Any] = {"name": name, "format": fmt, "buffer_time": t,
                               "fresh_pmisc": fresh, "nslices_buffer": n, "note": note,
                               "slices": {str(i): f"{v:08X}" for i, v in sorted(slices.items()) if i < n}}
        v = parsed.get(name)
        if v is None or "STOPTIMEHEX" not in v:
            rec.update(status="ERROR", stdout=so[-1500:], stderr=se[-1500:])
        else:
            rec["status"] = "OK"
            rec.update(v)
        print(f"{name}: {rec['status']} REJECT={rec.get('REJECT')}")
        records.append(rec)
    if not all(r["status"] == "OK" for r in records):
        print("refusing to write golden: a case errored")
        print(se[-3000:])
        return 1
    hdr = {"oracle_shims": ["erode.pro (tail only; not reached: soda2_backfill origtot<2)",
                            "uniq.pro (tail only)", "dilate.pro (tail only)"],
           "source": "SODA2/abansemer-soda2-afcea15/soda2_processbuffer.pro:80-127 + tail",
           "pmisc": "soda2_process_2d.pro:39-41"}
    GOLDEN.write_text(json.dumps([hdr, *records], indent=1) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN} -- {len(records)} records")
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
