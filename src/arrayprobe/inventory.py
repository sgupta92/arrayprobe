# SPDX-License-Identifier: BSD-3-Clause
"""Raw-file inventory: flag empty and truncated raw probe files before processing.

One row per raw file: path, size, SHA-256, ``empty`` (size 0), ``truncated`` (the bytes after
any header are not a whole number of records) and a probe-format guess. Rows are written to a
JSON and a CSV inventory file. Nothing here reads a product or changes a computed number; the
flags live in the inventory file (and in the ``.call`` stamp), never as an
attribute on a product.

Record lengths are the readers' own constants, imported rather than typed:
SPEC ``spec_core.RECORD_BYTES`` (4114), DMT ``readers.dmt._RECORD_BYTES`` (4112), RAF/PMS ``.2d``
``readers.pms._RECORD_BYTES`` (4116, after the XML preamble ending ``</OAP>``, skipped with the
reader's own ``_skip_xml_header``). A format with no fixed record length gets ``truncated=None``.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path

from arrayprobe_uiops.readers import pms as _pms
from arrayprobe_uiops.spec_core import RECORD_BYTES as _SPEC_RECORD_BYTES

from .readers import dmt as _dmt

__all__ = ["RECORD_BYTES", "guess_format", "inventory", "inventory_row", "write_inventory"]

#: Record length per format, read from each reader. ``None``: no fixed record length.
RECORD_BYTES: dict[str, int | None] = {
    "spec": _SPEC_RECORD_BYTES,
    "dmt": _dmt._RECORD_BYTES,
    "pms_2d": _pms._RECORD_BYTES,
    "unknown": None,
}

_SPEC_SUFFIXES = ("2ds", "hvps", "3v", "3vcpi")
_DMT_SUFFIXES = ("dmt", "cip", "pip")
_FIELDS = ("path", "size", "sha256", "format_guess", "record_bytes", "header_bytes",
           "empty", "truncated", "trailing_bytes")


def guess_format(path: str | os.PathLike) -> str:
    """A guess, not a reader decision: ``pms_2d``, ``spec``, ``dmt`` or ``unknown``."""
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            head = fh.read(65536)
    except OSError:
        head = b""
    if head.lstrip().startswith(b"<") and b"</OAP>" in head:
        return "pms_2d"
    suffix = p.suffix.lower().lstrip(".")
    if suffix == "2d":
        return "pms_2d"
    if suffix in _SPEC_SUFFIXES:
        return "spec"
    if suffix in _DMT_SUFFIXES:
        return "dmt"
    return "unknown"


def _header_bytes(path: Path, fmt: str) -> int | None:
    """Bytes before the first record; ``None`` if the reader's header rule finds no end."""
    if fmt != "pms_2d":
        return 0
    with open(path, "rb") as fh:
        try:
            _pms._skip_xml_header(fh)
        except ValueError:
            return None
        return fh.tell()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def inventory_row(path: str | os.PathLike, fmt: str | None = None) -> dict:
    """One inventory row for ``path``; ``fmt`` overrides the guess."""
    p = Path(path)
    size = p.stat().st_size
    fmt = fmt or guess_format(p)
    rec = RECORD_BYTES.get(fmt)
    row = {"path": str(p), "size": size, "sha256": _sha256(p), "format_guess": fmt,
           "record_bytes": rec, "header_bytes": None, "empty": size == 0,
           "truncated": None, "trailing_bytes": None}
    if rec is None or size == 0:
        return row
    hdr = _header_bytes(p, fmt)
    row["header_bytes"] = hdr
    if hdr is None:  # header never ends: nothing after it is a whole record
        row["truncated"] = True
        return row
    trailing = (size - hdr) % rec
    row["trailing_bytes"] = trailing
    row["truncated"] = trailing != 0
    return row


def inventory(paths: str | os.PathLike | Iterable[str | os.PathLike],
              fmt: str | None = None) -> list[dict]:
    """Rows for every regular file in a directory (sorted, non-recursive) or for a list."""
    if isinstance(paths, (str, os.PathLike)) and Path(paths).is_dir():
        files = sorted(q for q in Path(paths).iterdir() if q.is_file())
    elif isinstance(paths, (str, os.PathLike)):
        files = [Path(paths)]
    else:
        files = [Path(q) for q in paths]
    return [inventory_row(f, fmt) for f in files]


def write_inventory(rows: list[dict], out_stem: str | os.PathLike) -> tuple[Path, Path]:
    """Write ``<out_stem>.json`` and ``<out_stem>.csv``; return both paths."""
    # Appended, never with_suffix: a stem like "inv_2026.10.28" keeps every dot.
    jpath, cpath = Path(f"{out_stem}.json"), Path(f"{out_stem}.csv")
    jpath.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    with open(cpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in _FIELDS})
    return jpath, cpath
