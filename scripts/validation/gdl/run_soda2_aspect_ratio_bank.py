# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2 geometry chain's last file: ``aspect_ratio.pro`` under GDL, unmodified where GDL
can run it, shimmed where it cannot.

GDL 1.1.2 has no ``ERODE`` (measured: ``Attempt to call undefined function:
ERODE``). ``aspect_ratio.pro`` calls it only when the image has more than two
slices along airflow (``s[2] gt 2``), so GDL runs the routine **unmodified**
for coordinate input and for images with at most two slices -- families F1
and F2 below are real doctrine-layer-2 evidence. For images with more than
two slices (F3), this bank supplies its own ``erode.pro`` -- a plain
4-connected cross erosion under the same ``edge_rule`` the Python port
defaults to (``arrayprobe_soda2.aspect_ratio.ERODE_EDGE_RULE``) -- via
``locate.run_pro``'s ``extra_files``. That is *this bank's own reading* of
IDL's real ERODE semantics at the image border, not a confirmed one (the
IDL/NV5 ERODE reference pages did not resolve when checked).
F3 records are
therefore layer 3, labelled ``erode_rule="zero_outside_shim_unconfirmed"``,
and every one of them is real end-to-end output of the *actual*
``aspect_ratio.pro`` -- including its calls to the real, vendored
``min_circle_fast.pro`` and ``find_angle.pro`` -- so this bank in no way
depends on this repository's own (concurrently developed) Python port of
``min_circle_fast``.

Every case runs ``aspect_ratio`` end to end and records ``ASPR``, ``ORIENT``,
``DIAM``, ``CX``, ``CY``, ``CORNERS`` and the ``x_ind``/``y_ind`` keyword
outputs (``XI``, unadjusted ``YI``). That lets the test suite check three
different things against the same golden: the outline/index-order step alone
(F1, erosion-free), :func:`arrayprobe_soda2.aspect_ratio.axis_and_ratio` given
IDL's own circle (all OK cases, no dependency on the Python
``min_circle_fast``), and eventually the whole composed routine once that
Python port lands.

Literal rule specific to this bank: **``tas_adjust`` is the one place a bare
(FLOAT) literal is correct on purpose.** Production passes a FLOAT
(``soda2_findsize.pro:30``), so ``tas_kind="float"`` cases emit a bare decimal
and ``tas_kind="double"`` cases go through ``locate.idl_double``. Every other
literal in this bank -- coordinates aside, which are LONG by construction
(``lonarr``) -- is ``d``-suffixed.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_aspect_ratio_bank.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from locate import GDLUnavailable, idl_double, run_pro  # noqa: E402

from arrayprobe_soda2.aspect_ratio import ERODE_EDGE_RULE, outline_indices  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[3] / "tests" / "data"
           / "gdl_soda2_aspect_ratio_golden.json")

_d = idl_double  #: see locate.idl_double -- `d` is IDL's exponent marker


# --------------------------------------------------------------------------
# The erode.pro shim (F3 only). Same edge_rule as the port's own default, so
# a "zero_outside" pixel is one that fails a cross-neighbour test against a
# neighbour outside the image; a "clip_element" pixel simply isn't required
# to have that neighbour at all. Both are expressed as a single padding
# value for the missing neighbour: 0b makes the test fail (zero_outside), 1b
# makes it trivially pass (clip_element).
# --------------------------------------------------------------------------
_ERODE_SHIM_TEMPLATE = """
; shim for GDL 1.1.2, which lacks ERODE (measured: "Attempt to call
; undefined function: ERODE"). 4-connected (cross) binary erosion.
; edge_rule = '{edge_rule}': a missing neighbour reads as {padval}b.
; UNCONFIRMED against real IDL/GDL semantics -- see
; the SODA-2 port design notes, the aspect_ratio.pro section, "the oracle gap".
FUNCTION erode, img, element
  s = size(img)
  nx = s[1]
  ny = s[2]
  out = bytarr(nx, ny)
  padval = {padval}b
  FOR y=0L, ny-1 DO BEGIN
    FOR x=0L, nx-1 DO BEGIN
      up = padval
      IF y gt 0 THEN up = img[x,y-1]
      down = padval
      IF y lt ny-1 THEN down = img[x,y+1]
      left = padval
      IF x gt 0 THEN left = img[x-1,y]
      right = padval
      IF x lt nx-1 THEN right = img[x+1,y]
      out[x,y] = (img[x,y] ne 0) and (up ne 0) and (down ne 0) $
                 and (left ne 0) and (right ne 0)
    ENDFOR
  ENDFOR
  return, out
END
"""


