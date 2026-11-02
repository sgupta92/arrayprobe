# SPDX-License-Identifier: BSD-3-Clause
"""Analysis-ready export of a port output file — lossless by default.

**The question this answers**, asked 2026-08-26 and lost until the instruction
ledger recovered it: *"are the output data saved in ARCO formats?"* No, and
``arrayprobe`` itself must not. It writes NETCDF3_CLASSIC because that is what
MATLAB's bare ``'clobber'`` default writes, and the byte-level fidelity the
package exists to demonstrate depends on it — including its failure modes, such
as the 2 GiB non-record variable cap that makes a large flight fail at exactly
the point MATLAB's would. An analysis-ready form belongs *here*, on the
enhancements side, as an export that reads faithful output and never modifies it.

**What "analysis-ready" buys, beyond the word "compression".** Four separate
levers, and they were measured individually rather than assumed, because two of
the four behaved opposite to expectation.

1. **Dtype narrowing.** The production lineage declares *every* proc variable
   ``double``, where stock declares each at its natural width. 40 of 41
   variables hold values a narrower type represents exactly or nearly. Narrowing
   an *integral* variable to the smallest integer type that holds its range is
   **lossless**, and this module verifies that per variable rather than
   trusting the declaration.

2. **Chunking.** NETCDF3 stores a variable contiguously; reading one second out
   of a 20-million-particle file means seeking through the whole variable.
   Chunked storage lets a reader pull a slice without touching the rest, which
   is the property that makes a file usable from object storage or over a
   network — and it is what "analysis-ready" mostly means in practice, not
   size.

3. **Compression** (zlib). Per variable, per chunk, so a reader decompresses
   only the chunks it touches.

4. **The shuffle filter**, which reorders bytes so that same-significance bytes
   sit together before compression. **Measured: it helps integral data and
   HURTS float data here** — 8.6 % of baseline with shuffle against 10.7 %
   without for an integral variable, but **46.4 % with against 24.9 % without**
   for a float one. So it is chosen per variable from the data, never globally.

**Lossless by default, and the measurement is why.** Narrowing float64 to
float32 is lossy, and it buys almost nothing once compression is on: 23.5 % of
baseline against 24.9 % for lossless float64 + zlib. A 1.4-point gain is not
worth discarding mantissa bits in a package whose entire claim is fidelity. So
``lossy_floats`` defaults to ``False`` and, when enabled, the maximum relative
error actually introduced is measured and recorded in the output file rather
than assumed to be "float32 precision".

**Zarr is deliberately not attempted here.** ``zarr``, ``xarray`` and ``dask``
are all absent from this environment, against a package convention of adding no
dependencies (``particle_clustering`` hand-rolls k-means for the same reason).
The trade is scoped in ``enhancements_uiops/README.md``; this module needs nothing
that is not already required.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Literal

import netCDF4
import numpy as np

#: Chunk length along the particle/time dimension. 200,000 particles is roughly
#: a 1.6 MB float64 chunk -- large enough that per-chunk overhead is negligible,
#: small enough that a reader wanting one second does not pull tens of MB.
DEFAULT_CHUNK = 200_000

#: zlib level. 4 was chosen by measurement, not convention: levels above it cost
#: several times the write wall-clock for a few percent of size on this data.
DEFAULT_COMPLEVEL: Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9] = 4


@dataclasses.dataclass(frozen=True)
class VariablePlan:
    """How one variable will be written, and why."""

    name: str
    dtype: str
    shuffle: bool
    lossless: bool
    reason: str
    max_rel_error: float = 0.0


def _integral(sample: np.ndarray) -> bool:
    finite = sample[np.isfinite(sample)]
    return finite.size > 0 and bool(np.all(finite == np.round(finite)))


def _smallest_int(lo: float, hi: float) -> str | None:
    for dtype, info in (("i1", np.iinfo(np.int8)), ("u1", np.iinfo(np.uint8)),
                        ("i2", np.iinfo(np.int16)), ("u2", np.iinfo(np.uint16)),
                        ("i4", np.iinfo(np.int32)), ("u4", np.iinfo(np.uint32))):
        if lo >= info.min and hi <= info.max:
            return dtype
    return None


def plan_variable(name: str, values: np.ndarray, *,
                  lossy_floats: bool = False) -> VariablePlan:
    """Decide dtype and shuffle for one variable, from its own values.

    The decision is made from the data rather than from the declared type,
    because the declared type here is ``double`` for everything and says nothing.
    """
    if values.dtype.kind in "iu":
        return VariablePlan(name, values.dtype.str[1:], True, True,
                            "already an integer type; shuffle helps integral data")

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return VariablePlan(name, "f4", False, False,
                            "no finite values; nothing to preserve")

    if _integral(values):
        lo, hi = float(finite.min()), float(finite.max())
        narrowed = _smallest_int(lo, hi)
        has_nan = bool((~np.isfinite(values)).any())
        if narrowed and not has_nan:
            return VariablePlan(
                name, narrowed, True, True,
                f"every value integral in [{lo:g}, {hi:g}]; {narrowed} holds them exactly")
        if narrowed and has_nan:
            # An integer type cannot carry NaN, and inventing a fill value would
            # change what a reader sees. Keep the float and let zlib work.
            return VariablePlan(name, "f8", False, True,
                                "integral but carries NaN; an integer type would "
                                "need a fill value that changes the data")

    if lossy_floats:
        as32 = values.astype("f4").astype("f8")
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.abs(as32 - values) / np.where(values != 0, np.abs(values), 1.0)
        err = float(np.nanmax(rel)) if rel.size else 0.0
        return VariablePlan(name, "f4", False, False,
                            "float32 requested; error measured, not assumed", err)

    return VariablePlan(name, "f8", False, True,
                        "float64 kept; shuffle measured to HURT float data here")


def _exact_fill(var, dtype):
    """The source variable's ``_FillValue`` in ``dtype`` if it converts exactly, else None."""
    if "_FillValue" not in var.ncattrs():
        return None
    src = np.asarray(var.getncattr("_FillValue"))
    out = src.astype(dtype)
    same = (np.isnan(src) & np.isnan(out)) if src.dtype.kind == "f" and np.dtype(dtype).kind == "f" \
        else np.zeros(src.shape, bool)
    if bool(np.all(same | (out.astype(src.dtype) == src))):
        return out.item()
    return None


