# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_export_ncdf_raf.pro`` (312 lines): SODA-2's NCAR-RAF/nimbus netCDF export.

Who calls it: like its sibling ``soda2_export_ncdf.pro`` (ported as
:mod:`arrayprobe_soda2.export_ncdf`), only the GUI (``soda2_export.pro``);
the driver ``soda2_process_2d.pro`` never does. Input is the same ``data``
structure (:class:`~arrayprobe_soda2.process_2d.ProcessData`, or a mapping
of IDL tag to value in declaration order, with ``op`` a mapping).

Format: ``ncdf_create(outfile[0], /clobber)`` (`:14`), no NETCDF4 keyword,
so ``NETCDF3_CLASSIC``.

Ported whole: dimensions (`:16-29`), global attributes (`:31-55`), the
three time variables (`:57-74`), the main-tag loop (`:77-237`) and the
bulk-variable loop (`:239-312`: LWC, IWC, IWC100, AREA, AREA100, MVD, MND,
NT, MVD100, MND100, NT100 from ``compute_bulk_simple``/``compute_area``,
always from the normalized ``data.conc1d`` whatever ``normalize`` is).
Refused by name: ``i100 = -1`` or ``= numbins`` (`:241-242`,
:class:`~arrayprobe_soda2.export_ncdf.MinsizeBinstartOutOfRange`) and a
``data`` whose last tag is CONC1D/SPEC1D (`:296-301`,
:class:`BulkAttnameCarryOver`).

Quirks preserved (bug-for-bug, never fixed):

- ``sps1`` (`:19`) is ``(1.0/data.op.rate)>1``, a FLOAT dimension size
  that the ncdf layer truncates to a long: rate 1 -> 1, rate 0.1 -> 10,
  rate 0.3 -> 3, rate 10 -> 1. The 3-D variables are then written with a
  ``reform(..., numbins, 1, ntime)`` value (`:186`, `:197`), so when
  ``sps1 > 1`` only the ``sps1 = 0`` slab is written and the rest keeps the
  fill value (derived from ``ncdf_varput``'s default COUNT = the value's
  own dimensions; pinned by GDL).
- Three ``Vector<n>`` dimensions are named by their length (`:22-29`), so
  two equal lengths collide: IDL halts at the second ``ncdf_dimdef``
  (:class:`~arrayprobe_soda2.export_ncdf.DimensionNameInUse`). The
  area-ratio dimension (`:29`) is defined and never used.
- ``Time``/``base_time``/``utc_time`` are LONG variables (`:59-67`) fed
  the float ``data.time`` (`:71-73`): the store truncates toward zero.
  ``base_time`` is ``data.time[0] + days1970*86400L`` evaluated in
  ``data.time``'s own type first, so a FLOAT time loses its seconds before
  the truncation.
- An empty-string ``op`` field is replaced by ``'none'`` in the caller's
  own ``op`` (`:53`, by reference).
- A main tag whose output name already exists as a variable is re-put
  into it rather than redefined (`:223-224`): ``'C'+probetype`` with
  probetype ``'LH'`` lands in ``CLH``.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import numpy as np

from .export_ascii import compute_bulk_simple, unnormalize
from .export_ncdf import (
    DimensionNameInUse,
    MinsizeBinstartOutOfRange,
    _first,
    _idl_value,
    _min_where_ge,
    _n_elements,
    _put_att,
    _tags,
    compute_area,
    idl_sfm2hms,
)
from .pbp_writer import _idl_hms_string, engine_attrs
from .spec_index import julday
from .timeconv import soda2_parsedate

__all__ = [
    "BulkAttnameCarryOver",
    "FillValueOnExistingVariable",
    "MinsizeBinstartOutOfRange",
    "soda2_export_ncdf_raf",
    "sps1_size",
]


