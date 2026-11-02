# SPDX-License-Identifier: BSD-3-Clause
"""Score a reviewer's labels against what the run decided, per reject code and size bin.

For each queue in a queue file (the file ``arrayprobe tune sample`` writes and
``arrayprobe triage --queue-file`` reads), the verdicts and phases the reviewer recorded in the
triage verdict store are joined to the queue's particles by ``particle_index``. The store is read
with the triage server's own loader; a re-check queue (name starting ``recheck-``) is read from
its own store, ``<flight>.recheck.json``, exactly as the server shows it.

Two crossings per queue:

* **per size bin**: verdict counts, and the phase recorded beside each verdict in
  ``phase_verdicts`` (default ``real``), with the ice fraction ``ice / (ice + drizzle)`` and a
  Wilson 95 % interval. Bins with no ice or drizzle label get no fraction and are named.
* **per reject code** (the code each particle carried when the queue was drawn): verdict counts
  per size bin, and for the code as a whole how many particles it **rejected that the reviewer
  labelled real**, or, for an accepted code, how many it **accepted that the reviewer labelled
  artifact**.

The reject code is read from the queue item's ``reject_code`` field when there is one, else from
the ``code X`` in the note ``arrayprobe.tune.sample.queue_items`` writes beside each particle; a
particle with neither is counted under ``unknown``. Nothing here reads a proc file, runs the
pipeline or writes anything but the report.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from pathlib import Path

from arrayprobe.matlab_compat import REJECT_CODE_WORDS
from arrayprobe.tune.sample import ACCEPTED_CODES, COVERAGE_KEY

VERDICTS = ("real", "artifact", "mixed", "unsure")
PHASES = ("ice", "drizzle", "unsure")
UNKNOWN_CODE = "unknown"
_NOTE_CODE_RE = re.compile(r"(?:^|,\s*)code (\S+?)(?:,|$)")


def wilson(k: float, n: float, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval; ``(nan, nan)`` for n == 0 (as ``scripts/score_ena_reject_fields``)."""
    if n <= 0:
        return (math.nan, math.nan)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def reject_code_of(item: dict) -> str:
    """The reject code a queue item carries, as a character, or :data:`UNKNOWN_CODE`."""
    code = item.get("reject_code")
    if code is not None:
        return str(code)
    m = _NOTE_CODE_RE.search(str(item.get("note", "")))
    return m.group(1) if m else UNKNOWN_CODE


def _verdict_counts() -> dict:
    return {**{f"v_{v}": 0 for v in VERDICTS}, "v_other": 0}


def _bins_of(items: list[dict], coverage: dict | None) -> tuple[list[str | None], dict]:
    # str | None: an item without a size_bin contributes None as its own bin below.
    if coverage and coverage.get("strata"):
        bins = [s["bin"] for s in coverage["strata"]]
        available = {s["bin"]: int(s["available"]) for s in coverage["strata"]}
    else:
        bins, available = [], {}
    for item in items:
        if item.get("size_bin") not in bins:
            bins.append(item.get("size_bin"))
    return bins, available


def _score(items: list[dict], record: Callable[[dict], object], coverage: dict | None,
           phase_verdicts: Sequence[str]) -> dict:
    bins, available = _bins_of(items, coverage)
    rows = {b: {"bin": b, "available": available.get(b), "queued": 0, "labelled": 0,
                **_verdict_counts(),
                **{f"p_{p}": 0 for p in PHASES}, "p_none": 0, "p_other": 0}
            for b in bins}
    for item in items:
        row = rows[item.get("size_bin")]
        row["queued"] += 1
        rec = record(item)
        if not isinstance(rec, dict):
            continue
        row["labelled"] += 1
        v = rec.get("verdict")
        row[f"v_{v}" if v in VERDICTS else "v_other"] += 1
        if v not in phase_verdicts:
            continue
        p = rec.get("phase")
        row["p_none" if p is None else (f"p_{p}" if p in PHASES else "p_other")] += 1
    weighted_num = weighted_den = 0.0
    excluded = []
    for b in bins:
        r = rows[b]
        n = r["p_ice"] + r["p_drizzle"]
        r["decided"] = n
        if n:
            r["ice_fraction"] = r["p_ice"] / n
            r["wilson95"] = list(wilson(r["p_ice"], n))
            if r["available"] is not None:
                weighted_num += r["available"] * r["ice_fraction"]
                weighted_den += r["available"]
        else:
            r["ice_fraction"] = None
            r["wilson95"] = None
            excluded.append({"bin": b, "available": r["available"], "labelled": r["labelled"]})
    return {"rows": [rows[b] for b in bins],
            "weighted_ice_fraction": weighted_num / weighted_den if weighted_den else None,
            "weighted_over_available": int(weighted_den),
            "excluded_bins": excluded,
            "phase_verdicts": list(phase_verdicts)}


