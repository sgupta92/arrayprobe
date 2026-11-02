# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S6-k: ``.pbp.nc``'s ``rejectionflag`` is a signed byte; bit 128
(depth-of-field reject) reads back negative.

``pbpprops`` declares ``rejectionflag`` as ``'byte'``
(``soda2_process_2d.pro:236``), and ``ncdf_vardef(ncdf_id, ..., /byte,
...)`` (``:277``) creates a netCDF ``NC_BYTE`` variable, which is
**signed** 8-bit in the netCDF-3/4 data model. A ``rejectionflag``
value of 128 (the depth-of-field bit, S5-a) therefore does not fit in
the signed range and reads back as ``-128`` through any reader that
honours the declared type. The CSV writer prints the same value
through a bare ``(i0)`` integer format and shows ``128`` unaffected,
so the two on-path files disagree on the sign of this one flag exactly
when bit 128 is set.

**Correction**: the register's own suggested edit -- declare
``rejectionflag`` as ``/ubyte`` (unsigned byte, ``NC_UBYTE``) instead
of ``/byte``. Every other value the variable ever carries is
non-negative regardless, so the correction never changes the *value*
written, only how a signed-byte reader would have displayed it.

``src/arrayprobe_soda2/pbp_writer.py`` is never imported
for writing and never modified. A netCDF variable's declared type
cannot be changed after creation, so this module duplicates
``open_pbp_ncdf``'s dataset-creation orchestration -- the fix is
inside the type-selection expression itself, not something a keyword
selects -- changing only ``rejectionflag``'s netCDF type from ``i1``
to ``u1``; every other variable, global attribute, and the ``pthdat``
extras are unchanged. Tests:
``tests/test_pbp_rejectionflag_ubyte.py``.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from arrayprobe_soda2.pbp_writer import (
    _NCDF_TYPE,
    PBPPROPS,
    PbpImagesNotPorted,
    _idl_hms_string,
    engine_attrs,
    sfm2hms,
)

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_open_pbp_ncdf"]


def corrected_open_pbp_ncdf(
    fn_ncdf: str,
    op: Mapping[str, Any],
    date: Mapping[str, str],
    pthdat: Mapping[str, Any] | None = None,
    *,
    stamp_profile: str | None = None,
):
    """``open_pbp_ncdf`` with S6-k corrected: ``rejectionflag`` is
    declared ``u1`` (unsigned byte, ``NC_UBYTE``), not ``i1``. Every
    other line reproduces ``open_pbp_ncdf`` exactly."""
    import netCDF4

    Path(fn_ncdf).unlink(missing_ok=True)
    ds = netCDF4.Dataset(fn_ncdf, "w", format="NETCDF4")
    ds.createDimension("Time", None)

    lower = {k.lower(): v for k, v in op.items()}
    # The port's own formatter, not a copy: this module's copy kept writing SS:MM:HH
    # after the port fixed it (8d4a8db), found on a real 2D-S run 2026-09-15.
    starttimestr = _idl_hms_string(sfm2hms(float(lower["starttime"])))
    stoptimestr = _idl_hms_string(sfm2hms(float(lower["stoptime"])))

    ds.Source = "SODA-2 OAP Processing Software"
    ds.FlightDate = f"{date['month']}/{date['day']}/{date['year']}"
    ds.DateProcessed = _dt.datetime.now().ctime()
    ds.TimeInterval = f"{starttimestr}-{stoptimestr}"

    for name, value in op.items():
        key = name.upper()
        if isinstance(value, str):
            setattr(ds, key, value if value != "" else "none")
        else:
            setattr(ds, key, np.asarray(value))
    # In-file provenance, the port's own helper (not a copy), so the drop-in keeps the port's
    # signature and header: `soda2_process_2d` passes `stamp_profile` to whichever is bound.
    for name, value in engine_attrs(stamp_profile).items():
        ds.setncattr(name, value)

    for name, longname, unit, dtype, _fmt in PBPPROPS:
        # S6-k: rejectionflag alone is unsigned -- every other field's
        # declared type is unchanged.
        nc_type = "u1" if name == "rejectionflag" else _NCDF_TYPE[dtype]
        var = ds.createVariable(name, nc_type, ("Time",), zlib=True, complevel=5)
        var.longname = longname
        var.units = unit

    ncdfparticlefile = int(lower.get("ncdfparticlefile", 1))
    if ncdfparticlefile == 2:
        raise PbpImagesNotPorted("soda2_process_2d.pro:286-306 -- particle images not ported")

    if pthdat is not None:
        pkeys = {k.upper() for k in pthdat}
        if "LAT" in pkeys:
            v = ds.createVariable("lat", "f8", ("Time",), zlib=True, complevel=5)
            v.longname, v.units = "Latitude", "degrees"
        if "LON" in pkeys:
            v = ds.createVariable("lon", "f8", ("Time",), zlib=True, complevel=5)
            v.longname, v.units = "Longitude", "degrees"
        if "GALT" in pkeys:
            v = ds.createVariable("alt", "f8", ("Time",), zlib=True, complevel=5)
            v.longname, v.units = "GPS altitude", "meters"
        if "T" in pkeys:
            v = ds.createVariable("t", "f8", ("Time",), zlib=True, complevel=5)
            v.longname, v.units = "Temperature", "degrees Celsius"

    return ds


register(EnhancementSpec(
    name="pbp_rejectionflag_ubyte",
    summary=".pbp.nc's rejectionflag variable is declared unsigned "
            "byte (NC_UBYTE), not signed (NC_BYTE) -- bit 128 "
            "(depth-of-field reject) no longer reads back as -128.",
    finding="S6-k",
    reachability="live",
    entry_point="corrected_open_pbp_ncdf",
))
