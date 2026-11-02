# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_process_2d.pro`` -- the SODA-2 driver, SPEC path and (CIP-1) the
SEA/CIP route,
raw bytes to the in-memory ``data``. Composes every module
ported in rounds
5-6 (``update_op``, ``buildindex``, ``process_hk``, ``read2dbuffer``,
``processbuffer_spec``/``processbuffer_tail``, ``particlesort``,
``sample_area``) into the whole driver body. **Round 9
wires in the PBP writers** (``pbp_writer.py``): ``particlefile
== 1`` (``.pbp.csv``) and ``ncdfparticlefile in (1,)`` (``.pbp.nc``, the
non-image variant) now write real per-particle output, one call, raw bytes
to ``.pbp.*``. ``fn_pbp`` reprocesses from an existing ``.pbp.nc``
(``:30-35``, ``:584-617``; :mod:`reprocess_pbp`) and writes no particle file.

Vendored source: ``SODA2/abansemer-soda2-afcea15/soda2_process_2d.pro``, 742
lines. **Never edited.** Its scope table, traps and GDL bank are recorded in the
project's development record.

**Not ported here:**
- ``:241-354``, ``:286-306`` -- particle-image output (``ncdfparticlefile ==
  2``) is ported on the serial path; with ``jobs > 1`` it raises
  ``PbpImagesNotPorted`` before any file read.
- ``:732-739`` -- the widget/``print`` notification after the SAVE (a
  ``dialog_message`` or ``print, infoline``): console only, not reproduced.

**PTH files:** ``dat``/``sav`` (`:131-145`, W2) -- ``_pth_from_sav``
below; ``txt``/``csv``/``nc`` (`:147-172`) --
``pth_readers.read_pth``. ``pth`` set and missing raises at ``:185-186`` (an
IDL ``stop``).

**Ported late:** the ASCII PSD export (``:722-726``, ``asciipsdfile``, W4;
``export_ascii.soda2_export_ascii``) and, after it in IDL order,
the IDL SAVE file (``:729-731``, ``savfile``, W1;
``save_writer.save_process_data``), which replaced the earlier
``pbp_writer.SaveFileNotPorted`` -- that class was defined but never raised,
so ``savfile=1`` (the ``update_op`` default) silently wrote no ``.dat``.
- ``:376`` -- more than one raw file in ``op.fn`` (SPEC-only scope, same
  restriction ``spec_process_hk``/``soda2_buildindex`` already carry).
- ``:493`` -- ``activetimefrommissed`` (an IDL ``stop``, "Under development"
  in the source itself).

**S6-f (read-only):** the
early ``return`` at both ``:430-433`` and ``:576`` fires **after** the PBP
files are opened (``:197-354``) but **before** the tail close block
(``:689-721``, ``close,lun_pbp`` / ``ncdf_close,ncdf_id``) ever runs -- so a
window with no buffers, or a tail flush that lands exactly on empty, leaves
both ``.pbp.csv`` and ``.pbp.nc`` open with header/definitions written but
never closed. This port reproduces it exactly: :func:`soda2_process_2d`
returns ``None`` on both paths without calling ``close_pbp_ncdf``/
``csv_f.close()`` when writers were opened.

**Traps**, cited to the plan's numbering (S6-a..S6-d are the measured/derived
findings):

1. (S6-a) The processing window includes one buffer at or before
   ``starttime`` and one at or after ``stoptime`` (`:427-429`):
   ``firstbuff = max(where(bufftime lt starttime)) > 0`` (no match -> ``-1 >
   0`` -> 0); ``lastbuff = min(where(bufftime gt stoptime))`` (no match ->
   ``numbuffs-1``). Both edge buffers are processed and folded into the edge
   time records via ``timeindex``'s clamp at `:454`.
2. (S6-b) A date mismatch of more than 5 days between ``op.date`` and the
   file's own first buffer date makes the driver **silently adopt the file's
   date** (`:410-418`); a mismatch of 1-5 days shifts every buffer by whole
   days and typically empties the requested window (returns ``None``).
3. (S6-c) ``lastdhist`` is read from the **current** record's ``dhist``
   after it has already been updated with the just-processed buffer
   (`:497-498``, order preserved exactly).
4. ``numrecords``/``timeindex``/``buffindex`` are IDL ``long()`` --
   truncation toward zero, not floor.
5. ``x``'s per-field dtypes at the ``particlesort`` call (`:113-117``,
   `:510-544``) -- see ``_X_DTYPES`` below.
6. ``probetas = interpol(house.tas, house.time, b.time)`` (`:462``) runs
   only when ``nimages > 0``.
