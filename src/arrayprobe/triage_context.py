# SPDX-License-Identifier: BSD-3-Clause
"""What the triage pages show beside a particle that its product does not state outright.

Four things, each read or recomputed from data the server already holds, never written into a
product (the triage server changes no computed number):

* :func:`reject_outcome` — what the size distribution does with a particle of each automatic
  reject code: kept as is, kept with its size corrected, or rejected.
* :func:`shape_test_habit` — Holroyd's shape test re-run on the particle's own image. UIOOPS
  v3.5's ``imgProc_sm.m:1218-1236`` (the ungated "[EXPERIMENTAL]" hollow block) writes habit
  ``'s'`` for any particle under 0.3 mm whose enclosing-circle centre pixel is unshadowed,
  without running the shape test, so the letter in a v3.5 file is no evidence of shape there:
  on the 2018-02-15 ARM flight 99.2 % of its ``'s'`` particles came from that block (measured
  2026-10-01, every 50th particle). Where the block did not act, the re-run agrees with the
  file letter for every particle measured (the 200-item all-codes queue of that flight).
* :func:`particle_parts` — the separate pieces of shadow in an image, numbered in order along
  the flight, so a reviewer can say which piece of a two-particle image is real; fragments
  within :data:`PIECE_GAP_DIODES` empty diodes of each other count as one piece.
* :class:`MetFolder` — the ambient air temperature at the particle's record time, from ARM's
  merged aircraft files (``enaaafmergedF1.c1.<date>.<time>.nc``, ``ambient_temp`` in °C, one
  row per second).
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

import numpy as np

from arrayprobe_uiops.sizedist_core import GOOD_REJECT_CODES

__all__ = [
    "REJECT_OUTCOMES", "LATER_SCREENS_NOTE", "reject_outcome",
    "shape_test_habit", "particle_parts", "piece_groups", "PIECE_GAP_DIODES", "MetFolder",
    "PIECE_COUNT_CLASSES", "PIECE_COUNT_WORDS", "count_class", "piece_count_class",
]

#: The codes the size distribution keeps, with what happens to each. The kept set is
#: ``sizeDist.m:1460`` in v3.5 and ``:1209`` in v3.1.4, the same five letters both times
#: (:data:`arrayprobe.sizedist.GOOD_REJECT_CODES`); every other code is rejected. ``'H'`` is
#: the only kept code whose size changes: ``imgProc_sm.m:1275-1276`` (v3.5) divides its
#: smallest-circle diameter by the Korolev hollow-particle size factor.
REJECT_OUTCOMES: dict[str, tuple[str, str]] = {
    "0": ("kept", "kept as is"),
    "h": ("kept", "kept as is: hollow, but no hole ratio to correct its size with"),
    "u": ("kept", "kept as is: hollow, but its hole is too small to correct its size"),
    "H": ("corrected", "kept with its size corrected: the smallest-circle diameter is divided "
                       "by the Korolev hollow-particle factor"),
    "R": ("kept", "kept again: the shattering screen removed it and the re-acceptance put it "
                  "back"),
}

if set(REJECT_OUTCOMES) != set(GOOD_REJECT_CODES):  # the page must never mislabel a code
    raise ImportError(f"REJECT_OUTCOMES {sorted(REJECT_OUTCOMES)} disagrees with "
                      f"sizedist.GOOD_REJECT_CODES {GOOD_REJECT_CODES!r}")

#: What the particle file cannot say: the size distribution's own later screens.
LATER_SCREENS_NOTE = (
    "A kept particle can still be dropped by the size distribution's later screens "
    "(shattering, inter-arrival time, area ratio, a centre outside the sample area); "
    "the particle file does not record those.")


def reject_outcome(code) -> tuple[str, str] | None:
    """``(kind, words)`` for an automatic reject code; ``kind`` is ``"kept"``,
    ``"corrected"`` or ``"rejected"``. ``None`` when there is no code to describe."""
    if not isinstance(code, str) or not code:
        return None
    if code in REJECT_OUTCOMES:
        return REJECT_OUTCOMES[code]
    return ("rejected", "rejected: not counted in the size distribution")


def shape_test_habit(c, diode_mm: float) -> str:
    """Holroyd's habit letter from the shape test alone, on the boolean silhouette ``c``
    (``(n_slices, n_diodes)``, the whole record width as ``imgProc_sm`` passes it).

    Uses the v3.5 port's ``holroyd`` (``holroyd.m:7-89`` of v3.5), whose decision tree has
    no stub, so it answers the shape question for files of either engine.
    """
    from arrayprobe_uiops.habit import holroyd

    letter, _ = holroyd(np.asarray(c, dtype=bool), diode_mm)
    return letter


def piece_groups(c, gap: int = 0, scale: str = "constant") -> list[np.ndarray]:
    """The 8-connected pieces of ``c`` grouped single-linkage when the gap between their
    nearest pixels is at most ``gap`` diodes; one boolean mask per group.

    The gap is the Chebyshev distance between the nearest pixels less one, i.e. the number of
    empty pixels between them, so ``gap=0`` is plain 8-connectivity. Exact: dilating every
    pixel by a ``(gap+1)``-square makes two pixels 8-adjacent iff their Chebyshev distance
    is at most ``gap + 1``, so the dilation's components are the single-linkage groups.

    ``scale="larger"`` (opt-in) makes the allowed gap size-scaled: two 8-connected
    components join when their gap is at most ``min(gap, extent of the larger of the two)``,
    extent being ``max(bbox height, bbox width)`` in pixels, single linkage; ``gap`` is then
    the cap. Measured on 441 hand labels of 2018-02-15 with cap 12 it agrees with 393
    against 388 for the best constant gap. The default, ``"constant"``, is unchanged.
    """
    from scipy import ndimage

    if scale not in ("constant", "larger"):
        raise ValueError(f"scale must be 'constant' or 'larger', got {scale!r}")
    c = np.asarray(c, dtype=bool)
    if c.size == 0 or not c.any():
        return []
    if scale == "larger":
        return _piece_groups_larger(c, gap)
    eight = np.ones((3, 3), dtype=int)
    if gap <= 0:
        labels, count = ndimage.label(c, structure=eight)
    else:
        pad = gap + 1
        big = np.pad(c, pad)
        grown = ndimage.binary_dilation(big, structure=np.ones((gap + 1, gap + 1), dtype=bool))
        labels, count = ndimage.label(grown, structure=eight)
        labels = labels[pad:-pad, pad:-pad] * c
    return [labels == lab for lab in range(1, count + 1) if (labels == lab).any()]



def _piece_groups_larger(c: np.ndarray, cap: int) -> list[np.ndarray]:
    """:func:`piece_groups` with ``scale="larger"``: pairwise gaps, size-scaled threshold."""
    from scipy import ndimage

    labels, count = ndimage.label(c, structure=np.ones((3, 3), dtype=int))
    masks = [labels == lab for lab in range(1, count + 1)]
    extents = []
    for m in masks:
        rr, cc = np.nonzero(m)
        extents.append(max(int(rr.max() - rr.min()) + 1, int(cc.max() - cc.min()) + 1))
    parent = list(range(count))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(count):
        # Chebyshev distance from every pixel to component i's nearest pixel.
        dist = ndimage.distance_transform_cdt(~masks[i], metric="chessboard")
        for j in range(i + 1, count):
            pair_gap = int(dist[masks[j]].min()) - 1
            if pair_gap <= min(cap, max(extents[i], extents[j])):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    groups: dict[int, np.ndarray] = {}
    for i in range(count):
        r = find(i)
        groups[r] = groups[r] | masks[i] if r in groups else masks[i].copy()
    return [groups[r] for r in sorted(groups)]

#: Pieces whose nearest pixels are at most this many empty diodes apart are drawn and numbered
#: as one particle. Set to 8. Measured against 441 hand labels
#: of 2018-02-15, G = 7 and G = 8 both agree with 388, the maximum; G = 8
#: joins one more real crystal (6 split, against 7) and merges two of the 27 two-particle
#: labels.
PIECE_GAP_DIODES = 8


def particle_parts(c, gap: int = PIECE_GAP_DIODES, scale: str = "constant") -> list[dict]:
    """The separate pieces of shadow in ``c``, numbered 1, 2, … in order along the flight.

    A piece is a group of 8-connected components whose nearest pixels are at most ``gap``
    empty diodes apart (:func:`piece_groups`; ``gap=0`` is plain 8-connectivity), so one
    fragmented crystal is one piece. Order is by first slice, then first diode, so piece 1 is
    the one the probe met first. Each entry: ``n``, ``pixels``, ``row``/``col`` (centroid, in
    pixels), ``rows``/``cols`` (inclusive first and last). Display only. ``scale`` is passed
    to :func:`piece_groups` (``"larger"``: size-scaled gap, ``gap`` the cap).
    """
    parts: list[dict[str, Any]] = []
    for mask in piece_groups(c, gap, scale):
        rr, cc = np.nonzero(mask)
        parts.append({"pixels": int(rr.size), "row": float(rr.mean()), "col": float(cc.mean()),
                      "rows": (int(rr.min()), int(rr.max())),
                      "cols": (int(cc.min()), int(cc.max()))})
    parts.sort(key=lambda p: (p["rows"][0], p["cols"][0]))
    for n, p in enumerate(parts, start=1):
        p["n"] = n
    return parts


#: The particle-count schema: an image holds
#: one piece, two, or three or more, counted with the size-scaled gap capped at
#: :data:`PIECE_GAP_DIODES`. Display and labelling only; no computed number reads it.
PIECE_COUNT_CLASSES = ("one", "two", "three_or_more")
PIECE_COUNT_WORDS = {"one": "one particle", "two": "two particles",
                     "three_or_more": "three or more particles"}


def count_class(n: int) -> str | None:
    """A piece count as its :data:`PIECE_COUNT_CLASSES` entry; ``None`` for no pieces."""
    if n <= 0:
        return None
    return PIECE_COUNT_CLASSES[min(n, 3) - 1]


def piece_count_class(c, gap: int = PIECE_GAP_DIODES, scale: str = "larger") -> str | None:
    """How many particles ``c`` shows under the particle-count schema: ``"one"``, ``"two"`` or
    ``"three_or_more"`` (``None`` for an empty image).

    Pieces are :func:`piece_groups` with the size-scaled gap by default (``scale="larger"``:
    two components join when the empty diodes between them are at most
    ``min(gap, extent of the larger)``), so specks much smaller than ``gap`` stay separate.
    The gap is counted in diodes, so the rule reads the same at every probe resolution; its
    physical width is ``gap`` times the diode size. Display only.
    """
    return count_class(len(piece_groups(c, gap, scale)))

_MERGED_NAME = re.compile(r"^enaaafmergedF1\.c1\.(\d{8})\.(\d{6})\.nc$")
#: ORACLES P-3 merge files (``mrg1_P3_<date>_R<rev>.nc``): ``Static_Air_Temp`` in degC on
#: ``Start_UTC``, seconds after midnight UTC of the file's date.
_ORACLES_MERGE_NAME = re.compile(r"^mrg1_P3_(\d{8})_R\d+\.nc$")
_TIME_UNITS = re.compile(r"^seconds since (\d{4})-(\d{2})-(\d{2})[ T]00:00:00")


class MetFolder:
    """ARM AAF merged files in one folder, read once each, for the temperature at a second.

    ``temperature_at(yyyymmdd, hhmmss)`` returns ``(degC, file name)`` for the row at that
    second, or ``None`` when no file of that date holds a valid value there. A value is
    invalid when masked, not finite, or at or below -9990 (the files' missing-value
    convention). The time axis is checked,
    not assumed: ``time``'s units must be "seconds since <the file's date> 00:00:00".
    """

    VARIABLE = "ambient_temp"

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._by_date: dict[str, list[Path]] = {}
        for p in sorted(self.folder.glob("enaaafmergedF1.c1.*.nc")):
            m = _MERGED_NAME.match(p.name)
            if m:
                self._by_date.setdefault(m.group(1), []).append(p)
        for p in sorted(self.folder.glob("mrg1_P3_*.nc")):
            m = _ORACLES_MERGE_NAME.match(p.name)
            if m:
                self._by_date.setdefault(m.group(1), []).append(p)
        self._cache: dict[Path, tuple[np.ndarray, np.ndarray] | None] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_date.values())

    def _load(self, path: Path):
        import netCDF4

        with self._lock:
            if path in self._cache:
                return self._cache[path]
            loaded = None
            if _ORACLES_MERGE_NAME.match(path.name):
                loaded = self._load_oracles(path)
                self._cache[path] = loaded
                return loaded
            with netCDF4.Dataset(path) as ds:
                tv = ds.variables.get("time")
                m = _TIME_UNITS.match(getattr(tv, "units", "") or "") if tv is not None else None
                name = _MERGED_NAME.match(path.name)
                assert name is not None  # only names matching _MERGED_NAME are indexed
                date = name.group(1)
                if (tv is not None and m and "".join(m.groups()) == date
                        and self.VARIABLE in ds.variables):
                    t = np.ma.filled(np.ma.asarray(tv[:]).astype(float), np.nan)
                    v = np.ma.filled(np.ma.asarray(ds.variables[self.VARIABLE][:]).astype(float),
                                     np.nan)
                    v[v <= -9990] = np.nan
                    loaded = (t, v)
            self._cache[path] = loaded
            return loaded

    @staticmethod
    def _load_oracles(path: Path):
        """``(seconds of day, degC)`` from an ORACLES merge file, or ``None``.

        ``Start_UTC`` must be in "seconds", and the epoch ``time`` axis minus ``Start_UTC``
        must land on midnight UTC of the date in the file name, so a mislabelled file reads
        as no temperature rather than a wrong one."""
        import datetime as _dt

        import netCDF4

        m = _ORACLES_MERGE_NAME.match(path.name)
        if m is None:  # callers pass only names the pattern matched (:214, :230)
            return None
        date = m.group(1)
        with netCDF4.Dataset(path) as ds:
            su, tv, temp = (ds.variables.get(k) for k in ("Start_UTC", "time", "Static_Air_Temp"))
            if su is None or temp is None or (getattr(su, "units", "") or "").strip() != "seconds":
                return None
            t = np.ma.filled(np.ma.asarray(su[:]).astype(float), np.nan)
            if tv is not None and t.size:
                um = re.match(r"^seconds since 1970-01-01[ T]00:00:00",
                              getattr(tv, "units", "") or "")
                epoch = np.ma.filled(np.ma.asarray(tv[:1]).astype(float), np.nan)
                midnight = _dt.datetime.strptime(date, "%Y%m%d").replace(
                    tzinfo=_dt.UTC).timestamp()
                if not um or not np.isfinite(epoch[0]) or abs(epoch[0] - t[0] - midnight) > 1.0:
                    return None
            v = np.ma.filled(np.ma.asarray(temp[:]).astype(float), np.nan)
            v[v <= -9990] = np.nan
            return t, v

    def temperature_at(self, yyyymmdd, hhmmss) -> tuple[float, str] | None:
        """``(degC, file name)`` for the row at the record second ``hhmmss`` (UTC) of date
        ``yyyymmdd``, from the first file of that date holding a valid value; ``None`` otherwise."""
        try:
            date = f"{int(yyyymmdd):08d}"
            hms = int(hhmmss)
        except (TypeError, ValueError):
            return None
        sec = (hms // 10000) * 3600 + (hms // 100 % 100) * 60 + hms % 100
        for path in self._by_date.get(date, []):
            loaded = self._load(path)
            if loaded is None:
                continue
            t, v = loaded
            hit = np.flatnonzero(t == sec)
            if hit.size and np.isfinite(v[hit[0]]):
                return float(v[hit[0]]), path.name
        return None


class StateFileError(ValueError):
    """A state-variable file that cannot give the air temperature unambiguously."""


_CF_TIME_UNITS = re.compile(
    r"^\s*(seconds?|minutes?|hours?|days?)\s+since\s+(\d{4})-(\d{1,2})-(\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d*)?))?)?\s*(?:Z|UTC|\+0+(?::?0+)?)?\s*$",
    re.IGNORECASE)
_UNIT_SECONDS = {"second": 1.0, "minute": 60.0, "hour": 3600.0, "day": 86400.0}
_CELSIUS_UNITS = {"degc", "deg_c", "deg c", "°c", "c", "celsius", "degree_celsius",
                  "degrees_celsius", "degrees c", "degree c"}
_KELVIN_UNITS = {"k", "kelvin", "degk", "deg_k", "degrees_kelvin"}
#: Words that mark a temperature as something other than the static air temperature.
_NOT_AIR = ("dew", "frost", "potential", "virtual", "total", "skin", "surface", "brightness",
            "equivalent", "wet_bulb", "wet bulb", "wetbulb", "cabin", "housing", "inlet",
            "sensor", "instrument", "probe", "flag", "uncertainty", "std", "qc")


def _attr(var, name: str) -> str:
    return str(getattr(var, name, "") or "").strip()


def _temperature_scale(var) -> str | None:
    """``"C"`` or ``"K"`` from a variable's units, else ``None``."""
    u = _attr(var, "units").lower()
    if u in _CELSIUS_UNITS:
        return "C"
    if u in _KELVIN_UNITS:
        return "K"
    return None


