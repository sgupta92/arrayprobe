# SPDX-License-Identifier: BSD-3-Clause
"""Where a run's true airspeed comes from: an ordered, recorded chain.

The author's ruling, verbatim:

* *"yes for oracles, for other probes/campaigns - use probe airspeed"* -- use the ORACLES merge
  file's airspeed instead of the 2D-S probe's;
* *"never drop, use a cutoff and a default to fall to, provide user an option to select both in
  config so nothing is hard coded"*;
* *"07-06: ... - ARM's own"*;
* *"for oracles - yes, use the merged-file airspeed. for non-oracles, a merged file may not be
  available, so we look elsewhere for a reliable source, and if not, then the probe file itself
  with the decisions made earlier today. document this chain in the TAS page too and the
  metadata provides exactly what was followed. during processing, user can be given an
  opt-in/option in the config file."*

So the source is a **chain of tiers, tried in order** (:data:`TIERS`):

1. ``merge`` -- a campaign merge file (ORACLES ``mrg1_P3_<yyyymmdd>_R*.nc``, ``True_Air_Speed``);
2. ``aircraft`` -- another reliable aircraft source (ARM AAF ``enaaafmergedF1.c1.<date>.*.nc``,
   ``true_airspeed``);
3. ``probe`` -- the probe's own ``<stem>.tas.csv``, reduced under the duplicate-second rules
   (:func:`arrayprobe.tools.make_tas_file.reduce_probe_csv`).

``mode="auto"`` walks the tiers and uses the first that is available and passes its checks;
``"merge"``/``"aircraft"``/``"probe"`` pin one tier and **refuse** rather than fall through when
it is absent. Every tier tried is recorded -- used, skipped (not available) or failed (a check,
named) -- in the aircraft file's global attributes and in the run log.

**Only sources read off a real file are registered** (:data:`SOURCES`), each with the file it was
read from. A file matching no entry raises naming what it carries; nothing is guessed.

**Units are read, not assumed**: a registered source whose entry says ``units="attribute"``
must carry a ``units`` attribute naming one of :data:`UNIT_FACTORS`, or it is refused. The UIOOPS
``TAS``/``Time`` convention carries none and is m/s by definition (``imgproc.py:531-532`` reads
two bare arrays).

**The fidelity boundary.** Nothing here touches either engine. ``imgProc_sm.m:365``/``:763``'s
own 170 m/s fallback (``imgproc.py:118``) stays as it is; what this module configures is the
aircraft file the engine is *handed* and, when a run selects it, the TAS series ``sizeDist`` is
handed in place of the probe's.
"""

from __future__ import annotations

import glob as _glob
import json as _json
import os as _os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from arrayprobe.tools import make_tas_file as _mtf
from arrayprobe.tools.make_tas_file import TasPolicy, second_ranges

__all__ = ["AircraftSource", "SOURCES", "TIERS", "MODES", "UNIT_FACTORS", "AircraftSeries",
           "read_aircraft", "substitute", "ChainResult", "resolve_chain", "write_chain_file",
           "series_for_sizedist", "regular_grid_hhmmss", "regular_series_for_sizedist",
           "write_soda2_pth_csv"]

#: The tiers in the order ``auto`` tries them.
TIERS = ("merge", "aircraft", "probe")
#: ``[tas].source`` / ``--tas-source`` values: walk the chain, or pin one tier.
MODES = ("auto", *TIERS)

#: Factor to m/s per units string, for the units strings met on registered files. A units
#: string not here is refused, never guessed. 1 kt = 1852 m / 3600 s exactly (international
#: nautical mile).
UNIT_FACTORS = {"kts": 1852.0 / 3600.0, "m/s": 1.0}


@dataclass(frozen=True)
class AircraftSource:
    """One registered aircraft TAS source, read off a real file before being added."""

    name: str
    tier: str
    tas_var: str
    time_var: str
    time_axis: str          # "hhmmss" | "seconds-of-day" | "seconds-since-base_time"
    units: str              # "attribute" (read and checked) | "m/s" (the UIOOPS convention)
    pattern: str | None     # file name glob with {yyyymmdd}; None = only when named explicitly
    evidence: str


