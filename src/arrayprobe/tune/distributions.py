# SPDX-License-Identifier: BSD-3-Clause
"""Per-particle distributions inside time windows of one proc file, active thresholds marked.

For the particles whose image-record header time (``Time``, HHMMSS) falls inside any window
(seconds of day, both ends included; parsed by :func:`arrayprobe.tune.sample.read_windows`), the
report gives:

* particles per second, all and at or above the review queues' size floor
  (:data:`arrayprobe.tune.sample.SIZE_EDGES_MM`'s first edge), with the fraction of window seconds
  holding more than 100 -- SODA-2's inter-arrival cutoff fit runs only for a period holding more
  than 100 particles (``soda2_particlesort.pro:92``);
* inter-arrival time in log bins, and the fraction at or below the probe case's shattering
  threshold (``defaultIntArrThresh``), overall and per size bin.  The mark says whether the
  case's gate (``applyIntArrThresh``) is on; where it is off the threshold has no effect on this
  probe case.  With no probe case given, no shattering threshold is marked;
* area ratio, ``image_area / (pi/4 * image_diam_minR^2)`` clipped at 1 as v3.5's
  ``sizeDist.m:1161`` does, per size bin, with the fraction below the area-ratio cut.  It is
  computed from the proc file's own diameter, so a size ``sizeDist`` later corrects (the hollow
  'H' division) differs;
* ``image_axis_ratio`` per size bin, with the fraction above each image-stage aspect-ratio
  ceiling.  The reject computes its own aspect ratio, so the reject-code counts, not this
  fraction, say what the reject did;
* ``image_auto_reject`` codes named in words, ``holroyd_habit`` codes and the hollow fraction,
  per size bin.

Diameters that are not finite (zero-area particles among them) get their own bin rather than
falling into the top one.  Every threshold mark carries the place its value was read from; the
report states no expected value.  Read-only: nothing here computes or changes a product.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from arrayprobe.matlab_compat import REJECT_CODE_WORDS
from arrayprobe.tune import sample

__all__ = [
    "SIZE_EDGES_MM",
    "IA_EDGES_S",
    "PERCENTILES",
    "PER_SECOND_LIMIT",
    "NONFINITE_LABEL",
    "BELOW_FLOOR_LABEL",
    "COLUMNS",
    "threshold_marks",
    "size_bins",
    "reject_code_counts",
    "habit_code_counts",
    "per_second_counts",
    "area_ratio",
    "report",
    "read_proc_columns",
    "summary_lines",
]

#: Size-bin edges, mm; the first bin starts at zero and the last is open-ended.
SIZE_EDGES_MM: tuple[float, ...] = (0.0, 0.055, 0.1, 0.2, 0.4, 1.0, float("inf"))
#: Inter-arrival histogram edges, s: 35 log-spaced bins from 1e-7 s to 1 s.
IA_EDGES_S = np.logspace(-7, 0, 36)
PERCENTILES = (10, 50, 90)
#: ``soda2_particlesort.pro:92``: the cutoff fit needs ``total(...) gt 100`` in a period.
PER_SECOND_LIMIT = 100
NONFINITE_LABEL = "non-finite diameter"
BELOW_FLOOR_LABEL = "below the first edge"
#: The proc-file columns read.
COLUMNS = ("Time", "image_diam_minR", "image_area", "image_auto_reject", "image_axis_ratio",
           "inter_arrival", "image_hollow", "holroyd_habit")

_SIZEDIST_M = "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"
_REJECT_M = "UIOPS-v3.5/joefinlon-UIOPS-039be82/calculate_reject_unified.m"


def threshold_marks(probe_case: Any = None, area_ratio_z: float | None = None) -> dict:
    """The thresholds that act on the reported quantities, each with where its value came from.

    ``area_ratio_z`` is a run's ``--area-ratio-z``; ``None`` takes v3.5's stock cut.  The
    shattering mark comes from ``probe_case`` through
    :func:`arrayprobe.tune.settings.resolve_probe_defaults`; ``None`` marks none.
    """
    from arrayprobe.tune import settings
    from arrayprobe_uiops import measure as v35_measure
    from arrayprobe_uiops import sizedist as v35_sizedist

    by_name = settings.settings_by_name()
    if area_ratio_z is None:
        ar = {"value": float(v35_sizedist.AREA_RATIO_Z),
              "source": f"arrayprobe_uiops.sizedist.AREA_RATIO_Z ({_SIZEDIST_M}:1162)"}
    else:
        ar = {"value": float(area_ratio_z), "source": "given (--area-ratio-z)"}
    ar["acts"] = "sizeDist rejects a particle whose area ratio is below this value (code 'z')"

    rc = v35_measure.STOCK_V35_REJECT_CONFIG
    marks: dict[str, Any] = {
        "area_ratio_z": ar,
        "max_comp_img_ar": {
            "value": float(rc.max_comp_img_ar),
            "source": f"arrayprobe_uiops.measure.STOCK_V35_REJECT_CONFIG ({_REJECT_M}:66)",
            "acts": by_name["max_comp_img_ar"].does},
        "max_edge_img_ar": {
            "value": float(rc.max_edge_img_ar),
            "source": f"arrayprobe_uiops.measure.STOCK_V35_REJECT_CONFIG ({_REJECT_M}:65)",
            "acts": by_name["max_edge_img_ar"].does},
    }
    if probe_case is None:
        marks["shattering"] = {"value": None, "probe_case": None,
                               "effect": "not marked: no probe case given (--probe-case)"}
    else:
        pd = settings.resolve_probe_defaults(probe_case)
        name = probe_case if isinstance(probe_case, str) else None
        marks["shattering"] = {
            "value": float(pd.defaultIntArrThresh),
            "probe_case": name,
            "applyIntArrThresh": int(pd.applyIntArrThresh),
            "effect": by_name["defaultIntArrThresh"].effect(pd).reason,
            "source": "the probe case's defaultIntArrThresh "
                      "(arrayprobe.tune.settings.resolve_probe_defaults)",
            "acts": by_name["defaultIntArrThresh"].does}
    return marks


def size_bins(diam_mm, edges: Sequence[float] = SIZE_EDGES_MM) -> tuple[np.ndarray, list[str]]:
    """Bin index per particle and the labels; the last two bins are below-floor and non-finite.

    ``np.digitize`` alone would put NaN and inf in the top bin; here they get their own.
    """
    d = np.asarray(diam_mm, float)
    labels = sample.bin_labels(edges)
    idx = sample.assign_bins(d, edges)
    idx[idx < 0] = len(labels)
    idx[~np.isfinite(d)] = len(labels) + 1
    return idx, labels + [BELOW_FLOOR_LABEL, NONFINITE_LABEL]


def _code_key(v: int) -> str:
    return chr(v) if 32 <= v < 127 else f"#{v}"


def reject_code_counts(codes) -> dict[str, dict]:
    """``{code: {"n", "meaning"}}``, the meaning from :data:`REJECT_CODE_WORDS`."""
    vals, n = np.unique(np.asarray(codes).astype(np.int64), return_counts=True)
    out = {}
    for v, c in zip(vals.tolist(), n.tolist(), strict=True):
        key = _code_key(v)
        out[key] = {"n": int(c), "meaning": REJECT_CODE_WORDS.get(key, "not a known reject code")}
    return out


def habit_code_counts(codes) -> dict[str, int]:
    """``{habit code: n}``."""
    vals, n = np.unique(np.asarray(codes).astype(np.int64), return_counts=True)
    return {_code_key(v): int(c) for v, c in zip(vals.tolist(), n.tolist(), strict=True)}


def per_second_counts(sod, windows: Sequence[tuple[int, int]]) -> np.ndarray:
    """Particles in each distinct window second, in order (a second in two windows counts once)."""
    secs = np.unique(np.concatenate([np.arange(lo, hi + 1) for lo, hi in windows]))
    s = np.sort(np.asarray(sod, np.int64))
    return np.searchsorted(s, secs, "right") - np.searchsorted(s, secs, "left")


def area_ratio(image_area, diam_mm) -> np.ndarray:
    """``image_area / (pi/4 * d^2)``, clipped at 1 by v3.5's own ``clip_area_ratio``."""
    from arrayprobe_uiops.sizedist import clip_area_ratio

    a = np.asarray(image_area, float)
    d = np.asarray(diam_mm, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return clip_area_ratio(a / (np.pi / 4 * d ** 2))


def _pct(x) -> dict[str, float]:
    x = np.asarray(x, float)
    return {str(p): float(np.percentile(x, p)) for p in PERCENTILES} if x.size else {}


def _frac(mask) -> float | None:
    mask = np.asarray(mask, bool)
    return float(mask.mean()) if mask.size else None


def report(cols: dict[str, np.ndarray], *, windows: Sequence[tuple[int, int]],
           marks: dict, edges: Sequence[float] = SIZE_EDGES_MM, proc_name: str = "") -> dict:
    """The distributions for the particles of ``cols`` (the :data:`COLUMNS`) inside ``windows``."""
    sod_all = sample.hhmmss_to_sod(np.asarray(cols["Time"]).reshape(-1))
    idx = np.flatnonzero(sample.in_windows(sod_all, windows))

    def get(name, dtype=None):
        a = np.asarray(cols[name]).reshape(-1)[idx]
        return a.astype(dtype) if dtype is not None else a

    sod = sod_all[idx]
    diam = get("image_diam_minR", float)
    ia = get("inter_arrival", float)
    axis = get("image_axis_ratio", float)
    arat = area_ratio(get("image_area", float), diam)
    rej, habit, hollow = get("image_auto_reject"), get("holroyd_habit"), get("image_hollow")
    sbin, labels = size_bins(diam, edges)

    floor = sample.SIZE_EDGES_MM[0]
    pa = per_second_counts(sod, windows)
    pb = per_second_counts(sod[diam >= floor], windows)
    ia_thr = marks["shattering"]["value"]
    z = marks["area_ratio_z"]["value"]
    axis_marks = {k: marks[k]["value"] for k in ("max_comp_img_ar", "max_edge_img_ar")}

    fin = np.isfinite(ia) & (ia > 0)
    ia_block: dict[str, Any] = {
        "edges_s": IA_EDGES_S.tolist(),
        "counts": np.histogram(ia[fin], IA_EDGES_S)[0].tolist(),
        "nonpositive_or_nonfinite": int((~fin).sum()),
        "threshold_s": ia_thr,
        "threshold_effect": marks["shattering"]["effect"],
    }
    if ia_thr is not None:
        ia_block["fraction_at_or_below_threshold"] = _frac(ia[fin] <= ia_thr)
        ia_block["fraction_at_or_below_threshold_by_size"] = {
            lab: _frac(ia[fin & (sbin == b)] <= ia_thr) for b, lab in enumerate(labels)}

    by_size: dict[str, dict] = {}
    for b, lab in enumerate(labels):
        m = sbin == b
        if not m.any():
            by_size[lab] = {"n": 0}
            continue
        ar = arat[m][np.isfinite(arat[m])]
        ax = axis[m][np.isfinite(axis[m])]
        by_size[lab] = {
            "n": int(m.sum()),
            "area_ratio_percentiles": _pct(ar),
            "area_ratio_not_finite": int(m.sum() - ar.size),
            "area_ratio_fraction_below_cut": _frac(ar < z),
            "area_ratio_hist_0_to_1_by_0.1": np.histogram(ar, np.linspace(0, 1, 11))[0].tolist(),
            "axis_ratio_percentiles": _pct(ax),
            **{f"axis_ratio_fraction_above_{k}": _frac(ax > v) for k, v in axis_marks.items()},
            "reject_codes": reject_code_counts(rej[m]),
            "habit_codes": habit_code_counts(habit[m]),
            "hollow_fraction": _frac(hollow[m] == 1),
        }

    return {
        "tool": "arrayprobe tune distributions",
        "proc_file": proc_name,
        "window_clock": sample.WINDOW_CLOCK,
        "windows_s_of_day_inclusive": [list(w) for w in windows],
        "window_seconds": int(pa.size),
        "n_particles_file": int(sod_all.size),
        "n_particles_in_windows": int(idx.size),
        "size_edges_mm": [e if math.isfinite(e) else "inf" for e in edges],
        "thresholds": marks,
        "per_second": {
            "all": _pct(pa),
            f"at_or_above_{floor:g}mm": _pct(pb),
            f"fraction_of_window_seconds_over_{PER_SECOND_LIMIT}_all": _frac(pa > PER_SECOND_LIMIT),
            "limit_source": "soda2_particlesort.pro:92 (the inter-arrival cutoff fit needs more "
                            f"than {PER_SECOND_LIMIT} particles in a period)",
        },
        "inter_arrival": ia_block,
        "by_size": by_size,
    }


def read_proc_columns(path: Path) -> dict[str, np.ndarray]:
    """The :data:`COLUMNS` of a proc file, flattened, raw (no masking or scaling)."""
    import netCDF4

    with netCDF4.Dataset(path) as d:
        d.set_auto_mask(False)
        missing = [c for c in COLUMNS if c not in d.variables]
        if missing:
            raise ValueError(f"{Path(path).name} has no {', '.join(missing)}")
        return {c: np.asarray(d[c][:]).reshape(-1) for c in COLUMNS}


def summary_lines(rep: dict) -> list[str]:
    """A few lines for the terminal: counts, the marks and, per size bin, the cut fractions."""
    th = rep["thresholds"]
    lines = [f"{rep['n_particles_in_windows']} of {rep['n_particles_file']} particles in "
             f"{len(rep['windows_s_of_day_inclusive'])} windows ({rep['window_seconds']} s)"]
    sh = th["shattering"]
    lines.append(f"shattering threshold: {sh['value']} s -- {sh['effect']}")
    if sh["value"] is not None:
        lines.append("  inter-arrival at or below it: "
                     f"{rep['inter_arrival']['fraction_at_or_below_threshold']}")
    lines.append(f"area-ratio cut {th['area_ratio_z']['value']:g}; aspect-ratio ceilings "
                 f"{th['max_comp_img_ar']['value']:g} (contained), "
                 f"{th['max_edge_img_ar']['value']:g} (edge)")
    for lab, r in rep["by_size"].items():
        if not r["n"]:
            continue
        below = r["area_ratio_fraction_below_cut"]
        below_s = "n/a" if below is None else f"{below:.3f}"
        codes = ", ".join(f"{k} {v['n']}" for k, v in r["reject_codes"].items())
        lines.append(f"  {lab:>20s}: n={r['n']:>8d}  area ratio below cut {below_s}  "
                     f"codes {codes}")
    return lines