def _erode_shim(edge_rule: str) -> str:
    padval = 0 if edge_rule == "zero_outside" else 1
    return _ERODE_SHIM_TEMPLATE.format(edge_rule=edge_rule, padval=padval)


_ERODE_RULE_LABEL = {
    "zero_outside": "zero_outside_shim_unconfirmed",
    "clip_element": "clip_element_shim_unconfirmed",
}


# --------------------------------------------------------------------------
# Case construction
# --------------------------------------------------------------------------

class Case:
    __slots__ = ("name", "family", "mode", "image", "coords", "tas_kind", "tas_value")

    def __init__(self, name, family, mode, *, image=None, coords=None,
                 tas_kind="none", tas_value=None):
        self.name = name
        self.family = family
        self.mode = mode  # 'image' | 'coords'
        self.image = image  # list of rows, y-major, 0/1
        self.coords = coords  # list of [x, y]
        self.tas_kind = tas_kind  # 'none' | 'float' | 'double'
        self.tas_value = tas_value


def _image_from_rows(rows: list[list[int]]) -> list[list[int]]:
    return [list(map(int, r)) for r in rows]


def _largest_4connected_component(grid: np.ndarray) -> np.ndarray | None:
    """Plain BFS -- no scipy dependency for a fixture-generation script."""
    h, w = grid.shape
    visited = np.zeros_like(grid, dtype=bool)
    best: list[tuple[int, int]] | None = None
    for sy in range(h):
        for sx in range(w):
            if not grid[sy, sx] or visited[sy, sx]:
                continue
            stack = [(sy, sx)]
            visited[sy, sx] = True
            comp = [(sy, sx)]
            while stack:
                cy, cx = stack.pop()
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if (0 <= ny < h and 0 <= nx < w and grid[ny, nx]
                            and not visited[ny, nx]):
                        visited[ny, nx] = True
                        comp.append((ny, nx))
                        stack.append((ny, nx))
            if best is None or len(comp) > len(best):
                best = comp
    if best is None:
        return None
    mask = np.zeros_like(grid, dtype=bool)
    for y, x in best:
        mask[y, x] = True
    return mask


def _random_blobs(n: int, seed: int = 20260912) -> list[np.ndarray]:
    """``n`` deterministic 4-connected blobs, cropped tight, at least 3 rows
    tall (so they are F3-eligible: erosion only applies for > 2 slices)."""
    rng = np.random.default_rng(seed)
    blobs: list[np.ndarray] = []
    while len(blobs) < n:
        h = int(rng.integers(6, 13))
        w = int(rng.integers(6, 13))
        grid = (rng.random((h, w)) < 0.55)
        mask = _largest_4connected_component(grid)
        if mask is None or mask.sum() < 6:
            continue
        ys, xs = np.nonzero(mask)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        cropped = mask[y0:y1 + 1, x0:x1 + 1].astype(np.uint8)
        if cropped.shape[0] <= 2:
            continue
        blobs.append(cropped)
    return blobs


def _disc_outline(radius_lo2: int, radius_hi2: int, center: int = 3) -> list[list[int]]:
    pts = sorted(
        {(center + dx, center + dy)
         for dx in range(-center - 1, center + 2)
         for dy in range(-center - 1, center + 2)
         if radius_lo2 <= dx * dx + dy * dy <= radius_hi2},
        key=lambda p: (p[1], p[0]),
    )
    return [list(p) for p in pts]


def _rect_outline(nx: int, ny: int) -> list[list[int]]:
    pts = sorted(
        {(x, y) for x in range(nx) for y in range(ny)
         if x in (0, nx - 1) or y in (0, ny - 1)},
        key=lambda p: (p[1], p[0]),
    )
    return [list(p) for p in pts]


def _square_outline(n: int) -> list[list[int]]:
    return _rect_outline(n, n)


def _square_full(n: int) -> list[list[int]]:
    return [[x, y] for y in range(n) for x in range(n)]


