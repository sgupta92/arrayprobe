# SPDX-License-Identifier: BSD-3-Clause
"""SEA (CIP/2DC) raw decoder -- ``read_binary_SEA.m``.

**"This only works for MC3E field campaign"** is the MATLAB's own comment
(``:4``), and the port inherits that scope: this is one probe family's raw
format, distinct from SPEC/DMT/PMS, read in a tagged, offset-navigated
container (a directory record of 16 bytes -- ``tagNumber``, ``dataOffset``,
``numberBytes``, ``samples``, ``bytesPerSample``, ``type``, three ``param``
bytes, ``address`` -- precedes each chunk). Byte order is **little-endian**
(``fopen(...,'r','l')``), like DMT, unlike PMS.

Two directory-tag values are handled; everything else is walked past without
action (the source never errors or logs on an unrecognized tag -- only
``tagNumber == 999`` is a recognized "end of this run" marker):

- **``tagNumber == 33000, numberBytes == 4098``** -- a CIP image record.
  Writes to the ``.CIP.cdf`` output. Its image payload uses **the exact same
  byte-level run-length scheme as DMT** (:mod:`arrayprobe.readers.dmt`) --
  same marker bit, same literal/zero-run/fill-run encoding -- reused here via
  :func:`arrayprobe.readers.dmt._decompress_record` rather than
  reimplemented, since the two are the same algorithm, not merely similar.
- **``tagNumber == 5000, numberBytes == 4096``** -- a 2DC record.
  **The source cannot run this branch**: ``:270`` calls
  ``netcdf.putVar(f1, varid91, ...)``, and ``varid91`` is never assigned by
  any ``netcdf.defVar`` anywhere in the file -- the ``.2DC.cdf`` output (see
  ``:56-64``) declares no ``tas`` variable at all. MATLAB raises an
  "undefined variable" error the first time this branch is reached. This
  port raises :class:`SeaUndefinedVariableError` at the same point, on the
  theory used throughout this package: a MATLAB crash is a real, checkable
  fact about the source, not something to paper over. Flagged for the UIOOPS
  authors.

**The peek-and-rewind pattern, twice, more elaborately than DMT's or PMS's.**
Both branches read a directory record, a timestamp block, and the image
payload as a *lookahead* -- extracting the values into variables -- and then
``fseek`` back by the exact byte count just consumed, before re-reading only
the *last* directory record. The net effect on the file position is as if
only the directory records had been read at all; the timestamp and image
bytes are peeked, not permanently consumed from the stream. The CIP branch's
rewind is a fixed 4150 bytes, so it is transcribed literally: a payload cut
short by the end of the file moves where the re-read lands.

**``readTime`` reads two 18-byte timestamp groups and returns only the
second** (``:329-343`` -- the loop variable ``time`` is overwritten each
iteration). The first group's bytes are consumed and discarded; preserved
here as a genuine double-read, not simplified to a single read, since a
record whose stream runs out between the two groups behaves differently
under each interpretation.

**A CIP record with no complete run of eight sync bytes in its decompressed
stream is silently dropped, not an error** (``:173-180``) -- unlike DMT,
whose search runs on past the array and dies. A sync byte is any byte
``0xA0``-``0xAF``, since ``:161`` compares one hex digit
(``exact_sync=True`` opts into ``0xAA`` alone), and a run that ends on the
stream's last byte counts as none. SEA's own search caps at
``i == length(decomp)`` and sets a "weird" flag; the record is skipped
entirely (nothing written, the write-counter does not advance), and a
running total of how many records this happened to is printed once at the
very end. This port counts the same total and returns it rather than
printing it. A record that decompresses to **nothing** (every byte a no-op) is
different: ``decomp`` is then undefined at ``:161``, because ``:280`` clears it after every record,
and MATLAB dies; the port raises :class:`SeaUndefinedVariableError` there.

**A SEA-specific reassembly quirk, different from DMT's.** ``:198-200``
pads a short image with ``-1`` starting at index ``length(decomp_convert)``
(1-based) through ``1700`` -- which, being an inclusive MATLAB range,
**overwrites the last real decoded row as well as the padding**, unlike
DMT's ``len+1`` convention which leaves the last real row alone. Preserved
verbatim: a CIP record of 8 to 1699 groups loses its final row of real data
to the padding value. Below eight groups ``length`` is 8, so every row
survives and rows up to 7 are zeros (:func:`_reassemble_sea`).

Not ported: the ``'*'``-glob and ``outfilename == '1'`` auto-naming branches
(``:8-27``), for the same reason as DMT and PMS -- this port's callers
always pass an explicit output base path.
"""

