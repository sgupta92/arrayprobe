# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_export_ncdf.pro`` (462 lines) -- SODA-2's own netCDF
size-distribution export, ported bug-for-bug.

Vendored source, read whole: ``SODA2/abansemer-soda2-afcea15/
soda2_export_ncdf.pro``, plus ``compute_area.pro`` (40) and
``compute_meanar.pro`` (22), which only this export calls. The bulk
properties reuse Y1's :func:`arrayprobe_soda2.export_ascii.compute_bulk_simple`
(and through it ``mmdiam``/``mvdiam``/``meandiam``/``unnormalize``);
``sfm2hms`` and the ``/REVERSE_OFFSET`` ``HH:MM:SS`` builder reuse
:mod:`arrayprobe_soda2.pbp_writer`; ``soda2_parsedate``/``julday`` reuse
:mod:`arrayprobe_soda2.timeconv`. Oracle: ``gdl_oracle/
run_soda2_export_ncdf_bank.py`` (unmodified ``.pro`` under GDL), golden
``tests/data/gdl_soda2_export_ncdf_golden.json``.

**Who calls it.** Not the driver: ``soda2_process_2d.pro`` never calls this
routine (its only exports are the PBP files, ``:688-718``, and
``soda2_export_ascii``, ``:722-726``). The one caller in the vendored tree is
the GUI, ``soda2_export.pro:39-44``: ``restore`` a ``.dat`` SAVE file, then
``soda2_export_ncdf, data, outfile=outdir + <basename>.nc``. So the port's
input is the ``data`` structure that SAVE file holds -- which is
:class:`arrayprobe_soda2.process_2d.ProcessData`, field for field
(``soda2_process_2d.pro:678-687``) -- and there is no driver call site to
wire.

**Format.** ``ncdf_create(outfile, /clobber)`` (`:15`) with no
``/NETCDF4_FORMAT`` keyword is a classic netCDF-3 file: ``NETCDF3_CLASSIC``,
no compression, fixed-size ``Time`` dimension.

**Reading of IDL semantics the port reproduces (each pinned by a bank case):**

- ``data`` is a positional argument, hence by reference: `:22`'s
  ``data = create_struct(data, 'endbins', ...)`` replaces the *caller's*
  variable with one carrying a new ``ENDBINS`` tag, and `:69` writes
  ``'none'`` into the caller's own ``op`` for every empty-string field. The
  port reproduces the second on the caller's ``op`` dict and the first on a
  caller ``dict`` (a :class:`ProcessData` has no slot to add, so there it is
  the returned file, not the object, that carries it).
- Every ``op`` field becomes a global attribute holding only its **first
  element** (`:70`, ``data.op.(i)[0]``), in the field's own IDL type.
- Every variable is ``/float`` (`:177`, `:377`), whatever the tag's type.
- IDL lists dimensions fastest-first, so ``[xdimid, ydimid]`` is the
  netCDF variable ``(Vector<n>, Time)``; the port writes ``arr.T`` for a
  ``[ntimes, nbins]`` array. Never hand-rolled elsewhere -- here only.
- An attribute value whose IDL type is INT (``size(/TYPE) eq 2``) is
  written ``/LONG`` (NC_INT) (`:179-180`); a global attribute is not
  (`:70`), so an INT ``op`` field is NC_SHORT.
- `:160` tests ``'INTENDDBINS'`` (double D), so ``INTENDBINS`` never matches
  and falls to ``ELSE``: its dimension is defined (`:40-43`) but no
  variable is ever written on it. Reproduced.

**Refused by name** (not reached by any caller in the vendored tree):
``pthfile`` (`:392-457`, ``restore`` of an IDL SAVE into the local ``data``
-- :class:`PthfileNotPorted`); ``noskip=1`` on a non-numeric tag whose
element count equals ``n_elements(data.time)`` (`:167-170` would
``ncdf_varput`` a string or structure -- :class:`NoskipNonNumericNotPorted`).

Imports nothing from ``arrayprobe``/``arrayprobe_uiops``.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import numpy as np

from .export_ascii import compute_bulk_simple
from .pbp_writer import _idl_hms_string, engine_attrs, sfm2hms
from .pth_readers import pth_suffix
from .spec_index import julday
from .timeconv import soda2_parsedate

