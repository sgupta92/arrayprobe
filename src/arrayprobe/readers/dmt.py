# SPDX-License-Identifier: BSD-3-Clause
"""DMT probe raw decoder -- ``read_binary_DMT.m``.

The raw file is a flat sequence of **4112-byte records**: eight ``uint16`` of
timestamp (year, month, day, hour, minute, second, millisecond, weekday), then
4096 bytes of a **byte-level run-length compressed** image block -- a
different compression scheme from the SPEC probes' own word-oriented one
(:mod:`arrayprobe.readers.spec`), even though the two share the same
downstream canvas convention (8 diode-words x 1700 slices, an 0xAA boundary
sentinel, ``-1`` padding beyond the last real slice) that ``imgProc_sm``
already expects.

**The compression scheme, read directly from ``:99-140`` since nothing else
documents it.** Each of the 4096 payload bytes is either a control byte or a
literal, walked left to right:

- **bit 5 set** (``byte & 0x20``) -- a marker. Consumes just this one byte;
  nothing is decoded from it.
- **top two bits 00** -- a literal run: the next ``(byte & 0x1F) + 1`` bytes
  are copied through unchanged.
- **top two bits 10** -- a zero run: ``(byte & 0x1F) + 1`` copies of ``0x00``,
  with no further bytes consumed (the count is the whole payload).
- **top two bits 01** -- a fill run: ``(byte & 0x1F) + 1`` copies of ``0xFF``,
  likewise self-contained.
- **top two bits 11** (and bit 5 clear) -- no-op; the byte is simply skipped.

**Two preserved quirks, both structural rather than incidental:**

1. **The 4096th byte of every record is never read.** The control-byte scan
   is bounded ``while i<4096`` (MATLAB, 1-based) -- the last payload byte can
   only ever be a literal *inside* a run that was already truncated by the
   ``i < length(bytes)`` guard in the literal-copy loop (:117), never a
   control byte in its own right. This mirrors ``read_binary_SPEC.m``'s "last
   record is never a primary" quirk in shape, though the mechanism differs.
2. **The 8-byte reassembly is byte-reversed within each group.** ``:165-166``
   builds each output word from ``decomp(dd+7), decomp(dd+6), ..., decomp(dd)``
   -- descending, not ascending. Transcribed as read; a plausible-looking
   ascending version would silently mirror every image horizontally.

After decompression, the code searches for the first run of **eight
consecutive sync bytes** and reassembles everything after it into 8-byte
groups -- the same canvas convention SPEC's ``get_img`` consumes, which is why
nothing downstream of this reader needs to know DMT and SPEC compress
differently. If a record decompresses to shorter than 1700 groups, row
``len+1`` is set to the sentinel and rows beyond that to ``-1``, matching
:func:`arrayprobe.readers.spec._ImageCanvas`'s own tail convention.

**Four more preserved behaviours, each measured under Octave on the vendored
source** (``tests/test_reader_edge_octave.py::DmtAgainstOctave``):

3. **A sync byte is any byte ``0xA0``-``0xAF``**, not only the sentinel
   ``0xAA``: ``:148`` compares one hex digit of a char array (see
   :func:`_sync_bytes`). ``exact_sync=True`` opts into the exact byte.
4. **A record of 1700 groups or more writes the previous record's image.** The
   canvas is rewritten only when the record is shorter (``:176``), so the
   buffer goes out as the last shorter record left it (zeros before the first).
5. **A record of 1-7 groups, or of none, stops the run** at ``:177``
   (:class:`NonconformantAssignmentError`).
6. **A truncated tail stops the run** unless it is under 20 bytes (the EOF
   probe, ``:212-219``) or holds a 4095-byte payload (:func:`_tail_after`).
   A record whose high hex digits hold no run of eight sync bytes stops it too
   (:class:`DecompressionError`): the search then runs through the low digits
   and indexes past the array.
"""

from __future__ import annotations

import os