from __future__ import annotations

import os
import struct

import numpy as np

from .. import ncio
from ..matlab_compat import MatlabIndexError
from .dmt import _decompress_record, _sync_bytes

__all__ = ["read_binary_SEA", "SeaUndefinedVariableError"]

_DIR_BYTES = 16
_TIME_GROUP_BYTES = 18  # 9 * uint16
_SENTINEL = 0xAA
_IMG_ROWLEN = 8
_IMG_BLOCKLEN = 1700

_TAG_CIP = 33000
_NBYTES_CIP = 4098
_TAG_2DC = 5000
_NBYTES_2DC = 4096


class SeaUndefinedVariableError(RuntimeError):
    """``read_binary_SEA.m:270`` references ``varid91``, never assigned.

    MATLAB errors here the first time a 5000/4096-tagged record is reached;
    see the module docstring for the full trace.
    """


def _read_dir(fh) -> tuple[int, ...] | None:
    """``readDir`` -- 16-byte little-endian directory record, or ``None`` at EOF."""
    raw = fh.read(_DIR_BYTES)
    if len(raw) < _DIR_BYTES:
        return None
    tag, offset, nbytes, samples, bps = struct.unpack_from("<5H", raw, 0)
    typ, p1, p2, p3 = raw[10], raw[11], raw[12], raw[13]
    addr, = struct.unpack_from("<H", raw, 14)
    return (tag, offset, nbytes, samples, bps, typ, p1, p2, p3, addr)


def _read_time(fh) -> tuple[int, ...]:
    """``readTime`` -- two 18-byte groups; only the second is returned."""
    # Seeded with the empty tuple rather than ``None``: the loop always runs twice,
    # so the seed can never be returned, and typing it as a tuple is what lets the
    # declared ``tuple[int, ...]`` return type stand without an ignore.  Behaviour
    # is unchanged -- the only reachable return is the second group's unpack.
    last: tuple[int, ...] = ()
    for _ in range(2):
        raw = fh.read(_TIME_GROUP_BYTES)
        last = struct.unpack("<9H", raw)
    return last  # year, month, day, hour, minute, second, fracsec, maxfreq, bls


def _inner_loop_eof(partial: bytes) -> tuple[int, int]:
    """What ``read_binary_SEA.m`` does when ``readDir`` (``:88``) hits EOF.

    ``readDir`` (``:312-326``) concatenates whatever ``fread`` calls still
    returned, so ``datatemp`` holds only the complete fields of ``partial``
    (empty when fewer than two bytes remain). MATLAB then dies at the first
    index past its end:

    - ``:90`` ``datatemp(1)`` on an empty vector (measured under Octave 8.4:
      ``datatemp(1): out of bound 0``), or ``datatemp(3)`` when the tag is
      33000 and fewer than three fields survived; any other tag loops once
      more and the next ``readDir`` returns empty, so ``:90`` again;
    - ``:97`` ``ttt(1)`` when a partial 33000/4098 record enters the CIP
      branch and ``readTime`` reads nothing; ``:221``/``:229`` likewise for
      5000/4096;
    - ``:283`` ``datatemp(2)`` for a tag-999 record cut before its offset.

    A tag-999 record whose offset survived leaves the inner loop normally:
    ``(999, offset)`` is returned for the caller's ``:282-286`` handling.
    """
    vals = struct.unpack_from(f"<{min(len(partial) // 2, 5)}H", partial)

    def die(line: str, what: str) -> MatlabIndexError:
        return MatlabIndexError(
            f"read_binary_SEA.m:{line}: {what} -- EOF inside the inner directory "
            f"loop ({len(partial)}-byte partial directory record)")

    if not vals:
        raise die("90", "datatemp(1) of an empty directory record")
    tag = vals[0]
    if tag == _TAG_CIP:
        if len(vals) < 3:
            raise die("90", "datatemp(3) of a partial directory record")
        if vals[2] == _NBYTES_CIP:
            raise die("97", "ttt(1) of an empty timestamp")
    if tag == _TAG_2DC:
        if len(vals) < 3:
            raise die("221", "datatemp(3) of a partial directory record")
        if vals[2] == _NBYTES_2DC:
            raise die("229", "ttt(1) of an empty timestamp")
    if tag == 999:
        if len(vals) < 2:
            raise die("283", "datatemp(2) of a partial directory record")
        return (999, vals[1])
    raise die("90", "datatemp(1) of an empty directory record")


