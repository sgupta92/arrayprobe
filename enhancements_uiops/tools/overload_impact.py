# SPDX-License-Identifier: BSD-3-Clause
"""What A8 actually changes, per file: touched seconds, changed seconds, negatives.

``overload_accounting_fix`` rewrites ``sum_IntArr`` and ``sample_vol`` for seconds that hold
particles but accept none. Three numbers describe its effect, and they are easy to confuse --
this tool exists because two of them were confused in the project's own notes on 2026-08-29:

* **touched** -- seconds matching the finding's predicate (particles present, none accepted,
  ``sum_IntArr == 1``);
* **changed** -- of those, the ones where the recomputed ``1 - time_interval72`` is not 1, i.e.
  the second actually had an overload-flagged particle. On real files this is a minority: the
  rest would read 1 either way;
* **negative** -- of those, the ones where ``time_interval72 > 1 s`` because ``sizeDist.m:696``
  measures a second's first particle against the previous particle *in the file*, across any
  empty seconds between. Rare, and large only on sparse files.

Measured 2026-08-29 across eight decoded files: negatives on four of them, none on the other
four; minimum −4.69 on the sparse ``064403``, −0.26 elsewhere. Numbers in
``enhancements_uiops/docs/CORRECTIONS.md`, part `overload_accounting_fix.py``.

Usage, from the repository root::

    .venv/Scripts/python.exe ../enhancements_uiops/tools/overload_impact.py \\
        ../_decoded/sd.base160906064403.H.nc [more sd files ...]

The matching ``proc`` file is found beside each ``sd`` (same stem and ``.stockreject`` /
``.diodecorrected`` suffix); pass ``--proc`` to name one explicitly for a single file.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "../enhancements_uiops/src")

from arrayprobe_enhancements.overload_accounting_fix import (  # noqa: E402
    apply_overload_accounting,
)


def proc_beside(sd_path: str) -> str | None:
    """The ``proc`` file matching an ``sd`` file, by stem and variant suffix."""
    directory, name = os.path.split(sd_path)
    parts = name.split(".")            # sd.<stem>.H[.variant].nc
    if len(parts) < 4 or parts[0] != "sd":
        return None
    stem, rest = parts[1], parts[3:-1]
    suffix = "." + ".".join(rest) if rest else ""
    candidate = os.path.join(directory, f"proc.{stem}.H{suffix}.nc")
    return candidate if os.path.exists(candidate) else None


def measure(proc_path: str, sd_path: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        report = apply_overload_accounting(proc_path, sd_path, os.path.join(tmp, "a8.nc"))
    values = np.array([row[3] for row in report]) if report else np.array([])
    changed = values[values != 1.0] if values.size else values
    return {
        "file": os.path.basename(sd_path),
        "touched": int(values.size),
        "changed": int(changed.size),
        "negative": int((values < 0).sum()) if values.size else 0,
        "min": float(values.min()) if values.size else float("nan"),
        "median_changed": float(np.median(changed)) if changed.size else float("nan"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sd", nargs="+", help="sd.*.nc file(s) written by the port")
    ap.add_argument("--proc", help="proc file (only valid with a single sd file)")
    args = ap.parse_args(argv)
    if args.proc and len(args.sd) != 1:
        print("--proc names one proc, so pass exactly one sd file", file=sys.stderr)
        return 2

    print(f"{'sd file':44s} {'touched':>7s} {'changed':>7s} {'negative':>8s} "
          f"{'min':>7s} {'median chg':>10s}")
    rc = 0
    for sd_path in args.sd:
        proc_path = args.proc or proc_beside(sd_path)
        if not proc_path:
            print(f"{os.path.basename(sd_path):44s}  no matching proc file", file=sys.stderr)
            rc = 1
            continue
        r = measure(proc_path, sd_path)
        print(f"{r['file'][:44]:44s} {r['touched']:7d} {r['changed']:7d} {r['negative']:8d} "
              f"{r['min']:7.2f} {r['median_changed']:10.3f}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
