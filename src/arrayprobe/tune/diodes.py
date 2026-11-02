# SPDX-License-Identifier: BSD-3-Clause
"""Stuck diodes in one proc file: ``bin_stats`` as lit counts, run through the fork's rule.

The ORACLES chain's ``find_shadow_diodes.m`` reads ``bin_stats`` from an imgProc output and flags
a diode that reads lit on fewer slices than the others
(:func:`arrayprobe_uiops.diode_mask.stuck_diodes`, ``find_shadow_diodes.m:66-97``).  The rule is
written for **lit** counts, and which slices a proc file's ``bin_stats`` counts depends on what
wrote it:

* the ORACLES fork's ``imgProc_sm.m:387-388`` sums ``c=='1'`` (lit) -- a v3.1.4 profile with
  ``diode_stats_counts_shadowed=False``;
* stock v3.1.4 (``imgProc_sm.m:804-805``) and the v3.5 engine (``arrayprobe_uiops/measure.py``,
  v3.5 ``imgProc_sm.m:1207-1211``) sum ``c=='0'`` (shadowed).

A shadow count is converted as ``lit_i = S - shadow_i``: every diode sees every slice of every
particle, so ``S``, the total slice count of the particles that fed ``bin_stats``, is common to
all diodes.  ``S`` is read from the proc file's ``position`` (start and end slice of each
particle within its image record, v3.5 ``imgProc_sm.m:856``) as
``sum(end - start + 1 - image_slice_offset)``, the offset being the probe's
(``arrayprobe_uiops.imgproc.PROBES_V35``, ``:764-795``).  Feeding the rule an unconverted shadow
count flags the healthiest diodes instead of the stuck ones.

**Provenance.** The engine and profile come from the file's own provenance attributes or its
``.call`` sidecar (:mod:`arrayprobe_uiops.provenance`); the two carriers must agree.  A stamp with
no
``engine=`` key, or no stamp at all, is read as v3.1.4 (the repository's rule for products
stamped before 2026-09-15 and for MATLAB-written products).  v3.1.4 has profiles of both
conventions, so where the stamp names no profile the caller must name one (``profile=``); the
convention is never defaulted.  SODA-2 products carry no ``bin_stats`` and are refused.

Read-only: nothing here writes a product or changes a computed number.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "RULE_SOURCE",
    "DiodeReportError",
    "counting_convention",
    "slice_offset",
    "lit_counts",
    "position_slice_total",
    "report",
    "report_from_counts",
    "toml_line",
    "summary_lines",
]

#: Where the rule's two branches and its high-count test live (promoted ``.m`` line numbers).
RULE_SOURCE = {
    "max": "find_shadow_diodes.m:97 (a < int32(STUCK_FRACTION*max(a)))",
    "mean": "find_shadow_diodes.m:94 (a < STUCK_FRACTION*mean(a), after :66-69)",
    "high": "find_shadow_diodes.m:66 (a > HIGH_FRACTION*mean(a))",
}

_LIT_SOURCE = "ORACLES fork imgProc_sm.m:387-388 (sum(c=='1'))"
_SHADOW_SOURCE = {
    "3.5": "arrayprobe_uiops/measure.py (v3.5 imgProc_sm.m:1207-1211, sum(c=='0'))",
    "3.1.4": "stock v3.1.4 imgProc_sm.m:804-805 (sum(c=='0'))",
}


class DiodeReportError(ValueError):
    """A proc file whose ``bin_stats`` convention or slice total cannot be established."""


def _stamp_of(path: Path):
    """The file's stamp from either carrier, refusing when both exist and disagree."""
    from arrayprobe_uiops import provenance

    sidecar = provenance.read(path)
    try:
        inside = provenance.read_in_file_stamp(path)
    except (OSError, RuntimeError, ValueError):
        inside = None
    diffs = provenance.disagreements(sidecar, inside)
    if diffs:
        raise provenance.ProvenanceDisagreement(path, diffs)
    if sidecar is not None and sidecar.format == "unparseable":
        raise DiodeReportError(f"{path.name}: its .call sidecar cannot be parsed: {sidecar.raw!r}")
    return sidecar if sidecar is not None else inside