def build_cases() -> list[Case]:
    cases: list[Case] = []

    # ---- F1: image, <= 2 slices (GDL runs unmodified) ---------------------
    cases.append(Case("single_pixel", "F1", "image",
                       image=_image_from_rows([[1]])))
    cases.append(Case("empty_image", "F1", "image",
                       image=_image_from_rows([[0, 0, 0, 0], [0, 0, 0, 0]])))
    cases.append(Case("hline_5", "F1", "image",
                       image=_image_from_rows([[1, 1, 1, 1, 1]])))
    cases.append(Case("hline_gapped", "F1", "image",
                       image=_image_from_rows([[1, 0, 1, 0, 1]])))
    cases.append(Case("two_slice_full", "F1", "image",
                       image=_image_from_rows([[1, 1, 1, 1, 1], [1, 1, 1, 1, 1]])))
    cases.append(Case("two_slice_antidiag", "F1", "image",
                       image=_image_from_rows([[1, 0], [0, 1]])))
    cases.append(Case("two_slice_L", "F1", "image",
                       image=_image_from_rows([[1, 1, 1], [1, 0, 0]])))
    cases.append(Case("hpair_tas05_float", "F1", "image",
                       image=_image_from_rows([[1, 1]]),
                       tas_kind="float", tas_value=0.5))
    cases.append(Case("two_slice_tas0p1_float", "F1", "image",
                       image=_image_from_rows([[1, 1, 1, 1, 1], [1, 1, 1, 1, 1]]),
                       tas_kind="float", tas_value=0.1))
    cases.append(Case("two_slice_tas0p1_double", "F1", "image",
                       image=_image_from_rows([[1, 1, 1, 1, 1], [1, 1, 1, 1, 1]]),
                       tas_kind="double", tas_value=0.1))
    cases.append(Case("two_slice_notas", "F1", "image",
                       image=_image_from_rows([[1, 1, 1, 1, 1], [1, 1, 1, 1, 1]])))

    # ---- F2: coordinates (GDL runs unmodified) -----------------------------
    cases.append(Case("vline_5", "F2", "coords",
                       coords=[[0, k] for k in range(5)]))
    cases.append(Case("diag_5", "F2", "coords",
                       coords=[[k, k] for k in range(5)]))
    cases.append(Case("square5_outline", "F2", "coords",
                       coords=_square_outline(5)))
    cases.append(Case("square5_full", "F2", "coords",
                       coords=_square_full(5)))
    cases.append(Case("acute_tri", "F2", "coords",
                       coords=[[0, 0], [2, 0], [1, 3]]))
    cases.append(Case("obtuse_tri", "F2", "coords",
                       coords=[[0, 0], [4, 0], [2, 1]]))
    cases.append(Case("right_tri", "F2", "coords",
                       coords=[[0, 0], [2, 0], [0, 2]]))
    cases.append(Case("plus_cross_5", "F2", "coords",
                       coords=[[1, 0], [0, 1], [1, 1], [2, 1], [1, 2]]))
    cases.append(Case("den_clamp_bites_tas025_float", "F2", "coords",
                       coords=[[0, 0], [0, 2], [1, 1]],
                       tas_kind="float", tas_value=0.25))
    cases.append(Case("den_clamp_bites_tas025_double", "F2", "coords",
                       coords=[[0, 0], [0, 2], [1, 1]],
                       tas_kind="double", tas_value=0.25))
    cases.append(Case("duplicate_points", "F2", "coords",
                       coords=[[0, 0], [0, 0], [1, 0]]))
    cases.append(Case("all_same_point", "F2", "coords",
                       coords=[[2, 2], [2, 2], [2, 2]]))
    cases.append(Case("disc_r3_outline", "F2", "coords",
                       coords=_disc_outline(6, 9)))
    cases.append(Case("rect_3x7_outline", "F2", "coords",
                       coords=_rect_outline(3, 7)))

    # ---- F3 named: image, > 2 slices (needs the erode shim) ----------------
    cases.append(Case("square5_image", "F3", "image", image=_image_from_rows(
        [[1, 1, 1, 1, 1] for _ in range(5)])))
    disc_pts = _disc_outline(0, 9)  # filled disc, not just the outline
    disc_nx = max(x for x, _y in disc_pts) + 1
    disc_ny = max(y for _x, y in disc_pts) + 1
    disc_img = [[0] * disc_nx for _ in range(disc_ny)]
    for x, y in disc_pts:
        disc_img[y][x] = 1
    cases.append(Case("disc_r3_image", "F3", "image", image=disc_img))
    cases.append(Case("rect_3x7_image", "F3", "image",
                       image=[[1, 1, 1] for _ in range(7)]))
    cases.append(Case("column_1x7_image", "F3", "image",
                       image=[[1] for _ in range(7)]))

    # ---- 8 random blobs: feed as F2 coords (via the port's own outline)
    #      AND as F3 images (unpadded + padded) -----------------------------
    blobs = _random_blobs(8)
    for i, blob in enumerate(blobs):
        x_ind, y_ind, area = outline_indices(blob, edge_rule=ERODE_EDGE_RULE)
        if area == 0:
            continue
        coords = [[int(x), int(y)] for x, y in
                  zip(x_ind.tolist(), y_ind.tolist(), strict=True)]
        cases.append(Case(f"random_blob_{i}_outline_coords", "coords_from_port_outline",
                           "coords", coords=coords))

        img_rows = blob.tolist()
        cases.append(Case(f"random_blob_{i}_image", "F3", "image", image=img_rows))

        ny, nx = blob.shape
        padded = np.zeros((ny + 2, nx + 2), dtype=np.uint8)
        padded[1:-1, 1:-1] = blob
        cases.append(Case(f"random_blob_{i}_image_padded", "F3", "image",
                           image=padded.tolist()))

    return cases