def _cf_time_origin(var) -> tuple[float, float] | None:
    """``(epoch seconds of the origin, seconds per unit)`` for a CF time axis, else ``None``."""
    import datetime as _dt

    m = _CF_TIME_UNITS.match(_attr(var, "units"))
    if not m:
        return None
    unit = m.group(1).lower().rstrip("s")
    y, mo, d = (int(g) for g in m.group(2, 3, 4))
    hh, mm = int(m.group(5) or 0), int(m.group(6) or 0)
    ss = float(m.group(7) or 0.0)
    origin = _dt.datetime(y, mo, d, hh, mm, tzinfo=_dt.UTC).timestamp() + ss
    return origin, _UNIT_SECONDS[unit]


def detect_state_variables(ds, var: str | None = None) -> tuple[str, str]:
    """``(temperature variable, time variable)`` in an open netCDF ``ds``, chosen by content.

    The temperature is a 1-D variable whose units are a temperature (degC/C/K and their
    spellings). With ``var`` given, that variable is used and only checked. Otherwise the
    candidates are ranked: ``standard_name = air_temperature`` first, then a name or
    long_name saying static or ambient air temperature, then any other temperature whose
    name, long_name and standard_name carry none of :data:`_NOT_AIR` (dew point, total,
    potential, ...). More than one candidate in the best rank is refused, listing them, so
    a file never silently gives the wrong temperature. The time variable is the 1-D CF time
    axis ("<unit> since <date>") on the temperature's dimension; more than one is refused.
    """
    vars_ = ds.variables
    if var is not None:
        if var not in vars_:
            found = sorted(n for n in vars_ if _temperature_scale(vars_[n]))
            raise StateFileError(f"no variable {var!r} in the file; temperature-like "
                                 f"variables: {found}")
        if _temperature_scale(vars_[var]) is None or vars_[var].ndim != 1:
            raise StateFileError(f"{var!r} is not a 1-D temperature (units "
                                 f"{_attr(vars_[var], 'units')!r}; need degC, C or K)")
        temp = var
    else:
        ranks: dict[int, list[str]] = {}
        for name, v in vars_.items():
            if v.ndim != 1 or _temperature_scale(v) is None:
                continue
            text = " ".join((name, _attr(v, "long_name"), _attr(v, "standard_name"))).lower()
            if _attr(v, "standard_name").lower() == "air_temperature":
                rank = 0
            elif any(w in text for w in _NOT_AIR):
                continue
            elif "static" in text or "ambient" in text:
                rank = 1
            elif "temp" in text:
                rank = 2
            else:
                continue
            ranks.setdefault(rank, []).append(name)
        if not ranks:
            raise StateFileError("no air-temperature variable found (looked for a 1-D variable "
                                 "with units degC, C or K); name one with --state-var")
        best = ranks[min(ranks)]
        if len(best) > 1:
            raise StateFileError(f"ambiguous air temperature: candidates {', '.join(best)}; "
                                 "name one with --state-var")
        temp = best[0]
    dim = vars_[temp].dimensions[0]
    times = [n for n, v in vars_.items()
             if v.ndim == 1 and v.dimensions[0] == dim and _cf_time_origin(v) is not None]
    if len(times) > 1 and dim in times:
        times = [dim]
    if not times:
        raise StateFileError(f"no CF time axis ('<unit> since <date>') on {temp!r}'s dimension "
                             f"{dim!r} to align on")
    if len(times) > 1:
        raise StateFileError(f"ambiguous time axis for {temp!r}: candidates {', '.join(times)}")
    return temp, times[0]