def _outer_partial_dir(partial: bytes) -> tuple[int, int] | None:
    """What ``:78`` makes of a directory record cut short by the end of the file.

    ``readDir`` keeps the fields ``fread`` still returned. With fewer than two,
    ``:79``'s ``-datatemp(2)`` dies (an empty file included: ``feof`` is false
    before the first read). A tag of 999 skips the inner loop, and the probe
    then ends the run; any other tag enters it, whose ``readDir`` gets nothing,
    so ``:90`` dies. Returns ``None`` for the clean end.
    """
    vals = struct.unpack_from(f"<{min(len(partial) // 2, 5)}H", partial)
    if len(vals) < 2:
        raise MatlabIndexError(
            f"read_binary_SEA.m:79: datatemp(2) of a {len(partial)}-byte directory record")
    if vals[0] == 999:
        return None
    raise MatlabIndexError(
        "read_binary_SEA.m:90: datatemp(1) of an empty directory record -- EOF inside "
        f"the inner directory loop ({len(partial)}-byte partial outer record)")


def _find_boundary_or_none(decomp: np.ndarray, *, exact_sync: bool = False) -> int | None:
    """``:157-180`` -- SEA's own boundary search: ``None`` in place of a crash.

    A sync byte is any byte ``0xA0``-``0xAF`` (``decomp(i)=='AA'`` reads one
    hex digit; :func:`arrayprobe.readers.dmt._sync_bytes`), or only ``0xAA``
    under the opt-in ``exact_sync``. ``None`` is MATLAB's ``nWierd = 1``: no
    run of eight, **or a run that ends on the last byte** -- ``:173``'s
    ``i==length(decomp)`` test runs after ``:167``'s ``count == 8`` test in the
    same pass and overrides it (Octave-measured).
    """
    accepted = _sync_bytes(decomp, exact_sync)
    if len(accepted) >= 8:
        window = np.convolve(accepted.astype(np.int64), np.ones(8, dtype=np.int64),
                             mode="valid")
        hit = np.flatnonzero(window == 8)
        if hit.size and int(hit[0]) + 8 < len(decomp):
            return int(hit[0]) + 8
    return None


