# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_processbuffer.pro``, the CIP branch (`:129-203`).

The DMT CIP's buffer processing, composed with the shared tail
(:mod:`processbuffer_tail`, `:612-747`) into the whole
``soda2_processbuffer`` for ``probetype eq 'CIP'``. The CIPG (grey) branch
(`:205-262`, ``decompress_dmt_grey``) is not ported and is refused by name.

Vendored source (never edited): ``SODA2/abansemer-soda2-afcea15/
soda2_processbuffer.pro``. GDL bank: ``gdl_oracle/run_soda2_cip_bank.py``,
which runs the real ``soda2_processbuffer`` (all 748 lines) on synthetic
buffers and, when the UND data is present, on real ones.

**Line-by-line** (IDL 0-based):

- `:130` -- ``x = decompress_dmt3(buffer.image)``.
- `:134-135` -- ``good1``: particles whose computed slice count is within 1
  of the header's and is positive; fewer than 3 -> ``nullbuffer``.
- `:138-140` -- ``good2``: within 100 s of the ``median`` (IDL ``MEDIAN``
  without ``/EVEN``: the upper-middle element for an even count) of the
  ``good1`` times; fewer than 3 -> ``nullbuffer``.
- `:146-160` -- ``good4``: counter differences (UINT, wrapping at 65536)
  and interarrival times, against ``(*pmisc).lastparticlecount`` and
  ``lastclock``; the neighbour tests read ``[x[1:*], 0]``, so the **last**
  particle is always compared with 0. ``strictcounter`` (default 0) adds the
  counter tests.
- `:166-167` -- ``startline = sync_ind + 2``, ``stopline = startline +
  slice_count - 1``: ends on the next particle's sync slice (see
  :mod:`decompress_dmt`).
- `:180-181` -- every sync and header slice of the buffer is blanked, not
  only the kept particles'.
- `:184-187` -- ``missed = uint(pc) - uint(prev) - 1``: UINT minus INT is
  UINT in IDL (measured under GDL: ``0us - 1`` is 65535), so a repeated
  counter gives ``missed = 65535``, not -1. ``overload = byte(missed < 1)``:
  1 unless ``missed`` is 0.