# --------------------------------------------------------------------------
# IDL script generation and output parsing
# --------------------------------------------------------------------------

_KEYS = ("ASPR", "ORIENT", "DIAM", "CX", "CY")


def _tas_literal(case: Case) -> str | None:
    if case.tas_kind == "none":
        return None
    if case.tas_kind == "float":
        return repr(float(case.tas_value))
    if case.tas_kind == "double":
        return _d(case.tas_value)
    raise ValueError(case.tas_kind)


def _call_script(case: Case) -> str:
    lines: list[str] = []
    if case.mode == "image":
        rows = case.image
        ny = len(rows)
        nx = len(rows[0]) if ny else 0
        lines.append(f"img = bytarr({nx}, {ny})")
        for y, row in enumerate(rows):
            for x, v in enumerate(row):
                if v:
                    lines.append(f"img[{x}, {y}] = 1b")
        target = "img"
        extra = ""
    else:
        pts = case.coords
        n = len(pts)
        lines.append(f"pts = lonarr({n}, 2)")
        lines.append("pts[*,0] = [" + ", ".join(str(int(p[0])) for p in pts) + "]")
        lines.append("pts[*,1] = [" + ", ".join(str(int(p[1])) for p in pts) + "]")
        target = "pts"
        extra = ", /coordinates"

    tas_lit = _tas_literal(case)
    tas_kw = f", tas_adjust={tas_lit}" if tas_lit is not None else ""
    lines.append(
        f"r = aspect_ratio({target}{extra}{tas_kw}, circle=c, orientation=o, "
        "x_ind=xi, y_ind=yi)"
    )
    lines.append("print, 'ASPR=', r, format='(A,E24.16)'")
    lines.append("print, 'ORIENT=', o, format='(A,E24.16)'")
    lines.append("print, 'DIAM=', c.diam, format='(A,E24.16)'")
    lines.append("print, 'CX=', c.center[0], format='(A,E24.16)'")
    lines.append("print, 'CY=', c.center[1], format='(A,E24.16)'")
    lines.append("nc = n_elements(c.corners)")
    lines.append("print, 'NCORNERS=', nc, format='(A,I0)'")
    lines.append(
        "fmt_c = '(A,' + strtrim(nc,2) + '(1X,I0))' "
        "& print, 'CORNERS=', c.corners, format=fmt_c"
    )
    lines.append("nxi = n_elements(xi)")
    lines.append("print, 'NXI=', nxi, format='(A,I0)'")
    lines.append(
        "fmt_xi = '(A,' + strtrim(nxi,2) + '(1X,I0))' "
        "& print, 'XI=', xi, format=fmt_xi"
    )
    lines.append(
        "fmt_yi = '(A,' + strtrim(nxi,2) + '(1X,I0))' "
        "& print, 'YI=', yi, format=fmt_yi"
    )
    return "\n".join(lines)


def _parse_scalar(stdout: str, key: str) -> float | None:
    prefix = f"{key}="
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return float(line[len(prefix):].strip())
    return None


def _parse_int_list(stdout: str, key: str) -> list[int] | None:
    prefix = f"{key}="
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            rest = line[len(prefix):].strip()
            return [int(v) for v in rest.split()]
    return None


