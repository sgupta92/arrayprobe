# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""SODA-2's DMT CIP image decoder : ``decompress_dmt3.pro`` (133
lines) and ``decode_header_slice.pro`` (39), ported whole, with the two bit
helpers they call (``dec2bin8.pro``, ``bin2dec.pro``) folded in.

``decompress_dmt3`` is what ``soda2_processbuffer.pro:130`` calls for
``probetype eq 'CIP'``; ``decompress_dmt.pro`` (the older version) has no
caller in the vendored tree and is not ported.

Vendored sources (never edited): ``SODA2/abansemer-soda2-afcea15/
decompress_dmt3.pro``, ``decode_header_slice.pro``, ``dec2bin8.pro``,
``bin2dec.pro``. GDL bank: ``gdl_oracle/run_soda2_cip_bank.py``.

**The compression** (DMT manual, as the IDL reads it): each header byte
``rlehb`` carries three flags and a 5-bit ``count``. ``0x80`` alone: write
``count+1`` bytes of ``0x00`` (shadowed); ``0x40`` alone: ``count+1`` bytes of
``0xFF`` (blank); no flag: copy the next ``count+1`` bytes literally;
``0x20`` (dummy), or ``0x80|0x40`` together: nothing. A particle starts with
a sync slice (eight ``0xAA``) followed by a header ("time") slice; a slice is
8 bytes = 64 diodes.

**IDL semantics this port reproduces** (the bank covers the revert, null and nominal paths;
the ``ipos == 0`` and overflow halts are read, with the ``[0:-1]`` rule measured under GDL):

- ``:13`` -- ``image=bytarr(8,20000)+255`` is **INT**, not BYTE (``BYTE +
  INT``), so the decompressed ``image`` and the ``not(image)`` at ``:126`` are
  16-bit; ``dec2bin8`` then reads only the low 8 bits.
- ``:28-34`` -- the first sync search keeps a candidate only when the byte
  *before* the eight ``0xAA`` is a literal-run header with ``count`` in
  ``7..31``.
- ``:39``, ``:49`` -- the ``c``-th (last) sync is never decompressed:
  ``syncpos[c]`` is the array's zero initialiser, so ``FOR cipos=syncpos[c-1],
  -1`` runs no iterations.
