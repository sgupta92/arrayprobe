# SPDX-License-Identifier: BSD-3-Clause
r"""`fillholes.pro` under GDL, unmodified.

Hole-filling on a binary ROI, called from the shared per-particle tail at
`soda2_processbuffer.pro:714`; `area_filled = total(fillholes(roi))`
feeds `poisson_spot_correct` (`:716`) and `voidarea` (`:719`).

`fillholes.pro:9` calls `label_blobs(img xor 1b)` with no keywords (4-
connected `label_region` on the negative, BYTE-cast at
`label_blobs.pro:28`). Needs GDL's own `uniq.pro` (`fillholes.pro:14`),
which is on disk but not on `run_pro`'s search path -- imported, not
copied, from `run_soda2_processbuffer_spec_bank.UNIQ_SHIM` (that bank's own
docstring names the same need at `fillholes.pro:14`).

Images are built as `(roilen, ndiodes)`-shaped pixel lists in Python and
emitted in IDL orientation: `img = bytarr(ndiodes, roilen)` then one
`img[d, s] = 1b` per ON pixel (`d` diode, `s` slice).

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_fillholes_bank.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, run_pro  # noqa: E402
from run_soda2_processbuffer_spec_bank import UNIQ_SHIM  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[3] / "tests" / "data"
           / "gdl_soda2_fillholes_golden.json")

Pixel = tuple[int, int]  # (diode, slice)


def _full_block(ndiodes: int, nslices: int, holes: set[Pixel]) -> list[Pixel]:
    return [(d, s) for s in range(nslices) for d in range(ndiodes)
            if (d, s) not in holes]


def _ring(ndiodes: int, nslices: int, gap: Pixel | None = None,
          diagonal_gap: bool = False) -> list[Pixel]:
    pixels = []
    for s in range(nslices):
        for d in range(ndiodes):
            on_border = d in (0, ndiodes - 1) or s in (0, nslices - 1)
            if on_border:
                if diagonal_gap and d == 0 and s == 0:
                    continue
                if gap is not None and (d, s) == gap:
                    continue
                pixels.append((d, s))
    return pixels


def _many_holes(ndiodes: int, nslices: int, n_holes_target: int) -> list[Pixel]:
    """Solid block, ON everywhere except isolated single-pixel holes on a
    checkerboard-like lattice, none touching any edge, up to
    `n_holes_target` holes."""
    holes: set[Pixel] = set()
    for s in range(2, nslices - 2, 2):
        for d in range(2, ndiodes - 2, 2):
            if len(holes) >= n_holes_target:
                break
            holes.add((d, s))
        if len(holes) >= n_holes_target:
            break
    return _full_block(ndiodes, nslices, holes), len(holes)


CASES: dict[str, tuple[int, int, list[Pixel]]] = {}

# too_small_3_slices: 3 slices x 8 diodes with a hole -> `:8` early return.
CASES["too_small_3_slices"] = (8, 3, _full_block(8, 3, {(4, 1)}))
# too_small_3_diodes: 8 slices x 3 diodes.
CASES["too_small_3_diodes"] = (3, 8, _full_block(3, 8, {(1, 4)}))
# single_slice: 1 slice.
CASES["single_slice"] = (8, 1, [(d, 0) for d in range(8)])
# ring: 5x5 ring on a 7x7 zero field (centered).
CASES["ring"] = (7, 7, _ring(7, 7))
# ring_open: same ring, one gap.
CASES["ring_open"] = (7, 7, _ring(7, 7, gap=(3, 0)))
# diagonal_gap: ring missing one corner pixel.
CASES["diagonal_gap"] = (7, 7, _ring(7, 7, diagonal_gap=True))
# touching_edge: ring flush against slice 0 (shrink to 7 diodes x 6 slices,
# top row is the array's own edge).
_touch = [(d, s) for s in range(6) for d in range(7)
          if d in (0, 6) or s in (0, 5)]
# drop the s=0 row so the "ring" is flush against the array edge; the hole
# stays interior (rows 1..4), background above is edge-connected.
_touch = [(d, s) for (d, s) in _touch if s != 0] + [(d, 0) for d in (0, 6)]
CASES["touching_edge"] = (7, 6, sorted(set(_touch)))
# particle_on_all_edges: solid 7x7 block covering the whole ROI, one hole.
CASES["particle_on_all_edges"] = (7, 7, _full_block(7, 7, {(3, 3)}))
# two_holes: two separate holes in a solid interior.
CASES["two_holes"] = (9, 9, _full_block(9, 9, {(2, 2), (6, 6)}))
# no_particle: all zero.
CASES["no_particle"] = (6, 6, [])
# many_holes: 128 diodes x 24 slices, isolated holes > 255.
_mh_pixels, _mh_n = _many_holes(128, 24, 400)
CASES["many_holes"] = (128, 24, _mh_pixels)
# many_holes_255: same lattice trimmed to exactly 255 holes.
_mh255_pixels, _mh255_n = _many_holes(128, 24, 255)
CASES["many_holes_255"] = (128, 24, _mh255_pixels)


def _emit_script(ndiodes: int, nslices: int, pixels: list[Pixel]) -> str:
    assigns = "\n".join(f"img[{d},{s}] = 1b" for d, s in pixels)
    return f"""