def _run_case(case: Case) -> dict[str, Any]:
    script = _call_script(case)
    extra_files = None
    erode_rule = "n/a"
    if case.family in ("F3",):
        extra_files = {"erode.pro": _erode_shim(ERODE_EDGE_RULE)}
        erode_rule = _ERODE_RULE_LABEL[ERODE_EDGE_RULE]
    stdout, stderr = run_pro(script, extra_files=extra_files)

    rec: dict[str, Any] = {
        "name": case.name, "family": case.family, "mode": case.mode,
        "tas_kind": case.tas_kind, "tas_value": case.tas_value,
        "erode_rule": erode_rule,
        "erode_source": "shim" if extra_files else "gdl",
    }
    if case.mode == "image":
        rec["image"] = case.image
    else:
        rec["coords"] = case.coords

    diam = _parse_scalar(stdout, "DIAM")
    ncorners_list = _parse_int_list(stdout, "NCORNERS")
    corners = _parse_int_list(stdout, "CORNERS")
    nxi_list = _parse_int_list(stdout, "NXI")
    xi = _parse_int_list(stdout, "XI")
    yi = _parse_int_list(stdout, "YI")
    scalars = {k: _parse_scalar(stdout, k) for k in _KEYS}

    ok = (diam is not None and corners is not None and xi is not None
          and yi is not None and all(v is not None for v in scalars.values()))
    if not ok:
        rec.update(status="ERROR", stdout=stdout[-600:], stderr=stderr[-600:])
    else:
        rec.update(status="OK", **scalars, CORNERS=corners,
                    XI=xi, YI=yi,
                    NCORNERS=ncorners_list[0] if ncorners_list else None,
                    NXI=nxi_list[0] if nxi_list else None)
    return rec


# --------------------------------------------------------------------------
# F4: IDL-semantics-only records (no aspect_ratio call)
# --------------------------------------------------------------------------

def _run_nan_lt_one() -> dict[str, Any]:
    script = "print, (!values.d_nan < 1.0d), format='(E24.16)'"
    stdout, stderr = run_pro(script)
    try:
        value = float(stdout.strip().splitlines()[-1])
        return {"name": "nan_lt_one", "family": "F4", "status": "OK", "value": value}
    except (IndexError, ValueError):
        return {"name": "nan_lt_one", "family": "F4", "status": "ERROR",
                 "stdout": stdout[-400:], "stderr": stderr[-400:]}


def _run_mod_grid() -> list[dict[str, Any]]:
    """48 values (7x7 minus (0,0)) pinning the float32 `atan`/`mod` chain that
    `orientation_deg` implements, independent of any circle/particle case."""
    records = []
    lines = []
    pairs = [(dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)
             if not (dx == 0 and dy == 0)]
    for dx, dy in pairs:
        tag = f"MG_{dx}_{dy}="
        lines.append(
            f"print, '{tag}', "
            f"((atan(float({dy}), float({dx}))*180/!pi - 360 - 90) mod 180) + 90, "
            "format='(A,E24.16)'"
        )
    stdout, stderr = run_pro("\n".join(lines))
    parsed: dict[str, float] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("MG_"):
            key, _, val = line.partition("=")
            parsed[key] = float(val.strip())
    for dx, dy in pairs:
        key = f"MG_{dx}_{dy}"
        name = f"mod_grid_dx{dx}_dy{dy}"
        if key in parsed:
            records.append({"name": name, "family": "F4", "status": "OK",
                             "dx": dx, "dy": dy, "value": parsed[key]})
        else:
            records.append({"name": name, "family": "F4", "status": "ERROR",
                             "dx": dx, "dy": dy, "stdout": stdout[-400:],
                             "stderr": stderr[-400:]})
    return records


_UNCLAMPED_SNIPPET = """
pts = lonarr(3, 2)
pts[*,0] = [0, 0, 1]
pts[*,1] = [0, 2, 1]
tas = {tas}
r = aspect_ratio(pts, /coordinates, tas_adjust=tas, circle=c, orientation=o, $
                 x_ind=xi, y_ind=yi)
yi_adj = yi * tas
n = n_elements(c.corners)
IF n eq 3 THEN BEGIN
  P = c.corners[0] & Q = c.corners[1] & R = c.corners[2]
  angP = find_angle([xi[P],yi_adj[P]], [xi[R],yi_adj[R]], [xi[Q],yi_adj[Q]])
  angQ = find_angle([xi[Q],yi_adj[Q]], [xi[R],yi_adj[R]], [xi[P],yi_adj[P]])
  angR = find_angle([xi[R],yi_adj[R]], [xi[Q],yi_adj[Q]], [xi[P],yi_adj[P]])
  dummy = min([angP, angQ, angR], vertex)
  cx1 = xi[c.corners[vertex]] & cy1 = yi_adj[c.corners[vertex]]
  cx2 = c.center[0] & cy2 = c.center[1]
ENDIF ELSE BEGIN
  cx1 = xi[c.corners[0]] & cy1 = yi_adj[c.corners[0]]
  cx2 = xi[c.corners[1]] & cy2 = yi_adj[c.corners[1]]
ENDELSE
a = cy1 - cy2
b = cx2 - cx1
cc = cx1*cy2 - cx2*cy1
den = sqrt(a^2 + b^2)                 ; deliberately NOT clamped -- the point
distmajor = (a*xi + b*yi_adj + cc)/den
aspr_unclamped = (max(distmajor) - min(distmajor) + 1)/(c.diam + 1)
print, 'ASPRU=', aspr_unclamped, format='(A,E24.16)'
print, 'ASPRC=', (aspr_unclamped < 1.0d), format='(A,E24.16)'
"""


