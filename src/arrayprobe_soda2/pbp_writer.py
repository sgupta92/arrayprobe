# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_process_2d.pro`` PBP writers.

Ports the two on-path per-particle-file writers that ``soda2_process_2d.pro``
opens before the buffer loop and closes after it: the ASCII/CSV file (W3,
gated by ``op.particlefile eq 1``) and the per-particle netCDF-4 file (W2,
gated by ``op.ncdfparticlefile ge 1``). The IDL SAVE file (W1,
``save_writer.save_process_data``) and the ASCII PSD export (W4,
``export_ascii.soda2_export_ascii``) are ported in their own modules and called
from ``process_2d``, not here.

Provenance: ``SODA2/abansemer-soda2-afcea15/soda2_process_2d.pro`` lines
190-354 (setup) and 696-731 (tail); ``soda2_particlesort.pro`` lines 186-298
(per-buffer body); ``soda2_filename.pro`` (whole file, 24 lines).
Copyright (C) 2016 UCAR, 3-clause BSD.

Imports nothing from ``arrayprobe``/``arrayprobe_uiops`` (separate port,
own oracle discipline, like every other ``arrayprobe_soda2`` module).

**Functions consumed as plain arguments, not a driver object**:
lane A's driver calls these at three points -- header before the buffer
loop, body per buffer, close after the concentration block. See
``run_with_writers`` below for the three call sites, named for the merge.

**Scope:**
- ``op.ncdfparticlefile == 2`` (particle images: ``:286-306``, ``:264-276``)
  -- ported on the serial path (the SODA-2 particle-image output; a GDL golden is pending);
  the parallel driver raises :class:`PbpImagesNotPorted`, and so does an image
  chunk of fewer than two slices (``:275``, unmeasured).
- ``op.asciipsdfile == 1`` (W4, ``soda2_export_ascii.pro``) -- ported as
  ``export_ascii.soda2_export_ascii``, called from ``process_2d``.
  :class:`AsciiPsdNotPorted` is kept only so an old import does not break;
  nothing raises it.
- The IDL SAVE file (W1, ``:729-731``) -- **ported** as
  ``save_writer.save_process_data``, called from ``process_2d``.
  :class:`SaveFileNotPorted` is kept only so an old import does not break;
  nothing raises it (before the SAVE writer nothing did either, so ``savfile=1`` silently
  wrote no ``.dat``).

**Findings** (candidates, to verify):
- S6-i: CSV writes ``x[i].inttime`` (the raw tag) while netCDF writes the
  clamped ``interarrival`` (``soda2_particlesort.pro:198`` vs the CSV
  special-case at ``:293-294``, which falls through to the generic
  ``nw eq 1`` branch at ``:289-290`` for ``inttime`` since it *is* a tag of
  ``x`` -- only ``time`` and ``rejectionflag`` are not).
- S6-k: ``.pbp.nc``'s ``rejectionflag`` is declared ``/byte`` (netCDF signed
  ``NC_BYTE``, int8); bit 128 (S5-a) stores as -128 for any reader that
  honours the type. CSV prints the unsigned value (``format='(i0)'`` on the
  raw ``uint8``).
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any

import numpy as np

__all__ = [
    "PBPPROPS",
    "AsciiPsdNotPorted",
    "PbpImagesNotPorted",
    "SaveFileNotPorted",
    "sfm2hms",
    "pbp_filename",
    "open_pbp_csv",
    "write_pbp_csv_buffer",
    "open_pbp_ncdf",
    "write_pbp_ncdf_buffer",
    "write_pbp_ncdf_images",
    "PBP_IMAGE_INDEX_VARS",
    "close_pbp_ncdf",
]


class PbpImagesNotPorted(NotImplementedError):
    """A particle-image case (``op.ncdfparticlefile == 2``) still refused: the
    parallel driver and unmeasured chunk shapes. The serial path is ported
    (``soda2_process_2d.pro:286-306``, ``:546-553``,
    ``soda2_particlesort.pro:264-276``; the particle-image output)."""


