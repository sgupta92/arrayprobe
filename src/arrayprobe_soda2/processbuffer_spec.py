# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_processbuffer.pro``, the SPEC branch (`:264-376`) -- P-c+P-d.

Ports the whole `CASE` branch entered for `probetype` in `{'HVPS3','2DS',
'3VCPI','HVPS4'}`, `:264-376`, as one function. P-c (the per-image loop,
`:265-340`) and P-d (the time assembly, `:341-372`) share three locals
(`c`, `inttime`, `lastclock`) and are ported together rather than split.
The shared tail (`:612-747`) -- `soda2_findsize`, the size/reject fields,
`dhist` -- and the driver (`soda2_process_2d.pro`) are later pairs; this
module stops exactly where the branch's own locals are last read, `:376`.

The branch reads **nothing from `buffer.image`** -- only `buffer.time`
(`:344`, `:362`, `:375`). All image data comes through **LUN 1**, a literal
unit number (`spec_read_hk(1,...)` `:285`, `spec_read_frame(1,...)`
`:292-293`): the caller has the raw file open as unit 1 before entering
this branch. This port takes an open binary file object instead.

Round 6-A adds :func:`soda2_processbuffer`, composing this branch
with `processbuffer_tail.process_buffer_tail` (the shared tail,
`:612-747`) into the whole `soda2_processbuffer.pro`, SPEC path, end to
end -- a `NullBuffer` from `process_spec_buffer` is passed straight
through without calling the tail, exactly as IDL returns `nullbuffer` at
`:267`/`:339` before reaching `:612`.

Validated against GDL by ``tests/test_soda2_processbuffer_spec.py``; bank
at ``gdl_oracle/run_soda2_processbuffer_spec_bank.py``, which runs the
*real* `soda2_processbuffer` (all 748 lines, via three oracle shims never
an edit to `SODA2/`) end to end on the tracked SPEC fixtures. Findings
S4-n through S4-q.

**Line-by-line** (IDL 0-based indexing throughout):

- `:266-267` -- `num_images = (*pmisc).nimages`; 0 -> return the null buffer
  (`rejectbuffer=1`) immediately.
- `:268-278` -- locals: `bitimage` starts as a single dummy blank slice
  (kept -- `slicecount=1` counts it), `startline`/`stopline` (uint32),
  `inttime` (float64), `overload` (uint8), `particle_count` (uint16),
  `rawtime` (uint32), `clocktas` (float32), `stretch` (float32, `+1.0`),
  `dof` (int16, `+1`).
- `:280-282` -- `c=0`; `lastclock = misc.lastclock`; `lasthkpointer = -1`.
- `:285-286` -- `spec_read_hk` is called **only when the HK pointer
  changed** since the previous image -- `lasthkpointer` is the guard.
  Version is never passed by either vendored caller, so this port never
  passes it either (the ported default, `version=1`).
- `:287-288` -- when `subformat ne 0`, `hk.tas = (*pmisc).probetas` on
  **every** image (the HK record read at `:285` is still read, version 1,
  from the image file, and its `tas` discarded). Assignment converts to the
  field's type, so `hk.tas` becomes `float32(probetas)` and reaches both
  `clocktas[c]` and the `:307-308` stretch test.
- `:291-295` -- `subformat` 0 reads `spec_read_frame(f, pointer, probeid)`
  (version 0, the original 2D-S/HVPS3 format); 1 reads
  `spec_read_frame(..., version=1)` (3VCPI/Hawkeye, Fast 2D-S); 2 reads
  `hvps4_read_frame(f, pointer, probeid)`. The `CASE` has no `ELSE`, so any
  other value is an IDL error: :class:`UnsupportedSpecSubformat` naming
  `:291`, raised **before any read**. `hvps4_read_frame` returns no
  `timetrunc`, which is safe only because `:316` is gated on `HVPS3`.