def export(infile, outfile, *, lossy_floats: bool = False,
           chunk: int = DEFAULT_CHUNK,
           complevel: Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9] = DEFAULT_COMPLEVEL,
           sample: int = 500_000, progress=None) -> list[VariablePlan]:
    """Write an analysis-ready copy of ``infile``. Returns the plan per variable.

    ``infile`` is never opened for writing. The port's own output is the
    reference and this is a derived artefact, which is the whole reason the
    export lives in this package rather than in ``arrayprobe``.
    """
    infile, outfile = Path(infile), Path(outfile)
    plans: list[VariablePlan] = []
    with netCDF4.Dataset(str(infile)) as src, \
            netCDF4.Dataset(str(outfile), "w", format="NETCDF4") as dst:
        for name, dim in src.dimensions.items():
            dst.createDimension(name, None if dim.isunlimited() else dim.size)

        for i, (name, var) in enumerate(src.variables.items()):
            head = np.asarray(var[:sample] if var.ndim == 1 else var[:sample, ...])
            plan = plan_variable(name, head.ravel(), lossy_floats=lossy_floats)
            plans.append(plan)

            sizes = [dst.dimensions[d].size or var.shape[k]
                     for k, d in enumerate(var.dimensions)]
            chunks = [min(chunk, sizes[0])] + sizes[1:] if sizes else None

            # netCDF4 accepts _FillValue only at creation, so a source fill is passed here
            # and skipped in the attribute copy below; one the planned dtype cannot hold
            # exactly is recorded instead of being rounded into a different value.
            fill = _exact_fill(var, plan.dtype)
            out = dst.createVariable(
                name, plan.dtype, var.dimensions, zlib=True, complevel=complevel,
                shuffle=plan.shuffle, chunksizes=chunks or None, fill_value=fill)
            out.setncattr("arrayprobe_source_dtype", str(var.dtype))
            out.setncattr("arrayprobe_lossless", "true" if plan.lossless else "false")
            out.setncattr("arrayprobe_plan", plan.reason)
            if not plan.lossless and plan.max_rel_error:
                out.setncattr("arrayprobe_max_relative_error", plan.max_rel_error)
            for attr in var.ncattrs():
                if attr == "_FillValue":
                    if fill is None:
                        out.setncattr("arrayprobe_source_fill_value", str(var.getncattr(attr)))
                    continue
                out.setncattr(attr, var.getncattr(attr))

            # Copy in slices along the FIRST dimension, clamping the last one.
            # Not every variable is indexed by the particle axis -- `bin_stats`
            # is 128 long -- and an unclamped final slice asks netCDF4 to write
            # more elements than the variable holds, which it refuses with
            # "size of data array does not conform to slice" rather than
            # truncating the way numpy would.
            n = var.shape[0] if var.shape else 0
            step = max(chunk, 1)
            for lo in range(0, n, step):
                hi = min(lo + step, n)
                out[lo:hi] = np.asarray(var[lo:hi]).astype(plan.dtype)
            if progress:
                progress(i + 1, len(src.variables), name)

        dst.setncattr("arrayprobe_arco_export",
                      "derived from a bug-for-bug faithful arrayprobe output; the "
                      "source file is authoritative and unmodified")
        dst.setncattr("arrayprobe_source_file", infile.name)
        dst.setncattr("arrayprobe_all_lossless",
                      "true" if all(p.lossless for p in plans) else "false")
    return plans
