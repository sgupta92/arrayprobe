# SPDX-License-Identifier: BSD-3-Clause
"""Reproduction report: compare a product against an archived product, cell by cell.

Read-only. Opens both files for reading, writes nothing to either, and lists every
differing cell (variable, index, both values), never a summary alone.
Where a ``.call`` sidecar sits beside a file, its engine and stamp are reported.

``compare.py`` joins per-particle files on particle identity; a size-distribution
product has no particle axis, so this report compares shared variables cell by cell
on their stored shape. Two NaNs in the same cell count as equal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

from arrayprobe import provenance


def _call_stamp(path: Path) -> dict | None:
    side = Path(str(path) + ".call")
    if not side.exists():
        side = path.with_suffix(".call")
    if not side.exists():
        return None
    text = side.read_text(encoding="utf-8", errors="replace").strip()
    # The engine is what the stamp records, or None: a stamp naming no engine is not v3.1.4.
    return {"path": str(side), "engine": provenance.parse(text).engine, "stamp": text}


def _read(ds, name):
    v = ds.variables[name]
    v.set_auto_maskandscale(False)
    return np.asarray(v[...])


def _scalar(x):
    x = x.item() if hasattr(x, "item") else x
    if isinstance(x, bytes):
        return x.decode("latin-1")
    if isinstance(x, float) and np.isnan(x):
        return "NaN"
    return x


def build_report(product, archived) -> dict:
    """Compare every variable the two files share; return the report as a dict."""
    product, archived = Path(product), Path(archived)
    out: dict[str, Any] = {"product": str(product), "archived": str(archived),
           "call": {"product": _call_stamp(product), "archived": _call_stamp(archived)},
           "variables": [], "only_in_product": [], "only_in_archived": [],
           "differing_cells": []}
    with netCDF4.Dataset(str(product)) as a, netCDF4.Dataset(str(archived)) as b:
        na, nb = set(a.variables), set(b.variables)
        out["only_in_product"] = sorted(na - nb)
        out["only_in_archived"] = sorted(nb - na)
        for name in sorted(na & nb):
            x, y = _read(a, name), _read(b, name)
            row = {"name": name, "shape_product": list(x.shape),
                   "shape_archived": list(y.shape), "cells": 0, "exact": 0,
                   "differing": 0, "max_abs": 0.0, "max_rel": 0.0}
            if x.shape != y.shape:
                row["note"] = "shapes differ; not compared cell by cell"
                out["variables"].append(row)
                continue
            if x.dtype.kind in "fiub" and y.dtype.kind in "fiub":
                xf, yf = x.astype(np.float64), y.astype(np.float64)
                eq = (xf == yf) | (np.isnan(xf) & np.isnan(yf))
                d = np.abs(xf - yf)
                d = np.where(eq, 0.0, d)
                fin = np.isfinite(d)
                if fin.any():
                    row["max_abs"] = float(d[fin].max())
                    with np.errstate(divide="ignore", invalid="ignore"):
                        r = d / np.abs(yf)
                    r = np.where(eq, 0.0, r)
                    rf = np.isfinite(r)
                    row["max_rel"] = float(r[rf].max()) if rf.any() else 0.0
                    if (~rf & ~eq).any():
                        row["max_rel"] = "inf"
            else:
                eq = x == y
            eq = np.asarray(eq, dtype=bool).reshape(x.shape)
            row["cells"] = int(eq.size)
            row["exact"] = int(eq.sum())
            row["differing"] = int(eq.size - eq.sum())
            for pos in np.argwhere(~eq):
                idx = tuple(int(i) for i in pos)
                out["differing_cells"].append(
                    {"variable": name, "index": list(idx),
                     "product": _scalar(x[idx]), "archived": _scalar(y[idx])})
            out["variables"].append(row)
    out["cells"] = sum(v["cells"] for v in out["variables"])
    out["exact"] = sum(v["exact"] for v in out["variables"])
    out["n_differing"] = len(out["differing_cells"])
    out["identical"] = (out["n_differing"] == 0 and not out["only_in_product"]
                        and not out["only_in_archived"]
                        and all("note" not in v for v in out["variables"]))
    return out


def render_markdown(rep: dict) -> str:
    """Render a :func:`build_report` dict as the Markdown reproduction report."""
    lines = ["# Reproduction report", "",
             f"- Product: `{rep['product']}`", f"- Archived: `{rep['archived']}`"]
    for side in ("product", "archived"):
        c = rep["call"][side]
        lines.append(f"- {side} `.call`: " + (
            f"engine={c['engine']}, stamp `{c['stamp']}`" if c else "no sidecar"))
    verdict = "EXACT" if rep["identical"] else "NOT EXACT"
    lines += ["", f"**{verdict}**: {rep['exact']} of {rep['cells']} cells equal; "
              f"{rep['n_differing']} differing.", ""]
    if rep["only_in_product"]:
        lines.append("Only in product: " + ", ".join(rep["only_in_product"]))
    if rep["only_in_archived"]:
        lines.append("Only in archived: " + ", ".join(rep["only_in_archived"]))
    lines += ["| variable | cells | exact | differing | max abs | max rel | note |",
              "|---|---|---|---|---|---|---|"]
    for v in rep["variables"]:
        lines.append(f"| {v['name']} | {v['cells']} | {v['exact']} | {v['differing']} "
                     f"| {v['max_abs']} | {v['max_rel']} | {v.get('note', '')} |")
    lines += ["", "## Every differing cell", ""]
    if not rep["differing_cells"]:
        lines.append("None.")
    else:
        lines += ["| variable | index | product | archived |", "|---|---|---|---|"]
        for c in rep["differing_cells"]:
            lines.append(f"| {c['variable']} | {tuple(c['index'])} "
                         f"| {c['product']} | {c['archived']} |")
    return "\n".join(lines) + "\n"


def write_report(product, archived, out_md=None, out_json=None) -> dict:
    """Build the report for a product against its archived twin and write the requested files.

    ``out_md`` receives :func:`render_markdown`'s text, ``out_json`` the report dict; either may
    be omitted. Returns the report dict.
    """
    rep = build_report(product, archived)
    if out_md:
        Path(out_md).write_text(render_markdown(rep), encoding="utf-8")
    if out_json:
        Path(out_json).write_text(json.dumps(rep, indent=1, default=str),
                                  encoding="utf-8")
    return rep
