# SPDX-License-Identifier: BSD-3-Clause
"""How much does A17 cost each file? Duplicated TAS seconds and the particles in them.

Reports, per raw-file stem: the TAS grid's size, how many whole seconds appear more than once,
how many empty intervals that creates, and how many particles the per-particle file holds in
those seconds (accepted = ``imgProc``'s reject code plus ``image_center_in``, before
``sizeDist``'s own area-ratio and inter-arrival cuts).

**Two numbers, deliberately.** The accepted count states what the grid discards; only an A/B
with the port's own ``sizeDist`` states what a corrected grid would add to a published
distribution -- on ``base160906104932`` those are 32,831 and +4,070 used-bin particles
respectively. Use ``tas_grid_ab.py`` for the second. Quoting the first alone overstates the
effect roughly eightfold.

Usage, from the repository root::

    .venv/Scripts/python.exe ../enhancements_uiops/tools/tas_grid_impact.py base160906104932 [more...]
"""

from __future__ import annotations

import os
import sys

import netCDF4
import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "../enhancements_uiops/src")

from arrayprobe.readers.tasinfo import load_tas_info  # noqa: E402

from arrayprobe_enhancements.tas_grid_fix import (  # noqa: E402
    duplicate_seconds,
    empty_intervals,
    floor_to_seconds,
)

GOOD_CODES = [ord(c) for c in "0HhuR"]
DECODED = "../_decoded"


def hhmmss(second: float) -> int:
    s = int(second)
    return s // 3600 * 10000 + (s // 60) % 60 * 100 + s % 60


def measure(stem: str, decoded: str = DECODED) -> dict | None:
    tas_csv = os.path.join(decoded, f"{stem}.tas.csv")
    proc = None
    for suffix in ("", ".diodecorrected", ".stockreject"):
        candidate = os.path.join(decoded, f"proc.{stem}.H{suffix}.nc")
        if os.path.exists(candidate):
            proc = candidate
            break
    if not (os.path.exists(tas_csv) and proc):
        return None
    times, _ = load_tas_info(tas_csv)
    dup = duplicate_seconds(times)
    dup_hh = {hhmmss(s) for s in dup}
    with netCDF4.Dataset(proc) as d:
        t = np.asarray(d.variables["Time"][:], float).astype(int)
        code = np.asarray(d.variables["image_auto_reject"][:]).astype(int)
        centre_in = np.asarray(d.variables["image_center_in"][:], float)
        diam = np.asarray(d.variables["image_diam_minR"][:], float)
    inside = np.isin(t, list(dup_hh))
    accepted = inside & np.isin(code, GOOD_CODES) & (centre_in == 1) & np.isfinite(diam)
    bins = np.floor((diam[accepted] - 0.005) / 0.010).astype(int) + 1
    return {
        "stem": stem,
        "proc": os.path.basename(proc),
        "rows": int(times.size),
        "unique": int(np.unique(floor_to_seconds(times)).size),
        "duplicated": int(dup.size),
        "empty_intervals": int(empty_intervals(times).size),
        "accepted": int(accepted.sum()),
        "used_bin": int((bins >= 6).sum()) if bins.size else 0,
    }


def main(argv=None) -> int:
    stems = list(argv if argv is not None else sys.argv[1:])
    if not stems:
        print(__doc__)
        return 2
    print(f"{'stem':22s} {'rows':>6s} {'unique':>6s} {'dup':>5s} {'empty':>5s} "
          f"{'accepted':>10s} {'used-bin':>8s}")
    rc = 0
    for stem in stems:
        r = measure(stem)
        if r is None:
            print(f"{stem:22s}  no tas.csv / proc pair in {DECODED}", file=sys.stderr)
            rc = 1
            continue
        print(f"{r['stem']:22s} {r['rows']:6d} {r['unique']:6d} {r['duplicated']:5d} "
              f"{r['empty_intervals']:5d} {r['accepted']:10,d} {r['used_bin']:8,d}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