def counting_convention(path: Path | str, profile: str | None = None) -> dict[str, Any]:
    """Which slices ``path``'s ``bin_stats`` counts, and how that was established.

    Returns ``{"engine", "engine_source", "profile", "shadowed", "convention_source"}``.
    ``profile`` names the v3.1.4 profile when the stamp names none; when the stamp names one,
    a different ``profile`` is refused.
    """
    from arrayprobe import profiles

    path = Path(path)
    stamp = _stamp_of(path)
    if stamp is None:
        engine, engine_source = "3.1.4", "no stamp: read as v3.1.4"
        stamped_profile = None
    else:
        stamped_profile = stamp.profile
        if stamp.engine is not None:
            engine, engine_source = stamp.engine, f"stamp ({stamp.format})"
        else:
            engine, engine_source = "3.1.4", "stamp names no engine: read as v3.1.4"
    if engine == "soda2":
        raise DiodeReportError(f"{path.name}: a SODA-2 product carries no bin_stats")
    if stamped_profile and profile and stamped_profile != profile:
        raise DiodeReportError(
            f"{path.name}: the stamp names profile {stamped_profile!r}, not {profile!r}")
    chosen = stamped_profile or profile

    if engine == "3.5":
        return {"engine": engine, "engine_source": engine_source, "profile": chosen,
                "shadowed": True, "convention_source": _SHADOW_SOURCE["3.5"]}
    if not chosen:
        raise DiodeReportError(
            f"{path.name}: engine 3.1.4 ({engine_source}) and no profile named; v3.1.4 profiles "
            "count lit slices (the ORACLES fork) or shadowed ones (stock), so name the profile")
    try:
        prof = profiles.profile(chosen)
    except KeyError as exc:
        raise DiodeReportError(f"{path.name}: {exc.args[0]}") from None
    shadowed = bool(prof.diode_stats_counts_shadowed)
    return {"engine": engine, "engine_source": engine_source, "profile": chosen,
            "shadowed": shadowed,
            "convention_source": (_SHADOW_SOURCE["3.1.4"] if shadowed else _LIT_SOURCE)
            + f"; profile {chosen}.diode_stats_counts_shadowed={shadowed}"}


def slice_offset(n_diodes: int, probe: str | None = None) -> tuple[int, str]:
    """The probe's ``image_slice_offset`` and where it came from.

    With ``probe`` given, its :data:`~arrayprobe_uiops.imgproc.PROBES_V35` entry.  Without, the
    offset shared by every probe of ``n_diodes`` diodes; refused when those probes differ.
    """
    from arrayprobe_uiops.imgproc import PROBES_V35

    if probe is not None:
        if probe not in PROBES_V35:
            raise DiodeReportError(f"unknown probe {probe!r}; known: {', '.join(PROBES_V35)}")
        return int(PROBES_V35[probe].image_slice_offset), f"PROBES_V35[{probe!r}]"
    same = {name: int(p.image_slice_offset) for name, p in PROBES_V35.items()
            if int(p.diodenum) == n_diodes}
    offsets = set(same.values())
    if len(offsets) != 1:
        raise DiodeReportError(
            f"{n_diodes} diodes: the probes of that width ({', '.join(same) or 'none'}) do not "
            "share one image_slice_offset; name the probe")
    return offsets.pop(), f"every {n_diodes}-diode probe in PROBES_V35 ({', '.join(same)})"


#: Rows of ``position`` read per block when ``S`` is computed from a file.
POSITION_BLOCK_ROWS = 1_000_000
#: Below this many rows ``S`` is computed in this process; above it, across worker processes.
PARALLEL_MIN_ROWS = 2_000_000

