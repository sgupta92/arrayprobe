# SPDX-License-Identifier: BSD-3-Clause
"""How big are the particles E5 recovers?

``last_record_fix`` recovers the particles in the final record of a SPEC raw file, which UIOOPS
never decodes. The particle *count* (0-235 per file) does not say whether those particles would
reach a published size distribution, so this tool answers that directly: it writes the dropped
record as a one-record ``.H.cdf``, runs the port's own ``imgProc_sm`` over it, applies the same
accept criteria the products use, and reports how many land in the used bins (6+) rather than in
bins 1-5, which the science does not use.

Measured 2026-08-29 on five dense files: **0-14 per file reach used bins**, largest recovered
particle 40-133 um. The numbers are in ``enhancements_uiops/docs/CORRECTIONS.md`, part `last_record_fix.py``.

Usage, from the repository root (it imports the port and the enhancements package)::

    .venv/Scripts/python.exe ../enhancements_uiops/tools/last_record_particle_sizes.py \\
        /path/to/raw/base160906075333.2DS [more.2DS ...]
"""

from __future__ import annotations

import os
import sys
import tempfile

import netCDF4
import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "../enhancements_uiops/src")

from arrayprobe import imgproc  # noqa: E402
from arrayprobe.profiles import ORACLES_PRODUCTION  # noqa: E402
from arrayprobe.readers import spec  # noqa: E402

from arrayprobe_enhancements.last_record_fix import (  # noqa: E402
    count_last_record_packets,
    decode_last_record,
)

#: Reject codes the products accept, and the bin ladder's lower edges (mm).
GOOD_CODES = [ord(c) for c in "0HhuR"]
FIRST_USED_BIN = 6


def bin_of(diameter_mm: float) -> int:
    """1-based size bin, matching ``sizeDist``'s 0.005 + 0.010 k ladder."""
    return int((diameter_mm - 0.005) // 0.010) + 1


def measure(raw: str) -> dict:
    packets = count_last_record_packets(raw)
    decoded = decode_last_record(raw, profile=ORACLES_PRODUCTION)
    if decoded is None:
        return {"stem": os.path.basename(raw), "packets": packets, "framed": 0,
                "accepted": 0, "used": 0, "max_um": 0.0}
    header, img_h, _ = decoded
    stem = os.path.basename(raw).replace(".2DS", "")
    tmp = tempfile.mkdtemp()
    image_file = os.path.join(tmp, f"{stem}.H.cdf")
    out = spec._ImageFile(image_file)
    out.append(header, spec._pack_image(img_h))
    out.close()
    proc = os.path.join(tmp, f"proc.{stem}.nc")
    framed = imgproc.imgproc_sm(image_file, proc, "2DS", 1, 1, "ORACLES",
                                profile=ORACLES_PRODUCTION)
    with netCDF4.Dataset(proc) as d:
        diam = np.asarray(d.variables["image_diam_minR"][:], float)
        code = np.asarray(d.variables["image_auto_reject"][:]).astype(int)
        centre_in = np.asarray(d.variables["image_center_in"][:], float)
    ok = np.isin(code, GOOD_CODES) & (centre_in == 1) & np.isfinite(diam)
    accepted = diam[ok]
    bins = np.array([bin_of(x) for x in accepted]) if accepted.size else np.array([])
    return {"stem": stem, "packets": packets, "framed": int(framed),
            "accepted": int(accepted.size),
            "used": int((bins >= FIRST_USED_BIN).sum()) if bins.size else 0,
            "max_um": float(accepted.max() * 1000) if accepted.size else 0.0}


def main(argv=None) -> int:
    files = list(argv if argv is not None else sys.argv[1:])
    if not files:
        print(__doc__)
        return 2
    print(f"{'file':26s} {'H pkts':>6s} {'framed':>6s} {'accepted':>8s} "
          f"{'used 6+':>7s} {'max um':>7s}")
    for raw in sorted(files):
        r = measure(raw)
        print(f"{r['stem']:26s} {r['packets']['h']:6d} {r['framed']:6d} {r['accepted']:8d} "
              f"{r['used']:7d} {r['max_um']:7.0f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