7. (S6-d, S6-f) The 10,000,000-particle flush (`:565-573``): ``soda2_particlesort``
   is called on ``x[0:istop]``, then ``istop`` resets to -1 and
   ``ncdf_offset`` advances; if the buffers processed after the last flush
   add no particles, ``istop`` stays -1 and the driver returns ``None`` at
   `:576`, **discarding nothing new but reporting no output** for that tail
   -- and (S6-f) leaving any open PBP writers unclosed.
8. Concentration dtypes (`:625-675``): ``spec1d`` is float32, taken before
   the ``corr_fac`` clamp (IDL's ``>`` is MAX, not comparison) is applied to
   both ``spec1d`` and ``d.spec2d``/``d.spec2d_aspr`` in place.
   ``soda2_samplearea``'s IDL signature carries a ``smethod`` positional
   parameter between ``eawmethod`` and ``wavelength``
   (``soda2_samplearea.pro:1``); it is never read in that function's body
   (grepped directly), and this port's ``sample_area.sample_area`` already
   omits it -- confirmed, not guessed.
9. ``orientation_index`` (`:669-673``) only ever fires when a bin's total
   orientation histogram exceeds 50 counts; never reached on the tracked
   fixtures.
10. ``aircrafttas`` (`:652-653``): ``pth_tas`` when ``got_pth == 1``
    (``fixedtas > 0``), else ``d.tas``.
11. ``buffindex`` (the driver's local, returned as ``data.ind``) is kept as
    computed -- "for output only" per the source's own comment -- and can be
    negative for a buffer before ``starttime``.

Findings registered: S6-a, S6-b, S6-c, S6-d (``tests/test_soda2_findings_are_registered.py``).
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import numpy as np

from . import processbuffer_cip as _pb_cip
from . import processbuffer_spec as _pb_spec
from . import processbuffer_tail as _pb_tail
from .buildindex import GenericIndex, buildindex, point_lun
from .export_ascii import soda2_export_ascii
from .particlesort import (
    Accumulator,
    ParticlesortOptions,
    new_accumulator,
    soda2_particlesort,
    spec_sort_locals,
)
from .pbp_writer import (
    PbpImagesNotPorted,
    close_pbp_ncdf,
    open_pbp_csv,
    open_pbp_ncdf,
    pbp_filename,
    write_pbp_csv_buffer,
    write_pbp_ncdf_buffer,
    write_pbp_ncdf_images,
)
from .process_hk import HouseData, _interpol, process_hk
from .processbuffer_cip import CipMisc, CipOp, soda2_processbuffer_cip
from .processbuffer_spec import NullBuffer, SpecMisc, SpecOp, soda2_processbuffer
from .processbuffer_tail import TailOp
from .pth_readers import pth_suffix as _pth_suffix
from .pth_readers import read_pth
from .read2dbuffer import DmtBuffer2D, SeaBuffer2D, read2dbuffer
from .sample_area import sample_area
from .save_writer import save_process_data
from .timeconv import soda2_parsedate
from .update_op import update_op

__all__ = ["ProcessData", "SeaHouse", "NUM2PROCESS", "soda2_process_2d"]

#: `:565` `num2process` literal -- a module constant, overridable per call
#: for tests (§3 trap 7).
NUM2PROCESS = 10_000_000

#: `:105` `maxslices` -- the image flush threshold (`:564`), overridable for tests.
MAXSLICES = 10_000_000

#: `:113-117` -- the ``basestruct`` dtypes, keyed by the lower-case tag name.
#: ``particlesort.py``'s ``X_TAGS`` lists the subset ``soda2_particlesort``
#: itself reads; this table is the superset the driver's ``x`` struct
#: actually declares (plus ``startline``/``stopline``, always 0 here --
#: ``ncdfparticlefile eq 2`` only, lane B).
_X_DTYPES: dict[str, Any] = {
    "buffertime": np.float64, "probetime": np.float64, "reftime": np.float64,
    "rawtime": np.float64, "inttime": np.float64,
    "diam": np.float32, "xsize": np.float32, "ysize": np.float32,
    "xextent": np.float32, "areasize": np.float32, "oned": np.float32,
    "twod": np.float32, "arearatio": np.float32, "arearatiofilled": np.float32,
    "aspectratio": np.float32, "area": np.float32, "areafilled": np.float32,
    "perimeterarea": np.float32, "area75": np.float32, "xpos": np.float32,
    "ypos": np.float32, "probetas": np.float32, "aircrafttas": np.float32,
    "zd": np.float32, "sizecorrection": np.float32, "missed": np.float32,
    "orientation": np.float32,
    "allin": np.uint8, "centerin": np.uint8, "edgetouch": np.uint8,
    "dofflag": np.uint8, "numregions": np.uint8,
    "particlecounter": np.int32,
    "diodegaps": np.int16,
    "startline": np.uint64, "stopline": np.uint64,
    "overloadflag": np.uint8,
}

#: `x` keys, driver declaration order (`:510-544``, plus `startline`/`stopline`).
_X_KEYS = tuple(_X_DTYPES.keys())

#: The two composed per-buffer calls as *this module* bound them at import.
#:
#: They are a substitution surface, not just an import. The 2016 UND emulation
#: (the ``rollover-65536`` part) recompiles
#: ``processbuffer_spec.py`` whole and **rebinds ``process_2d.soda2_processbuffer``**
#: on this module, because its target is inline in ``process_spec_buffer`` and
#: has no separately-named call to patch; ``soda2_particlesort`` is rebound the
#: same way. The serial loop below therefore calls these names as module
#: globals, exactly as before the front/tail split, so a rebind still takes
#: effect.
#:
#: Recorded here so :func:`process_2d_parallel.refuse_unsplittable` can *refuse*
#: ``jobs > 1`` when one has been replaced: the split loop calls the two halves
#: directly and cannot honour a replaced composition. (``soda2_particlesort`` is
#: not in this dict -- the split path reaches it through this module's own
#: ``_flush``, so a rebind of it is honoured.)
_PRISTINE_CALLS: dict[str, Any] = {
    "soda2_processbuffer": soda2_processbuffer,
    "soda2_processbuffer_cip": soda2_processbuffer_cip,
}


@dataclass
class SeaHouse:
    """``house={op:op}`` (``soda2_process_2d.pro:394``) -- the SEA/CIP
    branch's housekeeping placeholder when ``n_elements(op.seatag) lt 2``
    (`:397-398` then skips ``process_cip1d_sea``). CIP-1: a
    ``seatag`` of two or more elements fires ``process_cip1d_sea`` instead,
    which gives ``data.house`` a different struct entirely (its own tag set, no
    ``time``/``tas``/``nb``): `soda2_process_2d` then stores
    :func:`process_hk.process_cip1d_sea`'s result, not this placeholder."""

    op: dict


class Soda2ProcessError(RuntimeError):
    """An IDL ``stop`` this module reproduces as a raise, naming the line."""


@dataclass
class ProcessData:
    """``data`` (`:678-687``), declaration order. ``date_processed`` is
    non-deterministic (like UIOOPS's ``'Creation Time'``) -- exclude it from
    every comparison.

    Source: ``soda2_process_2d.pro:678-687`` (SODA-2)."""

    op: dict
    time: np.ndarray
    tas: np.ndarray
    probetas: np.ndarray
    midbins: np.ndarray
    activetime: np.ndarray
    date_processed: str
    sa: np.ndarray
    intspec_all: np.ndarray
    intspec_accepted: np.ndarray
    intendbins: np.ndarray
    intmidbins: np.ndarray
    count_rejected: np.ndarray
    total_count_rejected: np.ndarray
    count_accepted: np.ndarray
    count_missed: np.ndarray
    missed_hist: np.ndarray
    conc1d: np.ndarray
    spec1d: np.ndarray
    spec2d: np.ndarray
    spec2d_aspr: np.ndarray
    corr_fac: np.ndarray
    poisson_fac: np.ndarray
    intcutoff: np.ndarray
    zdspec: np.ndarray
    zdendbins: np.ndarray
    zdmidbins: np.ndarray
    pointer: np.ndarray
    ind: np.ndarray
    currentfile: np.ndarray
    numbuffsaccepted: np.ndarray
    numbuffsrejected: np.ndarray
    dhist: np.ndarray
    hist3d: np.ndarray
    spec2d_orientation: np.ndarray
    orientation_index: np.ndarray
    #: ``dict`` when two or more SEA tags give process_cip1d_sea's record (`:397-398`).
    house: HouseData | SeaHouse | dict
    pbpstartindex: np.ndarray
    pbp_csv_path: str | None = None
    """Path of the ``.pbp.csv`` this call wrote (``particlefile=1``); ``None`` when none was
    opened. Port tooling only (for the ``.pbp.call`` sidecar): not a ``data`` field
    of `soda2_process_2d.pro`, and it changes no number."""
    pbp_ncdf_path: str | None = None
    """Same, for the ``.pbp.nc`` (``ncdfparticlefile>=1``)."""
    save_path: str | None = None
    """Same, for the IDL SAVE ``.dat`` (``savfile=1``)."""


def _spec_op(op: dict) -> SpecOp:
    """``op`` dict -> :class:`processbuffer_spec.SpecOp`. Every field is read
    by name; a field ``update_op`` did not supply is a ``KeyError``."""
    return SpecOp(
        probetype=str(op["probetype"]),
        subformat=int(op["subformat"]),
        probeid=str(op["probeid"]),
        dofreject=int(op["dofreject"]),
        stretchcorrect=int(op["stretchcorrect"]),
        yres=float(op["yres"]),
        res=float(op["res"]),
    )


def _tail_op(op: dict, *, jit: bool = False) -> TailOp:
    """``op`` dict -> :class:`processbuffer_tail.TailOp`.

    ``jit`` is the ONE field that does not come from the ``op`` dict, and
    deliberately: it is a resource knob, not an IDL ``op`` tag, so it arrives as
    :func:`soda2_process_2d`'s keyword argument and never enters the struct the
    ``.pbp.call`` sidecar records -- the same treatment ``jobs`` and ``chunks``
    get, and for the same reason (it moves no written byte).
    """
    dr = op["dioderange"]
    return TailOp(
        stuckbits=int(op["stuckbits"]),
        rakefix=int(op["rakefix"]),
        greythresh=int(op["greythresh"]),
        dioderange=(int(dr[0]), int(dr[1])),
        numdiodes=int(op["numdiodes"]),
        keeplargest=int(op["keeplargest"]),
        res=float(op["res"]),
        yres=float(op["yres"]),
        jit=bool(jit),
    )


def _as_float(value: Any) -> np.ndarray:
    """An ``op`` bin ladder or threshold as the IDL FLOAT it stands for, held
    in double so every comparison against it runs in double as IDL's does.

    The driver reads the op's floats as FLOAT everywhere else -- the
    concentration block's ``endbins`` (`:628-629`), ``res``/``yres`` in the
    buffer processing -- and SODA-2's own ladders are FLOAT literals
    (``soda2.pro:383``, ``example_batch.pro:28``). Held as the decimal double
    instead, an edge such as ``0.2`` sits below FLOAT ``0.2`` and moves a
    particle whose aspect ratio is exactly FLOAT ``0.2`` (a one-pixel line five
    pixels long) up one bin at `:163`."""
    return np.asarray(value, dtype=np.float32).astype(np.float64)


def _corr_fac_at_least_one(corr_fac: np.ndarray) -> np.ndarray:
    """`:663-665` ``(d.corr_fac[i] > 1.0)``, one record at a time: IDL's MAX
    operator on a scalar keeps the left operand only when ``gt`` is true, so a
    NaN factor becomes 1.0 (GDL: ``!values.f_nan > 0.01`` is 0.0100000),
    where ``np.maximum`` would carry the NaN into every spectrum of that
    record. A NaN factor comes from a Poisson fit that returns ``a[1] = 0``
    (``fit_poisson`` with no usable interarrival, `soda2_particlesort.pro:97-98`)."""
    return np.where(corr_fac > np.float32(1.0), corr_fac, np.float32(1.0)).astype(np.float32)


def _psopts(op: dict, starttime: float, rate: float) -> ParticlesortOptions:
    """``op`` dict -> :class:`particlesort.ParticlesortOptions`."""
    return ParticlesortOptions(
        starttime=starttime,
        rate=rate,
        clusterthresh=float(_as_float(op["clusterthresh"])),
        inttime_reject=int(op["inttime_reject"]),
        smethod=str(op["smethod"]),
        apply_psc=int(op["apply_psc"]),
        apply_psc_sizelimit=float(_as_float(op["apply_psc_sizelimit"])),
        water=int(op["water"]),
        endbins=_as_float(op["endbins"]),
        arendbins=_as_float(op["arendbins"]),
        eawmethod=str(op["eawmethod"]),
        res=float(op["res"]),
        dofreject=int(op["dofreject"]),
        format=str(op["format"]),
        probetype=str(op["probetype"]),
    )


def _idl_round(x: np.ndarray) -> np.ndarray:
    """IDL ``ROUND()``: round-half-away-from-zero (``np.round`` is
    round-half-to-even and disagrees on exact ``.5`` values)."""
    # IDL round() never lets |x| + 0.5 carry: GDL gives round(0.49999999999999994d)
    # = 0 and round(1.4999999999999998d) = 1, where floor(|x| + 0.5) gives 1 and 2.
    # x - trunc(x) is exact in double. Applied pass 6 (pass 5 item 4).
    t = np.trunc(x)
    return t + np.where(np.abs(x - t) >= 0.5, np.sign(x), 0.0)


def _pth_from_sav(pth: str, starttime: float, stoptime: float, rate: float,
                   numrecords: int) -> np.ndarray:
    """``:128-145`` -- ``op.pth`` suffix ``dat``/``sav``: ``restore, op.pth``
    binds the file's top-level ``data`` structure (``data.time``,
    ``data.tas``). ``d.time`` (the comparison target at ``:133``) is the
    accumulator's own time grid, ``op.starttime + op.rate*dindgen(numrecords)``
    (``:62``, DOUBLE) -- not anything read from the file."""
    from scipy.io import readsav

    restored = readsav(pth)
    pth_data = restored["data"]
    # scipy.io.readsav already returns native-byte-order arrays; the
    # explicit swap matches the reference-extraction convention and is a no-op if readsav's own
    # conversion already ran.
    data_time = np.asarray(pth_data["time"][0])
    data_time = data_time.astype(data_time.dtype.newbyteorder("=")).astype(np.float64)
    data_tas = np.asarray(pth_data["tas"][0])
    data_tas = data_tas.astype(data_tas.dtype.newbyteorder("="))

    time_grid = starttime + rate * np.arange(numrecords, dtype=np.float64)  # `d.time`, `:62`
    # `:133` `total(d.time - data.time) ne 0`: IDL subtracts over the SHORTER
    # operand and `total` sums left to right, so a file whose first records
    # match the grid takes the whole-file branch below whatever its length.
    n_common = min(time_grid.size, data_time.size)
    diff_total = 0.0
    for k in range(n_common):
        diff_total += float(time_grid[k] - data_time[k])
    if diff_total != 0.0:
        # `:134-139` -- nearest-point fill.
        good = np.nonzero(
            (data_tas > 0) & (data_tas < 400)
            & (data_time >= starttime) & (data_time <= stoptime)
        )[0]
        if good.size == 0:
            raise Soda2ProcessError(
                "soda2_process_2d.pro:136: stop -- Time mismatch for TAS "
                "file.")
        itas = np.trunc(
            (_idl_round(data_time[good]) - starttime) / rate
        ).astype(np.int64)  # IDL truncates a floating subscript
        # `:127` allocates `pth_tas` as a FLOAT array: FLOAT whatever `data.tas` is.
        pth_tas = np.zeros(numrecords, dtype=np.float32)
        for i in range(good.size):
            start_idx = int(itas[i])
            # `:139` `pth_tas[itas[i]:*]`: a start past the end halts, and a
            # negative one counts from the end (GDL: `p[-4.5d:*]` on ten
            # elements sets the last four), which a record rounded to before
            # a fractional `starttime` reaches when `rate` < 0.5.
            if not -numrecords <= start_idx < numrecords:
                raise Soda2ProcessError(
                    "soda2_process_2d.pro:139: subscript out of range "
                    f"[{start_idx}:*] for pth_tas of {numrecords} records")
            pth_tas[start_idx:] = data_tas[good[i]]
        return pth_tas
    # `:141` -- whole-variable reassignment: `pth_tas` takes on `data.tas`'s
    # own dtype (FLOAT32 on the measured UND `SODA2_TAS.dat`) and its own
    # length. A shorter file halts the buffer loop at `:468` when a buffer's
    # record lies past its end; a longer one leaves `data.tas` whole, invalid
    # airspeeds included.
    return data_tas


def _new_x() -> dict[str, list]:
    return {key: [] for key in _X_KEYS}


def _append_particle(x: dict[str, list], p: Any, buffer_time: float,
                      aircrafttas_i: float, idx: int) -> None:
    """`:510-544` -- one row of ``x`` from ``p`` (a
    :class:`processbuffer_tail.ProcessedBuffer`), index ``idx`` into its
    per-particle arrays."""
    x["buffertime"].append(buffer_time)
    x["probetime"].append(p.probetime[idx])
    x["reftime"].append(p.reftime)
    x["rawtime"].append(p.rawtime[idx])
    x["inttime"].append(p.inttime[idx])
    x["diam"].append(p.diam[idx])
    x["xsize"].append(p.xsize[idx])
    x["ysize"].append(p.ysize[idx])
    x["xextent"].append(p.xextent[idx])
    x["oned"].append(p.oned[idx])
    x["twod"].append(p.twod[idx])
    x["areasize"].append(p.areasize[idx])
    x["arearatio"].append(p.ar[idx])
    x["arearatiofilled"].append(p.arfilled[idx])
    x["aspectratio"].append(p.aspr[idx])
    x["area"].append(p.area_orig[idx])
    x["areafilled"].append(p.area_filled[idx])
    x["perimeterarea"].append(p.perimeterarea[idx])
    x["area75"].append(p.area75[idx])
    x["allin"].append(p.allin[idx])
    x["centerin"].append(p.centerin[idx])
    x["edgetouch"].append(p.edgetouch[idx])
    x["probetas"].append(p.clocktas[idx])
    x["aircrafttas"].append(aircrafttas_i)
    x["zd"].append(p.zd[idx])
    x["sizecorrection"].append(p.sizecorrection[idx])
    x["xpos"].append(p.xpos[idx])
    x["ypos"].append(p.ypos[idx])
    x["numregions"].append(p.numregions[idx])
    x["diodegaps"].append(p.diodegaps[idx])
    # `:540` assigns `p.missed` to the buffer's slice of `x.missed` -- IDL broadcasts a scalar
    # (SPEC's per-buffer count) or assigns element-wise (CIP's per-particle
    # array, `processbuffer_cip.CipBufferParticles.missed`). CIP-1 §2.2.
    x["missed"].append(p.missed[idx] if np.ndim(p.missed) > 0 else p.missed)
    x["particlecounter"].append(p.particlecounter[idx])
    x["overloadflag"].append(p.overloadflag[idx])
    x["dofflag"].append(p.dofflag[idx])
    x["orientation"].append(p.orientation[idx])
    # `:546-553` (`ncdfparticlefile eq 2` only) -- 0 here; the serial loop
    # overwrites both with the offset image indices when images are on.
    x["startline"].append(0)
    x["stopline"].append(0)


def _x_to_arrays(x: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """``x``'s columns as the ``basestruct`` dtypes (`:113-117`).

    Takes a mapping of *sequences*, not specifically lists, so the parallel
    path can hand it already-typed columns: ``np.asarray`` on a same-dtype
    array is a no-op and on a list of Python floats is the element-by-element
    conversion the serial path performs -- the same values either way."""
    return {key: np.asarray(x[key], dtype=_X_DTYPES[key]) for key in _X_KEYS}


def _flush(psopts: ParticlesortOptions, x: Mapping[str, Any],
           d: Accumulator, istop: int, *,
           csv_f: Any = None, ncdf_ds: Any = None,
           ncdf_offset: int = 0, image: np.ndarray | None = None,
           slices_written: int = 0,
           inewbuffer: np.ndarray | None = None) -> int:
    """`:565-576`/`:578-581` -- slice ``x[0:istop]``, convert to the
    ``basestruct`` dtypes, and call :func:`particlesort.soda2_particlesort`.

    Round 9: the IDL passes ``lun_pbp, ncdf_offset, ncdf_id, pbpprops``
    straight into ``soda2_particlesort`` (`:567``, `:579``) and it writes the
    buffer inline; this port keeps ``soda2_particlesort``'s
    signature unchanged and writes here instead, using
    :func:`particlesort.spec_sort_locals` for the same
    ``truetime``/``interarrival`` locals ``soda2_particlesort`` computed
    internally (`:22``, `:28``) and the ``rejectionflag`` it returns.
    Returns the number of particles flushed (``istop + 1``, or 0 when
    ``istop < 0``) so the caller can advance ``ncdf_offset`` the way `:569`
    does.
    """
    if istop < 0:
        return 0
    sliced = {key: x[key][: istop + 1] for key in _X_KEYS}
    arrays = _x_to_arrays(sliced)
    rejectionflag = soda2_particlesort(psopts, arrays, d, inewbuffer=inewbuffer)
    if csv_f is not None or ncdf_ds is not None:
        truetime, interarrival = spec_sort_locals(arrays, format=psopts.format)
        if csv_f is not None:
            write_pbp_csv_buffer(csv_f, arrays, istop, truetime, rejectionflag)
        if ncdf_ds is not None:
            write_pbp_ncdf_buffer(ncdf_ds, arrays, istop, truetime,
                                   interarrival, rejectionflag, ncdf_offset)
            if image is not None:
                # `soda2_particlesort.pro:264-276`, after the PBP variables.
                write_pbp_ncdf_images(ncdf_ds, arrays, istop, image,
                                      ncdf_offset, slices_written)
    return istop + 1


def _image_chunk(chunks: Sequence[np.ndarray]) -> np.ndarray:
    """`:567`/`:580` ``image[*, 0:image_offset_local-1]``, slice-first."""
    if not chunks:
        return np.zeros((0, 0), dtype=np.uint8)
    return np.concatenate(chunks, axis=0)


@dataclass
class _LoopContext:
    """Everything the per-buffer work reads that does not change between
    buffers -- the driver's loop invariants, gathered so that
    :func:`_front_half` and :func:`_tail_half` can be called identically from
    the serial loop below, from the parallel plan's carry-in sweep and from
    each parallel worker (:mod:`process_2d_parallel`).

    Every field is picklable: a worker rebuilds its context from this and
    nothing else, so a field added here is a field the parallel path sees.
    Computes nothing."""

    op: dict
    op_format: str
    spec_op: SpecOp | None
    cip_op: CipOp | None
    tail_op: TailOp
    starttime: float
    rate: float
    numrecords: int
    numdiodes: int
    pth_tas: np.ndarray
    bufftime: np.ndarray
    buffpoint: np.ndarray
    bufffile: np.ndarray
    fn_list: list[str]
    y: Any
    house: HouseData | SeaHouse | dict


def _front_half(ctx: _LoopContext, i: int, f: Any,
                misc: SpecMisc | CipMisc) -> tuple[Any, float, int, float]:
    """`:449-470` -- the buffer read and the **state-carrying** half of
    ``soda2_processbuffer``, for buffer ``i`` of an already-open ``f``.

    Returns ``(front, b_time, timeindex, aircrafttas_i)``. ``misc`` is mutated
    in place exactly where the IDL writes ``(*pmisc)``; nothing else is
    touched -- no ``dhist``, no ``x``, no accumulator. That is what makes the
    loop splittable: this half carries the whole cross-buffer chain
    (``lastclock``/``lastbufftime``/``maxsfm`` for SPEC,
    ``lastclock``/``lastparticlecount`` for CIP). It costs **2.7 %** of the
    loop on CIP, measured on the UND 2016-09-06 CIP (60 buffers: read 3.63 ms,
    front 10.70 ms, tail 518.29 ms per buffer;
    measured 2026-09-17), and about
    15 % of the split loop on a 1 GB 2D-S file (derived from the sweep, pool and
    replay times in the 2D-S SODA-2 replay launch log).

    **Used by the parallel path only** -- by the carry-in sweep and by every
    worker, so those two cannot drift apart. The serial loop below does NOT
    call it: it calls the composed ``soda2_processbuffer`` /
    ``soda2_processbuffer_cip`` as module globals, because those are a
    substitution surface (see ``_PRISTINE_CALLS``) that a split into halves
    cannot honour. So this function is a *second written form* of `:449-470`,
    and the thing that keeps it honest is
    ``tests/test_soda2_parallel.py``'s byte comparison of the two paths on
    both routes -- not the type checker and not this docstring. An earlier
    version of this refactor had the serial loop call these halves; it was
    reverted when the suite showed it silently bypassed every SODA-2
    correction and the 2016 UND emulation.
    """
    point_lun(f, int(ctx.buffpoint[i]))
    b = read2dbuffer(f, ctx.op)
    b.time = float(ctx.bufftime[i])  # `:451`
    # `:454` -- IDL long() truncation, then clamp into [0, numrecords-1].
    timeindex = int(np.clip(np.trunc((b.time - ctx.starttime) / ctx.rate),
                            0, ctx.numrecords - 1))

    # `:462` `probetas=interpol(house.tas, house.time, b.time)`: SPEC only
    # (the format test at `:457`) -- `GenericIndex`
    # (the SEA/CIP index) has none of the fields this block reads
    # (`buildindex.py:23-34`), so it is skipped for SEA, not adapted.
    if ctx.op_format == "SPEC":
        y, house = ctx.y, ctx.house
        assert not isinstance(y, GenericIndex)
        assert isinstance(house, HouseData)
        assert isinstance(misc, SpecMisc)
        misc.nimages = int(y.numimages[i])
        if misc.nimages > 0:
            # `:460` `i*y.buffsize + y.imagep[...]` is IDL `LONG * ULONG64 +
            # INT[]` -> ULONG64, stored into the LON64 field at `:40`. NumPy
            # 2's weak-scalar rule would otherwise keep the array's int16
            # dtype and either wrap (i <= 7) or raise OverflowError (i >= 8)
            # on a real buffer count -- W2b.
            firstp_i = int(y.firstp[i])
            misc.imagepointers = cast(Sequence[int], (
                np.int64(i) * np.int64(y.buffsize)
                + y.imagep[firstp_i: firstp_i + misc.nimages].astype(np.int64)
            ))
            misc.hkpointers = cast(Sequence[int], y.hkp[
                y.ihk[firstp_i: firstp_i + misc.nimages]
            ])
            misc.probetas = _interpol(house.tas, house.time, b.time)

    # `:468` -- unconditional, every format.
    aircrafttas_i = float(ctx.pth_tas[timeindex])

    front: Any
    # Through the module, never a bound name: `process_spec_buffer` is a
    # registered hook point (`enhancement_hooks.HOOK_POINTS`), substituted by
    # setting the attribute on `processbuffer_spec`, and a bound name would not
    # see it -- which is how the composed `soda2_processbuffer` reads it too.
    if ctx.op_format == "SPEC":
        assert ctx.spec_op is not None and isinstance(misc, SpecMisc)
        misc.aircrafttas = aircrafttas_i
        front = _pb_spec.process_spec_buffer(f, b.time, ctx.spec_op, misc)
    else:
        assert ctx.cip_op is not None and isinstance(misc, CipMisc)
        assert isinstance(b, (SeaBuffer2D, DmtBuffer2D))
        # `buffer_tas` is `b.tas` (`soda2_processbuffer.pro:195`, which
        # fills `clocktas` from the buffer's own TAS), not `pmisc.aircrafttas`
        # -- measured by grep (CIP-1 §2.2). DMT has no `stoptime` (`:106`).
        front = _pb_cip.process_cip_buffer(b.image, b.time, getattr(b, "stoptime", 0.0),
                                           float(b.tas),
                                           ctx.cip_op, misc)
        # `:474-486`'s `activetime_sea` update (using the `stoptime` the CIP
        # branch leaves in the caller's buffer) is not ported: `:648` reads it
        # only for `probetype ne 'CIP'`, so CIP's own activetime is the
        # deadtime formula applied after the loop (`:677-683`).
    return front, b.time, timeindex, aircrafttas_i


def _tail_half(ctx: _LoopContext, front: Any, lastdhist: np.ndarray) -> Any:
    """`:612-747` -- the shared image-processing tail, **97.3 %** of the loop
    and a pure function of its own buffer once ``lastdhist`` is dead
    (``processbuffer_tail.py:195-196`` reads it only under
    ``op.stuckbits``). A ``NullBuffer`` from the front half is returned
    without calling the tail, matching IDL's early ``nullbuffer`` returns
    (``soda2_processbuffer.pro:267``/``:339``/``:135``/``:140``/``:160``)."""
    if isinstance(front, NullBuffer):
        return front
    return _pb_tail.process_buffer_tail(front, ctx.tail_op, lastdhist)


#: One liveness line per this many buffers when ``report_every`` is passed.
#: Silent by default, so a library caller's output is unchanged.
REPORT_EVERY_BUFFERS = 20_000

#: Its own logger, never given a persistent handler and ``propagate`` left on so
#: ``arrayprobe.cli``'s handler carries it into the run's log. Mirrors
#: ``readers/spec.py``'s ``_report_part_progress``, which solved this for the
#: decode in pair J.
_progress_logger = logging.getLogger(f"{__name__}.progress")


def _report_progress(i: int, first: int, last: int, started: float) -> None:
    """One line saying where a long run has got to.

    WHY THIS EXISTS (2026-09-17). ``soda2 run`` printed **nothing** for its
    entire duration. On ACE-ENA RF18 -- dense cloud, and the per-particle output
    is 287 MB against 07-07's 12.8 MB -- the SPEC pass ran **11.5 hours** in
    complete silence. A healthy long run and a wedged one were indistinguishable
    from outside, and the coordinator killed it as pathological when it was
    neither: it had finished its per-particle stage and was in accumulation.
    Roughly 24 CPU-hours were discarded on a misreading that a single printed
    line per 20,000 buffers would have prevented.

    This changes no computed number: it reads the loop counter and writes to a
    log, nothing more.
    """
    done = i - first + 1
    total = last - first + 1
    elapsed = time.monotonic() - started
    rate = done / elapsed if elapsed > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else float("nan")
    _progress_logger.info(
        "  ...buffer %d of %d (%.1f%%), %.0f buff/s, %.1f min elapsed, ETA %.1f min",
        done, total, 100.0 * done / total, rate, elapsed / 60.0, eta / 60.0)


def _reprocess_from_pbp(fn_pbp: str, op_format: str, psopts: ParticlesortOptions,
                        d: Accumulator, num2process: int) -> None:
    """`:584-617` -- the reprocess branch: particles come from ``fn_pbp`` in
    blocks of ``num2process`` and go straight to ``soda2_particlesort``.

    SPEC: `:593-597` recomputes the particle time with ``spec_newtime`` over
    the whole file and `:606` hands each block its slice as
    ``reprocessed_time``. `:599` loops ``i = 0 .. n/num2process`` inclusive,
    so when ``n`` is a multiple of ``num2process`` the last pass reads at
    offset ``n`` and halts (:class:`reprocess_pbp.PbpRestoreError`)."""
    from .reprocess_pbp import pbp_particle_count, restore_pbp, spec_newtime

    n = pbp_particle_count(fn_pbp)
    newtime: np.ndarray | None = None
    if op_format == "SPEC":
        whole = restore_pbp(fn_pbp)
        newtime = spec_newtime(whole.columns["rawtime"], whole.columns["buffertime"],
                               whole.columns["probetas"], whole.global_attrs["yres"])
    for i in range(n // num2process + 1):
        block = restore_pbp(fn_pbp, offset=i * num2process, count=num2process)
        cols = block.columns
        nblock = cols["time"].size
        reprocessed_time = None
        if op_format == "SPEC":
            assert newtime is not None
            reprocessed_time = newtime[i * num2process: i * num2process + nblock]
        arrays = {k: np.asarray(v, dtype=_X_DTYPES[k]) if k in _X_DTYPES else v
                  for k, v in cols.items()}
        soda2_particlesort(psopts, arrays, d, reprocessed_time=reprocessed_time)


def soda2_process_2d(
    op: dict,
    *,
    fn_pbp: str | None = None,
    num2process: int = NUM2PROCESS,
    report_every: int = 0,
    jobs: int = 1,
    chunks: int = 0,
    jit: bool = False,
    stamp_profile: str | None = None,
) -> ProcessData | None:
    """``soda2_process_2d, op`` -- SPEC path, and the SEA/CIP route (a
    1-element ``op.seatag``, or two or more, which adds the CIP-1D
    housekeeping of ``process_cip1d_sea``), raw bytes to the in-memory ``data``.
    Returns ``None`` exactly where the IDL ``return``s with no output
    (`:430-433`, `:576`).

    Source: ``soda2_process_2d.pro`` (SODA-2); bare line references here are into that file.

    ``jobs`` (default 1, serial -- the IDL has no parallelism and this changes
    no computed number) splits the buffer loop (`:449-573`) across that many
    processes; ``chunks`` (default 0 = ``4 * jobs``) is how many contiguous
    buffer ranges it is split into, more than ``jobs`` for balance because a
    buffer's cost is its particle count. Every number the run produces comes
    from the same per-buffer calls in the same buffer order and from this
    function's own bookkeeping and ``_flush``; byte-identity is asserted on a
    real fixture by ``tests/test_soda2_parallel.py``, not claimed here.
    ``jobs > 1`` is refused, by name, where the split would not be exact --
    see :func:`process_2d_parallel.run_parallel_loop`.

    ``jit`` (default False) routes ``label_blobs``'s ``_label_region`` -- and
    ``fillholes``' own call to it -- through :mod:`arrayprobe_soda2.jit_kernels`'
    numba flood fill. Speed only: the kernel is exact by construction and
    ``tests/test_soda2_label_region_jit_identity.py`` asserts it with
    ``np.array_equal``, so it is not recorded in the ``op`` struct, exactly as
    ``jobs``/``chunks`` are not. It reaches the per-buffer work as
    :attr:`processbuffer_tail.TailOp.jit`, which rides in ``_LoopContext`` and so
    reaches a ``jobs > 1`` worker as well as the serial loop
    (``tests/test_soda2_jit_flag.py``).

    ``stamp_profile`` (default None) is the configuration name a driver ran this under; it is
    written into ``.pbp.nc`` as the ``arrayprobe_profile`` global attribute
    (:func:`pbp_writer.engine_attrs`), ``"unstated"`` when None. Metadata only: it is not
    recorded in ``op`` and moves no computed number."""
    if jobs < 1:
        raise ValueError(f"jobs must be >= 1 (got {jobs})")
    op = update_op(op)

    # `:30-35` -- reprocess from an existing `.pbp.nc`; no particle files are
    # written on this path ("since they may overwrite while in process").
    reprocess = fn_pbp is not None
    if reprocess:
        if not os.path.isfile(str(fn_pbp)):
            raise Soda2ProcessError("soda2_process_2d.pro:32: stop -- PBP file not found.")
        op = {**op, "ncdfparticlefile": 0, "particlefile": 0}

    op_format = str(op.get("format"))
    op_probetype = str(op.get("probetype"))
    if op_format == "SPEC":
        pass
    elif op_format == "SEA":
        # `soda2_read2dbuffer.pro:77-82` / `soda2_processbuffer.pro:205-262`:
        # only the CIP route (`:69-76` / `:129-203`) is ported; CIPG, 2DC,
        # 1D2D, HVPS and HAIL each need their own read/process branch.
        if op_probetype != "CIP":
            raise NotImplementedError(
                "soda2_read2dbuffer.pro:77-82 / soda2_processbuffer.pro:205-262: "
                f"SEA probetype {op_probetype!r} not ported (only CIP is)")
        # `soda2_process_2d.pro:397-398`: `process_cip1d_sea` fires whenever
        # `n_elements(op.seatag) ge 2` and replaces `house`; ported below
        # (`process_hk.process_cip1d_sea`, GDL-matched on all 17 fields).
    elif op_format == "DMT":
        # `soda2_read2dbuffer.pro:91-107` (one branch for every probetype) and
        # `soda2_processbuffer.pro:129-203` (CIP; PIP is 'CIP' since
        # `soda2_update_op.pro:49`). CIPG (`:205-262`) is not ported.
        if op_probetype != "CIP":
            raise NotImplementedError(
                "soda2_processbuffer.pro:205-262: DMT probetype "
                f"{op_probetype!r} not ported (only CIP, incl. PIP, is)")
    elif op_format == "RAF":
        # `soda2_read2dbuffer.pro:19-66` / `soda2_processbuffer.pro:28-78`:
        # Fast-2DC (F2DC, F2DC_v2, `:28-78`) and 2DC (`:80-127`) are ported;
        # HVPS1, F2DC66 and every other RAF probetype are refused by name.
        if op_probetype not in ("F2DC", "F2DC_v2", "2DC"):
            raise NotImplementedError(
                "soda2_processbuffer.pro:22-127: RAF probetype "
                f"{op_probetype!r} not ported (only F2DC, F2DC_v2 and 2DC are)")
        if jobs > 1:
            # `soda2_process_2d.pro:39`: `f2d_remainder` (Fast-2DC) and
            # `lastclock` (2DC, `soda2_processbuffer.pro:119-121`) carry
            # across every buffer, and 2DC's `inewbuffer` (`:441`, `:506`)
            # spans the whole loop; a chunk boundary would cut them.
            raise NotImplementedError(
                "soda2_process_2d.pro:39: RAF "
                f"{'2DC' if op_probetype == '2DC' else 'Fast-2DC'} with jobs > 1 -- the "
                "per-buffer carry crosses chunk boundaries; run jobs=1")
    else:
        raise NotImplementedError(
            "soda2_process_2d.pro: only op.format in ('SPEC', 'SEA', 'DMT', 'RAF') is "
            f"ported (got {op.get('format')!r})")

    fn = op["fn"]
    fn_list = list(fn) if isinstance(fn, (list, tuple)) else [fn]

    if jobs > 1:
        # Beside the driver's other configuration refusals above, and before
        # anything is opened: a `jobs > 1` this module cannot split exactly
        # must cost no file. (S6-f's early returns leave open PBP writers
        # behind them; a refusal has no business joining them.)
        from .process_2d_parallel import refuse_unsplittable
        refuse_unsplittable(op, fn_list, jobs)

    pth = str(op.get("pth", ""))
    pth_suffix = _pth_suffix(pth)  # `:129`
    pth_file_exists = pth != "" and os.path.exists(pth)
    if pth != "" and not pth_file_exists:
        raise Soda2ProcessError(
            "soda2_process_2d.pro:185-186: stop -- PTH file not found")
    # A `pth` that exists with any other suffix (including `dat`/`sav`,
    # handled below) falls through here unchanged -- IDL's `:128-172` has
    # no branch for an unrecognised suffix and silently leaves `got_pth=0`,
    # a preserved quirk (e.g. a case-mismatched `.DAT`), not raised.

    # `:336` -- IDL tests `eq 1`, not `ge 1`; any other nonzero value writes
    # no CSV (silently, in the vendored source -- read-only, not measured).
    particlefile = int(op.get("particlefile", 0))
    # `:241` -- IDL tests `ge 1`; `== 2` (particle images) is refused inside
    # :func:`pbp_writer.open_pbp_ncdf` (``PbpImagesNotPorted``), not here.
    ncdfparticlefile = int(op.get("ncdfparticlefile", 0))
    # `:105-109` / `:546-553` (particle-image output): the image accumulator, held
    # as a list of per-buffer slice-first chunks (IDL preallocates
    # `bytarr(numdiodes, maxslices)` whatever the switch; the port allocates
    # only what is appended). `slices_written` is IDL's `image_offset` at the
    # last flush; `image_offset` the running total.
    images = ncdfparticlefile == 2
    image_chunks: list[np.ndarray] = []
    image_offset = 0
    image_offset_local = 0
    slices_written = 0
    if images and jobs > 1:
        raise PbpImagesNotPorted(
            "soda2_process_2d.pro:546-553 -- particle images on the parallel driver")

    starttime = float(op["starttime"])
    stoptime = float(op["stoptime"])
    # `:644,:646` (S6-e): `fltarr(numrecords) + op.rate` takes IDL's type
    # promotion -- FLOAT for an INT, LONG or FLOAT `rate`, DOUBLE only for a
    # DOUBLE one. Measured under GDL (`run_soda2_save_writer_bank.py`
    # `rate_types`, and the `help` check): `{rate:1}`, `{rate:1L}` and
    # `{rate:1.0}` give FLOAT, `{rate:1.0d}` DOUBLE; `frame_full`/
    # `frame_stretch` (`rate:1.0d`) measure DOUBLE. The caller's IDL type is
    # only visible before `float()` below: an integer (Python `int`, any
    # `np.integer`) or `np.float32` means FLOAT; `np.float64` or a plain
    # Python float means DOUBLE -- the port's standing convention that a
    # Python float is a C double (IDL's bare `1.0` is FLOAT: pass
    # `np.float32` for it). Before that measurement an integer `rate` gave DOUBLE here,
    # which is every TOML `rate = 1` and SODA-2's own example scripts.
    rate_in = op["rate"]
    activetime_dtype = (np.float32
                        if isinstance(rate_in, (int, np.integer, np.float32))
                        else np.float64)
    rate = float(rate_in)
    numrecords = int((stoptime - starttime) / rate + 1)  # `:49`, IDL long() truncation

    d = new_accumulator(_psopts(op, starttime, rate), numrecords)
    numbuffsaccepted = np.zeros(numrecords, dtype=np.int16)
    numbuffsrejected = np.zeros(numrecords, dtype=np.int16)
    dhist = np.zeros((numrecords, int(op["numdiodes"])), dtype=np.int32)
    lastdhist = np.zeros(int(op["numdiodes"]), dtype=np.int32)

    date = soda2_parsedate(str(op["date"]))  # `:100-109`

    # `:126-189` -- `numrecords` is needed to size/resolve `pth_tas`, so
    # this port resolves it here rather than at `:49`'s IDL position; the
    # refusal/existence checks above already ran before any raw `fn` file
    # read, matching the source's own ordering guarantee.
    if pth_file_exists and pth_suffix in ("dat", "sav"):
        # `:131-145`.
        pth_tas = _pth_from_sav(pth, starttime, stoptime, rate, numrecords)
        got_pth = 1
    elif pth_file_exists and pth_suffix in ("txt", "csv", "nc"):
        # `:147-172` -- pth_readers (wired at integration).
        # `pthdat` stays unset for these formats: `:144` sets it only in the
        # SAVE branch.
        pth_tas, got_pth = read_pth(pth, pth_suffix, starttime, stoptime,
                                    rate, numrecords)
    elif pth_file_exists:
        # `:128-172` has no branch for this suffix -- IDL silently leaves
        # `got_pth=0`.
        got_pth = 0
        pth_tas = np.zeros(numrecords, dtype=np.float32)
    else:
        # `:173-177` -- `file_test(op.pth)` false; `pth==''` (`pth!=''`
        # and missing already raised above).
        fixedtas = float(op.get("fixedtas", 0.0))
        if fixedtas > 0:
            got_pth = 1
            pth_tas = np.zeros(numrecords, dtype=np.float32) + np.float32(fixedtas)
        else:
            got_pth = 0
            pth_tas = np.zeros(numrecords, dtype=np.float32)

    # `:190-354` -- PBP writer setup, round 9. Opened here (relative IDL
    # order: after the PTH/TAS block, before buildindex) so that S6-f's
    # early returns below (`:430-433`, `:576`) can leave them open,
    # unclosed, exactly as the vendored source does -- never move this
    # block after the `firstbuff`/`lastbuff` check.
    date_map = {"month": date.month, "day": date.day, "year": date.year}
    csv_f: Any = None
    ncdf_ds: Any = None
    ncdf_offset = 0
    fn_pbp_out: str | None = None
    fn_ncdf_out: str | None = None
    if particlefile == 1:
        fn_pbp_out = pbp_filename(op, str(op["shortname"]), extension=".pbp.csv")
        csv_f = open_pbp_csv(fn_pbp_out, op, date_map)
    if ncdfparticlefile >= 1:
        fn_ncdf_out = pbp_filename(op, str(op["shortname"]), extension=".pbp.nc")
        ncdf_ds = open_pbp_ncdf(fn_ncdf_out, op, date_map, pthdat=None,
                                stamp_profile=stamp_profile)

    # `:364-391` -- one index per raw file, concatenated in `op.fn` order with
    # a per-buffer file index; SPEC stops on the second file (`:376`), after
    # the first file's index was built. A file whose `error` is neither 0
    # nor 1 is skipped, as GDL's loop does.
    firstfile = True
    for ifile, path in enumerate(fn_list):
        y = buildindex(path, op)
        if y.error == 0:
            if firstfile:
                bufftime = np.asarray(y.bufftime, dtype=np.float64)
                buffdate = np.asarray(y.date, dtype=np.int64)
                buffpoint = np.asarray(y.pointer)
                bufffile = np.full(y.count, ifile, dtype=np.uint8)
            else:
                if op_format == "SPEC":
                    raise Soda2ProcessError(
                        "soda2_process_2d.pro:376: stop -- Multiple files not "
                        "supported with SPEC format, need to concatenate raw "
                        "files first")
                bufftime = np.concatenate(
                    [bufftime, np.asarray(y.bufftime, dtype=np.float64)])
                buffdate = np.concatenate(
                    [buffdate, np.asarray(y.date, dtype=np.int64)])
                buffpoint = np.concatenate([buffpoint, np.asarray(y.pointer)])
                bufffile = np.concatenate(
                    [bufffile, np.full(y.count, ifile, dtype=np.uint8)])
            firstfile = False
        if y.error == 1:
            raise Soda2ProcessError(
                "soda2_process_2d.pro:385-389: stop -- error building index, "
                "verify probe ID and/or SEA tags are correct")

    # `:394-398` -- housekeeping. SPEC: `spec_process_hk`. SEA/CIP with
    # `n_elements(op.seatag) ge 2` (including `update_op.py`'s default
    # 3-element `[33000,0,0]`): `process_cip1d_sea` replaces `house`
    # (`:397-398`). Any other SEA/DMT case: IDL's own `house={op:op}`
    # placeholder.
    house: HouseData | SeaHouse | dict
    if op_format == "SPEC":
        assert not isinstance(y, GenericIndex)  # SPEC always indexes to SpecIndex.
        house = process_hk(op, y=y)
    elif (op_format == "SEA" and op_probetype == "CIP"
          and np.atleast_1d(np.asarray(op.get("seatag"))).size >= 2):
        # `:397-398` call `process_cip1d_sea` without writing, returning `house` --
        # `house` becomes that routine's `data` struct outright.
        from .process_hk import process_cip1d_sea
        house = process_cip1d_sea(op)
    else:
        house = SeaHouse(op=op)

    # `:408-418` -- date check (S6-b).
    startdate = int(date.julday)
    if abs(int(buffdate[0]) - startdate) > 5:
        startdate = int(buffdate[0])
    bufftime = bufftime + 86400.0 * (buffdate - startdate)

    # `:419-423` -- sort; buffindex "for output only".
    order = np.argsort(bufftime, kind="stable")
    bufftime = bufftime[order]
    buffpoint = buffpoint[order]
    bufffile = bufffile[order]
    buffindex = np.trunc((bufftime - starttime) / rate).astype(np.int64)

    numbuffs = bufftime.size
    pbpstartindex = np.zeros(numbuffs, dtype=np.int32)

    # `:427-429` -- trap 1 / S6-a.
    lt_start = np.nonzero(bufftime < starttime)[0]
    firstbuff = max(int(lt_start.max()), 0) if lt_start.size else 0
    gt_stop = np.nonzero(bufftime > stoptime)[0]
    lastbuff = int(gt_stop.min()) if gt_stop.size else numbuffs - 1

    if (lastbuff - firstbuff) <= 0:
        return None

    currentfile = -1
    istop = -1
    f = None
    # Lists on the serial path, typed columns on the parallel one; `_flush` and
    # `_x_to_arrays` accept either and convert each element the same way.
    x: dict[str, Any] = _new_x()
    psopts = _psopts(op, starttime, rate)

    misc = SpecMisc(
        nimages=0, hkpointers=cast(Sequence[int], np.array([0])),
        imagepointers=cast(Sequence[int], np.array([0])),
        probetas=0.0, aircrafttas=0.0, lastclock=0.0, lastbufftime=0.0,
        maxsfm=0.0,
    )
    spec_op = _spec_op(op) if op_format == "SPEC" else None
    tail_op = _tail_op(op, jit=jit)
    cip_op = CipOp(probetype=op_probetype, format=op_format,
                   strictcounter=int(op["strictcounter"])) if op_format != "SPEC" else None
    cip_misc = CipMisc() if op_format != "SPEC" else None
    from .processbuffer_f2dc import F2dcMisc, F2dcOp
    f2d_op = F2dcOp(probetype=op_probetype)
    f2d_misc = F2dcMisc()  # `soda2_process_2d.pro:39`, one per run
    from .processbuffer_2dc import TwoDcMisc, TwoDcOp
    twodc_op = TwoDcOp(probetype=op_probetype, format=op_format,
                       yres=float(op.get("yres", op.get("res", 0.0))))
    twodc_misc = TwoDcMisc()  # `(*pmisc).lastclock`, `soda2_process_2d.pro:39`
    # `:441` allocates `inewbuffer` as a LONG array: one entry per buffer,
    # set at `:506` for each accepted buffer, never reset at a flush, and
    # passed whole to every `soda2_particlesort` call (`:567`, `:579`). Only
    # the 2DC block (`soda2_particlesort.pro:65-76`) reads it.
    inewbuffer = np.zeros(max(lastbuff - firstbuff + 1, 0), dtype=np.int32)

    ctx = _LoopContext(
        op=op, op_format=op_format, spec_op=spec_op, cip_op=cip_op, tail_op=tail_op,
        starttime=starttime, rate=rate, numrecords=numrecords,
        numdiodes=int(op["numdiodes"]), pth_tas=pth_tas, bufftime=bufftime,
        buffpoint=buffpoint, bufffile=bufffile, fn_list=[str(p) for p in fn_list],
        y=y, house=house,
    )
    loop_misc: SpecMisc | CipMisc = misc if op_format == "SPEC" else cast(CipMisc, cip_misc)

    if jobs > 1:
        # `:449-573`, split across processes. Opt-in; refuses rather than
        # guesses (see `refuse_unsplittable`). The per-buffer work is
        # `_front_half`/`_tail_half`, a second written form of this loop's own
        # `:449-470` (see `_front_half`); the bookkeeping below is not written
        # twice -- it is replayed in buffer order from what the workers report,
        # and the particles go to this function's own `_flush`.
        from .process_2d_parallel import run_parallel_loop
        istop, ncdf_offset, x = run_parallel_loop(
            ctx, firstbuff, lastbuff, loop_misc, jobs=jobs, chunks=chunks,
            report_every=report_every, d=d, dhist=dhist,
            numbuffsaccepted=numbuffsaccepted, numbuffsrejected=numbuffsrejected,
            pbpstartindex=pbpstartindex, num2process=num2process, psopts=psopts,
            flush=_flush, csv_f=csv_f, ncdf_ds=ncdf_ds)
        if int(op.get("activetimefrommissed", 0)) == 1:
            raise Soda2ProcessError(
                "soda2_process_2d.pro:493: stop -- activetimefrommissed "
                "'Under development'")

    #: The serial loop's iteration set -- empty when `run_parallel_loop` above
    #: already did the work, so the body below stays the one and only written
    #: form of the driver's bookkeeping.
    buffer_range = range(firstbuff, lastbuff + 1) if (jobs == 1 and not reprocess) else range(0)
    if reprocess:
        assert fn_pbp is not None
        _reprocess_from_pbp(str(fn_pbp), op_format, psopts, d, num2process)

    _started = time.monotonic()
    try:
        for i in buffer_range:
            if report_every > 0 and (i - firstbuff) and (i - firstbuff) % report_every == 0:
                _report_progress(i, firstbuff, lastbuff, _started)
            if currentfile != int(bufffile[i]):
                if f is not None:
                    f.close()
                f = open(fn_list[int(bufffile[i])], "rb")
                currentfile = int(bufffile[i])
            assert f is not None

            point_lun(f, int(buffpoint[i]))
            b = read2dbuffer(f, op)
            b.time = float(bufftime[i])  # `:451`
            # `:454` -- IDL long() truncation, then clamp into [0, numrecords-1].
            timeindex = int(np.clip(np.trunc((b.time - starttime) / rate), 0, numrecords - 1))

            # `:462` `probetas=interpol(house.tas, house.time, b.time)`: SPEC
            # only (the format test at `:457`) --
            # `GenericIndex` (the SEA/CIP index) has none of the fields this
            # block reads (`buildindex.py:23-34`), so it is skipped for SEA,
            # not adapted.
            if op_format == "SPEC":
                assert not isinstance(y, GenericIndex)
                assert isinstance(house, HouseData)
                misc.nimages = int(y.numimages[i])
                if misc.nimages > 0:
                    # `:460` `i*y.buffsize + y.imagep[...]` is IDL `LONG * ULONG64 +
                    # INT[]` -> ULONG64, stored into the LON64 field at `:40`. NumPy
                    # 2's weak-scalar rule would otherwise keep the array's int16
                    # dtype and either wrap (i <= 7) or raise OverflowError (i >= 8)
                    # on a real buffer count -- W2b.
                    firstp_i = int(y.firstp[i])
                    misc.imagepointers = cast(Sequence[int], (
                        np.int64(i) * np.int64(y.buffsize)
                        + y.imagep[firstp_i: firstp_i + misc.nimages].astype(np.int64)
                    ))
                    misc.hkpointers = cast(Sequence[int], y.hkp[
                        y.ihk[firstp_i: firstp_i + misc.nimages]
                    ])
                    misc.probetas = _interpol(house.tas, house.time, b.time)

            # `:468` -- unconditional, every format.
            aircrafttas_i = float(pth_tas[timeindex])
            b_time = b.time

            # The COMPOSED per-buffer call, read as a module global, unchanged
            # from before the front/tail split: the 2016 UND reference script
            # rebinds `process_2d.soda2_processbuffer` for the 2016 UND
            # emulation, and a bound name would silently drop that. The split
            # loop, which calls the two halves separately, refuses instead
            # (`process_2d_parallel.refuse_unsplittable`).
            if op_format == "SPEC":
                assert spec_op is not None
                misc.aircrafttas = aircrafttas_i
                p = soda2_processbuffer(f, b.time, spec_op, tail_op, misc, lastdhist)
            elif op_format == "RAF" and op_probetype == "2DC":
                # `soda2_process_2d.pro:470` calls `soda2_processbuffer` per buffer,
                # whose `CASE` takes the 2DC arm at `soda2_processbuffer.pro:80`
                # (`:80-127`, then the shared tail); `twodc_misc.lastclock`
                # persists across buffers as `(*pmisc)` does.
                from .processbuffer_2dc import soda2_processbuffer_2dc
                assert isinstance(b.image, np.ndarray)  # a RAF buffer always carries one
                p = soda2_processbuffer_2dc(
                    b.image, b.time, float(b.tas), twodc_op, tail_op, twodc_misc,
                    lastdhist)
            elif op_format == "RAF":
                # `soda2_processbuffer.pro:28-78`; `f2d_misc` persists across
                # buffers as `(*pmisc)` does (`soda2_process_2d.pro:39`).
                from .processbuffer_f2dc import soda2_processbuffer_f2dc
                # A RAF buffer that reached here was read whole (a short read
                # returns the null buffer earlier), so its image is an array.
                assert isinstance(b.image, np.ndarray)
                p = soda2_processbuffer_f2dc(
                    b.image, b.time, float(b.tas), f2d_op, tail_op, f2d_misc, lastdhist)
            else:
                assert cip_op is not None and cip_misc is not None
                assert isinstance(b, (SeaBuffer2D, DmtBuffer2D))
                # `buffer_tas` is `b.tas` (`soda2_processbuffer.pro:195`, which
                # fills `clocktas` from the buffer's own TAS), not
                # `pmisc.aircrafttas` -- measured by grep (CIP-1 §2.2).
                # A DMT buffer has no `stoptime` tag (`:106`); `:199-202`
                # never reads it for that format, so 0.0 is a placeholder.
                p, _stoptime = soda2_processbuffer_cip(
                    b.image, b.time, getattr(b, "stoptime", 0.0), float(b.tas),
                    cip_op, tail_op, cip_misc, lastdhist)
                # `:474-486`'s `activetime_sea` update (using the discarded
                # `_stoptime`) is not ported: `:648` reads it only for
                # `probetype ne 'CIP'`, so CIP's own activetime is the
                # deadtime formula already applied below (`:677-683`).

            if int(op.get("activetimefrommissed", 0)) == 1:
                raise Soda2ProcessError(
                    "soda2_process_2d.pro:493: stop -- activetimefrommissed "
                    "'Under development'")

            if not isinstance(p, NullBuffer):
                dhist[timeindex, :] = dhist[timeindex, :] + p.dhist
            lastdhist = dhist[max(timeindex - 1, 0), :]

            if isinstance(p, NullBuffer) or p.rejectbuffer != 0:
                numbuffsrejected[timeindex] += 1
            else:
                numbuffsaccepted[timeindex] += 1
                n = p.diam.size
                istart = istop + 1
                istop = istart + n - 1
                inewbuffer[i - firstbuff] = istart  # `:506`
                pbpstartindex[i] = istart + ncdf_offset  # `:507` -- fix, round 9.
                for k in range(n):
                    _append_particle(x, p, b_time, aircrafttas_i, k)
                if images:
                    # `:546-553`. `nslices` is the bitimage's own slice count
                    # (dummy first slice included), not `p.nslices`.
                    bitimage = np.asarray(p.bitimage, dtype=np.uint8)
                    nslices = bitimage.shape[0]
                    image_chunks.append(bitimage)
                    x["startline"][istart:istop + 1] = [
                        int(v) + image_offset for v in np.asarray(p.startline)[:n]]
                    x["stopline"][istart:istop + 1] = [
                        int(v) + image_offset for v in np.asarray(p.stopline)[:n]]
                    image_offset += nslices
                    image_offset_local += nslices

            if istop + 500 > num2process or image_offset_local + 10000 > MAXSLICES:
                ncdf_offset += _flush(psopts, x, d, istop, csv_f=csv_f,
                                       ncdf_ds=ncdf_ds, ncdf_offset=ncdf_offset,
                                       image=_image_chunk(image_chunks) if images else None,
                                       slices_written=slices_written,
                                       inewbuffer=inewbuffer)
                istop = -1
                x = _new_x()
                slices_written += image_offset_local
                image_offset_local = 0
                image_chunks = []
    finally:
        if f is not None:
            f.close()

    if reprocess:
        pass
    elif istop < 0:
        # S6-f: the IDL `return` at `:576` fires before `:689-721`'s close
        # block -- `csv_f`/`ncdf_ds`, if open, are left unclosed here too,
        # reproducing the vendored bug rather than fixing it.
        return None
    else:
        _flush(psopts, x, d, istop, csv_f=csv_f, ncdf_ds=ncdf_ds, ncdf_offset=ncdf_offset,
               image=_image_chunk(image_chunks) if images else None,
               slices_written=slices_written, inewbuffer=inewbuffer)

    # `:625-675` -- concentration.
    spec1d = d.spec2d.sum(axis=2, dtype=np.float32)
    numbins = len(op["endbins"]) - 1
    endbins = np.asarray(op["endbins"], dtype=np.float32)
    midbins = (endbins[0:numbins] + endbins[1: numbins + 1]) / np.float32(2.0)
    binwidth = endbins[1: numbins + 1] - endbins[0:numbins]

    dioderange = op["dioderange"]
    numdiodes = int(op["numdiodes"])
    if int(dioderange[0]) != 0 or int(dioderange[1]) != 0:
        numactivediodes = int(dioderange[1]) - int(dioderange[0]) + 1
    else:
        numactivediodes = numdiodes

    sa = sample_area(
        midbins, float(op["res"]), float(op["armwidth"]), numactivediodes,
        str(op["eawmethod"]), np.float32(op["wavelength"]), float(op["dofconst"]),
        dof=np.asarray(op["customdof"], dtype=np.float32),
    )[0]

    if int(op.get("ignoredeadtime", 0)) == 1:
        activetime = np.full(numrecords, rate, dtype=activetime_dtype)
    else:
        activetime = np.clip(
            np.full(numrecords, rate, dtype=activetime_dtype) - d.deadtime,
            0.0, rate,
        ).astype(activetime_dtype)

    probetas = d.tas
    aircrafttas = pth_tas if got_pth == 1 else probetas

    orientation_index = np.zeros((numrecords, numbins), dtype=np.float32)
    conc1d = np.zeros((numrecords, numbins), dtype=np.float32)

    corr_fac_clamped = _corr_fac_at_least_one(d.corr_fac)
    spec1d = spec1d * corr_fac_clamped[:, None]
    d.spec2d[:, :, :] = d.spec2d * corr_fac_clamped[:, None, None]
    d.spec2d_aspr[:, :, :] = d.spec2d_aspr * corr_fac_clamped[:, None, None]

    for i in range(numrecords):
        if float(aircrafttas[i]) * float(activetime[i]) > 0:
            conc1d[i, :] = (
                spec1d[i, :] / (sa * aircrafttas[i] * activetime[i])
                / (binwidth / np.float32(1.0e6))
            )
            for j in range(numbins):
                hist = d.spec2d_orientation[i, j, :]
                omax = float(np.nanmax(hist)) if hist.size else 0.0
                totspec = float(np.nansum(hist))
                if totspec > 50:
                    orientation_index[i, j] = omax / totspec

    # `:677` -- `string(systime(/julian), format='(C(CYI, "/", CMOI2.2,
    # "/", CDI2.2, " ", CHI2.2, ":", CMI2.2, ":", CSI2.2))')`: local time
    # (`systime(/julian)` without `/UTC`), `YYYY/MM/DD HH:MM:SS`. The value
    # is non-deterministic; its *form* is not, and it is written into the
    # SAVE file. Before the SAVE writer this was `datetime.now(UTC).isoformat()`.
    date_processed = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    # `:689-721` -- close the PBP writers (only reached on this path; S6-f's
    # early returns above skip this by construction, matching the IDL).
    if csv_f is not None:
        csv_f.close()
    if ncdf_ds is not None:
        close_pbp_ncdf(ncdf_ds, pthdat=None)

    result = ProcessData(
        op=op, time=d.time, tas=aircrafttas, probetas=probetas, midbins=midbins,
        activetime=activetime, date_processed=date_processed, sa=sa,
        intspec_all=d.intspec_all, intspec_accepted=d.intspec_accepted,
        intendbins=d.intendbins, intmidbins=d.intmidbins,
        count_rejected=d.count_rejected, total_count_rejected=d.total_count_rejected,
        count_accepted=d.count_accepted, count_missed=d.count_missed,
        missed_hist=d.missed_hist, conc1d=conc1d, spec1d=spec1d, spec2d=d.spec2d,
        spec2d_aspr=d.spec2d_aspr, corr_fac=d.corr_fac, poisson_fac=d.poisson_fac,
        intcutoff=d.intcutoff, zdspec=d.zdspec, zdendbins=d.zdendbins,
        zdmidbins=d.zdmidbins, pointer=buffpoint, ind=buffindex, currentfile=bufffile,
        numbuffsaccepted=numbuffsaccepted, numbuffsrejected=numbuffsrejected,
        dhist=dhist, hist3d=d.hist3d, spec2d_orientation=d.spec2d_orientation,
        orientation_index=orientation_index, house=house, pbpstartindex=pbpstartindex,
        pbp_csv_path=fn_pbp_out, pbp_ncdf_path=fn_ncdf_out,
    )

    # `:722-726`: the ASCII PSD/counts export. IDL tests
    # `eq 1` here (not `ge 1`, unlike `ncdfparticlefile`'s `ge 1` above);
    # reproduced verbatim -- any other nonzero value writes nothing.
    if int(op.get("asciipsdfile", 0)) == 1:
        fn_asciipsd = pbp_filename(op, str(op["shortname"]), extension=".txt")
        soda2_export_ascii(result, fn_asciipsd)

    # `:729-731`: the output name comes from `soda2_filename`, and
    # the data are saved, compressed, only when `op.savfile` is 1.
    # `eq 1`, not `ge 1`: any other value writes nothing, as in the IDL.
    # `update_op` defaults `savfile` to 1, so a run writes the `.dat` unless
    # the caller sets `savfile=0` -- before the SAVE writer it silently never did.
    if int(op.get("savfile", 0)) == 1:
        if "outdir" not in {str(k).lower() for k in op}:
            # `soda2_filename.pro:5` reads `op.outdir`, a tag
            # `soda2_update_op` never defaults: IDL halts here.
            raise Soda2ProcessError(
                "soda2_process_2d.pro:729 / soda2_filename.pro:5: op has no "
                "OUTDIR tag -- IDL halts before writing the SAVE file (set "
                "op['outdir'], or savfile=0)")
        fn_out = pbp_filename(op, str(op["shortname"]))
        save_process_data(fn_out, result, compress=True)
        result.save_path = fn_out

    return result