class AsciiPsdNotPorted(NotImplementedError):
    """``op.asciipsdfile == 1`` (``soda2_export_ascii.pro``) lies outside this module; its
    port is :mod:`arrayprobe_soda2.export_ascii`."""


class SaveFileNotPorted(NotImplementedError):
    """Retired: the IDL SAVE file (``soda2_process_2d.pro:729-731``) is written by
    ``save_writer.save_process_data``. Kept for import compatibility only;
    nothing raises it."""


#: ``soda2_process_2d.pro:202-238`` -- ``[varname, longname, unit, datatype,
#: ascii_format]``, transcribed verbatim (order matters: it is both the
#: netCDF variable-definition order and the CSV column order).
PBPPROPS: tuple[tuple[str, str, str, str, str], ...] = (
    ("time", "UTC time", "seconds", "double", "f0.5"),
    ("probetime", "Unadjusted probe particle time", "seconds", "double", "f0.5"),
    ("buffertime", "Buffer time", "seconds", "double", "f0.5"),
    ("rawtime", "Raw time", "slices or seconds", "double", "f0.5"),
    ("reftime", "Reference time for buffer matching", "seconds", "double", "f0.5"),
    ("inttime", "Interarrival time from previous particle", "seconds", "float", "e0.5"),
    ("diam", "Particle diameter from circle fit. No Poisson spot size corrections applied", "microns", "float", "f0.1"),
    ("xsize", "X-size (across array). No Poisson spot size corrections applied", "microns", "float", "f0.1"),
    ("ysize", "Y-size (along airflow). No Poisson spot size corrections applied", "microns", "float", "f0.1"),
    ("xextent", "Maximum x-size (across array) for a single slice. No Poisson spot size corrections applied", "microns", "float", "f0.1"),
    ("oned", "1-D emulation size. Number of latched pixels. No Poisson spot size corrections applied", "microns", "float", "f0.1"),
    ("twod", "2-D emulation size. Maximum number of shaded pixels on a single slice. No Poisson spot size corrections applied", "microns", "float", "f0.1"),
    ("areasize", "Equivalent area size. No Poisson spot size corrections applied", "microns", "float", "f0.1"),
    ("arearatio", "Area ratio", "unitless", "float", "f0.2"),
    ("arearatiofilled", "Area ratio with particle voids filled", "unitless", "float", "f0.2"),
    ("aspectratio", "Aspect ratio", "unitless", "float", "f0.2"),
    ("area", "Number of shaded pixels", "pixels", "short", "i0"),
    ("areafilled", "Number of shaded pixels including voids", "pixels", "short", "i0"),
    ("perimeterarea", "Number of shaded pixels on particle perimeter", "pixels", "short", "i0"),
    ("area75", "Number of shaded pixels at the 75% (or grey level-3) shading", "pixels", "short", "i0"),
    ("xpos", "X-position of particle center (across array)", "pixels", "float", "f0.2"),
    ("ypos", "Y-position of particle center (along airflow)", "pixels", "float", "f0.2"),
    ("allin", "All-in flag (1=all-in)", "unitless", "byte", "i0"),
    ("centerin", "Center-in flag (1=center-in)", "unitless", "byte", "i0"),
    ("dofflag", "Depth of field flag from probe, if available (1=accepted)", "unitless", "byte", "i0"),
    ("edgetouch", "Edge touch (1=left 2=right 3=both)", "unitless", "byte", "i0"),
    ("sizecorrection", "Size correction factor from Korolev 2007 (D_edge/D0). Use to adjust sizes in this file if necessary", "unitless", "float", "f0.2"),
    ("zd", "Z position from Korolev correction", "microns", "float", "f0.2"),
    ("missed", "Missed particle count", "number", "float", "i0"),
    ("probetas", "True air speed for probe clock", "m/s", "float", "f0.2"),
    ("aircrafttas", "True air speed for aircraft (if available)", "m/s", "float", "f0.2"),
    ("overloadflag", "Overload flag", "boolean", "byte", "i0"),
    ("particlecounter", "Particle counter", "number", "long", "i0"),
    ("orientation", "Particle orientation relative to array axis", "degrees", "float", "f0.2"),
    ("rejectionflag", "Particle rejection code (see soda2_reject.pro for codes)", "unitless", "byte", "i0"),
    ("numregions", "Number of connected regions (blobs) in the particle image, if the KEEP_LARGEST option is enabled", "count", "byte", "i0"),
    ("diodegaps", "Number of unshaded diodes between the first and last shaded diodes", "count", "short", "i0"),
)

