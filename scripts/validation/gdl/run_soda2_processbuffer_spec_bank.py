# SPDX-License-Identifier: BSD-3-Clause
r"""`soda2_processbuffer.pro` (`:264-747`, the
whole SPEC path) run **end to end, the real function, under GDL**, on the
three tracked SPEC fixtures (`s2_spec_raw_fixture`, `soda2_spec_frame_fixture`).

This bank extends the P-c/P-d bank: the tail (`:612-747`) is now
**asserted**, not merely recorded -- every `TAIL_*` field, `STREAK` and
`DIODETOTAL` are printed and parsed, and `op`/`misc` are parameterised so a
case can set `stuckbits`, `rakefix`, `keeplargest`, `dioderange`,
`greythresh` and `lastdhist`. A new shim, `dilate.pro` (`_DILATE_SHIM`,
imported from `run_soda2_label_blobs_bank.py`, the same way this bank
already imports `_erode_shim`), is needed for the `keeplargest` cases
(`label_blobs`'s `dilate=1`/`dilate=2` under GDL).

Unlike every earlier SPEC-decode bank, this one does not call one leaf `.pro` file --
it calls `soda2_processbuffer` itself (748 lines), with `pop`/`pmisc` built
as anonymous IDL structs from literals inside the script (`ptr_new({...})`).
The SPEC branch reads nothing from `buffer.image`; all image data comes
through LUN 1 opened on the fixture file (`spec_read_hk(1,...)`,
`spec_read_frame(1,...)` -- the literal unit number the source hard-codes).

**Three oracle shims**, none of them edits to `SODA2/`, passed through
`run_pro(..., extra_files=)`:

1. `spec_decompress.pro` +1 line -- `decompress_shim()`, already vendored for
   `run_soda2_spec_read_frame_bank.py` (GDL's `ISHFT` array quirk).
2. `erode.pro` -- `_erode_shim(ERODE_EDGE_RULE)`, already vendored for
   `run_soda2_aspect_ratio_bank.py` (needed by the tail's `soda2_findsize` ->
   `aspect_ratio.pro:13`).
3. `uniq.pro` -- new, `UNIQ_SHIM` below (`fillholes.pro:14`; GDL's own
   `uniq.pro` exists on disk but is not on `run_pro`'s search path).

Shims 2 and 3 exercise only the **shared tail** (`:612-747`), which this
plan does not port and does not assert -- the loop-level outputs this
bank's golden asserts are all computed before `:376`. The tail's own
outputs (`diam`, `xsize`, ... `dhist`, `numregions`) are recorded per case
(`TAIL_DIAM`, hex) as a starting golden for the tail's own pair, never
compared against a Python translation here.

Cases (all on tracked fixtures). Per U5, this run keeps the nine `s2_*`
cases plus `nimages0`, `all_dropped` and `frame_h_all18` -- twelve cases,
all expected `OK` except the two explicitly rejecting whole
buffers.

**Subformats 1 and 2 (HVPS-4 slice B, step 2; ``SUBFORMAT_CASES``).** The
same real ``soda2_processbuffer`` on whole buffers with ``op.subformat`` 1
(``spec_read_frame(..., version=1)``, ``:293``) and 2 (``hvps4_read_frame``,
``:294``), with ``pmisc.probetas`` set to 87.3, a value no HK record in either
fixture decodes, so the ``:287-288`` override ``hk.tas = probetas`` is measured
end to end in ``CLOCKTASHEX``. The frames are slice A's synthetic ones: the
version-1 pair in ``soda2_spec_frame_fixture`` (pointers 4266/4286,
``run_soda2_spec_read_frame_bank.py``) and the HVPS-4 frames in
``soda2_hvps4_frame_fixture`` (``run_soda2_hvps4_read_frame_bank.POINTERS``).
Subformat 2 needs slice A's oracle-path shim
``gdl_oracle/shims/hvps4_read_frame.pro`` (lines 39-40, ``strmid`` for IDL's
``id.substring``, which GDL 1.1.2 cannot run), so every subformat-2 record is
labelled ``"shim_derived": ["array", "res"]``; subformat-1 records reach no
new shim. These cases run in their own GDL invocation and write their own
golden, ``gdl_soda2_processbuffer_spec_subformat_golden.json``, so a halt in
one group cannot cost the other. Synthetic, layer 2 only.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_processbuffer_spec_bank.py [--only name,name]

``--only`` re-runs the named cases and merges them into the golden(s) they
belong to, keeping every other record.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, idl_double, run_pro  # noqa: E402
from run_soda2_aspect_ratio_bank import ERODE_EDGE_RULE, _erode_shim  # noqa: E402
from run_soda2_hvps4_read_frame_bank import POINTERS as HVPS4_POINTERS  # noqa: E402
from run_soda2_label_blobs_bank import _DILATE_SHIM  # noqa: E402
from run_soda2_spec_read_frame_bank import decompress_shim  # noqa: E402

DATA = Path(__file__).resolve().parents[3] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_processbuffer_spec_golden.json"
S2_FIXTURE = DATA / "s2_spec_raw_fixture"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"
HVPS4_FIXTURE = DATA / "soda2_hvps4_frame_fixture"
SUBFORMAT_GOLDEN = DATA / "gdl_soda2_processbuffer_spec_subformat_golden.json"
HVPS4_SHIM = Path(__file__).resolve().parent / "shims" / "hvps4_read_frame.pro"
FIXTURES = {"s2": S2_FIXTURE, "frame": FRAME_FIXTURE, "hvps4": HVPS4_FIXTURE}

#: `gdl_soda2_spec_index_golden.json`, case `s2_abs` (P-b) -- the s2
#: fixture's two image pointers.
S2_IMAGEP = [16, 4130]
S2_HKP = [8262, 8262]

#: `gdl_soda2_spec_read_frame_golden.json` -- every distinct pointer named
#: there against `soda2_spec_frame_fixture`, read independently as 'H'.
FRAME_IMAGEP = [16, 34, 54, 82, 104, 122, 136, 4098, 4138, 4156, 4194,
                4266, 4286, 8220]

#: GDL-oracle shim for `UNIQ` -- IDL's library routine (index of the last
#: element of each run of equal values). The portable GDL tree's own
#: `uniq.pro` is not on `run_pro`'s search path.
UNIQ_SHIM = """FUNCTION uniq, array, idx
   ; GDL-oracle shim: IDL's library UNIQ. The portable GDL tree's lib is not on the oracle path.
   IF n_elements(idx) gt 0 THEN a = array[idx] ELSE a = array
   n = n_elements(a)
   IF n le 1 THEN return, [0L]
   q = where(a ne shift(a, -1), c)
   IF c eq 0 THEN q = [n-1L]
   IF n_elements(idx) gt 0 THEN return, idx[q] ELSE return, q
