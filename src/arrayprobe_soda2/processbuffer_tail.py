# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_processbuffer.pro:612-747`` -- the shared per-particle tail, SPEC path.

Round 6-A. Ports "Code common to all probes" (`:612-747`) for the
locals `processbuffer_spec.process_spec_buffer` produces
(`probetype in {'2DS','HVPS3'}`, `subformat 0`): a `SpecBufferParticles`
(never a `NullBuffer` -- the caller, :func:`soda2_processbuffer` in
`processbuffer_spec.py`, passes a `NullBuffer` straight through without
calling this module, exactly as IDL returns `nullbuffer` at `:267`/`:339`
before reaching `:612`).

**Convention.** This package's `bitimage` is `(nslices+1, 128)` uint8,
slice axis first (`processbuffer_spec.py`'s docstring). IDL's
`bitimage[fp:lp, startline:stopline]` is diode-then-slice; the equivalent
slice here is ``bitimage[startline:stopline+1, fp:lp+1]``, i.e. `roi` is
`(roilen, ndiodes)` -- exactly `fillholes.py`'s and `findsize.py`'s own
`(slices, diodes)` convention, so no per-call transpose is needed.
`label_blobs.py` names its axes generically (`s0`/`s1`); the flood fill is
symmetric in the two axes, so passing `(roilen, ndiodes)` there is also
correct, just not the axis identity its own docstring assumes for the
`:687-689` caller in IDL terms.

**A 1-slice ROI is 1-D in IDL** (`bitimage[fp:lp, s:s]` drops the trailing
dimension). Reproduced here: when `roilen == 1`, `roi`/`roi_orig` are
squeezed to 1-D (`roi[0]`) before `label_blobs`, `fillholes` and
`soda2_findsize` see them -- all three already handle 1-D input.

**Not ported / refused before any leaf call** (never invented):

- `greythresh > 0` (`:666`) -- every SPEC entry in `soda2_probespecs.pro`
  carries `greythresh 0`; refused by name.
- HAIL (`:656-663`) and 1D2D's `area75` (`:638`) -- unreachable for SPEC;
  `area75` stays zeros.

**Findings** (measured against the GDL bank,
`gdl_oracle/run_soda2_processbuffer_spec_bank.py`):

- **S5-f**: `stuckbits=1` corrupts diode `numdiodes-8` in every buffer that
  follows a clean second -- `fixstuckbits`'s S4-x negative-index corruption
  reached through `:615`'s always-defined `h=sbhist` for SPEC
  (`soda2_process_2d.pro:41,498`).
- **S5-g**: an all-overload (empty-particle) buffer reaches the tail with
  an all-zero `bitimage`; `streak = max(diodetotal)/mean(diodetotal) gt 3`
  is `0/0`, an IDL floating-point error whose *value* is well defined
  (`NaN gt 3` is false, `streak=0`) -- computed here under
  `np.errstate(all="ignore")`.
- **S5-h**: the same empty ROI makes `where(roihist gt 0, nw)` return
  `nw=0`, `w=-1` (IDL's no-match sentinel), so
  `xspan = max(-1)-min(-1)+1 = 1` and `diodegaps = 1 - 0 = 1`, not 0.



"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .backfill import soda2_backfill
from .fillholes import fillholes
from .findsize import soda2_findsize
from .fixraking import fixraking
from .fixstuckbits import fixstuckbits
from .label_blobs import label_blobs
from .poisson_spot_correct import poisson_spot_correct
from .processbuffer_spec import SpecBufferParticles

__all__ = ["TailOp", "ProcessedBuffer", "process_buffer_tail"]


@dataclass(frozen=True)
class TailOp:
    """The `(*pop)` fields the tail (`:612-747`) reads, beyond `SpecOp`.
    No defaults -- every field is a fidelity-relevant threshold and must
    be given explicitly (the same discipline `profiles.py` applies to
    `FidelityProfile`). IDL types in comments; `res`/`yres` are FLOAT.

    Source: ``soda2_processbuffer.pro:612-747`` (SODA-2)."""

    stuckbits: int
    rakefix: int
    greythresh: int
    dioderange: tuple[int, int]
    numdiodes: int
    keeplargest: int
    res: float    # FLOAT
    yres: float   # FLOAT
    #: Speed only, and the ONE field here that carries a default. Every other
    #: field is a fidelity-relevant threshold and must be given explicitly; this
    #: one moves no written byte -- label_blobs routes _label_region through
    #: arrayprobe_soda2.jit_kernels when set, and
    #: tests/test_soda2_label_region_jit_identity.py proves the two paths
    #: byte-identical with mutation tests showing the comparison discriminates.
    #: Default False, so an op that does not set it is unchanged.
    jit: bool = False


@dataclass
class ProcessedBuffer:
    """`soda2_processbuffer.pro:740-747`'s 40-field return structure, in
    declaration order."""

    diam: np.ndarray
    xsize: np.ndarray
    ysize: np.ndarray
    xextent: np.ndarray
    areasize: np.ndarray
    oned: np.ndarray
    twod: np.ndarray
    probetime: np.ndarray
    reftime: float
    rawtime: np.ndarray
    ar: np.ndarray
    arfilled: np.ndarray
    aspr: np.ndarray
    rejectbuffer: int
    bitimage: np.ndarray
    allin: np.ndarray
    centerin: np.ndarray
    streak: int
    zd: np.ndarray
    sizecorrection: np.ndarray
    dhist: np.ndarray
    nslices: int
    missed: int
    diodegaps: np.ndarray
    overloadflag: np.ndarray
    dofflag: np.ndarray
    xpos: np.ndarray
    ypos: np.ndarray
    orientation: np.ndarray
    area_orig: np.ndarray
    area_filled: np.ndarray
    perimeterarea: np.ndarray
    area75: np.ndarray
    particlecounter: np.ndarray
    edgetouch: np.ndarray
    inttime: np.ndarray
    clocktas: np.ndarray
    startline: np.ndarray
    stopline: np.ndarray
    numregions: np.ndarray


class RakefixNotPorted(NotImplementedError):
    """Formerly raised for `soda2_processbuffer.pro:616` `rakefix>0`; no
    longer raised now that `fixraking.pro` is ported (`fixraking.py`).
    Kept for import compatibility."""


class GreythreshNotPorted(NotImplementedError):
    """`soda2_processbuffer.pro:666`: `greythresh>0` grey-probe adjustment
    not ported; no SPEC entry in `soda2_probespecs.pro` carries a nonzero
    `greythresh`."""


class RestoreSliceNotPorted(NotImplementedError):
    """Formerly raised for `soda2_processbuffer.pro:678` `restore_slice`
    true; no longer raised now that `soda2_backfill.pro` is ported
    (`backfill.py`). Kept for import compatibility."""


def _dioderange(op: TailOp) -> tuple[int, int]:
    fp, lp = op.dioderange
    if lp == 0:
        lp = op.numdiodes - 1
    return fp, lp


def process_buffer_tail(
    p: SpecBufferParticles, op: TailOp, lastdhist: np.ndarray,
) -> ProcessedBuffer:
    """``soda2_processbuffer.pro:612-747``, SPEC path only. ``lastdhist``
    is ``(*pmisc).lastdhist`` -- unused directly (``fixstuckbits`` already
    consumed it at ``:615`` when ``op.stuckbits`` is set, via the caller),
    kept as a parameter only to assert its shape against ``op.numdiodes``.
    """
    lastdhist = np.asarray(lastdhist)
    if lastdhist.shape != (op.numdiodes,):
        raise ValueError(
            f"lastdhist shape {lastdhist.shape} != (numdiodes,)="
            f"({op.numdiodes},)")

    if op.greythresh > 0:
        raise GreythreshNotPorted(
            "soda2_processbuffer.pro:666: greythresh>0 grey-probe path "
            "not ported")

    num_images = p.num_images
    # `:613-615`. `bitimage_orig` is a copy of the buffer's own image,
    # taken before `fixstuckbits` (trap 8) -- `roi_orig` is built from it
    # below so stuck-bit corruption never reaches `dhist`. `fixstuckbits`
    # is diode-axis-first (`h=lastdhist` has length `numdiodes`), so the
    # buffer's own (slice, diode) layout is transposed in and back out.
    bitimage_orig = p.bitimage
    if op.stuckbits:
        bitimage = fixstuckbits(bitimage_orig.T, h=lastdhist).T
    else:
        bitimage = bitimage_orig
    # `:616`. `fixraking` is [diode, slice] like `fixstuckbits`, so the
    # buffer's (slice, diode) layout is transposed in and back out.
    if op.rakefix > 0:
        bitimage = fixraking(bitimage.T, op.rakefix).T

    # `:617-618`. `total(bitimage,2)` in IDL's [diode,slice] layout sums
    # over slices, leaving one value per diode -- axis=0 here.
    with np.errstate(all="ignore"):
        diodetotal = bitimage.sum(axis=0).astype(np.float32)
        ratio = np.max(diodetotal) / np.mean(diodetotal)
        streak = 1 if ratio > 3 else 0

    fp, lp = _dioderange(op)

    diam = np.zeros(num_images, dtype=np.float32)
    xsize = np.zeros(num_images, dtype=np.float32)
    ysize = np.zeros(num_images, dtype=np.float32)
    xextent = np.zeros(num_images, dtype=np.float32)
    areasize = np.zeros(num_images, dtype=np.float32)
    oned = np.zeros(num_images, dtype=np.float32)
    twod = np.zeros(num_images, dtype=np.float32)
    allin = np.zeros(num_images, dtype=np.uint8)
    centerin = np.zeros(num_images, dtype=np.uint8)
    edgetouch = np.zeros(num_images, dtype=np.uint8)
    arearatio = np.zeros(num_images, dtype=np.float32)
    arearatiofilled = np.zeros(num_images, dtype=np.float32)
    aspr = np.zeros(num_images, dtype=np.float32)
    orientation = np.zeros(num_images, dtype=np.float32)
    area_orig = np.zeros(num_images, dtype=np.float32)
    area_filled = np.zeros(num_images, dtype=np.float32)
    perimeterarea = np.zeros(num_images, dtype=np.float32)
    area75 = np.zeros(num_images, dtype=np.float32)  # :638, 1D2D only, unreachable
    zd = np.zeros(num_images, dtype=np.float32)
    sizecorrection = np.ones(num_images, dtype=np.float32)
    xpos = np.zeros(num_images, dtype=np.float32)
    ypos = np.zeros(num_images, dtype=np.float32)
    diodegaps = np.zeros(num_images, dtype=np.int16)
    numregions = np.zeros(num_images, dtype=np.uint8)
    dhist = np.zeros(op.numdiodes, dtype=np.int16)

    overloadflag = p.overload

    nslices = 0

    for i in range(num_images):
        s, e = int(p.startline[i]), int(p.stopline[i])
        roi: Any = bitimage[s:e + 1, fp:lp + 1]
        roi_orig: Any = bitimage_orig[s:e + 1, fp:lp + 1]
        roilen = e - s + 1
        nslices += roilen

        if roilen == 1:
            roi = roi[0]
            roi_orig = roi_orig[0]

        # `:678` -- `soda2_backfill` is applied to the ROI when `restore_slice` is set. 2DC branch
        # only (`:114-115`); roi_orig is untouched.
        if p.restore_slice:
            roi = soda2_backfill(roi)

        # `:686-700` -- keeplargest.
        if op.keeplargest != 0:
            # `jit` is a speed-only switch: label_blobs routes _label_region
            # through arrayprobe_soda2.jit_kernels when set, and
            # tests/test_soda2_label_region_jit_identity.py proves the two
            # paths byte-identical (np.array_equal, with mutation tests showing
            # the comparison is a real discriminator). Default off, so an op
            # that does not set it is unchanged.
            _jit = bool(getattr(op, "jit", False))
            if op.keeplargest == 1:
                blobs = label_blobs(roi, dilatelength=2, jit=_jit)
            elif op.keeplargest == 2:
                blobs = label_blobs(roi, dilatelength=1, jit=_jit)
            else:
                blobs = label_blobs(roi, dilatelength=0, all_neighbors=True, jit=_jit)
            nblobs = int(blobs.max()) if blobs.size else 0
            numregions[i] = nblobs % 256
            if nblobs > 1:
                counts = np.bincount(blobs.ravel().astype(np.int64),
                                      minlength=nblobs + 1)[1:nblobs + 1]
                ilargest = int(np.argmax(counts))  # first maximum
                good = blobs == (ilargest + 1)
                roi2 = np.zeros_like(roi)
                roi2[good] = roi[good]
                roi = roi2

        # `:703-704`.
        if roilen == 1:
            roihist = roi_orig.astype(np.float64)
        else:
            roihist = roi_orig.sum(axis=0).astype(np.float64)
        dhist[fp:lp + 1] += roihist.astype(np.int16)

        # `:707-709`.
        w = np.flatnonzero(roihist > 0)
        nw = w.size
        if nw == 0:
            xspan = 1  # max(-1)-min(-1)+1, IDL no-match sentinel -- S5-h
        else:
            xspan = int(w.max()) - int(w.min()) + 1
        diodegaps[i] = xspan - nw

        # `:712-716`.
        area_orig[i] = float(np.sum(roi, dtype=np.float64))
        roifilled = fillholes(roi, jit=bool(getattr(op, "jit", False)))
        area_filled[i] = float(np.sum(roifilled, dtype=np.float64))
        pc = poisson_spot_correct(area_orig[i], area_filled[i])
        sizecorrection[i] = pc.correction
        zd[i] = pc.zd

        # `:719-737`.
        yres_eff = np.float32(op.yres) * np.float32(p.stretch[i])
        part = soda2_findsize(
            roi, np.float32(op.res), yres_eff,
            voidarea=float(area_filled[i]) - float(area_orig[i]))
        diam[i] = part.diam
        xsize[i] = part.xsize
        ysize[i] = part.ysize
        xextent[i] = part.xextent
        oned[i] = part.oned
        twod[i] = part.twod
        areasize[i] = part.areasize
        arearatio[i] = part.ar
        arearatiofilled[i] = part.arfilled
        aspr[i] = part.aspr
        allin[i] = part.allin
        centerin[i] = part.centerin
        edgetouch[i] = part.edgetouch
        xpos[i] = part.c[0]
        ypos[i] = part.c[1]
        orientation[i] = part.orientation
        perimeterarea[i] = part.perimeterarea

    return ProcessedBuffer(
        diam=diam, xsize=xsize, ysize=ysize, xextent=xextent,
        areasize=areasize, oned=oned, twod=twod,
        probetime=p.time_sfm, reftime=p.reftime, rawtime=p.rawtime,
        ar=arearatio, arfilled=arearatiofilled, aspr=aspr,
        rejectbuffer=0, bitimage=bitimage, allin=allin, centerin=centerin,
        streak=streak, zd=zd, sizecorrection=sizecorrection, dhist=dhist,
        nslices=nslices, missed=p.missed, diodegaps=diodegaps,
        overloadflag=overloadflag, dofflag=p.dof, xpos=xpos, ypos=ypos,
        orientation=orientation, area_orig=area_orig,
        area_filled=area_filled, perimeterarea=perimeterarea,
        area75=area75, particlecounter=p.particle_count,
        edgetouch=edgetouch, inttime=p.inttime, clocktas=p.clocktas,
        startline=p.startline, stopline=p.stopline, numregions=numregions,
    )