__all__ = [
    "DimensionNameInUse",
    "MinsizeBinstartOutOfRange",
    "NoskipNonNumericNotPorted",
    "PthfileNotPorted",
    "compute_area",
    "compute_meanar",
    "idl_sfm2hms",
    "soda2_export_ncdf",
    "write_run_psd",
]


class PthfileNotPorted(NotImplementedError):
    """``soda2_export_ncdf.pro:392-457`` -- ``pthfile`` makes the routine
    ``restore`` an IDL SAVE file into its own local ``data`` (and so, by
    reference, into the caller's). No caller in the vendored tree passes it
    (``soda2_export.pro:43`` does not)."""


class NoskipNonNumericNotPorted(NotImplementedError):
    """``soda2_export_ncdf.pro:167-170`` with ``noskip=1`` on a tag that is a
    string or structure but has ``n_elements(data.time)`` elements: IDL would
    multiply it by ``1.0`` and ``ncdf_varput`` it. Not ported."""


class DimensionNameInUse(RuntimeError):
    """``soda2_export_ncdf.pro:30-42`` names every bin dimension
    ``'Vector'+n_elements(...)``, so two different axes of the same length
    get the same name. The driver's interarrival axis has 40 midbins and 41
    endbins (``soda2_process_2d.pro:53-57``), so a size axis of 39, 40 or 41
    bins collides: measured under GDL (case ``vector_collision``),
    ``NCDF_DIMDEF: (NC_ERROR=-42)`` halts at `:38` with the file open."""


class MinsizeBinstartOutOfRange(IndexError):
    """``soda2_export_ncdf.pro:195-202`` -- ``i100``/``i200``/``i1000`` is
    ``min(where(data.op.endbins ge N))``: ``-1`` when no edge reaches ``N``,
    and equal to ``numbins`` when only the *last* edge does. Either way
    ``compute_bulk_simple`` cannot run: the ``-1`` case halts three frames
    down in ``mmdiam.pro:12`` (``fltarr(0)``, the same halt measured for
    ``soda2_export_ascii``'s ``minsize_above_bins``; SODA-2 register entry S7-b), the
    ``numbins`` case on a ``[binstart:binstop]`` subscript with
    ``low > high``. The port raises here, before calling it; the bank pins
    that GDL halts too."""


# ---------------------------------------------------------------------------
# Call tree not already ported
# ---------------------------------------------------------------------------

def idl_sfm2hms(sfm: float) -> int:
    """``sfm2hms.pro`` exactly: ``long(sfm)``, then ``10000*hour +
    100*minute + sec`` with **no** wrap at 86400 s -- 86401 s is
    ``240001``. This name delegates to :func:`arrayprobe_soda2.pbp_writer.sfm2hms`, so the two
    cannot drift apart. `:56-57` feed it
    ``min``/``max(data.time)``, which do cross midnight (bank case
    ``past_midnight``; ``run_soda2_sfm2hms_bank.py``)."""
    return sfm2hms(sfm)


def _idl_total_nan(x: np.ndarray) -> np.float32:
    """IDL ``total(x, /nan)`` on a FLOAT array: a sequential single-precision
    sum in IDL's memory order (first index fastest), NaN skipped.
    ``numpy.nansum`` sums pairwise in C order and differs by an ULP (bank
    cases ``full_driver_shape``/``precip_full``, ``AREA``/``AREA200``)."""
    flat = np.asarray(x, dtype=np.float32).ravel(order="F")
    flat = flat[~np.isnan(flat)]
    return np.cumsum(flat, dtype=np.float32)[-1] if flat.size else np.float32(0.0)


def compute_meanar(spec2d: np.ndarray, armidbins: np.ndarray) -> np.ndarray:
    """``compute_meanar.pro`` (22 lines). ``spec2d`` ``[ntimes, nbins,
    narbins]``; returns FLOAT ``[ntimes, nbins]``, 0 where a size bin holds
    nothing."""
    s = np.asarray(spec2d, dtype=np.float32)
    ar = np.asarray(armidbins, dtype=np.float32)
    meanar = np.zeros(s.shape[:2], dtype=np.float32)
    for i in range(s.shape[0]):
        for j in range(s.shape[1]):
            tot = _idl_total_nan(s[i, j, :])
            if tot > 0:
                meanar[i, j] = _idl_total_nan(s[i, j, :] * ar) / tot
    return meanar