- `:296` -- a frame is kept only if `x.error == 0` **and**
  `max(x.image.shape) < 1000` -- this port's `image` is `(nslices, 128)`,
  so the IDL `max(size(x.image,/dim))` over `[128, nslices]` reduces, for
  every fixture case reached here, to the same `nslices < 1000` test
  (the 128 side never wins). A frame at or past 1000 slices is dropped
  silently, same as IDL -- no count kept (S4-q).
- `:297-304` -- kept frame: slices appended to `bitimage`; `startline[c]`,
  `stopline[c]`, `overload[c]`, `particle_count[c]`, `rawtime[c] = x.time`.
- `:303` -- `dofreject == 3` calls `binary_dof(x.image)` -- **now honoured**
  (`arrayprobe_soda2.binary_dof`), computed per kept frame
  and written into `dof[c]`.
- `:305-308` -- `clocktas[c] = hk.tas` (float32); `stretch[c] =
  clip(aircrafttas/hk.tas, 0.1, 10.0)` iff `aircrafttas > 0 and hk.tas > 0
  and stretchcorrect == 1` -- float32 arithmetic throughout.
- `:309` -- `freq = double(yres / (1.0e6 * clocktas[c]))`: the division
  itself runs in **float32** (`yres`, `1.0e6`, `clocktas` are all float32
  in IDL) and is only widened to double afterwards -- so `freq` carries
  float32 rounding baked into a float64 container (finding **S4-p**).
