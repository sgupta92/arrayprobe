# SPDX-License-Identifier: BSD-3-Clause
"""A/B for A17: run the port's own sizeDist over the collapsed TAS grid.

Runs ``arrayprobe.sizedist.run`` (or, with ``--engine 3.5``,
``arrayprobe_uiops.sizedist.run`` -- v3.5's own positional signature) twice on the same proc
file -- once with the TAS grid exactly as the port reads it, once with duplicated seconds
collapsed (``tas_grid_fix``) -- and reports what the collapse recovers. The port is not
modified: only its input changes. ``collapse_tas_grid`` itself is engine-agnostic (pure
in-memory transform of ``(tas, timehhmmss)`` before either engine's ``sizedist.run`` ever sees
them), so this tool is the only thing that had to learn about the second engine.

Usage, from the repository root::

    .venv/Scripts/python.exe ../enhancements_uiops/tools/tas_grid_ab.py base160906104932 [out_dir] [--engine {3.1.4,3.5}]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

import netCDF4
import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "../enhancements_uiops/src")

from arrayprobe import sizedist  # noqa: E402
from arrayprobe.readers.tasinfo import load_tas_info  # noqa: E402

from arrayprobe_enhancements.tas_grid_fix import collapse_tas_grid  # noqa: E402

PROBE, PROJECT, D_CHOICE, SA_METHOD = "2DS", "ORACLES", 6, 0
PRES_PA, TEMP_C = 1013.25, 20.0
IAT_FILE = "2DS_intArrThreshold_MISSING.cdf"

#: The v3.5 switches ``scripts/run_flight.py``'s ``V35_CALL``/S4 call site use
#: (``:500-503``, ``:1531-1532``) -- same values as
#: ``arrayprobe_enhancements.pressure_units_fix.V35_SIZEDIST_SWITCHES``, duplicated rather
#: than imported because this is a standalone ``scripts/`` script, not a package module.
V35_SOFTWARE = "UIOOPS_v3.5"


def totals(path):
    with netCDF4.Dataset(path) as d:
        c = np.nan_to_num(np.asarray(d.variables["count"][:], float))
        c = c if c.shape[0] == 128 else c.T
    return float(c.sum()), float(c[5:].sum())


def _run_sizedist(engine, proc, out, t_tas, t_time, ddate):
    if engine == "3.5":
        from arrayprobe_uiops import sizedist as sizedist_v35

        sizedist_v35.run(
            proc, out, t_tas, t_time, PROBE, D_CHOICE, SA_METHOD,
            np.full_like(t_tas, PRES_PA), np.full_like(t_tas, TEMP_C),
            1, 0, 0, 0, PROJECT, ddate, IAT_FILE, software=V35_SOFTWARE)
    else:
        sizedist.run(proc, out, t_tas, t_time, PROBE, D_CHOICE, SA_METHOD,
                     np.full_like(t_tas, PRES_PA), np.full_like(t_tas, TEMP_C),
                     PROJECT, ddate, IAT_FILE, tree="production")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("stem", nargs="?")
    parser.add_argument("out_dir", nargs="?")
    parser.add_argument("--engine", choices=("3.1.4", "3.5"), default="3.1.4")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if not args.stem:
        print(__doc__)
        return 2
    stem = args.stem
    out_dir = args.out_dir or tempfile.mkdtemp()
    os.makedirs(out_dir, exist_ok=True)
    proc = None
    for suffix in ("", ".diodecorrected", ".stockreject"):
        candidate = f"../_decoded/proc.{stem}.H{suffix}.nc"
        if os.path.exists(candidate):
            proc = candidate
            break
    if proc is None:
        print(f"no proc file for {stem} in ../_decoded", file=sys.stderr)
        return 2
    print(f"proc: {os.path.basename(proc)}  engine: {args.engine}", flush=True)
    tas_csv = f"../_decoded/{stem}.tas.csv"
    timehhmmss, tas = load_tas_info(tas_csv)
    ddate = f"20{stem[4:10]} {stem[10:16]}"

    results = {}
    for label, (t_tas, t_time) in {
        "as-is": (tas, np.floor(timehhmmss)),
        "collapsed": collapse_tas_grid(tas, np.floor(timehhmmss))[:2],
    }.items():
        out = os.path.join(out_dir, f"sd_{label}.nc")
        t0 = time.time()
        _run_sizedist(args.engine, proc, out, t_tas, t_time, ddate)
        all_bin, used = totals(out)
        results[label] = (all_bin, used, len(t_tas))
        print(f"{label:10s} grid rows {len(t_tas):6d}  all-bin {all_bin:12,.0f}  "
              f"used-bin {used:10,.0f}   ({time.time() - t0:.0f} s)", flush=True)

    a, u, _ = results["as-is"]
    a2, u2, _ = results["collapsed"]
    print(f"\nrecovered: all-bin {a2 - a:+,.0f} ({100 * (a2 / a - 1):+.2f} %)   "
          f"used-bin {u2 - u:+,.0f} ({100 * (u2 / u - 1):+.2f} %)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