def compute_area(data: Mapping[str, Any], binstart: int = 0) -> dict[str, np.ndarray]:
    """``compute_area.pro`` (40 lines). ``data`` is the upper-cased tag
    mapping :func:`soda2_export_ncdf` builds. Returns ``area`` (FLOAT
    ``[ntimes]``, 1/m) and ``asd`` (FLOAT ``[ntimes, nbins]``)."""
    op = {str(k).lower(): v for k, v in data["OP"].items()}
    spec2d = np.asarray(data["SPEC2D"], dtype=np.float32)
    ntimes, nbins_s, narbins = spec2d.shape
    area = np.zeros(ntimes, dtype=np.float32)
    endbins = np.asarray(op["endbins"], dtype=np.float32)
    numbins = len(endbins) - 1
    midbins = (endbins[0:numbins] + endbins[1:numbins + 1]) / np.float32(2.0)
    arend = np.asarray(_idl_value(op["arendbins"]))
    armidbins = (arend[:-1] + arend[1:]) / 2.0  # the op field's own type
    pi = np.float32(np.pi)
    sa = np.asarray(data["SA"], dtype=np.float32)
    agrid = np.zeros((nbins_s, narbins), dtype=np.float32)
    sagrid = np.zeros((nbins_s, narbins), dtype=np.float32)
    for i in range(nbins_s):
        agrid[i, :] = pi / np.float32(4) * (midbins[i] / np.float32(1.0e6)) ** 2 * armidbins
        sagrid[i, :] = sa[i]
    asd = np.zeros((ntimes, nbins_s), dtype=np.float32)
    tas = np.asarray(data["TAS"])
    act = np.asarray(data["ACTIVETIME"])
    for i in range(ntimes):
        svgrid = sagrid * tas[i] * act[i]  # IDL promotion: FLOAT unless tas is DOUBLE
        if tas[i] > 0:
            with np.errstate(divide="ignore", invalid="ignore"):
                fullgrid = agrid[binstart:, :] * spec2d[i, binstart:, :] / svgrid[binstart:, :]
            for j in range(fullgrid.shape[0]):
                asd[i, binstart + j] = _idl_total_nan(fullgrid[j, :])
            area[i] = _idl_total_nan(fullgrid)
    return {"area": area, "asd": asd}


# ---------------------------------------------------------------------------
# IDL -> netCDF typing
# ---------------------------------------------------------------------------

def _idl_value(value: Any) -> Any:
    """A Python value as the IDL type it stands for. numpy values keep their
    dtype (the caller's own IDL type, as ``pbp_writer``'s B5 convention);
    a Python ``int`` is an IDL integer literal (INT if it fits, else LONG);
    a Python ``float`` is DOUBLE; ``str`` stays a string."""
    if isinstance(value, str | np.str_):
        return str(value)
    if isinstance(value, bool | np.bool_):
        return np.int16(value)
    if isinstance(value, int):
        return np.int16(value) if -32768 <= value <= 32767 else np.int32(value)
    if isinstance(value, float):
        return np.float64(value)
    arr = np.asarray(value)
    if arr.dtype.kind in "US":
        return arr.astype(str)
    if arr.dtype == np.int64:
        # A list of Python ints: an IDL array literal of INT/LONG.
        return arr.astype(np.int16 if np.all(np.abs(arr) <= 32767) else np.int32)
    return arr


def _first(value: Any) -> Any:
    """IDL ``v[0]`` on a scalar or an array."""
    v = _idl_value(value)
    if isinstance(v, str):
        return v
    arr = np.asarray(v)
    return arr.ravel()[0] if arr.ndim else arr[()]


def _put_att(target: Any, name: str, value: Any, *, long_int: bool) -> None:
    """``ncdf_attput``: strings as NC_CHAR; numbers in their own type, INT
    raised to NC_INT when the call carries ``/LONG`` (`:179-180`)."""
    v = _idl_value(value)
    if isinstance(v, str):
        target.setncattr(name, v)
        return
    arr = np.asarray(v)
    if arr.dtype.kind == "U":
        target.setncattr(name, str(arr.ravel()[0]))
        return
    if long_int and arr.dtype == np.int16:
        arr = arr.astype(np.int32)
    target.setncattr(name, arr if arr.ndim else arr[()])


# ---------------------------------------------------------------------------
# Per-tag tables (`:104-172`, `:248-372`)
# ---------------------------------------------------------------------------

