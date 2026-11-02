# SPDX-License-Identifier: BSD-3-Clause
"""NCAR OAP raw decoder -- ``read_binary_PMS.m``.

The format is an XML preamble (terminated by a literal ``</OAP>`` line) followed
by a flat stream of fixed **4116-byte records**: a 2-byte probe-type tag, nine
big-endian ``uint16`` header fields, then 4096 bytes of raw image data with
**no compression at all** -- unlike DMT's byte-level RLE (:mod:`arrayprobe.readers.dmt`)
or SPEC's run-length words (:mod:`arrayprobe.readers.spec`). The probe-type tag
routes each record to one of three output files (2DC, F2DC, 2DP); nothing else
about decoding a record depends on which type it is.

**Byte order is big-endian** (``fopen(...,'r','b')``, MATLAB's ``'ieee-be'``) --
the opposite of DMT's little-endian raw stream.

**The image reshape has no reversal.** ``reshape(data, n, 4096/n)`` is a plain
column-major reshape of the flat 4096-byte payload into an ``(n, 4096/n)``
MATLAB array (``n`` is 4 for 2DC/2DP, 8 for F2DC). Unlike DMT's byte-reversed
8-groups, this is passed straight to :func:`arrayprobe.ncio.put_var`, which
performs the MATLAB-order-in/on-disk-order-out conversion itself.

**A preserved bug, found by tracing every ``netcdf.putVar`` call's file handle
against its variable id, not by reading the branch labels: the ``'C6'`` tag
(``probetype == [67, 54]``, ``:147-166``) writes its nine scalar fields to the
*2DC file* (`f`), not the F2DC file (`f1`) its own comment claims.** Only the
image write on that branch (``:159``) correctly targets ``f1``. The scalar
writes use variable ids that were allocated on ``f1`` (``varid02..varid92``)
but are passed to ``netcdf.putVar(f, ...)``, MATLAB's low-level call, which
resolves the id **within whichever file handle it is given** -- so the write
lands on `f`'s *own* variable of the same numeric id. Both files declare their
ten variables in identical order (year, month, ..., tas, data), so id-for-id
this happens to hit the correctly *named* variable, just in the wrong file:
a `'C6'` record's year/month/day/... land in the 2DC output, at the F2DC
write-counter's index (``kk2-1``) -- a different index sequence than 2DC's
own counter (``kk``), so it can silently overwrite an unrelated 2DC record's
scalar fields while leaving that record's image untouched, or extend the 2DC
file with scalar-populated, image-empty (fill-value) trailing rows. Meanwhile
the F2DC file gets `'C6'` **images with no matching scalar fields** at that
same index, since nothing in this branch writes them to `f1`. Verified by
constructing a synthetic file and tracing both ``f`` and ``f1`` on the real
MATLAB under Octave: a `'C6'` record's `second`/`millisec`/`tas` show up in
the **2DC** output, not the F2DC one. Flagged for the UIOOPS authors
-- likely a copy-paste of the `'C1'` branch
above it that missed updating the file handle on nine of its ten lines.

**Preserved verbatim, not fixed**: the ``'C6'`` branch below writes scalars
to the 2DC file/varids and the image to the F2DC file/varids, exactly
mirroring the bug. The ``'C4'`` tag (``probetype == [67, 52]``) has no such
bug -- all ten of its writes correctly target `f1`, at its own independent
counter (``kk3``).

**The trailing EOF probe (``:215-222``) is a byte-by-byte peek-and-rewind
with no observable effect beyond "does a full next record exist".** MATLAB
reads up to 4116 individual bytes checking ``feof`` after each one, then
unconditionally seeks back exactly 4116 bytes -- a no-op if that many bytes
were actually available, which is the only case where the loop continues.
This port reproduces the *outcome* (a trailing partial record, less than
4116 bytes, is never decoded) via a strict read-or-stop check rather than
the byte-by-byte mechanism, since the mechanism itself has no effect a
caller can observe. The first record has no probe in front of it, so a
file whose first record is short is handled apart (:func:`_first_record_short`).

**Not ported: the ``'*'``-glob and ``outfilename == '1'`` auto-naming
branches (``:8-33``).** Driver-script conveniences for
``automaticDataProcessing.m``; this port's callers always pass an explicit
output base path, the same simplification already made for
:func:`arrayprobe.readers.dmt.read_binary_DMT`.
"""

