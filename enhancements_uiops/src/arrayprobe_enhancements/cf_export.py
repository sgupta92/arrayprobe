# SPDX-License-Identifier: BSD-3-Clause
"""An opt-in CF-1.10 copy of a port ``sd`` (``sizeDist``) output file.

**The question this answers**:
the
port's UIOOPS-shaped files carry UIOOPS-native ``units`` strings, no
``Conventions``, no ``standard_name`` and an ``HHMMSS`` time axis, so a CF
reader cannot label the axes or trust the units. This module writes a
**sibling** file that a CF reader can: a CF time coordinate, a size-bin
coordinate with ``bounds``, an area-ratio-bin coordinate with ``bounds``, and
every physical variable in canonical SI udunits units with the rescale factor
recorded on the variable (``arrayprobe_cf_scale``), so the export is invertible.
The port file is only ever opened read-only; its bytes are never touched
(the UIOOPS-shaped file is part of the output contract).

**Scope: ``sd`` only.** ``proc`` (``imgProc_sm``) files carry no ``units``
attribute on any of their 41 variables (R4 memo B.1), so each unit would have
to be read from ``imgProc_sm.m`` variable by variable -- a separate job, not
done here and not guessed. A variable this table does not map is refused by
name, never copied with an invented unit.

**Units are keyed by variable, not by the unit string.** The string is the
thing under suspicion: four of sizeDist's strings do not describe the value
they label, established by inspection and recorded per row below:

- ``vt`` is labelled ``g/cm4`` (``sizeDist.m:1954``, both releases). It is the
  **sum of per-particle terminal velocities**, normalised like ``conc_minR``
  (``:990`` per-particle ``single_vt``, ``:1407`` bin sum, ``:1426`` per-cm of
  size, ``:1764`` per cm3): unit ``m s-1 cm-4``. ``single_vt.m`` is SI
  (diameter in m, mass in kg, ``:37`` ``vt = nu/diameter*Re``); run unmodified
  under Octave 11.3 it returned 0.228 for a 100 um ice sphere against a Stokes
  SI reference of 0.288 m s-1 -- metres per second, not centimetres. Measured
  on every Octave-written sizeDist golden in ``tests/data``:
  ``vt/conc_minR == Prec_rate/mass`` to <= 5.3e-16 relative in every
  single-particle bin, 0.016-0.19 m s-1. The long name says "mass-weighted";
  the value is a number sum (the mass-weighted one is ``Prec_rate/mass``).
- ``Prec_rate`` is labelled ``mm/hr`` (``:1958``). It is ``sum(m_i v_i)``
  (``:992`` ``particle_pr = particle_mass.*particle_vt``, grams times m s-1)
  normalised like ``mass``: unit ``g m s-1 cm-4``, a size-resolved mass-flux
  density -- **not** a liquid-equivalent precipitation rate, so CF's
  ``lwe_precipitation_rate`` does not apply and no standard name is written.
- ``habitmsd`` is labelled ``g/cm-4`` (``:1962``), which udunits parses as
  g cm4. It accumulates ``good_iwc`` (``:1358-1376``) with ``mass``'s
  normalisation; measured ``sum over Habit of habitmsd == mass`` (max abs
  difference 4e-23) on the same goldens: unit ``g cm-4``.
- ``re`` is labelled ``um`` by v3.1.4 (``:1935``) and ``mm`` by v3.5
  (``:2182``) and the ORACLES production tree, over the identical formula
  (v3.1.4 ``:1441``, v3.5 ``:1684``, both commented ``% in unit of um``):
  ``*1000*(g/mm2 over 0.91 g cm-3)*1000`` is micrometres. Measured: the two
  goldens ``s7f_2dc_accepted`` (``mm``) and ``s7g_f2dc`` (``um``) carry the
  identical value 17.88014416 under the two strings.

**Standard names.** Only ``time`` is written. The CF standard-name table has
no entry for an OAP size-distribution quantity; ``number_concentration_of_*``
and ``effective_radius_of_*`` need a phase the file does not declare, and
``lwe_precipitation_rate`` does not describe ``Prec_rate`` (above). Inventing
one is forbidden by CF itself ("Creating a new string value when a standard
name does not exist is not allowed", quoted by ``arm_export``). ``long_name``
is copied from the source.

**Changes no computed number** in the port's sense (same class as
``arco_export``/``arm_export``): every value written is the source value times
the recorded ``arrayprobe_cf_scale``, the source unit string is kept as
``arrayprobe_source_units``, and the HHMMSS time is kept as ``time_hhmmss``.
``arm_export`` delegates its variable pass here with ``rescale=False`` so its
``CF-1.9`` token is backed by corrected, udunits-legal unit strings and bin
bounds rather than asserted over ``100/100``.

Explicit way on: ``python -m arrayprobe_enhancements.cf_export SD.nc OUT.nc
--flight-date YYYY-MM-DD`` or :func:`export`. ``[enhancements] cf_export =
true`` resolves and records a named skip in the run sidecar, because the run
config carries no flight date and one is never inferred from a file name.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
from pathlib import Path

import netCDF4
import numpy as np

#: The CF version declared. Every requirement this file exercises (§1.3
#: Conventions, §3.1 udunits units, §3.3 standard_name from the table, §4.4
#: time coordinate, §5 coordinate variables, §7.1 cell bounds) reads the same
#: in CF-1.9 and CF-1.10; ``tests/test_cf_export.py`` checks each one.
CF_VERSION = "1.10"
CONVENTIONS = f"CF-{CF_VERSION}"

#: Standard names this exporter may emit -- hand-checked against the CF
#: standard-name table. ``time`` is the only one; see the module docstring.
STANDARD_NAME_ALLOWLIST = frozenset({"time"})

_SIZEDIST = "sizeDist.m"


@dataclasses.dataclass(frozen=True)
class CfMapping:
    """One sizeDist variable's unit story.

    ``source_units`` -- every spelling sizeDist.m writes for it (v3.1.4 and
    v3.5); a file carrying any other string is refused. ``true_units`` -- a
    udunits string for what the value actually is (``scale`` 1 from source).
    ``cf_units`` -- canonical SI. ``scale`` -- multiply the source value by
    this to get ``cf_units``. ``basis`` -- how ``true_units`` was established.
    """

    source_units: frozenset[str]
    true_units: str
    cf_units: str
    scale: float
    basis: str
    long_name: str | None = None


def _m(src, true, cf, scale, basis, long_name=None) -> CfMapping:
    return CfMapping(frozenset(src if isinstance(src, (set, frozenset)) else {src}),
                     true, cf, scale, basis, long_name)


_READ = f"read: the {_SIZEDIST} units string, udunits-legal and not under suspicion"

#: Variable name -> mapping. ``REJ_<name>`` resolves to ``<name>``
#: (sizeDist.m writes the rejected-particle twins with the same units).
VARIABLE_MAP: dict[str, CfMapping] = {
    "bin_min": _m("millimeter", "mm", "m", 1e-3, _READ),
    "bin_max": _m("millimeter", "mm", "m", 1e-3, _READ),
    "bin_mid": _m("millimeter", "mm", "m", 1e-3, _READ),
    "bin_dD": _m("millimeter", "mm", "m", 1e-3, _READ),
    "conc_minR": _m("cm-4", "cm-4", "m-4", 1e8, _READ),
    "conc_AreaR": _m("cm-4", "cm-4", "m-4", 1e8, _READ),
    "habitsd": _m("cm-4", "cm-4", "m-4", 1e8, _READ),
    "area": _m("cm-4", "cm-4", "m-4", 1e8,
               "measured: sum over CIParealen of area equals conc_minR in every "
               "non-zero bin of three Octave-written sizeDist goldens"),
    "n": _m("cm-3", "cm-3", "m-3", 1e6, _READ),
    "total_area": _m("mm2/cm4", "mm2 cm-4", "m-2", 1e2, _READ),
    "Calcd_area": _m("mm^2/cm4", "mm2 cm-4", "m-2", 1e2, _READ),
    "mass": _m("g/cm4", "g cm-4", "kg m-4", 1e5, _READ),
    "massBL": _m("g/cm4", "g cm-4", "kg m-4", 1e5, _READ),
    "habitmsd": _m("g/cm-4", "g cm-4", "kg m-4", 1e5,
                   "derived + measured: sizeDist.m:1358-1376 accumulate good_iwc "
                   "(grams) with mass's normalisation; sum over Habit equals mass "
                   "on the Octave goldens. The source string g/cm-4 parses as g cm4"),
    "re": _m({"um", "mm"}, "um", "m", 1e-6,
             "derived + measured: v3.1.4 :1441 and v3.5 :1684 compute micrometres "
             "('% in unit of um'); v3.5 labels it mm, v3.1.4 um; identical values "
             "carry both strings (goldens s7f vs s7g)"),
    "ar": _m("100/100", "1", "1", 1.0, "read: '100/100' is a ratio; values in [0, 1]"),
    "Reject_ratio": _m("100/100", "1", "1", 1.0,
                       "read: '100/100' is a ratio; values in [0, 1]"),
    "vt": _m("g/cm4", "m s-1 cm-4", "m-3 s-1", 1e8,
             "derived + measured under Octave: sum of single_vt.m fall speeds (SI, "
             "m s-1) per cm of size per cm3; vt/conc_minR == Prec_rate/mass in "
             "single-particle bins",
             long_name="Sum of particle terminal velocities per unit volume per unit "
                       "size (number-weighted; divide by conc_minR for the mean)"),
    "Prec_rate": _m("mm/hr", "g m s-1 cm-4", "kg m-3 s-1", 1e5,
                    "derived + measured under Octave: sum of particle_mass*particle_vt "
                    "(g times m s-1) per cm of size per cm3 -- a size-resolved mass "
                    "flux density, not a liquid-equivalent rate in mm/hr",
                    long_name="Size-resolved downward mass flux density of particles "
                              "(sum of mass times terminal velocity per unit volume "
                              "per unit size)"),
    "count": _m("1", "1", "1", 1.0, _READ),
    "mean_area_ratio": _m("1", "1", "1", 1.0, _READ),
    "mean_aspect_ratio_rectangle": _m("1", "1", "1", 1.0, _READ),
    "mean_aspect_ratio_ellipse": _m("1", "1", "1", 1.0, _READ),
    "mean_perimeter": _m("um", "um", "m", 1e-6, _READ),
    "sum_IntArr": _m("s", "s", "s", 1.0, _READ),
    "iat_threshold": _m("s", "s", "s", 1.0, _READ),
    "sample_vol": _m("cm^3", "cm3", "m3", 1e-6, _READ),
}

#: ``area_bins = 0:.1:1.01`` -- v3.1.4 ``sizeDist.m:591``, v3.5 ``:722``: the
#: edges of the ``CIParealen`` dimension.
AREA_RATIO_EDGES = np.round(np.arange(0.0, 1.01, 0.1), 10)


class CfExportError(ValueError):
    """The source cannot be exported without inventing a fact."""


def mapping_for(name: str) -> CfMapping | None:
    if name in VARIABLE_MAP:
        return VARIABLE_MAP[name]
    if name.startswith("REJ_"):
        return VARIABLE_MAP.get(name[4:])
    return None


def hhmmss_to_seconds(values) -> np.ndarray:
    """Seconds since UTC midnight of the flight date, ``+240000`` read as the
    next day (the preserved ``sizeDist.m:98-99`` rollover); the same decode as
    ``arm_export._hhmmss_to_offset_seconds``."""
    values = np.asarray(values, dtype=np.float64)
    day = np.where(values >= 240000.0, 1, 0)
    folded = np.where(values >= 240000.0, values - 240000.0, values)
    hh = np.floor(folded / 10000.0)
    mm = np.floor((folded - hh * 10000.0) / 100.0)
    ss = folded - hh * 10000.0 - mm * 100.0
    return day * 86400.0 + hh * 3600.0 + mm * 60.0 + ss


def _values(var) -> np.ndarray:
    v = var[:]
    if np.ma.isMaskedArray(v):
        v = v.filled(np.nan if v.dtype.kind == "f" else v.fill_value)
    return np.asarray(v)


def _check_units(name: str, var, mapping: CfMapping) -> str:
    src_units = getattr(var, "units", None)
    if src_units not in mapping.source_units:
        raise CfExportError(
            f"{name}: units {src_units!r} is not a string sizeDist.m writes for this "
            f"variable ({sorted(mapping.source_units)}); refusing rather than guessing "
            "what the value is")
    return src_units


def write_variables(src, dst, *, rescale: bool, dim_map: dict[str, str],
                    skip: frozenset[str] = frozenset({"time"}),
                    coordinates: str | None = None) -> dict[str, float]:
    """Copy every mapped variable of ``src`` into ``dst`` (already holding the
    renamed dimensions). ``rescale=True`` writes ``cf_units`` (value times
    ``scale``); ``False`` writes ``true_units`` with the value untouched -- the
    pass ``arm_export`` delegates. Returns ``{name: scale_applied}``.
    Unmapped variables are refused by name."""
    unmapped = [n for n in src.variables if n not in skip and mapping_for(n) is None]
    if unmapped:
        raise CfExportError(f"no CF mapping for {unmapped}; cf_export maps sizeDist "
                            "(sd) variables only and never invents a unit")
    applied: dict[str, float] = {}
    for name, var in src.variables.items():
        if name in skip:
            continue
        mapping = mapping_for(name)
        # The `unmapped` sweep above already raised if any name outside `skip` had no
        # mapping, and `name` is unchanged since -- mapping_for is a pure lookup, so this
        # cannot be None here. Asserted so the type checker sees the same invariant the
        # earlier raise already enforces at runtime.
        assert mapping is not None
        src_units = _check_units(name, var, mapping)
        scale = mapping.scale if rescale else 1.0
        dims = tuple(dim_map.get(d, d) for d in var.dimensions)
        out = dst.createVariable(name, "f8", dims)
        values = _values(var).astype(np.float64)
        out[:] = values * scale if scale != 1.0 else values
        out.units = mapping.cf_units if rescale else mapping.true_units
        long_name = mapping.long_name or getattr(var, "long_name", None)
        if long_name is not None:
            out.long_name = long_name
        if getattr(var, "long_name", None) is not None and mapping.long_name is not None:
            out.arrayprobe_source_long_name = var.long_name
        if hasattr(var, "short_name"):
            out.arrayprobe_source_short_name = var.short_name
        out.arrayprobe_source_units = src_units
        out.arrayprobe_cf_scale = float(scale)
        out.arrayprobe_units_basis = mapping.basis
        if coordinates and len(dims) > 1 and "CIPcorrlen" in var.dimensions:
            out.coordinates = coordinates
        applied[name] = float(scale)
    return applied


def write_bin_bounds(src, dst, *, dim: str, name: str, scale: float) -> None:
    """``bin_min``/``bin_max`` as a CF §7.1 ``(n, 2)`` bounds variable."""
    if "nv" not in dst.dimensions:
        dst.createDimension("nv", 2)
    b = dst.createVariable(name, "f8", (dim, "nv"))
    b[:] = np.column_stack([_values(src.variables["bin_min"]),
                            _values(src.variables["bin_max"])]).astype(np.float64) * scale
    b.long_name = "size bin bounds (bin_min, bin_max)"
    # CF §7.1: a boundary variable inherits its parent's units; none written.


def _read_call_stamp(infile: Path) -> str | None:
    for cand in (infile.with_suffix(".call"), Path(f"{infile}.call")):
        if cand.is_file():
            return cand.read_text(encoding="utf-8").strip()
    return None


def _stamp_engine(stamp: str | None) -> str | None:
    if not stamp:
        return None
    for tok in stamp.split():
        if tok.startswith("engine="):
            return tok.split("=", 1)[1]
    return None


def _package_version(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return "unknown"


@dataclasses.dataclass(frozen=True)
class CfExportReport:
    outfile: Path
    n_times: int
    engine: str
    scales: dict[str, float]


def export(infile, outfile, *, flight_date: _dt.date, engine: str | None = None,
           call_stamp: str | None = None) -> CfExportReport:
    """Write a CF-1.10 sibling of ``infile`` (a port ``sd`` file).

    ``flight_date`` is required: the file's own ``time`` is ``HHMMSS`` and a
    date is never read off a file name (the ``arm_export`` rule). ``engine`` is
    taken from the ``.call`` stamp beside ``infile`` when not given; a stamp
    that names no engine is recorded as such, never guessed. A decoded time
    axis that is not strictly increasing is refused, not sorted."""
    infile, outfile = Path(infile), Path(outfile)
    if infile.resolve() == outfile.resolve():
        raise CfExportError("outfile must differ from infile; the port file is never rewritten")
    stamp = call_stamp if call_stamp is not None else _read_call_stamp(infile)
    engine = engine or _stamp_engine(stamp) or "not recorded in the .call stamp"

    with netCDF4.Dataset(str(infile)) as src:
        if "time" not in src.variables or "CIPcorrlen" not in src.dimensions:
            raise CfExportError(f"{infile} is not a sizeDist (sd) output")
        raw_time = _values(src.variables["time"]).astype(np.float64)
        if getattr(src.variables["time"], "units", None) != "HHMMSS":
            raise CfExportError("time is not HHMMSS; not a sizeDist output")
        seconds = hhmmss_to_seconds(raw_time)
        if seconds.size > 1 and not np.all(np.diff(seconds) > 0):
            bad = int(np.argmax(np.diff(seconds) <= 0))
            raise CfExportError(
                f"decoded time is not strictly increasing at index {bad} "
                f"({raw_time[bad]:.0f} -> {raw_time[bad + 1]:.0f}); the preserved "
                "sizeDist.m:98-99 rollover defect can do this. Refusing rather than sorting")
        dim_map = {"Time": "time", "CIPcorrlen": "bin", "CIParealen": "area_ratio_bin",
                   "Habit": "habit"}
        with netCDF4.Dataset(str(outfile), "w", format="NETCDF4") as dst:
            for name, dim in src.dimensions.items():
                dst.createDimension(dim_map.get(name, name),
                                    None if dim.isunlimited() else dim.size)

            t = dst.createVariable("time", "f8", ("time",))
            t[:] = seconds
            t.standard_name = "time"
            t.long_name = "time"
            t.units = f"seconds since {flight_date.isoformat()}T00:00:00Z"
            t.calendar = "standard"
            t.axis = "T"
            th = dst.createVariable("time_hhmmss", "f8", ("time",))
            th[:] = raw_time
            th.long_name = "sizeDist HHMMSS time, verbatim"
            th.comment = ("The source's own encoding (units string 'HHMMSS', not a "
                          "udunits unit, so kept here as a comment); decoded into time.")

            bin_scale = VARIABLE_MAP["bin_mid"].scale
            b = dst.createVariable("bin", "f8", ("bin",))
            b[:] = _values(src.variables["bin_mid"]).astype(np.float64) * bin_scale
            b.long_name = "particle size bin midpoint (maximum dimension)"
            b.units = "m"
            b.bounds = "bin_bounds"
            write_bin_bounds(src, dst, dim="bin", name="bin_bounds", scale=bin_scale)

            n_ar = src.dimensions["CIParealen"].size
            if n_ar != AREA_RATIO_EDGES.size - 1:
                raise CfExportError(f"CIParealen has {n_ar} bins; sizeDist.m's area_bins "
                                    f"define {AREA_RATIO_EDGES.size - 1}")
            a = dst.createVariable("area_ratio_bin", "f8", ("area_ratio_bin",))
            a[:] = 0.5 * (AREA_RATIO_EDGES[:-1] + AREA_RATIO_EDGES[1:])
            a.long_name = "area ratio bin midpoint"
            a.units = "1"
            a.bounds = "area_ratio_bin_bounds"
            a.comment = "edges area_bins = 0:.1:1.01 (sizeDist.m:591 v3.1.4, :722 v3.5)"
            ab = dst.createVariable("area_ratio_bin_bounds", "f8", ("area_ratio_bin", "nv"))
            ab[:] = np.column_stack([AREA_RATIO_EDGES[:-1], AREA_RATIO_EDGES[1:]])

            h = dst.createVariable("habit", "i4", ("habit",))
            h[:] = np.arange(1, src.dimensions["Habit"].size + 1, dtype=np.int32)
            h.long_name = "habit class index (third index of sizeDist.m cip2_habitsd)"
            h.units = "1"

            scales = write_variables(src, dst, rescale=True, dim_map=dim_map)
            _write_tas_qc(dst, infile, raw_time)

            title = getattr(src, "Description", None)
            dst.Conventions = CONVENTIONS
            dst.title = "Optical array probe size distribution (arrayprobe, CF export)"
            if title:
                dst.summary = str(title)
            inst = getattr(src, "Institution", None)
            if inst:
                dst.institution = str(inst)
            ver = _package_version("arrayprobe")
            ever = _package_version("arrayprobe-uiops-enhancements")
            dst.source = (f"arrayprobe {ver}, UIOPS {engine} engine; "
                          f"source software attribute {getattr(src, 'Software', 'absent')!r}")
            dst.history = (f"{_dt.datetime.now(_dt.timezone.utc).isoformat()} "
                           f"arrayprobe_enhancements.cf_export {infile.name} -> {outfile.name}")
            dst.references = ("UIOPS (McFarquhar group, GPLv3); arrayprobe "
                              "(bug-for-bug UIOPS port) and arrayprobe-enhancements")
            if stamp:
                dst.comment = f".call stamp of the source: {stamp}"
            dst.arrayprobe_cf_export_source = infile.name
            dst.enhancements_engine = engine
            dst.arrayprobe_version = ver
            dst.arrayprobe_enhancements_version = ever
            dst.enhancements_applied = "cf_export"

    return CfExportReport(outfile=outfile, n_times=int(seconds.size), engine=engine,
                          scales=scales)


def _write_tas_qc(dst, infile: Path, raw_time) -> None:
    """The source's ``.tasqc.json`` as globals plus a per-second ``tas_quality_flag``
    that every time-dimensioned data variable names in ``ancillary_variables``; with no
    record, one global says so. Read-only on the source."""
    from arrayprobe.tools import tas_sources as ts

    rec = ts.read_qc_sidecar(infile)
    if rec is None:
        dst.arrayprobe_tas_qc = ("absent: the source carries no .tasqc.json (no TAS source "
                                 "named, or it predates the 2026-09-23 record); defaulted seconds not stated")
        return
    for key, value in rec.items():
        dst.setncattr(f"arrayprobe_{key}", value)
    q = dst.createVariable("tas_quality_flag", "i1", ("time",))
    q[:] = ts.qc_flags(rec, raw_time)
    q.long_name = "quality of the true airspeed each second was sized with"
    q.flag_values = np.array([ts.QC_FLAG_MEASURED, ts.QC_FLAG_SUBSTITUTED,
                              ts.QC_FLAG_DEFAULTED], dtype=np.int8)
    q.flag_meanings = "measured substituted_by_policy absent_defaulted"
    q.comment = rec.get("tas_uncertainty", "")
    for name, var in dst.variables.items():
        if ("time" in var.dimensions
                and name not in ("time", "time_hhmmss", "tas_quality_flag")):
            var.ancillary_variables = "tas_quality_flag"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m arrayprobe_enhancements.cf_export",
                                description="Write a CF-1.10 sibling of a port sd file.")
    p.add_argument("infile")
    p.add_argument("outfile")
    p.add_argument("--flight-date", required=True, type=_dt.date.fromisoformat,
                   help="UTC date of the flight (YYYY-MM-DD); never inferred")
    p.add_argument("--engine", default=None,
                   help="UIOPS engine; default: read from the .call stamp beside infile")
    a = p.parse_args(argv)
    r = export(a.infile, a.outfile, flight_date=a.flight_date, engine=a.engine)
    print(f"wrote {r.outfile} ({r.n_times} times, engine {r.engine})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