#: The two PBP columns that are not tags of ``x`` (``soda2_particlesort.pro:293-294``).
_NOT_X_TAGS = {"time", "rejectionflag"}

_NCDF_TYPE = {"float": "f4", "double": "f8", "byte": "i1", "short": "i2", "long": "i4"}


def sfm2hms(sfm: float) -> int:
    """``sfm2hms.pro``: seconds-from-midnight to an ``HHMMSS`` integer (IDL
    LONG). ``soda2_filename.pro:20``, ``soda2_process_2d.pro:253-254`` and
    ``soda2_export_ncdf.pro:56-57`` all call this; ``timeconv.py`` does not
    carry it, so it is defined here and is the canonical port; moving it
    into ``timeconv.py`` would be a rename, not a re-derivation.

    **No wrap at midnight**: ``sfm=long(sfm_in)``,
    ``hour=sfm/3600l``, ``minute=(sfm mod 3600)/60``, ``sec=(sfm mod 3600) mod
    60`` -- nothing reduces modulo 86400, so 86401 s is ``240001`` and 90061 s
    ``250101``. Applying ``% 86400`` (``000001``) would disagree with the source,
    visibly in ``soda2_export_ncdf``'s ``TimeInterval``. IDL's ``long()`` and integer
    ``/`` truncate toward zero and ``mod`` takes the dividend's sign, so a
    negative ``sfm`` gives a negative result (-5 s is ``-5``), unlike
    Python's floor ``divmod``. Every case pinned by
    the GDL bank ``run_soda2_sfm2hms_bank.py`` (not included in this package)."""
    s = int(sfm)  # IDL long() truncates toward zero, as int() does
    hour = _idl_div(s, 3600)
    rem = s - 3600 * hour  # IDL `sfm mod 3600`: the dividend's sign
    minute = _idl_div(rem, 60)
    sec = rem - 60 * minute
    return 10000 * hour + 100 * minute + sec