img = bytarr({ndiodes}, {nslices})
{assigns}
out = fillholes(img)
sz = size(out)
IF sz[0] eq 2 THEN BEGIN
  print, 'OUT=' + strjoin(string(reform(out, n_elements(out)), format='(I0)'), ''), format='(A)'
  print, 'DIMS=' + strjoin(strtrim(string(size(out,/dim)),2), ','), format='(A)'
ENDIF ELSE BEGIN
  print, 'OUT=' + strjoin(string(out, format='(I0)'), ''), format='(A)'
  print, 'DIMS=' + strtrim(string(n_elements(out)),2), format='(A)'
ENDELSE
print, 'TNAME=' + size(out,/tname), format='(A)'
print, 'AREA_ORIG=', total(img), ' AREA_FILLED=', total(out), format='(A,F10.1,A,F10.1)'
lab = byte(label_blobs(img xor 1b))
print, 'NLAB=', max(label_blobs(img xor 1b, /integer)), ' MAXBYTE=', max(lab), format='(A,I0,A,I0)'
"""


def _parse(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        line = line.strip()
        for key in ("OUT=", "DIMS=", "TNAME="):
            if line.startswith(key):
                out[key.rstrip("=")] = line[len(key):].strip()
        if line.startswith("AREA_ORIG="):
            rest = line[len("AREA_ORIG="):]
            orig_part, _, filled_part = rest.partition("AREA_FILLED=")
            out["AREA_ORIG"] = orig_part.strip()
            out["AREA_FILLED"] = filled_part.strip()
        if line.startswith("NLAB="):
            rest = line[len("NLAB="):]
            nlab_part, _, maxb_part = rest.partition("MAXBYTE=")
            out["NLAB"] = nlab_part.strip()
            out["MAXBYTE"] = maxb_part.strip()
    return out


def main() -> int:
    extra_files = {"uniq.pro": UNIQ_SHIM}
    records = []
    try:
        for name, (ndiodes, nslices, pixels) in CASES.items():
            script = _emit_script(ndiodes, nslices, pixels)
            stdout, stderr = run_pro(script, timeout=120, extra_files=extra_files)
            vals = _parse(stdout)
            rec: dict = {
                "name": name, "ndiodes": ndiodes, "nslices": nslices,
                "n_pixels": len(pixels),
            }
            if not {"OUT", "DIMS", "TNAME", "AREA_ORIG", "AREA_FILLED"} <= set(vals):
                rec.update(status="ERROR", stdout=stdout[-600:], stderr=stderr[-800:])
                print(f"{name}: ERROR stderr={stderr[-200:]!r}")
            else:
                rec.update(status="OK", **vals, stderr=stderr[-400:])
                print(f"{name}: DIMS={vals['DIMS']} AREA_ORIG={vals['AREA_ORIG']} "
                      f"AREA_FILLED={vals['AREA_FILLED']} NLAB={vals.get('NLAB')} "
                      f"MAXBYTE={vals.get('MAXBYTE')}")
            records.append(rec)
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2

    ok = sum(1 for r in records if r["status"] == "OK")
    if ok == 0:
        print("refusing to write a golden in which every case errored")
        return 1
    FIXTURE.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    scrub_output(FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    print(f"\nwrote {FIXTURE} -- {len(records)} cases, {ok} OK "
          f"(many_holes target={_mh_n}, many_holes_255 target={_mh255_n})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
