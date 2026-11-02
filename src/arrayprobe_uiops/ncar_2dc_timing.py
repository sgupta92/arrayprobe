# SPDX-License-Identifier: BSD-3-Clause
"""NCAR-recorded PMS 2DC timing/sync words, converted to the 0x55 form before framing.

**Not UIOOPS behaviour: a default-on v3.5 correction** (the package's rule for upstream
defects that destroy data: on a probe with no archived product the defect is corrected by
default, can be turned off, and is stamped in the run's configuration record).
Finding: the timing-word form was identified.


The defect. ``imgProc_sm.m:137-139`` sets the probetype-0 frame as ``boundary = [255 255 255
255]`` followed by a slice whose first byte is ``boundarytime = 85`` (0x55), and ``:754`` frames a
particle only on that pair. RAF-format 2DC records written with NCAR's timing/sync words carry
``[FFFFFFFF][FF tttttt][FF000000]`` between particles -- the same structure (``:786``: "end of
particle, timing word, and sync word") with marker byte 0xFF -- so ``:754`` never fires and the
run writes an empty proc file with no message.

The correction is SODA-2's own (``fix2dimage.pro``; "The sync words and timelines are different on
NCAR probes"), applied under SODA-2's own gate (``soda2_processbuffer.pro:84-87``):

- gate (``soda2_processbuffer.pro:84-87``): a record is converted only when it has fewer than
  three primary 0x55 syncs (two consecutive slices with top byte 0x55), i.e. it does not already
  carry the form UIOOPS frames -- detected per record, never assumed per file;
- ``fix2dimage.pro:9``: candidate sync words ``FF800000``, ``0``, ``FF000000``, ``2A000000``;
- ``:10``: fewer than five candidates, the record is unchanged;
- ``:13-15``: keep the candidates followed by a gap greater than one (drops the last; a record
  with no such gap keeps them all);
- ``:17``: keep those with a blank (``FFFFFFFF``) slice two back, or an index below 2;
- ``:23-26``: the sync slice and the slice before it (the timing word) are rewritten
  ``(w or FF000000) xor AA000000`` -- top byte 0x55, the lower 24 bits (the timing count)
  unchanged. Subscript -1 is clipped to 0, as IDL does.

A slice here is ``imgProc_sm``'s ``data(j, 1:4)``, its first byte the first file byte -- the
``FF000000`` byte SODA-2 reads after its big-endian swap (``soda2_read2dbuffer.pro:23,53``), so
the 32-bit word is built big-endian from the four bytes. Only byte 1 of a converted slice changes.

Off (the faithful path) is byte-identical to upstream: :func:`convert_record` is never called.
"""
from __future__ import annotations

import numpy as np

__all__ = ["STAMP_OFF", "STAMP_ON", "convert_record", "ncar_word_slices"]

STAMP_ON = "on:fix2dimage"
STAMP_OFF = "off"

_CANDIDATES = (0xFF800000, 0x00000000, 0xFF000000, 0x2A000000)   # fix2dimage.pro:9
_BLANK = np.uint32(0xFFFFFFFF)
_TOP = np.uint32(0xFF000000)
_SYNC55 = np.uint32(0x55000000)


def _words(data: np.ndarray) -> np.ndarray:
    """Big-endian 32-bit word per slice from ``data``'s first four byte columns."""
    b = np.asarray(data[:, :4]).astype(np.uint32)
    return (b[:, 0] << 24) | (b[:, 1] << 16) | (b[:, 2] << 8) | b[:, 3]


def _primary_syncs(w: np.ndarray) -> int:
    """``soda2_processbuffer.pro:84``: slices k with k and k-1 both top byte 0x55."""
    top55 = (w & _TOP) == _SYNC55
    return int(np.count_nonzero(top55[1:] & top55[:-1]))


def ncar_word_slices(data: np.ndarray) -> np.ndarray:
    """0-based indices of the NCAR sync slices (``fix2dimage.pro:20``'s ``timelines``) in
    ``data``; empty when the record already carries 0x55 syncs (gate) or ``fix2dimage.pro``
    finds none. :func:`convert_record` rewrites these and the slice before each."""
    w = _words(data)
    if w.size < 2 or _primary_syncs(w) >= 3:                     # processbuffer :84-87
        return np.zeros(0, dtype=np.int64)
    hit = np.zeros(w.shape, dtype=bool)
    for c in _CANDIDATES:                                        # :9
        hit |= w == np.uint32(c)
    test1 = np.flatnonzero(hit).astype(np.int64)
    num = test1.size
    if num < 5:                                                  # :10
        return np.zeros(0, dtype=np.int64)
    good = np.flatnonzero(np.diff(test1) > 1)                    # :13-14
    if good.size > 0:                                            # :15
        test1 = test1[good]
    back = w[np.maximum(test1, 2) - 2]                           # :17
    timelines = test1[(back == _BLANK) | (test1 < 2)]
    if timelines.size == 0:                                      # :18
        return np.zeros(0, dtype=np.int64)
    return timelines


def convert_record(data: np.ndarray) -> tuple[np.ndarray, int]:
    """``data`` with every NCAR sync/timing slice's first byte set to 0x55
    (``fix2dimage.pro:23-26``: ``(w or FF000000) xor AA000000`` changes only the top byte, to
    ``FF xor AA = 55``), and the number of sync words converted. The input is not modified; a
    record the gate passes over is returned as the same object."""
    timelines = ncar_word_slices(data)
    if timelines.size == 0:
        return data, 0
    out = np.array(data, copy=True)
    out[timelines, 0] = 0x55                                     # :25
    out[np.maximum(timelines - 1, 0), 0] = 0x55                  # :26, IDL clips -1 to 0
    return out, int(timelines.size)