import numpy as np

from .. import ncio
from ..matlab_compat import MatlabIndexError

__all__ = ["DecompressionError", "NonconformantAssignmentError", "read_binary_DMT",
           "read_binary_DMT_parallel"]

IMG_ROWLEN = 8
IMG_BLOCKLEN = 1700
_RECORD_BYTES = 4112
_PAYLOAD_BYTES = 4096
_SENTINEL = 0xAA

# :35-42.  DMT's own header var types -- one field differs from SPEC's
# (`_TIME_VARS` in readers/spec.py): wkday is 'short' here, 'byte' there.
_TIME_VARS = (
    ("year", "short"),
    ("month", "byte"),
    ("day", "byte"),
    ("hour", "byte"),
    ("minute", "byte"),
    ("second", "byte"),
    ("millisec", "short"),
    ("wkday", "short"),
)
_TIME_FIELDS = tuple(name for name, _ in _TIME_VARS)
# :85-92's read order, which is also the write order above.
_HEADER_FIELDS = _TIME_FIELDS


class DecompressionError(ValueError):
    """A record's decompressed stream has no run of eight sync bytes.

    MATLAB's search (``:147-160``) has no exit for this case: it runs on
    through the low hex digits of its char array and dies indexing past the
    array, or, if it finds a run there, at ``:177`` (Octave-measured).
    """


class NonconformantAssignmentError(ValueError):
    """``read_binary_DMT.m:177`` dies: a record reassembles to 1-7 groups.

    ``length`` of an *n*-by-8 matrix is ``max(n, 8)``, so for *n* < 8 the
    assignment ``decomp_convert1(1:8,:) = decomp_convert`` puts *n* rows into
    eight (Octave 11.3: ``=: nonconformant arguments (op1 is 8x8, op2 is 3x8)``).
    Zero groups dies the same way under Octave, whose ``hex2dec`` of an empty
    selection returns a scalar 0 and so makes a 1-by-8 row.
    """


def _decompress_record(payload: np.ndarray) -> np.ndarray:
    """``:94-140`` -- byte-level run-length expansion of one 4096-byte block.

    ``payload`` is the raw ``uint8`` bytes (the ``bytes``/``data`` array in
    the MATLAB, already as integer VALUES rather than the hex-string form the
    MATLAB builds and re-parses -- an implementation difference with no
    behavioural one, since ``dec2hex``/``hex2dec`` round-trip exactly).

    Returns the decompressed byte values, a 1-D ``uint8`` array that may be
    longer or shorter than 4096 depending on how many runs it contains.

    The control scan's bound is the constant ``i<4096`` (``:108``), not the
    payload's length, so a payload shorter than 4095 bytes -- the tail of a
    truncated file -- is indexed past its end, and MATLAB dies at ``:109``'s
    ``b1full(i,:)``. That raises :class:`~arrayprobe.matlab_compat.MatlabIndexError`
    here. A 4095-byte payload decodes: its last control byte is at 4095.
    """
    n = len(payload)
    out: list[int] = []
    i = 0  # 0-based; MATLAB's `i` is 1-based, so this is MATLAB's i - 1.
    while i < _PAYLOAD_BYTES - 1:  # :108 -- MATLAB `while i<4096`, 1-based
        if i >= n:
            raise MatlabIndexError(
                f"read_binary_DMT.m:109: b1full({i + 1},:) exceeds the {n}-byte payload "
                "(a truncated record)")
        b = int(payload[i])
        i += 1
        if b & 0x20:  # :112 -- marker byte, consumes only itself
            continue
        count = (b & 0x1F) + 1  # :105, :116/:127/:133
        top2 = b >> 6
        if top2 == 0b00:  # :114 -- literal run
            for _ in range(count):
                # :117 -- `if i < length(bytes)`, checked in MATLAB's 1-based
                # `i` *after* it was advanced to the next byte to read. The
                # 0-based equivalent excludes the payload's last byte: MATLAB
                # never reads 1-based index n (Python 0-based n-1), so the
                # guard here is `i >= n - 1`, not `i >= n`.
                if i >= n - 1:
                    break
                out.append(int(payload[i]))
                i += 1
        elif top2 == 0b10:  # :125 -- zero run, no further bytes consumed
            out.extend([0x00] * count)
        elif top2 == 0b01:  # :131 -- fill run, no further bytes consumed
            out.extend([0xFF] * count)
        # top2 == 0b11: :137 -- no-op, byte already consumed above
    return np.asarray(out, dtype=np.uint8)