_MAIN_SIMPLE = {
    "SA": ("Sample Area", "m2", "size"),
    "COUNT_ACCEPTED": ("Count Accepted", "#", "time"),
    "TAS": ("True Air speed used", "m/s", "time"),
    "ACTIVETIME": ("Probe activity time", "s", "time"),
    "MIDBINS": ("Size Bin Mid-points", "micrometers", "size"),
    "ENDBINS": ("Size Bin End-points", "micrometers", "sizeend"),
    "INTMIDBINS": ("Interarrival Bin Mid-points", "s", "int"),
    # `:160` spells it 'INTENDDBINS', so the real INTENDBINS tag never matches.
    "INTENDDBINS": ("Interarrival Bin End-points", "s", "intend"),
}

_BULK_SIMPLE: dict[str, tuple[str, str]] = {
    "AREA": ("Projected Particle Area, All Particles", "1/m"),
    "AREA100": ("Projected Particle Area, Particles Larger than 100um in Diameter", "1/m"),
    "AREA200": ("Projected Particle Area, Particles Larger than 200um in Diameter", "1/m"),
    "AREA1000": ("Projected Particle Area, Particles Larger than 1000um in Diameter", "1/m"),
    "MVD": ("Median Volume Diameter, All Particles", "micrometers"),
    "MND": ("Mean Diameter, All Particles", "micrometers"),
    "DMASS": ("Mass-weighted Diameter, All Particles", "micrometers"),
    "NT": ("Total Number Concentration, All Particles", "#/m3"),
}
for _n in ("100", "200", "1000"):
    _gt = f"Particles Larger than {_n}um in Diameter"
    _BULK_SIMPLE[f"MVD{_n}"] = (f"Median Volume Diameter, {_gt}", "micrometers")
    _BULK_SIMPLE[f"MND{_n}"] = (f"Mean Diameter, {_gt}", "micrometers")
    _BULK_SIMPLE[f"DMASS{_n}"] = (f"Mass-weighted Diameter, {_gt}", "micrometers")
    _BULK_SIMPLE[f"NT{_n}"] = (f"Total Number Concentration, {_gt}", "#/m3")

_LWC = {"LWC": "Liquid Water Content"}
_IWC = {"IWC": "Ice Water Content"}
for _n in ("100", "200", "1000"):
    _LWC[f"LWC{_n}"] = f"Liquid Water Content, Particles Larger than {_n}um in Diameter"
    _IWC[f"IWC{_n}"] = f"Ice Water Content, Particles Larger than {_n}um in Diameter"


def _tags(data: Any) -> dict[str, Any]:
    """``tag_names(data)`` with values, in declaration order, upper-cased.
    A :class:`ProcessData` contributes its IDL fields only (``pbp_csv_path``
    is port tooling, not a ``data`` tag)."""
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        return {f.name.upper(): getattr(data, f.name) for f in dataclasses.fields(data)
                if f.name != "pbp_csv_path"}
    return {str(k).upper(): v for k, v in data.items()}


def _n_elements(v: Any) -> int:
    if isinstance(v, str):
        return 1
    if dataclasses.is_dataclass(v) or isinstance(v, Mapping):
        return 1
    return int(np.asarray(v).size)


def _is_numeric(v: Any) -> bool:
    if isinstance(v, str) or dataclasses.is_dataclass(v) or isinstance(v, Mapping):
        return False
    return np.asarray(v).dtype.kind in "biuf"


def _min_where_ge(endbins: np.ndarray, threshold: float) -> int:
    idx = np.nonzero(endbins >= threshold)[0]
    return int(idx.min()) if idx.size else -1


def _bulk_checked(conc1d: np.ndarray, endbins: np.ndarray, binstart: int,
                  line: str) -> dict[str, np.ndarray]:
    numbins = len(endbins) - 1
    if binstart < 0 or binstart > numbins - 1:
        raise MinsizeBinstartOutOfRange(
            f"soda2_export_ncdf.pro:{line}: binstart={binstart} for {numbins} bins "
            f"(endbins up to {float(endbins[-1])}) -- compute_bulk_simple halts")
    return compute_bulk_simple(conc1d, endbins, binstart=binstart)


# ---------------------------------------------------------------------------
# soda2_export_ncdf
# ---------------------------------------------------------------------------

#: The airspeed record's convention, written as ``arrayprobe_tas_qc_convention``.
TAS_QC_CONVENTION = "arrayprobe-soda2-tas-qc/1"