#: Order matters for identification only (the first whose two variables a file carries);
#: the chain's order is :data:`TIERS`.
SOURCES = (
    AircraftSource(
        "uiops-flightdata", "aircraft", "TAS", "Time", "hhmmss", "m/s", None,
        "UIOPS flightData_*.cdf -- the convention imgProc_sm.m expects; imgproc.py:531-532 "
        "reads these names; tests/data/demo_flight_v35_aircraft.cdf"),
    AircraftSource(
        "oracles-p3-merge", "merge", "True_Air_Speed", "Start_UTC", "seconds-of-day",
        "attribute", "mrg1_P3_{yyyymmdd}_R*.nc",
        "read 2026-09-23 off mrg1_P3_20160906_R36.nc, mrg1_P3_20170812_R28.nc and "
        "mrg1_P3_20181002_R25.nc ($ARRAYPROBE_ORACLES_DATA): Start_UTC f8 units 'seconds' "
        "(of day), whole, 1 Hz; True_Air_Speed f8 units 'kts', missing_value -9999/-7777/-8888, "
        "fill 9.969e36 (46-74 samples per file); source Hskping_P3_<date>_R*.ict"),
    AircraftSource(
        "arm-aaf-merged", "aircraft", "true_airspeed", "time", "seconds-since-base_time",
        "attribute", "enaaafmergedF1.c1.{yyyymmdd}.*.nc",
        "ARM AAF merged, read 2026-09-23 off enaaafmergedF1.c1.20170706.082313.nc: "
        "true_airspeed f4 units 'm/s' (source enaaafnaviwgF1.c1:true_airspeed), "
        "missing_value -9999; time f8 'seconds since 2017-07-06 00:00:00', base_time "
        "1499299200 (that midnight), whole, 1 Hz"),
)


@dataclass
class AircraftSeries:
    """An aircraft file read and converted: HHMMSS whole seconds, TAS in m/s (not yet
    policy-checked)."""

    time_hhmmss: np.ndarray
    tas_mps: np.ndarray
    source: AircraftSource
    path: str
    units: str
    factor: float
    notes: list = field(default_factory=list)


def _variables(path) -> set:
    import netCDF4
    with netCDF4.Dataset(str(path)) as ds:
        return set(ds.variables)


def _units(path, var) -> str | None:
    import netCDF4
    with netCDF4.Dataset(str(path)) as ds:
        v = ds.variables[var]
        return str(v.getncattr("units")) if "units" in v.ncattrs() else None


def _sod_to_hhmmss(sod) -> np.ndarray:
    return _mtf._sod_to_hhmmss(sod)


def identify(path) -> AircraftSource:
    """The registered source whose two variables ``path`` carries. Raises ``KeyError`` naming
    what it tried and what the file carries -- never a guess."""
    present = _variables(path)
    for src in SOURCES:
        if src.tas_var in present and src.time_var in present:
            return src
    tried = ", ".join(f"{s.tas_var}/{s.time_var}" for s in SOURCES)
    raise KeyError(
        f"{path}: no true-airspeed variable found. Tried {tried}. It carries: "
        f"{sorted(present)}. Add the source to arrayprobe.tools.tas_sources.SOURCES once you "
        "have read it out of a real file -- do not guess a name.")