- `:311`, `:313` -- 3VCPI@50 um (`10.0/...`) and HVPS4@150 um (`50.0/...`)
  clock overrides, each gated on probetype **and** `res`; reached from
  `subformat=0` only by a hand-set op (S4-p's table). GDL-measured freqs:
  `tests/test_soda2_processbuffer_spec.py::TheClockOverridesAtLines311And313`.
- `:315-318` -- `HVPS3`: `x.time = x.timetrunc`; `rollovervalue = 65536`.
  Else: `rollovervalue = 4294967295.0` -- **2**:sup:`32` **- 1, not**
  2**32 (finding **S4-n**).
- `:320-322` -- the rollover-aware interarrival time: `inttime[c] =
  ((x.time + rollovervalue) - lastclock) * freq` if `x.time < lastclock`
  else `(x.time - lastclock) * freq`; `lastclock = x.time`.
- `:326` -- `misc.lastclock = lastclock`, written **before** the
  `num_images == 0` early return at `:338` -- a buffer whose every frame
  was dropped still writes `lastclock` forward (unchanged, since nothing
  advanced it -- "what turned out to be fine" in the design record).
- `:327-338` -- `num_images = c`; every per-frame array trimmed to
  `[0:c-1]` (`c == 0` reproduces IDL 8's "to the last element" as an empty
  result rather than an error); `max(stopline) > 10000` also rejects the
  whole buffer (a distinct path from `num_images == 0`).
- `:344` -- `reftime = misc.maxsfm` if `buffer.time == misc.lastbufftime`
  else `buffer.time`.
- `:352-357` -- the **backward** count: `elaptime` accumulates `inttime`
  left to right; `time_sfm[i] = reftime - (total(inttime) - elaptime)`.
  `total()` of a float64 array is a plain left-to-right sum under GDL,
  reproduced here with an explicit left-to-right loop. `np.sum` is not one
  (pairwise from eight elements); it agreed with the golden's
  `frame_h_all18` only because those interarrivals sum exactly.
- `:362-365` -- if `buffer.time == lastbufftime`: **overwrite**
  `time_sfm[0] = maxsfm`, then `time_sfm[i] = time_sfm[i-1] + inttime[i]`
  for `i >= 1` -- the first particle's own `inttime[0]` is never added
  (finding **S4-o**).
- `:371-375` -- `restore_slice = 0`; `missed = 0`; `misc.maxsfm =
  max(time_sfm)`; `misc.lastbufftime = buffer.time`.

**Package convention**: `bitimage` is `(nslices + 1, 128)` uint8, the dummy
first slice included (matching `spec_decompress`'s own row-major, "row 0
always blank" convention -- see that module's docstring).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO

import numpy as np

from .binary_dof import binary_dof
from .hvps4_read_frame import hvps4_read_frame
from .spec_read_frame import spec_read_frame
from .spec_read_hk import spec_read_hk

if TYPE_CHECKING:
    # Deferred to break the import cycle: processbuffer_tail imports
    # SpecBufferParticles from this module, so importing ProcessedBuffer back
    # from it at module level would be circular. Safe under type-checking
    # only because `from __future__ import annotations` (above) never
    # evaluates this annotation at runtime.
    from .processbuffer_tail import ProcessedBuffer

__all__ = [
    "SpecOp",
    "SpecMisc",
    "SpecBufferParticles",
    "NullBuffer",
    "UnsupportedSpecSubformat",
    "process_spec_buffer",
    "soda2_processbuffer",
]

_MAX_KEPT_STOPLINE = 10000
_MAX_FRAME_SLICES = 1000


class UnsupportedSpecSubformat(NotImplementedError):
    """`:291-295` -- a `subformat` outside 0-2. The IDL `CASE` has no
    `ELSE`, so such a value is an IDL error; raised before any read
    (`soda2_processbuffer.pro:291`)."""


@dataclass(frozen=True)
class SpecOp:
    """The `(*pop)` fields the branch reads, `:264-318`. IDL types in
    comments; `yres`/`res` are FLOAT (`soda2_probespecs.pro:9`) -- kept as
    Python floats but the `:309` division reproduces float32 semantics
    explicitly (SODA-2 register entry S4-p) regardless of this field's own storage."""

    probetype: str
    subformat: int
    probeid: str
    dofreject: int
    stretchcorrect: int
    yres: float   # FLOAT
    res: float    # FLOAT


@dataclass
class SpecMisc:
    """The `(*pmisc)` fields the branch reads and mutates in place, exactly
    where the IDL writes them (`:326`, `:374`, `:375`).

    Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file."""

    nimages: int
    hkpointers: Sequence[int]
    imagepointers: Sequence[int]
    probetas: float          # FLOAT
    aircrafttas: float       # FLOAT
    lastclock: float         # DOUBLE
    lastbufftime: float      # DOUBLE
    maxsfm: float            # DOUBLE


@dataclass
class NullBuffer:
    """`:18-20`'s `nullbuffer` -- the branch's `rejectbuffer=1` return, at
    `:267` (no images) or `:339` (kept slices exceed 10 000).

    Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file."""

    rejectbuffer: int = 1


@dataclass
class SpecBufferParticles:
    """The branch's locals at `:376`, what the shared tail consumes.
    `rejectbuffer` is always 0 here -- a rejected buffer is a
    :class:`NullBuffer` instead.

    Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file."""

    rejectbuffer: int
    num_images: int
    bitimage: np.ndarray          # uint8 (num_images+1, 128), dummy slice kept
    startline: np.ndarray         # uint32
    stopline: np.ndarray          # uint32
    overload: np.ndarray          # uint8
    particle_count: np.ndarray    # uint16
    rawtime: np.ndarray           # uint32
    clocktas: np.ndarray          # float32
    stretch: np.ndarray           # float32
    inttime: np.ndarray           # float64
    dof: np.ndarray               # int16
    time_sfm: np.ndarray          # float64
    reftime: float                # DOUBLE
    restore_slice: int = 0
    missed: int = 0


def _freq(yres: float, clocktas: float) -> float:
    """`:309` -- `freq = double(yres / (1.0e6 * clocktas))`, computed in
    float32 and only then widened (S4-p)."""
    y32 = np.float32(yres)
    c32 = np.float32(clocktas)
    m32 = np.float32(1.0e6)
    return float(y32 / (m32 * c32))


def process_spec_buffer(
    f: BinaryIO, buffer_time: float, op: SpecOp, misc: SpecMisc,
) -> SpecBufferParticles | NullBuffer:
    """``p = soda2_processbuffer(buffer, pop, pmisc)``, the SPEC branch
    only (`:264-376`). ``f`` is the open raw file IDL has as LUN 1;
    ``buffer_time`` is `buffer.time`. ``misc`` is mutated in place, exactly
    where the IDL writes `(*pmisc)`.

    Source: ``soda2_processbuffer.pro:264-376`` (SODA-2); bare line references here are into that
    file.
    """
    if op.subformat not in (0, 1, 2):
        raise UnsupportedSpecSubformat(
            f"soda2_processbuffer.pro:291: subformat={op.subformat!r} matches "
            "no CASE arm (0, 1, 2) and the CASE has no ELSE")
    # `:266-267`.
    num_images_in = misc.nimages
    if num_images_in == 0:
        return NullBuffer()

    # `:268-278` -- locals, one dummy blank slice kept at index 0.
    bitimage_slices: list[np.ndarray] = [np.zeros(128, dtype=np.uint8)]
    startline = np.zeros(num_images_in, dtype=np.uint32)
    stopline = np.zeros(num_images_in, dtype=np.uint32)
    inttime = np.zeros(num_images_in, dtype=np.float64)
    overload = np.zeros(num_images_in, dtype=np.uint8)
    particle_count = np.zeros(num_images_in, dtype=np.uint16)
    rawtime = np.zeros(num_images_in, dtype=np.uint32)
    clocktas = np.zeros(num_images_in, dtype=np.float32)
    stretch = np.ones(num_images_in, dtype=np.float32)
    dof = np.ones(num_images_in, dtype=np.int16)

    # `:280-282`.
    c = 0
    slicecount = 1
    lastclock = misc.lastclock
    lasthkpointer = -1
    hk = None

    for i in range(num_images_in):
        hk_pointer = misc.hkpointers[i]
        img_pointer = misc.imagepointers[i]

        # `:285-286`.
        if hk_pointer != lasthkpointer:
            hk = spec_read_hk(f, hk_pointer)
            lasthkpointer = hk_pointer
        assert hk is not None

        # `:287-288` -- every iteration, not only after a fresh `:285` read.
        if op.subformat != 0:
            hk.tas = np.float32(misc.probetas)

        # `:291-295`.
        x: Any
        if op.subformat == 0:
            x = spec_read_frame(f, img_pointer, op.probeid)
        elif op.subformat == 1:
            x = spec_read_frame(f, img_pointer, op.probeid, version=1)
        else:
            x = hvps4_read_frame(f, img_pointer, op.probeid)

        # `:296` -- keep iff error==0 and slice count < 1000 (S4-q).
        if x.error != 0 or x.image.shape[0] >= _MAX_FRAME_SLICES:
            continue

        # `:297-304`.
        for row in range(x.image.shape[0]):
            bitimage_slices.append(x.image[row].astype(np.uint8))
        startline[c] = slicecount
        slicecount += x.image.shape[0]
        stopline[c] = slicecount - 1
        overload[c] = x.overload
        particle_count[c] = x.particlecount
        rawtime[c] = x.time

        # `:303` -- `dofreject == 3` calls `binary_dof(x.image)` per kept
        # frame; every other `dofreject` value leaves `dof[c]` at its `:278`
        # initial value of 1.
        if op.dofreject == 3:
            dof[c] = binary_dof(x.image).dof

        # `:305-308`.
        clocktas[c] = hk.tas
        if (misc.aircrafttas > 0 and float(hk.tas) > 0
                and op.stretchcorrect == 1):
            ratio = np.float32(misc.aircrafttas) / np.float32(hk.tas)
            stretch[c] = np.clip(ratio, np.float32(0.1), np.float32(10.0))

        # `:309`.
        freq = _freq(op.yres, float(clocktas[c]))

        # `:311`, `:313` -- the 50 um Hawkeye array runs on the 10 um clock
        # and the 150 um HVPS-4 array on the 50 um clock: each override
        # needs its `res` as well as its probetype, and the numerator is the
        # clock's resolution, not the array's. probespecs gives these two
        # probes subformat 1 and 2.
        if op.probetype == "3VCPI" and op.res == 50:
            freq = _freq(10.0, float(clocktas[c]))
        if op.probetype == "HVPS4" and op.res == 150:
            freq = _freq(50.0, float(clocktas[c]))

        # `:315-318`.
        xtime = int(x.time)
        if op.probetype == "HVPS3":
            xtime = int(x.timetrunc)
            rollovervalue = 65536.0
        else:
            rollovervalue = 4294967295.0  # 2**32 - 1, not 2**32 (S4-n)

        # `:320-322`.
        if xtime < lastclock:
            inttime[c] = ((xtime + rollovervalue) - lastclock) * freq
        else:
            inttime[c] = (xtime - lastclock) * freq
        lastclock = xtime

        c += 1

    # `:326` -- written before the `num_images == 0` early return below.
    misc.lastclock = lastclock

    # `:327-338`.
    num_images = c
    startline = startline[:num_images]
    stopline = stopline[:num_images]
    overload = overload[:num_images]
    particle_count = particle_count[:num_images]
    rawtime = rawtime[:num_images]
    clocktas = clocktas[:num_images]
    stretch = stretch[:num_images]
    inttime = inttime[:num_images]
    dof = dof[:num_images]

    if num_images == 0:
        return NullBuffer()
    if int(stopline.max()) > _MAX_KEPT_STOPLINE:
        return NullBuffer()

    bitimage = np.stack(bitimage_slices, axis=0)

    # `:344`.
    if buffer_time == misc.lastbufftime:
        reftime = misc.maxsfm
    else:
        reftime = buffer_time

    # `:352-357` -- backward count, left-to-right accumulation (U1).
    # `total(inttime)` is a sequential double sum under GDL; `np.sum` is
    # pairwise from eight elements up and differs from it once an addend is
    # inexact, which the first buffer's `x.time - 0` interarrival (a 32-bit
    # count times a FLOAT period) makes it.
    total_inttime = 0.0
    for value in inttime:
        total_inttime += float(value)
    time_sfm = np.zeros(num_images, dtype=np.float64)
    elaptime = 0.0
    for i in range(num_images):
        elaptime += float(inttime[i])
        time_sfm[i] = reftime - (total_inttime - elaptime)

    # `:362-365` -- overwrite; inttime[0] never added (S4-o).
    if buffer_time == misc.lastbufftime:
        time_sfm[0] = misc.maxsfm
        for i in range(1, num_images):
            time_sfm[i] = time_sfm[i - 1] + inttime[i]

    # `:371-375`.
    misc.maxsfm = float(time_sfm.max())
    misc.lastbufftime = buffer_time

    return SpecBufferParticles(
        rejectbuffer=0,
        num_images=num_images,
        bitimage=bitimage,
        startline=startline,
        stopline=stopline,
        overload=overload,
        particle_count=particle_count,
        rawtime=rawtime,
        clocktas=clocktas,
        stretch=stretch,
        inttime=inttime,
        dof=dof,
        time_sfm=time_sfm,
        reftime=reftime,
        restore_slice=0,
        missed=0,
    )


def soda2_processbuffer(
    f: BinaryIO, buffer_time: float, op: SpecOp, tail_op: Any,
    misc: SpecMisc, lastdhist: Any,
) -> NullBuffer | ProcessedBuffer:
    """``p = soda2_processbuffer(buffer, pop, pmisc)``, SPEC path, whole
    function (`:264-747`) -- composes :func:`process_spec_buffer` with
    `processbuffer_tail.process_buffer_tail`. A `NullBuffer` from the
    branch is returned immediately, without calling the tail, matching
    IDL's early `nullbuffer` returns at `:267`/`:339`.

    Source: ``soda2_processbuffer.pro:264-747`` (SODA-2); bare line references here are into that
    file.
    """
    from .processbuffer_tail import process_buffer_tail

    result = process_spec_buffer(f, buffer_time, op, misc)
    if isinstance(result, NullBuffer):
        return result
    return process_buffer_tail(result, tail_op, lastdhist)
