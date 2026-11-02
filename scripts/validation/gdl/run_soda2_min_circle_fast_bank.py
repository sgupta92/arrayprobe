# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2 geometry chain: ``min_circle_fast.pro`` under GDL, unmodified.

The golden is real output from ``min_circle_fast.pro`` (which calls
``find_angle``, ``find_angle_array`` and ``find_radius`` -- all three already
GDL-validated leaves, see ``run_soda2_angles_bank.py`` /
``run_soda2_find_radius_bank.py``) run through GDL exactly as SODA-2 ships it.

**The headline fact this bank exists to exercise**: ``!pi`` is IDL's *single*
precision pi (``3.1415927410125732``), not ``!dpi``
(``3.1415926535897931``). ``min_circle_fast.pro`` uses ``!pi`` four times
(``:34, :37, :41, :51``), so an exact right angle -- ``acos(0) =
1.5707963267948966`` in true double precision -- is *less than* FLOAT
``!pi/2`` (``1.5707963705062866``), and the two-point branch at ``:51`` is
never taken for it. Every rectangle-like case in this bank (``rect_4``,
``block_5x3``, ``outline_20x8``, ``disc_outline_r12``, ``rect_tas_1p037``) is
here specifically to make GDL say so, rather than trusting the arithmetic on
paper.

Every literal goes through :func:`locate.idl_double` for DOUBLE cases, or is
written ``<n>L`` for LONG cases -- a bare decimal is FLOAT in IDL, which is
exactly the trap ``princomp``'s first golden fell into. Large arrays use IDL's
own generators
(``lonarr``, ``lindgen``, ``replicate``) rather than a giant literal: a
13,010-element literal line has been measured to make GDL print nothing at
all, silently.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_min_circle_fast_bank.py
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, idl_double, run_pro  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[3] / "tests" / "data"
           / "gdl_soda2_min_circle_fast_golden.json")


@dataclass
class CaseSpec:
    """One bank case: how GDL builds the arrays, and the identical values on
    the Python side, so the bank's own input-cross-check (A.4) can prove the
    two literals actually agree rather than merely looking plausible."""

    idl_x: str
    idl_y: str
    x: np.ndarray  # dtype mirrors the IDL type: int64 for LONG, float64 for DOUBLE
    y: np.ndarray
    is_double: bool
    record_xy: bool = field(default=True)

    def py(self) -> tuple[np.ndarray, np.ndarray]:
        return self.x, self.y


def _idl_literal(values: list, *, is_double: bool) -> str:
    """A multi-line IDL array literal, at most 20 values per line joined with
    ``, $`` continuation. Splitting like this is what the find_radius/angles
    banks did not need but the L-shape/circle/outline cases here do: GDL has
    been measured to silently print nothing for one very long
    literal line (a 13,010-element ``[0L,0L,...]``); splitting avoids it
    entirely rather than hoping every case stays under whatever the real
    limit is."""
    if is_double:
        parts = [idl_double(v) for v in values]
    else:
        parts = [f"{int(v)}L" for v in values]
    lines = [", ".join(parts[i:i + 20]) for i in range(0, len(parts), 20)]
    return "[" + (", $\n".join(lines)) + "]"


def _filled_block(w: int, h: int) -> list[tuple[int, int]]:
    """All ``w`` x ``h`` grid points, row-major (``for j: for i:``)."""
    return [(i, j) for j in range(h) for i in range(w)]


def _rect_outline(w: int, h: int) -> list[tuple[int, int]]:
    """The 4-sided boundary of a ``w`` x ``h`` rectangle, row-major."""
    return [(i, j) for j in range(h) for i in range(w)
            if i in (0, w - 1) or j in (0, h - 1)]


def _disc_outline(radius: int, offset: int) -> list[tuple[int, int]]:
    """4-connected boundary of the digitised disc ``i^2+j^2 <= radius^2``,
    offset by ``+offset`` so every coordinate is non-negative, row-major."""
    span = range(-radius - 1, radius + 2)
    filled = {(i, j) for i in span for j in span if i * i + j * j <= radius * radius}
    boundary = []
    for j in span:
        for i in span:
            if (i, j) not in filled:
                continue
            neighbours = ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1))
            if any(n not in filled for n in neighbours):
                boundary.append((i + offset, j + offset))
    return boundary