def read_aircraft(path, source: AircraftSource | None = None) -> AircraftSeries:
    """Read ``path`` as ``source`` (identified by its variables when not given), convert its
    time axis to UTC HHMMSS and its TAS to m/s by the units attribute. Read through
    ``ncio.ncread`` -- the call the engine makes -- so masking and scaling apply the same way."""
    from arrayprobe import ncio

    src = source or identify(path)
    tas = np.asarray(ncio.ncread(str(path), src.tas_var), dtype=np.float64).ravel()
    # A masked (fill-value) time is NaN here, not its stored fill: np.asarray on ncread's masked
    # array would hand back the fill itself (ARM's -9999), which the conversions below turn into
    # a real-looking clock second (-9999 s of day is 21:13:21).
    t = np.ma.filled(np.ma.asarray(ncio.ncread(str(path), src.time_var), dtype=np.float64),
                     np.nan).ravel()
    bad_time = int(np.sum(~np.isfinite(t)))
    if bad_time:
        raise ValueError(f"{path}: '{src.time_var}' has {bad_time} masked or non-finite "
                         "value(s); a time that is not a number cannot key a second")
    notes: list[str] = []
    if src.units == "attribute":
        units = _units(path, src.tas_var)
        if units is None:
            raise ValueError(f"{path}: {src.tas_var} carries no units attribute; source "
                             f"{src.name} is registered as reading its units from the file, so "
                             "a speed of unknown units is refused rather than assumed")
        if units not in UNIT_FACTORS:
            raise ValueError(f"{path}: {src.tas_var} units {units!r} are not one of "
                             f"{sorted(UNIT_FACTORS)}; refused rather than guessed")
    else:
        units = src.units
    factor = UNIT_FACTORS[units]
    if factor != 1.0:
        tas = tas * factor
        notes.append(f"{src.tas_var} converted from {units!r} to m/s (x {factor!r})")
    if src.time_axis == "seconds-of-day":
        if np.any(t != np.floor(t)):
            raise ValueError(f"{path}: {src.time_var} is not whole seconds; the exact-match "
                             "lookup at imgProc_sm.m:727 needs whole seconds")
        # Unwrapped, matching UIOOPS's own midnight convention (2026-09-28): a value at or
        # past 86400 s is the next day's clock continuing as 24xxxx HHMMSS, not folded back to
        # 000000 -- the same convention sizeDist.m's +240000 rollover keeps for particle times.
        t = _sod_to_hhmmss(t.astype(np.int64))
        notes.append(f"{src.time_var} converted from seconds of day to UTC HHMMSS (unwrapped "
                     "past midnight)")
    elif src.time_axis == "seconds-since-base_time":
        if "base_time" not in _variables(path):
            raise ValueError(
                f"{path}: '{src.time_var}' is seconds since base_time (ARM convention) but the "
                "file has no base_time variable, so the time of day cannot be established; "
                "refused rather than read as HHMMSS (it would match no record at "
                "imgProc_sm.m:727)")
        base = float(np.asarray(ncio.ncread(str(path), "base_time"), dtype=float).ravel()[0])
        # Unwrapped past midnight, same convention as the seconds-of-day branch above (B5):
        # seconds since base_time's own reference day, not folded back to 000000 at 86400 s.
        day0 = np.floor(base / 86400.0) * 86400.0
        sod = np.round(base + t - day0).astype(np.int64)
        t = _sod_to_hhmmss(sod)
        notes.append(f"'{src.time_var}' converted from seconds since base_time to UTC HHMMSS "
                     "(unwrapped past midnight)")
    return AircraftSeries(t, tas, src, str(path), units, factor, notes)


def substitute(time_hhmmss, tas, policy: TasPolicy):
    """Every out-of-range TAS -> ``policy.default_mps``. Returns ``(tas, subs)``, ``subs`` one
    ``(HHMMSS, original, reason)`` per substituted sample. Nothing is dropped."""
    t = np.asarray(time_hhmmss, dtype=np.float64).ravel()
    out = np.asarray(tas, dtype=np.float64).ravel().copy()
    subs = []
    for i, x in enumerate(out.tolist()):
        why = policy.reason(x)
        if why is not None:
            subs.append((int(t[i]) if np.isfinite(t[i]) else -1, x, why))
            out[i] = policy.default_mps
    return out, subs


@dataclass
class ChainResult:
    """What the chain decided for one flight file. ``tier``/``source`` name what was used;
    ``steps`` is every tier tried, in order, as ``(tier, source, outcome, detail)`` with outcome
    ``used`` / ``skipped`` / ``failed``."""

    mode: str
    tier: str
    source: str
    path: str
    time: np.ndarray
    tas: np.ndarray
    policy: TasPolicy
    steps: list
    substituted: list          # (HHMMSS, reason) per second that took the default
    lines: list
    provenance: dict

    def stamp(self) -> str:
        """The ``.call`` fragment (only ever added when a run opts into the chain)."""
        return f"tas_chain={self.tier}:{self.source} tas_policy=({self.policy.token()})"


def _steps_text(steps) -> str:
    return "; ".join(f"{tier}/{name}: {outcome}" + (f" ({detail})" if detail else "")
                     for tier, name, outcome, detail in steps)


def _probe_seconds(probe_csv) -> np.ndarray | None:
    if probe_csv is None or not Path(probe_csv).is_file():
        return None
    t, _ = _mtf.tas_from_csv(probe_csv)
    sod = _mtf._hhmmss_to_sod(np.asarray(t, dtype=float))
    return np.unique(_sod_to_hhmmss(np.floor(sod + 0.5).astype(np.int64)))