#: The parallel read's wall-clock allowance per row a worker reads: 10x the ~20 us a row
#: measured on the unchunked layout (2026-10-01), so a slow disk is not mistaken for a hang.
PARALLEL_ROW_ALLOWANCE_S = 200e-6

#: The parallel read's timeout never falls below this, so worker spawn and import are covered.
PARALLEL_TIMEOUT_FLOOR_S = 120.0


def _read(path: Path) -> tuple[np.ndarray, tuple[int, int] | None]:
    """``bin_stats`` (raw), and ``(n_rows, pos_axis)`` for ``position`` or ``None`` if absent.

    ``position`` itself is not read here: :func:`position_slice_total` reads it in blocks.
    """
    from netCDF4 import Dataset

    with Dataset(path, "r") as ds:
        if "bin_stats" not in ds.variables:
            raise DiodeReportError(f"{path.name}: no bin_stats variable")
        var = ds.variables["bin_stats"]
        var.set_auto_maskandscale(False)
        bin_stats = np.asarray(var[:]).reshape(-1)
        position = None
        if "position" in ds.variables:
            pv = ds.variables["position"]
            if len(pv.dimensions) == 2 and "pos_count" in pv.dimensions:
                axis = pv.dimensions.index("pos_count")
                position = (int(pv.shape[1 - axis]), axis)
    return bin_stats, position


def _block_total(block, offset: int) -> int:
    """``sum(end - start + 1 - offset)`` over one ``(n, 2)`` block, in int64."""
    pos = np.asarray(block, dtype=np.int64).reshape(-1, 2)
    return int(np.sum(pos[:, 1] - pos[:, 0] + 1 - offset, dtype=np.int64))


def _range_total(path: str, axis: int, offset: int, lo: int, hi: int, block_rows: int) -> int:
    """``S`` over rows ``[lo, hi)`` of ``path``'s ``position``, read ``block_rows`` at a time."""
    from netCDF4 import Dataset

    total = 0
    with Dataset(path, "r") as ds:
        pv = ds.variables["position"]
        pv.set_auto_maskandscale(False)
        for a in range(lo, hi, block_rows):
            b = min(a + block_rows, hi)
            block = np.asarray(pv[a:b, :] if axis == 1 else pv[:, a:b].T)
            total += _block_total(block, offset)
    return total


