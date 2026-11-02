# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2: ``label_blobs.pro`` under GDL. GDL 1.1.2 has
``LABEL_REGION`` (including ``/ALL_NEIGHBORS``) but lacks ``DILATE`` --
measured: ``Attempt to call undefined function: DILATE``. So
``dilatelength=0`` cases (F1) run **unmodified** (doctrine layer 2);
``dilatelength != 0`` cases (F2) supply a ``dilate.pro`` shim via
``locate.run_pro``'s ``extra_files`` -- a square all-ones kernel, origin
centred, out-of-range reads as 0. Unambiguous here (not layer-3-uncertain
like ``aspect_ratio``'s erosion shim): ``label_blobs.pro:16-17`` always
pads ``temp`` by at least ``dilatelength`` on every side before dilating,
and the kernel radius is ``dilatelength`` (``kerneldim <= 2*dilatelength+1``),
so dilation never reaches ``temp``'s own border -- no shim assumption
about that border is ever exercised.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_label_blobs_bank.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, run_pro  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[3] / "tests" / "data"
           / "gdl_soda2_label_blobs_golden.json")

_DILATE_SHIM = """
; shim for GDL 1.1.2, which lacks DILATE (measured: "Attempt to call
; undefined function: DILATE"). Square all-ones kernel, origin centred,
; out-of-range reads as 0b -- see the SODA-2 port design notes' label_blobs
; section: unambiguous here, dilation never reaches temp's own border.
FUNCTION dilate, img, kernel
  s = size(img)
  nx = s[1]
  ny = s[2]
  ks = size(kernel)
  kdim = ks[1]
  r = kdim / 2
  out = bytarr(nx, ny)
  FOR y=0L, ny-1 DO BEGIN
    FOR x=0L, nx-1 DO BEGIN
      IF img[x,y] eq 0 THEN CONTINUE
      x0 = (x-r) > 0
      x1 = (x+r) < (nx-1)
      y0 = (y-r) > 0
      y1 = (y+r) < (ny-1)
      out[x0:x1, y0:y1] = 1b
    ENDFOR
  ENDFOR
  return, out
END
"""


class Case:
    __slots__ = ("name", "family", "img", "dilatelength", "all_neighbors", "integer")

    def __init__(self, name, family, img, dilatelength=0, all_neighbors=False,
                 integer=False):
        self.name = name
        self.family = family
        self.img = img  # rows = diodes (axis0/x), cols = slices (axis1/y)
        self.dilatelength = dilatelength
        self.all_neighbors = all_neighbors
        self.integer = integer


def build_cases() -> list[Case]:
    cases: list[Case] = []

    def rect(nx, ny, on=()):
        img = [[0] * ny for _ in range(nx)]
        for (x, y) in on:
            img[x][y] = 1
        return img

    # F1: dilatelength=0 -----------------------------------------------------
    cases.append(Case("two_blobs_4conn", "F1", rect(6, 3, [(0, 0), (0, 1), (4, 1), (4, 2)])))
    # diagonal touch only: 2 blobs w/o /all, 1 with /all
    diag = rect(3, 3, [(0, 0), (1, 1), (2, 2)])
    cases.append(Case("diagonal_only_4conn", "F1", diag))
    cases.append(Case("diagonal_only_8conn", "F1", diag, all_neighbors=True))
    # raster order: first pixel at x=5,y=0; another blob at x=0,y=1
    raster = rect(6, 2, [(5, 0), (0, 1)])
    cases.append(Case("raster_order", "F1", raster))
    # edge pixels on all four borders
    edge = rect(4, 4, [(0, 0), (3, 0), (0, 3), (3, 3), (1, 0), (0, 1)])
    cases.append(Case("edge_pixels_kept", "F1", edge))
    # 1-D input
    cases.append(Case("one_d_input", "F1", [0, 1, 1, 0, 1]))
    # grey values clamped: use INT image w/ 2s and 3s
    grey = rect(4, 2, [(0, 0), (1, 0), (2, 1), (3, 1)])
    grey_int = [[2 if v else 0 for v in row] for row in grey]
    grey_int[2][1] = 3
    cases.append(Case("grey_values_clamped", "F1", grey_int))
    # >255 blobs wrapping byte return: 17x17 grid, isolated single pixels
    # at every even (x,y) -> 81 blobs (kept modest so GDL runtime stays
    # reasonable; the wrap property (S4-y) is checked port-side with a
    # synthetic >255-blob case that needs no GDL run, see the test module).
    wrap_pts = [(x, y) for x in range(0, 17, 2) for y in range(0, 17, 2)]
    cases.append(Case("wrap_moderate_blobs", "F1", rect(17, 17, wrap_pts)))
    cases.append(Case("wrap_moderate_blobs_int", "F1", rect(17, 17, wrap_pts), integer=True))
    cases.append(Case("hail_int_0", "F1", rect(3, 3, [(1, 1)]), integer=True))

    # F2: dilatelength != 0 (needs the dilate shim) --------------------------
    # a gap of 2 empty diodes bridges even under dilate=1 (radius 1 covers
    # it from both sides) -- measured, not assumed; kept as a boundary case
    gap2 = rect(9, 1, [(0, 0), (3, 0)])  # gap of 2 empty diodes (indices 1,2)
    cases.append(Case("dilate1_gap2_merges", "F2", gap2, dilatelength=1))
    cases.append(Case("dilate2_gap2_merges", "F2", gap2, dilatelength=2))
    # kernel clamps against s[1]+2 for a 1-slice roi: dilate=2 on a
    # single-slice image should behave like dilate=1 (3-wide kernel, not 5)
    gap3 = rect(10, 1, [(0, 0), (4, 0)])  # gap of 3 (indices 1,2,3)
    cases.append(Case("dilate2_one_slice_gap3_stays_separate", "F2", gap3, dilatelength=2))
    # a 3-slice roi with the same gap DOES merge (kernel isn't clamped)
    gap3_3slice = rect(10, 3, [(0, 0), (0, 1), (0, 2), (4, 0), (4, 1), (4, 2)])
    cases.append(Case("dilate2_three_slice_gap3_merges", "F2", gap3_3slice, dilatelength=2))
    cases.append(Case("hail_dilate1_int", "F2", rect(5, 1, [(0, 0), (2, 0)]),
                       dilatelength=1, integer=True))

    return cases


