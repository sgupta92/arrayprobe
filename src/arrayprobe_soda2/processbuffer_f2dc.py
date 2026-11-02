# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""SODA-2 ``soda2_processbuffer.pro:28-78``, the Fast-2DC branch
(probetype ``'F2DC'`` and ``'F2DC_v2'``), ahead of the shared tail.

Line map:
- `:31-35` the previous buffer's remainder is prepended; ``bufflength``.
- `:38` sync where the top two bytes are ``0xAAAA``, over every slice.
- `:39-43` fewer than three syncs: ``f2d_remainder_slices`` cleared, ``nullbuffer``.
- `:45-52` v2: 44-bit timeline, dof bit 44; v1: 40-bit timeline, dof bit 40; ``dof=1-dof``.
- `:54-58` sync slices blanked, the inverted image expanded to bits by ``dec2bin64``
  (column 0 = bit 63), ``startline=[0,sync_ind+1]``, ``stopline=((sync_ind-1)>0)>startline`` (IDL's
  ``>`` on unequal lengths truncates to the shorter operand).
- `:60-64` ``clockHz`` 12e6, v2 ``1e8/3d``; ``time_sfm``, ``reftime``, ``rawtime``.
- `:70-73` remainder from the last sync slice (already blanked) to the end, written
  into the fixed 512-slice ``f2d_remainder`` (``soda2_process_2d.pro:39``); a
  remainder longer than 512 is an IDL subscript error at `:73`, raised here.
- `:74-77` ``stretch`` 1, ``inttime`` 0, ``clocktas`` the buffer TAS.

The F2DC branch sets no ``overload``; the CIP shape's ``overload`` field is
filled with zeros here so the shared tail can run. This matches IDL:
`:648` guards the read with ``n_elements(overload)``, so for the F2DC branch
the tail sees ``bytarr(num_images)``, all zeros, as here
(``tests/test_soda2_f2dc_gdl_golden.py``).

Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .processbuffer_cip import CipBufferParticles
from .processbuffer_spec import NullBuffer

__all__ = ["F2dcOp", "F2dcMisc", "process_f2dc_buffer", "soda2_processbuffer_f2dc",
           "F2DC_REMAINDER_CAPACITY"]

F2DC_REMAINDER_CAPACITY = 512  # soda2_process_2d.pro:39, f2d_remainder:ulon64arr(512)
_SYNC_MASK = np.uint64(0xFFFF000000000000)
_SYNC = np.uint64(0xAAAA000000000000)


@dataclass(frozen=True)
class F2dcOp:
    """The ``(*pop)`` field the branch reads."""

    probetype: str


@dataclass
class F2dcMisc:
    """``(*pmisc)`` fields the branch reads and writes (``soda2_process_2d.pro:39``)."""

    f2d_remainder: np.ndarray = field(
        default_factory=lambda: np.zeros(F2DC_REMAINDER_CAPACITY, dtype=np.uint64))
    f2d_remainder_slices: int = 0
    lastbufftime: float = 0.0


