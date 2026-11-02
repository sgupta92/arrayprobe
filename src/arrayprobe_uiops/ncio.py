# SPDX-License-Identifier: BSD-3-Clause
"""MATLAB ``netcdf.*`` package semantics on top of netCDF4-python.

Reproduces the low-level MATLAB netCDF interface used by UIOOPS v3.1.4 so ported
call sites can be transliterated 1:1.  Two semantics this module exists to
preserve:

**(1) The dimension reversal.**  MATLAB stores arrays fastest-varying-dimension
first and reverses the dimension list when it calls the C API.  Verified three
independent ways (design doc §1.2): ``read_binary_SPEC.m:44-56`` declares ``data``
as ``[ImgRowlen(8) ImgBlocklen(1700) time]``, and the shipped
``2DS.20151205_subset1.V.cdf`` holds it as ``('time','ImgBlocklen','ImgRowlen')``
with shape ``(1000, 1700, 8)``.

The reversal lives in exactly one place here -- :func:`_c_order` and
:func:`_c_order_index` -- and every public entry point routes through it.
Callers pass MATLAB-order arguments and get MATLAB-shaped arrays back.  **There is
no public way to hand-roll a transpose, deliberately.**

A corollary worth internalizing: the ``'`` at a MATLAB call site and the dim
reversal *cancel*.  Anywhere MATLAB writes ``X'`` into a 2-D netCDF variable
(``imgProc_sm.m:885,929``; ``sizeDist.m:2104-2154``; ``read_binary_DMT.m:202``;
``read_binary_SEA.m:211``; ``IntArrAnalysis.m:293``), Python writes ``X``
unchanged in ``(time, other)`` order.  So does ``permute(X,[3 2 1])`` at
``sizeDist.m:2110,2117,2136,2142``.

**(2) Raw versus masked reads.**  MATLAB's low-level ``netcdf.getVar`` returns RAW
values -- no ``_FillValue`` masking, no ``scale_factor``/``add_offset``.
netCDF4-python masks by default *even when no ``_FillValue`` attribute exists*.
:func:`get_var` therefore forces masking off, while :func:`ncread` -- the
high-level MATLAB function, used at ``imgProc_sm.m:169-170,184-185`` -- keeps it
on.  Two functions, two policies; this is the single most important behavioural
distinction in the module.


MATLAB source of truth: ``UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/``.
"""

from __future__ import annotations

import contextlib
import os
import warnings
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import numpy.typing as npt
from netCDF4 import Dataset, Variable

from . import provenance

__all__ = [
    "NC_UNLIMITED",
    "NC_GLOBAL",
    "MATLAB_NC_TYPES",
    "NC_FILL",
    "get_constant",
    "NcFile",
    "create",
    "open",
    "def_dim",
    "def_var",
    "put_att",
    "end_def",
    "inq_dim",
    "inq_var_id",
    "get_var",
    "put_var",
    "close",
    "ncread",
    "read_image_record",
    "write_record_block",
    "put_provenance",
    "read_provenance",
    "provenance_of",
    "engine_of",
]


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

NC_UNLIMITED = 0
"""``netcdf.getConstant('NC_UNLIMITED')`` -- ``imgProc_sm.m:214``,
``read_binary_SPEC.m:44,61``."""

NC_GLOBAL = -1
"""``netcdf.getConstant('NC_GLOBAL')`` -- ``imgProc_sm.m:218``,
``sizeDist.m:1807``, ``IntArrAnalysis.m:249``."""

MATLAB_NC_TYPES: dict[str, type | str] = {
    # 'byte' is SIGNED int8. Confirmed empirically: month/day/hour/minute/second/
    # wkday all report int8 in all three shipped probe files. Guessing uint8 here
    # silently corrupts every date field. read_binary_SPEC.m:49-53.
    "byte": np.int8,
    "short": np.int16,    # read_binary_SPEC.m:48  -> year
    "int": np.int32,      # read_binary_SPEC.m:56  -> data
    "float": np.float32,  # never used in UIOOPS; mapping is unambiguous
    "double": np.float64,  # read_binary_SEA.m:39-47; all of sizeDist.m:1874-2089
    # NC_CHAR. No defVar(...,'char',...) site exists in UIOOPS or the ORACLES
    # variant; measured under Octave's netcdf package instead
    # (octave_oracle/run_defvar_char_bank.py): xtype 2, one byte per element,
    # unwritten elements NUL (0), which netCDF4-python reads as dtype 'S1'.
    "char": "S1",
}
"""MATLAB ``defVar`` type strings to numpy dtypes (``'S1'`` for ``'char'``).

The ``'char'`` mapping is measured, not assumed: Octave's ``netcdf.defVar(...,'char',...)``
writes ``NC_CHAR``, and the port's write is asserted byte for byte against that file
(``tests/test_ncio_char.py``, golden ``tests/data/defvar_char_octave_golden.json``).
"""

