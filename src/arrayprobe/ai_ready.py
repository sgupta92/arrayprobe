# SPDX-License-Identifier: BSD-3-Clause
"""A machine check that a file is "AI-ready" in exactly the sense this package claims.

:mod:`arrayprobe.attributed_export` writes OUTPUT 2, the attributed analysis-ready netCDF4 export
(and the opt-in Zarr copy, :func:`~arrayprobe.attributed_export.export_zarr`). Its docstring makes
specific claims; this module turns each into a named check, so the claim is a test and not a
sentence. :func:`check` returns human-readable failures, empty when the file passes.

The criteria, each one function below, each claimed by the exporter and nothing more:

- ``units_and_long_name`` -- every variable carries a non-empty ``units`` and ``long_name``, because
  the exporter states a sourced unit and name on every variable it copies.
- ``acdd_discovery`` -- every name in :data:`~arrayprobe.attributed_export.ACDD_KEYS` is a non-empty
  global attribute, because the exporter writes the ACDD-1.3 discovery block.
- ``conventions_names_acdd`` -- ``Conventions`` contains ``ACDD``, because that is the convention
  the file claims (and the only one: CF is deliberately not claimed, so no CF ``standard_name`` is
  required here).
- ``run_record`` -- ``arrayprobe_call_stamp`` is present and non-empty (a stamp, or the exporter's
  explicit ``ABSENT`` statement), because the file must say how it was made or say that it cannot.
- ``source_hash`` -- ``arrayprobe_source_sha256`` is a 64-hex-digit digest, because it ties the
  export to the exact faithful bytes it was copied from.
- ``encoding_statement`` -- ``arrayprobe_encoding`` is present and non-empty, because the file says
  how it is stored.
- ``chunked_and_compressed`` (netCDF4 only) -- every numeric variable with at least one non-empty
  dimension is chunked (not contiguous) and zlib-compressed, because the default export is the
  analysis-ready encoding (:func:`~arrayprobe.attributed_export.storage_options`). A Zarr store is
  chunked by construction and is not checked here.
- ``no_fill_value`` -- no variable carries ``_FillValue``: the faithful combined writer defines none
  (``combine_sizedist.m:202-231``; missing seconds are NaN) and the exporter adds none. If a future
  faithful source writes one, this check is to be relaxed to compare against that source.

**Further work.** These criteria are the package's own claims. Whether the file also meets a
published AI-readiness checklist is to be checked against a published checklist; none is named
here, because none has been verified against this file.

``python -m arrayprobe.ai_ready FILE [FILE...]`` prints PASS or FAIL per file with its failures and
exits 0 only when every file passes. Zarr support needs the ``[zarr]`` extra (xarray), imported
only when a directory is checked.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from .attributed_export import ACDD_KEYS, ATTR_PREFIX


@dataclass
class _Var:
    name: str
    attrs: Mapping[str, object]
    dtype: np.dtype
    sizes: tuple[int, ...]
    chunking: object = None            # netCDF4: "contiguous" or a list; None when not known
    zlib: bool | None = None           # netCDF4 filters()["zlib"]; None when not known


@dataclass
class _File:
    kind: str                          # "netcdf4" or "zarr"
    attrs: Mapping[str, object]
    variables: list[_Var] = field(default_factory=list)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _read_netcdf(path: Path) -> _File:
    ds = Dataset(str(path), "r")
    try:
        ds.set_auto_maskandscale(False)
        out = _File("netcdf4", {k: ds.getncattr(k) for k in ds.ncattrs()})
        for name, var in ds.variables.items():
            filters = var.filters() or {}
            out.variables.append(_Var(
                name, {k: var.getncattr(k) for k in var.ncattrs()}, np.dtype(var.dtype),
                tuple(len(ds.dimensions[d]) for d in var.dimensions),
                chunking=var.chunking(), zlib=bool(filters.get("zlib"))))
        return out
    finally:
        ds.close()


def _read_zarr(path: Path) -> _File:
    import xarray as xr  # lazy: the [zarr] extra, needed only for a store
    with xr.open_zarr(path, decode_cf=False, mask_and_scale=False, decode_times=False,
                      decode_coords=False, consolidated=False) as ds:
        out = _File("zarr", dict(ds.attrs))
        for name, var in ds.variables.items():
            out.variables.append(_Var(str(name), dict(var.attrs), np.dtype(var.dtype),
                                      tuple(int(n) for n in var.shape)))
        return out


def check_units_and_long_name(f: _File) -> list[str]:
    """Every variable has a non-empty ``units`` and ``long_name`` (the exporter sources both)."""
    return [f"variable {v.name!r} has no non-empty {key!r}"
            for v in f.variables for key in ("units", "long_name") if _blank(v.attrs.get(key))]


def check_acdd_discovery(f: _File) -> list[str]:
    """Every ACDD discovery attribute the exporter writes is present and non-empty."""
    return [f"global attribute {key!r} (ACDD discovery) is missing or empty"
            for key in ACDD_KEYS if _blank(f.attrs.get(key))]


def check_conventions_names_acdd(f: _File) -> list[str]:
    """``Conventions`` names ACDD, the convention the file claims."""
    value = f.attrs.get("Conventions")
    if isinstance(value, str) and "ACDD" in value:
        return []
    return [f"global attribute 'Conventions' does not name ACDD (got {value!r})"]


def check_run_record(f: _File) -> list[str]:
    """``arrayprobe_call_stamp`` is present: the run record, or the explicit ABSENT statement."""
    if _blank(f.attrs.get(f"{ATTR_PREFIX}call_stamp")):
        return [f"global attribute '{ATTR_PREFIX}call_stamp' (the run record, or its ABSENT "
                f"statement) is missing or empty"]
    return []


def check_source_hash(f: _File) -> list[str]:
    """``arrayprobe_source_sha256`` is a sha256 digest tying the export to the faithful bytes."""
    value = f.attrs.get(f"{ATTR_PREFIX}source_sha256")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return []
    return [f"global attribute '{ATTR_PREFIX}source_sha256' is missing or not a sha256 digest "
            f"(got {value!r})"]


def check_encoding_statement(f: _File) -> list[str]:
    """``arrayprobe_encoding`` states how the file is stored."""
    if _blank(f.attrs.get(f"{ATTR_PREFIX}encoding")):
        return [f"global attribute '{ATTR_PREFIX}encoding' is missing or empty"]
    return []


def check_chunked_and_compressed(f: _File) -> list[str]:
    """netCDF4: every numeric variable with a non-empty dimension is chunked and zlib-compressed."""
    if f.kind != "netcdf4":
        return []
    failures = []
    for v in f.variables:
        if v.dtype.kind not in "biuf" or not v.sizes or any(n == 0 for n in v.sizes):
            continue
        if v.chunking == "contiguous":
            failures.append(f"variable {v.name!r} is stored contiguous, not chunked")
        if not v.zlib:
            failures.append(f"variable {v.name!r} is not zlib-compressed")
    return failures


def check_no_fill_value(f: _File) -> list[str]:
    """No variable carries ``_FillValue``: the faithful writer defines none, the export none."""
    return [f"variable {v.name!r} carries a _FillValue the faithful source never wrote"
            for v in f.variables if "_FillValue" in v.attrs]


#: Every named check, in report order.
CHECKS: tuple[tuple[str, Callable[[_File], list[str]]], ...] = (
    ("units_and_long_name", check_units_and_long_name),
    ("acdd_discovery", check_acdd_discovery),
    ("conventions_names_acdd", check_conventions_names_acdd),
    ("run_record", check_run_record),
    ("source_hash", check_source_hash),
    ("encoding_statement", check_encoding_statement),
    ("chunked_and_compressed", check_chunked_and_compressed),
    ("no_fill_value", check_no_fill_value),
)


def check(path: Path | str) -> list[str]:
    """Failures for the netCDF4 file or Zarr store (a directory) at ``path``; empty = passes.

    Each failure is prefixed with the name of the check that produced it."""
    path = Path(path)
    try:
        f = _read_zarr(path) if path.is_dir() else _read_netcdf(path)
    except Exception as exc:  # an unreadable file fails the check; it does not crash the CLI
        return [f"unreadable: {type(exc).__name__}: {exc}"]
    return [f"{name}: {msg}" for name, fn in CHECKS for msg in fn(f)]


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m arrayprobe.ai_ready FILE [FILE...]``; exit 0 only when every file passes."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or any(a in ("-h", "--help") for a in args):
        print("usage: python -m arrayprobe.ai_ready FILE [FILE...]\n"
              "Check netCDF4 files or Zarr stores against the AI-ready claims of "
              "arrayprobe.attributed_export.")
        return 0 if args else 2
    ok = True
    for arg in args:
        failures = check(arg)
        print(f"{'PASS' if not failures else 'FAIL'} {arg}")
        for msg in failures:
            print(f"  - {msg}")
        ok = ok and not failures
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