- ``:49-78`` -- the inner ``FOR`` modifies its own loop variable
  (``cipos=cipos+count+1``), and IDL honours that; after the loop ``cipos`` is
  one past the last value tested, which ``:43`` then compares with the next
  sync position to detect a literal run that overran it ("decompression
  error": revert to the particle's start, ``:45-46``).
- ``:69`` -- a literal run that would read past the buffer is skipped whole
  (no bytes written, ``ipos`` and ``cipos`` not advanced).
- ``:81``, ``:86`` -- ``image[0:ipos-1]`` with ``ipos == 0`` is ``image[0:-1]``
  -- the **whole** 160 000-element array (IDL 8 and GDL both read a negative
  range end from the array's end; measured under GDL).
- ``:96`` -- the second sync search (over the decompressed slices) is what
  defines the particles; it tests bytes 0, 1 and 7 of a slice and the slice
  total ``1360`` (= 8 x 170).
- ``:123-124`` -- ``slice_count`` counts the slices from a sync to the next
  sync **minus one**, i.e. the header slice plus the image slices; the caller
  adds 2 to the sync index for the first image slice and ``slice_count-1``
  for the last, so each particle's last slice is the *next* particle's sync
  slice (blanked by ``soda2_processbuffer.pro:180``).
- ``decode_header_slice.pro:13-35`` -- the header's 8 bytes are reversed and
  read MSB-first: the 64-bit word is the header read little-endian; bits
  63-57 slice count, 56 DoF, 55-51 hour, 50-45 minute, 44-39 second, 38-29
  millisecond, 28-16 the 125-ns counter, 15-0 the particle counter.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["HeaderSlice", "Dmt3Result", "decode_header_slice", "decompress_dmt3"]

_IMAGE_LEN = 8 * 20000
_SYNC_ARRAY_LEN = 1000   # `:27` syncpos=intarr(1000)
_SLICE_ARRAY_LEN = 500   # `:88-93`


class DecompressDmtError(RuntimeError):
    """An IDL halt (subscript out of range) this port raises, naming the line."""


@dataclass
class HeaderSlice:
    """``decode_header_slice.pro:37``'s return. ``particle_count``,
    ``slice_count``, ``time`` and ``time_sfm`` are 1-element arrays in IDL
    (``bin2dec`` returns ``ulonarr(n)``); scalars here, the values are the
    same."""

    particle_count: int
    slice_count: int
    dof: int
    time: float
    time_sfm: float


def decode_header_slice(header: np.ndarray) -> HeaderSlice:
    """``decode_header_slice.pro``. ``header`` is 8 values 0..255 (the INT
    slice of the decompressed image); only each value's low 8 bits are read
    (``dec2bin8.pro:9``)."""
    h = [int(v) & 0xFF for v in np.asarray(header)[::-1]]   # :13 reverse
    w = 0
    for byte in h:                                          # :16 dec2bin8, MSB first
        w = (w << 8) | byte
    particle_count = w & 0xFFFF                             # :19 bslice[48:63]
    slice_count = (w >> 57) & 0x7F                          # :22 bslice[0:6]
    dof = (w >> 56) & 1                                     # :25 bslice[7]
    hour = (w >> 51) & 0x1F                                 # :28 bslice[8:12]
    minute = (w >> 45) & 0x3F                               # :29 bslice[13:18]
    second = (w >> 39) & 0x3F                               # :30 bslice[19:24]
    millisecond = (w >> 29) & 0x3FF                         # :31 bslice[25:34]
    counter = (w >> 16) & 0x1FFF                            # :32 bslice[35:47]
    # :34-35 -- left to right in DOUBLE; `1.0e9` is a FLOAT literal, exact.
    time = (hour * 10000.0 + minute * 100.0 + float(second)
            + millisecond / 1000.0 + counter * 125.0 / 1.0e9)
    time_sfm = (hour * 3600.0 + minute * 60.0 + float(second)
                + millisecond / 1000.0 + counter * 125.0 / 1.0e9)
    return HeaderSlice(particle_count=particle_count, slice_count=slice_count,
                       dof=dof, time=time, time_sfm=time_sfm)


@dataclass
class Dmt3Result:
    """``decompress_dmt3.pro:129-131`` (``null=False``) or the ``nullbuffer``
    of ``:18-19`` (``null=True``: ``slice_count`` 0, ``header_slice_count``
    999, everything else 0 -- so the caller's ``good1`` test at
    ``soda2_processbuffer.pro:134`` finds nothing)."""

    null: bool
    image: np.ndarray                 # INT, (8*slices,) -- `:13`, INT not BYTE
    bitimage: np.ndarray              # BYTE, (slices, 64): port layout, slice first
    sync_ind: np.ndarray              # INT
    time_elap: np.ndarray             # DOUBLE
    time_sfm: np.ndarray              # DOUBLE
    particle_count: np.ndarray        # LONG
    slice_count: np.ndarray           # INT
    dof: np.ndarray                   # BYTE
    remainder: np.ndarray             # BYTE
    header_slice_count: np.ndarray    # INT


def _null(image: np.ndarray) -> Dmt3Result:
    z = np.zeros(1, dtype=np.int16)
    return Dmt3Result(null=True, image=image, bitimage=np.zeros((0, 64), dtype=np.uint8),
                      sync_ind=z, time_elap=np.zeros(1), time_sfm=np.zeros(1),
                      particle_count=np.zeros(1, dtype=np.int32),
                      slice_count=np.zeros(1, dtype=np.int16),
                      dof=np.zeros(1, dtype=np.uint8), remainder=np.zeros(1, dtype=np.uint8),
                      header_slice_count=np.array([999], dtype=np.int16))


def _bitimage(image: np.ndarray, slices: int) -> np.ndarray:
    """``:126`` -- ``reform(reverse(dec2bin8(not(image)),1),64,slices)`` in the
    port's ``(slices, 64)`` layout: diode ``8k+b`` of slice ``s`` is bit ``b``
    (LSB first) of ``not(image[8s+k])``'s low byte."""
    low = (~image[: slices * 8].astype(np.int16)).astype(np.uint16) & 0xFF
    bits = ((low[:, None] >> np.arange(8, dtype=np.uint16)[None, :]) & 1).astype(np.uint8)
    return bits.reshape(slices, 64)


def decompress_dmt3(cimage: np.ndarray) -> Dmt3Result:
    """``decompress_dmt3.pro``: ``cimage`` is the BYTE buffer as read
    (``readseabuffer_caps.pro:34``, 4098 bytes for the UND CIP)."""
    cimage = np.asarray(cimage, dtype=np.uint8)
    image = np.full(_IMAGE_LEN, 255, dtype=np.int16)        # :13 INT
    nbytes = cimage.size                                    # :21
    if nbytes <= 1:                                         # :22
        return _null(image)

    # :25-34 -- the first sync search.
    # Vectorised, same test per `cipos` in 0..nbytes-9: bytes cipos+1..cipos+8
    # all 170, and 7 <= cimage[cipos] <= 31. Matches are kept in ascending order.
    cb = cimage.astype(np.int64)
    syncpos = np.zeros(_SYNC_ARRAY_LEN, dtype=np.int64)
    ncand = nbytes - 8
    hits = np.zeros(0, dtype=np.int64)
    if ncand > 0:
        run = np.concatenate([[0], np.cumsum(cb == 170)])
        pos = np.arange(ncand)
        eight = (run[pos + 9] - run[pos + 1]) == 8
        lead = (cb[:ncand] >= 7) & (cb[:ncand] <= 31)
        hits = np.flatnonzero(eight & lead)
    c = int(hits.size)
    if c > _SYNC_ARRAY_LEN:
        raise DecompressDmtError(
            "decompress_dmt3.pro:31: syncpos[c] subscript out of range "
            f"(more than {_SYNC_ARRAY_LEN} syncs)")
    syncpos[:c] = hits
    if c < 2:                                               # :36
        return _null(image)

    ipos = 0
    lastgoodipos = 0
    cipos = 0                                               # :38
    for i in range(c):                                      # :39
        if ipos % 8 != 0:                                   # :40-42
            ipos = ipos + 8 - (ipos % 8)
        if cipos > int(syncpos[i]):                         # :43-47
            ipos = lastgoodipos
            image[ipos:] = 255
        lastgoodipos = ipos                                 # :48
        cipos = int(syncpos[i])                             # :49 FOR start
        if i + 1 >= _SYNC_ARRAY_LEN:
            raise DecompressDmtError("decompress_dmt3.pro:49: syncpos[i+1] subscript out of range")
        end = int(syncpos[i + 1]) - 1
        while cipos <= end:
            rlehb = int(cb[cipos])                          # :51
            zeroes = (rlehb & 128) == 128                   # :52
            ones = (rlehb & 64) == 64                       # :53
            dummy = (rlehb & 32) == 32                      # :54
            count = rlehb & 31                              # :55
            if zeroes and not ones and not dummy:           # :57-60
                if ipos + count >= _IMAGE_LEN:
                    raise DecompressDmtError("decompress_dmt3.pro:58: image subscript out of range")
                image[ipos: ipos + count + 1] = 0
                ipos = ipos + count + 1
            if ones and not zeroes and not dummy:           # :62-65
                if ipos + count >= _IMAGE_LEN:
                    raise DecompressDmtError("decompress_dmt3.pro:63: image subscript out of range")
                image[ipos: ipos + count + 1] = 255
                ipos = ipos + count + 1
            if not zeroes and not ones and not dummy:       # :67-77
                if cipos + count + 1 < nbytes:
                    if ipos + count >= _IMAGE_LEN:
                        raise DecompressDmtError(
                            "decompress_dmt3.pro:73: image subscript out of range")
                    image[ipos: ipos + count + 1] = cb[cipos + 1: cipos + count + 2]
                    ipos = ipos + count + 1
                    cipos = cipos + count + 1
            cipos += 1                                      # FOR increment

    # :81 -- `image[0:ipos-1]`; ipos == 0 reads `[0:-1]`, the whole array.
    if ipos > 0:
        image = image[:ipos]
    slices = image.size // 8                                # :84-85
    if slices > 0:                                          # :86, same `[0:-1]` rule
        image = image[: slices * 8]

    # :87-110 -- the second sync search, over whole slices.
    sync_ind: list[int] = []
    time_l: list[float] = []
    time_total: list[float] = []
    particle_count: list[int] = []
    dof: list[int] = []
    header_slice_count: list[int] = []
    starttime = 0.0
    # :94-96, vectorised: slices 0..slices-2 whose bytes 0, 1 and 7 are 170 and
    # whose total is 1360; visited in ascending order as the IDL loop does.
    nsearch = max(slices - 1, 0)
    if nsearch > 0:
        sl = image[: nsearch * 8].reshape(nsearch, 8).astype(np.int64)
        match = ((sl[:, 0] == 170) & (sl[:, 1] == 170) & (sl[:, 7] == 170)
                 & (sl.sum(axis=1) == 1360))
        candidates = np.flatnonzero(match)
    else:
        candidates = np.zeros(0, dtype=np.int64)
    for i in (int(k) for k in candidates):
        ss = 8 * i
        se = ss + 7
        if len(sync_ind) >= _SLICE_ARRAY_LEN:
            raise DecompressDmtError(
                "decompress_dmt3.pro:97: sync_ind[sync_count] subscript out of range "
                f"(more than {_SLICE_ARRAY_LEN} sync slices)")
        params = decode_header_slice(image[ss + 8: se + 9])   # :99
        if not sync_ind:
            starttime = params.time_sfm                 # :105
        sync_ind.append(i)
        particle_count.append(params.particle_count)
        dof.append(params.dof)
        header_slice_count.append(params.slice_count)
        time_l.append(params.time_sfm - starttime)
        time_total.append(params.time_sfm)
    sync_count = len(sync_ind)
    if sync_count <= 2:                                     # :113
        return _null(image)

    si = np.asarray(sync_ind, dtype=np.int16)               # :115-120
    # :123-124 -- `fix(slices-1)`; INT arithmetic.
    slice_stop = np.concatenate([si[1:], np.array([slices - 1], dtype=np.int16)])
    slice_count = (slice_stop - si - 1).astype(np.int16)

    bitimage = _bitimage(image, slices)                     # :126
    remainder = cimage[int(syncpos[c - 1]):].copy()         # :127

    return Dmt3Result(
        null=False, image=image, bitimage=bitimage, sync_ind=si,
        time_elap=np.asarray(time_l, dtype=np.float64),
        time_sfm=np.asarray(time_total, dtype=np.float64),
        particle_count=np.asarray(particle_count, dtype=np.int32),
        slice_count=slice_count, dof=np.asarray(dof, dtype=np.uint8),
        remainder=remainder,
        header_slice_count=np.asarray(header_slice_count, dtype=np.int16),
    )