def _run_den_unclamped(name: str, tas_kind: str, tas_value: float) -> dict[str, Any]:
    tas_lit = repr(float(tas_value)) if tas_kind == "float" else _d(tas_value)
    script = _UNCLAMPED_SNIPPET.format(tas=tas_lit)
    stdout, stderr = run_pro(script)
    unclamped = _parse_scalar(stdout, "ASPRU")
    reclamped = _parse_scalar(stdout, "ASPRC")
    if unclamped is None:
        return {"name": name, "family": "F4", "status": "ERROR",
                "stdout": stdout[-400:], "stderr": stderr[-400:]}
    return {"name": name, "family": "F4", "status": "OK",
            "ASPR_UNCLAMPED": unclamped, "ASPR_RECLAMPED": reclamped}


_FIND_ANGLE_VERTEX_SNIPPET = """
x_ind=[109L,101L,105L] & y_ind=[10L,99L,54L]
tas_adjust=1.0
y_ind=y_ind*tas_adjust
P=0 & Q=1 & R=2
angP=find_angle([x_ind[P],y_ind[P]],[x_ind[R],y_ind[R]],[x_ind[Q],y_ind[Q]])
angQ=find_angle([x_ind[Q],y_ind[Q]],[x_ind[R],y_ind[R]],[x_ind[P],y_ind[P]])
angR=find_angle([x_ind[R],y_ind[R]],[x_ind[Q],y_ind[Q]],[x_ind[P],y_ind[P]])
dummy=min([angP, angQ, angR], vertex)
print, 'FAV_TYPE=', size(angP,/type), format='(A,I0)'
print, 'FAV_BITS=', long(angP,0), long(angQ,0), long(angR,0), format='(A,3(I0,:,","))'
print, 'FAV_VERTEX=', vertex, format='(A,I0)'
"""


def _run_find_angle_vertex() -> dict[str, Any]:
    """find_angle.pro run exactly as aspect_ratio.pro:33-38 calls it, on the
    near-collinear triangle x=[109,101,105], y=[10,99,54], tas_adjust=1.0
    (FLOAT): the three angles' float32 bit patterns and the argmin vertex."""
    name = "find_angle_vertex_near_collinear"
    stdout, stderr = run_pro(_FIND_ANGLE_VERTEX_SNIPPET)
    found: dict[str, str] = {}
    for line in stdout.splitlines():
        key, sep, val = line.strip().partition("=")
        if sep and key.startswith("FAV_"):
            found[key] = val.strip()
    try:
        bits = [int(v) & 0xFFFFFFFF for v in found["FAV_BITS"].split(",")]
        return {"name": name, "family": "F4", "status": "OK",
                "x_ind": [109, 101, 105], "y_ind": [10, 99, 54],
                "tas_adjust": 1.0, "idl_type": int(found["FAV_TYPE"]),
                "angle_bits_f32": bits, "vertex": int(found["FAV_VERTEX"])}
    except (KeyError, ValueError):
        return {"name": name, "family": "F4", "status": "ERROR",
                "stdout": stdout[-400:], "stderr": stderr[-400:]}


def main() -> int:
    records: list[dict[str, Any]] = []
    try:
        for case in build_cases():
            rec = _run_case(case)
            print(f"{case.name} [{case.family}]: {rec.get('status')}")
            records.append(rec)

        records.append(_run_nan_lt_one())
        records.extend(_run_mod_grid())
        records.append(_run_den_unclamped(
            "den_unclamped_tas025_float", "float", 0.25))
        records.append(_run_den_unclamped(
            "den_unclamped_tas025_double", "double", 0.25))
        records.append(_run_find_angle_vertex())
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