def _sync_bytes(decomp: np.ndarray, exact_sync: bool) -> np.ndarray:
    """Which decompressed bytes the boundary search counts as ``'AA'``.

    ``:148`` reads ``if decomp(i)=='AA'``, where ``decomp`` is an *N*-by-2
    char array of hex-digit pairs. ``decomp(i)`` is a LINEAR index, so for
    ``i <= N`` it is one character, the byte's high hex digit, and ``'A'=='AA'``
    scalar-expands to ``[1 1]``, which ``if`` takes. The search therefore counts
    every byte in ``0xA0``-``0xAF``, not only ``0xAA`` -- measured under Octave
    (``tests/test_reader_edge_octave.py::DmtAgainstOctave``), the same predicate
    ``read_binary_SEA.m:161`` has. ``exact_sync=True`` is the opt-in exact-byte
    test, which is what the sentinel means and not what the MATLAB does.
    """
    if exact_sync:
        return decomp == _SENTINEL
    return (decomp & 0xF0) == 0xA0


def _find_boundary(decomp: np.ndarray, *, exact_sync: bool = False) -> int:
    """``:144-160`` -- index (0-based) one past the first run of eight sync bytes.

    See :func:`_sync_bytes` for which bytes count. MATLAB's search is bounded
    only by its index: when the high digits hold no run it goes on through the
    LOW hex digits (``decomp(N+1:2N)``) and then dies indexing past ``2N``;
    a run it does find there leaves ``dd`` empty and dies at ``:177`` instead
    (Octave-measured). Either way the record does not decode, so this raises
    :class:`DecompressionError`.
    """
    accepted = _sync_bytes(decomp, exact_sync)
    if len(accepted) >= 8:
        # A run of >=8 True values starting at k is present when the
        # 8-window sum at k equals 8 -- cheap, vectorized equivalent of the
        # MATLAB's own running `count` scan.
        window = np.convolve(accepted.astype(np.int64), np.ones(8, dtype=np.int64), mode="valid")
        hit = np.flatnonzero(window == 8)
        if hit.size:
            return int(hit[0]) + 8  # one past the end of that 8-run
    raise DecompressionError(
        "no run of eight sync bytes in the decompressed record's high hex digits; "
        "read_binary_DMT.m's search (:147-160) then runs through the low digits and "
        "dies, at the index past the array or at :177"
    )


