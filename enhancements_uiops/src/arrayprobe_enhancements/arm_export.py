# SPDX-License-Identifier: BSD-3-Clause
"""A CF-1.9 + ARM Data File Standards structural copy of a port output file.

**The question this answers**, (item 22, "an ACT/ARM-conformant
output... Argonne-facing, small, and the first thing an ARM user will ask
for"). ARM's own facility publishes 2D-S/HVPS data (the ``aaf2dsh``/``aaf2dsv``
datastreams from the ARM Aerial Facility), but **no public ARM page names the
OAP processing software behind them**, and ``ACT`` (``ARM-DOE/ACT``) has no
reader for any optical array probe. This module writes a copy of a port
``sd``/combined output whose *structure* -- time axis, key global attributes
-- follows ``DOE/SC-ARM-15-004`` (ARM Data File Standards, v1.3, September
2020), so a generic ARM/CF reader (``act.io.read_arm_netcdf`` -- ACT's own
rename of what this module first cited as ``read_netcdf``, confirmed by
actually running it, ``tests/test_arm_export.py::ReadableByRealArmTools`` --
and ``xarray``) opens it correctly and an ARM user recognises the shape.

**Read directly from the standard, not recalled**, because this project's own
rule is that a fact that can be looked up is never reconstructed from memory:
the file-naming grammar (§5.1), the required ``base_time``/``time_offset``/
``time`` triple (§6.1.2-6.1.3), and the global-attribute definitions and worked
examples of §6.7.1 (``command_line``, ``Conventions``, ``process_version``,
``site_id``, ``platform_id``, ``facility_id``, ``data_level``, ``datastream``,
``title``, ``institution``, ``description``, ``history``).

**What this deliberately does NOT claim**, so nobody mistakes it for an
ARM Data Center-ingested product:

- **No DOI, no ``input_datastreams``/``input_source``.** Those require an
  ARM Data Center registration and an ARM-ingested input chain; this file has
  neither.
- **No QC parallel variables (§6.8).** The port has no per-value QC test
  framework yet (bit-packed or otherwise); adding empty ``qc_*`` variables
  would be worse than omitting them.
- **No ``standard_name`` on the physical variables (§6.6.4).** CF's own
  standard-name table has no entries for OAP-specific quantities like
  ``conc_minR`` or ``habitsd``; inventing one is explicitly against the CF
  rule this document itself quotes ("Creating a new string value when a
  standard name does not exist is not allowed"). ``long_name`` and a
  udunits-legal ``units`` are what CF requires when no standard name applies.
- **``site_id``/``facility_id``/``platform_id`` are never invented.** ARM's
  site and facility codes are assigned by the ARM Data Center; a P-3 flight
  over the open ocean has none. The three are required call-time arguments
  with no default, so a caller who *does* have real ARM identifiers (a future
  AAF deployment) stamps them, and a caller who does not is never handed a
  plausible-looking but fake one.
- **Six recommended §6.7.1 attributes are written only when supplied.**
  ``sampling_interval``, ``averaging_interval``, ``sensor_height``,
  ``location_description``, ``references`` and ``dod_version`` are
  recommended, not required, and nothing in a port output states them; a
  caller who has them passes ``recommended_attributes``, otherwise they are
  absent (the standard asks for no "not provided" placeholder).
- **``missing_value`` is declared only on request** (``declare_missing_value``,
  §6.6.2): it names the value the variable pass already writes for a masked
  source value (``NaN`` for floats, the source's fill value otherwise). Default
  off until the value is checked against ``sizeDist.m``'s own convention
  (``docs/developer/ARM_OUTPUT_FORMAT.md`` §2.3).
- **File naming (§5.1, §5.1.1)** is built by ``build_filename`` and checked
  by ``check_filename``; ``export(check_name=True)`` refuses an ``outfile``
  whose name breaks the grammar's character set or length limits.

**Provenance is opt-in and additive, never dropped by default.** Every global
attribute the source file carries is copied to the output under an
``arrayprobe_source_`` prefix (``preserve_source_globals``, default on) --
before this the export silently dropped them, which was a real gap: a file
this module wrote carried no trace of which engine produced it, what profile
it ran under, or the run's ``.call`` stamp. A caller with that information
(read from the source file's own attributes and from the sidecar files this
project already writes -- never invented here) passes it through
``engine``/``engine_validation``/``stage``/``call_stamp``/``enhancements_report``
and it is written as ``arrayprobe_engine`` etc.; a caller without it passes
nothing, and the attribute is simply absent, not filled with a guess.

**Changes no computed number** -- same space as ``particle_clustering`` and
``arco_export``: every data value is copied through unchanged; only the time
representation and the attribute set are added or reshaped. **The ``CF-1.9``
token is backed by** ``cf_export``'s variable pass run with
``rescale=False``: each ``units`` string is the udunits string for what the
value is (``100/100`` became ``1``; ``g/cm-4``, ``vt`` and ``Prec_rate`` are
corrected -- ``cf_export``'s docstring gives the evidence), the source string is
kept as ``arrayprobe_source_units``, and ``bin_mid`` carries CF bounds. A
variable ``cf_export`` does not map is refused by name. Composable with
``arco_export``: run this first for ARM/CF structure, then ``arco_export`` on
its output for the dtype/chunking/compression pass, or the reverse -- neither
touches the other's concern.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import re
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements.cf_export import write_bin_bounds, write_variables

#: The ARM Data File Standards version this module targets (DOE/SC-ARM-15-004).
ARM_STANDARDS_VERSION = "1.3"

#: This module's own contribution to the combined ``Conventions`` attribute.
#: ARM's own convention (§6.7.1) is "ARM" + "-" + the standards document
#: version, and recommends listing it first when combined with others.
CONVENTIONS = f"ARM-{ARM_STANDARDS_VERSION} CF-1.9"


@dataclasses.dataclass(frozen=True)
class ArmExportReport:
    """What was written, so a caller can log or assert it."""

    outfile: Path
    datastream: str
    n_times: int
    flight_date: _dt.date


def _hhmmss_to_offset_seconds(values: np.ndarray) -> np.ndarray:
    """Convert ``sizeDist``'s ``HHMMSS`` time encoding to seconds since UTC
    midnight of the flight date.

    ``sizeDist.m`` applies its own midnight rollover correction only to the
    *first* post-midnight second (preserved bug,
    fidelity doctrine: ``sizeDist.m:98-99``) by adding 240000 to it. This function
    decodes exactly what is in the file, including that quirk -- it does not
    attempt to detect or repair a second rollover the port itself does not
    correct, because inventing a corrected time series the source data does
    not support would be a new fact, not a read one.
    """
    values = np.asarray(values, dtype=np.float64)
    day = np.where(values >= 240000.0, 1, 0)
    folded = np.where(values >= 240000.0, values - 240000.0, values)
    hh = np.floor(folded / 10000.0)
    mm = np.floor((folded - hh * 10000.0) / 100.0)
    ss = folded - hh * 10000.0 - mm * 100.0
    return day * 86400.0 + hh * 3600.0 + mm * 60.0 + ss


def _epoch_seconds_at_midnight(flight_date: _dt.date) -> int:
    midnight = _dt.datetime(flight_date.year, flight_date.month, flight_date.day,
                             tzinfo=_dt.timezone.utc)
    return int(midnight.timestamp())


def build_datastream_id(site_id: str, platform_id: str, facility_id: str,
                         data_level: str) -> str:
    """``site_id + platform_id + facility_id + "." + data_level`` (§6.7.1).

    Lower-cased per the standard's "all characters are lowercase except for
    the facility indicator" rule (§5.1); the caller's ``facility_id`` case is
    preserved, since the standard requires an initial capital letter there
    (e.g. ``"F1"``, ``"M1"``).
    """
    return f"{site_id.lower()}{platform_id.lower()}{facility_id}.{data_level}"


def _write_qc_tas(dst, infile: Path, raw_time, time_dim: str) -> None:
    """The source's ``.tasqc.json`` as globals plus ARM's bit-packed ``qc_tas``
    (DOE/SC-ARM-15-004 bit conventions); with no record, one global says so. The only QC
    variable this export writes, and only when the record exists."""
    from arrayprobe.tools import tas_sources as ts

    rec = ts.read_qc_sidecar(infile)
    if rec is None:
        dst.setncattr("arrayprobe_tas_qc", "absent: the source carries no .tasqc.json (no TAS "
                                           "source named, or it predates the 2026-09-23 record)")
        return
    for key, value in rec.items():
        dst.setncattr(f"arrayprobe_{key}", value)
    flags = ts.qc_flags(rec, raw_time)
    bits = np.where(flags == ts.QC_FLAG_SUBSTITUTED, 1,
                    np.where(flags == ts.QC_FLAG_DEFAULTED, 2, 0)).astype(np.int32)
    q = dst.createVariable("qc_tas", "i4", (time_dim,))
    q[:] = bits
    q.long_name = "Quality check results on the true airspeed each second was sized with"
    q.units = "1"
    q.description = "This variable contains bit-packed integer values, where each bit represents a QC test on the data. Non-zero bits indicate the QC condition given in the description for those bits; a value of 0 (no bits set) indicates the data has not failed any QC tests."
    q.flag_method = "bit"
    q.bit_1_description = "true airspeed substituted by the run's TAS policy"
    q.bit_1_assessment = "Indeterminate"
    q.bit_2_description = "no true airspeed sample; sized with the default TAS"
    q.bit_2_assessment = "Indeterminate"
    q.comment = rec.get("tas_uncertainty", "")


#: §6.7.1 recommended attributes this module writes only when the caller
#: supplies them (``docs/developer/ARM_OUTPUT_FORMAT.md`` §0.4, §2.5).
RECOMMENDED_ATTRIBUTES = ("sampling_interval", "averaging_interval", "sensor_height",
                          "location_description", "references", "dod_version")

#: §5.1.1 length limits, as recorded in ARM_OUTPUT_FORMAT.md §0.1.
MAX_FILENAME_CHARS = 60
MAX_DATASTREAM_CHARS = 33
MAX_INSTRUMENT_CHARS = 24
_ALLOWED_NAME = re.compile(r"^[A-Za-z0-9.]+$")


class ArmFilenameError(ValueError):
    """An ARM filename breaks §5.1's character set or §5.1.1's length limits."""


def check_filename(name: str) -> str:
    """Raise ``ArmFilenameError`` if ``name`` breaks §5.1/§5.1.1; return it.

    Checks the allowed characters (``a-z A-Z 0-9 .``), the 60-character total
    and, when the name parses as ``<datastream>.<yyyymmdd>.<hhmmss>.nc``, the
    33-character datastream portion.
    """
    if not _ALLOWED_NAME.match(name):
        raise ArmFilenameError(f"{name!r}: only a-z, A-Z, 0-9 and '.' are allowed (ARM S5.1)")
    if len(name) > MAX_FILENAME_CHARS:
        raise ArmFilenameError(f"{name!r} is {len(name)} characters; ARM S5.1.1 allows "
                               f"at most {MAX_FILENAME_CHARS}")
    parts = name.split(".")
    if len(parts) >= 5:
        datastream = ".".join(parts[:-3])
        if len(datastream) > MAX_DATASTREAM_CHARS:
            raise ArmFilenameError(f"datastream portion {datastream!r} is {len(datastream)} "
                                   f"characters; ARM S5.1.1 allows at most "
                                   f"{MAX_DATASTREAM_CHARS}")
    return name


def build_filename(site_id: str, platform_id: str, facility_id: str, data_level: str,
                   start: _dt.datetime) -> str:
    """``(sss)(inst)(Fn).(dl).(yyyymmdd).(hhmmss).nc`` (§5.1), length-checked.

    ``start`` is the UTC time of the first data point. ``platform_id`` carries
    the instrument description (``inst`` plus any qualifier/temporal suffix),
    which §5.1.1 limits to 24 characters.
    """
    if len(platform_id) > MAX_INSTRUMENT_CHARS:
        raise ArmFilenameError(f"instrument portion {platform_id!r} is {len(platform_id)} "
                               f"characters; ARM S5.1.1 allows at most {MAX_INSTRUMENT_CHARS}")
    datastream = build_datastream_id(site_id, platform_id, facility_id, data_level)
    return check_filename(f"{datastream}.{start:%Y%m%d}.{start:%H%M%S}.nc")


def _declare_missing_values(src, dst, skip: set) -> None:
    """§6.6.2: name, on every copied data variable, the no-data value the
    variable pass already writes (NaN for floats, the source fill otherwise)."""
    for name, var in dst.variables.items():
        if name in skip or name not in src.variables:
            continue
        dtype = np.dtype(var.dtype)
        if dtype.kind == "f":
            value = dtype.type(np.nan)
        else:
            srcvar = src.variables[name]
            fill = getattr(srcvar, "_FillValue", None)
            if fill is None:
                fill = netCDF4.default_fillvals.get(dtype.str[1:])
            if fill is None:
                continue
            value = dtype.type(fill)
        var.setncattr("missing_value", value)


def export(infile, outfile, *,
           flight_date: _dt.date,
           site_id: str,
           platform_id: str,
           facility_id: str,
           data_level: str = "c1",
           command_line: str | None = None,
           institution: str | None = None,
           description: str | None = None,
           time_dim: str = "Time",
           preserve_source_globals: bool = True,
           engine: str | None = None,
           engine_validation: str | None = None,
           stage: str | None = None,
           call_stamp: str | None = None,
           enhancements_report: str | None = None,
           recommended_attributes: dict | None = None,
           declare_missing_value: bool = False,
           check_name: bool = False) -> ArmExportReport:
    """Write an ARM/CF-structural copy of ``infile`` (a port ``sd`` or
    combined output). ``infile`` is never opened for writing.

    ``flight_date`` is required rather than parsed from the source file: an
    ``sd`` file's own ``time`` variable carries only ``HHMMSS``, and the
    ORACLES stem convention (``base<YYMMDDhhmmss>``) is one campaign's
    convention, not every probe's.
    Guessing the date from a filename that might not encode one would be
    exactly the kind of invented fact this project's doctrine forbids.

    **Provenance, since I-arm-provenance.** Every global attribute ``infile``
    already carries (``Software``, ``Project``, ``Data_Source``, ``Habit_Scheme``,
    ...) is copied to the output under an ``arrayprobe_source_`` prefix when
    ``preserve_source_globals`` is true (the default) -- ARM's own required
    attributes (``description``, ``history``, ...) are lower/mixed-case and
    this project's port attributes use their own native casing (``Description``,
    ``SA Method``), so the prefix rules out any collision rather than relying on
    case alone. ``engine``, ``engine_validation``, ``stage``, ``call_stamp`` and
    ``enhancements_report`` are opt-in, caller-supplied text (never read from
    disk by this function -- the same "explicit argument, no guessing" design as
    ``flight_date``): a caller who has a ``.call`` sidecar or an
    ``arrayprobe_enhancements`` driver's ``*.enhancements.json`` report reads it
    and passes the text through; a caller with neither passes nothing, and none
    of these five attributes appear in the output -- no placeholder is invented
    to fill an absent one.
    """
    infile, outfile = Path(infile), Path(outfile)
    datastream = build_datastream_id(site_id, platform_id, facility_id, data_level)
    unknown = set(recommended_attributes or {}) - set(RECOMMENDED_ATTRIBUTES)
    if unknown:
        raise ValueError(f"not an ARM S6.7.1 recommended attribute: {sorted(unknown)}")
    if check_name:
        check_filename(Path(outfile).name)

    with netCDF4.Dataset(str(infile)) as src, \
            netCDF4.Dataset(str(outfile), "w", format="NETCDF4") as dst:
        if "time" not in src.variables:
            raise ValueError(f"{infile} has no 'time' variable; not a "
                              "recognised sizeDist/combine output")
        raw_time = np.asarray(src.variables["time"][:])
        offset_seconds = _hhmmss_to_offset_seconds(raw_time)
        base_epoch = _epoch_seconds_at_midnight(flight_date)

        for name, dim in src.dimensions.items():
            dst.createDimension(name, None if dim.isunlimited() else dim.size)

        base_time = dst.createVariable("base_time", "i8")
        base_time[:] = base_epoch
        base_time.long_name = "Base time in Epoch"
        base_time.units = "seconds since 1970-1-1 0:00:00 0:00"
        base_time.string = flight_date.strftime("%d-%b-%Y,00:00:00 GMT")
        base_time.ancillary_variables = "time_offset"

        time_units = f"seconds since {flight_date.isoformat()} 00:00:00 0:00"

        time_offset = dst.createVariable("time_offset", "f8", (time_dim,))
        time_offset[:] = offset_seconds
        time_offset.long_name = "Time offset from base_time"
        time_offset.units = time_units
        time_offset.ancillary_variables = "base_time"

        time_var = dst.createVariable("time", "f8", (time_dim,))
        time_var[:] = offset_seconds
        time_var.long_name = "Time offset from midnight"
        time_var.units = time_units
        time_var.standard_name = "time"
        time_var.calendar = "gregorian"
        time_var.axis = "T"

        # The source's own HHMMSS encoding, kept rather than discarded --
        # this project's own convention ("never invent a fact to
        # fill a gap") extends to never silently dropping one either.
        time_hhmmss = dst.createVariable("time_hhmmss", raw_time.dtype.str[1:],
                                          (time_dim,))
        time_hhmmss[:] = raw_time
        time_hhmmss.long_name = "Original sizeDist HHMMSS time encoding"
        # 'HHMMSS' is not a udunits unit, and CF §3.1 requires any units
        # attribute to be one; the encoding is named in the comment.
        time_hhmmss.comment = ("HHMMSS encoding (source units string 'HHMMSS'). "
                                "Decoded into time/time_offset/base_time above "
                                "following ARM's base_time+time_offset "
                                "convention (DOE/SC-ARM-15-004 S6.1.2); kept "
                                "verbatim so no information is discarded.")

        # The variable pass is cf_export's, with rescale=False --
        # every value is copied unchanged, but each variable's units string is
        # replaced by the udunits string for what the value actually is
        # (``100/100`` -> ``1``, ``g/cm-4`` -> ``g cm-4``, ``vt``/``Prec_rate``
        # corrected; the source string kept as ``arrayprobe_source_units``),
        # and the size bins gain CF §7.1 bounds. Before this the CF-1.9 token
        # in ``Conventions`` was asserted over non-udunits strings.
        write_variables(src, dst, rescale=False, dim_map={},
                        coordinates="bin_mid" if "bin_mid" in src.variables else None)
        if {"bin_min", "bin_max", "bin_mid"} <= set(src.variables):
            write_bin_bounds(src, dst, dim=src.variables["bin_mid"].dimensions[0],
                             name="bin_bounds", scale=1.0)
            dst.variables["bin_mid"].bounds = "bin_bounds"

        dst.setncattr("command_line", command_line or f"arrayprobe_enhancements.arm_export "
                                                        f"({infile.name} -> {outfile.name})")
        dst.setncattr("Conventions", CONVENTIONS)
        dst.setncattr("process_version", "arrayprobe_enhancements.arm_export, "
                                          f"ARM Data File Standards v{ARM_STANDARDS_VERSION}")
        dst.setncattr("site_id", site_id)
        dst.setncattr("platform_id", platform_id)
        dst.setncattr("facility_id", facility_id)
        dst.setncattr("data_level", data_level)
        dst.setncattr("datastream", datastream)
        dst.setncattr("title", "Optical array probe size distribution "
                                "(arrayprobe / UIOPS-derived)")
        dst.setncattr("institution", institution
                      or getattr(src, "Institution", "not an ARM-ingested product"))
        dst.setncattr("description", description
                      or "Derived from a bug-for-bug faithful arrayprobe "
                         "(UIOPS port) output; not an ARM Data Center product. "
                         "See arrayprobe_arm_export_source below.")
        dst.setncattr("history", f"created by arrayprobe_enhancements.arm_export "
                                  f"at {_dt.datetime.now(_dt.timezone.utc).isoformat()}")
        dst.setncattr("arrayprobe_arm_export_source", infile.name)
        dst.setncattr("arrayprobe_arm_export_standard",
                      f"DOE/SC-ARM-15-004 v{ARM_STANDARDS_VERSION}; structural "
                      "conformance only -- no DOI, no QC parallel variables, "
                      "no ARM-assigned identifiers unless supplied by the caller")

        # Provenance this package itself writes, all opt-in and caller-supplied
        # (see the docstring). Written only when the caller has the fact to
        # hand -- an absent attribute here means "not supplied," never "no".
        if engine is not None:
            dst.setncattr("arrayprobe_engine", engine)
        if engine_validation is not None:
            dst.setncattr("arrayprobe_engine_validation", engine_validation)
        if stage is not None:
            dst.setncattr("arrayprobe_stage", stage)
        if call_stamp is not None:
            dst.setncattr("arrayprobe_call_stamp", call_stamp)
        if enhancements_report is not None:
            dst.setncattr("arrayprobe_enhancements_report", enhancements_report)

        if preserve_source_globals:
            for name in src.ncattrs():
                dst.setncattr(f"arrayprobe_source_{name}", getattr(src, name))

        for key, value in (recommended_attributes or {}).items():
            dst.setncattr(key, value)
        if declare_missing_value:
            _declare_missing_values(src, dst, skip={"base_time", "time_offset", "time",
                                                    "time_hhmmss", "qc_tas", "bin_bounds"})

        _write_qc_tas(dst, infile, raw_time, time_dim)

    return ArmExportReport(outfile=outfile, datastream=datastream,
                            n_times=int(offset_seconds.size), flight_date=flight_date)