def _reassemble_sea(decomp: np.ndarray, start: int) -> np.ndarray:
    """``:183-200`` -- 8-byte groups, byte-reversed, then the off-by-one pad.

    ``decomp_convert(L:1700,:) = -1`` with ``L = length(decomp_convert)``
    (MATLAB, 1-based inclusive). For *n* >= 8 groups ``L`` is *n*, so the pad
    overwrites the last real row -- see the module docstring. For *n* < 8,
    ``length`` of the *n*-by-8 matrix is 8: all *n* rows survive, rows *n*+1
    to 7 are the zeros MATLAB grows the matrix with, and the pad starts at row
    8. No groups at all gives the same shape as one all-zero group, because
    ``hex2dec`` of an empty selection is 0 under Octave. 1700 groups or more
    are written as their first 1700. All measured under Octave
    (``tests/test_reader_edge_octave.py::SeaAgainstOctave``).
    """
    n_groups = max(0, (len(decomp) - start) // 8)
    canvas = np.full((_IMG_BLOCKLEN, _IMG_ROWLEN), -1, dtype=np.int64)
    usable = min(n_groups, _IMG_BLOCKLEN)
    if usable:
        block = decomp[start : start + usable * 8].reshape(usable, 8)
        canvas[:usable, :] = block[:, ::-1]
    if usable < _IMG_BLOCKLEN:
        length = max(usable, 8)  # MATLAB length() of an n-by-8 matrix
        canvas[usable : length - 1, :] = 0
        canvas[length - 1 :, :] = -1  # :198-200 -- overwrites the last real row too
    return canvas


def read_binary_SEA(infilename, outfilename, *, exact_sync: bool = False):  # noqa: N802,N803
    """``read_binary_SEA.m`` -- raw SEA file to ``.CIP.cdf`` and ``.2DC.cdf``.

    Returns ``(n_cip, n_weird_cip, n_2dc)`` -- ``n_weird_cip`` counts CIP
    records silently dropped for lack of a boundary run (MATLAB's
    ``nWierdTotal``). Raises :class:`SeaUndefinedVariableError` if a
    5000/4096-tagged record is ever reached, matching the MATLAB crash.

    ``exact_sync`` (default ``False``, MATLAB's behaviour) makes the boundary
    search count only the byte ``0xAA`` rather than every byte whose high hex
    digit is ``A`` -- see :func:`_find_boundary_or_none`.
    """
    f_cip = ncio.create(f"{outfilename}.CIP.cdf", "clobber")
    dim_time = f_cip.def_dim("time", ncio.NC_UNLIMITED)
    dim_row = f_cip.def_dim("ImgRowlen", _IMG_ROWLEN)
    dim_block = f_cip.def_dim("ImgBlocklen", _IMG_BLOCKLEN)
    v_cip = {
        "year": f_cip.def_var("year", "double", dim_time),
        "month": f_cip.def_var("month", "double", dim_time),
        "day": f_cip.def_var("day", "double", dim_time),
        "hour": f_cip.def_var("hour", "double", dim_time),
        "minute": f_cip.def_var("minute", "double", dim_time),
        "second": f_cip.def_var("second", "double", dim_time),
        "millisec": f_cip.def_var("millisec", "double", dim_time),
        "wkday": f_cip.def_var("wkday", "double", dim_time),
        "data": f_cip.def_var("data", "double", [dim_row, dim_block, dim_time]),
    }
    f_cip.end_def()

    # The .2DC.cdf file and its variables are declared unconditionally, exactly
    # as :50-64 does -- even though the 5000/4096 branch that would write to
    # them can never run (SeaUndefinedVariableError, see module docstring).
    # Nothing here is written to; the dict of ids is intentionally discarded.
    f_2dc = ncio.create(f"{outfilename}.2DC.cdf", "clobber")
    dim_time2 = f_2dc.def_dim("time", ncio.NC_UNLIMITED)
    dim_row2 = f_2dc.def_dim("ImgRowlen", _IMG_ROWLEN)
    dim_block2 = f_2dc.def_dim("ImgBlocklen", _IMG_BLOCKLEN)
    f_2dc.def_var("year", "double", dim_time2)
    f_2dc.def_var("month", "double", dim_time2)
    f_2dc.def_var("day", "double", dim_time2)
    f_2dc.def_var("hour", "double", dim_time2)
    f_2dc.def_var("minute", "double", dim_time2)
    f_2dc.def_var("second", "double", dim_time2)
    f_2dc.def_var("millisec", "double", dim_time2)
    f_2dc.def_var("wkday", "double", dim_time2)
    f_2dc.def_var("data", "double", [dim_row2, dim_block2, dim_time2])
    f_2dc.end_def()

    kk_cip = kk_2dc = 0
    n_weird = 0

    try:
        with open(infilename, "rb") as fh:
            endfile = False
            while not endfile:
                here = fh.tell()
                rec = _read_dir(fh)
                if rec is None:
                    # Only the first pass can get here: after it, :290-297's
                    # probe has seen 16 more bytes before the loop goes on.
                    fh.seek(here)
                    rec = _outer_partial_dir(fh.read())
                    if rec is None:
                        break
                tag = rec[0]
                # doffset1/doffset2 (:79, :283) are computed but only ever used
                # relative to a later tag==999 record within the SAME inner
                # loop -- see :286's fseek. No action at the outer level itself.
                doffset1 = -rec[1]

                n_tag_next = tag == 999
                while not n_tag_next:
                    here = fh.tell()
                    rec = _read_dir(fh)
                    if rec is None:
                        # F5: EOF inside the inner directory loop. MATLAB has
                        # no guard here; it dies (or, for a partial tag-999
                        # record, leaves the loop) -- see _inner_loop_eof.
                        fh.seek(here)
                        rec = _inner_loop_eof(fh.read())
                    tag, offset = rec[0], rec[1]

                    if tag == _TAG_CIP and rec[2] == _NBYTES_CIP:
                        # :93-110 -- one more dir record (its tag/offset are
                        # what the tag==999 check below actually sees, since
                        # :109 re-reads the identical bytes), then a peek at
                        # the timestamp and 4098-byte payload that :108
                        # rewinds past -- net file-position effect is as if
                        # only the one dir record had been read. The rewind
                        # is real here, not simplified away: skipping it
                        # desyncs every read after the first CIP record in a
                        # file, which is exactly the bug this comment used to
                        # paper over.
                        rec2 = _read_dir(fh)
                        if rec2 is None:
                            # F5: :93's readDir returns short at EOF and :95's
                            # readTime reads nothing, so MATLAB dies at :97.
                            raise MatlabIndexError(
                                "read_binary_SEA.m:97: ttt(1) of an empty timestamp "
                                "-- EOF after a 33000/4098 directory record")
                        ttt = _read_time(fh)
                        payload = fh.read(4098)
                        # :108 rewinds a fixed 4150 bytes (16 + 36 + 4098) and
                        # :109 re-reads the directory record there. A payload
                        # cut to 4096 or 4097 bytes by the end of the file
                        # lands the rewind that many bytes early, and the
                        # re-read sees shifted bytes; the literal seek keeps
                        # that. The position is always past 4150 here.
                        fh.seek(fh.tell() - 4150)
                        reread = _read_dir(fh)
                        if len(payload) < 4096:
                            # :110 ``data = data1(1:4096)`` -- MATLAB dies with
                            # 'Index exceeds matrix dimensions' on a short read.
                            raise MatlabIndexError(
                                "read_binary_SEA.m:110: data1(1:4096) on a "
                                f"{len(payload)}-byte payload (truncated file)")
                        if reread is None:  # pragma: no cover -- 16 bytes always follow
                            raise MatlabIndexError("read_binary_SEA.m:109: short re-read")
                        rec2 = reread
                        tag, offset = rec2[0], rec2[1]
                        data = np.frombuffer(payload[:4096], dtype=np.uint8)

                        decomp = _decompress_record(data)
                        if len(decomp) == 0:
                            # Every byte a no-op: :124-150 never assign `decomp`, :280 cleared
                            # the last record's, so :161's `decomp(i)` is an undefined variable
                            # and MATLAB dies (measured under Octave 11.3, 2026-09-27). A stream
                            # that decodes to something but has no 0xAA boundary is the graceful
                            # "weird" case below.
                            raise SeaUndefinedVariableError(
                                "read_binary_SEA.m:161: 'decomp' is undefined -- the CIP "
                                "record decompressed to nothing (every byte a no-op)")
                        start = _find_boundary_or_none(decomp, exact_sync=exact_sync)
                        if start is None:
                            n_weird += 1
                        else:
                            canvas = _reassemble_sea(decomp, start)
                            header = {
                                "year": ttt[0], "month": ttt[1], "day": ttt[2],
                                "hour": ttt[3], "minute": ttt[4], "second": ttt[5],
                                "millisec": ttt[6], "wkday": 1,
                            }
                            for name in ("year", "month", "day", "hour", "minute",
                                         "second", "millisec", "wkday"):
                                f_cip.put_var(v_cip[name], kk_cip, 1, header[name])
                            f_cip.put_var(v_cip["data"], [0, 0, kk_cip],
                                          [_IMG_ROWLEN, _IMG_BLOCKLEN, 1], canvas.T)
                            kk_cip += 1

                    elif tag == _TAG_2DC and rec[2] == _NBYTES_2DC:
                        raise SeaUndefinedVariableError(
                            "read_binary_SEA.m:270 references varid91, which is "
                            "never assigned by any netcdf.defVar in the source -- "
                            "MATLAB errors here, on the first 5000/4096-tagged "
                            "record; see arrayprobe.readers.sea's module docstring"
                        )

                    if tag == 999:
                        doffset2 = offset
                        n_tag_next = True
                        seek_by = doffset2 + doffset1
                        if seek_by:
                            # :285 MATLAB's fseek returns -1 and leaves the
                            # position unchanged for a target before BOF or
                            # past EOF (measured under Octave 8.4); Python's
                            # seek raises (before BOF) or succeeds (past EOF).
                            target = fh.tell() + seek_by
                            if 0 <= target <= os.fstat(fh.fileno()).st_size:
                                fh.seek(target)

                if endfile:
                    break

                # :290-297 -- the trailing EOF probe; see DMT's/PMS's module
                # docstrings for why the outcome (not the byte-by-byte
                # mechanism) is what this port reproduces.
                peek = fh.read(16)
                if len(peek) < 16:
                    endfile = True
                else:
                    fh.seek(-16, 1)
    finally:
        f_cip.close()
        f_2dc.close()

    return kk_cip, n_weird, kk_2dc
