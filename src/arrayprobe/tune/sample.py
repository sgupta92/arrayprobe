# SPDX-License-Identifier: BSD-3-Clause
"""Review queues drawn from one proc file: particles inside time windows, per size bin.

From a proc file's three columns -- the image record's header time (``Time``, HHMMSS),
``image_diam_minR`` (mm) and ``image_auto_reject`` -- the particles whose record time falls inside
any of the given windows (seconds of day, both ends included) and whose size is at least the first
size edge are split into size bins, and up to ``per_bin`` of each bin are drawn at random with a
fixed seed. Two queues go into one file:

* ``<stem>-accepted-n<per_bin>-s<seed>``: only the image codes ``sizeDist`` counts as accepted
  (:data:`ACCEPTED_CODES`);
* ``<stem>-all-n<per_bin>-s<seed>``: every image code, drawn independently of the first, so a
  particle can sit in both; the coverage block counts the overlap.

The file written has the shape :func:`arrayprobe.triage_server._load_queue_file` reads, with each
queue's coverage under ``_coverage``, and is merged into an existing queue file rather than
replacing it. Read-only towards the proc file: nothing here computes or changes a product.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

import numpy as np

#: Size-bin edges, mm. The first edge is the size floor; the last bin is open-ended.
SIZE_EDGES_MM: tuple[float, ...] = (0.055, 0.1, 0.2, 0.4, 1.0, float("inf"))
PER_BIN = 40
SEED = 20260930
#: The image codes ``sizeDist`` counts as accepted.
ACCEPTED_CODES = "0HhuR"
#: The key the coverage blocks go under; the triage server skips any key starting with ``_``.
COVERAGE_KEY = "_coverage"
WINDOW_CLOCK = "record header Time (HHMMSS)"

_WINDOW_RE = re.compile(r"(\d+)\s*-\s*(\d+)")
_SECONDS_PER_DAY = 86400

Windows = tuple[tuple[int, int], ...]


def parse_windows(text: str) -> Windows:
    """Every ``lo-hi`` pair (seconds of day) in ``text``, in order.

    Pairs may be separated by commas, spaces or new lines; a line starting with ``#`` is a comment.
    Refuses a window that ends before it starts, a second outside the day, and text with no window.
    """
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    out = []
    for a, b in _WINDOW_RE.findall(body):
        lo, hi = int(a), int(b)
        if hi < lo:
            raise ValueError(f"window {lo}-{hi} ends before it starts")
        if hi >= _SECONDS_PER_DAY:
            raise ValueError(f"window {lo}-{hi} is past the end of the day (86399 s)")
        out.append((lo, hi))
    if not out:
        raise ValueError(f"no lo-hi window (seconds of day) in {text!r}")
    return tuple(out)


def read_windows(spec: str | Path) -> Windows:
    """Windows from a file holding ``lo-hi`` pairs, or from the pairs given directly."""
    path = Path(spec)
    try:
        is_file = path.is_file()
    except OSError:  # a long window list is not a valid path on every platform
        is_file = False
    if is_file:
        return parse_windows(path.read_text(encoding="utf-8"))
    return parse_windows(str(spec))


def hhmmss_to_sod(hhmmss) -> np.ndarray:
    """A proc file's ``Time`` (HHMMSS) to seconds of day, as int64."""
    t = np.asarray(hhmmss, np.int64)
    return (t // 10000) * 3600 + ((t // 100) % 100) * 60 + t % 100


def in_windows(sod, windows: Sequence[tuple[int, int]]) -> np.ndarray:
    """True where a second of day falls inside any window, both ends included."""
    sod = np.asarray(sod, np.int64)
    mask = np.zeros(sod.shape, bool)
    for lo, hi in windows:
        mask |= (sod >= lo) & (sod <= hi)
    return mask


def bin_labels(edges: Sequence[float] = SIZE_EDGES_MM) -> list[str]:
    """``"55-100um"``-style labels, one per bin; the last is open-ended."""
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        top = "inf" if hi == float("inf") else f"{hi * 1000:g}"
        out.append(f"{lo * 1000:g}-{top}um")
    return out


def assign_bins(diam_mm, edges: Sequence[float] = SIZE_EDGES_MM) -> np.ndarray:
    """Bin index per particle, ``[lo, hi)``; -1 below the floor or not a number."""
    d = np.asarray(diam_mm, float)
    idx = np.digitize(d, edges) - 1
    idx[~np.isfinite(d) | (d < edges[0])] = -1
    return idx


def check_edges(edges: Sequence[float]) -> tuple[float, ...]:
    """``edges`` as a tuple, refused unless there are at least two and they strictly increase."""
    e = tuple(float(x) for x in edges)
    if len(e) < 2 or any(b <= a for a, b in zip(e[:-1], e[1:], strict=True)):
        raise ValueError(f"size edges must be at least two strictly increasing values, got {e}")
    return e


def draw(time_hhmmss, diam_mm, reject, *, windows: Sequence[tuple[int, int]],
         edges: Sequence[float] = SIZE_EDGES_MM, per_bin: int = PER_BIN, seed: int = SEED,
         accepted_codes: str | None = ACCEPTED_CODES) -> list[dict]:
    """Per bin: ``{"bin", "available", "requested", "taken", "under_filled", "indices"}``.

    ``accepted_codes=None`` keeps every image code. One generator, bins drawn in order, so the
    same arguments give the same queue on any machine.
    """
    if per_bin < 1:
        raise ValueError("per_bin must be at least 1")
    t = np.asarray(time_hhmmss).reshape(-1)
    d = np.asarray(diam_mm, float).reshape(-1)
    r = np.asarray(reject).reshape(-1)
    if not (t.size == d.size == r.size):
        raise ValueError("Time, image_diam_minR and image_auto_reject differ in length")
    eligible = in_windows(hhmmss_to_sod(t), windows)
    if accepted_codes is not None:
        eligible &= np.isin(r, [ord(c) for c in accepted_codes])
    bins = assign_bins(d, edges)
    rng = np.random.default_rng(seed)
    out = []
    for b, label in enumerate(bin_labels(edges)):
        cand = np.flatnonzero(eligible & (bins == b))
        if cand.size <= per_bin:
            pick = sorted(cand.tolist())
        else:
            pick = sorted(rng.choice(cand, size=per_bin, replace=False).tolist())
        out.append({"bin": label, "available": int(cand.size), "requested": per_bin,
                    "taken": len(pick), "under_filled": len(pick) < per_bin, "indices": pick})
    return out


def queue_items(strata, time_hhmmss, diam_mm, reject, flight: str,
                context: str = "window") -> list[dict]:
    """Queue entries in bin order, each with a note the reviewer sees beside the image."""
    items = []
    for s in strata:
        for i in s["indices"]:
            code = int(reject[i])
            code_s = chr(code) if 32 <= code < 127 else f"#{code}"
            size_um = float(diam_mm[i]) * 1000
            items.append({"flight": flight, "particle_index": int(i), "size_bin": s["bin"],
                          "note": f"{context}, {s['bin']}, minR {size_um:.0f} um, "
                                  f"code {code_s}, record time {int(time_hhmmss[i]):06d}"})
    return items


def write_queues(path: Path, queues: dict[str, list[dict]], coverage: dict[str, dict]) -> Path:
    """Add these queues and their coverage to ``path``, keeping every other queue in it."""
    path = Path(path)
    data: dict = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a queue file; refusing to replace it")
    data.update(queues)
    data.setdefault(COVERAGE_KEY, {}).update(coverage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    return path


def build(proc_name: str, time_hhmmss, diam_mm, reject, *, route: str, flight: str,
          windows: Sequence[tuple[int, int]], queue_stem: str,
          edges: Sequence[float] = SIZE_EDGES_MM, per_bin: int = PER_BIN, seed: int = SEED,
          accepted_codes: str = ACCEPTED_CODES, tool: str = "arrayprobe tune sample",
          context: str = "window") -> tuple[dict, dict]:
    """The two queues (accepted codes only, every code) and their coverage blocks."""
    in_win = in_windows(hhmmss_to_sod(time_hhmmss), windows)
    queues, coverage, picked = {}, {}, {}
    for kind, codes in (("accepted", accepted_codes), ("all", None)):
        strata = draw(time_hhmmss, diam_mm, reject, windows=windows, edges=edges,
                      per_bin=per_bin, seed=seed, accepted_codes=codes)
        name = f"{queue_stem}-{kind}-n{per_bin}-s{seed}"
        queues[name] = queue_items(strata, time_hhmmss, diam_mm, reject, flight, context)
        picked[kind] = {i for s in strata for i in s["indices"]}
        coverage[name] = {
            "tool": tool, "flight": flight,
            "proc_file": proc_name, "route": route, "seed": seed, "per_bin": per_bin,
            "windows_s_of_day_inclusive": [list(w) for w in windows],
            "size_floor_mm": edges[0], "size_edges_mm": [e if e != float("inf") else "inf"
                                                         for e in edges],
            "only_accepted": codes is not None, "accepted_codes": codes,
            "window_clock": WINDOW_CLOCK,
            "n_particles_file": int(np.asarray(time_hhmmss).size),
            "n_particles_in_windows": int(in_win.sum()),
            "n_particles": sum(s["taken"] for s in strata),
            "strata": [{k: v for k, v in s.items() if k != "indices"} for s in strata],
        }
    overlap = len(picked["accepted"] & picked["all"])
    for name in coverage:
        coverage[name]["overlap_between_the_two_queues"] = overlap
    return queues, coverage


def read_proc_columns(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``Time``, ``image_diam_minR`` and ``image_auto_reject`` from a proc file, flattened, raw."""
    import netCDF4

    with netCDF4.Dataset(path) as d:
        d.set_auto_mask(False)
        t = np.asarray(d["Time"][:]).reshape(-1)
        diam = np.asarray(d["image_diam_minR"][:], float).reshape(-1)
        rej = np.asarray(d["image_auto_reject"][:]).reshape(-1)
    return t, diam, rej


def flight_from_proc_name(name: str) -> str:
    """``proc.base180215125340.H.nc`` -> ``base180215125340.H`` (the triage server's flight)."""
    stem = Path(name).name
    if stem.startswith("proc."):
        stem = stem[len("proc."):]
    if stem.endswith(".nc"):
        stem = stem[:-len(".nc")]
    return stem


def summary_lines(coverage: dict[str, dict]) -> list[str]:
    """Per queue: particles taken, how many were in the windows, and each bin's fill."""
    lines = []
    for name, cov in coverage.items():
        lines.append(f"{name}: {cov['n_particles']} particles "
                     f"({cov['n_particles_in_windows']} of {cov['n_particles_file']} in windows)")
        for s in cov["strata"]:
            flag = "  UNDER-FILLED" if s["under_filled"] else ""
            lines.append(f"  {s['bin']:>12s} available {s['available']:8d} "
                         f"taken {s['taken']:3d}{flag}")
    return lines