#: The ``op.pth`` suffixes ``soda2_process_2d.pro:128-172`` reads (``process_2d.py``'s branch);
#: any other suffix leaves ``got_pth = 0`` and the probe's own airspeed is used.
_PTH_SUFFIXES = ("dat", "sav", "txt", "csv", "nc")


def _hms_ranges(seconds: list[int]) -> str:
    """Consecutive seconds-from-midnight as ``HHMMSS-HHMMSS`` runs, comma-separated."""
    runs: list[tuple[int, int]] = []
    for s in sorted(set(seconds)):
        if runs and s == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], s)
        else:
            runs.append((s, s))
    return ", ".join(f"{idl_sfm2hms(a):06d}" if a == b
                     else f"{idl_sfm2hms(a):06d}-{idl_sfm2hms(b):06d}" for a, b in runs)


def tas_qc_attrs(tags: Mapping[str, Any], op: Mapping[str, Any]) -> dict[str, Any]:
    """The airspeed data-quality record for one SODA-2 export, as global attributes.

    Not IDL output: written beside ``arrayprobe_engine``/``arrayprobe_profile`` so the file says
    where its airspeed came from, and which seconds had none. A second whose ``TAS`` is not
    positive gets no concentration (``process_2d.py:1095`` leaves ``conc1d`` at 0), so those
    zeros are missing data, not clear air. No variable changes.
    """
    opl = {str(k).lower(): v for k, v in op.items()}
    pth = str(_first(opl.get("pth", "")) or "")
    fixed = float(_first(opl.get("fixedtas", 0.0)) or 0.0)
    # Case-sensitive, as process_2d's own suffix test is: a ``.CSV`` is not read.
    suffix = pth_suffix(pth)
    if pth and pth != "none" and suffix in _PTH_SUFFIXES:
        source = f"pth file ({suffix})"
    elif pth and pth != "none":
        source = f"probe (op.pth suffix {suffix or 'none'!r} is not read)"
    elif fixed > 0:
        source = f"fixedtas {fixed:g} m/s (a constant, not a measurement)"
    else:
        source = "probe"
    time = np.asarray(tags["TIME"], dtype=np.float64).ravel()
    tas = np.asarray(tags["TAS"], dtype=np.float64).ravel()
    bad = ~(np.isfinite(tas) & (tas > 0))
    missing = [int(t) for t in time[bad]]
    n, total = len(missing), int(time.size)
    return {
        "arrayprobe_tas_qc_convention": TAS_QC_CONVENTION,
        "arrayprobe_tas_source": source,
        "arrayprobe_tas_seconds_total": total,
        "arrayprobe_tas_nonpositive_count": n,
        "arrayprobe_tas_nonpositive_ranges": _hms_ranges(missing) if n else "none",
        "arrayprobe_tas_uncertainty": (
            f"{n} of {total} seconds had no positive airspeed; their concentrations are 0 "
            "because no sample volume could be formed, not because no particle was seen."
            if n else "every second had a positive airspeed"),
    }