def process_f2dc_buffer(image: np.ndarray, buffer_time: float, buffer_tas: float,
                        op: F2dcOp, misc: F2dcMisc) -> NullBuffer | CipBufferParticles:
    """`:28-78`. Mutates ``misc`` as the IDL writes ``(*pmisc)``."""
    if op.probetype not in ("F2DC", "F2DC_v2"):
        raise NotImplementedError(f"soda2_processbuffer.pro:28: probetype {op.probetype!r}")
    buf = np.asarray(image, dtype=np.uint64)
    if misc.f2d_remainder_slices > 0:                                    # :31-34
        img = np.concatenate([misc.f2d_remainder[:misc.f2d_remainder_slices], buf])
    else:
        img = buf.copy()
    bufflength = img.size                                                # :35
    sync_ind = np.flatnonzero((img & _SYNC_MASK) == _SYNC)              # :38
    num_images = max(sync_ind.size, 1)  # where() -> -1 gives n_elements 1
    if sync_ind.size == 0 or num_images < 3:                             # :39-43
        misc.f2d_remainder_slices = 0
        return NullBuffer()

    words = img[sync_ind]
    if op.probetype == "F2DC_v2":                                        # :45-48
        timelines = words & np.uint64(0x00000FFFFFFFFFFF)
        dof = np.minimum(words & np.uint64(0x0000100000000000), np.uint64(1))
    else:                                                                # :49-51
        timelines = words & np.uint64(0x000000FFFFFFFFFF)
        dof = np.minimum(words & np.uint64(0x0000010000000000), np.uint64(1))
    dof = (1 - dof.astype(np.int64)).astype(np.uint8)                    # :52

    img[sync_ind] = np.uint64(0xFFFFFFFFFFFFFFFF)                        # :54
    inv = ~img                                                           # :55 dec2bin64(not(image))
    bitimage = np.unpackbits(inv.astype(">u8").view(np.uint8).reshape(-1, 8),
                             axis=1)                                     # column 0 = bit 63
    startline = np.concatenate([[0], sync_ind + 1]).astype(np.int64)     # :56
    stopline = np.maximum(sync_ind - 1, 0)                               # :57
    stopline = np.maximum(stopline, startline[:stopline.size])           # :58

    clock_hz = 12.0e6                                                    # :60
    if op.probetype == "F2DC_v2":
        clock_hz = 1e8 / 3.0                                             # :61
    time_sfm = timelines.astype(np.float64) / clock_hz                   # :62
    reftime = float(timelines[num_images - 1]) / clock_hz               # :63
    rawtime = timelines.copy()                                           # :64

    particle_count = np.zeros(num_images, dtype=np.int16)                # :68

    last = int(sync_ind.max())                                           # :71-73
    nremainder = bufflength - last
    if nremainder > F2DC_REMAINDER_CAPACITY:
        raise IndexError(
            f"soda2_processbuffer.pro:73: remainder of {nremainder} slices exceeds "
            f"f2d_remainder's {F2DC_REMAINDER_CAPACITY} (IDL subscript out of range)")
    misc.f2d_remainder_slices = nremainder
    misc.f2d_remainder[:nremainder] = img[last:bufflength]
    misc.lastbufftime = buffer_time                                      # :74

    return CipBufferParticles(
        rejectbuffer=0, num_images=num_images, bitimage=bitimage,
        startline=startline, stopline=stopline,
        overload=np.zeros(num_images, dtype=np.uint8),
        particle_count=particle_count, rawtime=rawtime,
        clocktas=np.zeros(num_images, dtype=np.float32) + np.float32(buffer_tas),  # :77
        stretch=np.zeros(num_images, dtype=np.float32) + np.float32(1.0),          # :75
        inttime=np.zeros(num_images, dtype=np.float64),                            # :76
        dof=dof, time_sfm=time_sfm, reftime=reftime,
        missed=0, stoptime=0.0, restore_slice=0)   # :66-67 (`missed=0`, an IDL scalar, :67)


def soda2_processbuffer_f2dc(image: np.ndarray, buffer_time: float, buffer_tas: float,
                             op: F2dcOp, tail_op: Any, misc: F2dcMisc,
                             lastdhist: Any) -> Any:
    """``p = soda2_processbuffer(b, pop, pmisc)`` for Fast-2DC: `:28-78` then
    the shared tail `:612-747`. Returns a :class:`NullBuffer` or
    :class:`processbuffer_tail.ProcessedBuffer`."""
    from .processbuffer_tail import process_buffer_tail

    result = process_f2dc_buffer(image, buffer_time, buffer_tas, op, misc)
    if isinstance(result, NullBuffer):
        return result
    return process_buffer_tail(result, tail_op, lastdhist)  # type: ignore[arg-type]