NC_FILL: dict[str, int | float] = {
    "byte": -127,            # NC_FILL_BYTE
    "short": -32767,         # NC_FILL_SHORT
    "int": -2147483647,      # NC_FILL_INT
    "float": 9.9692099683868690e36,   # NC_FILL_FLOAT
    "double": 9.9692099683868690e36,  # NC_FILL_DOUBLE
}
"""netCDF-3 default fill values.

UIOOPS never writes ``_FillValue``, never calls ``defVarFill`` and never calls
``setFill`` (design doc §1.6), so unwritten records carry exactly these.  They are
what :func:`get_var` returns *raw*, and what :func:`ncread` masks.
"""

_NC_FORMATS = ("NETCDF3_CLASSIC", "NETCDF3_64BIT_OFFSET", "NETCDF4_CLASSIC", "NETCDF4")


@contextlib.contextmanager
def _quiet_netcdf4_setitem() -> Iterator[None]:
    """Suppress one third-party DeprecationWarning around netCDF4 assignment.

    ``netCDF4 1.7.4``'s ``Variable.__setitem__`` sets ``.shape`` on the incoming
    array in place, which NumPy 2.5 deprecates.  It fires even for a perfectly
    contiguous, exactly-shaped input, so it cannot be avoided from this side --
    only by moving a pin, which we are not doing for a warning.

    Scoped to the two assignment sites rather than filtered globally, so a
    deprecation raised by *our own* code still surfaces, and so a test suite may
    run under ``warnings.simplefilter('error')``.  Revisit when netCDF4 releases
    a NumPy 2.5-clean version; see ``requirements.txt``.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Setting the shape on a NumPy array has been deprecated",
            category=DeprecationWarning,
        )
        yield


def get_constant(name: str) -> int:
    """``netcdf.getConstant(name)`` for the two constants UIOOPS uses."""
    try:
        return {"NC_UNLIMITED": NC_UNLIMITED, "NC_GLOBAL": NC_GLOBAL}[name]
    except KeyError:
        raise ValueError(
            f"netcdf.getConstant({name!r}): UIOPS uses only NC_UNLIMITED and "
            "NC_GLOBAL (design doc §1.1). Add it here with its call site if a "
            "later stage genuinely needs another."
        ) from None


# --------------------------------------------------------------------------
# The dimension reversal -- the ONLY place it happens
# --------------------------------------------------------------------------

def _c_order(seq: Iterable[Any]) -> tuple[Any, ...]:
    """MATLAB dimension order (fastest first) -> C/on-disk order (slowest first).

    Its own inverse, so it also converts back.  Every reversal in this module
    goes through here or through :func:`_c_order_index`.
    """
    return tuple(seq)[::-1]


def _c_order_index(start: npt.ArrayLike, count: npt.ArrayLike) -> tuple[slice, ...]:
    """MATLAB ``start``/``count`` vectors -> a C-order tuple of slices.

    ``start`` is **0-based everywhere** in UIOOPS.  Evidence: ``imgProc_sm.m:452-453``
    initializes ``w=-1; wstart=0;`` before feeding ``:873``, and ``sizeDist.m:686``
    writes ``start_all = find(startindex)-1;`` -- explicitly converting 1-based
    ``find`` results to 0-based netCDF starts.
    """
    s = np.atleast_1d(np.asarray(start, dtype=np.int64))
    c = np.atleast_1d(np.asarray(count, dtype=np.int64))
    if s.shape != c.shape:
        raise ValueError(f"start and count must have equal length, got {s.shape} and {c.shape}")
    return tuple(
        slice(int(a), int(a) + int(n))
        for a, n in zip(_c_order(s), _c_order(c), strict=True)
    )


def _as_char_array(data: str | npt.ArrayLike) -> np.ndarray:
    """A MATLAB char argument to ``putVar`` -> an ``'S1'`` array in MATLAB shape.

    A Python ``str`` is a MATLAB char row (``1xN``), as ``netcdf.putVar(ncid,vid,'wxyz')``
    passes it; an array of ``'S1'`` or one-character ``'U1'`` elements is a char matrix
    already in MATLAB order, so ``names'`` at the call site stays a transpose here too.
    A MATLAB char is one byte on disk (``NC_CHAR``), so each character must encode to
    one Latin-1 byte.
    """
    if isinstance(data, str):
        return np.array([c.encode("latin-1") for c in data], dtype="S1").reshape(1, -1)
    arr = np.asarray(data)
    if arr.dtype.kind == "U":
        if arr.dtype.itemsize > 4:
            raise ValueError("a char putVar takes one character per element, not strings")
        return np.char.encode(arr, "latin-1").astype("S1")
    if arr.dtype.kind == "S":
        if arr.dtype.itemsize > 1:
            raise ValueError("a char putVar takes one character per element, not strings")
        return arr.astype("S1")
    raise TypeError(f"a char variable takes str or 'S1'/'U1' data, got {arr.dtype}")


def _to_matlab_shape(arr: np.ndarray) -> np.ndarray:
    """Reverse the axes and apply MATLAB's shape conventions.

    MATLAB arrays are always at least 2-D and drop **trailing** singleton
    dimensions.  So ``getVar(f,id,[0,0,i-1],[8,1700,1])`` is ``8x1700``, not
    ``8x1700x1``, and a whole 1-D variable of length ``N`` comes back ``Nx1`` --
    a column.  The column part matters more than it looks: ``sizeDist.m:815``
    (``[0;diff(Time_in_seconds)]``) and ``:713`` (``[diff(start_all); ...]``) are
    vertical concatenations, which only typecheck on columns (a MATLAB-compatibility gap, and §T3
    of the design doc).
    """
    out = np.transpose(arr)
    while out.ndim > 2 and out.shape[-1] == 1:
        out = out.reshape(out.shape[:-1])
    while out.ndim < 2:
        out = out.reshape(out.shape + (1,))
    return out


def _from_matlab_shape(arr: np.ndarray, target_shape: tuple[int, ...]) -> np.ndarray:
    """Inverse of :func:`_to_matlab_shape` for writes.

    ``target_shape`` is the C-order shape of the destination region, so the
    MATLAB-shaped ``arr`` is reversed and then reshaped onto it.  This is where
    the ``X'`` at a MATLAB ``putVar`` call site cancels against the reversal.
    """
    out = np.transpose(np.asarray(arr))
    if out.shape == target_shape:
        # Contiguous, because netCDF4 1.7.4 reshapes a non-contiguous input
        # in-place and NumPy 2.5 deprecates that.
        return np.ascontiguousarray(out)
    # MATLAB pads to 2-D and drops trailing singletons, so a shape mismatch is
    # legitimate whenever the element count agrees -- e.g. a 1x1 write into a
    # scalar hyperslab, or an (N,1) column into a 1-D region of length N.
    if out.size != int(np.prod(target_shape, dtype=np.int64)):
        raise ValueError(
            f"cannot write an array of shape {np.shape(arr)} (MATLAB order) into a "
            f"region of on-disk shape {target_shape}"
        )
    return np.ascontiguousarray(out.reshape(target_shape))


# --------------------------------------------------------------------------
# The file handle
# --------------------------------------------------------------------------

class NcFile:
    """A MATLAB ``ncid``.

    MATLAB identifies dimensions and variables by **integer IDs assigned in
    creation order**, and UIOOPS relies on that: ``imgProc_sm.m:205-206`` reads
    dimension 0 (``time``) and dimension 2 (``ImgBlocklen``) by number alone,
    never by name.  A bare :class:`netCDF4.Dataset` has no such numbering, so this
    class keeps it -- along with the mask/scale policy and the define-mode state.
    """

    def __init__(self, ds: Dataset, *, define_mode: bool):
        self._ds = ds
        self._dim_names: list[str] = list(ds.dimensions)
        self._var_names: list[str] = list(ds.variables)
        self._in_define = define_mode
        for var in ds.variables.values():
            var.set_auto_maskandscale(False)

    # -- properties ------------------------------------------------------

    @property
    def dataset(self) -> Dataset:
        """The underlying :class:`netCDF4.Dataset`.

        For tests and for :mod:`tools.compare_nc`.  Ported call sites must not
        reach through it -- that is how a hand-rolled transpose gets in.
        """
        return self._ds

    @property
    def in_define_mode(self) -> bool:
        """Whether the file is still in netCDF define mode.

        NETCDF3_CLASSIC has the two-mode discipline MATLAB's ``netcdf.*``
        surface exposes: dimensions, variables and attributes are created in
        define mode, data is written in data mode, and ``netcdf.endDef``
        crosses over one way. netCDF4-python hides that, so it is tracked here
        instead and ``_require_define`` raises on a define-mode call made after
        the crossing -- the same error MATLAB would give, rather than a silent
        success that would let a call order the MATLAB cannot express pass
        review.
        """
        return self._in_define

    # -- definition ------------------------------------------------------

    def def_dim(self, name: str, length: int) -> int:
        """``netcdf.defDim(ncid,name,length)``; ``length == NC_UNLIMITED`` (0) is a
        record dimension.  Returns the 0-based dimension ID."""
        self._require_define("defDim")
        self._ds.createDimension(name, None if length == NC_UNLIMITED else int(length))
        self._dim_names.append(name)
        return len(self._dim_names) - 1

    def def_var(
        self,
        name: str,
        xtype: str,
        dimids: npt.ArrayLike,
        *,
        chunksizes: npt.ArrayLike | None = None,
    ) -> int:
        """``netcdf.defVar(ncid,name,xtype,dimids)`` with ``dimids`` in MATLAB order.

        **This is the only place the reversal happens on write.**
        ``read_binary_SPEC.m:56`` passes ``[dimid1 dimid2 dimid0]`` =
        ``[ImgRowlen ImgBlocklen time]`` and the file holds
        ``('time','ImgBlocklen','ImgRowlen')``.

        ``chunksizes`` mirrors ``netcdf.defVarChunking(ncid,varid,'CHUNKED',chunkSizes)``:
        MATLAB order, like ``dimids``, reversed by the same :func:`_c_order`, so no caller
        transposes it by hand.  ``None`` (the default) passes nothing to
        ``createVariable`` and leaves the library's default chunking, exactly as before
        the keyword existed.  A value on a classic-model file, which has no chunks, or
        one whose length differs from ``dimids``'s, raises :class:`ValueError`.
        """
        self._require_define("defVar")
        try:
            dtype = MATLAB_NC_TYPES[xtype]
        except KeyError:
            raise ValueError(
                f"unknown MATLAB netCDF type {xtype!r}; UIOPS uses only "
                f"{sorted(MATLAB_NC_TYPES)} (design doc §1.4)"
            ) from None
        ids = np.atleast_1d(np.asarray(dimids, dtype=np.int64))
        names = tuple(self._dim_names[int(i)] for i in _c_order(ids))
        extra: dict[str, Any] = {}
        if chunksizes is not None:
            if self._ds.data_model not in ("NETCDF4", "NETCDF4_CLASSIC"):
                raise ValueError(
                    f"defVarChunking on variable {name!r}: a {self._ds.data_model} file "
                    "has no chunks; chunksizes needs a NETCDF4 or NETCDF4_CLASSIC file"
                )
            sizes = [int(n) for n in np.atleast_1d(np.asarray(chunksizes, dtype=np.int64))]
            if len(sizes) != len(ids):
                raise ValueError(
                    f"defVarChunking on variable {name!r}: {len(sizes)} chunk sizes for "
                    f"{len(ids)} dimensions"
                )
            extra["chunksizes"] = tuple(_c_order(sizes))
        # Annotated because ``createVariable`` is generic in its element type and
        # mypy cannot solve the type variable from a runtime ``dtype`` looked up
        # out of ``MATLAB_NC_TYPES``.  ``Variable`` (i.e. ``Variable[Any]``) is
        # exactly what it returns; nothing here depends on the element type.
        var: Variable = self._ds.createVariable(name, dtype, names, **extra)
        var.set_auto_maskandscale(False)
        self._var_names.append(name)
        return len(self._var_names) - 1

    def put_att(self, varid: int, name: str, value: Any) -> None:
        """``netcdf.putAtt(ncid,varid,name,value)``; ``varid`` may be
        :data:`NC_GLOBAL`.

        Attribute names contain spaces (``'Creation Time'``, ``'SA Method'``,
        ``'Dmax Definition'``) and the ``Units``/``units`` case is inconsistent
        between ``imgProc_sm.m`` and ``sizeDist.m``.  Both are part of the output
        contract -- written verbatim, never normalized.
        """
        self._require_define("putAtt")
        target = self._ds if varid == NC_GLOBAL else self._ds.variables[self._var_names[varid]]
        target.setncattr(name, value)

    def end_def(self) -> None:
        """``netcdf.endDef(ncid)``.

        netCDF4-python leaves define mode implicitly, so this changes no bytes --
        but it flips the state that makes a ``putVar``-before-``endDef`` (or a
        ``putAtt``-after-) fail here exactly as it fails in MATLAB.  UIOOPS never
        calls ``reDef``, so the one-way transition is faithful.
        """
        self._in_define = False

    # -- inquiry ---------------------------------------------------------

    def inq_dim(self, dimid: int) -> tuple[str, int]:
        """``[name,len] = netcdf.inqDim(ncid,dimid)``.

        ``imgProc_sm.m:205-206`` calls this with the bare numbers 2 and 0.
        """
        name = self._dim_names[dimid]
        return name, len(self._ds.dimensions[name])

    def inq_var_id(self, name: str) -> int:
        """``netcdf.inqVarID(ncid,name)``."""
        try:
            return self._var_names.index(name)
        except ValueError:
            raise KeyError(
                f"netcdf.inqVarID: no variable {name!r} in {self._ds.filepath()}"
            ) from None

    def variable(self, varid: int) -> Variable:
        """The underlying netCDF4 ``Variable``, with mask/scale already off.

        For the fused helpers below and for structural assertions in tests.  Not
        for ported call sites: reaching for the on-disk array is how a hand-rolled
        transpose gets back in.
        """
        var = self._ds.variables[self._var_names[varid]]
        var.set_auto_maskandscale(False)
        return var

    # -- data motion -----------------------------------------------------

    def get_var(
        self,
        varid: int,
        start: npt.ArrayLike | None = None,
        count: npt.ArrayLike | None = None,
    ) -> np.ndarray:
        """``netcdf.getVar`` -- all three signatures UIOOPS uses.

        ``start``/``count`` are 0-based and in MATLAB dimension order; the return
        is in MATLAB dimension order and shape.  Auto mask/scale is **OFF**, so
        unwritten records come back as the raw :data:`NC_FILL` values, which is
        what MATLAB hands the caller.
        """
        var = self.variable(varid)
        if start is None and count is None:
            raw = var[...]
        elif start is None or count is None:
            raise ValueError("netcdf.getVar takes start and count together or neither")
        else:
            raw = var[_c_order_index(start, count)]
        return _to_matlab_shape(np.asarray(raw))

    def put_var(self, varid: int, *args: Any) -> None:
        """``netcdf.putVar`` -- all three signatures UIOOPS uses.

        ``put_var(vid, data)`` writes a whole variable; ``put_var(vid, start,
        count, data)`` writes a hyperslab.  ``data`` is MATLAB-ordered, so
        ``imgProc_sm.m:885``::

            netcdf.putVar(f, vid, [0 wstart], [2 w-wstart+1], images.position')

        transliterates as ``put_var(vid, [0, wstart], [2, n], position)`` with
        ``position`` of shape ``(2, n)``, landing on disk as ``(time, 2)``.
        """
        if self._in_define:
            raise RuntimeError(
                "netcdf.putVar before netcdf.endDef: the file is still in define "
                "mode (MATLAB raises NC_EINDEFINE). Call end_def() first."
            )
        var = self.variable(varid)
        if var.dtype == np.dtype("S1"):
            args = args[:-1] + (_as_char_array(args[-1]),)
        if len(args) == 1:
            (data,) = args
            arr = np.asarray(data)
            if var.shape == ():
                with _quiet_netcdf4_setitem():
                    var[...] = arr
            else:
                # An unlimited dimension reports its CURRENT length, which is 0 on
                # a freshly created file, so size the region from the data instead.
                region = tuple(var.shape)
                if 0 in region:
                    region = _c_order(np.shape(arr))
                with _quiet_netcdf4_setitem():
                    var[...] = _from_matlab_shape(arr, tuple(region))
        elif len(args) == 3:
            start, count, data = args
            index = _c_order_index(start, count)
            target = tuple(sl.stop - sl.start for sl in index)
            with _quiet_netcdf4_setitem():
                var[index] = _from_matlab_shape(np.asarray(data), target)
        else:
            raise TypeError(
                "netcdf.putVar takes (varid, data) or (varid, start, count, data); "
                f"got {len(args)} data argument(s)"
            )

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        """``netcdf.close(ncid)``.  Idempotent, so a double close in a ported
        error path does not mask the original failure."""
        if not self._ds.isopen():
            return
        self._ds.close()

    def _require_define(self, what: str) -> None:
        if not self._in_define:
            raise RuntimeError(
                f"netcdf.{what} after netcdf.endDef: the file has left define mode "
                "(MATLAB raises NC_ENOTINDEFINE). UIOPS never calls netcdf.reDef, so "
                "every definition belongs before end_def()."
            )

    def __enter__(self) -> NcFile:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "define" if self._in_define else "data"
        return f"<NcFile {self._ds.filepath()!r} mode={state} vars={len(self._var_names)}>"


# --------------------------------------------------------------------------
# Module-level functions mirroring the MATLAB names
# --------------------------------------------------------------------------

def create(
    filename: str | os.PathLike[str],
    mode: str = "clobber",
    *,
    format: str = "NETCDF3_CLASSIC",
) -> NcFile:
    """``netcdf.create(filename,'clobber')``.

    Every creation site in UIOOPS passes a bare ``'clobber'`` and no format, so
    MATLAB's default ``NC_FORMAT_CLASSIC`` applies -- confirmed from the magic
    bytes of the three shipped probe files (``b'CDF\\x01'``).  Default preserved
    here, **including its failure mode**: NETCDF3_CLASSIC caps a non-record
    variable at 2 GiB and ``imgProc_sm.m`` writes ~40 record variables, so a large
    flight fails at ``putVar`` exactly as MATLAB's would.  ``format=`` is the
    escape hatch, never the default.
    """
    if mode != "clobber":
        raise ValueError(
            f"netcdf.create mode {mode!r}: every UIOPS creation site passes "
            "'clobber' (design doc §1.1); 'noclobber' is unexercised"
        )
    if format not in _NC_FORMATS:
        raise ValueError(f"unknown netCDF format {format!r}; expected one of {_NC_FORMATS}")
    # The ``cast`` is discharged by the guard immediately above, not asserted on
    # faith: netCDF4 types ``format=`` as a ``Literal`` of five names and
    # ``_NC_FORMATS`` is a four-element subset of exactly those names, so any
    # value reaching this line is already one of them.  Keeping the parameter a
    # plain ``str`` is deliberate -- the ValueError above is the port's own
    # documented error for a bad format, and a ``Literal`` annotation would move
    # that rejection from runtime (where MATLAB's would also be) to type-check
    # time, which callers passing a computed string would never see.
    fmt = cast("Literal['NETCDF3_CLASSIC', 'NETCDF3_64BIT_OFFSET', "
               "'NETCDF4_CLASSIC', 'NETCDF4']", format)
    return NcFile(Dataset(filename, "w", format=fmt), define_mode=True)


def open(filename: str | os.PathLike[str], mode: str = "nowrite") -> NcFile:  # noqa: A001 -- MATLAB name
    """``netcdf.open(filename,'nowrite')``.

    Reads both NETCDF3_CLASSIC and NETCDF3_64BIT_OFFSET: the probe files UIOOPS
    writes are classic, but ``flightData_20151205.cdf`` -- an *input*, produced
    outside UIOOPS and consumed at ``imgProc_sm.m:169-170`` -- is 64-bit offset.
    """
    if mode not in ("nowrite", "write"):
        raise ValueError(f"netcdf.open mode {mode!r}: UIOPS uses only 'nowrite'")
    return NcFile(Dataset(filename, "r" if mode == "nowrite" else "a"), define_mode=False)


def def_dim(ncid: NcFile, name: str, length: int) -> int:
    """``netcdf.defDim`` -- see :meth:`NcFile.def_dim`."""
    return ncid.def_dim(name, length)


def def_var(
    ncid: NcFile,
    name: str,
    xtype: str,
    dimids: npt.ArrayLike,
    *,
    chunksizes: npt.ArrayLike | None = None,
) -> int:
    """``netcdf.defVar`` with ``dimids`` (and ``chunksizes``, when given) in MATLAB
    order -- see :meth:`NcFile.def_var`."""
    return ncid.def_var(name, xtype, dimids, chunksizes=chunksizes)


def put_att(ncid: NcFile, varid: int, name: str, value: Any) -> None:
    """``netcdf.putAtt`` -- see :meth:`NcFile.put_att`."""
    ncid.put_att(varid, name, value)


def end_def(ncid: NcFile) -> None:
    """``netcdf.endDef`` -- see :meth:`NcFile.end_def`."""
    ncid.end_def()


def inq_dim(ncid: NcFile, dimid: int) -> tuple[str, int]:
    """``netcdf.inqDim`` -- see :meth:`NcFile.inq_dim`."""
    return ncid.inq_dim(dimid)


def inq_var_id(ncid: NcFile, name: str) -> int:
    """``netcdf.inqVarID`` -- see :meth:`NcFile.inq_var_id`."""
    return ncid.inq_var_id(name)


def get_var(
    ncid: NcFile,
    varid: int,
    start: npt.ArrayLike | None = None,
    count: npt.ArrayLike | None = None,
) -> np.ndarray:
    """``netcdf.getVar`` -- see :meth:`NcFile.get_var`.  Raw, unmasked."""
    return ncid.get_var(varid, start, count)


def put_var(ncid: NcFile, varid: int, *args: Any) -> None:
    """``netcdf.putVar`` -- see :meth:`NcFile.put_var`."""
    ncid.put_var(varid, *args)


def close(ncid: NcFile) -> None:
    """``netcdf.close`` -- see :meth:`NcFile.close`."""
    ncid.close()


# --------------------------------------------------------------------------
# The high-level shim -- opposite masking policy, deliberately separate
# --------------------------------------------------------------------------

def ncread(filename: str | os.PathLike[str], varname: str) -> np.ndarray:
    """MATLAB ``ncread(filename,varname)``.

    MATLAB dimension order, like :func:`get_var`, but with ``_FillValue`` masking
    and ``scale_factor``/``add_offset`` **applied** -- the opposite policy, which
    is why this is a separate function rather than a flag.  Returns a masked array
    when the file gives cause to mask.

    Provenance: ``imgProc_sm.m:169-170,184-185`` (TAS and Time from the flight-data
    file); ``run_imgProc_Munich.m:16-24,32-34``; ``run_sizeDist_Munich.m:25-28``.
    """
    with Dataset(filename, "r") as ds:
        var = ds.variables[varname]
        var.set_auto_maskandscale(True)
        raw = var[...]
    if np.ma.isMaskedArray(raw):
        return np.ma.masked_array(
            _to_matlab_shape(raw.data),
            mask=_to_matlab_shape(np.ma.getmaskarray(raw)),
        )
    return _to_matlab_shape(np.asarray(raw))


# --------------------------------------------------------------------------
# Fused idioms -- so orientation-sensitive call sites are never re-derived
# --------------------------------------------------------------------------

def read_image_record(ncid: NcFile, varid: int, i: int, n_bytes: int, n_slices: int) -> np.ndarray:
    """``imgProc_sm.m:489-495`` fused into one call.

    MATLAB reads ``temp = netcdf.getVar(f,varid,[0,0,i-1],[8,1700,1])`` (``8x1700``)
    and immediately does ``data(:,:) = temp';`` -- so what the rest of
    ``imgProc_sm.m`` calls ``data`` is ``1700x8``, i.e. ``ds['data'][i,:,:]`` with
    no transpose at all.  ``i`` here is the **0-based** record index.

    Returns ``(n_slices, n_bytes)``.  Orientation check: the 2DS boundary word
    (``imgProc_sm.m:159``) fills a whole 8-element slice, so all-43690 runs lie
    along the last axis.
    """
    temp = ncid.get_var(varid, [0, 0, i], [n_bytes, n_slices, 1])
    return np.ascontiguousarray(temp.T)


# --------------------------------------------------------------------------
# Provenance carried BY THE BYTES -- the provenance stamp, opt-in, default off
# --------------------------------------------------------------------------

def put_provenance(
    ncid: NcFile,
    *,
    engine: str,
    # REQUIRED, not defaulted: `profile=None` is a legal and meaningful value here
    # -- an S2 stamp names no profile because neither the SEA nor the DMT reader
    # reads one -- but it must be STATED. A default cannot distinguish "absent by
    # design" from "the caller forgot", which is the whole point of
    # tests/test_profile_is_never_defaulted.py, and that check caught this module
    # propagating the anti-pattern across four signatures on 2026-09-18.
    profile: str | None,
    stage: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Write :func:`arrayprobe.provenance.attrs_for`'s global attributes into ``ncid``.

    **Opt-in, and nothing in the port calls it.** Adding a global attribute changes the file's
    bytes, and the layer-1 comparison is not hypothetical about that:
    the image-processing oracle test asserts
    ``a.ncattrs() == b.ncattrs()`` against the
    MATLAB-written oracle, so a writer that stamped by default would fail that test on its first
    run -- and would shift every tracked ``.call`` fixture and every archived comparison in the
    same commit. A writer opts in by calling this; the default stays "writes exactly what MATLAB
    wrote", which is the claim the whole project rests on.

    Define mode, like every other ``putAtt``: call it before :meth:`NcFile.end_def`. Returns the
    attributes written, so a caller can pass the identical values to
    :func:`arrayprobe.provenance.write` and have the sidecar and the attribute agree by
    construction -- both texts come from ``provenance.stamp_text``.

    ``alongside the .call sidecar rather than instead of it``: this does **not** write a sidecar.
    The two carriers are written by two calls on purpose, because a product may legitimately have
    one and not the other (an older product has only the sidecar; a hardlinked copy has only the
    attribute), and :func:`provenance_of` is what reads whichever exist.
    """
    attrs = provenance.attrs_for(engine=engine, profile=profile, stage=stage, extra=extra)
    for name, value in attrs.items():
        ncid.put_att(NC_GLOBAL, name, value)
    return attrs


def read_provenance(filename: str | os.PathLike[str]) -> provenance.Stamp | None:
    """The stamp ``filename`` carries **in its own bytes**, or ``None`` if it carries none.

    Survives a rename, a copy and a hardlink, which is the entire reason it exists: a ``.call``
    sidecar is keyed by filename, so a hardlinked name carries no sidecar stamp (observed
    for a 1.25 GB CIP product). One implementation, in the v3.5 engine:
    :func:`arrayprobe_uiops.provenance.read_in_file_stamp`.
    """
    return provenance.read_in_file_stamp(filename)


def provenance_of(filename: str | Path) -> provenance.Stamp:
    """Both carriers, reconciled -- raising rather than choosing when they disagree.

    Reads the attribute inside ``filename`` and the ``.call`` sidecar beside it, and:

    * raises :class:`arrayprobe.provenance.ProvenanceDisagreement` when both state a field and
      state it differently -- **the guard that provenance carried in the file exists
      for**. Neither carrier outranks the other, so there is no tie to break: one of them
      describes a run that did not write these bytes;
    * returns the attribute's stamp when only it exists (the hardlink case);
    * returns the sidecar's stamp when only it exists (every product written before today);
    * raises :class:`arrayprobe.provenance.Unstamped` when neither exists.

    Agreement is field-by-field over the fields **both** carriers state, so a sidecar that records
    no engine and an attribute that names one is agreement, not conflict -- see
    :func:`arrayprobe.provenance.disagreements`.
    """
    inside = read_provenance(filename)
    beside = provenance.read(filename)
    differences = provenance.disagreements(beside, inside)
    if differences:
        raise provenance.ProvenanceDisagreement(Path(filename), differences)
    if inside is not None:
        return inside
    if beside is not None:
        return beside
    raise provenance.Unstamped(filename)


def engine_of(filename: str | Path) -> str:
    """The engine that wrote ``filename``, from **either** carrier, or a refusal.

    :func:`arrayprobe.provenance.engine_of` asks the sidecar alone, so it cannot answer for a
    renamed, copied or hardlinked product. This asks the bytes first and the sidecar second, and
    is otherwise the same contract: it never returns a default, never infers an engine from a
    date, a filename or a neighbouring file, and raises

    * :class:`~arrayprobe.provenance.ProvenanceDisagreement` when the carriers conflict,
    * :class:`~arrayprobe.provenance.Unstamped` when neither exists,
    * :class:`~arrayprobe.provenance.EngineUnrecorded` when what exists does not say --
      which is still the honest answer for every product written before 2026-09-18.
    """
    stamp = provenance_of(filename)
    if stamp.engine is None:
        raise provenance.EngineUnrecorded(filename, stamp)
    return stamp.engine


def write_record_block(ncid: NcFile, varid: int, start: int, block: npt.ArrayLike) -> None:
    """``imgProc_sm.m:873-929`` fused: append ``block`` at 0-based record ``start``.

    ``block`` is in **C/on-disk order** (time first) because the MATLAB ``'`` at
    those call sites has already been absorbed -- that is the whole point of the
    cancellation noted in the module docstring.  Passing a MATLAB-order array here
    is the one easy mistake, so the shape is checked against the variable's
    trailing dimensions.
    """
    arr = np.asarray(block)
    var = ncid.variable(varid)
    trailing = tuple(var.shape[1:])
    n = arr.shape[0] if arr.ndim else 1
    expected = (n,) + trailing
    if arr.shape != expected:
        raise ValueError(
            f"write_record_block expects C/on-disk order {expected} for variable "
            f"{var.name!r}, got {arr.shape}. If you have a MATLAB-order array, use "
            "put_var(ncid, varid, start, count, data) instead."
        )
    with _quiet_netcdf4_setitem():
        var[start:start + n, ...] = arr