def _from_aircraft(series: AircraftSeries, policy: TasPolicy, probe_secs):
    """Check, substitute, and extend over the probe's seconds. Returns
    ``(time, tas, substituted, lines, extra_provenance)``; raises ValueError on a failed check."""
    t, v = series.time_hhmmss, series.tas_mps
    v, subs = substitute(t, v, policy)
    # The same fail-closed check the builder applies: whole, unique, clock-valid HHMMSS.
    t, v = _mtf.check_tas_series(t, v)
    lines = [f"TAS substituted: {s:06d} {x!r} -> {policy.default_mps:g} m/s ({why})"
             for s, x, why in subs]
    substituted = [(s, why) for s, x, why in subs]
    extra: dict = {}
    if probe_secs is not None:
        have = set(t.astype(np.int64).tolist())
        overlap = [s for s in probe_secs.astype(np.int64).tolist() if s in have]
        if not overlap:
            raise ValueError(
                f"shares no second with the probe's own clock ({probe_secs.size} probe seconds, "
                f"{int(probe_secs[0]):06d}..{int(probe_secs[-1]):06d}; source "
                f"{int(t[0]):06d}..{int(t[-1]):06d}) -- it cannot be this flight's airspeed")
        gaps = [s for s in probe_secs.astype(np.int64).tolist() if s not in have]
        extra["tas_probe_seconds_covered"] = np.int32(len(overlap))
        extra["tas_probe_seconds_total"] = np.int32(probe_secs.size)
        if gaps:
            # Never dropped: a probe second the aircraft source does not cover takes the
            # default, in the file, so the configured default -- not only the engine's own
            # fallback -- is what applies there. Logged as ranges; every second is recoverable.
            t = np.concatenate([t, np.asarray(gaps, dtype=np.float64)])
            v = np.concatenate([v, np.full(len(gaps), policy.default_mps)])
            order = np.argsort(_mtf._hhmmss_to_sod(t), kind="stable")
            t, v = t[order], v[order]
            substituted += [(s, "no-aircraft-sample") for s in gaps]
            lines.append(f"TAS substituted: {len(gaps)} probe second(s) with no aircraft "
                         f"sample -> {policy.default_mps:g} m/s: {second_ranges(gaps)}")
    return t, v, sorted(substituted), lines, extra


def _candidates(src: AircraftSource, yyyymmdd: str, search_dirs) -> list[Path]:
    assert src.pattern is not None, "callers skip a source registered with no file pattern"
    found: list[Path] = []
    for d in search_dirs:
        pattern = str(Path(d).expanduser() / src.pattern.format(yyyymmdd=yyyymmdd))
        found += [Path(p) for p in sorted(_glob.glob(pattern))]
    return found


def resolve_chain(mode: str, *, yyyymmdd: str | None, search_dirs=(), probe_csv=None,
                  policy: TasPolicy | None = None,
                  second_rule: str = _mtf.AUTHOR_SECOND_RULE,
                  neighbour: str = _mtf.AUTHOR_NEIGHBOUR_RULE,
                  explicit: dict | None = None) -> ChainResult:
    """Walk the chain (``mode="auto"``) or pin one tier, and return what was used and why.

    ``yyyymmdd`` names the flight's date (a raw stem ``base170812080701`` is ``20170812``) and
    fills each registered source's file-name pattern in ``search_dirs``; ``explicit`` maps a tier
    to a file named outright (``make-tas-file --from-merge``/``--from-aircraft``), which is then
    that tier's only candidate. ``probe_csv`` is the decode's ``<stem>.tas.csv``: the ``probe``
    tier's input, and for the other tiers the clock they must share at least one second with.

    Raises ``ValueError`` -- listing every step -- when no tier is usable, or when a pinned tier
    is absent or fails: a pinned source never falls through silently.
    """
    if mode not in MODES:
        raise ValueError(f"TAS source must be one of {MODES}, got {mode!r}")
    policy = policy or TasPolicy()
    explicit = explicit or {}
    tiers = TIERS if mode == "auto" else (mode,)
    probe_secs = _probe_seconds(probe_csv)
    steps: list[tuple[str, str, str, str]] = []
    for tier in tiers:
        if tier == "probe":
            if probe_csv is None or not Path(probe_csv).is_file():
                steps.append(("probe", "probe-tas-csv", "skipped",
                              f"not available: {probe_csv or 'no <stem>.tas.csv'}"))
                continue
            red = _mtf.reduce_probe_csv(probe_csv, policy=policy, second_rule=second_rule,
                                        neighbour=neighbour, unsettled="default")
            try:
                t, v = _mtf.check_tas_series(red.time, red.tas)
            except ValueError as exc:
                steps.append(("probe", "probe-tas-csv", "failed", str(exc)))
                continue
            steps.append(("probe", "probe-tas-csv", "used", str(probe_csv)))
            return _result(mode, "probe", "probe-tas-csv", str(probe_csv), t, v, policy, steps,
                           list(red.substituted), red.lines, red.provenance)
        sources = [s for s in SOURCES if s.tier == tier]
        for src in sources:
            if tier in explicit:
                cands = [Path(explicit[tier])]
            elif src.pattern is None:
                continue          # only reachable when named outright
            elif yyyymmdd is None:
                steps.append((tier, src.name, "skipped", "not available: no flight date"))
                continue
            elif not search_dirs:
                steps.append((tier, src.name, "skipped",
                              "not available: no search directory configured ([tas].search / "
                              "--tas-search)"))
                continue
            else:
                cands = _candidates(src, yyyymmdd, search_dirs)
            if not cands:
                # An explicit file is always one candidate, so an empty list came from
                # _candidates, which only runs for a source with a file pattern.
                assert src.pattern is not None
                steps.append((tier, src.name, "skipped",
                              f"not available: no {src.pattern.format(yyyymmdd=yyyymmdd)} in "
                              f"{[str(d) for d in search_dirs]}"))
                continue
            if len(cands) > 1:
                steps.append((tier, src.name, "failed",
                              f"{len(cands)} candidate files ({', '.join(c.name for c in cands)}); "
                              "name one outright rather than have one picked"))
                continue
            path = cands[0]
            try:
                found = identify(path)
                if tier in explicit and found.tier != tier:
                    raise ValueError(f"{path.name} reads as {found.name}, a {found.tier} source, "
                                     f"not a {tier} one")
                series = read_aircraft(path, found)
                t, v, subs, lines, extra = _from_aircraft(series, policy, probe_secs)
            except (KeyError, ValueError, OSError) as exc:
                steps.append((tier, src.name if tier not in explicit else path.name, "failed",
                              str(exc)))
                if tier in explicit:
                    break
                continue
            steps.append((tier, found.name, "used", str(path)))
            prov = {
                "tas_source": f"{path} ({found.name}, measured)",
                "tas_source_evidence": found.evidence,
                "tas_units_read": series.units,
                "tas_unit_factor_to_mps": float(series.factor),
                "tas_conversions": "; ".join(series.notes) or "none",
                **policy.attributes(),
                "tas_substituted_count": np.int32(len(subs)),
                # reason=HHMMSS ranges, one group per reason: every second is recoverable.
                "tas_substituted_seconds": "; ".join(
                    f"{why}={second_ranges([s for s, w in subs if w == why])}"
                    for why in dict.fromkeys(w for _, w in subs)),
                **extra,
            }
            return _result(mode, tier, found.name, str(path), t, v, policy, steps, subs,
                           list(series.notes) + lines, prov)
        if tier in explicit:
            break
    raise ValueError(f"TAS source chain ({mode}) found nothing usable: {_steps_text(steps)}")


