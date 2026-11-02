# SPDX-License-Identifier: BSD-3-Clause
"""Write the aircraft TAS file stock ``imgProc_sm.m`` reads as ``varargin{1}``.

Built 2026-09-16 on the cold-start usability audit's finding 1.2. The v3.5 engine
-- the package default, the one the Configuration page's decision tree sends a new user to
-- refuses to run without this file, citing ``imgProc_sm.m:183-185``. The refusal is good.
The problem the audit measured is that **no page stated the file's contents**: `<aircraft
TAS file>` appeared as a placeholder in the decision tree and as a path in an example, and
the only way to learn the schema was to open a tracked fixture with ``netCDF4``. So a
scientist with their own 2D-S data and no ORACLES involvement could not run the default
engine at all.

**The schema, read off what the port actually does** (``imgproc.py:531-532``)::

    tas      = ncio.ncread(tas_file, "TAS")     # m/s
    tas_time = ncio.ncread(tas_file, "Time")    # HHMMSS

Two 1-D variables of equal length, read by those exact names through ``ncread`` (so any
``scale_factor``/``add_offset``/``_FillValue`` a file carries is applied). ``Time`` is
HHMMSS-as-a-number -- 06:06:38 is ``60638.0``, not seconds since an epoch -- because
``imgProc_sm`` compares it against the probe's own housekeeping clock, which is HHMMSS.
Nothing else in the file is read: no units attribute, no global attribute, no dimension
name is required. This tool writes ``f8`` for both and names the dimension ``time``,
matching ``scripts/make_demo_reference.write_aircraft_v35`` and the tracked fixture
``tests/data/demo_flight_v35_aircraft.cdf``.

**Where the numbers come from.** Two sources, and the tool refuses to invent a third:

* ``--from-tas-csv <stem>.tas.csv`` -- the sidecar S2 already writes beside every decode
  (``read_binary_SPEC.m``'s own ``.tas.csv``), whose first two columns are exactly
  ``timehhmmss, tas``. This is the audit's own suggestion, and it is the path to use when
  the probe recorded the aircraft speed. Parsed by
  :func:`arrayprobe.readers.tasinfo.load_tas_info`, so the two columns are read by the
  same code ``loadTASinfo_2DS.m`` is ported into rather than by a second parser that could
  disagree with it.
* ``--constant-tas`` with ``--start-hhmmss`` and ``--seconds`` -- a flat series, for a
  campaign whose TAS is held outside the probe file. **Named a constant explicitly**, so
  it cannot be mistaken for a measurement: the tool will not derive a "typical" speed from
  anything.

**The S2 ``.tas.csv`` is sub-second and jittered** (``110126.232``, ``124834.999``,
``124838.000``, ...), and ``imgProc_sm.m:727`` (``imgproc.py:1027``) looks each image record's
integer HHMMSS up by **exact equality**. A fractional ``Time`` therefore matches almost never
and every record silently falls back to 170 m/s (``imgproc.py:118``) -- measured 2026-09-23 on
every finished ORACLES 2017 v3.5 product --
and a repeated integer ``Time`` makes MATLAB die at ``:738`` (the
port raises). So the CSV path reduces to whole seconds, and :func:`write_tas_file` refuses a
``Time`` that is non-finite, non-integer or repeated. The port's refusal is faithful and stays;
the remedy lives here, in the sidecar builder, never in the engine.

**The reduction takes two design decisions; both are the defaults and both stay
options:**

* ``--second-rule {round,floor}``, default **round** -- how a fractional HHMMSS becomes a
  second. They collide different pairs (``124835.999`` is 124836 under round, 124835 under
  floor).
* ``--neighbour {adjacent,nearest-present}``, default **adjacent** -- what "the previous or the
  next time step" means: the second just before / just after (s-1, s+1; absent if missing), or
  the nearest second that is present. At 124838 of ``base170821110122`` the first resolves and
  the second does not.

**Out-of-range TAS and unsettled duplicates fall to a default -- nothing is dropped (author;
this replaces an earlier ruling to drop such rows):** *"never drop, use a cutoff and a default
to fall to, provide user an option to select both in config so nothing is hard coded."* A row
whose TAS is above the cutoff, at or below 0 m/s (the decode's -999 marker) or non-finite is set
aside before the duplicate comparison; a second left with no in-range row, and a duplicated
second the duplicate rule cannot settle, both **take the default value**. The cutoff and the default
are a :class:`TasPolicy` -- ``--cutoff-mps`` / ``--default-mps`` here, ``[tas].cutoff_mps`` /
``[tas].default_mps`` in a run configuration -- whose documented defaults are
:data:`DEFAULT_CUTOFF_MPS` = 300 m/s (the largest ``tas_max`` in UIOOPS's probe table,
``constants.py:492``, ``:559``) and :data:`DEFAULT_FALLBACK_MPS` = 170 m/s
(the value ``imgProc_sm.m:365``/``:763`` falls back to; the engine's own ``TAS_FALLBACK`` is not
touched or read by this module). Every substituted second is printed, one line each, and listed
in the file's global attributes (``tas_substituted_seconds``, with its reason).

**When two samples land on one second: the author's rule, verbatim:**
*"For the Oracle's flight that fails, you look at the true airspeed from either of the previous
or the next time steps, and whatever looks the same as the double time step, you take that."*
+ *"and you document that decision and put it up whenever it comes up in the processing
chain."* Implemented as: all candidates identical -> keep one; exactly one distinct candidate
value equals the previous or next second's TAS (exact equality) -> keep it; otherwise
(several match, none matches, or no neighbour) -> **the rule picks nothing, and the second takes
the default**, printed as ``TAS substituted: <HHMMSS> ... unsettled-duplicate``.
``--on-unsettled refuse`` keeps the stop-and-list behaviour available (write no file, list the
seconds). A neighbour second that itself holds several distinct values, or was itself
substituted, counts as having no known TAS. Every resolved second is printed, one line each, and
recorded in the file's global attributes (``tas_duplicate_rule``, ``tas_duplicates_resolved``,
``tas_duplicates_resolved_seconds``, ...).

**Aircraft sources** (``--from-merge``, ``--from-aircraft``, ``--chain``) are
:mod:`arrayprobe.tools.tas_sources`: the ORACLES P-3 merge file and ARM's AAF merged file, read
off real files and listed in a registry there, converted by the units attribute each carries,
under the same :class:`TasPolicy`.

The ``--constant-tas`` path copies nothing measured and writes ``Time`` exactly as given
(whole seconds by construction).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = ["write_tas_file", "check_tas_series", "tas_from_csv", "constant_tas",
           "whole_second_series", "reduce_probe_csv", "TasPolicy", "DEFAULT_CUTOFF_MPS",
           "DEFAULT_FALLBACK_MPS", "SECOND_RULES", "NEIGHBOUR_RULES", "UNSETTLED_RULES",
           "TAS_DUPLICATE_RULE", "build_parser", "main"]

#: The two variable names ``imgproc.py:531-532`` reads. Named here so a rename there is a
#: test failure rather than a file this tool writes that the engine cannot read.
TAS_VARIABLE = "TAS"
TIME_VARIABLE = "Time"

#: The two reductions to whole seconds. The choice is the author's (no default anywhere).
SECOND_RULES = ("round", "floor")
#: The two readings of "the previous or the next time step". The author's choice.
NEIGHBOUR_RULES = ("adjacent", "nearest-present")
#: Written into the file so the decision travels with every product built from it.
TAS_DUPLICATE_RULE = ("Rule: keep the duplicate whose TAS equals the previous "
             "or next second's; when it picks no candidate the second takes the default "
             "value")
#: The author's choices (2026-09-23): round to the second, and "neighbour" is
#: the second just before / just after. Defaults because the author set them; still options.
AUTHOR_SECOND_RULE = "round"
AUTHOR_NEIGHBOUR_RULE = "adjacent"
#: Documented DEFAULTS for the two options, never read by the logic directly: every
#: function takes a :class:`TasPolicy`, and these are only what one is built with when the
#: caller names nothing. 300 m/s is the largest ``tas_max`` in UIOOPS's probe table
#: (constants.py:492, :559); 170 m/s is the value
#: ``imgProc_sm.m:365``/``:763`` falls back to (``tests/test_tas_sources.py`` asserts it equals
#: ``arrayprobe.imgproc.TAS_FALLBACK`` -- read from the engine, compared, never imported here).
DEFAULT_CUTOFF_MPS = 300.0
DEFAULT_FALLBACK_MPS = 170.0
#: A TAS at or below this is not a speed (author: "default yes") -- it catches the
#: decode's -999 "no TAS" marker, which MATLAB would otherwise use as a speed
#: (``imgProc_sm.m:730`` substitutes the fallback only for an empty or NaN match). This one is a
#: definition rather than an option: a non-positive airspeed is not an airspeed.
TAS_NONPOSITIVE_MPS = 0.0
#: What happens to a duplicated second the neighbour rule cannot settle. The author's ruling
#: is that it takes the default value. ``"refuse"`` keeps the stop-and-list behaviour.
UNSETTLED_RULES = ("default", "refuse")
AUTHOR_UNSETTLED_RULE = "default"


def write_tas_csv(path: str | Path, time_hhmmss: Sequence[float] | np.ndarray,
                  tas_mps: Sequence[float] | np.ndarray,
                  seconds_of_day: Sequence[float] | np.ndarray | None = None) -> int:
    """Write the nine-column ``.tas.csv`` and return the row count.

    Columns 1-2 are ``timehhmmss, tas``, the only two
    :func:`arrayprobe.readers.tasinfo.load_tas_info` and ``loadTASinfo_2DS.m``'s
    ``'%f%f%*s%*s%*s%*s%*s%*s%*s'`` read. Column 3 carries the seconds of day the HHMMSS was
    packed from, and 4-9 are ``0`` -- the same nine-field shape
    the CIP-housekeeping TAS producer writes, so the two SEA-chain TAS producers hand the
    pipeline the same thing.
    """
    t = np.asarray(time_hhmmss, dtype=np.float64).ravel()
    v = np.asarray(tas_mps, dtype=np.float64).ravel()
    if t.size != v.size:
        raise ValueError(f"time has {t.size} samples and tas has {v.size}")
    if t.size == 0:
        raise ValueError("refusing to write an empty .tas.csv")
    s = (np.asarray(seconds_of_day, dtype=np.float64).ravel()
         if seconds_of_day is not None else np.zeros_like(t))
    lines = [f"{float(a):f}, {float(b):f}, {float(c):f}, 0, 0, 0, 0, 0, 0\n"
             for a, b, c in zip(t, v, s, strict=True)]
    Path(path).write_text("".join(lines))
    return len(lines)


@dataclass(frozen=True)
class TasPolicy:
    """The TAS policy pair: a cutoff above which a TAS is not believed, and the value a second
    falls to when its TAS is out of range or unsettled. Both configurable (``[tas]`` in a run
    configuration, ``--cutoff-mps``/``--default-mps`` on the command line)."""

    cutoff_mps: float = DEFAULT_CUTOFF_MPS
    default_mps: float = DEFAULT_FALLBACK_MPS

    def __post_init__(self):
        c, d = float(self.cutoff_mps), float(self.default_mps)
        if not (np.isfinite(c) and np.isfinite(d)):
            raise ValueError(f"TAS policy values must be finite, got cutoff={c!r}, default={d!r}")
        if c <= TAS_NONPOSITIVE_MPS:
            raise ValueError(f"TAS cutoff must be above {TAS_NONPOSITIVE_MPS:g} m/s, got {c!r}")
        if not TAS_NONPOSITIVE_MPS < d <= c:
            raise ValueError(f"TAS default must lie in ({TAS_NONPOSITIVE_MPS:g}, cutoff={c:g}] "
                             f"m/s so a substituted second passes the same check, got {d!r}")

    def reason(self, value: float) -> str | None:
        """Why ``value`` is out of range (``None`` when it is in range)."""
        if not np.isfinite(value):
            return "non-finite"
        if value > self.cutoff_mps:
            return "above-cutoff"
        if value <= TAS_NONPOSITIVE_MPS:
            return "non-positive"
        return None

    def token(self) -> str:
        """One-line, round-trippable form, for ``.call`` stamps, attributes and worker argv."""
        return f"cutoff={float(self.cutoff_mps)!r},default={float(self.default_mps)!r}"

    @classmethod
    def parse(cls, token: str) -> TasPolicy:
        """The inverse of :meth:`token`: ``"cutoff=300.0,default=170.0"`` -> a policy."""
        fields = dict(part.split("=", 1) for part in token.split(","))
        return cls(float(fields["cutoff"]), float(fields["default"]))

    def attributes(self) -> dict:
        """The policy as file attributes: the token, both speeds and a note on the rule."""
        return {
            "tas_policy": self.token(),
            "tas_cutoff_mps": float(self.cutoff_mps),
            "tas_default_mps": float(self.default_mps),
            "tas_policy_note": (
                "Rule: never drop; a TAS above tas_cutoff_mps, at or below "
                "0 m/s (incl. the -999 no-TAS marker) or non-finite, and a duplicated second the "
                "duplicate rule cannot settle, take tas_default_mps. Documented defaults 300 m/s "
                "(largest UIOPS tas_max) and 170 m/s (imgProc_sm.m:365/"
                ":763's fallback); both configurable ([tas] in a run config, "
                "--cutoff-mps/--default-mps)"),
        }


def second_ranges(seconds) -> str:
    """``[124838, 124839, 124840, 130000]`` -> ``"124838-124840,130000"`` (HHMMSS, contiguous
    in seconds of day), so an attribute can list every substituted second compactly."""
    secs = sorted({int(s) for s in seconds})
    if not secs:
        return ""
    sod = [int(_hhmmss_to_sod([s])[0]) for s in secs]
    out, i = [], 0
    while i < len(secs):
        j = i
        while j + 1 < len(secs) and sod[j + 1] == sod[j] + 1:
            j += 1
        out.append(f"{secs[i]:06d}" if i == j else f"{secs[i]:06d}-{secs[j]:06d}")
        i = j + 1
    return ",".join(out)


def check_tas_series(time_hhmmss, tas_mps) -> tuple[np.ndarray, np.ndarray]:
    """Refuse a ``(Time, TAS)`` series that ``imgProc_sm.m:727``'s exact-match lookup cannot use.

    The one check every aircraft series passes before the engine sees it -- the file this
    tool writes, and an aircraft file ``run_flight.py`` is handed
    directly, such as ARM's merged file. Returns the two arrays as 1-D float64.
    """
    time_hhmmss = np.asarray(time_hhmmss, dtype=np.float64).ravel()
    tas_mps = np.asarray(tas_mps, dtype=np.float64).ravel()
    if time_hhmmss.size != tas_mps.size:
        raise ValueError(
            f"Time has {time_hhmmss.size} samples and TAS has {tas_mps.size}; "
            "imgProc_sm.m:183-185 indexes them together, so they must be the same length")
    if time_hhmmss.size == 0:
        raise ValueError("no samples: a TAS file with an empty time axis sets no "
                         "particle time at all")
    bad = ~np.isfinite(time_hhmmss)
    if bad.any():
        raise ValueError(f"{int(bad.sum())} non-finite Time value(s): imgProc_sm.m:727 "
                         "matches Time by exact equality, so such a row can never match")
    frac = time_hhmmss != np.floor(time_hhmmss)
    if frac.any():
        raise ValueError(
            f"{int(frac.sum())} of {time_hhmmss.size} Time values are not whole seconds "
            f"(first: {time_hhmmss[frac][0]!r}): imgProc_sm.m:727 looks the record's integer "
            "HHMMSS up by exact equality, so a fractional Time never matches and every record "
            "silently takes the 170 m/s fallback (imgproc.py:118). Reduce to whole seconds "
            "first (make-tas-file --from-tas-csv ... --second-rule {round,floor})")
    uniq, counts = np.unique(time_hhmmss, return_counts=True)
    if (counts > 1).any():
        rep = uniq[counts > 1]
        raise ValueError(
            f"{rep.size} repeated Time value(s) (first: {rep[0]:.0f}): a second with more "
            "than one TAS makes imgProc_sm.m:738 fail (the port raises too). Resolve the "
            "duplicates first (make-tas-file --from-tas-csv, the duplicate rule)")
    t = time_hhmmss.astype(np.int64)
    # UIOOPS's midnight convention is unwrapped: a flight crossing midnight keeps counting
    # 240000, 240001, ... rather than wrapping to 000000 (sizeDist.m:98-99/:657-658's
    # +240000 rollover, ported as arrayprobe.sizedist._rollover_240000).
    # So an hour of 24-47 (one further midnight crossing) is a
    # valid clock hour here, not "probably seconds since some epoch" -- only the minute and
    # second fields, and an hour past what one rollover can reach, distinguish a real epoch
    # value from an unwrapped clock time.
    bad_clock = (t < 0) | (t // 10000 > 47) | (t % 100 >= 60) | ((t // 100) % 100 >= 60)
    if bad_clock.any():
        raise ValueError(
            f"{int(bad_clock.sum())} of {t.size} Time values are not a clock time HHMMSS "
            f"(first: {t[bad_clock][0]}): the axis is probably seconds since some epoch, which "
            "never equals the record's HHMMSS at imgProc_sm.m:727, so every particle would "
            "silently take the 170 m/s fallback (imgproc.py:118)")
    return time_hhmmss, tas_mps


def write_tas_file(path, time_hhmmss, tas_mps, *, provenance: dict | None = None) -> Path:
    """Write ``path`` as NETCDF3_CLASSIC with ``Time`` (HHMMSS) and ``TAS`` (m/s), f8.

    NETCDF3_CLASSIC for the same reason every other file this package writes is
    (MATLAB's bare ``'clobber'`` default). Both arrays must be 1-D and the
    same length -- ``imgProc_sm`` indexes them together, so a mismatch here would be a
    silently misaligned time base rather than an error at read time.
    """
    import netCDF4

    time_hhmmss, tas_mps = check_tas_series(time_hhmmss, tas_mps)
    path = Path(path)
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", time_hhmmss.size)
        # units/long_name are written for the human who opens the file. The engine reads
        # neither (imgproc.py:531-532 is two bare ncread calls), so adding them changes no
        # computed number -- the audit's own complaint about the combined product, answered
        # here rather than repeated.
        v_time = ds.createVariable(TIME_VARIABLE, "f8", ("time",))
        v_time.units = "HHMMSS"
        v_time.long_name = "time of day as HHMMSS, the probe housekeeping clock's own base"
        v_time[:] = time_hhmmss
        v_tas = ds.createVariable(TAS_VARIABLE, "f8", ("time",))
        v_tas.units = "m s-1"
        v_tas.long_name = "aircraft true air speed"
        v_tas[:] = tas_mps
        # Global attributes only: the engine reads Time and TAS and nothing else
        # (imgproc.py:531-532), so provenance here changes no computed number.
        for key, value in (provenance or {}).items():
            ds.setncattr(key, value)
    return path


def tas_from_csv(csv_path) -> tuple[np.ndarray, np.ndarray]:
    """``(Time, TAS)`` from a ``<stem>.tas.csv`` the decode wrote.

    Delegates to :func:`arrayprobe.readers.tasinfo.load_tas_info` -- the port of
    ``loadTASinfo_2DS.m`` -- rather than parsing the CSV again here, so the two columns
    this tool copies are the two columns the MATLAB lineage reads.
    """
    from arrayprobe.readers.tasinfo import load_tas_info

    return load_tas_info(csv_path)


def _hhmmss_to_sod(hhmmss) -> np.ndarray:
    """HHMMSS (possibly fractional) to fractional seconds of day: the formula of
    ``scripts/tas_from_probe_housekeeping.hhmmss_to_seconds`` (``:57-63``) without
    its ``floor`` on the seconds, because the reduction is chosen separately (``second_rule``).
    Copied, not imported: ``scripts/`` is not importable from ``src/``."""
    h = np.asarray(hhmmss, dtype=np.float64)
    hh = np.floor(h / 10000.0)
    mm = np.floor((h - hh * 10000.0) / 100.0)
    ss = h - hh * 10000.0 - mm * 100.0
    return hh * 3600.0 + mm * 60.0 + ss


def _sod_to_hhmmss(sod) -> np.ndarray:
    """Whole seconds of day back to HHMMSS: ``tas_from_probe_housekeeping._hhmmss``
    (``:119-121``), copied. HHMMSS does not carry by adding 1, so the carry is done here."""
    s = np.asarray(sod, dtype=np.int64)
    return ((s // 3600) * 10000 + ((s % 3600) // 60) * 100 + (s % 60)).astype(np.float64)


def whole_second_series(time_hhmmss, tas, *, second_rule: str = AUTHOR_SECOND_RULE,
                        neighbour: str = AUTHOR_NEIGHBOUR_RULE,
                        policy: TasPolicy | None = None,
                        unsettled: str = AUTHOR_UNSETTLED_RULE):
    """Reduce a sub-second ``(Time, TAS)`` series to one sample per whole second.

    ``second_rule`` (``"round"`` = ``floor(sod + 0.5)``, ``"floor"`` = ``floor(sod)``) and
    ``neighbour`` (``"adjacent"`` = s-1 / s+1 only, ``"nearest-present"`` = the nearest
    second present on each side) default to round and adjacent.

    Rows out of range under ``policy`` (above its cutoff, at/below 0 m/s, non-finite) are set
    aside before grouping, one ``class="out-of-range"`` record per second: ``remaining`` says
    whether in-range rows keep that second; if not, the second **takes ``policy.default_mps``**
    (``fallback``). A duplicated second the rule cannot settle (``class="ambiguous"``) takes the
    default too under ``unsettled="default"``; under ``"refuse"`` it is left out of the series and
    the caller must refuse to write. Nothing is dropped under the default.

    Returns ``(time, tas, report)``. One record (a dict) per second with more than one sample or
    an out-of-range row: ``second`` (HHMMSS int), ``class`` (``identical`` / ``unambiguous`` /
    ``ambiguous`` / ``out-of-range``), ``candidates`` (every TAS, row order), ``prev`` / ``next``
    (the neighbour's TAS; ``None`` when absent, substituted, or itself holding several distinct
    values), ``prev_missing`` / ``next_missing``, ``kept`` (``None`` when ambiguous),
    ``fallback`` (the default value the second took, else ``None``), ``reasons``.
    """
    if second_rule not in SECOND_RULES:
        raise ValueError(f"second_rule must be one of {SECOND_RULES}, got {second_rule!r}")
    if neighbour not in NEIGHBOUR_RULES:
        raise ValueError(f"neighbour must be one of {NEIGHBOUR_RULES}, got {neighbour!r}")
    if unsettled not in UNSETTLED_RULES:
        raise ValueError(f"unsettled must be one of {UNSETTLED_RULES}, got {unsettled!r}")
    policy = policy or TasPolicy()
    t = np.asarray(time_hhmmss, dtype=np.float64).ravel()
    v = np.asarray(tas, dtype=np.float64).ravel()
    if t.size != v.size:
        raise ValueError(f"Time has {t.size} samples and TAS has {v.size}")
    sod = _hhmmss_to_sod(t)
    key = (np.floor(sod + 0.5) if second_rule == "round" else np.floor(sod)).astype(np.int64)

    groups: dict[int, list[float]] = {}
    aside: dict[int, list[float]] = {}
    reasons: dict[int, list[str]] = {}
    for k, x in zip(key.tolist(), v.tolist(), strict=True):
        why = policy.reason(x)
        if why is None:
            groups.setdefault(k, []).append(x)
        else:
            aside.setdefault(k, []).append(x)
            reasons.setdefault(k, []).append(why)
    report: list[dict] = [{
        "second": int(_sod_to_hhmmss([k])[0]), "class": "out-of-range",
        "candidates": vals, "prev": None, "next": None, "prev_missing": False,
        "next_missing": False, "kept": None, "remaining": k in groups,
        "fallback": None if k in groups else float(policy.default_mps),
        "reasons": list(dict.fromkeys(reasons[k])),
    } for k, vals in sorted(aside.items())]

    def known(k):
        vals = groups.get(k)
        if vals is None or len(set(vals)) != 1:
            return None
        return vals[0]

    out: dict[int, float] = {k: float(policy.default_mps) for k in aside if k not in groups}
    seconds = sorted(groups)
    for i, k in enumerate(seconds):
        cands = groups[k]
        if len(cands) == 1:
            out[k] = cands[0]
            continue
        if neighbour == "adjacent":
            prev, nxt = known(k - 1), known(k + 1)
        else:
            prev = known(seconds[i - 1]) if i > 0 else None
            nxt = known(seconds[i + 1]) if i + 1 < len(seconds) else None
        distinct = list(dict.fromkeys(cands))
        kept: float | None
        if len(distinct) == 1:
            cls, kept = "identical", distinct[0]
        else:
            matching = [c for c in distinct if c == prev or c == nxt]
            if len(matching) == 1:
                cls, kept = "unambiguous", matching[0]
            else:
                cls, kept = "ambiguous", None
        fallback = (float(policy.default_mps)
                    if kept is None and unsettled == "default" else None)
        report.append({
            "second": int(_sod_to_hhmmss([k])[0]),
            "class": cls, "candidates": cands, "prev": prev, "next": nxt,
            "prev_missing": (k - 1) not in groups, "next_missing": (k + 1) not in groups,
            "kept": kept, "fallback": fallback,
            "reasons": ["unsettled-duplicate"] if kept is None else [],
        })
        if kept is not None:
            out[k] = kept
        elif fallback is not None:
            out[k] = fallback
    ks = sorted(out)
    return (_sod_to_hhmmss(np.array(ks, dtype=np.int64)),
            np.array([out[k] for k in ks], dtype=np.float64), report)


@dataclass
class ProbeReduction:
    """What :func:`reduce_probe_csv` produced: the series, the log lines it printed, the
    provenance attributes for the file, and -- under ``unsettled="refuse"`` -- the seconds that
    stopped it (non-empty means: write nothing)."""

    time: np.ndarray
    tas: np.ndarray
    lines: list
    provenance: dict
    refused: list
    substituted: list   # (HHMMSS, reason) per second that took the default


def reduce_probe_csv(csv_path, *, policy: TasPolicy | None = None,
                     second_rule: str = AUTHOR_SECOND_RULE,
                     neighbour: str = AUTHOR_NEIGHBOUR_RULE,
                     unsettled: str = AUTHOR_UNSETTLED_RULE) -> ProbeReduction:
    """The probe path end to end: ``<stem>.tas.csv`` -> whole seconds under the TAS rules,
    one log line per decision. Shared by ``make-tas-file --from-tas-csv`` and the run driver's
    TAS source chain (:mod:`arrayprobe.tools.tas_sources`), so the two cannot disagree."""
    policy = policy or TasPolicy()
    raw_t, raw_v = tas_from_csv(csv_path)
    time_hhmmss, tas, report = whole_second_series(
        raw_t, raw_v, second_rule=second_rule, neighbour=neighbour, policy=policy,
        unsettled=unsettled)
    lines = [f"TAS reduction: --second-rule {second_rule} --neighbour "
             f"{neighbour} --on-unsettled {unsettled}; rows above {policy.cutoff_mps:g} m/s, "
             f"at/below {TAS_NONPOSITIVE_MPS:g} m/s or non-finite are set aside, and a second "
             f"left without a usable row takes {policy.default_mps:g} m/s (never dropped)"]
    substituted: list[tuple[int, str]] = []
    oor = [r for r in report if r["class"] == "out-of-range"]
    for r in oor:
        if r["remaining"]:
            lines.append(f"TAS out-of-range row(s) set aside: {r['second']:06d} "
                         f"{len(r['candidates'])} row(s) {'/'.join(r['reasons'])} (e.g. "
                         f"{r['candidates'][0]}); other rows keep this second")
        else:
            substituted.append((r["second"], "/".join(r["reasons"])))
            lines.append(f"TAS substituted: {r['second']:06d} {r['candidates'][0]} -> "
                         f"{policy.default_mps:g} m/s ({'/'.join(r['reasons'])}, "
                         f"{len(r['candidates'])} row(s))")
    dup = [r for r in report if r["class"] != "out-of-range"]
    ambiguous = [r for r in dup if r["class"] == "ambiguous"]
    refused: list[dict] = []
    for r in ambiguous:
        if r["fallback"] is not None:
            substituted.append((r["second"], "unsettled-duplicate"))
            lines.append(f"TAS substituted: {r['second']:06d} candidates="
                         f"{r['candidates']} prev={r['prev']} next={r['next']} -> "
                         f"{policy.default_mps:g} m/s (unsettled-duplicate: the duplicate rule "
                         "picks no candidate)")
        else:
            refused.append(r)
            gap = [side for side, miss in (("previous", r["prev_missing"]),
                                           ("next", r["next_missing"])) if miss]
            lines.append(f"TAS duplicate UNRESOLVED: {r['second']:06d} "
                         f"candidates={r['candidates']} prev={r['prev']} next={r['next']} "
                         f"missing adjacent second: {', '.join(gap) or 'none'}")
    resolved = [r for r in dup if r["class"] != "ambiguous"]
    for r in resolved:
        lines.append(f"TAS duplicate resolved: {r['second']:06d} class={r['class']} "
                     f"kept={r['kept']} candidates={r['candidates']} prev={r['prev']} "
                     f"next={r['next']}")
    n_id = sum(r["class"] == "identical" for r in resolved)
    substituted.sort()
    lines.append(f"TAS duplicates resolved: {len(resolved)} second(s) ({n_id} "
                 f"identical, {len(resolved) - n_id} unambiguous); {len(substituted)} second(s) "
                 f"took the default {policy.default_mps:g} m/s; {raw_t.size} rows -> "
                 f"{time_hhmmss.size} whole seconds")
    provenance = {
        "tas_source": f"{csv_path} (measured)",
        "tas_second_rule": second_rule,
        "tas_neighbour_rule": neighbour,
        "tas_duplicate_rule": TAS_DUPLICATE_RULE,
        "tas_duplicates_resolved": np.int32(len(resolved)),
        "tas_duplicates_resolved_seconds": ",".join(f"{r['second']:06d}" for r in resolved),
        "tas_unsettled_rule": (
            f"{unsettled} (rule: a duplicated second the duplicate rule cannot settle "
            "takes tas_default_mps)"),
        **policy.attributes(),
        "tas_substituted_count": np.int32(len(substituted)),
        "tas_substituted_seconds": ",".join(f"{s:06d}:{why}" for s, why in substituted),
        "tas_out_of_range_rows": np.int32(sum(len(r["candidates"]) for r in oor)),
    }
    return ProbeReduction(time_hhmmss, tas, lines, provenance, refused, substituted)


def constant_tas(start_hhmmss: float, seconds: int,
                 tas_mps: float) -> tuple[np.ndarray, np.ndarray]:
    """A flat 1-Hz series. ``Time`` steps by 1 in HHMMSS, which is only valid inside one
    minute -- so the tool refuses a span that would run past :59 rather than writing a
    time axis that jumps backwards at the minute boundary."""
    if seconds < 1:
        raise ValueError("--seconds must be at least 1")
    ss = int(round(start_hhmmss)) % 100
    if ss + seconds > 60:
        raise ValueError(
            f"--start-hhmmss {start_hhmmss:.0f} plus --seconds {seconds} runs past "
            f":{ss + seconds:02d}, and HHMMSS does not carry across a minute by adding 1. "
            "Give a start earlier in the minute, a shorter span, or use --from-tas-csv")
    t = float(start_hhmmss) + np.arange(seconds, dtype=np.float64)
    return t, np.full(seconds, float(tas_mps), dtype=np.float64)


def build_parser() -> argparse.ArgumentParser:
    """The tool's parser -- also the list ``arrayprobe make-tas-file`` must mirror
    (``tests/test_make_tas_file.py`` compares the two option sets)."""
    parser = argparse.ArgumentParser(
        prog="arrayprobe make-tas-file",
        description="Write the aircraft TAS file stock imgProc_sm.m reads as varargin{1}: "
                    "a netCDF file with 1-D `Time` (HHMMSS) and `TAS` (m/s). Required by "
                    "the v3.5 engine and by any profile with time_in_seconds_from_tas.")
    parser.add_argument("path", help="output path, e.g. aircraft_160906.cdf")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-tas-csv", metavar="CSV",
                     help="the <stem>.tas.csv sidecar the decode already wrote; its first "
                          "two columns are timehhmmss and tas")
    src.add_argument("--from-merge", metavar="NC",
                     help="a campaign merge file, e.g. ORACLES mrg1_P3_<yyyymmdd>_R*.nc "
                          "(True_Air_Speed on Start_UTC; units read from the file)")
    src.add_argument("--from-aircraft", metavar="NC",
                     help="another registered aircraft file, e.g. ARM enaaafmergedF1.c1.*.nc "
                          "(true_airspeed on time + base_time) or a UIOPS TAS/Time file")
    src.add_argument("--chain", choices=("auto", "merge", "aircraft", "probe"),
                     help="resolve the source through the TAS source chain (merge -> aircraft -> "
                          "probe): needs --date, and --search and/or --probe-csv")
    src.add_argument("--constant-tas", type=float, metavar="MPS",
                     help="write a FLAT series at this speed instead of a measured one "
                          "(needs --start-hhmmss and --seconds)")
    parser.add_argument("--date", default=None, metavar="YYYYMMDD",
                        help="--chain: the flight date that fills each source's file pattern")
    parser.add_argument("--search", action="append", default=None, metavar="DIR",
                        help="--chain: a directory holding merge/aircraft files (repeatable)")
    parser.add_argument("--probe-csv", default=None, metavar="CSV",
                        help="the decode's <stem>.tas.csv: the chain's probe tier, and the "
                             "clock an aircraft source must share a second with")
    parser.add_argument("--start-hhmmss", type=float, default=None,
                        help="first sample's time as HHMMSS, e.g. 60638 for 06:06:38")
    parser.add_argument("--seconds", type=int, default=None,
                        help="number of 1-Hz samples for --constant-tas")
    parser.add_argument("--second-rule", choices=SECOND_RULES, default=AUTHOR_SECOND_RULE,
                        help="how a fractional HHMMSS becomes a whole second (--from-tas-csv); "
                             f"default {AUTHOR_SECOND_RULE!r}")
    parser.add_argument("--neighbour", choices=NEIGHBOUR_RULES, default=AUTHOR_NEIGHBOUR_RULE,
                        help="what the duplicate rule compares a duplicate against: 'adjacent' = "
                             "the second just before/after; 'nearest-present' = the nearest "
                             f"second present; default {AUTHOR_NEIGHBOUR_RULE!r}")
    parser.add_argument("--on-unsettled", choices=UNSETTLED_RULES, default=AUTHOR_UNSETTLED_RULE,
                        help="a duplicated second the duplicate rule cannot settle: 'default' "
                             "gives it --default-mps; 'refuse' writes nothing and "
                             f"lists them; default {AUTHOR_UNSETTLED_RULE!r}")
    parser.add_argument("--cutoff-mps", type=float, default=DEFAULT_CUTOFF_MPS,
                        help="a TAS above this is out of range and takes --default-mps "
                             f"(default {DEFAULT_CUTOFF_MPS:g})")
    parser.add_argument("--default-mps", type=float, default=DEFAULT_FALLBACK_MPS,
                        help="the value an out-of-range, non-positive or unsettled second "
                             f"takes (default {DEFAULT_FALLBACK_MPS:g}, imgProc_sm.m:365's)")
    parser.add_argument("--soda2-pth", default=None, metavar="CSV",
                        help="also write the same series as a SODA-2 op.pth ASCII file "
                             "(<seconds of day>,<tas> per line)")
    return parser


def main(argv=None) -> int:
    """``arrayprobe make-tas-file`` -- write the aircraft TAS file the pipeline requires.

    Measured sources (``--from-tas-csv``, ``--from-merge``, ``--from-aircraft``, ``--chain``)
    are converted under the TAS rules and a :class:`TasPolicy`; ``--constant-tas``
    fabricates a series and says so in the file's own provenance (``constant <v> m/s (NOT a
    measurement)``). It refuses to guess a flight's clock or duration. Returns an exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        policy = TasPolicy(args.cutoff_mps, args.default_mps)
    except ValueError as exc:
        parser.error(str(exc))

    # A flag the chosen source never reads is refused rather than ignored (cold-user walk,
    # 2026-09-26): `--from-tas-csv x --start-hhmmss 120000 --seconds 99` and `--from-tas-csv x
    # --date ... --search ...` each wrote the whole csv's series, exit 0, as if the extra
    # flags had trimmed or checked it.
    given = {"--start-hhmmss": args.start_hhmmss, "--seconds": args.seconds,
             "--date": args.date, "--search": args.search, "--probe-csv": args.probe_csv}
    unread: tuple[str, ...]
    if args.constant_tas is not None:
        unread = ("--date", "--search", "--probe-csv")
    elif args.from_tas_csv is not None:
        unread = tuple(given)
    else:
        unread = ("--start-hhmmss", "--seconds")
    ignored = [flag for flag in unread if given[flag] not in (None, [], ())]
    if ignored:
        parser.error(f"{', '.join(ignored)} {'is' if len(ignored) == 1 else 'are'} not read "
                     f"with the source given; --start-hhmmss/--seconds belong to "
                     f"--constant-tas, --date/--search/--probe-csv to --chain (and "
                     f"--from-merge/--from-aircraft)")

    provenance: dict = {}
    if args.from_tas_csv is not None:
        try:
            red = reduce_probe_csv(args.from_tas_csv, policy=policy,
                                   second_rule=args.second_rule, neighbour=args.neighbour,
                                   unsettled=args.on_unsettled)
        except ValueError as exc:
            # A file that is not a decode's <stem>.tas.csv (wrong file, a raw file, a header
            # row) fails inside load_tas_info's numeric parse, and a decode csv whose content
            # cannot be reduced (whole_second_series) fails too, so the wording names
            # neither cause; the exception text says which. Say which file and stop.
            print(f"arrayprobe make-tas-file: {args.from_tas_csv} could not be read as a "
                  f"<stem>.tas.csv ({exc}). No file written: {args.path}", file=sys.stderr)
            return 2
        for line in red.lines:
            print(line)
        if red.refused:
            print(f"a choice is needed: the rule picks no candidate here "
                  f"({len(red.refused)} second(s) under --second-rule {args.second_rule} "
                  f"--neighbour {args.neighbour}); --on-unsettled refuse was given. "
                  f"No file written: {args.path}")
            return 1
        time_hhmmss, tas, provenance = red.time, red.tas, red.provenance
        source = f"{args.from_tas_csv} (measured)"
    elif args.constant_tas is not None:
        if args.start_hhmmss is None or args.seconds is None:
            parser.error("--constant-tas needs --start-hhmmss and --seconds -- this tool "
                         "will not guess a flight's clock or duration")
        if not args.constant_tas > 0:
            # A zero or negative airspeed was written as given, and the pipeline's own policy
            # then set every second aside for the 170 m/s default -- a different series from
            # the one the file claims.
            parser.error(f"--constant-tas must be a positive speed in m/s, got "
                         f"{args.constant_tas}")
        if args.seconds < 1:
            parser.error(f"--seconds must be at least 1, got {args.seconds}")
        # The same clock bounds write_tas_file enforces (:290): HHMMSS, hours up to 47
        # because UIOOPS's midnight crossing is unwrapped (240000, 240001, ...), not wrapped.
        start = int(args.start_hhmmss)
        hh, mm, ss = start // 10000, (start // 100) % 100, start % 100
        if args.start_hhmmss < 0 or hh > 47 or mm >= 60 or ss >= 60:
            parser.error(f"--start-hhmmss must be a clock time HHMMSS (hours 0-47 after a "
                         f"midnight crossing, minutes and seconds 0-59), got "
                         f"{args.start_hhmmss:.0f}")
        try:
            time_hhmmss, tas = constant_tas(args.start_hhmmss, args.seconds, args.constant_tas)
        except ValueError as exc:
            parser.error(str(exc))
        source = f"constant {args.constant_tas} m/s (NOT a measurement)"
        provenance = {"tas_source": source}
    else:
        from arrayprobe.tools import tas_sources

        if args.chain is not None:
            if args.date is None:
                parser.error("--chain needs --date YYYYMMDD: the tool will not guess a "
                             "flight's date")
            mode, explicit = args.chain, None
        else:
            mode = "merge" if args.from_merge is not None else "aircraft"
            explicit = {mode: args.from_merge or args.from_aircraft}
        try:
            res = tas_sources.resolve_chain(
                mode, yyyymmdd=args.date, search_dirs=args.search or (),
                probe_csv=args.probe_csv, policy=policy, second_rule=args.second_rule,
                neighbour=args.neighbour, explicit=explicit)
        except ValueError as exc:
            print(f"make-tas-file: {exc}. No file written: {args.path}")
            return 1
        for line in res.lines:
            print(line)
        time_hhmmss, tas, provenance = res.time, res.tas, res.provenance
        source = f"{res.path} ({res.tier}:{res.source})"
    try:
        out = write_tas_file(args.path, time_hhmmss, tas, provenance=provenance)
    except ValueError as exc:
        print(f"arrayprobe make-tas-file: {exc}. No file written: {args.path}",
              file=sys.stderr)
        return 2
    print(f"wrote {out} -- {time_hhmmss.size} samples, "
          f"Time {time_hhmmss[0]:.0f}..{time_hhmmss[-1]:.0f} HHMMSS, "
          f"TAS {tas.min():.1f}..{tas.max():.1f} m/s, from {source}")
    if args.soda2_pth is not None:
        from arrayprobe.tools import tas_sources

        pth = tas_sources.write_soda2_pth_csv(args.soda2_pth, time_hhmmss, tas)
        print(f"wrote {pth} -- the same series as a SODA-2 op.pth ASCII file; name it as "
              "[soda2].pth")
    print(f"next: name it in your run config as [run].tas_file = \"{out}\", "
          "or pass --tas-file to the imgproc stage")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