def _call_script(case: Case) -> str:
    lines: list[str] = []
    one_d = not isinstance(case.img[0], list)
    if one_d:
        n = len(case.img)
        lines.append(f"img = bytarr({n})")
        for x, v in enumerate(case.img):
            if v:
                lines.append(f"img[{x}] = 1b")
    else:
        nx = len(case.img)
        ny = len(case.img[0])
        # grey_values_clamped uses ints up to 3, so allocate intarr
        needs_int = any(v > 1 for row in case.img for v in row)
        arrtype = "intarr" if needs_int else "bytarr"
        lines.append(f"img = {arrtype}({nx}, {ny})")
        for x, row in enumerate(case.img):
            for y, v in enumerate(row):
                if v:
                    suffix = "" if needs_int else "b"
                    lines.append(f"img[{x}, {y}] = {v}{suffix}")

    kw = []
    if case.dilatelength:
        kw.append(f"dilatelength={case.dilatelength}")
    if case.all_neighbors:
        kw.append("/all")
    if case.integer:
        kw.append("/integer")
    kwstr = (", " + ", ".join(kw)) if kw else ""
    lines.append(f"r = label_blobs(img{kwstr})")
    lines.append("s = size(r)")
    lines.append("print, 'NDIM=', s[0], format='(A,I0)'")
    lines.append("nmax = max(r)")
    lines.append("print, 'MAX=', nmax, format='(A,I0)'")
    fmt = "'(A,' + strtrim(n_elements(r),2) + '(1X,I0))'"
    lines.append(f"fmt_r = {fmt}")
    lines.append("print, 'FLAT=', long(reform(r, n_elements(r))), format=fmt_r")
    return "\n".join(lines)


def _parse_scalar_int(stdout: str, key: str) -> int | None:
    prefix = f"{key}="
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return int(line[len(prefix):].strip())
    return None


def _parse_int_list(stdout: str, key: str) -> list[int] | None:
    prefix = f"{key}="
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return [int(v) for v in line[len(prefix):].split()]
    return None


def _run_case(case: Case) -> dict[str, Any]:
    script = _call_script(case)
    extra_files = {"dilate.pro": _DILATE_SHIM} if case.dilatelength else None
    stdout, stderr = run_pro(script, extra_files=extra_files)

    rec: dict[str, Any] = {
        "name": case.name, "family": case.family, "img": case.img,
        "dilatelength": case.dilatelength, "all_neighbors": case.all_neighbors,
        "integer": case.integer,
        "dilate_source": "shim" if extra_files else "n/a",
    }
    ndim = _parse_scalar_int(stdout, "NDIM")
    flat = _parse_int_list(stdout, "FLAT")
    nmax = _parse_scalar_int(stdout, "MAX")
    if flat is None:
        rec.update(status="ERROR", stdout=stdout[-800:], stderr=stderr[-800:])
        return rec
    rec.update(status="OK", NDIM=ndim, FLAT=flat, MAX=nmax)
    return rec


def main() -> int:
    records: list[dict[str, Any]] = []
    try:
        for case in build_cases():
            rec = _run_case(case)
            print(f"{case.name} [{case.family}]: {rec.get('status')}")
            records.append(rec)
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2

    ok = sum(1 for r in records if r.get("status") == "OK")
    if ok == 0:
        print("refusing to write a golden in which every case errored")
        return 1
    FIXTURE.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    scrub_output(FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    print(f"\nwrote {FIXTURE} -- {len(records)} records, {ok} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