def _result(mode, tier, source, path, t, v, policy, steps, subs, lines, prov) -> ChainResult:
    prov = dict(prov)
    prov["tas_chain_mode"] = mode
    prov["tas_chain_used"] = f"{tier}:{source}"
    prov["tas_chain_steps"] = _steps_text(steps)
    prov["tas_chain_note"] = (
        "Rule: tiers tried in order merge -> aircraft -> probe; "
        "the first available source that passes its checks is used; a pinned tier never falls "
        "through. See docs/developer/TAS.md, 'The TAS source chain'")
    head = [f"TAS chain ({mode}): {tier}/{source} used -- {path}"]
    head += [f"TAS chain step: {t_}/{n}: {o}" + (f" ({d})" if d else "")
             for t_, n, o, d in steps]
    return ChainResult(mode, tier, source, path, t, v, policy, steps, subs, head + lines, prov)


def write_chain_file(path, result: ChainResult) -> Path:
    """The aircraft file for the framing stage, in UIOOPS's ``TAS``/``Time`` convention, carrying
    the whole decision record in its global attributes."""
    return _mtf.write_tas_file(path, result.time, result.tas, provenance=result.provenance)


def series_for_sizedist(probe_time_hhmmss, aircraft_time, aircraft_tas, policy: TasPolicy):
    """The TAS array the size-distribution stage (``sizeDist``) gets when a run picks aircraft TAS.

    **The time axis stays the probe's own** (the ``<stem>.tas.csv`` times, floored exactly as
    the probe path floors them), because ``sizeDist``'s output time base *is* its TAS series'
    time axis (the earlier translation's ``sizeDist`` port, at its output time base): swapping the
    axis too would move or remove seconds of the
    product. Only the values are replaced -- by the aircraft TAS at the same whole second, and
    by ``policy.default_mps`` where the aircraft series has none (never dropped).
    Returns ``(time, tas, missing_seconds)``.
    """
    t = np.floor(np.asarray(probe_time_hhmmss, dtype=np.float64).ravel())
    lookup = dict(zip(np.asarray(aircraft_time, dtype=np.int64).tolist(),
                      np.asarray(aircraft_tas, dtype=np.float64).tolist(), strict=True))
    tas = np.empty_like(t)
    missing: list[int] = []
    for i, s in enumerate(t.astype(np.int64).tolist()):
        val = lookup.get(s)
        if val is None or policy.reason(val) is not None:
            tas[i] = policy.default_mps
            missing.append(s)
        else:
            tas[i] = val
    return t, tas, missing