class BulkAttnameCarryOver(IndexError):
    """`:296-301`: the bulk loop never resets ``attname``, so it inherits the
    main loop's last value (reset each pass at `:84`). When the last tag of
    ``data`` is CONC1D (nine names, `:165`) or SPEC1D (four, `:190`), the
    loop walks past the two-field bulk ``attvalue``: ``attvalue.(2)`` at
    `:297` is out of range, and ``attname[0] = '_FillValue'`` already pairs
    with the long-name string at `:300` (derived, not GDL-measured). IDL
    halts with the file open; the port raises before writing a bulk tag."""


class FillValueOnExistingVariable(NotImplementedError):
    """`:223-229`: a CONC1D/SPEC1D output name that repeats an existing
    variable re-puts ``_FillValue`` on it. netCDF4-python refuses a
    ``_FillValue`` after creation, so this path is refused by name."""


# `:91-152`, `:200-218` -- (long_name, units, dimension) per simple tag.
_MAIN_SIMPLE: dict[str, tuple[str, str, str]] = {
    "SA": ("Sample Area", "m2", "size"),
    "COUNT_ACCEPTED": ("Count Accepted", "#", "time"),
    "TAS": ("True Air speed used", "m/s", "time"),
    "CLH": ("CU Laser Hygrometer, Condensed Water Content", "g/m3", "time"),
    "LAT": ("Latitude", "degrees", "time"),
    "LON": ("Longitude", "degrees", "time"),
    "GALT": ("GPS Altitude", "meters", "time"),
    "T": ("Temperature", "degrees Celsius", "time"),
    "PRES": ("Pressure", "hPa", "time"),
    "ACTIVETIME": ("Probe activity time", "s", "time"),
    "CDP_NT": ("Total number concentration from the CDP", "#/cm3", "time"),
    "CDP_LWC": ("Total LWC derived from the CDP", "g/m3", "time"),
    "CDP_MEAND": ("Mean diameter from the CDP", "microns", "time"),
    "CONCU": ("UHSAS Total Concentration", "#/cm3", "time"),
    "CONCU100": ("UHSAS Concentration, 0.1 micron and bigger", "#/cm3", "time"),
    "CONCU500": ("UHSAS Concentration, 0.5 microns and bigger", "#/cm3", "time"),
    "W": ("GPS-Corrected Wind Vector, Vertical Gust Component", "m/s", "time"),
    "V": ("GPS-Corrected Wind Vector, North Component", "m/s", "time"),
    "U": ("GPS-Corrected Wind Vector, East Component", "m/s", "time"),
    "WSC": ("GPS-Corrected Horizontal Wind Speed", "m/s", "time"),
    "INTSPEC_ALL": ("Particle Count Per Interarrival Bin, All Particles", "#", "int2"),
    "INTSPEC_ACCEPTED": ("Particle Count Per Interarrival Bin, Accepted Particles", "#",
                         "int2"),
    "MIDBINS": ("Size Bin Mid-points", "um", "size"),
    "INTMIDBINS": ("Interarrival Bin Mid-points", "s", "int"),
}


# `:256-289` -- (long_name, units) per bulk tag; all on ("Time",) (`:250`).
_BULK: dict[str, tuple[str, str]] = {
    "LWC": ("Liquid Water Content", "gram/m3"),
    "IWC": ("Ice Water Content, All Particles", "gram/m3"),
    "IWC100": ("Ice Water Content, Particles Larger than 100um in Diameter", "gram/m3"),
    "AREA": ("Projected Particle Area, All Particles", "1/m"),
    "AREA100": ("Projected Particle Area, Particles Larger than 100um in Diameter", "1/m"),
    "MVD": ("Median Volume Diameter", "um"),
    "MND": ("Mean Diameter", "um"),
    "NT": ("Total Number Concentration, All Particles", "#/m3"),
    "MVD100": ("Median Volume Diameter, Particles Larger than 100um in Diameter", "um"),
    "MND100": ("Mean Diameter, Particles Larger than 100um in Diameter", "um"),
    "NT100": ("Total Number Concentration, Particles Larger than 100um in Diameter",
              "#/m3"),
}