class StateFile:
    """One state-variable file named by the user, for the temperature at a second.

    The same interface as :class:`MetFolder` (``temperature_at``, ``folder``, ``VARIABLE``,
    ``len``) so the particle page reads either. The variables are chosen by
    :func:`detect_state_variables` at construction, so a file that cannot give an
    unambiguous temperature is refused when it is named, not on the first particle.
    """

    def __init__(self, path: Path, var: str | None = None):
        import netCDF4

        self.path = Path(path)
        self.folder = self.path
        if not self.path.is_file():
            raise StateFileError(f"no such file: {self.path}")
        try:
            ds = netCDF4.Dataset(self.path)
        except OSError as e:
            raise StateFileError(f"not a readable netCDF file: {self.path} ({e})") from e
        with ds:
            temp, time = detect_state_variables(ds, var)
            origin, scale = _cf_time_origin(ds.variables[time])  # type: ignore[misc]
            t = np.ma.filled(np.ma.asarray(ds.variables[time][:]).astype(float), np.nan)
            v = np.ma.filled(np.ma.asarray(ds.variables[temp][:]).astype(float), np.nan)
            kelvin = _temperature_scale(ds.variables[temp]) == "K"
        v[v <= -9990] = np.nan
        if kelvin:
            v = v - 273.15
        self.VARIABLE = temp
        self.time_variable = time
        self._epoch = np.round(origin + t * scale)
        self._v = v

    def __len__(self) -> int:
        return 1

    def temperature_at(self, yyyymmdd, hhmmss) -> tuple[float, str] | None:
        """``(degC, file name)`` at the record second, or ``None`` when no valid value."""
        import datetime as _dt

        try:
            day = _dt.datetime.strptime(f"{int(yyyymmdd):08d}", "%Y%m%d").replace(tzinfo=_dt.UTC)
            hms = int(hhmmss)
        except (TypeError, ValueError):
            return None
        sec = day.timestamp() + (hms // 10000) * 3600 + (hms // 100 % 100) * 60 + hms % 100
        hit = np.flatnonzero(self._epoch == sec)
        if hit.size and np.isfinite(self._v[hit[0]]):
            return float(self._v[hit[0]]), self.path.name
        return None