from __future__ import annotations

import numpy as np

from .. import ncio
from ..matlab_compat import MatlabIndexError

__all__ = ["read_binary_PMS"]

_RECORD_BYTES = 4116  # 2 (tag) + 9*2 (header fields) + 4096 (data)
_HEADER_FIELDS = ("hour", "minute", "second", "year", "month", "day",
                   "tas", "millisec", "wkday")
_SCALAR_FIELDS = ("year", "month", "day", "hour", "minute", "second",
                   "millisec", "wkday", "tas")

_N_2DC = 4
_N_F2DC = 8
_N_2DP = 4

_TAG_2DC = (67, 49)     # 'C1'
_TAG_F2DC_A = (67, 54)  # 'C6' -- the buggy branch, see module docstring
_TAG_F2DC_B = (67, 52)  # 'C4'
_TAG_2DP_PREFIX = 80    # 'P*'


def _def_output(filename: str, n: int):
    """One output file: eight timestamp vars, ``tas``, and the packed image.

    ``:45-59`` -- dims declared ``[ImgRowlen(n) ImgBlocklen(4096/n) time]``,
    MATLAB order, same convention as :mod:`arrayprobe.readers.dmt` and
    :mod:`arrayprobe.readers.spec`. Variables are declared in the same order
    (year, month, day, hour, minute, second, millisec, wkday, tas, data) for
    every output file -- load-bearing for the `'C6'` bug above, which relies
    on both files assigning identical numeric ids to identically-named vars.
    """
    f = ncio.create(filename, "clobber")
    dim_time = f.def_dim("time", ncio.NC_UNLIMITED)
    dim_row = f.def_dim("ImgRowlen", n)
    dim_block = f.def_dim("ImgBlocklen", 4096 // n)
    varids = {
        "year": f.def_var("year", "short", dim_time),
        "month": f.def_var("month", "byte", dim_time),
        "day": f.def_var("day", "byte", dim_time),
        "hour": f.def_var("hour", "byte", dim_time),
        "minute": f.def_var("minute", "byte", dim_time),
        "second": f.def_var("second", "byte", dim_time),
        "millisec": f.def_var("millisec", "short", dim_time),
        "wkday": f.def_var("wkday", "short", dim_time),
        "tas": f.def_var("tas", "double", dim_time),
        "data": f.def_var("data", "int", [dim_row, dim_block, dim_time]),
    }
    f.end_def()
    return f, varids


def _write_scalars(f, varids, index: int, header: dict) -> None:
    for name in _SCALAR_FIELDS:
        f.put_var(varids[name], index, 1, header[name])


def _write_image(f, varids, index: int, image_matlab: np.ndarray) -> None:
    n, blocklen = image_matlab.shape
    f.put_var(varids["data"], [0, 0, index], [n, blocklen, 1], image_matlab)


def _skip_xml_header(fh) -> None:
    """``:103-106`` -- read text lines until one strips to literally ``</OAP>``."""
    line = bytearray()
    while True:
        b = fh.read(1)
        if not b:
            # fgetl returns a last line that has no newline, so a file ending
            # in ``</OAP>`` still ends the header (then there are no records).
            if line.decode("ascii", errors="replace").strip() == "</OAP>":
                return
            raise ValueError("no </OAP> header terminator found before EOF")
        if b == b"\n":
            if line.decode("ascii", errors="replace").strip() == "</OAP>":
                return
            line.clear()
        else:
            line += b


def _first_record_short(chunk: bytes) -> None:
    """What ``:109-123`` make of a first record cut short by the end of the file.

    The first record is read without the EOF probe that guards every later one
    (``:215-222``), so a short one reaches the tag tests. Octave-measured
    (``tests/test_reader_edge_octave.py::PmsAgainstOctave``): no bytes at all end the run
    cleanly (``fgetl`` has already left the file at its end); one byte dies at
    ``:127``'s ``probetype(2)``; a recognised tag dies at the branch's
    ``reshape`` of a short ``data``; an unrecognised tag is printed and the run
    ends. Raises :class:`~arrayprobe.matlab_compat.MatlabIndexError` for the
    two deaths.
    """
    if not chunk:
        return
    if len(chunk) < 2:
        raise MatlabIndexError(
            "read_binary_PMS.m:127: probetype(2) of a 1-byte record (truncated file)")
    tag = (chunk[0], chunk[1])
    if tag in (_TAG_2DC, _TAG_F2DC_A, _TAG_F2DC_B) or tag[0] == _TAG_2DP_PREFIX:
        raise MatlabIndexError(
            f"read_binary_PMS.m: reshape of a {max(0, len(chunk) - 20)}-byte data block "
            "to 4096 bytes -- the first record is truncated")


def _reshape_matlab(data: np.ndarray, n: int) -> np.ndarray:
    """``reshape(data, n, 4096/n)`` -- MATLAB column-major, no byte reversal."""
    return data.reshape((n, data.shape[0] // n), order="F")


def read_binary_PMS(infilename, outfilename):  # noqa: N802,N803
    """``read_binary_PMS.m`` -- raw NCAR-OAP file to three probe-type outputs.

    Writes ``<outfilename>.2dc.cdf``, ``<outfilename>.f2dc.cdf`` and
    ``<outfilename>.2dp.cdf``. Returns ``(n_2dc, n_f2dc_c6, n_f2dc_c4, n_2dp)``
    -- the four raw MATLAB write-counters (``kk``, ``kk2``, ``kk3``, ``kk1``),
    kept separate rather than summed because ``'C6'`` and ``'C4'`` records
    are not equivalent: see the module docstring for what each actually
    writes and where.
    """
    f_2dc, v_2dc = _def_output(f"{outfilename}.2dc.cdf", _N_2DC)
    f_f2dc, v_f2dc = _def_output(f"{outfilename}.f2dc.cdf", _N_F2DC)
    f_2dp, v_2dp = _def_output(f"{outfilename}.2dp.cdf", _N_2DP)

    kk = kk1 = kk2 = kk3 = 0  # 0-based; MATLAB's kk/kk1/kk2/kk3 start at 1

    try:
        with open(infilename, "rb") as fh:
            _skip_xml_header(fh)
            first = True
            while True:
                chunk = fh.read(_RECORD_BYTES)
                if len(chunk) < _RECORD_BYTES:  # :215-222's outcome, see docstring
                    if first:
                        _first_record_short(chunk)
                    break
                first = False
                tag = (chunk[0], chunk[1])
                fields = np.frombuffer(chunk[2:20], dtype=">u2")
                header = dict(zip(_HEADER_FIELDS, (int(v) for v in fields), strict=True))
                data = np.frombuffer(chunk[20:], dtype=np.uint8)

                if tag == _TAG_2DC:
                    image = _reshape_matlab(data, _N_2DC)
                    _write_scalars(f_2dc, v_2dc, kk, header)
                    _write_image(f_2dc, v_2dc, kk, image)
                    kk += 1
                elif tag == _TAG_F2DC_A:  # 'C6' -- upstream bug, see docstring
                    image = _reshape_matlab(data, _N_F2DC)
                    _write_scalars(f_2dc, v_2dc, kk2, header)   # wrong file, preserved
                    _write_image(f_f2dc, v_f2dc, kk2, image)    # right file
                    kk2 += 1
                elif tag == _TAG_F2DC_B:  # 'C4' -- correct
                    image = _reshape_matlab(data, _N_F2DC)
                    _write_scalars(f_f2dc, v_f2dc, kk3, header)
                    _write_image(f_f2dc, v_f2dc, kk3, image)
                    kk3 += 1
                elif tag[0] == _TAG_2DP_PREFIX:
                    image = _reshape_matlab(data, _N_2DP)
                    _write_scalars(f_2dp, v_2dp, kk1, header)
                    _write_image(f_2dp, v_2dp, kk1, image)
                    kk1 += 1
    finally:
        f_2dc.close()
        f_f2dc.close()
        f_2dp.close()

    return kk, kk2, kk3, kk1