def score_queue(items: list[dict], verdicts: dict, coverage: dict,
                phase_verdicts: Sequence[str] = ("real",)) -> dict:
    """Per-bin counts and fractions for one queue whose particles are all in ``verdicts``.

    ``verdicts`` is one flight's store as the triage server loads it (particle index as a
    string to record). The fraction is weighted by each bin's ``available`` count from the
    coverage block; bins with no decided label are left out of the weighting and named.
    """
    return _score(items, lambda it: verdicts.get(str(int(it["particle_index"]))), coverage,
                  phase_verdicts)


def cross_codes(items: list[dict], record: Callable[[dict], object],
                accepted_codes: str = ACCEPTED_CODES) -> list[dict]:
    """Per reject code: verdict counts per size bin and in total, and the disagreement count.

    For a code outside ``accepted_codes`` the disagreement is the particles it rejected that
    the reviewer labelled real; for an accepted code, those it accepted labelled artifact.
    """
    out: dict[str, dict] = {}
    for item in items:
        code = reject_code_of(item)
        c = out.setdefault(code, {
            "code": code, "words": REJECT_CODE_WORDS.get(code),
            "accepted": None if code == UNKNOWN_CODE else code in accepted_codes,
            "queued": 0, "labelled": 0, **_verdict_counts(), "bins": {}})
        b = c["bins"].setdefault(item.get("size_bin"),
                                 {"queued": 0, "labelled": 0, **_verdict_counts()})
        for d in (c, b):
            d["queued"] += 1
        rec = record(item)
        if not isinstance(rec, dict):
            continue
        v = rec.get("verdict")
        key = f"v_{v}" if v in VERDICTS else "v_other"
        for d in (c, b):
            d["labelled"] += 1
            d[key] += 1
    rows = []
    for code in sorted(out):
        c = out[code]
        c["rejected_labelled_real"] = c["v_real"] if c["accepted"] is False else None
        c["accepted_labelled_artifact"] = c["v_artifact"] if c["accepted"] else None
        rows.append(c)
    return rows


def store_lookup(decoded_dir: Path) -> Callable[[str, dict], object]:
    """``record(queue_name, item)`` reading the triage verdict store, one load per store."""
    from arrayprobe.triage_server import _load_verdicts, is_recheck_queue

    cache: dict[tuple[str, bool], dict] = {}

    def record(queue: str, item: dict):
        key = (str(item["flight"]), is_recheck_queue(queue))
        if key not in cache:
            cache[key] = _load_verdicts(Path(decoded_dir), key[0], recheck=key[1])
        return cache[key].get(str(int(item["particle_index"])))

    return record


def score_file(queue_data: dict, decoded_dir: Path,
               phase_verdicts: Sequence[str] = ("real",)) -> dict:
    """The report for every queue in a loaded queue file (underscore keys are metadata)."""
    from arrayprobe.triage_server import is_recheck_queue

    unknown = [v for v in phase_verdicts if v not in VERDICTS]
    if unknown:
        raise ValueError(f"unknown verdict(s) {unknown}; known: {list(VERDICTS)}")
    lookup = store_lookup(decoded_dir)
    coverages = queue_data.get(COVERAGE_KEY, {}) or {}
    queues = {}
    for name in sorted(n for n in queue_data if not n.startswith("_")):
        items = queue_data[name]
        cov = coverages.get(name)
        accepted = (cov.get("accepted_codes") if cov and cov.get("accepted_codes")
                    else ACCEPTED_CODES)

        def record(item, _name=name):
            return lookup(_name, item)

        queues[name] = {
            "store": "recheck" if is_recheck_queue(name) else "first",
            "flights": sorted({str(it["flight"]) for it in items}),
            "accepted_codes": accepted,
            "by_bin": _score(items, record, cov, phase_verdicts),
            "by_code": cross_codes(items, record, accepted),
        }
    return {"decoded_dir": str(decoded_dir), "phase_verdicts": list(phase_verdicts),
            "queues": queues}


def summary_lines(report: dict) -> list[str]:
    """Per queue and reject code: labelled count, and the disagreement with the run."""
    lines = []
    for name, q in report["queues"].items():
        n_lab = sum(r["labelled"] for r in q["by_bin"]["rows"])
        n_q = sum(r["queued"] for r in q["by_bin"]["rows"])
        lines.append(f"{name} ({q['store']} store): {n_lab} of {n_q} labelled")
        for c in q["by_code"]:
            if c["accepted"] is None:
                what = "code unknown"
            elif c["accepted"]:
                what = f"accepted, {c['accepted_labelled_artifact']} labelled artifact"
            else:
                what = f"rejected, {c['rejected_labelled_real']} labelled real"
            lines.append(f"  code {c['code']:>7s}: {c['labelled']:4d} of {c['queued']:4d} "
                         f"labelled; {what}")
    return lines
