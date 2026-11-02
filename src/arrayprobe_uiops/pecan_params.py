# SPDX-License-Identifier: BSD-3-Clause
"""A user-supplied stand-in for ``getPECANparams`` -- opt-in, required for PECAN, no default.

Both UIOOPS releases' ``sizeDist.m`` call, in the PECAN ``CIP`` and ``PIP`` cases (v3.5
``:164``/``:195``, v3.1.4 ``:132``/``:163``) ``getPECANparams(ddate, probename)``, keeping
its first, second and fifth outputs (window start times, end times and per-window thresholds).
The lines that follow (v3.1.4 ``:134-138``) fill the threshold series with
``defaultIntArrThresh`` and, for every TAS time inside a window ``[start, end)``, replace it
with that window's threshold.

``getPECANparams.m`` ships in no release, so MATLAB dies there and both engines refuse the
project. A run that names a parameter file gets exactly the loop above with the file's values
in place of the function's three used outputs; the two discarded outputs (``~``) are never
read, so the file does not carry them. Nothing here supplies a value the file does not.

File format (CSV, ``#`` lines are comments, header row required, column order free)::

    start_s,end_s,intar_threshold_s
    50400,51000,2.5e-6
    51600,52200,1.0e-5

``start_s``/``end_s`` are seconds after midnight of the flight date in ``sizeDist.m``'s own
``tas_time`` convention (so a flight past midnight carries values above 86400, as the
``+240000`` rollover makes ``tas_time``); a second is in a spiral when
``start_s <= tas_time < end_s``. ``intar_threshold_s`` is that spiral's inter-arrival
threshold in seconds. Two optional columns, ``date`` (``YYYYMMDD``) and ``probe``, restrict a
row to the ``ddate`` and ``probename`` the MATLAB call passes, so one file can hold a
campaign; a file with neither column applies to the run it is given to. A file (after that
filter) with no rows is refused rather than read as "no spirals".
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["PecanParams", "load_pecan_params", "pecan_intar_threshold", "resolve_pecan_params"]

_REQUIRED = ("start_s", "end_s", "intar_threshold_s")


@dataclass(frozen=True)
class PecanParams:
    """The three ``getPECANparams`` outputs ``sizeDist.m`` reads, one entry per spiral."""

    startT: Any  # noqa: N815 -- MATLAB names, deliberately
    endT: Any  # noqa: N815
    intar_threshold_spirals: Any
    source: str = ""

    def __post_init__(self) -> None:
        arrays = [np.asarray(a, dtype=np.float64).reshape(-1)
                  for a in (self.startT, self.endT, self.intar_threshold_spirals)]
        if not (arrays[0].size == arrays[1].size == arrays[2].size):
            raise ValueError("startT, endT and intar_threshold_spirals must have one entry "
                             "per spiral each")
        if arrays[0].size == 0:
            raise ValueError("PECAN parameters with no spirals: refused rather than read as "
                             "'no spiral', which would silently apply defaultIntArrThresh "
                             "to every second")
        if not all(np.isfinite(a).all() for a in arrays):
            raise ValueError("PECAN parameters must be finite numbers")
        if (arrays[2] < 0).any():
            raise ValueError("intar_threshold_s is a time in seconds and cannot be negative")
        object.__setattr__(self, "startT", arrays[0])
        object.__setattr__(self, "endT", arrays[1])
        object.__setattr__(self, "intar_threshold_spirals", arrays[2])


def _ddate_key(ddate: Any) -> str:
    """``YYYYMMDD`` from ``ddate`` (``'YYYYMMDD'`` or the driver's ``'YYYYMMDD HHMMSS'``)."""
    return str(ddate).strip()[:8]


def load_pecan_params(path: str | PathLike[str], *, ddate: Any = None,
                      probename: str | None = None) -> PecanParams:
    """Read the CSV described in the module docstring, filtered to ``ddate``/``probename``
    where the file carries ``date``/``probe`` columns."""
    p = Path(path)
    with p.open(newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(lines)
    fields = [f.strip() for f in (reader.fieldnames or [])]
    missing = [c for c in _REQUIRED if c not in fields]
    if missing:
        raise ValueError(f"{p}: PECAN parameter file lacks column(s) {missing}; "
                         f"required: {list(_REQUIRED)}")
    rows = []
    for row in reader:
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k is not None}
        if "date" in row and ddate is not None and row["date"] != _ddate_key(ddate):
            continue
        if "probe" in row and probename is not None and row["probe"] != probename:
            continue
        rows.append(row)
    if not rows:
        raise ValueError(f"{p}: no PECAN spiral rows for date={_ddate_key(ddate)!r} "
                         f"probe={probename!r}")
    try:
        cols = [[float(r[c]) for r in rows] for c in _REQUIRED]
    except ValueError as exc:
        raise ValueError(f"{p}: a PECAN parameter is not a number ({exc})") from None
    if not all(math.isfinite(v) for col in cols for v in col):
        raise ValueError(f"{p}: PECAN parameters must be finite numbers")
    return PecanParams(cols[0], cols[1], cols[2], source=str(p))


def resolve_pecan_params(value: Any, *, ddate: Any, probename: str | None) -> PecanParams:
    """A :class:`PecanParams` from a path or an existing record."""
    if isinstance(value, PecanParams):
        return value
    if isinstance(value, (str, PathLike)):
        return load_pecan_params(value, ddate=ddate, probename=probename)
    raise TypeError(f"pecan_params is a path to a parameter file or a PecanParams; "
                    f"got {type(value).__name__}")


def pecan_intar_threshold(tas_time: Any, params: PecanParams,
                          default_int_arr_thresh: float) -> np.ndarray:
    """``intar_threshold`` exactly as ``sizeDist.m``'s PECAN loop builds it: the default every
    second, then each spiral in file order overwriting the seconds in ``[startT, endT)``, so
    where spirals overlap the later one wins, as the inner loop's last assignment does."""
    tas_time = np.asarray(tas_time, dtype=np.float64).reshape(-1)
    out = np.ones(tas_time.shape) * default_int_arr_thresh
    for s, e, t in zip(params.startT, params.endT, params.intar_threshold_spirals,
                       strict=True):
        out[(tas_time >= s) & (tas_time < e)] = t
    return out
