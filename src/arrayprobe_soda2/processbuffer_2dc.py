# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""SODA-2 ``soda2_processbuffer.pro:80-127``, the 2DC branch (probetype ``'2DC'``,
32-diode ULONG slices, RAF ``0x55`` timing words; the SEA override at `:123-126`).

Line map:
- `:81-83` ``buffer.stoptime = buffer.time``; fewer than 1024 slices -> ``nullbuffer``.
- `:84` sync where slice *k* and slice *k-1* both carry top byte ``0x55``
  (over ``image[1:1023]`` / ``image[0:1022]``), plus 1.
- `:86-91` fewer than three: ``fix2dimage`` and retry, now also requiring
  ``image[k-1] ne '55000000'x``.
- `:93` still fewer than three: ``nullbuffer``.
- `:94-97` ``time_ind=sync_ind-1``; ``sync_ind=[0,sync_ind]``; 24-bit timelines.
- `:99-100` every slice with top byte ``0x55`` blanked to ``0xFFFFFFFF``.
- `:102-108` ``freq = yres/(1e6*tas)`` (FLOAT: ``yres`` and ``tas`` are FLOAT in
  ``op`` and the buffer), ``parttime=(timelines+2)*freq`` (FLOAT), ``elaptime``
  accumulated in DOUBLE, ``time_sfm`` counted back from ``buffer.time``,
  ``reftime = buffer.time + elaptime[-1]``.
- `:111` the bit image is the inverted image expanded to bits by ``dec2bin``: 32 columns,
  column 0 = bit 31 (``dec2bin.pro:8``); slice-first here, as the package convention.
- `:112-113` ``startline = [0,sync_ind] < 1023`` (num_images+1 entries),
  ``stopline = time_ind < 1023``.
- `:114-118` ``restore_slice=1``, ``missed=0``, counters 0, ``dof`` 1, ``stretch`` 1.
- `:119-121` ``inttime = time_sfm - [lastclock, time_sfm]`` (IDL truncates to the
  shorter operand), ``lastclock`` saved.
- `:122` ``clocktas`` the buffer TAS.
- `:123-126` SEA only: ``stoptime`` widened by the particle span, ``reftime=time_sfm[0]``.

The branch's ``restore_slice=1`` sends every ROI through ``soda2_backfill.pro``
in the shared tail (`:678`), ported as ``arrayprobe_soda2.backfill``;
:func:`process_2dc_buffer` returns the branch's locals only.
``tests/test_soda2_2dc_gdl.py`` compares them with GDL.

Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .fix2dimage import fix2dimage
from .processbuffer_cip import CipBufferParticles
from .processbuffer_spec import NullBuffer

__all__ = ["TwoDcOp", "TwoDcMisc", "process_2dc_buffer"]

_TOP = np.uint32(0xFF000000)
_SYNC = np.uint32(0x55000000)
_BLANK = np.uint32(0xFFFFFFFF)


@dataclass(frozen=True)
class TwoDcOp:
    """The ``(*pop)`` fields the branch reads."""

    probetype: str
    format: str
    yres: float


@dataclass
class TwoDcMisc:
    """``(*pmisc).lastclock`` (``soda2_process_2d.pro:39``), read and written at `:118-120`."""

    lastclock: float = 0.0


def _sync(img: np.ndarray, retry: bool) -> np.ndarray:
    a = (img[1:1024] & _TOP) == _SYNC                                    # :84 / :88
    b = (img[0:1023] & _TOP) == _SYNC
    m = a & b
    if retry:
        m &= img[0:1023] != _SYNC                                        # :90
    return np.flatnonzero(m).astype(np.int64) + 1


