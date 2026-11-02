# SPDX-License-Identifier: BSD-3-Clause
"""Build one aircraft TAS sidecar from another probe's housekeeping on the same aircraft.

**Why (author, 2026-09-22).** The UND CIP's own NASA-Ames airspeed file declares
m/s and is almost certainly knots, and converting it leaves a **5.8 %** residual
against the 2D-S's own series (ratio 1.833 measured over 23,914 shared in-flight
seconds, against the exact 1.9438). The author's instruction was not to lean on
that conversion but to *derive the airspeed from the 2D-S*: both instruments fly
on the same aircraft, so its true airspeed is one physical quantity, and the
2D-S housekeeping already records it **in m/s, in the pipeline's own sidecar
form**. Using it for the CIP removes the units question from the comparison
instead of carrying it — and it makes both instruments share one airspeed, which
is what a like-for-like comparison requires anyway.

**What this does, and nothing more.** Reads one or more ``<stem>.tas.csv`` files
written by the SPEC stage 2, puts every sample on a whole second, takes the
**median** of the samples landing in each second, and writes a single 1 Hz
sidecar covering the union. The median rather than the mean because SPEC
housekeeping carries occasional wild values; a single bad packet must not move
the second it lands in.

**It computes no science.** Seconds-to-HHMMSS packing and a per-second median.
The output is the same nine-column shape every other TAS producer here writes,
via :func:`arrayprobe.tools.make_tas_file.write_tas_csv`, so the pipeline cannot
tell which producer made it — except from the ``.call`` stamp, which is why the
caller must record the source.

Usage, from the repository root::

    python -m arrayprobe.driver.tas_from_probe_housekeeping \\
        ../_decoded/base160906*.tas.csv \\
        --out ../_decoded/cip160906/driver_v35_0921/2016_09_06_07_59_50.tas.csv

**The uncertainty this does NOT remove.** The 5.8 % spread between the two
airspeed series is a real disagreement between two measurements on one platform.
Choosing the 2D-S series makes the CIP and 2D-S self-consistent; it does not
make either one right in absolute terms. Any CIP-versus-2D-S figure carries
that as an uncertainty band, and this module prints the number so the
caller cannot claim not to know it.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from arrayprobe.tools.make_tas_file import write_tas_csv  # noqa: E402

#: Below this the aircraft is not flying; those seconds are kept in the series (stage 4 needs a
#: continuous axis) but excluded from the summary statistics this prints.
IN_FLIGHT_MPS = 20.0


def hhmmss_to_seconds(hhmmss: np.ndarray) -> np.ndarray:
    """HHMMSS (possibly fractional, possibly hour >= 24) to seconds from midnight."""
    h = np.asarray(hhmmss, dtype=np.float64)
    hh = np.floor(h / 10000.0)
    mm = np.floor((h - hh * 10000.0) / 100.0)
    ss = h - hh * 10000.0 - mm * 100.0
    return hh * 3600.0 + mm * 60.0 + np.floor(ss)


def merge(paths: list[Path]) -> tuple[np.ndarray, np.ndarray, int]:
    """Whole seconds and the median TAS in each, over every input file."""
    sod_all: list[np.ndarray] = []
    tas_all: list[np.ndarray] = []
    n_raw = 0
    for p in paths:
        table = np.loadtxt(p, delimiter=",", usecols=(0, 1), ndmin=2)
        if table.size == 0:
            continue
        n_raw += table.shape[0]
        sod_all.append(hhmmss_to_seconds(table[:, 0]))
        tas_all.append(table[:, 1].astype(np.float64))
    if not sod_all:
        raise SystemExit("no rows read from any input")
    sod = np.concatenate(sod_all)
    tas = np.concatenate(tas_all)
    finite = np.isfinite(sod) & np.isfinite(tas)
    sod, tas = sod[finite], tas[finite]
    order = np.argsort(sod, kind="stable")
    sod, tas = sod[order], tas[order]
    seconds, start = np.unique(sod, return_index=True)
    bounds = list(start[1:]) + [tas.size]
    medians = np.array([np.median(tas[a:b]) for a, b in zip(start, bounds, strict=True)])
    # strict=True: `bounds` is built from `start` and must be the same length by
    # construction, so a mismatch is a bug here rather than ragged input to tolerate.
    return seconds, medians, n_raw


def main(argv=None) -> int:
    """Command line: merge the named .tas.csv files into one whole-second TAS sidecar at --out."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+", help="one or more <stem>.tas.csv files")
    ap.add_argument("--out", required=True, help="the .tas.csv to write")
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.inputs]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise SystemExit(f"not found: {', '.join(str(p) for p in missing)}")

    seconds, tas, n_raw = merge(paths)
    flying = tas >= IN_FLIGHT_MPS
    rows = write_tas_csv(args.out, _hhmmss(seconds), tas, seconds_of_day=seconds)

    print(f"wrote {args.out} -- {rows} whole-second rows from {n_raw} housekeeping samples "
          f"across {len(paths)} file(s)")
    if flying.any():
        print(f"in-flight seconds {int(flying.sum())}: TAS median {np.median(tas[flying]):.2f}, "
              f"range {tas[flying].min():.2f}..{tas[flying].max():.2f} m/s")
    print("source: the SPEC probe's own housekeeping on the SAME aircraft, already in m/s -- "
          "used so both instruments share one airspeed. Record it in the run's .call stamp.")
    return 0


def _hhmmss(seconds_of_day: np.ndarray) -> np.ndarray:
    s = np.asarray(seconds_of_day, dtype=np.int64)
    return ((s // 3600) * 10000 + ((s % 3600) // 60) * 100 + (s % 60)).astype(np.float64)


if __name__ == "__main__":
    raise SystemExit(main())