def regular_grid_hhmmss(probe_time_hhmmss) -> np.ndarray:
    """A one-second HHMMSS grid from the probe axis's first second to its last, every second once.

    The probe's own ``<stem>.tas.csv`` axis repeats a second when two housekeeping packets
    fall in it and skips one when none does. ``sizeDist``'s block walk
    (v3.5 ``sizeDist.m:913-927``; v3.1.4 ``:745-754``) files no particle of a skipped second
    and none of a repeated one -- measured
    under Octave on the unmodified v3.5 source.
    This grid has
    neither. Midnight is unwrapped before the span is taken and wrapped back after, so a
    grid crossing it reads ``235959, 0, 1`` as the probe's own does. Returned as float64,
    the dtype the probe axis has.
    """
    t = np.floor(np.asarray(probe_time_hhmmss, dtype=np.float64).ravel()).astype(np.int64)
    if t.size == 0:
        return np.zeros(0, dtype=np.float64)
    sec = t // 10000 * 3600 + t // 100 % 100 * 60 + t % 100
    # A step back of more than half a day is a midnight crossing, not jitter.
    sec = sec + 86400 * np.concatenate([[0], np.cumsum(np.diff(sec) < -43200)])
    grid = np.arange(sec.min(), sec.max() + 1, dtype=np.int64) % 86400
    return (grid // 3600 * 10000 + grid // 60 % 60 * 100 + grid % 60).astype(np.float64)


def regular_series_for_sizedist(probe_time_hhmmss, aircraft_time, aircraft_tas,
                                policy: TasPolicy):
    """:func:`series_for_sizedist` on :func:`regular_grid_hhmmss`'s grid instead of the probe's
    own axis: the same aircraft-value lookup and the same policy default for a second the
    aircraft series lacks, over a time vector with every second of the probe's span once.

    The opt-in behind ``run_flight.py --tas-grid regular``. It is how UIOOPS's own worked example
    calls ``sizeDist`` with aircraft airspeed
    (``UIOPS-v3.5/joefinlon-UIOPS-039be82/minimal_working_example/run_sizeDist_Munich.m:25-26``
    and ``:40`` hand it the flight file's ``Time`` and ``TAS`` together), with the span kept to the
    probe's so the product covers the seconds it covered before. Returns
    ``(time, tas, missing_seconds)``.
    """
    return series_for_sizedist(regular_grid_hhmmss(probe_time_hhmmss), aircraft_time,
                               aircraft_tas, policy)


#: The sidecar format's name, so a reader can refuse a record it does not understand.
QC_CONVENTION = "arrayprobe-tasqc-1"


def _reasons_text(reasons) -> str:
    """``"above-cutoff:n;...;unsettled-duplicate:k"`` -- every reason the chain substitutes
    for, always all five, so a zero is stated rather than implied and the reasons sum to
    ``tas_substituted_count``. A slash-joined probe-tier reason (``"above-cutoff/non-finite"``)
    counts under its first component."""
    reasons = [r.split("/", 1)[0] for r in reasons]
    return ";".join(f"{r}:{reasons.count(r)}" for r in _REASONS)


def _uncertainty_text(n_default: int, total: int, policy: TasPolicy) -> str:
    """``tas_uncertainty``: one sentence a reader of the attributes needs, for a single product
    (:func:`qc_record`) and for a combine of several (:func:`merge_qc_records`) alike."""
    if n_default == 0:
        return f"none: every second has a measured TAS that passed policy {policy.token()}"
    frac = n_default / total if total else 0.0
    return (f"{n_default} of {total} seconds ({100.0 * frac:.2f} %) sized with default TAS "
            f"{policy.default_mps:g} m/s, not a measured value; sample volume scales with "
            f"TAS, so concentration in those seconds is in error by the unknown factor "
            f"TAS_true/{policy.default_mps:g}. Ranges: arrayprobe_tas_*_ranges.")


def qc_record(chain: ChainResult | None, policy: TasPolicy, probe_time_hhmmss, missing,
              legacy_subs=None) -> dict:
    """The TAS data-quality facts for one product: which seconds of the probe's axis
    were sized with a default TAS rather than a measured one, and why.

    ``probe_time_hhmmss`` is the probe's own time axis **before** flooring (``<stem>.tas.csv``);
    ``missing`` is :func:`series_for_sizedist`'s third return (``[]`` on a path that never
    called it); ``legacy_subs`` is :func:`substitute`'s ``subs`` for an aircraft file handed
    directly (``--tas-file``, no chain; ``None`` when there is no aircraft file). Keys become
    attribute names under ``arrayprobe_``.

    ``tas_floor_round_residual_*`` counts the absent seconds whose sample ``round``s onto a
    second the chain does have -- seconds lost only because this axis is floored
    (13 on 0812). Reported, not fixed: fixing it changes sd values.
    """
    t_raw = np.asarray(probe_time_hhmmss, dtype=np.float64).ravel()
    axis = np.floor(t_raw).astype(np.int64).tolist()
    in_axis = set(axis)
    chain_secs = (set(np.asarray(chain.time, dtype=np.int64).tolist())
                  if chain is not None else set())
    subs = [(int(s), why) for s, why in (chain.substituted if chain is not None else ())]
    subs += [(int(s), why) for s, _orig, why in (legacy_subs or ())]
    subs = [(s, why) for s, why in subs if s in in_axis]
    sub_secs = {s for s, _ in subs}
    missing = [int(s) for s in missing]
    missing_set = set(missing)
    absent = sorted(s for s in missing_set if s not in chain_secs)
    absent_set = set(absent)
    residual = sorted({s for s, x in zip(axis, t_raw.tolist(), strict=True)
                       if s in absent_set and int(np.round(x)) in chain_secs})
    total = len(axis)
    n_sub = sum(1 for s in axis if s in sub_secs and s not in missing_set)
    n_default = n_sub + len(missing)
    frac = n_default / total if total else 0.0
    if chain is not None:
        used = f"{chain.tier}:{chain.source}"
    else:
        used = "tas-file" if legacy_subs is not None else "none"
    text = _uncertainty_text(n_default, total, policy)
    return {
        "tas_qc_convention": QC_CONVENTION,
        "tas_chain_used": used,
        "tas_policy": policy.token(),
        "tas_seconds_total": total,
        "tas_substituted_count": len(sub_secs),
        "tas_substituted_ranges": second_ranges(sub_secs),
        "tas_substituted_reasons": _reasons_text(why for _, why in subs),
        "tas_missing_count": len(missing),
        "tas_missing_ranges": second_ranges(missing),
        "tas_missing_absent_count": len(absent),
        "tas_missing_absent_ranges": second_ranges(absent),
        "tas_floor_round_residual_count": len(residual),
        "tas_floor_round_residual_ranges": second_ranges(residual),
        "tas_defaulted_fraction": float(frac),
        "tas_uncertainty": text,
    }


_REASONS = ("above-cutoff", "non-finite", "non-positive", "no-aircraft-sample",
            "unsettled-duplicate")


def merge_qc_records(parts) -> dict:
    """One record for a combined product from its constituents' records.

    ``parts`` is ``[(sd_filename, record), ...]`` in stitch order. Counts are summed, ranges
    concatenated in that order, reasons summed per reason, and the fraction and uncertainty
    text recomputed over the summed axis; ``tas_qc_parts`` names every part. The parts must
    share one policy -- :func:`check_combine_provenance` has already refused inputs whose
    stamps disagree, so a mismatch here is a bug, raised rather than averaged over.
    """
    parts = list(parts)
    if not parts:
        raise ValueError("merge_qc_records: no parts")
    recs = [rec for _, rec in parts]
    policies = {rec["tas_policy"] for rec in recs}
    if len(policies) != 1:
        raise ValueError(f"merge_qc_records: parts disagree on tas_policy: {sorted(policies)}")
    policy = TasPolicy.parse(policies.pop())
    total = sum(int(rec["tas_seconds_total"]) for rec in recs)
    n_default = sum(int(round(float(rec["tas_defaulted_fraction"])
                              * int(rec["tas_seconds_total"]))) for rec in recs)
    out = {
        "tas_qc_convention": QC_CONVENTION,
        "tas_chain_used": ",".join(dict.fromkeys(rec["tas_chain_used"] for rec in recs)),
        "tas_policy": policy.token(),
        "tas_seconds_total": total,
        "tas_defaulted_fraction": float(n_default / total if total else 0.0),
        "tas_uncertainty": _uncertainty_text(n_default, total, policy),
        "tas_qc_parts": ",".join(name for name, _ in parts),
    }
    for stem in ("tas_substituted", "tas_missing", "tas_missing_absent",
                 "tas_floor_round_residual"):
        out[f"{stem}_count"] = sum(int(rec[f"{stem}_count"]) for rec in recs)
        out[f"{stem}_ranges"] = ",".join(r for r in (rec[f"{stem}_ranges"] for rec in recs) if r)
    counts = dict.fromkeys(_REASONS, 0)
    for rec in recs:
        for item in rec["tas_substituted_reasons"].split(";"):
            reason, n = item.rsplit(":", 1)
            counts[reason] += int(n)
    out["tas_substituted_reasons"] = ";".join(f"{r}:{counts[r]}" for r in _REASONS)
    return out

def qc_sidecar_path(product) -> Path:
    """``<product>.tasqc.json``, beside the product; staleness checks never read it."""
    product = Path(product)
    return product.with_name(product.name + ".tasqc.json")


def write_qc_sidecar(product, rec: dict) -> Path:
    """Write ``rec`` as sorted-key JSON beside ``product``, partial-then-rename like the
    ``.decode`` and ``.call`` sidecars, so a kill never leaves a half-written record."""
    target = qc_sidecar_path(product)
    partial = target.with_name(target.name + ".partial")
    partial.write_text(_json.dumps(rec, sort_keys=True, indent=1) + "\n",
                       encoding="utf-8")
    _os.replace(partial, target)
    return target


#: Per-second TAS quality flag values, for the CF and ARM exports.
QC_FLAG_MEASURED, QC_FLAG_SUBSTITUTED, QC_FLAG_DEFAULTED = 0, 1, 2


def expand_ranges(ranges: str) -> set[int]:
    """The inverse of :func:`second_ranges`: ``"124838-124840,130000"`` -> the HHMMSS seconds,
    stepping in seconds of day so a range across a minute or hour boundary is exact."""
    out: set[int] = set()
    for part in filter(None, (p.strip() for p in (ranges or "").split(","))):
        lo, _, hi = part.partition("-")
        a = int(_mtf._hhmmss_to_sod([int(lo)])[0])
        b = int(_mtf._hhmmss_to_sod([int(hi or lo)])[0])
        for sod in range(a, b + 1):
            out.add((sod // 3600) * 10000 + (sod % 3600 // 60) * 100 + sod % 60)
    return out


def qc_flags(rec: dict, time_hhmmss) -> np.ndarray:
    """One flag per ``time_hhmmss`` second: 2 where the record says the second took the default
    (absent from every tier, or lost to the floor/round residual), else 1 where a tier's value
    was substituted by policy, else 0. Seconds are matched as whole HHMMSS."""
    t = np.rint(np.asarray(time_hhmmss, dtype=np.float64).ravel()).astype(np.int64)
    subst = expand_ranges(rec.get("tas_substituted_ranges", ""))
    dflt = (expand_ranges(rec.get("tas_missing_ranges", ""))
            | expand_ranges(rec.get("tas_floor_round_residual_ranges", "")))
    flags = np.full(t.shape, QC_FLAG_MEASURED, dtype=np.int8)
    flags[np.isin(t, sorted(subst))] = QC_FLAG_SUBSTITUTED
    flags[np.isin(t, sorted(dflt))] = QC_FLAG_DEFAULTED
    return flags


def read_qc_sidecar(product) -> dict | None:
    """The record :func:`write_qc_sidecar` wrote beside ``product``, or ``None`` when there is
    none. A record of another convention raises rather than being read as this one."""
    target = qc_sidecar_path(product)
    if not target.is_file():
        return None
    rec = _json.loads(target.read_text(encoding="utf-8"))
    if rec.get("tas_qc_convention") != QC_CONVENTION:
        raise ValueError(f"{target.name}: convention {rec.get('tas_qc_convention')!r}, "
                         f"expected {QC_CONVENTION!r}")
    return rec

def write_soda2_pth_csv(path, time_hhmmss, tas_mps) -> Path:
    """The same series as a SODA-2 ``op.pth`` ASCII file (``soda2_process_2d.pro:147-162``,
    ported as ``arrayprobe_soda2.pth_readers.read_pth_ascii``): one ``<seconds of day>,<tas>``
    line per sample, since SODA-2's ``op.starttime`` is seconds from midnight. SODA-2 fills each
    accepted row forward and accepts ``0 < tas < 500`` (``:156``), so a series that has been
    through :class:`TasPolicy` passes whole when the cutoff is below 500 m/s."""
    t = np.asarray(time_hhmmss, dtype=np.float64).ravel()
    v = np.asarray(tas_mps, dtype=np.float64).ravel()
    sod = _mtf._hhmmss_to_sod(t)
    order = np.argsort(sod, kind="stable")
    path = Path(path)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        for s, x in zip(sod[order].tolist(), v[order].tolist(), strict=True):
            fh.write(f"{int(round(s))},{x!r}\n")
    return path