def process_2dc_buffer(image: np.ndarray, buffer_time: float, buffer_tas: float,
                       op: TwoDcOp, misc: TwoDcMisc) -> NullBuffer | CipBufferParticles:
    """`:80-127`. Mutates ``misc`` as the IDL writes ``(*pmisc)``. The returned
    ``stoptime`` is ``buffer.stoptime`` after the branch (`:82`, `:124`)."""
    if op.probetype != "2DC":
        raise NotImplementedError(f"soda2_processbuffer.pro:80: probetype {op.probetype!r}")
    img = np.asarray(image, dtype=np.uint32).copy()                      # :81
    stoptime = float(buffer_time)                                        # :82
    if img.size < 1024:                                                  # :83
        return NullBuffer()
    sync_ind = _sync(img, retry=False)                                   # :84
    if sync_ind.size < 3:                                                # :86-91
        img = np.asarray(fix2dimage(img), dtype=np.uint32).copy()
        sync_ind = _sync(img, retry=True)
    num_images = int(sync_ind.size)
    if num_images < 3:                                                   # :93
        return NullBuffer()
    time_ind = sync_ind - 1                                              # :94
    sync_ind = np.concatenate([[0], sync_ind]).astype(np.int64)          # :95

    timelines = img[time_ind] & np.uint32(0x00FFFFFF)                    # :97

    extralines = np.flatnonzero((img & _TOP) == _SYNC)                  # :99
    img[extralines] = _BLANK                                             # :100

    freq = np.float32(op.yres) / (np.float32(1.0e6) * np.float32(buffer_tas))   # :102
    parttime = ((timelines.astype(np.int64) + 2).astype(np.uint32).astype(np.float32)
                * freq).astype(np.float32)                               # :103
    elaptime = np.zeros(num_images, dtype=np.float64)                    # :104
    elaptime[0] = parttime[0]                                            # :105
    for i in range(1, num_images):                                       # :106
        elaptime[i] = elaptime[i - 1] + np.float64(parttime[i])
    time_sfm = np.float64(buffer_time) + elaptime - elaptime[num_images - 1]  # :107
    reftime = float(np.float64(buffer_time) + elaptime[num_images - 1])  # :108
    rawtime = timelines.copy()                                           # :109

    inv = ~img                                                           # :111 dec2bin(not(image))
    bitimage = np.unpackbits(inv.astype(">u4").view(np.uint8).reshape(-1, 4),
                             axis=1)                                     # column 0 = bit 31
    startline = np.minimum(sync_ind, 1023)                               # :112
    stopline = np.minimum(time_ind, 1023)                                # :113

    previoustime = np.concatenate([[np.float64(misc.lastclock)], time_sfm])  # :119
    inttime = time_sfm - previoustime[:num_images]                       # :120
    misc.lastclock = float(time_sfm[num_images - 1])                     # :121

    if op.format == "SEA":                                               # :123-126
        stoptime = float(np.float64(buffer_time) + (time_sfm[-1] - time_sfm[0]))
        reftime = float(time_sfm[0])

    return CipBufferParticles(
        rejectbuffer=0, num_images=num_images, bitimage=bitimage,
        startline=startline, stopline=stopline,
        overload=np.zeros(num_images, dtype=np.uint8),   # :648 n_elements guard
        particle_count=np.zeros(num_images, dtype=np.int16),             # :116
        rawtime=rawtime,
        clocktas=np.zeros(num_images, dtype=np.float32) + np.float32(buffer_tas),  # :122
        stretch=np.zeros(num_images, dtype=np.float32) + np.float32(1.0),          # :118
        inttime=inttime,
        dof=np.zeros(num_images, dtype=np.uint8) + np.uint8(1),          # :117
        time_sfm=time_sfm, reftime=reftime,
        missed=0, stoptime=stoptime, restore_slice=1)                    # :114-115


def soda2_processbuffer_2dc(image: np.ndarray, buffer_time: float, buffer_tas: float,
                            op: TwoDcOp, tail_op: Any, misc: TwoDcMisc,
                            lastdhist: Any) -> Any:
    """``p = soda2_processbuffer(b, pop, pmisc)`` for 2DC: `:80-127` then the
    shared tail `:612-747`, composed the way
    :func:`processbuffer_f2dc.soda2_processbuffer_f2dc` composes `:28-78`.
    Returns a :class:`NullBuffer` or :class:`processbuffer_tail.ProcessedBuffer`."""
    from .processbuffer_tail import process_buffer_tail

    result = process_2dc_buffer(image, buffer_time, buffer_tas, op, misc)
    if isinstance(result, NullBuffer):
        return result
    return process_buffer_tail(result, tail_op, lastdhist)  # type: ignore[arg-type]