- `:189-191` -- ``inttime = rawtime - [lastclock, time_sfm]`` (IDL takes
  the shorter operand's length); ``lastclock`` and ``lastparticlecount``
  are written only when the buffer is kept.
- `:199-202` -- for ``format eq 'SEA'``, the caller's buffer ``stoptime``
  is **overwritten** (IDL passes ``b`` by reference) and ``reftime`` becomes
  the first kept particle's time.

The ``nullbuffer`` returns at `:135`, `:140`, `:160` leave ``pmisc``
untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .decompress_dmt import decompress_dmt3
from .particlesort import idl_median
from .processbuffer_spec import NullBuffer

__all__ = ["CipOp", "CipMisc", "CipBufferParticles", "process_cip_buffer",
           "soda2_processbuffer_cip"]


@dataclass(frozen=True)
class CipOp:
    """The ``(*pop)`` fields the CIP branch reads."""

    probetype: str
    format: str
    strictcounter: int


@dataclass
class CipMisc:
    """The ``(*pmisc)`` fields the CIP branch reads and writes
    (``soda2_process_2d.pro:39-41``: ``lastclock:0d``, ``lastparticlecount:0L``)."""

    lastclock: float = 0.0
    lastparticlecount: int = 0


@dataclass
class CipBufferParticles:
    """The branch's locals at `:203`, what the shared tail consumes (the
    attribute names :func:`processbuffer_tail.process_buffer_tail` reads).
    ``bitimage`` is ``(slices, 64)``, slice first (the package convention).

    Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file."""

    rejectbuffer: int
    num_images: int
    bitimage: np.ndarray          # BYTE (slices, 64)
    startline: np.ndarray         # INT
    stopline: np.ndarray          # INT
    overload: np.ndarray          # BYTE
    particle_count: np.ndarray    # LONG
    rawtime: np.ndarray           # DOUBLE
    clocktas: np.ndarray          # FLOAT
    stretch: np.ndarray           # FLOAT
    inttime: np.ndarray           # DOUBLE
    dof: np.ndarray               # BYTE
    time_sfm: np.ndarray          # DOUBLE
    reftime: float                # DOUBLE
    missed: np.ndarray | int      # UINT (an array here; scalar 0 for SPEC and Fast-2DC)
    stoptime: float               # the caller's `buffer.stoptime` after `:200`
    restore_slice: int = 0


def _uint(a: np.ndarray) -> np.ndarray:
    """IDL ``uint()`` of a LONG: the low 16 bits."""
    return (np.asarray(a).astype(np.int64) & 0xFFFF).astype(np.uint16)


def process_cip_buffer(image: np.ndarray, buffer_time: float, buffer_stoptime: float,
                       buffer_tas: float, op: CipOp, misc: CipMisc,
                       ) -> CipBufferParticles | NullBuffer:
    """``soda2_processbuffer.pro:129-203``. ``misc`` is mutated in place where
    the IDL writes ``(*pmisc)``; the returned ``stoptime`` is the value the
    IDL leaves in the caller's ``buffer.stoptime``."""
    x = decompress_dmt3(image)                                           # :130

    # :134-135. The nullbuffer's scalars (slice_count 0, header 999) give none.
    sc = x.slice_count.astype(np.int64)
    hsc = x.header_slice_count.astype(np.int64)
    good1 = np.flatnonzero((np.abs(sc - hsc) <= 1) & (sc > 0))
    if good1.size < 3:
        return NullBuffer()

    t = x.time_sfm
    mediantime = idl_median(t[good1])                                    # :138
    good2 = np.flatnonzero(np.abs(t[good1] - mediantime) < 100)          # :139
    if good2.size < 3:
        return NullBuffer()
    good3 = good1[good2]                                                 # :143

    pc = x.particle_count
    previouscount = np.concatenate([[misc.lastparticlecount], pc[good3]])   # :146
    diffcount = (_uint(pc[good3]).astype(np.int64)
                 - _uint(previouscount[: good3.size]).astype(np.int64)) & 0xFFFF  # :147
    previoustime = np.concatenate([[misc.lastclock], t[good3]])          # :148
    inttime4 = t[good3] - previoustime[: good3.size]                     # :149
    nxt_it = np.concatenate([inttime4[1:], [0.0]])
    if int(op.strictcounter) == 1:                                       # :153-155
        nxt_dc = np.concatenate([diffcount[1:], [0]])
        good4 = np.flatnonzero((diffcount < 10000) & (nxt_dc < 10000)
                               & (inttime4 >= 0) & (nxt_it >= 0))
    else:                                                                # :156-158
        good4 = np.flatnonzero((inttime4 >= 0) & (nxt_it >= 0))
    if good4.size < 3:                                                   # :160
        return NullBuffer()

    good = good3[good4]                                                  # :163
    num_images = int(good.size)

    si = x.sync_ind.astype(np.int16)
    startline = (si[good] + np.int16(2)).astype(np.int16)                # :166
    stopline = (startline + x.slice_count[good] - np.int16(1)).astype(np.int16)  # :167

    time_sfm = t[good].copy()                                            # :174
    reftime = float(time_sfm[num_images - 1])                            # :175
    rawtime = time_sfm.copy()                                            # :176
    dof = x.dof[good].copy()                                             # :177
    particle_count = pc[good].copy()                                     # :178
    bitimage = x.bitimage.copy()                                         # :179
    bitimage[si.astype(np.int64), :] = 0                                 # :180
    bitimage[si.astype(np.int64) + 1, :] = 0                             # :181

    prev2 = np.concatenate([[misc.lastparticlecount], particle_count])   # :184
    diff2 = ((_uint(particle_count).astype(np.int64)
              - _uint(prev2[:num_images]).astype(np.int64)) & 0xFFFF)    # :185 UINT
    missed = ((diff2 - 1) & 0xFFFF).astype(np.uint16)                    # :186 UINT - INT
    misc.lastparticlecount = int(particle_count[num_images - 1])         # :187

    previoustime2 = np.concatenate([[misc.lastclock], time_sfm])         # :189
    inttime = rawtime - previoustime2[:num_images]                       # :190
    misc.lastclock = float(time_sfm[num_images - 1])                     # :191

    overload = np.minimum(missed, 1).astype(np.uint8)                    # :193
    stretch = np.ones(num_images, dtype=np.float32)                      # :194
    clocktas = np.zeros(num_images, dtype=np.float32) + np.float32(buffer_tas)  # :195

    stoptime = buffer_stoptime
    if op.format == "SEA":                                               # :199-202
        stoptime = buffer_time + (float(time_sfm[-1]) - float(time_sfm[0]))
        reftime = float(time_sfm[0])

    return CipBufferParticles(
        rejectbuffer=0, num_images=num_images, bitimage=bitimage,
        startline=startline, stopline=stopline, overload=overload,
        particle_count=particle_count, rawtime=rawtime, clocktas=clocktas,
        stretch=stretch, inttime=inttime, dof=dof, time_sfm=time_sfm,
        reftime=reftime, missed=missed, stoptime=stoptime, restore_slice=0)


def soda2_processbuffer_cip(image: np.ndarray, buffer_time: float, buffer_stoptime: float,
                            buffer_tas: float, op: CipOp, tail_op: Any, misc: CipMisc,
                            lastdhist: Any) -> tuple[Any, float]:
    """``p = soda2_processbuffer(b, pop, pmisc)`` for ``probetype 'CIP'``, the
    whole function (`:129-203` then `:612-747`). Returns ``(p, stoptime)``:
    ``p`` a :class:`NullBuffer` or :class:`processbuffer_tail.ProcessedBuffer`,
    ``stoptime`` the caller's ``buffer.stoptime`` afterwards (unchanged on a
    null return).

    Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file."""
    from .processbuffer_tail import process_buffer_tail

    if op.probetype != "CIP":
        raise NotImplementedError(
            f"soda2_processbuffer.pro: probetype {op.probetype!r} -- only the CIP "
            "branch (:129-203) is ported here (CIPG, :205-262, needs "
            "decompress_dmt_grey.pro)")
    result = process_cip_buffer(image, buffer_time, buffer_stoptime, buffer_tas, op, misc)
    if isinstance(result, NullBuffer):
        return result, buffer_stoptime
    return process_buffer_tail(result, tail_op, lastdhist), result.stoptime  # type: ignore[arg-type]