def position_slice_total(path: Path | str, offset: int, *, block_rows: int = POSITION_BLOCK_ROWS,
                         jobs: int | None = None) -> int | None:
    """``S = sum(end - start + 1 - offset)`` over ``path``'s ``position``, ``None`` if absent.

    Read in contiguous blocks of ``block_rows`` rows and summed in int64, so the result equals
    the whole-array sum exactly.  A proc file written before the v3.5 writer chunked
    ``position`` in ``[1024, 2]`` blocks stores it one particle per HDF5 chunk, and reading
    it costs ~20 us a row (measured on a 17.8 M-particle file), so
    ``jobs`` worker processes each read a share of the rows; ``None`` picks
    ``min(cpu_count, 8)`` above :data:`PARALLEL_MIN_ROWS` rows and one process below.
    """
    import os

    path = Path(path)
    _, position = _read(path)
    if position is None:
        return None
    n, axis = position
    if block_rows < 1:
        raise ValueError(f"block_rows must be positive, not {block_rows}")
    if jobs is None:
        jobs = min(os.cpu_count() or 1, 8) if n >= PARALLEL_MIN_ROWS else 1
    jobs = max(1, min(int(jobs), -(-n // block_rows) if n else 1))
    if jobs == 1:
        return _range_total(str(path), axis, offset, 0, n, block_rows)
    total, why = _parallel_total(str(path), axis, offset, n, jobs, block_rows)
    if total is None:
        logging.getLogger(__name__).warning(
            "arrayprobe tune diodes: the parallel read of %s's position failed (%s); "
            "reading it serially", path.name, why)
        return _range_total(str(path), axis, offset, 0, n, block_rows)
    return total


def _parallel_timeout(n: int, jobs: int, block_rows: int) -> float:
    """Seconds the parallel read may take before it is abandoned for the serial one.

    ``max(PARALLEL_TIMEOUT_FLOOR_S, blocks * rows_per_block * PARALLEL_ROW_ALLOWANCE_S)``, where
    ``blocks = ceil(share / block_rows)`` is the block count of the largest worker's share
    ``share = ceil(n / jobs)`` and ``rows_per_block = min(block_rows, share)``.  For 17.8 M rows
    over 8 workers in 1 M-row blocks: 3 blocks x 1 M rows x 200 us = 600 s.
    """
    share = -(-n // jobs)
    blocks = -(-share // block_rows)
    return max(PARALLEL_TIMEOUT_FLOOR_S, blocks * min(block_rows, share) * PARALLEL_ROW_ALLOWANCE_S)


def _parallel_total(path: str, axis: int, offset: int, n: int, jobs: int,
                    block_rows: int) -> tuple[int | None, str]:
    """``S`` across ``jobs`` worker processes, or ``(None, why)`` when the pool fails.

    Bounded: the results are awaited for :func:`_parallel_timeout` seconds at most, because
    Windows workers that die at spawn (``OSError: [WinError 6] The handle is invalid``) leave
    ``ProcessPoolExecutor`` waiting forever.  A timeout, a ``BrokenProcessPool`` or an
    ``OSError`` returns ``None`` and the caller reads serially; any other worker exception
    propagates.  A failed pool is shut down without waiting and its workers terminated.
    """
    import concurrent.futures as cf
    from concurrent.futures.process import BrokenProcessPool

    edges = [n * k // jobs for k in range(jobs + 1)]
    timeout = _parallel_timeout(n, jobs, block_rows)
    pool = None
    ok = False
    try:
        pool = cf.ProcessPoolExecutor(max_workers=jobs)
        parts = [pool.submit(_range_total, path, axis, offset, edges[k], edges[k + 1],
                             block_rows) for k in range(jobs)]
        done, pending = cf.wait(parts, timeout=timeout, return_when=cf.FIRST_EXCEPTION)
        for f in done:
            f.result()  # re-raises a worker's exception
        if pending:
            return None, f"no result within {timeout:.0f} s"
        total = sum(f.result() for f in parts)
        ok = True
        return total, ""
    except (BrokenProcessPool, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        if pool is not None:
            if ok:
                pool.shutdown(wait=True)
            else:
                pool.shutdown(wait=False, cancel_futures=True)
                # Python 3.12 has no public way to stop a running worker (3.14 adds
                # kill_workers); without this, interpreter exit joins a stalled worker.
                for proc in list((getattr(pool, "_processes", None) or {}).values()):
                    try:
                        proc.terminate()
                    except Exception:  # noqa: BLE001 - best effort on a pool already failed
                        pass


def lit_counts(bin_stats, *, shadowed: bool, position=None, offset: int = 0,
               total: int | None = None) -> tuple[np.ndarray, int | None]:
    """``bin_stats`` as lit counts, and ``S`` (``None`` when the counts were already lit).

    ``S`` comes from ``position`` (an ``(n, 2)`` start/end array) or, already summed, ``total``.
    """
    counts = np.asarray(bin_stats, dtype=np.int64).reshape(-1)
    if not shadowed:
        return counts, None
    if total is None:
        if position is None:
            raise DiodeReportError("a shadow count needs the proc file's position to compute S")
        total = _block_total(position, offset)
    total = int(total)
    if counts.size and int(counts.max()) > total:
        raise DiodeReportError(
            f"a shadow count ({int(counts.max())}) exceeds the slice total S={total}: "
            "position does not describe the particles that fed bin_stats")
    return total - counts, total


def report_from_counts(lit) -> dict[str, Any]:
    """The rule's verdict on lit counts, per diode and overall."""
    from arrayprobe_uiops import diode_mask

    lit = np.asarray(lit, dtype=np.int64).reshape(-1)
    rule = diode_mask.stuck_diodes(lit)
    flagged = [int(d) for d in rule.shadow_diode]
    mean = float(np.mean(lit.astype(np.float64)))
    peak = float(lit.max())
    per_diode = [
        {"diode": i + 1, "lit": int(v), "saved": int(rule.a[i]),
         "fraction_of_max": float(v) / peak if peak else None,
         "fraction_of_mean": float(v) / mean if mean else None,
         "flagged": (i + 1) in flagged}
        for i, v in enumerate(lit)
    ]
    return {
        "n_diodes": int(lit.size),
        "flagged": flagged,
        "ill_diode": [int(d) for d in rule.ill_diode],
        "branch": rule.branch,
        "threshold": rule.threshold,
        "stuck_fraction": diode_mask.STUCK_FRACTION,
        "high_fraction": diode_mask.HIGH_FRACTION,
        "rule_source": RULE_SOURCE[rule.branch],
        "high_source": RULE_SOURCE["high"],
        "per_diode": per_diode,
    }


def report(path: Path | str, *, profile: str | None = None, probe: str | None = None,
           jobs: int | None = None) -> dict[str, Any]:
    """The stuck-diode report for one proc file (see the module docstring)."""
    path = Path(path)
    conv = counting_convention(path, profile)
    bin_stats, _ = _read(path)
    offset, offset_source, total = (None, None, None)
    if conv["shadowed"]:
        offset, offset_source = slice_offset(bin_stats.size, probe)
        total = position_slice_total(path, offset, jobs=jobs)
    lit, total = lit_counts(bin_stats, shadowed=conv["shadowed"], offset=offset or 0,
                            total=total)
    out = {"proc": str(path), **conv,
           "counts": "shadowed, converted lit = S - shadow" if conv["shadowed"] else "lit",
           "S": total, "image_slice_offset": offset, "offset_source": offset_source}
    out.update(report_from_counts(lit))
    return out


def toml_line(stem: str, flagged) -> str:
    """The run-file entry declaring ``flagged`` for raw stem ``stem``: a ``[masking.diodes]``
    table row, which ``arrayprobe.config`` loads into ``RunConfig.diode_masks`` and a run
    applies under ``--diode-corrected``."""
    diodes = ", ".join(str(int(d)) for d in flagged)
    return f'[masking.diodes]\n"{stem}" = [{diodes}]'


def summary_lines(rep: dict[str, Any]) -> list[str]:
    """A short printed form of :func:`report`'s output."""
    lines = [
        f"{Path(rep['proc']).name}: engine {rep['engine']} ({rep['engine_source']}), "
        f"profile {rep['profile'] or 'unstated'}",
        f"  bin_stats counts: {rep['counts']}"
        + (f", S={rep['S']} (offset {rep['image_slice_offset']}, {rep['offset_source']})"
           if rep["S"] is not None else ""),
        f"  rule: branch {rep['branch']}, threshold {rep['threshold']:g} ({rep['rule_source']})",
        f"  diodes over {rep['high_fraction']:g} x mean: {rep['ill_diode'] or 'none'}",
        f"  flagged: {rep['flagged'] or 'none'}",
        "  diode      lit   of max  of mean",
    ]
    for d in rep["per_diode"]:
        if d["flagged"] or d["diode"] in rep["ill_diode"]:
            lines.append(f"  {d['diode']:5d} {d['lit']:8d} {d['fraction_of_max']:8.3f} "
                         f"{d['fraction_of_mean']:8.3f}" + ("  flagged" if d["flagged"] else ""))
    return lines