def _idl_div(a: int, b: int) -> int:
    """IDL integer ``/``: truncation toward zero (Python's ``//`` floors)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _idl_six_digit_int(value: int) -> str:
    """IDL format ``(i06)``: zero-padded to width 6, the sign inside the
    width (-5 is ``-00005``), and six asterisks when the value does not fit
    -- measured under GDL for ``sfm2hms`` >= 1000000, i.e. ``starttime`` at
    or past 100 h (``run_soda2_sfm2hms_bank.py``)."""
    text = f"{int(value):06d}"
    return "*" * 6 if len(text) > 6 else text


def _idl_hms_string(hms: int) -> str:
    """``soda2_process_2d.pro:253-256``: ``tb='0000'+strtrim(string(hms),2)``,
    then ``strmid(tb,5,2,/r)+':'+strmid(tb,3,2,/r)+':'+strmid(tb,1,2,/r)``.

    ``/REVERSE_OFFSET`` counts the *start* from the end of the string (0 = the
    last character) and still reads forward, so the three pieces are
    ``s[-6:-4]``, ``s[-4:-2]``, ``s[-2:]`` -- ``HH:MM:SS`` -- except that a start
    before the string's first character is clamped to it and two characters
    are still taken (measured under GDL: hms 5 -> ``00:00:05``, where a Python
    slice would give ``0:00:05``). Until 2026-09-14 this port read ``/r`` as
    reversing the field order and wrote ``SS:MM:HH``; the whole-driver GDL
    golden caught it."""
    s = "0000" + str(int(hms))

    def strmid_r(first: int, length: int) -> str:
        start = max(len(s) - 1 - first, 0)
        return s[start:start + length]

    return f"{strmid_r(5, 2)}:{strmid_r(3, 2)}:{strmid_r(1, 2)}"


def pbp_filename(
    op: Mapping[str, Any],
    suffix: str,
    *,
    extension: str = ".dat",
    outdir: str | None = None,
) -> str:
    """``soda2_filename.pro``. ``op`` is a plain mapping of IDL tag name
    (upper- or lower-case, looked up case-insensitively as ``tag_names``
    would present them) to value."""
    lower = {k.lower(): v for k, v in op.items()}
    if outdir is None:
        outdir = str(lower["outdir"])

    filetag = ""
    if "filetag" in lower and len(str(lower["filetag"])) > 0:
        filetag = "_" + str(lower["filetag"])

    if "probetype" in lower and lower["probetype"] in ("2DS", "3VCPI", "HVPS4"):
        suffix = suffix + "_" + str(lower["probeid"])

    hhmmss = _idl_six_digit_int(sfm2hms(float(lower["starttime"])))  # `:20`, form='(i06)'
    return (
        f"{outdir}{str(lower['date']).strip()}_{hhmmss}_{suffix}{filetag}{extension}"
    )


# ---------------------------------------------------------------------------
# W3: ASCII/CSV
# ---------------------------------------------------------------------------

def open_pbp_csv(fn_pbp: str, op: Mapping[str, Any], date: Mapping[str, str]) -> IO[str]:
    """``soda2_process_2d.pro:336-354``. Text mode, ``\\n`` line endings
    (IDL's ``printf`` writes ``\\n``, not the platform default)."""
    f = open(fn_pbp, "w", newline="\n")
    f.write("Source: SODA-2 OAP Processing Software\n")
    f.write(f"Flight Date (mm/dd/yyyy): {date['month']}/{date['day']}/{date['year']}\n")
    f.write(f"Date Processed: {_dt.datetime.now().ctime()}\n")
    f.write("Variable Descriptions: \n")
    # `:350` `string(i+1, format='(4i)')` -- `4` is a REPEAT COUNT (unused,
    # since only one value is printed), not a field width; the field takes
    # the default `I` width for the loop variable's own type. Measured under
    # GDL, R8B (2026-09-14): `i`'s initial value `0` is INT and *stays* INT
    # even though the loop bound `n_elements(tagnames)-1` is LONG (a
    # separately-probed fact -- IDL does not widen the index to the bound's
    # type here), and `string(<INT>, format='(4i)')` right-justifies in a
    # **7-character** field (`'      1'`), not 4.
    # `tests/data/gdl_soda2_pbp_one_buffer_3p.pbp.csv` line 5 is the golden.
    for i, (name, longname, unit, _dtype, _fmt) in enumerate(PBPPROPS):
        f.write(f"{i + 1:7d}. {name}: {longname} [{unit}]\n")
    f.write("-------------------------------------------\n")
    # :353 -- trailing-comma suppression (the "colon" in `(99(a0,:,","))`).
    f.write(",".join(name for name, *_ in PBPPROPS) + "\n")
    return f


def _idl_format_scalar(value: Any, fmt: str) -> str:
    """A small subset of IDL ``format=`` strings used by ``pbpprops[4,*]``:
    ``i0`` (bare integer), ``fN.M``/``f0.M`` (fixed), ``e0.5`` (scientific,
    5 digits after the point, IDL's minimal-width ``e0.5``)."""
    if fmt == "i0":
        return str(int(value))
    if fmt.startswith("f"):
        _, dec = fmt[1:].split(".")
        return f"{float(value):.{int(dec)}f}"
    if fmt.startswith("e"):
        _, dec = fmt[1:].split(".")
        s = f"{float(value):.{int(dec)}e}"
        mantissa, exp = s.split("e")
        exp_i = int(exp)
        return f"{mantissa}e{'+' if exp_i >= 0 else '-'}{abs(exp_i):02d}"
    raise ValueError(f"unhandled ascii_format {fmt!r}")


def write_pbp_csv_buffer(
    f: IO[str],
    x: Mapping[str, np.ndarray],
    istop: int,
    truetime: np.ndarray,
    rejectionflag: np.ndarray,
) -> None:
    """``soda2_particlesort.pro:279-298``. ``time`` and ``rejectionflag``
    are not tags of ``x`` (SODA-2 register entry S6-i notes ``inttime`` IS a tag, so it takes the
    generic branch and prints the raw value, not the clamped ``interarrival``
    netCDF writes)."""
    numparticles = istop + 1
    for i in range(numparticles):
        parts = []
        for name, _longname, _unit, _dtype, fmt in PBPPROPS:
            if name == "rejectionflag":
                parts.append(_idl_format_scalar(int(rejectionflag[i]), "i0"))
            elif name == "time":
                parts.append(_idl_format_scalar(float(truetime[i]), "f0.5"))
            else:
                parts.append(_idl_format_scalar(x[name][i], fmt))
        f.write(",".join(parts) + "\n")


# ---------------------------------------------------------------------------
# W2: per-particle netCDF-4
# ---------------------------------------------------------------------------

#: The two provenance global attributes every SODA-2 netCDF product carries (author, 2026-09-24; batch 5
#: item 5): the same names and the same "unstated" value as
#: ``arrayprobe.provenance.engine_attrs``, spelled here because this package never imports the
#: port. Not IDL output -- the GDL-golden comparisons exclude both, as they exclude
#: ``DateCreated``/``DateProcessed``.
ENGINE_ATTR = "arrayprobe_engine"
PROFILE_ATTR = "arrayprobe_profile"
PROFILE_UNSTATED = "unstated"


def engine_attrs(stamp_profile: str | None) -> dict[str, str]:
    """``{arrayprobe_engine: "soda2", arrayprobe_profile: stamp_profile or "unstated"}``.

    SODA-2 has no fidelity profile: its configuration is the ``op`` structure, already written
    as global attributes. ``stamp_profile`` is the name a driver ran it under, when it had one;
    a library call that names none writes ``"unstated"`` -- never a name inferred from ``op``.
    """
    text = PROFILE_UNSTATED if stamp_profile is None else str(stamp_profile)
    if not text or any(c in text for c in " \r\n"):
        raise ValueError(f"profile {text!r} cannot be carried as a stamp value")
    return {ENGINE_ATTR: "soda2", PROFILE_ATTR: text}


def soda2_stamp_profile(config_path: str | Path) -> str:
    """The ``stamp_profile`` a config-driven SODA-2 run carries: ``config:<file name>``.

    SODA-2 reads no fidelity profile (``arrayprobe soda2 run`` refuses a ``[fidelity]`` table),
    so the only name a run is made under is its config file's. Whitespace, which a stamp value
    cannot hold (:func:`engine_attrs`), becomes ``_``; the full path stays in the ``.pbp.call``
    sidecar's ``config_path``."""
    name = "_".join(Path(config_path).name.split())
    return f"config:{name}"


def open_pbp_ncdf(
    fn_ncdf: str, op: Mapping[str, Any], date: Mapping[str, str],
    pthdat: Mapping[str, Any] | None = None,
    *,
    stamp_profile: str | None = None,
) -> Any:
    """``soda2_process_2d.pro:240-333``, with the ``ncdfparticlefile == 2``
    image variables (`:286-306`). Returns an open
    ``netCDF4.Dataset`` in data mode (IDL's ``ncdf_control,/endef``)."""
    import netCDF4

    Path(fn_ncdf).unlink(missing_ok=True)  # :243 -- file_delete before create; /clobber fails on netCDF-4.
    ds = netCDF4.Dataset(fn_ncdf, "w", format="NETCDF4")
    ds.createDimension("Time", None)

    lower = {k.lower(): v for k, v in op.items()}
    starttimestr = _idl_hms_string(sfm2hms(float(lower["starttime"])))
    stoptimestr = _idl_hms_string(sfm2hms(float(lower["stoptime"])))

    ds.Source = "SODA-2 OAP Processing Software"
    ds.FlightDate = f"{date['month']}/{date['day']}/{date['year']}"
    ds.DateProcessed = _dt.datetime.now().ctime()
    ds.TimeInterval = f"{starttimestr}-{stoptimestr}"

    # B1 (§C.4, measured against the fresh GDL golden): IDL's
    # `tag_names(op)` returns every tag upper-cased, so `:265`'s
    # `ncdf_attput, ncdf_id, tn[i], v, /global` writes upper-case global
    # attribute names whatever case `op`'s literal was declared in. B5: the
    # golden's attribute dtypes are the caller's own IDL types (RATE
    # float32, STARTTIME/STOPTIME float64, ENDBINS an int array, several
    # int16 scalars) -- `np.asarray(value)` on the value as given preserves
    # whatever dtype the caller passed, rather than widening every Python
    # int/float to int64/float64 the way a bare `setattr(ds, name, value)`
    # would.
    for name, value in op.items():
        key = name.upper()
        if isinstance(value, str):
            setattr(ds, key, value if value != "" else "none")  # :267
        else:
            setattr(ds, key, np.asarray(value))
    for name, value in engine_attrs(stamp_profile).items():  # in-file provenance: not IDL output
        ds.setncattr(name, value)

    # Storage settings are what IDL REQUESTS, keyword for keyword (A2
    # layout check, 2026-10-03): every `ncdf_vardef` in
    # `soda2_process_2d.pro:275-330` passes `gzip=` and none passes
    # `/SHUFFLE`, so the shuffle filter is off on every variable. netCDF4-python
    # turns shuffle ON by default for `zlib=True`, so it is pinned off here.
    # GDL honours `/SHUFFLE` when given (the writer bank's own `/shuffle`,
    # `gdl_oracle/run_soda2_pbp_writer_bank.py:213-217`, is not in the IDL
    # source), and the driver golden written through the verbatim source has
    # shuffle off everywhere (`gdl_soda2_pbp_driver_frame_*.pbp.nc`).
    # `tests/test_soda2_pbp_storage_matches_idl.py` asserts this.
    for name, longname, unit, dtype, _fmt in PBPPROPS:
        var = ds.createVariable(name, _NCDF_TYPE[dtype], ("Time",), zlib=True, complevel=5,
                                shuffle=False)  # :275-279
        var.longname = longname
        var.units = unit

    ncdfparticlefile = int(lower.get("ncdfparticlefile", 1))
    if ncdfparticlefile == 2:
        # `:286-306` (particle-image output). IDL's `[diodedimid, slicedimid]` is
        # column-major, so the file declares (Slice, Diode) -- the package's
        # slice-first convention; `chunk=[numdiodes, 1024]` likewise reverses.
        # Dimension order and storage settings are read, not yet measured
        # against GDL (a GDL golden will settle them).
        numdiodes = int(lower["numdiodes"])
        ds.createDimension("Diode", None)
        ds.createDimension("Slice", None)
        for vname, longname in PBP_IMAGE_INDEX_VARS:
            v = ds.createVariable(vname, "u4", ("Time",), zlib=True, complevel=5,
                                  shuffle=False)  # :290-299
            v.longname = longname
            v.units = "unitless"
        v = ds.createVariable("image", "u1", ("Slice", "Diode"), zlib=True, complevel=8,
                              shuffle=False, chunksizes=(1024, numdiodes))  # :303
        v.longname = "Particle images"
        v.units = "unitless"

    if pthdat is not None:
        # `:309-330`: `gzip=5`, no `/SHUFFLE`, the same request as the
        # `pbpprops` loop above. (A note here until 2026-10-03 called the
        # `pthdat_extrap` golden's shuffle asymmetry a GDL quirk; it was the
        # writer bank's own `/shuffle` on the `pbpprops` loop, which the IDL
        # source does not pass.)
        pkeys = {k.upper() for k in pthdat}
        if "LAT" in pkeys:
            v = ds.createVariable("lat", "f8", ("Time",), zlib=True, complevel=5, shuffle=False)
            v.longname, v.units = "Latitude", "degrees"
        if "LON" in pkeys:
            v = ds.createVariable("lon", "f8", ("Time",), zlib=True, complevel=5, shuffle=False)
            v.longname, v.units = "Longitude", "degrees"
        if "GALT" in pkeys:
            v = ds.createVariable("alt", "f8", ("Time",), zlib=True, complevel=5, shuffle=False)
            v.longname, v.units = "GPS altitude", "meters"
        if "T" in pkeys:
            v = ds.createVariable("t", "f8", ("Time",), zlib=True, complevel=5, shuffle=False)
            v.longname, v.units = "Temperature", "degrees Celsius"

    return ds


def write_pbp_ncdf_buffer(
    ds: Any,
    x: Mapping[str, np.ndarray],
    istop: int,
    truetime: np.ndarray,
    interarrival: np.ndarray,
    rejectionflag: np.ndarray,
    ncdf_offset: int,
) -> None:
    """``soda2_particlesort.pro:186-261``. ``time`` <- ``truetime``,
    ``inttime`` <- ``interarrival`` (the clamped local, SODA-2 register entry S6-i -- NOT
    ``x['inttime']``, which is what the CSV writer uses); every other
    variable is ``x[name][0:istop]``."""
    numparticles = istop + 1
    sl = slice(ncdf_offset, ncdf_offset + numparticles)
    ds.variables["time"][sl] = truetime[:numparticles]
    ds.variables["inttime"][sl] = interarrival[:numparticles]
    ds.variables["rejectionflag"][sl] = rejectionflag[:numparticles]
    for name, _longname, _unit, _dtype, _fmt in PBPPROPS:
        if name in ("time", "inttime", "rejectionflag"):
            continue
        ds.variables[name][sl] = np.asarray(x[name])[:numparticles]


#: `:290-301` -- the four per-particle image index variables, in definition order.
PBP_IMAGE_INDEX_VARS: tuple[tuple[str, str], ...] = (
    ("starty", "Index of start slice (y-position) in image array"),
    ("stopy", "Index of stop slice (y-position) in image array"),
    ("startx", "Index of start diode (x-position) in image array"),
    ("stopx", "Index of stop diode (x-position) in image array"),
)


def write_pbp_ncdf_images(
    ds: Any,
    x: Mapping[str, np.ndarray],
    istop: int,
    image: np.ndarray,
    ncdf_offset: int,
    image_offset: int,
) -> None:
    """``soda2_particlesort.pro:264-276`` (``ncdfparticlefile eq 2``).
    ``image`` is this flush's chunk, slice-first ``(nslices, numdiodes)``;
    ``image_offset`` is the driver's ``slices_written``. ``startx`` is zeros
    and ``stopx`` the chunk's diode width less one (`:269-272`)."""
    image = np.asarray(image)
    if image.ndim != 2 or image.shape[0] < 2:
        # `:275` on a one-slice or empty chunk: IDL collapses `image[*,0:0]`
        # to 1-D, and `0:-1` is unmeasured -- refused until GDL measures it.
        raise PbpImagesNotPorted(
            "soda2_particlesort.pro:275 -- image chunk of fewer than two slices, not measured")
    numparticles = istop + 1
    sl = slice(ncdf_offset, ncdf_offset + numparticles)
    ds.variables["starty"][sl] = np.asarray(x["startline"])[:numparticles]
    ds.variables["stopy"][sl] = np.asarray(x["stopline"])[:numparticles]
    ds.variables["startx"][sl] = np.zeros(numparticles, dtype=np.int16)
    ds.variables["stopx"][sl] = np.zeros(numparticles, dtype=np.int16) + (image.shape[1] - 1)
    ds.variables["image"][image_offset:image_offset + image.shape[0], 0:image.shape[1]] = image


def _idl_interpol(v: np.ndarray, x: np.ndarray, xout: np.ndarray) -> np.ndarray:
    """IDL/GDL ``INTERPOL(V, X, XOUT)``, regular linear case (no
    ``/LSQUADRATIC``, ``/QUADRATIC`` or ``/SPLINE``) -- **not** ``np.interp``,
    which clamps outside ``[X[0], X[-1]]``. IDL's own documentation: outside
    the range of ``X``, the two nearest points are extrapolated linearly.
    GDL's own stub (``share/gnudatalanguage/lib/utilities/interpol.pro``,
    read 2026-09-14) sorts ``X`` (and ``V`` with it) when called
    with three arguments and then dispatches to the built-in
    ``GDL_INTERPOL``; the sort is reproduced here (``np.interp`` requires an
    ascending abscissa anyway). Measured against GDL 1.1.2
    (``gdl_oracle/probe_pthdat_hang.py``, ``tests/data/
    gdl_soda2_pbp_writer_golden.json``'s ``pthdat_extrap`` case,
    ``tests/data/gdl_soda2_pbp_pthdat_extrap.pbp.nc``): ``x=[1,2]``,
    ``v=[10,20]`` (lat) evaluated at ``xout=[0.5, 2.5]`` gives ``[5, 25]``,
    the slope of the (only, so nearest) segment carried past both ends.

    Two points minimum (IDL's ``INTERPOL`` itself needs at least two to
    define a slope); a single-abscissa ``pthdat.time`` is out of scope here,
    as it is for IDL. Duplicate or otherwise degenerate abscissae are not
    explored -- GDL's linear-extrapolation slope computation is a built-in
    (``GDL_INTERPOL``, not a ``.pro`` file), so its behaviour there cannot be
    read, only measured, and no case exercising it has been measured.
    """
    x = np.asarray(x, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    xout = np.asarray(xout, dtype=np.float64)
    order = np.argsort(x)
    xs, vs = x[order], v[order]
    out = np.interp(xout, xs, vs)  # correct in-range; clamps at the tails
    if xs.size >= 2:
        below = xout < xs[0]
        if np.any(below):
            slope = (vs[1] - vs[0]) / (xs[1] - xs[0])
            out = np.where(below, vs[0] + slope * (xout - xs[0]), out)
        above = xout > xs[-1]
        if np.any(above):
            slope = (vs[-1] - vs[-2]) / (xs[-1] - xs[-2])
            out = np.where(above, vs[-1] + slope * (xout - xs[-1]), out)
    return out


def close_pbp_ncdf(ds: Any, pthdat: Mapping[str, Any] | None = None) -> None:
    """``soda2_process_2d.pro:696-721`` tail: interpolate PTH variables onto
    the written ``time`` axis, then close, via ``_idl_interpol`` -- IDL's
    ``INTERPOL`` linearly extrapolates outside ``pthdat.time``'s range;
    ``np.interp`` would clamp there instead. Measured under GDL
    (``pthdat_extrap`` golden case)."""
    if pthdat is not None:
        ptime = np.asarray(ds.variables["time"][:])
        pkeys = {k.upper(): k for k in pthdat}
        for pkey, ncname in (("LAT", "lat"), ("LON", "lon"), ("GALT", "alt"), ("T", "t")):
            if pkey in pkeys and ncname in ds.variables:
                src_time = np.asarray(pthdat["time"])
                src_val = np.asarray(pthdat[pkeys[pkey]])
                ds.variables[ncname][:] = _idl_interpol(src_val, src_time, ptime)
    ds.close()
