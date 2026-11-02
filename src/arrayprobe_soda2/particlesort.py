# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_particlesort.pro:1-171`` -- SODA-2's per-buffer accumulation step.
Sorts a batch of particle structures into the
per-second accumulation arrays (``d``): PSD spectra, interarrival spectra,
deadtime, missed-particle histograms, the accept/reject tally.

Provenance: ``SODA2/abansemer-soda2-afcea15/soda2_particlesort.pro``, lines
1-171 only, Aaron Bansemer, NCAR, 2009. Copyright (C) 2016 UCAR, 3-clause BSD.

**Scope, exactly as agreed in the sizing-core plan (section C.1) -- everything else is
out of scope for this module, not silently dropped:**

- ``:172-300`` (the netCDF/ASCII per-particle-file writes) -- handled by the PBP/SAVE writers.
- The ``2DC`` deadtime block (``:64-76``) is ported (``_deadtime_2dc``):
  the gap between buffers, zeroed for format ``RAF`` (``:69``), summed per
  time index and capped at ``op.rate`` (``:74``), *assigned* (not added)
  before the forward ``:125-127`` accumulation. It needs ``inewbuffer``.
- The ``TXT`` interarrival/truetime branch (``:43-46``) -- refused by name;
  only ``op.format in ("SPEC", "SEA", "DMT", "RAF")`` is ported. The ``SEA`` branch
  (``:30-42``) was added by CIP-1, the driver's
  own SEA/CIP dispatch requiring it (``process_2d.py``'s ``_flush``). The
  ``DMT`` (PADS/PACS) path was added in pass 5 item 7b: it is the
  *pre-branch default* -- ``truetime`` from ``:12``, ``interarrival =
  difftime`` from ``:13``/``:16`` -- plus the **forward** deadtime ``ELSE``
  of ``:125-127``, which ``:59``'s ``deadtime`` feeds; asserted bit for bit
  against the whole-driver GDL golden ``tests/data/gdl_soda2_dmt_golden.json``
  (``tests/test_soda2_dmt_driver.py``).
- ``reprocessed_time`` -- accepted as a keyword-equivalent argument and
  applied exactly where ``:28`` applies it (one assignment).

Imports nothing from ``arrayprobe`` or ``arrayprobe_uiops`` (``arrayprobe_soda2``
is a separate port with its own oracle discipline).

**GDL bank**: ``scripts/validation/gdl/
run_soda2_particlesort_bank.py`` (14 cases, all OK), golden at
``tests/data/gdl_soda2_particlesort_golden.json``. Two traps below were
measured WRONG against round 5's reading of the IDL and are now fixed and
cited to the golden case that forced each (the first hypothesis -> trap 10 / S5-q; the
second -> trap 3 / S5-p). Everything else in this list was read correctly the first time and
the bank confirms it.


**Traps preserved, each cited to the plan trap that named it:**

1. ``:22`` ``x.inttime > 0`` is MAX, not comparison -- a negative ``inttime``
   clamps to 0.
2. ``:12`` uses IDL ``MEDIAN`` without ``/EVEN``: for an even-length array
   this is the **upper**-middle sorted element, not an average of the two
   middle elements. Exposed as :func:`idl_median`; unused for the SPEC path
   after ``:28`` overrides ``truetime``, computed anyway for fidelity.
3. ``:50-56`` the cluster loop is sequential and self-referential
   (``cluster[i-1]`` is read after the previous iteration wrote it); a
   Python loop, not a vectorised one, and the running cluster count
   **wraps modulo 256 at the 256th chained particle** -- measured by the
   R6C GDL bank's ``cluster_300`` case (H2, finding **S5-p**), not the
   round-5 port's saturate-at-255. ``clustercount`` is ``BYTE + INT``
   (promotes to INT), then storing that INT into the BYTE ``cluster`` array
   truncates; the wrap zeroes the whole ``cluster[i-cluster[i-1]:i]`` range,
   so a 256-particle chain is entirely un-clustered and the chain restarts
   at 2 on the next particle. Round 5's docstring said "saturates at 255" --
   that was the port's own behaviour read back as if it were the IDL's,
   never measured; the bank refutes it.
4. ``:60`` ``long((truetime-starttime)/rate)`` truncates toward zero, so a
   particle before ``starttime`` gets ``timeindex = 0``, never negative.
5. ``:79`` the outer loop bound is ``(max(timeindex)<d.numrecords)`` -- IDL's
   binary ``<`` is MIN here, so the loop's upper bound is
   ``min(max(timeindex), numrecords)`` **inclusive**, and the inner guard
   ``itime lt d.numrecords`` (``:81``) then silently drops any particle whose
   ``timeindex`` lands exactly on ``numrecords``. Finding **S5-c**.
6. ``:87`` ``intbin=max(where(...))`` returns ``-1`` (``nw=0``) when nothing
   matches; the increment is guarded by ``nw gt 0``, so an interarrival
   below the first ``intendbins`` edge is silently uncounted.
7. ``:92`` the shattering-correction branch (``fit_poisson``) fires only
   when ``op.inttime_reject == 1`` **and** the second already holds more
   than 100 particles. See ``fit_poisson.py`` for why this branch has no
   GDL oracle.
8. ``:102-124`` SPEC deadtime is applied **backward**, split only across the
   start and stop time index -- the source's own comment marks the
   intermediate full-deadtime fill as deliberately removed (``:119-121``,
   preserved as a comment, not code). Read-only finding, not measured.
9. ``:159-163`` ``sizebin=max(where(op.endbins le binningsize))`` with a
   special case for ``binningsize == endbins[0]``; ``arbin``/``asprbin`` use
   strict ``lt``. When ``binningsize`` is below ``endbins[0]`` and not
   exactly equal, ``sizebin`` stays ``-1`` -- IDL's negative-subscript
   convention reads the **last** row of ``d.spec2d``, which this port
   reproduces because Python's own ``[-1]`` indexing means the same thing.
   Not yet measured whether IDL actually permits this without erroring;
   flagged for the GDL bank. Finding **S5-b**.
10. ``:177`` ``ireject=where(reject and [1,2,4,8,16,32,64])`` tests only the
    first seven reject bits -- bit 128 (depth-of-field) is never counted in
    ``d.count_rejected``, which is why that array has 7 columns
    (``soda2_process_2d.pro:65``, ``count_rejected:lonarr(numrecords,7)``).
    A particle rejected on bit 128 alone gives ``ireject=[-1]``, so
    ``d.count_rejected[itime,-1]`` increments the array's **last** column
    (the bit-64 column), not a dedicated bit-128 column. Finding **S5-a**.
    **``d.count_rejected[itime,ireject[0]]++`` takes the FIRST (lowest-bit)
    column, not the highest** -- measured by the R6C GDL bank's
    ``multi_bit_reject`` case (bits 1+8: IDL column 0, the round-5 port's
    ``_max_where`` gave column 3). H1, finding **S5-q**: the source's own
    comment "Increment for each reason" is wrong -- it increments one
    column, for the lowest-numbered reason.
11. ``:154`` ``binningsize /= sizecorrection`` runs under ``apply_psc``;
    ``sizecorrection == 0`` divides by zero in FLOAT (IEEE inf, no
    exception), pushing ``sizebin`` past every ``endbins`` edge. Finding
    **S5-d**.
12. ``:83`` the per-second TAS, the mean of the particles' ``probetas``, is an IDL FLOAT
    mean; ported as a running float32 accumulation (not ``numpy.mean`` on
    the float32 array, which sums in a wider working type by default) so a
    sequential-summation order is reproduced. Finding **S5-e** if a
    divergence from ``numpy.mean`` is later measured on real data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from arrayprobe_soda2.reject import Particle, RejectOptions, soda2_reject

__all__ = [
    "Accumulator",
    "ParticlesortOptions",
    "Soda2ParticlesortError",
    "idl_median",
    "new_accumulator",
    "soda2_particlesort",
]


class Soda2ParticlesortError(RuntimeError):
    """An IDL subscript-range halt this module reproduces as a raise, naming
    the line. CIP-1: ``soda2_particlesort.pro:39``'s ``truetime[1:*]`` halts in IDL
    for a 1-particle ``x`` (the finding derived for the SPEC branch's own
    ``:13``, same construct, `run_soda2_process_2d_bank.py` module docstring)."""

#: The particle-structure tags this module reads from ``x`` (sizing-core plan C.2),
#: plus the six ``soda2_reject`` needs (``arearatio``, ``arearatiofilled``,
#: ``allin``, ``centerin``, ``diam``, ``dofflag`` -- already listed below).
X_TAGS = (
    "probetime",
    "buffertime",
    "reftime",
    "inttime",
    "overloadflag",
    "probetas",
    "missed",
    "xsize",
    "ysize",
    "areasize",
    "xextent",
    "oned",
    "twod",
    "diam",
    "sizecorrection",
    "arearatiofilled",
    "arearatio",
    "aspectratio",
    "orientation",
    "zd",
    "allin",
    "centerin",
    "dofflag",
)


def idl_median(values: np.ndarray) -> float:
    """IDL ``MEDIAN(values)`` without ``/EVEN``: for an even-length array
    this is the upper-middle sorted element, not an average. Python 0-based
    ``sorted[n // 2]`` lands on exactly that element for both parities."""
    sorted_values = np.sort(np.asarray(values, dtype=np.float64))
    n = sorted_values.size
    return float(sorted_values[n // 2])


def _max_where(condition: np.ndarray) -> tuple[int, int]:
    """``max(where(condition), nw)``: the largest index where ``condition``
    is true, and the count of true entries. ``(-1, 0)`` when none match,
    matching IDL's ``WHERE`` returning ``-1`` on no match."""
    idx = np.nonzero(condition)[0]
    if idx.size == 0:
        return -1, 0
    return int(idx.max()), int(idx.size)


def _first_where(condition: np.ndarray) -> tuple[int, int]:
    """``where(condition)`` indexed at ``[0]``: the SMALLEST index where
    ``condition`` is true (IDL's ``where()`` returns matches in ascending
    order), and the count of true entries. ``(-1, 0)`` when none match.

    Used only at ``:177``'s ``ireject=where(...)`` / ``ireject[0]`` -- the R6C
    GDL bank's ``multi_bit_reject`` case (bits 1+8: IDL column 0, the
    round-5 port's ``_max_where`` gave column 3) measured that IDL takes the
    FIRST element, not the last. Finding S5-q."""
    idx = np.nonzero(condition)[0]
    if idx.size == 0:
        return -1, 0
    return int(idx.min()), int(idx.size)


#: ``:162-163``'s ``0.99`` and ``0.01`` are FLOAT literals.
_F99 = float(np.float32(0.99))
_F01 = float(np.float32(0.01))


def _idl_clamp_99_01(value: float) -> float:
    """``value<0.99>0.01`` on an IDL scalar (``:162-163``). The binary MIN/MAX
    operators on a scalar keep the left operand only when the comparison is
    true, so a NaN comes out as 0.99 (GDL: ``!values.f_nan<0.99>0.01`` is
    0.990000), where Python's ``min``/``max`` and NumPy's keep the NaN. Both
    bounds are FLOAT, so the clamp lands on 0.99000000953674316, not 0.99."""
    v = value if value < _F99 else _F99
    return v if v > _F01 else _F01


def _idl_histogram_0_49(values: np.ndarray) -> np.ndarray:
    """``histogram(values, min=0, max=49)``: 50 integer bins, values outside
    ``[0, 49]`` excluded entirely (not clipped into an edge bin)."""
    counts = np.zeros(50, dtype=np.float64)
    in_range = values[(values >= 0) & (values <= 49)]
    idx, freq = np.unique(np.floor(in_range).astype(np.int64), return_counts=True)
    counts[idx] = freq
    return counts


@dataclass
class ParticlesortOptions:
    """The ``op`` (``*pop``) tags this module reads. ``format`` must be
    ``"SPEC"``, ``"SEA"``, ``"DMT"`` or ``"RAF"`` and ``probetype`` must not be
    ``"2DC"``; anything else raises ``NotImplementedError`` naming the source
    line the unported branch lives at."""

    starttime: float
    rate: float
    clusterthresh: float
    inttime_reject: int
    smethod: str
    apply_psc: int
    apply_psc_sizelimit: float
    water: int
    endbins: np.ndarray
    arendbins: np.ndarray
    eawmethod: str
    res: float = 0.0
    dofreject: int = 0
    format: str = "SPEC"
    probetype: str = ""

    def as_reject_options(self) -> RejectOptions:
        return RejectOptions(
            endbins=self.endbins,
            eawmethod=self.eawmethod,
            water=self.water,
            res=self.res,
            dofreject=self.dofreject,
            clusterthresh=self.clusterthresh,
        )


@dataclass
class Accumulator:
    """``d``, transcribed from ``soda2_process_2d.pro:49-104``. Every field's
    dtype mirrors the IDL literal it was built from (``fltarr`` -> float32,
    ``lonarr`` -> int32, ``dblarr``/``dindgen`` -> float64)."""

    numrecords: int
    numbins: int
    numarbins: int
    time: np.ndarray
    count_accepted: np.ndarray
    count_rejected: np.ndarray
    total_count_rejected: np.ndarray
    count_missed: np.ndarray
    missed_hist: np.ndarray
    spec2d: np.ndarray
    spec2d_aspr: np.ndarray
    spec2d_orientation: np.ndarray
    numintbins: int
    intendbins: np.ndarray
    intmidbins: np.ndarray
    intspec_all: np.ndarray
    intspec_accepted: np.ndarray
    numzdbins: int
    zdendbins: np.ndarray
    zdmidbins: np.ndarray
    zdspec: np.ndarray
    tas: np.ndarray
    poisson_fac: np.ndarray
    corr_fac: np.ndarray
    intcutoff: np.ndarray
    deadtime: np.ndarray
    hist3d: np.ndarray


def _idl_powf(base: float | np.ndarray, exponent: float | np.ndarray) -> np.ndarray:
    """IDL FLOAT^FLOAT, platform-independently: the correctly rounded double
    power narrowed to FLOAT (the same rule ``export_ascii._idl_alog10`` uses
    for ``alog10``). ``numpy.power`` on float32 calls the C runtime's ``powf``,
    which is not correctly rounded under glibc."""
    out = np.power(np.asarray(base, dtype=np.float64), np.asarray(exponent, dtype=np.float64))
    return out.astype(np.float32)


def new_accumulator(op: ParticlesortOptions, numrecords: int) -> Accumulator:
    """``d={...}`` from ``soda2_process_2d.pro:49-104``. ``numbins``/
    ``numarbins`` come from ``op.endbins``/``op.arendbins`` the way the
    source derives them (``n_elements(endbins)-1``)."""
    numbins = len(op.endbins) - 1
    numarbins = len(op.arendbins) - 1
    numintbins = 40
    iminpower, imaxpower = -7, 1
    span = imaxpower - iminpower
    # IDL ``10.0^float``: the double-precision power rounded once to FLOAT.
    # Measured against the GDL golden (all 81 edges bit-identical); numpy's
    # own float32 power is the platform ``powf`` and differs from it by one
    # ULP in 13 of 81 edges under glibc, in none under the MSVC runtime.
    intendbins = _idl_powf(10.0, (np.arange(numintbins + 1, dtype=np.float32) / numintbins)
                           * span + iminpower)
    intmidbins = _idl_powf(10.0, ((np.arange(numintbins, dtype=np.float32) + 0.5) / numintbins)
                           * span + iminpower)
    numzdbins = 163

    return Accumulator(
        numrecords=numrecords,
        numbins=numbins,
        numarbins=numarbins,
        time=op.starttime + op.rate * np.arange(numrecords, dtype=np.float64),
        count_accepted=np.zeros(numrecords, dtype=np.int32),
        count_rejected=np.zeros((numrecords, 7), dtype=np.int32),
        total_count_rejected=np.zeros(numrecords, dtype=np.int32),
        count_missed=np.zeros(numrecords, dtype=np.int32),
        missed_hist=np.zeros((numrecords, 50), dtype=np.float32),
        spec2d=np.zeros((numrecords, numbins, numarbins), dtype=np.float32),
        spec2d_aspr=np.zeros((numrecords, numbins, numarbins), dtype=np.float32),
        spec2d_orientation=np.zeros((numrecords, numbins, 18), dtype=np.float32),
        numintbins=numintbins,
        intendbins=intendbins,
        intmidbins=intmidbins,
        intspec_all=np.zeros((numrecords, numintbins), dtype=np.float32),
        intspec_accepted=np.zeros((numrecords, numintbins), dtype=np.float32),
        numzdbins=numzdbins,
        zdendbins=np.arange(numzdbins, dtype=np.float32) * 0.05 - 0.025,
        zdmidbins=np.arange(numzdbins, dtype=np.float32) * 0.05,
        zdspec=np.zeros((numbins, numzdbins), dtype=np.int32),
        tas=np.zeros(numrecords, dtype=np.float32),
        poisson_fac=np.zeros((numrecords, 3), dtype=np.float32),
        corr_fac=np.ones(numrecords, dtype=np.float32),
        intcutoff=np.zeros(numrecords, dtype=np.float32),
        deadtime=np.zeros(numrecords, dtype=np.float32),
        hist3d=np.zeros((numbins, numarbins, numarbins), dtype=np.float32),
    )


def spec_sort_locals(
    x: dict[str, np.ndarray], reprocessed_time: np.ndarray | None = None,
    format: str = "SPEC",
) -> tuple[np.ndarray, np.ndarray]:
    """``soda2_particlesort.pro:22`` and ``:28`` (SPEC), ``:30-41`` (SEA) or
    ``:12-16`` (the pre-branch default, which every format the IDL does not
    override at ``:21-46`` takes -- here ``DMT`` and ``RAF``) --
    the two locals the PBP writers consume (``truetime``, ``interarrival``),
    extracted so the writers and their GDL test see exactly what
    :func:`soda2_particlesort` used internally. Round 8-B (§D)
    ported the SPEC branch as a pure extraction; CIP-1 adds the
    ``format`` keyword for the SEA branch it ports here -- SPEC's own path
    through this function is unchanged (same three lines, same default)."""
    inttime = np.asarray(x["inttime"], dtype=np.float64)
    buffertime = np.asarray(x["buffertime"], dtype=np.float64)
    if format in ("DMT", "RAF"):
        # :12-16 are the pre-branch default: only SPEC (:21-29), SEA (:30-41)
        # and TXT (:43-46) override them, so RAF takes them exactly as DMT.
        probetime = np.asarray(x["probetime"], dtype=np.float64)
        reftime = np.asarray(x["reftime"], dtype=np.float64)
        if probetime.size == 1:
            # `:13` successive `truetime` differences, 0 first, floored at 0 -- the same
            # out-of-range `1:*` as the SEA branch's `:39`; GDL halts one
            # line earlier, at `:12`'s `median` of a 1-element struct field
            # (`run_soda2_particlesort_bank.py`, `_PAD`).
            raise Soda2ParticlesortError(
                "soda2_particlesort.pro:12-13 -- median/truetime[1:*] halt in "
                f"IDL for a 1-particle {format} flush (the :12-16 default)")
        # :12 -- DOUBLE + scalar DOUBLE median (upper-middle for even n).
        truetime = probetime + idl_median(buffertime - reftime)
        # :13/:16 -- `[0,truetime[1:*]-truetime]>0`, no `inttime` at all.
        interarrival = np.maximum(np.concatenate([[0.0], np.diff(truetime)]), 0.0)
        return truetime, interarrival
    if format == "SEA":
        probetime = np.asarray(x["probetime"], dtype=np.float64)
        reftime = np.asarray(x["reftime"], dtype=np.float64)
        if probetime.size == 1:
            # `:39` `it2 = [0,truetime[1:*]-truetime] > 0` -- IDL's
            # subscript range `1:*` on a 1-element array is out of range and
            # halts (the derived finding for the SPEC branch's own `:13`,
            # same construct).
            raise Soda2ParticlesortError(
                "soda2_particlesort.pro:39 -- truetime[1:*] halts in IDL "
                "for a 1-particle SEA flush")
        interarrival = np.maximum(inttime, 0.0)                        # :32
        truetime = probetime - reftime + buffertime                     # :36
        # :39 -- secondary interarrival calculation.
        it2 = np.maximum(np.concatenate([[0.0], np.diff(truetime)]), 0.0)
        # :40-41 -- bad interarrival times (>0.1 s off) zeroed. `0.1` is a
        # FLOAT literal: DOUBLE `gt` compares against 0.100000001490116.
        bad = np.abs(interarrival - it2) > np.float64(np.float32(0.1))
        if np.any(bad):
            interarrival = interarrival.copy()
            interarrival[bad] = 0.0
        return truetime, interarrival
    interarrival = np.maximum(inttime, 0.0)
    truetime = reprocessed_time if reprocessed_time is not None else buffertime
    truetime = np.asarray(truetime, dtype=np.float64)
    return truetime, interarrival


def _deadtime_2dc(op: ParticlesortOptions, d: Accumulator, truetime: np.ndarray,
                  timeindex: np.ndarray, inewbuffer: np.ndarray) -> None:
    """``soda2_particlesort.pro:65-76``, bug for bug.

    ``:68`` each dead time is a new buffer's first ``truetime`` minus the one
    before it, floored at 0
    (DOUBLE); ``:69`` the RAF arm replaces it with the INT scalar ``0``, so
    every ``total(deadtimes[w])`` is 0 and the block *zeroes*
    ``d.deadtime[itime]`` at each buffer start; ``:72-75`` loop
    ``min(timeindex)..max(timeindex)`` and **assign** ``total(...) < op.rate``
    (a sequential DOUBLE sum capped at the period, stored FLOAT) -- an
    assignment, not an accumulation, so a second call for the same second
    overwrites the first. The forward ``:125-127`` deadtime still adds on top.
    """
    if inewbuffer.size < 2:
        # `inewbuffer[1:*]` on a 1-element array halts in IDL.
        raise Soda2ParticlesortError(
            "soda2_particlesort.pro:68 -- inewbuffer[1:*] halts in IDL "
            "for a single buffer")
    # IDL clips an out-of-range element of a subscript *array* to the array's
    # bounds (no `compile_opt strictarrsubs` in this file): `inewbuffer` spans
    # every buffer of the run and is never reset at a flush, so it holds 0 for
    # rejected buffers (`-1` -> element 0) and stale starts from an earlier,
    # larger flush (-> the last element). NumPy would wrap or raise instead.
    # Checked under GDL 2026-10-07: `a=[1,2,3] & print, a[[-1,5]]` prints 1 3, and
    # `tt=[10d,20,30] & nb=[0,2,7] & print, tt[nb]-tt[nb-1]` prints 0 10 0.
    last = truetime.size - 1
    nb = np.clip(inewbuffer[1:], 0, last)
    nbm1 = np.clip(inewbuffer[1:] - 1, 0, last)
    ideadtime = timeindex[nb]                                          # :68
    raf = op.format == "RAF"                                           # :69
    deadtimes = None if raf else np.maximum(truetime[nb] - truetime[nbm1], 0.0)
    for itime in range(int(timeindex.min()), int(timeindex.max()) + 1):  # :72
        w = np.nonzero(ideadtime == itime)[0]                          # :73
        if w.size == 0:
            continue
        if not 0 <= itime < d.numrecords:
            raise Soda2ParticlesortError(
                f"soda2_particlesort.pro:74 -- d.deadtime[{itime}] is out of "
                f"range (numrecords {d.numrecords}); IDL halts")
        if raf:
            tot = 0.0      # total() of the INT scalar 0, however subscripted
        else:
            assert deadtimes is not None
            tot = 0.0
            for k in w:    # TOTAL: sequential DOUBLE sum
                tot += float(deadtimes[k])
        d.deadtime[itime] = np.float32(min(tot, float(op.rate)))       # :74 `< op.rate`


def soda2_particlesort(
    op: ParticlesortOptions,
    x: dict[str, np.ndarray],
    d: Accumulator,
    reprocessed_time: np.ndarray | None = None,
    inewbuffer: np.ndarray | None = None,
) -> np.ndarray:
    """Port of ``soda2_particlesort.pro:1-171``. Mutates ``d`` in place and
    returns ``rejectionflag`` (the IDL keeps it local); the PBP writers in
    :mod:`arrayprobe_soda2.pbp_writer` consume it directly. ``inewbuffer``
    (the IDL positional argument) is read only by the 2DC block
    (``:65-76``) and is required there."""
    if op.probetype == "2DC" and inewbuffer is None:
        raise Soda2ParticlesortError(
            "soda2_particlesort.pro:68 -- the 2DC deadtime block reads "
            "inewbuffer; pass it")
    if op.format not in ("SPEC", "SEA", "DMT", "RAF"):
        raise NotImplementedError(
            f"soda2_particlesort.pro:30-46 -- format {op.format!r} "
            "(only 'SPEC', 'SEA', 'DMT' and 'RAF' are ported)"
        )

    probetime = np.asarray(x["probetime"], dtype=np.float64)
    buffertime = np.asarray(x["buffertime"], dtype=np.float64)
    reftime = np.asarray(x["reftime"], dtype=np.float64)
    overloadflag = np.asarray(x["overloadflag"])
    numparticles = probetime.size
    rejectionflag = np.zeros(numparticles, dtype=np.uint8)

    # :12 -- computed for fidelity; unused for SPEC after :28 overrides truetime.
    _ = idl_median(buffertime - reftime)

    # :22 -- MAX, not comparison (trap 1). :28 -- SPEC truetime override.
    # :30-41 -- SEA truetime/interarrival (CIP-1, §2.3). :12-16 -- the
    # DMT defaults (pass 5, item 7b).
    truetime, interarrival = spec_sort_locals(x, reprocessed_time, format=op.format)

    # :49-56 -- sequential, self-referential cluster loop (trap 3). BYTE +
    # INT literal promotes to INT (`(cluster[i-1]+1)>2`), then storing that
    # INT back into the BYTE `cluster` array WRAPS modulo 256, it does not
    # saturate at 255 (H2, finding S5-p, measured by the R6C GDL bank's
    # cluster_300 case: of 300 particles chained with clusterthresh>0, GDL
    # accepts the first 255 -- the wrap at the 256th particle zeroes the
    # whole `cluster[0:255]` range via `cluster[i-cluster[i-1]:i]=0`, and the
    # chain restarts at 2 -- and rejects only the last 45, where a
    # saturating port would instead reject 299 of 300).
    cluster = np.zeros(numparticles, dtype=np.uint8)
    for i in range(1, numparticles):
        if interarrival[i] < op.clusterthresh:
            clustercount = (max(int(cluster[i - 1]) + 1, 2)) % 256
            start = i - int(cluster[i - 1])
            cluster[start : i + 1] = clustercount

    # :59 -- `interarrival*x.overloadflag`, DOUBLE * BYTE -> DOUBLE. Read
    # only by the forward `ELSE` at :126 (DMT); superseded for SPEC and
    # SEA/CIP by the backward deadtime block below (:102-124), same as the
    # IDL leaves it unused there.
    _deadtime_flagged = interarrival * overloadflag.astype(np.float64)
    # :102 -- which deadtime method this op takes.
    backward_deadtime = op.format == "SPEC" or (op.probetype == "CIP" and op.format == "SEA")
    # :60 -- truncation toward zero (trap 4), not floor.
    timeindex = np.trunc((truetime - op.starttime) / op.rate).astype(np.int64)

    if numparticles > 1:
        dtimeindex = np.diff(timeindex)
        # non-monotonic: IDL only prints a warning, doesn't raise.
        _ = dtimeindex.min() < 0 if dtimeindex.size else False

    # :65-76 -- 2DC only: deadtime from the gaps between buffers.
    if op.probetype == "2DC":
        assert inewbuffer is not None
        _deadtime_2dc(op, d, truetime, timeindex, np.asarray(inewbuffer, dtype=np.int64))

    lo = max(int(timeindex.min()), 0) if numparticles else 0
    hi = min(int(timeindex.max()), d.numrecords) if numparticles else -1

    for itime in range(lo, hi + 1):
        iparticles = np.nonzero(timeindex == itime)[0]
        nparticles = iparticles.size
        if not (0 <= itime < d.numrecords and nparticles > 0):
            continue  # trap 5: itime == numrecords is silently dropped

        # :83 -- FLOAT mean via sequential accumulation (trap 12).
        acc = np.float32(0.0)
        for k in iparticles:
            acc = np.float32(acc + np.float32(x["probetas"][k]))
        d.tas[itime] = np.float32(acc / np.float32(nparticles))

        for j in iparticles:
            intbin, nw = _max_where(d.intendbins <= interarrival[j])
            if nw > 0 and intbin < d.numintbins:
                d.intspec_all[itime, intbin] += 1

        if op.inttime_reject == 1 and d.intspec_all[itime, :].sum() > 100:
            from arrayprobe_soda2.fit_poisson import fit_poisson

            imax = int(np.argmax(d.intspec_all[itime, :]))
            poisson_firstguess = d.intmidbins[imax] / 5.0
            pf = fit_poisson(d.intspec_all[itime, :], d.intmidbins, poisson_firstguess, plot=False)
            d.poisson_fac[itime, :] = pf.a
            d.intcutoff[itime] = 1.0 / pf.a[1] * 0.05
            d.corr_fac[itime] = 1.0 / (2 * np.exp(-d.intcutoff[itime] * pf.a[1]) - 1)

        # :102-124 -- SPEC / SEA-CIP deadtime, applied backward (trap 8).
        # :125-127 -- every other format (DMT here) accumulates :59's
        # forward deadtime: FLOAT + TOTAL(DOUBLE) -> DOUBLE, stored FLOAT.
        # IDL's TOTAL is a sequential double sum, so accumulate in order.
        if not backward_deadtime:
            total = 0.0
            for j in iparticles:
                total += float(_deadtime_flagged[j])
            d.deadtime[itime] = np.float32(float(d.deadtime[itime]) + total)
        else:
            for j in iparticles:
                if x["overloadflag"][j]:
                    deadtimestart = truetime[j] - interarrival[j]
                    deadtimestop = truetime[j]
                    timeindexstart = max(int(np.trunc((deadtimestart - op.starttime) / op.rate)), 0)
                    timeindexstop = int(np.trunc((deadtimestop - op.starttime) / op.rate))
                    if timeindexstart == timeindexstop:
                        d.deadtime[timeindexstart] += interarrival[j]
                    else:
                        d.deadtime[timeindexstart] += (
                            d.time[timeindexstart] + op.rate - deadtimestart
                        )
                        d.deadtime[timeindexstop] += deadtimestop - d.time[timeindexstop]

        # :130 -- `x.missed` is FLOAT, `total()` a sequential FLOAT sum, and
        # LONG + FLOAT is FLOAT, truncated back into the LONG array. Past 2^24
        # the FLOAT sum rounds: a CIP's repeated counter gives missed = 65535
        # per particle, and 300 of them total 19660544 under GDL, not 19660500.
        missed32 = np.maximum(np.asarray(x["missed"], dtype=np.float32)[iparticles],
                              np.float32(0))
        tot32 = np.cumsum(missed32, dtype=np.float32)[-1]
        d.count_missed[itime] = int(np.float32(d.count_missed[itime]) + tot32)
        d.missed_hist[itime, :] += _idl_histogram_0_49(np.asarray(x["missed"][iparticles]))

        reject_opts = op.as_reject_options()
        for j in iparticles:
            j = int(j)
            match op.smethod:
                case "xsize":
                    binningsize = float(x["xsize"][j])
                case "ysize":
                    binningsize = float(x["ysize"][j])
                case "areasize":
                    binningsize = float(x["areasize"][j])
                case "xextent":
                    binningsize = float(x["xextent"][j])
                case "oned":
                    binningsize = float(x["oned"][j])
                case "twod":
                    binningsize = float(x["twod"][j])
                case _:
                    binningsize = float(x["diam"][j])

            apply_psc = 0
            if op.apply_psc == 1:
                if op.apply_psc_sizelimit == 0:
                    apply_psc = 1
                if op.apply_psc_sizelimit > 0 and binningsize <= op.apply_psc_sizelimit:
                    apply_psc = 1
            if op.water >= 1:
                apply_psc = 1
            if apply_psc == 1:
                # :154 -- trap 11: sizecorrection==0 divides to inf, not an
                # exception (IDL FLOAT semantics, finding S5-d). NumPy's
                # float32 division reproduces IEEE inf/nan where a plain
                # Python float division would raise ZeroDivisionError.
                with np.errstate(divide="ignore", invalid="ignore"):
                    binningsize = float(
                        np.float32(binningsize) / np.float32(x["sizecorrection"][j])
                    )

            binningar = (
                float(x["arearatiofilled"][j]) if op.water >= 1 else float(x["arearatio"][j])
            )

            particle = Particle(
                arearatio=float(x["arearatio"][j]),
                arearatiofilled=float(x["arearatiofilled"][j]),
                allin=int(x["allin"][j]),
                centerin=int(x["centerin"][j]),
                diam=float(x["diam"][j]),
                dofflag=int(x["dofflag"][j]),
            )
            nextidx = min(j + 1, numparticles - 1)
            result = soda2_reject(
                particle,
                interarrival[j],
                interarrival[nextidx],
                float(d.intcutoff[itime]),
                int(cluster[j]),
                binningsize,
                reject_opts,
            )
            reject = result.reject
            rejectionflag[j] = reject & 0xFF

            if reject == 0:
                # :159-161 -- trap 9: le, with the first-bin special case.
                sizebin, _nws = _max_where(op.endbins <= binningsize)
                if binningsize == op.endbins[0]:
                    sizebin = 0
                clamped_ar = _idl_clamp_99_01(binningar)
                arbin, _nwa = _max_where(op.arendbins < clamped_ar)
                clamped_aspr = _idl_clamp_99_01(float(x["aspectratio"][j]))
                asprbin, _nwasp = _max_where(op.arendbins < clamped_aspr)
                # IDL adds 90 in FLOAT, so the sum can round up across an
                # integer (GDL: floor(69.99999237 + 90) / 10 = 16; the double
                # sum gives 15). floor() -> LONG, then LONG / 10. Pass 6.
                o32 = np.float32(x["orientation"][j]) + np.float32(90)
                obin = min(int(np.floor(o32)) // 10, 17)

                d.spec2d[itime, sizebin, arbin] += 1
                d.spec2d_aspr[itime, sizebin, asprbin] += 1
                d.spec2d_orientation[itime, sizebin, obin] += 1
                d.count_accepted[itime] += 1
                d.hist3d[sizebin, arbin, asprbin] += 1

                intbin, nw = _max_where(d.intendbins <= interarrival[j])
                if nw > 0 and intbin < d.numintbins:
                    d.intspec_accepted[itime, intbin] += 1

                zdbin, _nzd = _max_where(d.zdendbins <= float(x["zd"][j]))
                d.zdspec[sizebin, zdbin] += 1
            else:
                # :177 -- trap 10: bit 128 is never counted (S5-a); a
                # no-overlap reject wraps to the last column via -1.
                # ireject[0] (S5-q, measured by the R6C GDL bank's
                # multi_bit_reject case): the FIRST set bit's column, not the
                # highest -- `where()` returns ascending indices and IDL
                # indexes element 0.
                bits = np.array([1, 2, 4, 8, 16, 32, 64])
                ireject, _n = _first_where((reject & bits) != 0)
                d.count_rejected[itime, ireject] += 1
                d.total_count_rejected[itime] += 1

    return rejectionflag
