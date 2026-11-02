# SPDX-License-Identifier: BSD-3-Clause
"""Open a product file as an :class:`xarray.Dataset`, read exactly as written.

Every netCDF file this package writes (decoded images, ``proc`` particle files, ``sd`` size
distributions, combined flight files) opens the same way for analysis. :func:`open_product` sets
the decode choices once, so a notebook or script does not repeat them::

    import arrayprobe as ap

    sd = ap.open_product("sd.nc")          # raw values, as the file stores them
    sd["conc_minR"].isel(Time=slice(0, 5))
    sd["time"].attrs["units"]              # 'HHMMSS': a clock reading, not CF time

It reads and computes nothing. Attributes are returned verbatim, including names with spaces
(``'Creation Time'``, ``'SA Method'``) and the two spellings ``Units`` and ``units`` that
different stages write; nothing is renamed or added.

``xarray`` is optional: install it with ``pip install arrayprobe[zarr]`` (the extra that already
carries it) or ``pip install xarray``. Importing this module needs neither.
"""

from __future__ import annotations

from os import PathLike

#: The extra whose requirements include xarray.
XARRAY_EXTRA = "zarr"

#: The decode modes :func:`open_product` accepts.
DECODE_MODES = ("raw", "cf")


def open_product(path: str | PathLike[str], *, decode: str = "raw", load: bool = True):
    """Open the netCDF product at ``path`` and return an ``xarray.Dataset``.

    ``decode`` chooses how values are read:

    ``"raw"`` (default)
        The stored values, untouched: no ``_FillValue`` masking, no ``scale_factor`` /
        ``add_offset``, and integer variables keep their integer dtype. This is MATLAB's
        ``netcdf.getVar`` view and the one every comparison against an archived product uses.
    ``"cf"``
        Masking and scaling applied (fill values become NaN, packed integers are unpacked to
        floating point): MATLAB's ``ncread`` view.

    In both modes times are not decoded: the products store clock readings such as ``HHMMSS``
    and ``YYYYMMDD`` that are not CF time, so ``time`` stays the number in the file. Coordinate
    attributes are not interpreted, and attributes are carried verbatim.

    With ``load=True`` (default) the values are read into memory and the file is closed before
    returning, so the Dataset stays usable after the file is moved or rewritten and no handle is
    left open. ``load=False`` returns a lazily read Dataset whose file stays open until
    ``ds.close()``.

    Raises ``ImportError`` naming the extra when xarray is not installed, and ``ValueError``
    for an unknown ``decode``.
    """
    if decode not in DECODE_MODES:
        raise ValueError(f"decode must be one of {DECODE_MODES}, not {decode!r}")
    try:
        import xarray as xr  # lazy: optional, not a core dependency
    except ImportError as exc:
        raise ImportError(
            f"open_product needs xarray, which is not installed ({exc}). Install it with "
            f"`pip install arrayprobe[{XARRAY_EXTRA}]` or `pip install xarray`; reading a "
            f"product with netCDF4 directly needs neither.") from exc
    ds = xr.open_dataset(
        path,
        engine="netcdf4",
        mask_and_scale=(decode == "cf"),
        decode_times=False,
        decode_timedelta=False,
        decode_coords=False,
    )
    if not load:
        return ds
    with ds:
        return ds.load()
