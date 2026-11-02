# SPDX-License-Identifier: BSD-3-Clause
"""Export the human triage verdicts from a decoded directory to a folder of your choice. Tooling.

``triage_verdicts/<flight>.json`` lives beside the decoded files, so the only copy of every
hand label is one file on one disk. This copies every ``source: human`` record into an output
folder, one file per verdict store, and nothing an automatic pass wrote. The output folder is
``--out``; when it is not given, it is ``exported_labels`` inside the first ``--decoded-dir``.

**A label is kept with the particle's raw identity, not only its index.** ``particle_index``
is a row of one proc file, and reprocessing renumbers rows. So each record also carries the
2D-S particle header's counter and 32-bit clock (``Particle_number_all``,
``particle_microsec``), the key ``compare_soda2_uiops.py`` pairs on, with the record time. A
label then stays attached to its particle through any later processing of the same raw file.
The proc file each index points into is fingerprinted (name, size, SHA-256).

Deterministic: re-running with no new labels rewrites identical bytes.

Usage, from the repository root::

    python scripts/export_human_verdicts.py --decoded-dir DIR [--decoded-dir DIR2] [--out OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import netCDF4
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from arrayprobe.triage_server import _discover_flights  # noqa: E402

#: Proc columns copied beside each label: the raw identity first, then context.
IDENTITY = ("Particle_number_all", "particle_microsec", "Time", "msec", "parent_rec_num")
CONTEXT = ("image_diam_minR", "image_auto_reject", "image_length", "image_width")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _scalar(v):
    x = float(v)
    return int(x) if np.isfinite(x) and x == int(x) else (None if not np.isfinite(x) else x)


def export_store(decoded_dir: Path, flight: str, paths: dict) -> dict | None:
    """The human records of one verdict store with their identity, or None if none."""
    store = decoded_dir / "triage_verdicts" / f"{flight}.json"
    if not store.is_file():
        return None
    records = json.loads(store.read_text(encoding="utf-8"))
    human = {k: r for k, r in records.items()
             if isinstance(r, dict) and r.get("source") == "human"}
    if not human:
        return None
    proc = Path(paths["proc"])
    labels = []
    with netCDF4.Dataset(str(proc)) as d:
        d.set_auto_mask(False)
        v = d.variables
        for key in sorted(human, key=int):
            i = int(key)
            row = {"particle_index": i, **{f: human[key].get(f) for f in
                                           ("verdict", "note", "at", "reviewer", "queue")}}
            # The phase (ice, drizzle or unsure) is a label too, so it leaves with the
            # verdict. Only when recorded: a store without it exports the same bytes as before.
            if "phase" in human[key]:
                row["phase"] = human[key]["phase"]
            for name in IDENTITY + CONTEXT:
                row[name] = _scalar(v[name][i]) if name in v else None
            labels.append(row)
    return {
        "flight": flight,
        "probe": paths.get("probe", "2DS"),
        "decoded_dir": decoded_dir.name,
        "proc": {"name": proc.name, "bytes": proc.stat().st_size, "sha256": _sha256(proc)},
        "n_labels": len(labels),
        "labels": labels,
    }


def export_all(decoded_dirs, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for dd in decoded_dirs:
        dd = Path(dd)
        for flight, paths in _discover_flights(dd).items():
            doc = export_store(dd, flight, paths)
            if doc is None:
                continue
            out = out_dir / f"{dd.name}__{flight}.json"
            out.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")
            written.append(out)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decoded-dir", action="append", required=True,
                    help="a directory holding triage_verdicts/ (repeat for several)")
    ap.add_argument("--out", default=None,
                    help="output folder; default: exported_labels inside the first --decoded-dir")
    a = ap.parse_args(argv)
    dirs = a.decoded_dir
    out = Path(a.out) if a.out else Path(dirs[0]) / "exported_labels"
    for p in export_all(dirs, out):
        n = json.loads(p.read_text(encoding="utf-8"))["n_labels"]
        print(f"{n:6d} human labels -> {p.relative_to(REPO) if p.is_relative_to(REPO) else p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
