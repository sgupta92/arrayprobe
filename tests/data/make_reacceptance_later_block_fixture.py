# SPDX-License-Identifier: BSD-3-Clause
"""Write the proc fixture for a shattering reacceptance that begins in a LATER block.

WHY A SECOND FIXTURE. ``reacceptance_proc.nc`` puts its six particles in
the file's first one-second block. That block's first inter-arrival is the
sentinel 0 (``sizeDist.m`` differences ``Time_in_seconds`` from the block's own
first particle when ``start - 1 <= 0``), so the first ``rEnd`` falls before the
first ``rBegin`` and ``find(rBegin):find(rEnd)`` is an empty range: that
fixture can only show reacceptance *not* firing. A well-formed event needs a
block whose first inter-arrival is a real gap read across the block boundary,
which happens only when the block starts at 0-based index 2 or later.

THE FIXTURE, seven particles in two one-second blocks:

  index  block (Time)  gap before  gap after   diameter  outcome
  -----  ------------  ----------  ----------  --------  ---------------------
  0      A (60643)     0 sentinel  1e-3        0.30 mm   'S' (sentinel <= thr)
  1      A (60643)     1e-3        1e-3        0.30 mm   binned
  2      B (60644)     1e-3        5e-7 rBegin 0.30 mm   'S'
  3      B (60644)     5e-7        5e-7        0.30 mm   'S'
  4      B (60644)     5e-7        5e-7        0.80 mm   'S'
  5      B (60644)     5e-7        1e-3 rEnd   1.40 mm   'S', then 'R': binned
  6      B (60644)     1e-3        1e-3        0.90 mm   binned

Block B starts at index 2, so its first gap is read across the boundary from
particle 1 and is quiet; ``rBegin`` is at B's first particle and ``rEnd`` at its
fourth, and the scan ``2:5`` keeps the largest particle that arrived faster than
``reaccptMaxIA`` (1e-6 s): particle 5. Every particle is above SOCRATES/2DS's
``reaccptD`` floor of 0.05 mm (``sizeDist.m:280``), so the choice is made by
size alone: particles 3 and 4 are smaller inside the event, and particle 2,
inside the range but arriving after a quiet gap, is not a candidate. Three
particles are binned with reacceptance and two without it.

Every row is tiled from row 0 of ``reacceptance_proc.nc`` (itself tiled
from a real ``imgProc_sm`` output), and only the fields the shattering block
reads are overwritten. The per-particle threshold file holds 6 us for each of
the seven particles.

Regenerate from the repository root::

    .venv/Scripts/python.exe tests/data/make_reacceptance_later_block_fixture.py

The Octave golden is written by
``octave_oracle/run_reacceptance_later_block_bank.py``, which calls this module.
"""
from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np

_HERE = Path(__file__).resolve().parent
SOURCE = _HERE / "reacceptance_proc.nc"
FIXTURE = _HERE / "reacceptance_later_block_proc.nc"
THRESH_FILE = _HERE / "reacceptance_later_block_threshold.cdf"

#: Gaps in seconds: the burst sits well inside the 6 us threshold and inside
#: ``reaccptMaxIA``; the quiet gap is three orders of magnitude outside both.
QUIET = 1e-3
BURST = 5e-7
THRESH_S = 6e-6

#: HHMMSS of each particle: two in the first block, five in the second.
TIMES_HHMMSS = [60643, 60643, 60644, 60644, 60644, 60644, 60644]
#: Gap before each particle; the first is where the cumulative clock starts.
GAPS = [0.0, QUIET, QUIET, BURST, BURST, BURST, QUIET]
DIAMETERS_MM = [0.30, 0.30, 0.30, 0.30, 0.80, 1.40, 0.90]

#: 0-based index of the particle that must come back as 'R'.
REACCEPTED = 5
#: Particles binned with reacceptance (1, 5 and 6) and without it (1 and 6).
BINNED_WITH = 3
BINNED_WITHOUT = 2


def times_in_seconds() -> np.ndarray:
    return np.cumsum(GAPS) + 1.0


def write_fixture(source: Path = SOURCE, target: Path = FIXTURE) -> Path:
    """The seven-particle proc file, rows tiled from ``source``'s first row."""
    if not source.is_file():
        raise SystemExit(f"source fixture missing: {source}")
    n = len(GAPS)
    diam = np.asarray(DIAMETERS_MM, dtype=float)
    target.unlink(missing_ok=True)
    with netCDF4.Dataset(source) as src, netCDF4.Dataset(
            target, "w", format="NETCDF3_CLASSIC") as dst:
        for name, dim in src.dimensions.items():
            dst.createDimension(name, None if name == "time" else dim.size)
        for name, var in src.variables.items():
            out = dst.createVariable(name, var.dtype, var.dimensions)
            data = np.asarray(var[:])
            if var.dimensions and var.dimensions[0] == "time":
                reps = [n] + [1] * (data.ndim - 1)
                data = np.tile(data[:1], reps)
            out[...] = data
        dst.variables["Time"][:] = np.asarray(TIMES_HHMMSS)
        dst.variables["Time_in_seconds"][:] = times_in_seconds()
        dst.variables["image_diam_minR"][:] = diam
        dst.variables["image_diam_AreaR"][:] = diam * 0.9
        # A particle reaches the shattering code only if it survived the reject
        # ladder with its centre in.
        dst.variables["image_auto_reject"][:] = np.full(n, ord("0"))
        dst.variables["image_center_in"][:] = np.ones(n, dtype=int)
    return target


def write_threshold_file(target: Path = THRESH_FILE) -> Path:
    """The ``intArrThreshold`` file ``iaThreshType = 1`` reads, one per particle."""
    target.unlink(missing_ok=True)
    with netCDF4.Dataset(target, "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("time", None)
        v = d.createVariable("threshold", "f8", ("time",))
        v[:] = np.full(len(GAPS), THRESH_S)
    return target


def main() -> int:
    print(f"wrote {write_fixture().name}")
    print(f"wrote {write_threshold_file().name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