def _reassemble(decomp: np.ndarray, start: int,
                previous: np.ndarray | None = None) -> np.ndarray:
    """``:162-180`` -- 8-byte groups from ``start`` to the end, byte-reversed
    within each group, onto the 1700-row canvas ``decomp_convert1``.

    ``decomp_convert1`` is allocated once (``:3``) and rewritten only inside
    the branch taken when the decompressed record is shorter than 1700 groups
    (``:176``). A record of 1700 groups or
    more therefore writes the buffer as the previous record left it --
    ``previous``, which is ``zeros(1700,8)`` before any record has filled it
    -- and none of its own groups. A record of fewer than eight groups dies
    at ``:177`` (:class:`NonconformantAssignmentError`). Both measured under
    Octave.
    """
    n_groups = max(0, (len(decomp) - start) // 8)
    if n_groups >= IMG_BLOCKLEN:
        if previous is None:
            return np.zeros((IMG_BLOCKLEN, IMG_ROWLEN), dtype=np.int64)
        return previous
    if n_groups < 8:
        raise NonconformantAssignmentError(
            f"read_binary_DMT.m:177: =: nonconformant arguments (op1 is 8x8, op2 is "
            f"{max(n_groups, 1)}x8) -- the record reassembles to {n_groups} groups, and "
            "length() of an n-by-8 matrix is 8 for n < 8")
    canvas = np.full((IMG_BLOCKLEN, IMG_ROWLEN), -1, dtype=np.int64)
    block = decomp[start : start + n_groups * 8].reshape(n_groups, 8)
    canvas[:n_groups, :] = block[:, ::-1]  # :165-166 -- descending within a group
    canvas[n_groups, :] = _SENTINEL  # :178
    return canvas


def _decode_one(payload: np.ndarray, previous: np.ndarray | None = None, *,
                exact_sync: bool = False) -> np.ndarray:
    decomp = _decompress_record(payload)
    start = _find_boundary(decomp, exact_sync=exact_sync)
    return _reassemble(decomp, start, previous)


def _tail_after(pos: int, size: int) -> str:
    """What ``:212-219``'s probe and the next pass make of the bytes after ``pos``.

    The probe reads twenty bytes one at a time and stops the loop only when a
    read fails, so fewer than 20 bytes end the file cleanly (``"end"``). With
    20 or more the loop reads another header and ``fread(fid,4096,'uchar')``:
    a whole record decodes (``"record"``); a 4095-byte payload decodes too
    (its last control byte is 4095); anything shorter dies at ``:109``
    (``"die"``). Octave-measured (``tests/test_reader_edge_octave.py::DmtAgainstOctave``).
    """
    left = size - pos
    if left < 20:
        return "end"
    if left - 16 >= _PAYLOAD_BYTES - 1:
        return "record"
    return "die"


class _ImageFile:
    """One output file: the eight timestamp variables plus the packed image.

    Structurally identical to ``readers.spec._ImageFile`` except for
    ``wkday``'s type (see ``_TIME_VARS`` above) -- kept separate rather than
    parametrizing the SPEC writer, since the two formats have no other reason
    to share code and a shared writer would couple them for no benefit.
    """

    def __init__(self, filename, *, block: int = 256) -> None:
        self.ncid = ncio.create(filename, "clobber")
        dim_time = self.ncid.def_dim("time", ncio.NC_UNLIMITED)
        dim_row = self.ncid.def_dim("ImgRowlen", IMG_ROWLEN)
        dim_block = self.ncid.def_dim("ImgBlocklen", IMG_BLOCKLEN)
        self.varids = [self.ncid.def_var(n, t, dim_time) for n, t in _TIME_VARS]
        self.varid_data = self.ncid.def_var("data", "int", [dim_row, dim_block, dim_time])
        self.ncid.end_def()
        self.count = 0
        self._block = block
        self._times: list[tuple[int, ...]] = []
        self._images: list[np.ndarray] = []

    def append(self, header: dict, canvas: np.ndarray) -> None:
        """Queue one decoded record, flushing once ``block`` have piled up.

        ``count`` advances here, not at flush time: it is the record count
        :func:`read_binary_DMT` returns, and that must describe what was
        decoded rather than how the writes were batched.
        """
        self._times.append(tuple(header[f] for f in _TIME_FIELDS))
        self._images.append(canvas)
        self.count += 1
        if len(self._images) >= self._block:
            self.flush()

    def flush(self) -> None:
        """Write the queued records as one netCDF block, then empty the queue.

        ``start`` is recovered from ``count`` rather than tracked separately,
        so the record index stays a single fact. The comment below is the one
        real difference from ``spec.py``'s otherwise identical writer, and it
        is a difference in the *decoder's* output shape, not in this contract.
        """
        if not self._images:
            return
        start = self.count - len(self._images)
        times = np.asarray(self._times, dtype=np.int64)
        for k, varid in enumerate(self.varids):
            self.ncid.put_var(varid, start, times.shape[0], times[:, k])
        # canvas is already (1700, 8) = (ImgBlocklen, ImgRowlen); stacking
        # records gives (n, 1700, 8) directly -- the on-disk order
        # write_record_block wants, no transpose needed (unlike spec.py's
        # writer, whose per-record images are (ImgRowlen, ImgBlocklen)).
        block = np.stack(self._images)
        ncio.write_record_block(self.ncid, self.varid_data, start, block)
        self._times.clear()
        self._images.clear()

    def close(self) -> None:
        """Flush whatever is still queued, then close the netCDF file.

        Required, not tidying: an unflushed final partial batch would leave the
        file short by up to ``block`` records with nothing downstream reporting
        it -- ``imgProc_sm`` would just process a shorter flight.
        """
        self.flush()
        self.ncid.close()


def _read_record(fh):
    """``:85-94`` -- one header and up to 4096 payload bytes from ``fh``.

    Returns ``(header, payload)``. A record too short to decode raises where
    ``:109`` dies (see :func:`_decompress_record`); the check is made here,
    before the header is unpacked, because a header cut short is only ever
    followed by an empty payload.
    """
    chunk = fh.read(16)  # :85-92, eight little-endian uint16
    payload_bytes = fh.read(_PAYLOAD_BYTES) if len(chunk) == 16 else b""  # :94
    if len(payload_bytes) < _PAYLOAD_BYTES - 1:
        raise MatlabIndexError(
            f"read_binary_DMT.m:109: b1full({len(payload_bytes) + 1},:) exceeds the "
            f"{len(payload_bytes)}-byte payload (a truncated record)")
    header = dict(zip(_HEADER_FIELDS, (int(v) for v in np.frombuffer(chunk, dtype="<u2")),
                      strict=True))
    return header, np.frombuffer(payload_bytes, dtype=np.uint8)


def read_binary_DMT(infilename, outfilename, *, progress=None,  # noqa: N802,N803
                    exact_sync: bool = False):
    """``read_binary_DMT.m`` -- raw DMT probe file to ``<outfilename>``.

    Unlike ``read_binary_SPEC`` in the earlier translation (not included in this package), DMT
    writes one
    output file (no H/V channel split -- the format has none) and the input
    is a flat sequence of fixed 4112-byte records with no sliding window: the
    MATLAB's ``while feof(fid)==0`` reads and decodes every record until end
    of file, checked by trial-reading (and rewinding) the next 20 bytes
    (``:212-219``) rather than by a record-count computed up front. The first
    record is read unconditionally, so a file too short to hold one raises;
    so does a tail of 20 bytes or more that is not a whole record (see
    :func:`_tail_after`).

    ``exact_sync`` (default ``False``, MATLAB's behaviour) makes the boundary
    search count only the byte ``0xAA`` rather than every byte whose high hex
    digit is ``A`` -- see :func:`_sync_bytes`.

    Returns the number of records written.
    """
    out = _ImageFile(str(outfilename))
    previous = None
    try:
        with open(infilename, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            while True:
                header, payload = _read_record(fh)
                canvas = _decode_one(payload, previous, exact_sync=exact_sync)
                previous = canvas
                out.append(header, canvas)
                if progress is not None:
                    progress(out.count)
                # :211-219 -- trial-read the next 20 bytes to detect EOF.
                if _tail_after(fh.tell(), size) == "end":
                    break
    finally:
        out.close()
    return out.count


# ---------------------------------------------------------------------------
# Opt-in parallel decode. Port space: byte-identical, default serial, no new
# dependency. Byte identity: tests/test_dmt_parallel.py.
#
# ---------------------------------------------------------------------------


def _n_decodable_records(infilename) -> int:
    """Whole records in the file, ``floor(size / 4112)``: the ones the parts
    decode. What follows them -- nothing, a record's worth of 4111 bytes, or a
    tail that stops the run -- is the parent's, after the merge
    (:func:`_tail_after`).
    """
    return os.path.getsize(infilename) // _RECORD_BYTES


#: A canvas no record can produce (every real value is a byte or -1). A part
#: returns it for a record of 1700 groups or more whose image is the previous
#: record's, when that previous record belongs to an earlier part; the merge,
#: which sees the records in file order, substitutes it.
_STALE = np.full((IMG_BLOCKLEN, IMG_ROWLEN), -2, dtype=np.int64)


def _decode_dmt_range(args) -> dict:
    """Worker: decode records ``[lo, hi)`` into ``.npy`` blocks under ``part``.

    Spills every ``block`` records to disk, so a part never holds more than
    ``block`` canvases. On the first exception at record ``k`` it stops and
    returns the exception with ``k``, as the serial loop raises before
    appending record ``k``.
    """
    infilename, part, lo, hi, block, report_every, *rest = args
    exact_sync = bool(rest[0]) if rest else False
    os.makedirs(part, exist_ok=True)
    files: list[tuple[str, str]] = []
    hdrs: list[np.ndarray] = []
    imgs: list[np.ndarray] = []
    fail_at = None
    error = None
    previous = _STALE  # the image before this part's first record is not ours

    def _spill() -> None:
        j = len(files)
        hp = os.path.join(part, f"h{j:06d}.npy")
        ip = os.path.join(part, f"i{j:06d}.npy")
        np.save(hp, np.stack(hdrs))
        np.save(ip, np.stack(imgs))
        files.append((hp, ip))
        hdrs.clear()
        imgs.clear()

    with open(infilename, "rb") as fh:
        fh.seek(lo * _RECORD_BYTES)
        for k in range(lo, hi):
            rec = fh.read(_RECORD_BYTES)
            fields = np.frombuffer(rec[:16], dtype="<u2").astype(np.int64)
            payload = np.frombuffer(rec[16:], dtype=np.uint8)
            try:
                canvas = _decode_one(payload, previous, exact_sync=exact_sync)
            except Exception as exc:  # noqa: BLE001 -- re-raised by the parent
                fail_at, error = k, exc
                break
            previous = canvas
            hdrs.append(fields)
            imgs.append(canvas)
            if len(imgs) >= block:
                _spill()
            done = k - lo + 1
            if report_every and done % report_every == 0:
                # The SPEC decoder's liveness helper (logging, flushed, fresh handler per
                # call, no-op without a stdout), so the port keeps no bare print.
                from arrayprobe_uiops.spec_core import _report_part_progress
                _report_part_progress(os.path.basename(part), done, hi - lo, unit="records")
    if imgs:
        _spill()
    return {"files": files, "fail_at": fail_at, "error": error}


def _merge_dmt_parts(parts, outfilename, progress, *, tail=None) -> int:
    """Append every part's records, in file order, through one serial writer.

    Reusing :class:`_ImageFile` with the serial append sequence keeps the
    netCDF call sequence identical, not merely equivalent. A part's
    :data:`_STALE` canvas becomes the image written before it, as the serial
    loop's carried buffer would be. Stops at the lowest failing record, closes
    the file (as the serial ``finally`` does) and re-raises that record's
    exception.

    ``tail``, ``(infilename, exact_sync)``, finishes the file after the whole
    records the way the serial loop does: a 4111-byte record decodes, a
    shorter tail of 20 bytes or more raises.
    """
    error = None
    previous = None
    out = _ImageFile(str(outfilename))
    try:
        for part in parts:
            for hp, ip in part["files"]:
                hdr = np.load(hp)
                img = np.load(ip)
                for row, canvas in zip(hdr, img, strict=True):
                    if canvas[0, 0] == _STALE[0, 0]:
                        canvas = (previous if previous is not None
                                  else np.zeros((IMG_BLOCKLEN, IMG_ROWLEN), dtype=np.int64))
                    previous = canvas
                    header = dict(zip(_HEADER_FIELDS, (int(v) for v in row),
                                      strict=True))
                    out.append(header, canvas)
                    if progress is not None:
                        progress(out.count)
            if part["fail_at"] is not None:
                error = part["error"]
                break
        if error is None and tail is not None:
            infilename, exact_sync = tail
            with open(infilename, "rb") as fh:
                size = os.fstat(fh.fileno()).st_size
                fh.seek(_n_decodable_records(infilename) * _RECORD_BYTES)
                while _tail_after(fh.tell(), size) != "end":
                    header, payload = _read_record(fh)
                    canvas = _decode_one(payload, previous, exact_sync=exact_sync)
                    previous = canvas
                    out.append(header, canvas)
                    if progress is not None:
                        progress(out.count)
    finally:
        out.close()
    if error is not None:
        raise error
    return out.count


def read_binary_DMT_parallel(  # noqa: N802 -- matches the serial name
    infilename,
    outfilename,
    *,
    jobs: int,
    workdir=None,
    progress=None,
    spawn_retries: int = 2,
    report_every: int = 0,
    block: int = 256,
    exact_sync: bool = False,
) -> int:
    """:func:`read_binary_DMT` across ``jobs`` processes, byte-identical output.

    Every DMT record decodes from its own 4112 bytes, so records split at any
    multiple of 4112 with no priming; the one thing carried from record to
    record, the image a record of 1700 groups or more repeats, is resolved in
    the merge (:data:`_STALE`), and the bytes after the last whole record are
    handled there too. ``jobs <= 1`` or a file of at most one
    record delegates to the serial function. ``progress(count)`` is called
    from the parent per record, the same sequence as serial. A decode failure
    leaves the same partial file and raises the same exception as serial.
    ``spawn_retries`` restarts a pool that died (``BrokenProcessPool``) from a
    fresh temporary directory with ``spec.SpawnRetryWarning``, as
    ``spec.read_binary_SPEC_parallel`` does. ``report_every`` (default 0,
    silent) prints a liveness line per part every that many records.
    """
    import concurrent.futures
    import concurrent.futures.process
    import shutil
    import tempfile
    import time
    import warnings

    from arrayprobe_uiops.spec_core import SpawnRetryWarning

    outfilename = os.fspath(outfilename)
    n = _n_decodable_records(infilename)
    if jobs <= 1 or n <= 1:
        return read_binary_DMT(infilename, outfilename, progress=progress,
                               exact_sync=exact_sync)

    jobs = min(jobs, n)
    edges = [round(k * n / jobs) for k in range(jobs + 1)]
    for attempt in range(spawn_retries + 1):
        tmp = tempfile.mkdtemp(prefix="s2dmtparallel_", dir=workdir)
        try:
            tasks = [
                (os.fspath(infilename), os.path.join(tmp, f"p{k:03d}"),
                 edges[k], edges[k + 1], block, report_every, exact_sync)
                for k in range(jobs)
                if edges[k + 1] > edges[k]
            ]
            try:
                with concurrent.futures.ProcessPoolExecutor(
                        max_workers=len(tasks)) as pool:
                    parts = list(pool.map(_decode_dmt_range, tasks))
            except concurrent.futures.process.BrokenProcessPool:
                if attempt >= spawn_retries:
                    raise
                warnings.warn(
                    f"parallel decode of {os.path.basename(os.fspath(infilename))}: "
                    f"the worker pool died before completing (attempt {attempt + 1} "
                    f"of {spawn_retries + 1}); restarting it from a fresh temporary "
                    "directory",
                    SpawnRetryWarning, stacklevel=2)
                time.sleep(2.0 * (attempt + 1))
                continue
            return _merge_dmt_parts(parts, outfilename, progress,
                                    tail=(os.fspath(infilename), exact_sync))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    raise AssertionError("unreachable")  # pragma: no cover
