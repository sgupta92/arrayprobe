# SPDX-License-Identifier: BSD-3-Clause
"""A/B for A12: what the Korolev out-of-focus correction does to a size distribution.

`sizeDist.m:793` computes a depth estimate and a size correction factor and never applies them.
`outoffocus.py` applies it. Until now the module was validated only per particle -- the recomputed
`part_z`/`size_factor` equal the stored columns bit-for-bit -- and the *size-distribution*
consequence was listed as not done. This closes that.

**The shape of the run, and why it needs a prerequisite.** Under the production reject
configuration (`rej_hollow = 0`) the hollow block never executes, so every stored `size_factor` is
1 and there is nothing to apply. `hollow_diagnostics` therefore re-derives the factors with the
hollow block forced on -- **diagnostics only, the accept/reject decision is untouched** -- and the
corrected diameters go into a copy of the proc file. `arrayprobe.sizedist.run` is then run
unmodified over both copies. The port is never modified; only its input is.

Usage, from the repository root::

    .venv/Scripts/python.exe ../enhancements_uiops/tools/outoffocus_ab.py base160906064403 [out_dir]
    .venv/Scripts/python.exe ../enhancements_uiops/tools/outoffocus_ab.py base170828121128 out \
        --decoded-dir ../_bench_big/baseline

Reports the corrected-particle count, the diameter shift, and the per-bin change in the size
distribution -- and prints the used-bin (6+) change separately, because that is the only part a
published distribution uses.

``--decoded-dir`` exists because the run this tool was always owed is on a file that is not in
``_decoded/``.  The A12 row asks for the A/B on a *dense* file -- ``064403`` is sparse, and this
project has been misled by a sparse file before -- and the only dense whole-file ``proc`` that
will ever be free of compute cost is the benchmark leg in ``_bench_big/baseline/``, kept on disk
for exactly this.  The three inputs are read from one directory, so naming it is the whole change.

``--engine {3.1.4,3.5}`` (2026-09-14) selects which ``hollow_diagnostics``/
``apply_outoffocus`` path runs and which files this tool looks for: v3.1.4's S2 output is
``<stem>.H.cdf`` and the production reject default is
``ORACLES_PRODUCTION_REJECT_CONFIG`` (``rej_hollow=0``, everything to re-derive); v3.5's S2
output is ``<stem>.H.nc`` (``arrayprobe_uiops/spec.py:597``) and the stock reject config is
``arrayprobe_uiops.measure.STOCK_V35_REJECT_CONFIG``, which already carries ``rej_hollow=True``
(``calculate_reject_unified.m:62`` forces it) -- so on a v3.5 decoded flight the hollow block
already ran and this tool's re-derivation should reproduce the stored columns rather than
newly populate them; that is itself the discriminating check ``--engine 3.5`` runs.

``--direction {korolev,dead_line_v314}`` and ``--area-mode {sphere,keep}``
(since 2026-09-15) select the correction's two open choices; both are printed and written into the
corrected copy's global attributes.  **Every A/B this tool ran before 2026-09-15 was
``dead_line_v314`` + ``keep``** -- the multiply, which runs Korolev's correction the wrong way
(``outoffocus.py`` docstring) -- so to reproduce one of them pass those two values.  The same
date moved the S4 pressure/temperature from 1013.25 / 20 to the ORACLES production call's
9e5 / 15 (``scripts/run_flight.py``'s ``ORACLES_2016_2DS_H``), so a baseline made here now matches
the archived product's call; the earlier constants were not the call of record (K1).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

import netCDF4
import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "../enhancements_uiops/src")

from arrayprobe import sizedist  # noqa: E402
from arrayprobe.readers.tasinfo import load_tas_info  # noqa: E402
from arrayprobe.reject import ORACLES_PRODUCTION_REJECT_CONFIG  # noqa: E402

from arrayprobe_enhancements.outoffocus import (  # noqa: E402
    AREA_MODES,
    DIRECTIONS,
    apply_outoffocus,
)

PROBE, PROJECT, D_CHOICE, SA_METHOD = "2DS", "ORACLES", 6, 0
# The ORACLES 2016 2D-S production call (scripts/run_flight.py ORACLES_2016_2DS_H: pres_pa=9e5,
# temp_c=15.0).  1013.25 / 20.0 until 2026-09-15, which is not the call of record.
PRES_PA, TEMP_C = 9e5, 15.0
IAT_FILE = "2DS_intArrThreshold_MISSING.cdf"


def changed_mask(corrected, original):
    """Which diameters actually changed — the comparison policy, in one place.

    Two decisions, both of which produced a wrong number the first time this tool ran:

    * **NaN against NaN is not a change.** ``np.isclose(nan, nan)`` is ``False``, and a real proc
      file is full of NaN diameters (3,932 of 49,637 on ``064403``), so the naive comparison
      reported 4,012 changes where there were 80.
    * **The tolerance is exact.** ``rtol=0, atol=0`` — the correction is a multiply by a stored
      factor, so a genuine change is exact and a one-ulp difference is still a difference. A
      tolerance here would hide small corrections rather than round-tripping noise.

    Pinned by ``tests/test_ab_tool_semantics.py``, along with the arithmetic identity that
    catches this class of error: a multiplicative correction cannot change more diameters than
    there are non-unit factors.
    """
    return ~np.isclose(np.asarray(corrected, float), np.asarray(original, float),
                       rtol=0, atol=0, equal_nan=True)


def _grid(path):
    with netCDF4.Dataset(path) as d:
        counts = np.nan_to_num(np.asarray(d.variables["count"][:], float))
    return counts if counts.shape[0] == 128 else counts.T


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    decoded_dir = "../_decoded"
    if "--decoded-dir" in args:
        i = args.index("--decoded-dir")
        if i + 1 >= len(args):
            print("--decoded-dir needs a directory", file=sys.stderr)
            return 2
        decoded_dir = args[i + 1]
        del args[i:i + 2]
    engine = "3.1.4"
    if "--engine" in args:
        i = args.index("--engine")
        if i + 1 >= len(args) or args[i + 1] not in ("3.1.4", "3.5"):
            print("--engine needs one of 3.1.4, 3.5", file=sys.stderr)
            return 2
        engine = args[i + 1]
        del args[i:i + 2]
    choices = {}
    for flag, allowed, default in (("--direction", DIRECTIONS, "korolev"),
                                   ("--area-mode", AREA_MODES, "sphere")):
        choices[flag] = default
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args) or args[i + 1] not in allowed:
                print(f"{flag} needs one of {', '.join(allowed)}", file=sys.stderr)
                return 2
            choices[flag] = args[i + 1]
            del args[i:i + 2]
    direction, area_mode = choices["--direction"], choices["--area-mode"]
    if not args:
        print(__doc__)
        return 2
    stem = args[0]
    out_dir = args[1] if len(args) > 1 else tempfile.mkdtemp()
    os.makedirs(out_dir, exist_ok=True)

    image_suffix = ".H.nc" if engine == "3.5" else ".H.cdf"
    proc = os.path.join(decoded_dir, f"proc.{stem}.H.nc")
    image = os.path.join(decoded_dir, f"{stem}{image_suffix}")
    tas_csv = os.path.join(decoded_dir, f"{stem}.tas.csv")
    for path in (proc, image, tas_csv):
        if not os.path.exists(path):
            print(f"missing {path}", file=sys.stderr)
            return 2

    if engine == "3.5":
        # arrayprobe_uiops/measure.py:59-60 -- calculate_reject_unified.m:62 forces
        # handles.rej_hollow = 1 unconditionally, so the stock v3.5 config already has it.
        from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG
        config = STOCK_V35_REJECT_CONFIG
    else:
        # The production configuration is the point: it is the one that made the archived
        # products, and the one under which every stored size_factor is 1 -- so there is
        # nothing to apply until hollow_diagnostics re-derives the factors with the hollow
        # block forced on.
        config = ORACLES_PRODUCTION_REJECT_CONFIG

    print(f"engine: {engine}   direction: {direction}   area_mode: {area_mode}", flush=True)
    print(f"proc:  {os.path.basename(proc)}", flush=True)
    t0 = time.time()
    with netCDF4.Dataset(image) as img_ds, netCDF4.Dataset(proc) as proc_ds:
        original = np.asarray(proc_ds.variables["image_diam_minR"][:], dtype=float)
        # apply_outoffocus returns a named tuple, not an array -- np.asarray() on it silently
        # builds a block and every downstream number is then nonsense.
        res = apply_outoffocus(img_ds, proc_ds, config=config, engine=engine,
                               direction=direction, area_mode=area_mode)
        original_area = np.asarray(proc_ds.variables["image_area"][:], dtype=float)
    corrected = np.asarray(res.corrected_diam, dtype=float)
    size_factor, part_z = res.size_factor, res.part_z
    if corrected.shape != original.shape:
        print(f"shape mismatch: corrected {corrected.shape} vs stored {original.shape}",
              file=sys.stderr)
        return 3
    moved = changed_mask(corrected, original)
    if int(moved.sum()) > int((size_factor != 1).sum()):
        # The identity that caught this tool's first, plausible-looking wrong answer: a
        # multiplicative correction cannot change more diameters than it has non-unit factors.
        print(f"IMPOSSIBLE: {int(moved.sum())} changed diameters against "
              f"{int((size_factor != 1).sum())} non-unit factors -- the comparison is wrong, "
              f"not the data", file=sys.stderr)
        return 4
    print(f"re-derived {original.size:,} particles in {time.time() - t0:.0f} s: "
          f"{int(moved.sum()):,} diameters change ({100 * moved.mean():.4f} %); "
          f"{int((size_factor != 1).sum()):,} non-unit size factors, "
          f"{int((part_z != -1).sum()):,} with a depth estimate, "
          f"{int(np.isnan(original).sum()):,} NaN diameters excluded from the comparison",
          flush=True)
    if moved.any():
        ratio = corrected[moved] / np.where(original[moved] == 0, np.nan, original[moved])
        print(f"  diameter ratio on those: min {np.nanmin(ratio):.4f}  "
              f"median {np.nanmedian(ratio):.4f}  max {np.nanmax(ratio):.4f}")

    # The corrected diameters go into a copy; sizedist then runs unmodified over each.
    corrected_proc = os.path.join(out_dir, f"proc.{stem}.H.outoffocus.nc")
    shutil.copyfile(proc, corrected_proc)
    with netCDF4.Dataset(corrected_proc, "a") as ds:
        ds.variables["image_diam_minR"][:] = corrected
        ds.variables["image_area"][:] = res.corrected_area
        ds.setncattr("outoffocus_direction", res.direction)
        ds.setncattr("outoffocus_area_mode", res.area_mode)
    print(f"  areas changed: {int(changed_mask(res.corrected_area, original_area).sum()):,}")

    timehhmmss, tas = load_tas_info(tas_csv)
    ddate = f"20{stem[4:10]} {stem[10:16]}"
    grids = {}
    for label, source in (("as-is", proc), ("corrected", corrected_proc)):
        out = os.path.join(out_dir, f"sd_outoffocus_{label}.nc")
        t0 = time.time()
        sizedist.run(source, out, tas, np.floor(timehhmmss), PROBE, D_CHOICE, SA_METHOD,
                     np.full_like(tas, PRES_PA), np.full_like(tas, TEMP_C),
                     PROJECT, ddate, IAT_FILE, tree="production")
        grids[label] = _grid(out)
        g = grids[label]
        print(f"{label:10s} all-bin {g.sum():12,.0f}   used-bin {g[5:].sum():10,.0f}   "
              f"({time.time() - t0:.0f} s)", flush=True)

    a, b = grids["as-is"], grids["corrected"]
    cells = int((a != b).sum())
    print(f"\ncells changed: {cells:,} of {a.size:,}  "
          f"(used bins 6+: {int((a[5:] != b[5:]).sum()):,})")
    print(f"all-bin particles {b.sum() - a.sum():+,.0f}   "
          f"used-bin particles {b[5:].sum() - a[5:].sum():+,.0f}")
    if cells:
        rows = np.flatnonzero((a != b).any(axis=1))
        print(f"bins touched: {rows.min() + 1}..{rows.max() + 1} (1-based); "
              f"largest single-cell change {np.abs(b - a).max():,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