def sps1_size(rate: Any) -> int:
    """`:19` ``(1.0/data.op.rate)>1``: FLOAT (DOUBLE for a DOUBLE rate),
    truncated to a long dimension size."""
    r = _first(_idl_value(rate))
    if isinstance(r, np.float64):
        q: float = float(np.float64(1.0) / r)
    else:
        q = float(np.float32(1.0) / np.float32(r))
    return int(max(q, 1.0))


def _to_long(x: np.ndarray) -> np.ndarray:
    """``ncdf_varput`` of a float into a LONG variable: truncation toward 0."""
    arr = np.asarray(x)
    if arr.dtype.kind == "f":
        arr = np.trunc(arr)
    return arr.astype(np.int32)


def soda2_export_ncdf_raf(
    data: Any,
    outfile: str,
    *,
    normalize: int = 1,
    suffix: str = "",
    legacybinning: int = 0,
    date_created: str | None = None,
    stamp_profile: str | None = None,
) -> str:
    """``soda2_export_ncdf_raf.pro``. Keywords as IDL's (`:7-9` defaults).
    ``date_created`` overrides ``systime()`` (`:47`, non-deterministic)."""
    import netCDF4

    normalize = int(normalize)
    legacybinning = int(legacybinning)
    tags = _tags(data)
    op: MutableMapping[str, Any] = tags["OP"]
    opl = {str(k).lower(): k for k in op}
    opnames = [str(k).upper() for k in op]

    def opget(name: str) -> Any:
        return op[opl[name]]

    time = np.asarray(tags["TIME"])
    ntimes = int(time.size)
    endbins = _idl_value(opget("endbins"))

    Path(outfile).unlink(missing_ok=True)  # /clobber
    ds = netCDF4.Dataset(outfile, "w", format="NETCDF3_CLASSIC")
    try:
        ds.createDimension("Time", ntimes)  # `:17`
        nsps = sps1_size(opget("rate"))  # `:19`
        ds.createDimension("sps1", nsps)

        def dimdef(n: int, line: str) -> str:
            name = f"Vector{n}"
            if name in ds.dimensions:
                raise DimensionNameInUse(
                    f"soda2_export_ncdf_raf.pro:{line}: NCDF_DIMDEF: (NC_ERROR=-42) -- "
                    f"dimension {name!r} is already defined")
            ds.createDimension(name, n)
            return name

        ne = _n_elements(endbins)
        numbins = ne if legacybinning else ne - 1  # `:21`
        dim_size = dimdef(numbins, "23")
        dim_int = dimdef(_n_elements(tags["INTMIDBINS"]), "26")
        dimdef(_n_elements(opget("arendbins")) - 1, "29")  # defined, never used

        date = soda2_parsedate(str(opget("date")))  # `:34-36`
        days1970 = int(date.julday) - julday(1, 1, 1970)
        flightdate = f"{date.month}/{date.day}/{date.year}"
        starttime = _idl_hms_string(idl_sfm2hms(float(np.min(time))))  # `:38-42`
        stoptime = _idl_hms_string(idl_sfm2hms(float(np.max(time))))

        # `:45-55` -- global attributes.
        ds.setncattr("Source", "SODA-2 OAP Processing Software")
        ds.setncattr("Conventions", "NCAR-RAF/nimbus")
        ds.setncattr("DateCreated", date_created if date_created is not None
                     else _dt.datetime.now().ctime())
        ds.setncattr("FlightDate", flightdate)
        ds.setncattr("DateProcessed", str(tags["DATE_PROCESSED"]))
        ds.setncattr("TimeInterval", f"{starttime}-{stoptime}")
        for key, name in zip(list(op.keys()), opnames, strict=True):
            first = _first(op[key])
            if isinstance(first, str) and first == "":
                # `:53` -- written into the caller's own op (by reference).
                v = op[key]
                if isinstance(v, str):
                    op[key] = "none"
                else:
                    arr = np.asarray(v).astype(object)
                    arr.ravel()[0] = "none"
                    op[key] = arr.astype(str)
                first = "none"
            _put_att(ds, name, first, long_int=False)
        # In-file provenance (author, 2026-09-24) -- not IDL output; see pbp_writer.engine_attrs.
        for name, value in engine_attrs(stamp_profile).items():
            ds.setncattr(name, value)

        # `:57-68` -- the three LONG time variables.
        vt = ds.createVariable("Time", "i4", ("Time",))
        vt.setncattr("long_name", "Time")
        vt.setncattr("units", f"seconds since {date.year}-{date.month}-{date.day} "
                              f"{starttime} +0000")
        vb = ds.createVariable("base_time", "i4", ())
        vb.setncattr("long_name", "Base time")
        vb.setncattr("units", "seconds since 01/01/1970")
        vu = ds.createVariable("utc_time", "i4", ("Time",))
        vu.setncattr("long_name", "UTC time")
        vu.setncattr("units", "seconds from midnight of start date")
        # `:71-73`
        vu[:] = _to_long(time)
        t0 = time.ravel()[0]
        base: Any
        if time.dtype == np.float32:
            base = np.float32(t0) + np.float32(days1970 * 86400)
        elif time.dtype.kind == "f":
            base = np.float64(t0) + np.float64(days1970 * 86400)
        else:
            base = np.int64(t0) + np.int64(days1970 * 86400)
        vb.assignValue(_to_long(np.asarray(base))[()])
        vt[:] = _to_long(time - t0)

        # `:77-237` -- main structure tags.
        ncdims = {"time": ("Time",), "size": (dim_size,), "int": (dim_int,),
                  "int2": ("Time", dim_int), "3d": ("Time", "sps1", dim_size)}
        probetype = str(_first(opget("probetype")))
        for tag in list(tags):
            value = tags[tag]
            tagname = tag + suffix  # `:88`
            atts: list[tuple[str, Any]]
            if tag in _MAIN_SIMPLE:
                ln, un, dkey = _MAIN_SIMPLE[tag]
                atts = [("long_name", ln), ("units", un)]
                current = np.asarray(value)
                if tag in ("SA", "MIDBINS") and legacybinning == 1:
                    # `:94`, `:213` -- [0, data.sa]: INT 0 promoted to the array's type.
                    current = np.concatenate([np.zeros(1, dtype=current.dtype), current])
            elif tag in ("CONC1D", "SPEC1D"):
                dkey = "3d"
                if tag == "CONC1D":  # `:153-188`
                    if legacybinning == 1:
                        note = "CellSizes are upper bin limits as particle size"
                        firstbin = np.int16(1)
                        lastbin = np.int16(_n_elements(tags["MIDBINS"]))
                    else:
                        note = "CellSizes are lower bin limits as particle size"
                        firstbin = np.int16(0)
                        lastbin = np.int16(_n_elements(tags["MIDBINS"]) - 1)
                    if normalize == 1:
                        ln = "Particle Concentration Per Channel, Normalized by Bin Width"
                        un = "#/m4"
                        src = np.asarray(value)
                    elif normalize == 0:
                        ln, un = "Particle Concentration Per Channel", "#/L"
                        un_m3 = unnormalize(np.asarray(value), np.asarray(endbins))
                        src = un_m3 / np.asarray(np.float32(1e3), dtype=un_m3.dtype)  # `:179`
                    else:
                        # IDL: neither branch runs, attvalue stays a 2-string array and
                        # `attvalue.(k)` errors at `:226`.
                        raise ValueError(
                            "soda2_export_ncdf_raf.pro:166-180: normalize must be 0 or 1")
                    atts = [("_FillValue", np.float32(-32767.0)), ("long_name", ln),
                            ("units", un), ("FirstBin", firstbin), ("LastBin", lastbin),
                            ("CellSizes", endbins), ("CellSizeUnits", "micrometers"),
                            ("Category", "PMS Probe"), ("CellSizeNote", note)]
                    tagname = "C" + probetype + suffix  # `:187`
                else:  # `:189-199`
                    src = np.asarray(value)
                    atts = [("_FillValue", np.float32(-32767.0)),
                            ("long_name", "Particle Count Per Size Bin"),
                            ("units", "count"), ("Category", "PMS Probe")]
                    tagname = "A" + probetype + suffix  # `:198`
                # `:184-186` -- fltarr(ntime, numbins), legacy pads bin 0.
                grid = np.zeros((ntimes, numbins), dtype=np.float32)
                if legacybinning:
                    grid[:, 1:] = src
                else:
                    grid[:, :] = src
                current = grid.reshape(ntimes, 1, numbins)
            else:
                continue  # ELSE: skiptag (`:219`)

            # `:222-235`
            fill = None
            if atts[0][0] == "_FillValue":
                fill = atts[0][1]
            if tagname in ds.variables:
                var = ds.variables[tagname]
                if fill is not None:
                    raise FillValueOnExistingVariable(
                        f"soda2_export_ncdf_raf.pro:223-229: {tagname!r} already exists")
            else:
                var = ds.createVariable(tagname, "f4", ncdims[dkey], fill_value=fill)
            for aname, aval in atts:
                if aname == "_FillValue":
                    continue  # set at creation (netCDF4-python's rule)
                # `:226-227` -- an INT attribute goes out /LONG.
                _put_att(var, aname, aval, long_int=True)
            # `:234` currentdata*1.0 into a FLOAT variable.
            arr = np.asarray(current).astype(np.float32)
            if dkey == "3d":
                var[:, 0:1, :] = arr
            else:
                var[:] = arr
        # `:84` resets attname on every main-loop pass (skipped tags too), so
        # the bulk loop below inherits the LAST tag's list.
        last_tag = list(tags)[-1] if tags else ""

        # `:239-245` -- bulk structure: compute_bulk_simple's tags, then the
        # 100-um subset and the two areas, in create_struct order.
        eb = np.asarray(endbins, dtype=np.float32)
        conc1d = tags["CONC1D"]
        bulkall = compute_bulk_simple(conc1d, eb, binstart=0)  # `:240`
        i100 = _min_where_ge(eb, 100)  # `:241`
        nb = len(eb) - 1
        if i100 < 0 or i100 > nb - 1:
            raise MinsizeBinstartOutOfRange(
                f"soda2_export_ncdf_raf.pro:242: binstart={i100} for {nb} bins "
                f"(endbins up to {float(eb[-1])}) -- compute_bulk_simple halts")
        bulk100 = compute_bulk_simple(conc1d, eb, binstart=i100)  # `:242`
        area = compute_area(tags)  # `:243`
        area100 = compute_area(tags, binstart=i100)  # `:244`
        bulk: dict[str, Any] = {k.upper(): v for k, v in bulkall.items()}
        bulk.update({"NT100": bulk100["nt"], "MND100": bulk100["mnd"],
                     "MVD100": bulk100["mvd"], "IWC100": bulk100["iwc"],
                     "AREA": area["area"], "AREA100": area100["area"]})

        if last_tag in ("CONC1D", "SPEC1D"):
            raise BulkAttnameCarryOver(
                f"soda2_export_ncdf_raf.pro:296-301: the last data tag is {last_tag!r}, "
                "so attname has more entries than the bulk attvalue's two fields")

        # `:247-308`
        for tag, value in bulk.items():
            if tag not in _BULK:
                continue  # ELSE: skiptag (`:290`)
            tagname = tag + suffix  # `:254`
            ln, un = _BULK[tag]
            if tagname in ds.variables:  # `:294`
                var = ds.variables[tagname]
            else:
                var = ds.createVariable(tagname, "f4", ("Time",))  # `:295`
            var.setncattr("long_name", ln)  # `:296-302`
            var.setncattr("units", un)
            var[:] = np.asarray(value).astype(np.float32)  # `:305` currentdata*1.0
    finally:
        ds.close()  # `:311`
    return str(outfile)