END
"""


@dataclass
class Case:
    name: str
    fixture: str  # "s2" or "frame"
    probeid: str
    probetype: str = "2DS"
    dofreject: int = 0
    stretchcorrect: int = 0
    yres: float = 10.0
    res: float = 10.0
    imagepointers: list[int] = field(default_factory=lambda: list(S2_IMAGEP))
    hkpointers: list[int] = field(default_factory=lambda: list(S2_HKP))
    nimages: int | None = None
    aircrafttas: float = 100.0
    lastclock: float = 0.0
    lastbufftime: float = 0.0
    maxsfm: float = 0.0
    bufftime: float = 24243.25
    stuckbits: int = 0
    rakefix: int = 0
    keeplargest: int = 0
    dioderange: tuple[int, int] = (0, 127)
    greythresh: int = 0
    lastdhist: str = "lonarr(128)"  # literal IDL expression, evaluated before misc={}
    note: str = ""
    subformat: int = 0
    probetas: float = 0.0


CASES: list[Case] = [
    Case("s2_h_baseline", "s2", "H",
         note="the measured baseline; dropped V frame."),
    Case("s2_v", "s2", "V",
         note="frame at 16 dropped (H-only), 4130 kept."),
    Case("s2_hvps3", "s2", "H", probetype="HVPS3",
         note=":315-317 timetrunc substitution, rollover 65536."),
    Case("s2_rollover", "s2", "H", lastclock=70000.0,
         note=":320 x.time lt lastclock with rollovervalue 4294967295d."),
    Case("s2_hvps3_rollover", "s2", "H", probetype="HVPS3", lastclock=5.0,
         note=":320 with rollovervalue 65536."),
    Case("s2_sametime", "s2", "H", lastbufftime=24243.25, maxsfm=24240.5,
         note=":344, :362-365 forward count."),
    Case("s2_stretch", "s2", "H", stretchcorrect=1, aircrafttas=120.0,
         note=":307-308 stretch, recorded from the port only."),
    Case("s2_stretch_clamp", "s2", "H", stretchcorrect=1, aircrafttas=1000.0,
         note=":307-308 clamp < 10.0."),
    Case("s2_yres25", "s2", "H", yres=25.0,
         note=":309 float32 freq, non-power-of-two ratio."),
    Case("nimages0", "s2", "H", imagepointers=[0], hkpointers=[0], nimages=0,
         note=":267 nullbuffer; MISCHEX unchanged."),
    Case("all_dropped", "s2", "H", imagepointers=[4130], hkpointers=[8262],
         nimages=1,
         note=":338 nullbuffer after the loop (the s2 fixture's only "
              "V-array frame, dropped for probeid H); lastclock written "
              "at :326 unchanged."),
    Case("frame_h_all18", "frame", "H",
         imagepointers=list(FRAME_IMAGEP),
         hkpointers=[0] * len(FRAME_IMAGEP),
         note="multi-frame accumulation over the frame fixture's own "
              "pointers, hk all 0 (S4-l's live path)."),
    Case("frame_hvps3_sametime", "frame", "H", probetype="HVPS3",
         imagepointers=list(FRAME_IMAGEP), hkpointers=[0] * len(FRAME_IMAGEP),
         lastbufftime=24243.25, maxsfm=100.0, bufftime=24243.25,
         note=":344, :362-365 forward count over a multi-particle buffer "
              "(M3's discriminating case -- s2_sametime keeps only one "
              "particle, where the backward and forward formulas coincide)."),
    # Round 6-A (lane A) -- the shared tail (`:612-747`), asserted.
    Case("frame_h_all18_stuckbits", "frame", "H",
         imagepointers=list(FRAME_IMAGEP), hkpointers=[0] * len(FRAME_IMAGEP),
         stuckbits=1,
         note=":613-615 stuckbits=1, lastdhist all zeros -- S5-f, "
              "DIODETOTAL[120] should equal the baseline's [119]."),
    Case("frame_h_all18_stuckbits_hist", "frame", "H",
         imagepointers=list(FRAME_IMAGEP), hkpointers=[0] * len(FRAME_IMAGEP),
         stuckbits=1, lastdhist="h=lonarr(128) & h[40]=5000L & h",
         note=":613-615 stuckbits=1, lastdhist has a real spike at diode "
              "40 -- DIODETOTAL[40] should equal the baseline's [39]."),
    Case("frame_h_all18_keeplargest1", "frame", "H",
         imagepointers=list(FRAME_IMAGEP), hkpointers=[0] * len(FRAME_IMAGEP),
         keeplargest=1, note=":686-700 keeplargest=1, dilate=2."),
    Case("frame_h_all18_keeplargest2", "frame", "H",
         imagepointers=list(FRAME_IMAGEP), hkpointers=[0] * len(FRAME_IMAGEP),
         keeplargest=2, note=":686-700 keeplargest=2, dilate=1."),
    Case("frame_h_all18_keeplargest3", "frame", "H",
         imagepointers=list(FRAME_IMAGEP), hkpointers=[0] * len(FRAME_IMAGEP),
         keeplargest=3, note=":686-700 keeplargest=3, dilate=0, /all."),
    Case("frame_h_all18_dioderange00", "frame", "H",
         imagepointers=list(FRAME_IMAGEP), hkpointers=[0] * len(FRAME_IMAGEP),
         dioderange=(0, 0),
         note=":650-652 lp eq 0 -> numdiodes-1; must equal the baseline "
              "bit for bit."),
    Case("frame_h_all18_dioderange10_100", "frame", "H",
         imagepointers=list(FRAME_IMAGEP), hkpointers=[0] * len(FRAME_IMAGEP),
         dioderange=(10, 100),
         note=":650-652 ROI cropped to diodes 10..100."),
    Case("frame_overload_only", "frame", "H",
         imagepointers=[82], hkpointers=[0],
         note=":617-618, :707-709 an all-overload (empty-particle) buffer "
              "-- S5-g (streak on 0/0) and S5-h (diodegaps=1 on the "
              "empty ROI)."),
]

#: HVPS-4 slice B step 2 -- `:287-295` on whole buffers. `probetas` is
#: deliberately unequal to any HK TAS so `CLOCKTASHEX` shows the override.
SUBFORMAT_PROBETAS = 87.3
_H50_FRAMES = ["h50", "mtw", "overload", "high_counter"]
SUBFORMAT_CASES: list[Case] = [
    Case("sf2_hvps4_h50", "hvps4", "H50", probetype="HVPS4", subformat=2,
         yres=50.0, res=50.0, probetas=SUBFORMAT_PROBETAS,
         imagepointers=[HVPS4_POINTERS[n] for n in _H50_FRAMES],
         hkpointers=[0] * len(_H50_FRAMES),
         note=":294 hvps4_read_frame, :288 override; mtw is dropped at "
              ":296 (error=1); high_counter carries GDL's ishft(ULONG,32) "
              "(an oracle difference)."),
    Case("sf2_hvps4_v150_stretch", "hvps4", "V150", probetype="HVPS4",
         subformat=2, yres=150.0, res=150.0, probetas=SUBFORMAT_PROBETAS,
         stretchcorrect=1, aircrafttas=100.0,
         imagepointers=[HVPS4_POINTERS["v150"]], hkpointers=[0],
         note=":313 HVPS4@150 takes the 50 um clock; :288 override "
              "reaches :307 stretch."),
    Case("sf1_3vcpi_h50", "frame", "H", probetype="3VCPI", subformat=1,
         yres=50.0, res=50.0, probetas=SUBFORMAT_PROBETAS,
         imagepointers=[4266], hkpointers=[0],
         note=":293 version=1 reader (frame v1_h); :311 3VCPI@50 takes "
              "the 10 um clock."),
    Case("sf1_f2ds_v", "frame", "V", probetype="2DS", subformat=1,
         yres=10.0, res=10.0, probetas=SUBFORMAT_PROBETAS,
         imagepointers=[4286], hkpointers=[0],
         note="Fast 2D-S: :293 version=1 reader (frame v1_v) and :288, "
              "neither :311 nor :313."),
]


_CASE_SCRIPT = """
op = {{probetype:'{probetype}', subformat:{subformat}, probeid:'{probeid}', dofreject:{dofreject}, stretchcorrect:{stretchcorrect}, yres:{yres}, res:{res}, format:'SPEC', stuckbits:{stuckbits}, rakefix:{rakefix}, greythresh:{greythresh}, dioderange:[{dr0},{dr1}], numdiodes:128, keeplargest:{keeplargest}}}
{lastdhist_setup}
misc = {{nimages:{nimages}L, hkpointers:[{hkp}], imagepointers:[{imgp}], probetas:{probetas}, aircrafttas:{aircrafttas}, lastclock:{lastclock}, lastbufftime:{lastbufftime}, maxsfm:{maxsfm}, lastdhist:{lastdhist_expr}}}
pop = ptr_new(op) & pmisc = ptr_new(misc)
b = {{time:{bufftime}, tas:100.0, image:0}}
p = soda2_processbuffer(b, pop, pmisc)
print, 'CASE={name} REJECT=', p.rejectbuffer, format='(A,I0)'
IF p.rejectbuffer eq 0 THEN BEGIN
  print, 'STARTLINE=' + strjoin(strtrim(string(p.startline),2), ','), format='(A)'
  print, 'STOPLINE=' + strjoin(strtrim(string(p.stopline),2), ','), format='(A)'
  print, 'RAWTIME=' + strjoin(strtrim(string(p.rawtime),2), ','), format='(A)'
  print, 'PC=' + strjoin(strtrim(string(p.particlecounter),2), ','), format='(A)'
  print, 'OVL=' + strjoin(strtrim(string(fix(p.overloadflag)),2), ','), format='(A)'
  print, 'DOF=' + strjoin(strtrim(string(fix(p.dofflag)),2), ','), format='(A)'
  print, 'CLOCKTASHEX=' + strjoin(string(ulong(p.clocktas,0,n_elements(p.clocktas)), format='(Z08)'), ','), format='(A)'
  print, 'INTTIMEHEX=' + strjoin(string(ulong64(p.inttime,0,n_elements(p.inttime)), format='(Z016)'), ','), format='(A)'
  print, 'PROBETIMEHEX=' + strjoin(string(ulong64(p.probetime,0,n_elements(p.probetime)), format='(Z016)'), ','), format='(A)'
  print, 'REFTIMEHEX=', string(ulong64(p.reftime,0,1), format='(Z016)'), format='(A,A)'
  print, 'NSLICES=', p.nslices, ' BITDIM=', strjoin(strtrim(string(size(p.bitimage,/dim)),2), ','), format='(A,I0,A,A)'
  print, 'TAIL_DIAM=' + strjoin(string(ulong(p.diam,0,n_elements(p.diam)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_XSIZEHEX=' + strjoin(string(ulong(p.xsize,0,n_elements(p.xsize)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_YSIZEHEX=' + strjoin(string(ulong(p.ysize,0,n_elements(p.ysize)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_XEXTENTHEX=' + strjoin(string(ulong(p.xextent,0,n_elements(p.xextent)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_AREASIZEHEX=' + strjoin(string(ulong(p.areasize,0,n_elements(p.areasize)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_ONEDHEX=' + strjoin(string(ulong(p.oned,0,n_elements(p.oned)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_TWODHEX=' + strjoin(string(ulong(p.twod,0,n_elements(p.twod)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_ARHEX=' + strjoin(string(ulong(p.ar,0,n_elements(p.ar)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_ARFILLEDHEX=' + strjoin(string(ulong(p.arfilled,0,n_elements(p.arfilled)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_ASPRHEX=' + strjoin(string(ulong(p.aspr,0,n_elements(p.aspr)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_ZDHEX=' + strjoin(string(ulong(p.zd,0,n_elements(p.zd)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_SIZECORRHEX=' + strjoin(string(ulong(p.sizecorrection,0,n_elements(p.sizecorrection)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_XPOSHEX=' + strjoin(string(ulong(p.xpos,0,n_elements(p.xpos)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_YPOSHEX=' + strjoin(string(ulong(p.ypos,0,n_elements(p.ypos)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_ORIENTHEX=' + strjoin(string(ulong(p.orientation,0,n_elements(p.orientation)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_AREAORIGHEX=' + strjoin(string(ulong(p.area_orig,0,n_elements(p.area_orig)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_AREAFILLEDHEX=' + strjoin(string(ulong(p.area_filled,0,n_elements(p.area_filled)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_AREA75HEX=' + strjoin(string(ulong(p.area75,0,n_elements(p.area75)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_ALLIN=' + strjoin(strtrim(string(fix(p.allin)),2), ','), format='(A)'
  print, 'TAIL_CENTERIN=' + strjoin(strtrim(string(fix(p.centerin)),2), ','), format='(A)'
  print, 'TAIL_EDGETOUCH=' + strjoin(strtrim(string(fix(p.edgetouch)),2), ','), format='(A)'
  print, 'TAIL_NUMREGIONS=' + strjoin(strtrim(string(fix(p.numregions)),2), ','), format='(A)'
  print, 'TAIL_DIODEGAPS=' + strjoin(strtrim(string(fix(p.diodegaps)),2), ','), format='(A)'
  print, 'TAIL_PERIMHEX=' + strjoin(string(ulong(p.perimeterarea,0,n_elements(p.perimeterarea)), format='(Z08)'), ','), format='(A)'
  print, 'TAIL_DHIST=' + strjoin(strtrim(string(fix(p.dhist)),2), ','), format='(A)'
  print, 'STREAK=', p.streak, format='(A,I0)'
  print, 'DIODETOTAL=' + strjoin(strtrim(string(fix(total(p.bitimage,2))),2), ','), format='(A)'
  print, 'TAIL_TN=' + size(p.diam,/tname)+','+size(p.allin,/tname)+','+size(p.diodegaps,/tname)+','+size(p.dhist,/tname)+','+size(p.numregions,/tname)+','+size(p.perimeterarea,/tname)+','+size(p.streak,/tname), format='(A)'
  print, 'TN=' + size(p.startline,/tname)+','+size(p.rawtime,/tname)+','+size(p.inttime,/tname)+','+size(p.clocktas,/tname)+','+size(p.probetime,/tname)+','+size(p.dofflag,/tname)+','+size(p.particlecounter,/tname)+','+size(p.overloadflag,/tname), format='(A)'
ENDIF
print, 'MISCHEX=' + string(ulong64((*pmisc).lastclock,0,1), format='(Z016)') + ',' + string(ulong64((*pmisc).maxsfm,0,1), format='(Z016)') + ',' + string(ulong64((*pmisc).lastbufftime,0,1), format='(Z016)'), format='(A)'
ptr_free, pop & ptr_free, pmisc
"""


def _fmt(x: float) -> str:
    return idl_double(x)


def _script_for(case: Case) -> str:
    n = case.nimages if case.nimages is not None else len(case.imagepointers)
    if case.lastdhist == "lonarr(128)":
        lastdhist_setup = ""
        lastdhist_expr = "lonarr(128)"
    else:
        # a caller-supplied literal IDL statement sequence building `h`,
        # ending with the bare expression `h` -- see e.g.
        # "h=lonarr(128) & h[40]=5000L & h" for the spike case.
        *stmts, expr = case.lastdhist.split(" & ")
        lastdhist_setup = "\n".join(stmts)
        lastdhist_expr = expr
    return _CASE_SCRIPT.format(
        probetype=case.probetype, probeid=case.probeid,
        dofreject=case.dofreject, stretchcorrect=case.stretchcorrect,
        yres=case.yres, res=case.res, name=case.name, nimages=n,
        hkp=",".join(f"{v}LL" for v in case.hkpointers),
        imgp=",".join(f"{v}LL" for v in case.imagepointers),
        aircrafttas=case.aircrafttas, lastclock=_fmt(case.lastclock),
        lastbufftime=_fmt(case.lastbufftime), maxsfm=_fmt(case.maxsfm),
        bufftime=_fmt(case.bufftime),
        stuckbits=case.stuckbits, rakefix=case.rakefix,
        greythresh=case.greythresh, keeplargest=case.keeplargest,
        dr0=case.dioderange[0], dr1=case.dioderange[1],
        lastdhist_setup=lastdhist_setup, lastdhist_expr=lastdhist_expr,
        subformat=case.subformat, probetas=repr(float(case.probetas)),
    )


def _script_for_all(cases: list[Case]) -> str:
    """One `openr, 1` per fixture, in `FIXTURES` order (s2, frame, hvps4)."""
    lines = []
    for fixture, path in FIXTURES.items():
        sel = [c for c in cases if c.fixture == fixture]
        if not sel:
            continue
        lines.append(f"openr, 1, '{path.resolve().as_posix()}'")
        for c in sel:
            lines.append(_script_for(c))
        lines.append("close, 1")
    return "\n".join(lines)


def _parse(stdout: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("CASE="):
            rest = line[len("CASE="):]
            name, _, reject_str = rest.partition(" REJECT=")
            current = {"name": name, "REJECT": int(reject_str)}
            records[name] = current
        elif current is None:
            continue
        elif line.startswith("MISCHEX="):
            current["MISCHEX"] = line[len("MISCHEX="):].strip().split(",")
        elif line.startswith("NSLICES="):
            rest = line[len("NSLICES="):]
            nsl_str, _, bitdim = rest.partition(" BITDIM=")
            current["NSLICES"] = nsl_str.strip()
            current["BITDIM"] = bitdim.strip()
        elif "=" in line:
            key, _, val = line.partition("=")
            current[key] = val.strip()
    return records


_ARRAY_KEYS = ("STARTLINE", "STOPLINE", "RAWTIME", "PC", "OVL", "DOF")
_HEX_KEYS = ("CLOCKTASHEX", "INTTIMEHEX", "PROBETIMEHEX")
_TAIL_HEX_KEYS = (
    "TAIL_DIAM", "TAIL_XSIZEHEX", "TAIL_YSIZEHEX", "TAIL_XEXTENTHEX",
    "TAIL_AREASIZEHEX", "TAIL_ONEDHEX", "TAIL_TWODHEX", "TAIL_ARHEX",
    "TAIL_ARFILLEDHEX", "TAIL_ASPRHEX", "TAIL_ZDHEX", "TAIL_SIZECORRHEX",
    "TAIL_XPOSHEX", "TAIL_YPOSHEX", "TAIL_ORIENTHEX", "TAIL_AREAORIGHEX",
    "TAIL_AREAFILLEDHEX", "TAIL_AREA75HEX", "TAIL_PERIMHEX",
)
_TAIL_INT_KEYS = (
    "TAIL_ALLIN", "TAIL_CENTERIN", "TAIL_EDGETOUCH", "TAIL_NUMREGIONS",
    "TAIL_DIODEGAPS", "TAIL_DHIST", "DIODETOTAL",
)


def _record(case: Case, vals: dict[str, Any] | None, stdout: str,
            stderr: str) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "name": case.name, "fixture": case.fixture,
        "probeid": case.probeid, "probetype": case.probetype,
        "dofreject": case.dofreject,
        "stretchcorrect": case.stretchcorrect,
        "yres": case.yres, "res": case.res,
        "imagepointers": case.imagepointers,
        "hkpointers": case.hkpointers,
        "nimages": (case.nimages if case.nimages is not None
                    else len(case.imagepointers)),
        "aircrafttas": case.aircrafttas, "lastclock": case.lastclock,
        "lastbufftime": case.lastbufftime, "maxsfm": case.maxsfm,
        "bufftime": case.bufftime, "note": case.note,
        "stuckbits": case.stuckbits, "rakefix": case.rakefix,
        "keeplargest": case.keeplargest,
        "dioderange": list(case.dioderange),
        "greythresh": case.greythresh, "lastdhist": case.lastdhist,
    }
    if case.subformat != 0:
        rec["subformat"] = case.subformat
        rec["probetas"] = case.probetas
        rec["shim_derived"] = ["array", "res"] if case.subformat == 2 else []
    if vals is None or "REJECT" not in vals or "MISCHEX" not in vals:
        rec.update(status="ERROR", stdout=stdout[-1500:], stderr=stderr[-800:])
        print(f"{case.name}: ERROR")
        return rec
    rec["status"] = "OK"
    rec["REJECT"] = vals["REJECT"]
    rec["MISCHEX"] = vals["MISCHEX"]
    if vals["REJECT"] == 0:
        for k in _ARRAY_KEYS:
            rec[k] = [int(v) for v in vals[k].split(",")]
        for k in _HEX_KEYS:
            rec[k] = vals[k].split(",")
        rec["REFTIMEHEX"] = vals["REFTIMEHEX"]
        rec["NSLICES"] = int(vals["NSLICES"])
        rec["BITDIM"] = vals["BITDIM"]
        for k in _TAIL_HEX_KEYS:
            rec[k] = vals.get(k, "").split(",")
        for k in _TAIL_INT_KEYS:
            raw = vals.get(k, "")
            rec[k] = [int(v) for v in raw.split(",")] if raw else []
        rec["STREAK"] = int(vals["STREAK"]) if "STREAK" in vals else None
        rec["TAIL_TN"] = vals.get("TAIL_TN", "")
        rec["TN"] = vals["TN"]
    print(f"{case.name}: REJECT={vals['REJECT']}"
          + (f" INTTIME={rec.get('INTTIMEHEX')}" if vals["REJECT"] == 0 else ""))
    return rec


_MAIN_SHIMS = ["spec_decompress.pro (+1 line, ISHFT array quirk)",
               "erode.pro (ERODE_EDGE_RULE, tail only)",
               "uniq.pro (new, fillholes.pro:14, tail only)",
               "dilate.pro (keeplargest 1/2 only)"]
_SUBFORMAT_SHIMS = [*_MAIN_SHIMS,
                    "gdl_oracle/shims/hvps4_read_frame.pro (lines 39-40: strmid "
                    "for id.substring; subformat 2 only, array/res shim-derived)"]


def _run_group(cases: list[Case], golden: Path, shims: list[str],
               merge: bool) -> int:
    extra_files = {
        "spec_decompress.pro": decompress_shim(),
        "erode.pro": _erode_shim(ERODE_EDGE_RULE),
        "uniq.pro": UNIQ_SHIM,
        "dilate.pro": _DILATE_SHIM,
    }
    if any(c.subformat == 2 for c in cases):
        extra_files["hvps4_read_frame.pro"] = HVPS4_SHIM.read_text(encoding="utf-8")
    stdout, stderr = run_pro(_script_for_all(cases), timeout=180,
                             extra_files=extra_files)
    parsed = _parse(stdout)
    records = [_record(c, parsed.get(c.name), stdout, stderr) for c in cases]
    ok = sum(1 for r in records if r.get("status") == "OK")
    if ok == 0:
        print(f"refusing to write {golden.name}: every case errored")
        return 1
    if merge and golden.is_file():
        fresh = {r["name"]: r for r in records}
        old = [r for r in json.loads(golden.read_text(encoding="utf-8"))
               if "oracle_shims" not in r]
        records = [fresh.pop(r["name"], r) for r in old] + list(fresh.values())
    golden_out = [{"oracle_shims": shims}, *records]
    golden.write_text(json.dumps(golden_out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {golden} -- {len(records)} cases, {ok} OK this run")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default="",
                    help="comma-separated case names; merged into their golden")
    args = ap.parse_args(argv)
    only = {n for n in args.only.replace(" ", ",").split(",") if n}
    known = {c.name for c in CASES} | {c.name for c in SUBFORMAT_CASES}
    if only - known:
        print(f"unknown case(s): {sorted(only - known)}")
        return 2
    for path in FIXTURES.values():
        if not path.is_file():
            print(f"missing tracked fixture: {path}")
            return 2

    groups = [(CASES, GOLDEN, _MAIN_SHIMS),
              (SUBFORMAT_CASES, SUBFORMAT_GOLDEN, _SUBFORMAT_SHIMS)]
    rc = 0
    try:
        for cases, golden, shims in groups:
            sel = [c for c in cases if not only or c.name in only]
            if sel:
                rc = max(rc, _run_group(sel, golden, shims, merge=bool(only)))
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