def soda2_export_ncdf(
    data: Any,
    outfile: str,
    *,
    pthfile: str | None = None,
    lite: int = 0,
    noskip: int = 0,
    date_created: str | None = None,
    stamp_profile: str | None = None,
) -> str:
    """``soda2_export_ncdf.pro`` (462 lines). ``data`` is a
    :class:`~arrayprobe_soda2.process_2d.ProcessData` or a mapping of IDL
    tag name to value in IDL declaration order; ``data['op']``/``data.op``
    is a mapping of ``op`` field to value, types as :func:`_idl_value`
    reads them. ``[ntimes, nbins]`` arrays are row-per-time, as
    ``ProcessData`` holds them. ``date_created`` overrides ``systime()``
    (`:64`, non-deterministic) for tests. Returns ``outfile``."""
    import netCDF4

    if pthfile is not None:
        raise PthfileNotPorted(
            "soda2_export_ncdf.pro:392-457: pthfile (restore of an IDL SAVE) is not ported")
    lite = int(lite)
    noskip = int(noskip)

    tags = _tags(data)
    op: MutableMapping[str, Any] = tags["OP"]
    opl = {str(k).lower(): k for k in op}  # lower-case -> the caller's own key
    opnames = [str(k).upper() for k in op]

    def opget(name: str) -> Any:
        return op[opl[name]]

    time = np.asarray(tags["TIME"])
    ntimes = int(time.size)

    # `:21-24` -- the caller's `data` gains an ENDBINS tag (by reference).
    if "ENDBINS" in opnames and "ENDBINS" not in tags:
        tags["ENDBINS"] = opget("endbins")
        if isinstance(data, MutableMapping) and not dataclasses.is_dataclass(data):
            data["endbins"] = opget("endbins")

    Path(outfile).unlink(missing_ok=True)  # /clobber
    ds = netCDF4.Dataset(outfile, "w", format="NETCDF3_CLASSIC")
    try:
        ds.createDimension("Time", ntimes)  # `:27`
        dimname: dict[str, str] = {"time": "Time"}

        def dimdef(key: str, n: int, line: str) -> None:
            name = f"Vector{n}"
            if name in ds.dimensions:
                raise DimensionNameInUse(
                    f"soda2_export_ncdf.pro:{line}: NCDF_DIMDEF: (NC_ERROR=-42) -- "
                    f"dimension {name!r} is already defined")
            dimname[key] = name
            ds.createDimension(name, n)

        if "ENDBINS" in opnames:  # `:28-34`
            ne = _n_elements(opget("endbins"))
            dimdef("size", ne - 1, "31")
            dimdef("sizeend", ne, "33")
        if "INTMIDBINS" in tags:  # `:36-39`
            dimdef("int", _n_elements(tags["INTMIDBINS"]), "38")
        if "INTENDBINS" in tags:  # `:40-43`
            dimdef("intend", _n_elements(tags["INTENDBINS"]), "42")
        if "ARENDBINS" in tags:  # `:45-48` (tests `tags`, reads `data.op`)
            dimdef("ar", _n_elements(opget("arendbins")) - 1, "47")

        date = soda2_parsedate(str(opget("date")))
        days1970 = int(date.julday) - julday(1, 1, 1970)  # `:53`
        flightdate = f"{date.month}/{date.day}/{date.year}"
        starttime = _idl_hms_string(idl_sfm2hms(float(np.min(time))))
        stoptime = _idl_hms_string(idl_sfm2hms(float(np.max(time))))

        # `:63-71` -- global attributes.
        ds.setncattr("Source", "SODA-2 OAP Processing Software")
        ds.setncattr("DateCreated", date_created if date_created is not None
                     else _dt.datetime.now().ctime())
        ds.setncattr("FlightDate", flightdate)
        if "DATE_PROCESSED" in tags:
            ds.setncattr("DateProcessed", str(tags["DATE_PROCESSED"]))
        ds.setncattr("TimeInterval", f"{starttime}-{stoptime}")
        for key, name in zip(list(op.keys()), opnames, strict=True):
            first = _first(op[key])
            if isinstance(first, str) and first == "":
                # `:69` -- written into the caller's own op (by reference).
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
        for name, value in tas_qc_attrs(tags, op).items():
            ds.setncattr(name, value)

        # `:74-91` -- the three time variables.
        v = ds.createVariable("elapsed_time", "f8", ("Time",))
        v.setncattr("long_name", "Elapsed time")
        v.setncattr("units", f"seconds since {date.year}-{date.month}-{date.day} {starttime} +0000")
        vb = ds.createVariable("base_time", "f8", ())
        vb.setncattr("long_name", "Base time")
        vb.setncattr("units", "seconds since 01/01/1970")
        vt = ds.createVariable("time", "f8", ("Time",))
        vt.setncattr("long_name", "Time")
        vt.setncattr("units", "seconds from midnight of start date")
        vt[:] = time
        # `:89` data.time[0] + LONG: IDL keeps a FLOAT time FLOAT (a DOUBLE
        # one DOUBLE), so a FLOAT data.time loses the seconds of base_time.
        t0 = time.ravel()[0]
        base: np.floating[Any]
        if time.dtype == np.float32:
            base = np.float32(t0) + np.float32(days1970 * 86400)
        else:
            base = np.float64(t0) + np.float64(days1970 * 86400)
        vb.assignValue(base)
        v[:] = time - time.ravel()[0]

        def write_var(tagname: str, dims: tuple[str, ...], atts: list[tuple[str, Any]],
                      value: Any) -> None:
            # `:176-188`: reuse a same-named variable if one exists.
            ncdims = tuple(dimname[d] for d in reversed(dims))
            var = ds.variables[tagname] if tagname in ds.variables else \
                ds.createVariable(tagname, "f4", ncdims)
            for aname, aval in atts:
                _put_att(var, aname, aval, long_int=True)
            # `:187` currentdata*1.0 then ncdf_varput into a FLOAT variable:
            # every input type lands as float32 (round-to-nearest).
            arr = np.asarray(value).astype(np.float32)
            var[:] = np.ascontiguousarray(arr.T) if arr.ndim == 2 else arr

        endbins_raw = _idl_value(opget("endbins")) if "endbins" in opl else None

        def bin_atts(long_name: str, units: str, *,
                     parameterization: str | None = None) -> list[tuple[str, Any]]:
            eb = np.asarray(endbins_raw)
            binwidth = eb[1:] - eb[:-1]
            out: list[tuple[str, Any]] = [("long_name", long_name), ("units", units)]
            if parameterization is not None:
                out.append(("parameterization", parameterization))
            out.append(("Bin_midpoints", _idl_value(tags["MIDBINS"])))
            out.append(("Bin_endpoints", eb))
            out.append(("Bin_width", binwidth))
            out.append(("Bin_units", "micrometers"))
            return out

        # `:94-190` -- main structure tags.
        dims: tuple[str, ...]
        for tag, value in list(tags.items()):
            if tag in _MAIN_SIMPLE:
                ln, un, dim = _MAIN_SIMPLE[tag]
                dims = (dim,)
                if lite == 1 and len(dims) > 1:
                    continue
                write_var(tag, dims, [("long_name", ln), ("units", un)], value)
            elif tag in ("CONC1D", "SPEC1D"):
                if lite == 1:
                    continue
                if tag == "CONC1D":
                    atts = bin_atts("Particle Concentration Per Size Bin, "
                                    "Normalized by Bin Width", "#/m4")
                    name = "CONCENTRATION"
                else:
                    atts = bin_atts("Particle Count Per Size Bin", "#")
                    name = "COUNTS"
                write_var(name, ("time", "size"), atts, value)
            elif tag in ("INTSPEC_ALL", "INTSPEC_ACCEPTED"):
                if lite == 1:
                    continue
                ieb = _idl_value(tags["INTENDBINS"])
                which = "All Particles" if tag == "INTSPEC_ALL" else "Accepted Particles"
                atts = [("long_name", f"Particle Count Per Interarrival Bin, {which}"),
                        ("units", "#"), ("Bin_endpoints", ieb),
                        ("Bin_width", np.asarray(ieb)[1:] - np.asarray(ieb)[:-1]),
                        ("Bin_units", "seconds")]
                write_var(tag, ("time", "int"), atts, value)
            else:  # ELSE, `:164-171`
                if noskip == 1 and _n_elements(value) == ntimes and tag != "TIME":
                    if not _is_numeric(value):
                        raise NoskipNonNumericNotPorted(
                            f"soda2_export_ncdf.pro:167-170: noskip on non-numeric tag {tag}")
                    write_var(tag, ("time",),
                              [("long_name", "Unknown"), ("units", "Unknown")], value)

        # `:193-235` -- bulk properties.
        if "ENDBINS" in opnames and float(np.max(np.asarray(opget("endbins")))) > 100:
            conc1d = tags["CONC1D"]
            eb = np.asarray(opget("endbins"), dtype=np.float32)
            bulkall = compute_bulk_simple(conc1d, eb, binstart=0)
            i100 = _min_where_ge(eb, 100)
            bulk100 = _bulk_checked(conc1d, eb, i100, "195-196")
            i200 = _min_where_ge(eb, 200)
            bulk200 = _bulk_checked(conc1d, eb, i200, "197-198")
            got_precip = 0
            if str(opget("probetype")) != "MERGED" and float(_first(opget("res"))) >= 100:
                got_precip = 1
                i1000 = _min_where_ge(eb, 1000)
                bulk1000 = _bulk_checked(conc1d, eb, i1000, "201-202")
            bulk: dict[str, Any] = {k.upper(): v for k, v in bulkall.items()}
            if "SPEC2D_ASPR" in tags:
                arend = np.asarray(_idl_value(opget("arendbins")))
                armid = (arend[:-1] + arend[1:]) / 2.0  # `:205`
                meanar = compute_meanar(tags["SPEC2D"], armid)
                meanaspr = compute_meanar(tags["SPEC2D_ASPR"], armid)
                area = compute_area(tags)
                bulk.update({"AREA": area["area"], "MEANAR": meanar,
                             "MEANASPR": meanaspr, "ASD": area["asd"]})
                if got_precip == 0:
                    area100 = compute_area(tags, binstart=i100)
                    area200 = compute_area(tags, binstart=i200)
                    for n, b, a in (("100", bulk100, area100), ("200", bulk200, area200)):
                        bulk.update({f"NT{n}": b["nt"], f"MND{n}": b["mnd"], f"MVD{n}": b["mvd"],
                                     f"DMASS{n}": b["dmass"], f"IWC{n}": b["iwc"],
                                     f"AREA{n}": a["area"], f"LWC{n}": b["lwc"]})
                else:
                    area1000 = compute_area(tags, binstart=i1000)
                    bulk.update({"NT1000": bulk1000["nt"], "MND1000": bulk1000["mnd"],
                                 "MVD1000": bulk1000["mvd"], "DMASS1000": bulk1000["dmass"],
                                 "IWC1000": bulk1000["iwc"], "AREA1000": area1000["area"],
                                 "LWC1000": bulk1000["lwc"]})
            else:
                parts = ((("100", bulk100), ("200", bulk200)) if got_precip == 0
                         else (("1000", bulk1000),))
                for n, b in parts:
                    bulk.update({f"NT{n}": b["nt"], f"MND{n}": b["mnd"], f"MVD{n}": b["mvd"],
                                 f"DMASS{n}": b["dmass"], f"IWC{n}": b["iwc"], f"LWC{n}": b["lwc"]})
        else:
            bulk = dict(tags)  # `:235` -- CDP/FSSP: bulk variables already in data

        water = int(_first(opget("water")))
        for tag, value in bulk.items():  # `:238-390`
            dims = ("time",)
            if tag in _LWC:
                if water == 0:
                    continue
                atts = [("long_name", _LWC[tag]), ("units", "gram/m3")]
                name = tag
            elif tag in _IWC:
                atts = [("long_name", _IWC[tag]), ("units", "gram/m3"),
                        ("parameterization", "Brown and Francis 1995")]
                name = tag
            elif tag in _BULK_SIMPLE:
                ln, un = _BULK_SIMPLE[tag]
                atts = [("long_name", ln), ("units", un)]
                name = tag
            elif tag in ("MEANAR", "MEANASPR"):
                word = "Area" if tag == "MEANAR" else "Aspect"
                atts = [("long_name", f"Mean {word} Ratio Per Size Bin"), ("units", "unitless"),
                        ("Bin_midpoints", _idl_value(tags["MIDBINS"])),
                        ("Bin_endpoints", np.asarray(endbins_raw)),
                        ("Bin_units", "micrometers")]
                dims = ("time", "size")
                name = "MEAN_AREARATIO" if tag == "MEANAR" else "MEAN_ASPECTRATIO"
            elif tag == "ASD":
                atts = bin_atts("Projected Area Per Size Bin, Not Normalized by Bin Width", "1/m")
                dims = ("time", "size")
                name = "ASD"
            elif tag == "MSD":
                atts = bin_atts("Calculated Mass Per Size Bin, Not Normalized by Bin Width", "g/m3",
                                parameterization="Brown and Francis 1995")
                dims = ("time", "size")
                name = "MSD"
            else:
                continue
            if lite == 1 and len(dims) > 1:
                continue
            write_var(name, dims, atts, value)
    finally:
        ds.close()
    return str(outfile)


def write_run_psd(data: Any, *, outdir: str | None = None,
                  date_created: str | None = None) -> str:
    """Write the size-distribution netCDF ``<stem>.nc`` of a finished run.

    ``data`` is the :class:`~arrayprobe_soda2.process_2d.ProcessData` that
    ``soda2_process_2d`` returns, the struct the IDL driver saves at
    ``soda2_process_2d.pro:729-731``. The file is :func:`soda2_export_ncdf`
    on that struct, unchanged, named as ``soda2_filename.pro`` names the
    SAVE file with ``.nc`` for ``.dat`` -- the PSD file NCAR's pipeline makes
    by restoring the SAVE file and calling ``soda2_export_ncdf, data``.
    ``outdir`` defaults to ``op.outdir``. Returns the path written."""
    from .pbp_writer import pbp_filename

    op = _tags(data)["OP"]
    lower = {str(k).lower(): v for k, v in op.items()}
    outfile = pbp_filename(op, str(lower["shortname"]), extension=".nc", outdir=outdir)
    return soda2_export_ncdf(data, outfile, date_created=date_created)
