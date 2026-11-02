# SPDX-License-Identifier: BSD-3-Clause
"""Gross-failure sanity check for size-distribution (sd) and particle (proc) netCDF files.

Built after a CIP v3.5 sd came out entirely empty because its proc's
``particle_time`` was never shifted to UTC: every second of the sd was NaN or
zero and nothing downstream complained. This tool catches that class of
failure on any UIOOPS-style product (v3.1.4 or v3.5 sd/proc, combined
products) without importing any engine: netCDF4 and numpy only.

Per file it prints:

* sd: fraction of seconds with ``n > 0``, fraction with a nonzero total
  concentration (``conc_minR``, else ``count``), an all-zero/all-NaN verdict,
  fraction of bins empty in every second, time-axis monotonicity and span;
* proc: fraction of particles whose ``particle_time`` lies within the span of
  the record time axis ``Time``, its monotonicity and span;
* image (decoded raw, ``data`` + ``hour/minute/second``): time span only;
* whether a ``.call`` sidecar exists and names ``engine=``.

Each file gets OK, ANOMALY (with reasons) or SKIP (variables not
recognised). Exit status is 1 if any file is ANOMALY, else 0. Read-only.

    python -m arrayprobe_uiops.product_sanity FILE [FILE ...]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# A proc is anomalous when fewer than this fraction of its particles fall in
# the record-time span; an sd when fewer than this fraction of seconds carry
# particles is reported but not flagged (sparse cloud is legitimate).
MIN_PARTICLE_TIME_ON_AXIS = 0.5


@dataclass
class Report:
    path: str
    kind: str = "unknown"
    facts: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.kind == "unknown":
            return "SKIP"
        return "ANOMALY" if self.reasons else "OK"


def hhmmss_to_sod(v: np.ndarray) -> np.ndarray:
    """HHMMSS (possibly fractional, possibly >= 240000 after a rollover) to seconds."""
    v = np.asarray(v, dtype=float)
    whole = np.floor(v)
    h = np.floor(whole / 10000.0)
    m = np.floor(whole / 100.0) % 100
    s = whole % 100 + (v - whole)
    return h * 3600 + m * 60 + s


def _read(ds: Any, name: str) -> Any:
    var = ds.variables[name]
    var.set_auto_mask(False)
    a = np.asarray(var[:], dtype=float)
    fill = getattr(var, "_FillValue", None)
    if fill is not None:
        a = np.where(a == float(fill), np.nan, a)
    return a


def _call_stamp(path: str) -> str:
    call = path + ".call"
    if not os.path.exists(call):
        return "absent"
    try:
        with open(call, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return "unreadable"
    m = re.search(r"engine=(\S+)", text)
    return f"engine={m.group(1)}" if m else "present, no engine="


def _axis_facts(rep: Report, t: np.ndarray, label: str) -> None:
    finite = t[np.isfinite(t)]
    if finite.size == 0:
        rep.reasons.append(f"{label} time axis has no finite values")
        return
    mono = bool(np.all(np.diff(finite) >= 0))
    rep.facts[f"{label}_monotonic"] = mono
    rep.facts[f"{label}_span"] = f"{finite.min():.0f}-{finite.max():.0f}"
    if not mono:
        rep.reasons.append(f"{label} time axis is not monotonic")


def check_sd(ds: Any, rep: Report) -> None:
    rep.kind = "sd"
    tname = "time" if "time" in ds.variables else "Time"
    t = _read(ds, tname)
    nsec = t.size
    rep.facts["seconds"] = nsec
    _axis_facts(rep, t, "time")
    if nsec == 0:
        rep.reasons.append("time axis is empty")
        return
    frac_n = None
    if "n" in ds.variables:
        n = _read(ds, "n").reshape(nsec, -1)
        frac_n = float(np.mean(np.nansum(n, axis=1) > 0))
        rep.facts["frac_n_pos"] = round(frac_n, 4)
    cname = next((c for c in ("conc_minR", "count") if c in ds.variables), None)
    frac_c = None
    if cname is not None:
        c = _read(ds, cname).reshape(nsec, -1)
        allnan = bool(np.all(np.isnan(c)))
        frac_nan_rows = float(np.mean(np.all(np.isnan(c), axis=1)))
        tot = np.nansum(c, axis=1)
        frac_c = float(np.mean(tot > 0))
        rep.facts[f"frac_{cname}_pos"] = round(frac_c, 4)
        rep.facts["frac_rows_all_nan"] = round(frac_nan_rows, 4)
        bins_empty = np.nansum(c, axis=0) <= 0
        rep.facts["frac_bins_always_empty"] = round(float(np.mean(bins_empty)), 4)
        if allnan:
            rep.reasons.append(f"{cname} is NaN everywhere")
    if frac_n is None and frac_c is None:
        rep.kind = "unknown"
        return
    if not (frac_n or frac_c):
        rep.reasons.append("no second has n>0 or a nonzero concentration (all zero/NaN)")


def check_proc(ds: Any, rep: Report) -> None:
    rep.kind = "proc"
    pt = _read(ds, "particle_time")
    rep.facts["particles"] = pt.size
    if pt.size == 0:
        rep.reasons.append("no particles")
        return
    if "Time" in ds.variables:
        rec = hhmmss_to_sod(_read(ds, "Time"))
        rec = rec[np.isfinite(rec)]
        _axis_facts(rep, _read(ds, "Time"), "Time")
    else:
        rec = np.array([])
    ptf = pt[np.isfinite(pt)]
    rep.facts["particle_time_span"] = (
        f"{ptf.min():.0f}-{ptf.max():.0f}" if ptf.size else "none finite")
    if rec.size == 0 or ptf.size == 0:
        rep.reasons.append("no finite record Time or particle_time to compare")
        return
    psod = hhmmss_to_sod(ptf)
    lo, hi = rec.min(), rec.max()
    frac = float(np.mean((psod >= lo - 1) & (psod <= hi + 1)))
    rep.facts["frac_particle_time_on_axis"] = round(frac, 4)
    rep.facts["median_offset_s"] = round(float(np.median(psod) - np.median(rec)), 1)
    if frac < MIN_PARTICLE_TIME_ON_AXIS:
        rep.reasons.append(
            f"only {frac:.2%} of particle_time lies in the record Time span "
            f"(median offset {rep.facts['median_offset_s']:+.0f} s)")


def check_image(ds: Any, rep: Report) -> None:
    rep.kind = "image"
    sod = _read(ds, "hour") * 3600 + _read(ds, "minute") * 60 + _read(ds, "second")
    rep.facts["records"] = sod.size
    if sod.size:
        rep.facts["span_sod"] = f"{np.nanmin(sod):.0f}-{np.nanmax(sod):.0f}"


def check_file(path: str) -> Report:
    import netCDF4

    rep = Report(path)
    try:
        ds = netCDF4.Dataset(path)
    except OSError as exc:
        rep.facts["error"] = str(exc)
        return rep
    try:
        names = set(ds.variables)
        if "particle_time" in names:
            check_proc(ds, rep)
        elif names & {"conc_minR", "count", "n"}:
            check_sd(ds, rep)
        elif {"data", "hour", "minute", "second"} <= names:
            check_image(ds, rep)
    finally:
        ds.close()
    if rep.kind != "unknown":
        rep.facts["call"] = _call_stamp(path)
    return rep


def format_report(rep: Report) -> str:
    facts = " ".join(f"{k}={v}" for k, v in rep.facts.items())
    line = f"{rep.verdict:7s} [{rep.kind}] {rep.path}\n        {facts}"
    for r in rep.reasons:
        line += f"\n        ! {r}"
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    bad = 0
    for f in args.files:
        rep = check_file(f)
        print(format_report(rep))
        bad += rep.verdict == "ANOMALY"
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())


# --- The batch driver's post-S4 plausibility gate -----------------------------------
#: Below this fraction of seconds carrying particles, an sd built from a proc that holds accepted
#: particles is implausible and the driver refuses it (exit 2). 2026-10-04: an all-zero CIP sd and
#: near-empty v3.5 2D-S sds were written with exit 0 and caught only by luck.
MIN_FRAC_SECONDS_WITH_PARTICLES = 0.001
#: Below this many accepted particles an empty sd is not evidence of a fault: sizeDist's own
#: rejections (shattering, size range, TAS axis) can legitimately drop a handful. The demo flight
#: (3 accepted particles, 0 seconds with particles in its sd) is valid; the 2026-10-04 empty CIP sd
#: had 3,797,537 accepted particles.
MIN_ACCEPTED_FOR_REFUSAL = 100
#: A value at or above this is MATLAB's realmax written as a number, not a measurement.
REALMAX_LIKE = 1e300


@dataclass
class Plausibility:
    seconds: int
    frac_pos: float
    nonfinite_seconds: int
    duplicated_seconds: int
    bins: int
    accepted_particles: int | None
    implausible: bool
    reason: str = ""

    def token(self) -> str:
        """One space-free ``.call`` stamp token."""
        acc = "na" if self.accepted_particles is None else str(self.accepted_particles)
        return (f"plausibility=(sec={self.seconds},pos={self.frac_pos:.4f},"
                f"nonfinite={self.nonfinite_seconds},dup={self.duplicated_seconds},"
                f"bins={self.bins},accepted={acc},"
                f"{'IMPLAUSIBLE' if self.implausible else 'ok'})")


def accepted_seconds(proc_path: str | os.PathLike[str]) -> int | None:
    """Distinct seconds (``floor(particle_time)``) holding an accepted particle, else None. The
    denominator for a short or sparse flight: the sd cannot carry particles in more seconds than
    the proc accepted particles in, whatever the length of its time axis."""
    import netCDF4

    with netCDF4.Dataset(proc_path) as ds:
        if "particle_time" not in ds.variables:
            return None
        t = np.asarray(_read(ds, "particle_time"), dtype=float).reshape(-1)
        if "image_auto_reject" in ds.variables:
            rej = np.asarray(_read(ds, "image_auto_reject")).reshape(-1)
            if rej.size == t.size:
                t = t[np.isin(rej, [ord(c) for c in "0HhuR"])]
    t = t[np.isfinite(t)]
    return int(np.unique(np.floor(t)).size)


def accepted_particles(proc_path: str | os.PathLike[str]) -> int | None:
    """Particles a proc accepted (``image_auto_reject`` in ``'0HhuR'``, the codes sizeDist keeps),
    else all particles, else None."""
    import netCDF4

    with netCDF4.Dataset(proc_path) as ds:
        if "image_auto_reject" in ds.variables:
            rej = _read(ds, "image_auto_reject")
            return int(np.count_nonzero(np.isin(rej, [ord(c) for c in "0HhuR"])))
        if "particle_time" in ds.variables:
            return int(ds.variables["particle_time"].size)
    return None


def _per_second(a: np.ndarray, nsec: int) -> np.ndarray:
    """``a`` as (seconds, columns) whichever axis the file put the time dimension on: a
    MATLAB-declared (Time, bins) variable is (bins, Time) in the file, so reshaping blindly would
    scramble seconds and bins."""
    if a.ndim == 2 and a.shape[0] != nsec and a.shape[1] == nsec:
        a = a.T
    return a.reshape(nsec, -1)


def sd_plausibility(sd_path: str | os.PathLike[str], accepted: int | None = None,
                    min_frac: float = MIN_FRAC_SECONDS_WITH_PARTICLES,
                    accepted_secs: int | None = None,
                    min_accepted: int = MIN_ACCEPTED_FOR_REFUSAL) -> Plausibility:
    """Plausibility of one sd: seconds with particles, non-finite/realmax seconds, duplicated
    seconds and bin count. Implausible when no second (or fewer than ``min_frac``) carries
    particles while the proc behind it accepted at least ``min_accepted`` (``None`` = unknown,
    treated as enough). The fraction is of ``min(seconds, accepted_secs)`` when the proc's
    accepted seconds are known, so a short or sparse but valid flight is not refused for the
    length of its axis."""
    import netCDF4

    with netCDF4.Dataset(sd_path) as ds:
        tname = "time" if "time" in ds.variables else "Time"
        t = _read(ds, tname).reshape(-1) if tname in ds.variables else np.array([])
        nsec = t.size
        cname = next((c for c in ("conc_minR", "count") if c in ds.variables), None)
        c = _per_second(_read(ds, cname), nsec) if cname and nsec else np.zeros((nsec, 0))
        n = _per_second(_read(ds, "n"), nsec) if "n" in ds.variables and nsec else None
    bins = int(c.shape[1]) if c.ndim == 2 else 0
    rows = c if n is None else np.concatenate([c, n], axis=1)
    bad = ~np.isfinite(rows) & ~np.isnan(rows) | (np.abs(np.nan_to_num(rows)) >= REALMAX_LIKE)
    nonfinite = int(np.count_nonzero(bad.any(axis=1))) if rows.size else 0
    clean = np.where(bad, np.nan, rows)
    pos = (np.nansum(np.where(clean > 0, clean, 0), axis=1) > 0
           if rows.size else np.zeros(nsec, bool))
    frac = float(pos.mean()) if nsec else 0.0
    dup = int(nsec - np.unique(np.floor(t[np.isfinite(t)])).size) if nsec else 0
    denom = min(nsec, accepted_secs) if accepted_secs else nsec
    frac_gate = float(pos.sum()) / denom if denom else 0.0
    reason = ""
    if accepted is None or accepted >= min_accepted:
        if nsec == 0:
            reason = "the sd has no seconds"
        elif not pos.any():
            reason = "no second has particles (all zero/NaN)"
        elif frac_gate < min_frac:
            reason = (f"only {int(pos.sum())} of {denom} seconds carry particles "
                      f"({frac_gate:.4%}, threshold {min_frac:.1%})")
    return Plausibility(nsec, frac, nonfinite, dup, bins, accepted, bool(reason), reason)