def _circle_points(n: int, r: float, cx: float, cy: float) -> list[tuple[float, float]]:
    return [(r * math.cos(2 * math.pi * k / n) + cx, r * math.sin(2 * math.pi * k / n) + cy)
            for k in range(n)]


def _from_points(pts: list[tuple], *, is_double: bool, record_xy: bool = True) -> CaseSpec:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    idl_x = _idl_literal(xs, is_double=is_double)
    idl_y = _idl_literal(ys, is_double=is_double)
    dtype = np.float64 if is_double else np.int64
    return CaseSpec(idl_x, idl_y, np.asarray(xs, dtype=dtype), np.asarray(ys, dtype=dtype),
                     is_double, record_xy)


def _build_cases() -> dict[str, CaseSpec]:
    cases: dict[str, CaseSpec] = {}

    cases["one_point"] = _from_points([(5, 7)], is_double=False)
    cases["two_points"] = _from_points([(0, 0), (1, 0)], is_double=False)

    cases["collinear_3"] = _from_points([(0, 0), (1, 0), (2, 0)], is_double=False)
    cases["collinear_4"] = _from_points([(0, 0), (1, 0), (2, 0), (3, 0)], is_double=False)
    cases["diagonal_10"] = _from_points([(k, k) for k in range(10)], is_double=False)

    cases["qflip"] = _from_points([(0.0, 0.0), (1.0, 0.1), (3.0, 0.3)], is_double=True)

    cases["rect_4"] = _from_points([(0, 0), (3, 0), (0, 2), (3, 2)], is_double=False)
    cases["block_5x3"] = _from_points(_filled_block(5, 3), is_double=False)
    cases["outline_20x8"] = _from_points(_rect_outline(20, 8), is_double=False)
    cases["disc_outline_r12"] = _from_points(_disc_outline(12, 20), is_double=False)
    cases["rect_tas_1p037"] = _from_points(
        [(0.0, 0.0), (3.0, 0.0), (0.0, 2.074), (3.0, 2.074)], is_double=True)

    cases["circle_360"] = _from_points(_circle_points(360, 50.0, 60.0, 60.0), is_double=True)
    cases["acute_triangle"] = _from_points([(0.0, 0.0), (4.0, 0.0), (1.0, 0.5)], is_double=True)

    # --- L-shape: a 10010-point column plus a 3000-point arm at its top ----
    l_x = np.concatenate([np.zeros(10010, dtype=np.int64), np.arange(1, 3001, dtype=np.int64)])
    l_y = np.concatenate([np.arange(10010, dtype=np.int64), np.full(3000, 10009, dtype=np.int64)])
    cases["L_shape"] = CaseSpec(
        idl_x="[lonarr(10010), lindgen(3000)+1L]",
        idl_y="[lindgen(10010), replicate(10009L,3000)]",
        x=l_x, y=l_y, is_double=False, record_xy=False)

    # --- the iteration cap: a single straight column ------------------------
    cases["column_10010"] = CaseSpec(
        idl_x="lonarr(10010)", idl_y="lindgen(10010)",
        x=np.zeros(10010, dtype=np.int64), y=np.arange(10010, dtype=np.int64),
        is_double=False, record_xy=False)
    cases["column_100"] = CaseSpec(
        idl_x="lonarr(100)", idl_y="lindgen(100)",
        x=np.zeros(100, dtype=np.int64), y=np.arange(100, dtype=np.int64),
        is_double=False)

    cases["dup_of_q"] = _from_points([(0, 0), (1, 0), (1, 0)], is_double=False)
    cases["all_coincident_3"] = _from_points([(2, 5), (2, 5), (2, 5)], is_double=False)

    # --- the real two-blob-in-one-row ROIs
    # from `frame_h_all18` particles 4/5 (identical ROI) and particle 6,
    # `soda2_processbuffer.pro:612-747`'s tail -> `aspect_ratio.pro:11-17`'s
    # `outline_indices` (`tas_adjust`=1.0 exactly on this case, so the
    # adjusted y is still integer) -- extracted by
    # `arrayprobe_soda2.aspect_ratio.outline_indices` on the port's own ROI.
    # Points listed exactly as the port's
    # (x_ind, y_adj) arrays, row-major (matches IDL `where`'s x-fastest
    # order for this array layout).
    _p4_x = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 18, 19, 20, 21, 22, 23, 24, 25,
             10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
             26, 27, 28, 29, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46,
             47, 48, 49]
    _p4_y = [1] * 18 + [2] * 35
    cases["real_roi_p4"] = _from_points(
        list(zip(_p4_x, _p4_y, strict=True)), is_double=False)

    _p6_x = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 18, 19, 20, 21, 22, 23, 24, 25,
             2, 3, 4, 5, 7, 8, 9, 12,
             10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
             26, 27, 28, 29, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46,
             47, 48, 49]
    _p6_y = [1] * 18 + [2] * 8 + [3] * 35
    cases["real_roi_p6"] = _from_points(
        list(zip(_p6_x, _p6_y, strict=True)), is_double=False)

    return cases


