# SPDX-License-Identifier: BSD-3-Clause
"""Shared leaf: the SPEC record geometry, packet markers and marker scan both engines use.

Moved verbatim from ``arrayprobe.readers.spec``;
that module re-imports them, so its names still resolve.  Constants and pure
functions: no module state, no numba, nothing a worker pickles.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from arrayprobe_uiops.matlab_compat import MatlabIndexError

# --------------------------------------------------------------------------
# Record geometry -- read_binary_SPEC.m:170-182, :150-156
# --------------------------------------------------------------------------

HEADER_WORDS = 8
DATA_WORDS = 2048
RECORD_WORDS = HEADER_WORDS + DATA_WORDS + 1  # + the discarded trailing word
RECORD_BYTES = RECORD_WORDS * 2  # 4114

IMG_ROWLEN = 8  # read_binary_SPEC.m:45  -- 8 words of 16 diodes
IMG_BLOCKLEN = 1700  # read_binary_SPEC.m:46
DIODES = IMG_ROWLEN * 16  # 128

# Packet markers, as the little-endian uint16 the ASCII pair decodes to.
MARKER_2S = 12883  # 0x3253 -- 'S','2' on disk; image packet   (:198)
MARKER_HK = 18507  # 0x484B -- 'K','H' on disk; housekeeping   (:290)
MARKER_MK = 19787  # 0x4D4B -- 'K','M' on disk; mask           (:307)

# The alternating '1010...' boundary slice (:244), as sixteen2int packs it.
BOUNDARY_WORD = 43690  # 0b1010101010101010

_MASK_COUNT = 4095  # 0b0000111111111111  -- nH / nV        (:199)
_MASK_TIMING = 4096  # 0b0001000000000000  -- timing flag     (:199)
_MASK_RUN = 16256  # 0b0011111110000000  -- shadowed run     (:227)
_MASK_CLEAR = 127  # 0b0000000001111111  -- clear run        (:228)
_MASK_NEWSLICE = 16384  # 0b0100000000000000 -- new-slice bit  (:233)


def _marker_positions(buf) -> np.ndarray:
    """1-based positions of every marker word in the scanned half of the window.

    ``read_binary_SPEC.m:320-322`` walks past a non-marker word one at a time and
    does nothing else, and on real ORACLES data that is ~97% of the words: 99328
    of the first 102400.  Jumping straight to the next marker is the same walk
    with the no-ops elided, and it is the difference between minutes and hours
    over a 1 GB flight file.
    """
    head = buf[:DATA_WORDS]
    hit = (head == MARKER_2S) | (head == MARKER_HK) | (head == MARKER_MK)
    return np.flatnonzero(hit) + 1


def _next_marker(markers, iii: int, size: int | None = None) -> int:
    """Where the ``else: iii=iii+1`` walk would next find something to do.

    ``size`` is the window's length. A window shorter than the scan (the lone
    primary of a file holding less than one whole record) has no word at
    ``size + 1``, so the walk stops there and the next ``_at`` raises where
    MATLAB's ``buf(iii)`` does, instead of jumping silently to the scan's end.
    """
    if markers is None:
        return iii + 1
    k = int(np.searchsorted(markers, iii, side="left"))
    if k < markers.size:
        return int(markers[k])
    if size is not None and size < DATA_WORDS:
        return size + 1
    return DATA_WORDS + 1


# --------------------------------------------------------------------------
# Moved verbatim from arrayprobe.readers.spec (v3.1.4 cut S2, 2026-10-10); that
# module re-exports every name below, same objects.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordHeader:
    """The eight timestamp words of one raw record (``readRecord``, :170-182).

    Source: ``readRecord`` in ``read_binary_SPEC.m:170-182`` (UIOOPS v3.1.4)."""

    year: int
    month: int
    wkday: int
    day: int
    hour: int
    minute: int
    second: int
    millisec: int

    @property
    def timehhmmss(self) -> float:
        """``hour*10000 + minute*100 + second + millisec/1000`` (:94)."""
        return self.hour * 10000 + self.minute * 100 + self.second + self.millisec / 1000


# --------------------------------------------------------------------------
# Buffer access
# --------------------------------------------------------------------------


def _at(buf: np.ndarray, k: int) -> int:
    """``buf(k)`` with MATLAB's 1-based index and MATLAB's out-of-range error."""
    if k < 1 or k > buf.size:
        raise MatlabIndexError(
            f"buf({k}) exceeds the {buf.size}-word decode window. MATLAB raises "
            "'Index exceeds matrix dimensions' here; stock v3.1.4 guards against it "
            "(read_binary_SPEC.m:222,226,233) but the ORACLES variant does not."
        )
    return int(buf[k - 1])


class _ImageCanvas:
    """``zeros(128, 1700)`` that grows on assignment, as a MATLAB array does.

    Columns are slices, rows are diodes, both 1-based on the public methods so the
    transcription stays visually identical to the source.
    """

    __slots__ = ("_a",)

    def __init__(self, ncols: int = IMG_BLOCKLEN) -> None:
        self._a = np.zeros((DIODES, ncols), dtype=np.uint8)

    def _ensure(self, col: int) -> None:
        if col > self._a.shape[1]:
            grown = np.zeros((DIODES, max(col, 2 * self._a.shape[1])), dtype=np.uint8)
            grown[:, : self._a.shape[1]] = self._a
            self._a = grown

    def set_run(self, lo: int, hi: int, col: int) -> None:
        """``img(lo:hi, col) = 1`` -- a no-op when ``hi < lo``, as in MATLAB."""
        self._ensure(col)
        if hi >= lo:
            self._a[lo - 1 : hi, col - 1] = 1

    def set_column(self, col: int, values: np.ndarray) -> None:
        """``img(:, col) = values`` for a full 128-element column."""
        self._ensure(col)
        self._a[:, col - 1] = values

    def set_rows(self, lo: int, hi: int, col: int, values: np.ndarray) -> None:
        """``img(lo:hi, col) = values``."""
        self._ensure(col)
        self._a[lo - 1 : hi, col - 1] = values

    def add_diff(self, diff: np.ndarray, first_col: int) -> None:
        """Union in a ``(129, n)`` difference array starting at ``first_col``.

        The vectorized run fill accumulates ``+1`` at each run's first row and
        ``-1`` one past its last; a cumulative sum down the rows then marks every
        covered diode.  ``> 0`` rather than ``== 1`` because runs within a slice
        overlap freely.
        """
        n = diff.shape[1]
        if n == 0:
            return
        self._ensure(first_col + n - 1)
        covered = np.cumsum(diff[:DIODES, :], axis=0) > 0
        self._a[:, first_col - 1 : first_col - 1 + n] |= covered.astype(np.uint8)

    def result(self) -> np.ndarray:
        """The grown array, exactly as ``get_img`` returns it to its caller."""
        return self._a


# --------------------------------------------------------------------------
# Run-length image decompression
# --------------------------------------------------------------------------


def _decode_runs_scalar(buf, iii, n_words, n_slices, canvas, i_slice, guard):
    """Literal transcription of ``read_binary_SPEC.m:223-241`` (H) / ``:257-275`` (V).

    ``iii`` has already been advanced past the five-word packet header, so word
    ``kkk`` of the particle is ``buf(iii+kkk)`` with ``kkk`` counting from 0.
    Returns nothing; the canvas is mutated in place.
    """
    jjj = 1
    kkk = 0
    limit = n_words - 2  # the last two words are the particle timestamp
    while (not guard or iii + kkk <= buf.size) and jjj <= n_slices and kkk < limit:
        word = _at(buf, iii + kkk)
        aa = (word & _MASK_RUN) // 128
        bb = word & _MASK_CLEAR
        canvas.set_run(min(DIODES, bb + 1), min(aa + bb, DIODES), i_slice + jjj)
        b_base = min(aa + bb, DIODES)
        kkk += 1
        while (
            (not guard or iii + kkk <= buf.size)
            and (_at(buf, iii + kkk) & _MASK_NEWSLICE) == 0
            and kkk < limit
        ):
            word = _at(buf, iii + kkk)
            aa = (word & _MASK_RUN) // 128
            bb = word & _MASK_CLEAR
            canvas.set_run(
                min(DIODES, b_base + bb + 1), min(b_base + aa + bb, DIODES), i_slice + jjj
            )
            b_base = min(b_base + aa + bb, DIODES)
            kkk += 1
        jjj += 1


def _decode_runs_fast(buf, iii, n_words, n_slices, canvas, i_slice, guard):
    """Vectorized equivalent of :func:`_decode_runs_scalar`.

    Three observations make the sequential loop collapse:

    * A slice ends at the first word whose bit 14 is set, so slice boundaries are
      ``flatnonzero`` of that bit -- no scan needed.
    * ``bBase`` is a *saturating* running sum of non-negative increments, so
      ``min(cumsum, 128)`` at each word equals the clamped recurrence: once the
      sum reaches 128 it can never come back down.
    * Every write is ``= 1`` over a row range, which a difference array plus one
      ``cumsum`` turns into a single array operation.

    Randomized equivalence against the scalar form is pinned in
    ``test_spec_reader.TestRunDecodeEquivalence``.
    """
    limit = n_words - 2
    if limit <= 0 or n_slices <= 0:
        return

    # How far the scalar loop may read.  Under the guard it stops at the window
    # edge; without it, an over-long packet must still raise from _at().
    end = iii + limit - 1
    if end > buf.size:
        if not guard:
            _at(buf, end)  # raises MatlabIndexError, as MATLAB does
        limit = max(0, buf.size - iii + 1)
        if limit == 0:
            return

    words = buf[iii - 1 : iii - 1 + limit].astype(np.int64)
    new_slice = (words & _MASK_NEWSLICE) != 0

    # Slice starts: word 0 always, then every word that raises the new-slice bit.
    starts = np.concatenate(([0], np.flatnonzero(new_slice[1:]) + 1))
    if starts.size > n_slices:
        starts = starts[:n_slices]
    consumed = int(starts[-1])
    # The final slice runs to the next start, or to the word budget.
    tail = np.flatnonzero(new_slice[consumed + 1 :]) + consumed + 1
    stop = int(tail[0]) if (starts.size == n_slices and tail.size) else limit
    words = words[:stop]

    aa = (words & _MASK_RUN) // 128
    bb = words & _MASK_CLEAR
    col = np.searchsorted(starts, np.arange(stop), side="right") - 1

    cum = np.cumsum(aa + bb)
    cum_before = np.concatenate(([0], cum[:-1]))
    base_at_start = cum_before[starts]  # cum just before each slice
    prev = cum_before - base_at_start[col]

    lo = np.minimum(DIODES, prev + bb + 1)
    hi = np.minimum(cum - base_at_start[col], DIODES)
    keep = hi >= lo
    if not keep.any():
        return

    diff = np.zeros((DIODES + 1, int(col[-1]) + 1), dtype=np.int32)
    np.add.at(diff, (lo[keep] - 1, col[keep]), 1)
    np.add.at(diff, (hi[keep], col[keep]), -1)
    canvas.add_diff(diff, i_slice + 1)


#: Below this many run words the scalar loop beats the vectorized one: setting up
#: a dozen NumPy calls costs more than iterating a handful of Python ints.  Real
#: ORACLES 2D-S data is dominated by 1-3 word particles (marine stratocumulus
#: drops shadow one or two diodes), so this branch carries most of the traffic --
#: and the two paths are pinned equivalent by
#: ``TestRunDecodeEquivalence.test_random_packets_agree``, which spans the
#: threshold in both directions.
_VECTOR_THRESHOLD = 12


def _decode_runs_auto(buf, iii, n_words, n_slices, canvas, i_slice, guard):
    """Pick whichever run decoder is cheaper for this particle.  Same result either way."""
    if n_words - 2 <= _VECTOR_THRESHOLD:
        _decode_runs_scalar(buf, iii, n_words, n_slices, canvas, i_slice, guard)
    else:
        _decode_runs_fast(buf, iii, n_words, n_slices, canvas, i_slice, guard)


_BIT_SHIFTS = {w: np.arange(w - 1, -1, -1, dtype=np.int64) for w in (16, 32, DIODES)}


def _bits(value: int, width: int) -> np.ndarray:
    """``dec2bin(value, width) - 48`` for the header slice's fixed widths.

    :func:`~arrayprobe.matlab_compat.dec2bin` is the general transcription and stays
    the reference; this is it specialized to the five calls per particle that
    ``_write_header_slice`` makes, which profiling put at 60% of decode time.  The
    two agree exactly whenever ``value < 2**width`` -- which every one of these does,
    ``tParticle`` being two 16-bit words -- and
    ``TestHeaderSlice.test_bit_helper_matches_dec2bin`` pins that.
    """
    return ((value >> _BIT_SHIFTS[width]) & 1).astype(np.uint8)


def _write_header_slice(canvas, i_slice, t_particle, n_word, pc, n_s, *, with_metadata):
    """``read_binary_SPEC.m:244-252`` -- the boundary slice and the header slice.

    Line 246 (``img(:,iSlice)=1``) is a dead store: line 248 overwrites the whole
    column.  It is left out rather than transcribed, because reproducing a write
    that is immediately and unconditionally discarded buys nothing and costs a
    read of the reader's attention.  Lines 248 and 249 are *also* redundant with
    each other -- ``dec2bin(t,128)`` and ``dec2bin(t,32)`` agree on rows 97-128
    for any ``t < 2^32``, which every particle timestamp is -- but the second is
    kept, since it is what pins rows 97-128 if a timestamp ever overflows.
    """
    # The alternating boundary pattern, which sixteen2int packs to eight 43690s.
    boundary = np.zeros(DIODES, dtype=np.uint8)
    boundary[0::2] = 1
    canvas.set_column(i_slice - 1, boundary)

    canvas.set_column(i_slice, _bits(t_particle, DIODES))
    canvas.set_rows(97, 128, i_slice, _bits(t_particle, 32))
    if with_metadata:
        canvas.set_rows(49, 64, i_slice, _bits(n_word, 16))
        canvas.set_rows(65, 80, i_slice, _bits(pc, 16))
        canvas.set_rows(81, 96, i_slice, _bits(n_s, 16))


# --------------------------------------------------------------------------
# Packing
# --------------------------------------------------------------------------


def sixteen2int(rows: np.ndarray) -> np.ndarray:
    """``read_binary_SPEC.m:328-335`` -- pack 16 diode rows MSB-first into a word.

    ``rows`` is ``(16, n)``; row 1 is bit 15.  Returns ``(n,)`` int64.  The
    all-alternating boundary slice packs to :data:`BOUNDARY_WORD`, which is the
    cheapest orientation check there is.
    """
    a = np.asarray(rows, dtype=np.int64)
    weights = (1 << np.arange(15, -1, -1, dtype=np.int64))[:, None]
    return (a * weights).sum(axis=0)


def _pack_image(img: np.ndarray) -> np.ndarray:
    """``:108-110`` -- the 8 x 1700 packed block MATLAB calls ``img1``."""
    block = img[:, :IMG_BLOCKLEN]
    return np.vstack([sixteen2int(block[m * 16 : (m + 1) * 16, :]) for m in range(IMG_ROWLEN)])


# --------------------------------------------------------------------------
# Sidecar CSVs
# --------------------------------------------------------------------------


def _as_single(value) -> float:
    """``single(value)``, returned as the exactly equal Python float.

    Same helper as ``arrayprobe_uiops.spec._as_single``, duplicated rather than
    imported: the port and the v3.5 engine stay independently importable
    (see the two-engines note), and this is two lines.
    """
    return float(np.float32(value))


def _matlab_f(value: float) -> str:
    """MATLAB's ``%f``: C's for finite values, ``NaN``/``Inf``/``-Inf`` otherwise.

    Same helper as ``arrayprobe_uiops.spec._matlab_f``; see its docstring.
    """
    if value != value:
        return "NaN"
    if value in (float("inf"), float("-inf")):
        return "Inf" if value > 0 else "-Inf"
    return f"{value:f}"


class SidecarWriter:
    """The three ``.csv`` files ``get_img`` appends to, buffered.

    Source: the appends of ``get_img`` in ``read_binary_SPEC.m:184-326`` (UIOOPS v3.1.4):
    ``.NV.csv`` at ``:210-211``, ``.tas.csv`` at ``:301-302``, ``.MK.csv`` at ``:314-315``.

    MATLAB opens, appends and closes on every single event.  Buffering changes
    the syscall pattern and nothing else: the lines, their order and their
    formatting are byte-identical -- including one formatting bug that is
    preserved deliberately.

    **The mask file has no line terminators.**  ``:313`` declares twenty ``%d``
    conversions but ``:315`` supplies nineteen values (``timeWord``, sixteen mask
    bits, ``timeStart``, ``timeEnd``).  MATLAB's ``fprintf`` stops as soon as the
    data runs out, emitting the literal text up to the unfilled conversion and
    dropping everything after it -- so each record ends ``..., `` and the trailing
    ``' \\n'`` is never written.  Every mask record in a run therefore lands on one
    single line.  Reproduced; a file that suddenly gained newlines would not
    compare against the reference.

    Files are opened in append mode, as MATLAB's ``fopen(...,'a')`` does: a second
    run over the same input adds to them rather than replacing them.
    """

    def __init__(self, outfilename, *, enabled: bool = True, output_txt: bool = False,
                 output_txt_path: str | None = None) -> None:
        self.outfilename = os.fspath(outfilename)
        self.enabled = enabled
        self.output_txt_enabled = output_txt
        # ``:215`` redirects into ``output.txt`` relative to MATLAB's cwd, so the
        # faithful default is the cwd. A parallel worker overrides it with its
        # own part file so the lines can be merged in record order (found
        # 2026-09-06: every worker was appending to the cwd file directly, in
        # completion order, and the merge was looking for a part file nobody
        # wrote -- see tests/test_spec_output_txt.py).
        self.output_txt_path = output_txt_path or "output.txt"
        self._nv: list[str] = []
        self._tas: list[str] = []
        self._mask: list[str] = []
        self._output: list[str] = []

    def nv(self, timehhmmss, nv_word) -> None:
        """``:209-212`` -- ``'%f, %d\\n'``."""
        if self.enabled:
            self._nv.append(f"{timehhmmss:f}, {int(nv_word):d}\n")

    def tas(self, timehhmmss, tas, time, n_twm, n_scm, n_hol, n_vol, n_vpd, n_hpd) -> None:
        """``:300-303`` -- ``'%f, %f, %f, %d, %d, %d, %d, %d, %d\\n'``.

        ``:291`` reads ``tas`` as a MATLAB single with no accept/reject gate
        (unlike v3.5's ``update_tas``), and ``:302`` builds the row as one array
        ``[timehhmmss tas time nTWM ...]``: once any element of a MATLAB array is
        single, the whole array is, so ``timehhmmss`` and ``time`` are also
        rounded to float32 here -- ``123454.999`` prints ``123455.000000`` and a
        ``time`` counter above 2**24 loses its low bits. Mirrors
        ``arrayprobe_uiops.spec.SidecarWriterV35.tas``, unconditionally rather than
        gated, because v3.1.4 has no gate to be unconditional about.
        """
        if self.enabled:
            self._tas.append(
                f"{_matlab_f(_as_single(timehhmmss))}, {_matlab_f(_as_single(tas))}, "
                f"{_matlab_f(_as_single(time))}, "
                f"{int(n_twm):d}, {int(n_scm):d}, {int(n_hol):d}, "
                f"{int(n_vol):d}, {int(n_vpd):d}, {int(n_hpd):d}\n"
            )

    def mask(self, time_word, mask_bits, time_start, time_end) -> None:
        """``:313-316`` -- nineteen values into twenty conversions.  See the class docstring."""
        if self.enabled:
            values = [int(time_word), *(int(b) for b in mask_bits), int(time_start), int(time_end)]
            self._mask.append(", ".join(str(v) for v in values) + ", ")

    def output_txt(self, n_h, n_v) -> None:
        """``:215`` -- ``system('echo nH nV >> output.txt')``, without the process spawn."""
        if self.output_txt_enabled:
            self._output.append(f"{int(n_h)} {int(n_v)}\n")

    def flush(self) -> None:
        """Append the buffered lines to the three sidecars, then drop the buffers.

        This is the only place the files are touched. MATLAB opens, writes and
        closes per event (``:209-212``, ``:300-303``, ``:313-316``); buffering
        and flushing produces the identical bytes in the identical order, and
        the append mode is what makes that true across several flushes and
        across a second run over the same input.

        A sidecar with nothing buffered is not created, which matches MATLAB:
        a run that never reaches an ``NV`` event writes no ``.NV.csv`` at all.
        Idempotent -- calling it twice writes nothing the second time.
        """
        for suffix, lines in (
            (".NV.csv", self._nv),
            (".tas.csv", self._tas),
            (".MK.csv", self._mask),
        ):
            if lines:
                with open(self.outfilename + suffix, "a", newline="") as fh:
                    fh.writelines(lines)
                lines.clear()
        if self._output:
            with open(self.output_txt_path, "a", newline="") as fh:
                fh.writelines(self._output)
            self._output.clear()

    def __enter__(self) -> SidecarWriter:
        return self

    def __exit__(self, *exc) -> None:
        self.flush()


# --------------------------------------------------------------------------
# Record iteration
# --------------------------------------------------------------------------


def iter_record_windows(path, start: int = 0, stop: int | None = None):
    """Yield ``(RecordHeader, buf)`` for each primary record, MATLAB's way.

    ``start``/``stop`` select a half-open range of primary records without
    building the ones before it. The default is the whole file, which is what
    every existing caller gets. The range exists for the parallel decode: a
    worker assigned windows ``[a, b)`` must be able to reach window *a* without
    paying for the *a* windows before it, and with a memory map that costs
    nothing -- record *i* is at a computable offset, so no scan is needed to
    find it. **These are 0-based**, unlike the rest of this port's public
    surface: they index this port's own window range, added for the parallel
    decode, not a MATLAB array -- so the global "every public index is
    MATLAB 1-based" convention (``docs/09-conventions.md``) does
    not apply to them, and this is the one place that says so explicitly.

    A worker reads one record **beyond** its last window, because window
    ``b-1`` is built from records ``b-1`` and ``b``. That overlap is what makes
    the ranges independent rather than merely adjacent.

    Reproduces ``read_binary_SPEC.m:83-160``: read records *N* and *N+1*,
    concatenate their 2048-word image buffers into the 4096-word decode window,
    then advance by one record.  **The final record is never a primary** -- the
    loop probes one byte past the pair and breaks -- so a file of *n* records
    yields *n-1* windows.  Preserved; see the module docstring, point 2.

    **A trailing partial record changes that count, and the window is short, not
    padded.** The EOF probe fails only when the byte it reads is past the end,
    so bytes after the last whole record keep the loop going for one more pair:
    the last whole record becomes a primary, continued by whatever
    ``fread(fid,2048,'uint16')`` returns from the partial one (none at all when
    fewer than 18 bytes remain). A file of *n* whole records plus any tail
    therefore yields *n* windows. A file shorter than one record yields a single
    window whose primary is itself short; the scan then indexes past it, and
    that raises from :func:`_at` where MATLAB's ``buf(iii)`` dies. An empty file,
    or one too short to hold a data word, raises here: ``get_img`` receives an
    empty ``buf`` and MATLAB dies at ``buf(1)``. All measured under Octave on
    both vendored trees (a reader edge-case Octave test).
    """
    size = os.path.getsize(path)
    n_records, tail = divmod(size, RECORD_BYTES)
    n_windows = record_window_count(path)
    lo = max(0, start)
    hi = n_windows if stop is None else min(stop, n_windows)
    if hi <= lo:
        return
    if n_records == 0:
        # The only window: a primary shorter than one record, nothing after it.
        n_words = _data_words_in(size)
        if n_words == 0:
            raise MatlabIndexError(
                f"buf(1) exceeds the 0-word decode window: a {size}-byte file holds no "
                "image word, and read_binary_SPEC.m's get_img indexes buf(1) regardless.")
        raw = np.fromfile(path, dtype="<u2", count=HEADER_WORDS + n_words)
        header = RecordHeader(*(int(v) for v in raw[:HEADER_WORDS]))
        yield header, raw[HEADER_WORDS:].astype(np.int64)
        return
    words = np.memmap(path, dtype="<u2", mode="r", shape=(n_records, RECORD_WORDS))
    tail_words = None
    if tail:
        n_tail = _data_words_in(tail)
        tail_words = np.fromfile(
            path, dtype="<u2", count=n_tail,
            offset=n_records * RECORD_BYTES + 2 * HEADER_WORDS) if n_tail else np.zeros(0, "<u2")

    for i in range(lo, hi):
        head = words[i, :HEADER_WORDS]
        header = RecordHeader(*(int(v) for v in head))
        primary = words[i, HEADER_WORDS : HEADER_WORDS + DATA_WORDS]
        if i + 1 < n_records:
            buf = np.concatenate(
                (primary, words[i + 1, HEADER_WORDS : HEADER_WORDS + DATA_WORDS]))
        elif tail_words is not None:
            buf = np.concatenate((primary, tail_words))
        else:
            # A one-record file: that record still enters the loop once, with a
            # short (2048-word) window.
            buf = np.asarray(primary)
        yield header, buf.astype(np.int64)


def _data_words_in(n_bytes: int) -> int:
    """Image words ``readRecord`` gets from a record of ``n_bytes`` bytes: the
    eight header ``fread`` calls take the first 16, ``fread(fid,2048,'uint16')``
    takes whole words after that, and an odd byte is left over."""
    return min(DATA_WORDS, max(0, (n_bytes - 2 * HEADER_WORDS) // 2))


def record_window_count(path) -> int:
    """How many decode windows ``read_binary_SPEC.m``'s loop makes of this file.

    *n* whole records give *n-1* (the last is never a primary), one whole record
    gives 1, and *n* whole records followed by a partial one give *n*: the
    partial record keeps the EOF probe from failing for one more pair. A file
    with no whole record gives 1, the window MATLAB builds and then dies on
    unless its primary holds enough words -- see :func:`iter_record_windows`.
    """
    n_records, tail = divmod(os.path.getsize(path), RECORD_BYTES)
    if n_records == 0:
        return 1
    if tail:
        return n_records
    return max(1, n_records - 1)


# Since 2026-09-15 this heartbeat is the one library message that
# cannot simply move behind ``arrayprobe.cli``'s handler (see
# ``_report_part_progress`` below) -- it runs inside a ``ProcessPoolExecutor``
# worker, a fresh interpreter on Windows' ``spawn`` start method that never
# sees whatever ``arrayprobe.cli`` configured in the parent process. Its own
# logger is used only to build the :class:`logging.LogRecord` (never given a
# persistent handler, and ``propagate = False`` so nothing here can double
# into a caller-configured "arrayprobe" handler) -- a bare ``import
# arrayprobe`` still installs nothing (this only runs when
# ``report_every > 0`` is passed explicitly, unchanged from the old
# ``print``).
_progress_logger = logging.getLogger(f"{__name__}._report_part_progress")
_progress_logger.propagate = False


def _report_part_progress(label: str, done: int, span: int, unit: str = "windows") -> None:
    """One liveness line from a part process to the stdout it inherited.

    A part runs in a ``ProcessPoolExecutor`` child, whose stdout is the parent's
    fd 1 -- under ``scripts/run_flight.py`` that is the worker's own log, the file
    ``_await_workers`` watches for growth (measured 2026-09-13 through the same
    ``Popen(stdout=file)`` chain ``_spawn_worker`` uses). A fresh
    :class:`logging.StreamHandler` bound to the *current* ``sys.stdout`` is
    built on every call, deliberately never cached: the old ``print`` looked
    up ``sys.stdout`` fresh on every call too (that is what let a test
    redirect it mid-run), and a handler cached from the first call would keep
    writing to whatever stream was current *then* -- exactly the bug a
    resident handler would introduce and the tests catch. ``handler.emit``
    flushes unconditionally, the same load-bearing property the old
    ``print(..., flush=True)`` had: a file-backed stdout is block-buffered,
    and an unflushed line would sit in the buffer until the part exits, which
    is exactly the silence this exists to end. ``print`` was a no-op when
    ``sys.stdout`` was ``None`` (a handle-less child) because ``print`` checks
    that itself; ``StreamHandler`` does not -- passing ``None`` makes it fall
    back to ``sys.stderr`` instead of doing nothing -- so that check is made
    explicit here to keep the same no-op behaviour.

    The shape ``[HH:MM:SS]   ...part pNNN n/N windows`` matches the runner's own
    ``log()`` lines, and deliberately does NOT match the run monitor's
    pattern for a cumulative count (``...<digits> records``).
    """
    if sys.stdout is None:
        return
    record = _progress_logger.makeRecord(
        _progress_logger.name, logging.INFO, __file__, 0,
        "[%s]   ...part %s %d/%d %s",
        (f"{datetime.now():%H:%M:%S}", label, done, span, unit),
        None,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(record)


def _merge_sidecars(parts, outfilename, *, output_txt: bool) -> None:
    """Concatenate the part sidecars in range order onto the real ones.

    ``SidecarWriter`` opens in append mode, matching MATLAB's
    ``fopen(..., 'a')``, so this appends rather than replaces -- the same
    behaviour a second serial run over the same input would have.
    """
    # (suffix of the part file, path the merged bytes are appended to). The
    # ``output.txt`` lines go to the cwd, exactly where the serial writer and
    # MATLAB's ``:215`` shell redirect put them -- not beside the output file.
    targets = [(s, outfilename + "." + s) for s in ("tas.csv", "NV.csv", "MK.csv")]
    if output_txt:
        targets.append(("txt", "output.txt"))
    for suffix, target in targets:
        chunks = []
        for part in sorted(parts, key=lambda p: p["lo"]):
            path = part["prefix"] + ".sc." + suffix
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    chunks.append(fh.read())
        if chunks:
            with open(target, "ab") as fh:
                fh.write(b"".join(chunks))


class SpawnRetryWarning(RuntimeWarning):
    """A parallel decode's worker pool died before any task ran, and the whole
    pool was started again from a fresh temporary directory.

    Emitted once per retry so a log shows a degraded start even though the bytes
    written are those of a first-attempt success. Nothing computed changes; only
    whether the opt-in speed path completes or raises.

    Background: on Windows, ``ProcessPoolExecutor``'s spawned workers have been
    observed (2026-09-10/11) dying at their first call-queue semaphore acquire
    with ``OSError: [WinError 6] The handle is invalid``, which
    ``concurrent.futures`` reports to the parent as ``BrokenProcessPool`` with no
    informative ``__cause__``. The root cause is **not established** -- a probe that ran
    48 workers under heavy load without reproducing it --
    so this retry treats
    the death as transient rather than claiming to diagnose it.
    """