CASES: dict[str, CaseSpec] = _build_cases()

_SCRIPT = """
x = {idl_x}
y = {idl_y}
r = min_circle_fast(x, y)
print, 'N=', n_elements(x), format='(A,I8)'
print, 'SX=', total(double(x)), format='(A,E24.16)'
print, 'SY=', total(double(y)), format='(A,E24.16)'
print, 'DIAM=', r.diam, format='(A,E24.16)'
print, 'CX=', r.center[0], format='(A,E24.16)'
print, 'CY=', r.center[1], format='(A,E24.16)'
print, 'NC=', n_elements(r.corners), format='(A,I8)'
print, 'CORNERS=' + strjoin(strtrim(string(r.corners),2), ',')
print, 'AREA=', r.area, format='(A,I8)'
"""


def _parse(stdout: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("CORNERS="):
            body = line[len("CORNERS="):].strip()
            out["CORNERS"] = [int(v) for v in body.split(",") if v.strip() != ""]
        elif line.startswith("N="):
            out["N"] = int(line[len("N="):].strip())
        elif line.startswith("SX="):
            out["SX"] = float(line[len("SX="):].strip())
        elif line.startswith("SY="):
            out["SY"] = float(line[len("SY="):].strip())
        elif line.startswith("DIAM="):
            out["DIAM"] = float(line[len("DIAM="):].strip())
        elif line.startswith("CX="):
            out["CX"] = float(line[len("CX="):].strip())
        elif line.startswith("CY="):
            out["CY"] = float(line[len("CY="):].strip())
        elif line.startswith("NC="):
            out["NC"] = int(line[len("NC="):].strip())
        elif line.startswith("AREA="):
            out["AREA"] = int(line[len("AREA="):].strip())
    return out


_REQUIRED = {"N", "SX", "SY", "DIAM", "CX", "CY", "NC", "CORNERS", "AREA"}


def main() -> int:
    records = []
    try:
        for name, spec in CASES.items():
            script = _SCRIPT.format(idl_x=spec.idl_x, idl_y=spec.idl_y)
            stdout, stderr = run_pro(script, timeout=120)
            vals = _parse(stdout)
            rec: dict[str, object] = {"name": name, "is_double": spec.is_double}
            if spec.record_xy:
                rec["x"] = spec.x.tolist()
                rec["y"] = spec.y.tolist()
            if not _REQUIRED.issubset(vals):
                rec.update(status="ERROR", stdout=stdout[-800:], stderr=stderr[-800:])
                print(f"{name}: ERROR (missing {_REQUIRED - set(vals)})")
            else:
                rec.update(status="OK", **vals)
                print(f"{name}: n={vals['N']} diam={vals['DIAM']:.10g} "
                      f"corners={vals['CORNERS']} area={vals['AREA']}")
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
    print(f"\nwrote {FIXTURE} -- {len(records)} cases, {ok} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
