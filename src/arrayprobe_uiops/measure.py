# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``imgProc_sm.m:1204-1291`` -- the per-particle measurement block.

The block is inline driver code between the record-time bookkeeping and the
``iRectEllipse`` unit: the minimum-enclosing-circle call, the ungated
``[EXPERIMENTAL]`` hollow override, the habit call, ``calculate_reject_unified``,
the area reconstruction, ``AreaR``/``Perimeter``/``sphericity``, the Korolev
retarget onto ``minR``, the centre-out ``'C'`` override and ``axis_ratio``.
Nothing else of ``imgProc_sm.m`` is here (no writer, no record loop, no iQC).

Every callee is the already-validated port of its own v3.5 file -- ``habit``
(V2), ``reject`` (V3), ``min_circle`` (V4) -- or the byte-identical
``arrayprobe.particle_perimeter``; this module re-translates none of them.

Validation: ``octave_oracle/run_v35_measure_bank.py`` slices the block's own
lines out of the vendored file and runs them under Octave with the real v3.5
callees and the v3.5 ``CGAL_minR`` MEX; ``tests/test_v35_measure.py`` asserts
every output of every record against that fixture.


Three things the block does that a reader would not expect,
all measured and reproduced here as written:

* the override's ``is_hollow = 1`` (``:1236``) is overwritten by the reject
  call's ninth output (``:1256-1260``) -- it reaches the file only as the
  ``ihollow`` *input* to the reject function;
* ``CGAL_minR`` returns a 0-based centre (``CGAL_minR.cpp:80-84``) that
  ``:1218-1219`` index 1-based, so the centre probe reads one pixel toward the
  origin and every particle of two pixels or fewer is ruled hollow;
* ``sphericity`` (``:1272``) is MATLAB ``mrdivide`` of two growing row vectors
  -- a least-squares slope over the record so far, exact only for ``kk == 1``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from arrayprobe_uiops.particle_perimeter import particle_perimeter
from arrayprobe_uiops.reject_core import RejectConfig

from .habit import HolroydNewResult, holroyd, holroyd_new, holroyd_new_hvps
from .hollow_size_rule import HollowSizeRule, resolve_ihollow, size_um_from_minr
from .min_circle import cgal_min_r_v35
from .particle import shadow_mask
from .reject import calculate_reject_unified

__all__ = [
    "RecordGeometry",
    "ParticleMeasurement",
    "RecordMeasurements",
    "STOCK_V35_REJECT_CONFIG",
    "IMAGE_ASSISTED_V35_REJECT_CONFIG",
    "measure_record",
    "sphericity_mrdivide",
]

#: ``calculate_reject_unified.m:60-66`` (v3.5) assigns these unconditionally at
#: the top of the function, so under the stock driver they are constants.
STOCK_V35_REJECT_CONFIG = RejectConfig(
    rej_zero_area=True, rej_split=True, rej_hollow=True,
    shadowed_area=25, max_edge_img_ar=6, max_comp_img_ar=5,
)

#: ``STOCK_V35_REJECT_CONFIG`` with **only** ``rej_hollow`` turned off --
#: every other field is the unchanged stock v3.5 value, cited on its own line
#: below against ``calculate_reject_unified.m`` in
#: ``UIOPS-v3.5/joefinlon-UIOPS-039be82/``.
#:
#: **This is NOT a second MATLAB tree's value, unlike
#: :data:`~arrayprobe.reject.ORACLES_PRODUCTION_REJECT_CONFIG`.** No fork ever
#: shipped this combination; it is a project decision (author,
#: 2026-09-18), made from the author's own 200 triage labels
#: against the hollow test's actual calls on the 2016-09-06 CIP:
#:
#: * **205-305 um: the hollow test discards 19 real particles in 25** -- about
#:   5,654 counts at stake in that bin, ~76% of them real.
#: * **105-205 um: ambiguous** (11 real / 14 artifact).
#: * **55-105 um: the test is correct 25/25.**
#:
#: This is the isolated half of an A/B that previously confounded two changes at
#: once (``ORACLES_PRODUCTION_V35`` moves ``rej_hollow`` AND both aspect-ratio
#: ceilings together), which is why stock showed *more* counts than production at
#: 55-105 um (R = 1.0396) while showing far fewer at 205-305 um (R = 0.2283) --
#: the looser aspect ratios were partly cancelling the stricter hollow test. This
#: profile moves only ``rej_hollow``, so a difference against ``STOCK_V35`` is
#: attributable to that one axis.
#:
#: **Honest caveat, because a single boolean cannot express size-dependent
#: labels**: turning ``rej_hollow`` off flat also admits the 55-105 um artifacts
#: the test was correctly catching there -- that bin is 68% artifact even among
#: particles BOTH configurations accept, so no threshold rescues it, and this
#: configuration is not optimal in that bin. The follow-on -- a size-dependent
#: accept/reject rule shaped like the labels themselves -- is new behaviour and
#: belongs opt-in inside the engine, not as a fourth package; it is not
#: this constant.
IMAGE_ASSISTED_V35_REJECT_CONFIG = RejectConfig(
    rej_zero_area=True,   # :60  stock sets rej_zero_area on    -- unchanged from stock
    rej_split=True,       # :61  stock sets rej_split on        -- unchanged from stock
    rej_hollow=False,     # :62  stock sets rej_hollow on       -- OVERRIDDEN 1->0
    shadowed_area=25,     # :64  stock shadowed_area 25         -- unchanged from stock
    max_edge_img_ar=6,    # :65  stock max_edge_img_ar 6        -- unchanged from stock
    max_comp_img_ar=5,    # :66  stock max_comp_img_ar 5        -- unchanged from stock
)


@dataclass(frozen=True)
class RecordGeometry:
    """The record-level inputs the block reads. Every field is required -- no
    default picks a probe or a ``tasRatio`` (no default silently
    picks a side)."""

    diodesize: float      #: ``handles.diodesize`` (mm/diode), from the probe table ``:141-235``
    diodenum: int         #: ``handles.diodenum``; also becomes ``handles.bits_per_slice`` (``:1206``)  # noqa: E501
    tas_ratio: float      #: ``handles.tasRatio`` (``:709``/``:711``)
    i_new_habit: int      #: ``iNewHabit`` -- 0 ``holroyd.m``, 1 ``holroyd_new*.m``
    probename: str        #: ``'HVPS'`` selects ``holroyd_new_HVPS.m`` under ``iNewHabit == 1`` (``:1224``)  # noqa: E501
    i_calc_all_diode_stats: int = 0  #: ``iCalcAllDiodeStats`` (``:1207-1209``)
    #: The size-dependent hollow rule. Defaults to a DISABLED rule, so every
    #: existing caller is bit-identical -- the rule only ever bypasses the hollow
    #: test above its threshold, and never manufactures a rejection.
    hollow_size_rule: HollowSizeRule = field(default_factory=lambda: HollowSizeRule())


@dataclass
class ParticleMeasurement:
    """One ``kk`` row of the ``images`` struct, MATLAB field names kept.

    Source: the ``images`` fields filled in ``imgProc_sm.m:1204-1291`` (UIOOPS v3.5)."""

    minR: float
    ctx: float
    cty: float
    FS: float
    holroyd_habit: str
    is_hollow: int
    image_length: float
    image_width: float
    image_area: float
    longest_y_within_a_slice: int
    max_top_edge_touching: int
    max_bottom_edge_touching: int
    image_touching_edge: object
    auto_reject: str
    percent_shadow: float
    part_z: float
    sf: float
    area_hole_ratio: float
    max_hole_diameter: float
    edge_at_max_hole: float
    center_in: int
    AreaR: float
    Perimeter: float
    sphericity: float
    axis_ratio: float
    #: ``holroyd_new*``'s seven extra outputs; ``None`` under ``iNewHabit == 0``
    new_habit: HolroydNewResult | None = None
    #: ``images.diode_stats(kk, :)`` when ``iCalcAllDiodeStats``; else ``None``
    diode_stats: np.ndarray | None = None


@dataclass
class RecordMeasurements:
    """What one record's pass through ``imgProc_sm.m:1204-1291`` (UIOOPS v3.5) leaves behind: the
    per-particle measurements, the accumulated ``diode_stats``, the last ``csum`` and the console
    warnings. Returned by :func:`measure_record`."""
    particles: list[ParticleMeasurement] = field(default_factory=list)
    #: ``diode_stats`` accumulated over the record (``:1210``)
    diode_stats_total: np.ndarray | None = None
    #: the last particle's ``csum`` (``:1211``)
    csum_last: np.ndarray | None = None
    #: the ``:1277`` console warnings, one string per firing
    warnings: list[str] = field(default_factory=list)


def sphericity_mrdivide(image_area: Any, perimeter: Any, tas_ratio: float) -> float:
    """``:1272`` -- ``sqrt(images.image_area/handles.tasRatio)/images.Perimeter``
    with BOTH operands the whole 1 x kk row vectors of the record so far.

    Source: ``imgProc_sm.m:1272`` (UIOOPS v3.5).

    ``/`` between two row vectors is MATLAB ``mrdivide``: it solves
    ``x * b = a`` for the scalar ``x`` in the least-squares sense, i.e. the
    slope of ``a`` on ``b`` through the origin. For ``kk == 1`` that is the
    plain per-particle ratio; for every later ``kk`` it is not. Preserved.
    """
    a = np.sqrt(np.asarray(image_area, dtype=float) / tas_ratio)
    b = np.asarray(perimeter, dtype=float)
    if a.size == 1:
        # A faithful 0/0 must still be nan (preserved, not "fixed"); this only
        # silences the RuntimeWarning a real run emitted 3,927 times for it.
        with np.errstate(invalid="ignore", divide="ignore"):
            return float(a[0] / b[0])
    # Octave solves the non-square `a / b` by Householder QR, not by SVD: `lstsq` (gelsd) landed
    # 1 ULP off the Octave golden on Linux where QR matches it (cloud pass 7 item 4).
    q, r = np.linalg.qr(b[:, None])
    # A rank-deficient b (every perimeter 0) or an infinite pivot: Octave returns the
    # minimum-norm solution, 0, where the QR division gives inf or NaN (cloud pass 8, F1;
    # [1 2]/[0 0], [0 0]/[0 0] and [1 2]/[Inf 1] are all 0 under Octave 11.3).
    if r[0, 0] == 0 or np.isinf(r[0, 0]):
        return 0.0
    return float((q.T @ a)[0] / r[0, 0])


def _ascii(shadow: np.ndarray) -> np.ndarray:
    """``ParticlePerimeter.m`` and the C++ read ASCII codes; 48 is shadowed."""
    return np.where(shadow, 48, 49).astype(np.int64)


def _habit_call(shadow: Any, geom: RecordGeometry) -> Any:
    """``:1220-1230`` / ``:1238-1250`` -- which classifier, with which handles."""
    if geom.i_new_habit == 0:
        habit, fs = holroyd(shadow, geom.diodesize, bits_per_slice=geom.diodenum)
        return habit, fs, None
    fn = holroyd_new_hvps if geom.probename == "HVPS" else holroyd_new
    res = fn(shadow, probe_resolution=geom.diodesize, tas_ratio=geom.tas_ratio,
             bits_per_slice=geom.diodenum)
    return res.holroyd_habit, res.F, res


def measure_record(images: Any, geom: RecordGeometry, reject_config: RejectConfig,
                   *, jit: bool = False) -> RecordMeasurements:
    """Run ``:1204-1291`` over the particles of one record, in order.

    Source: ``imgProc_sm.m:1204-1291`` (UIOOPS v3.5); bare line references here are into that file.

    ``images`` is the sequence of per-particle ``c`` matrices (any form
    :func:`arrayprobe.particle.shadow_mask` accepts; ``'0'`` / 48 / ``True`` is
    shadowed), each ``n_slices x diodenum``. State that persists across ``kk``
    -- ``diode_stats``, and the growing ``image_area``/``Perimeter`` vectors
    that ``sphericity`` reads -- lives here, which is why the unit is a record
    and not a particle.
    """
    out = RecordMeasurements()
    diode_stats = np.zeros(geom.diodenum, dtype=float)          # zeros(1, diodenum)
    areas: list[float] = []
    perims: list[float] = []
    csum = None

    for c in images:
        shadow = shadow_mask(c)
        if shadow.ndim != 2:
            shadow = np.atleast_2d(shadow)
        codes = _ascii(shadow)
        n_slices = shadow.shape[0]

        # :1207-1211
        row_stats = shadow.sum(axis=0).astype(float)             # sum(c=='0', 1)
        diode_stats = diode_stats + row_stats
        csum = row_stats

        # :1213-1216. ``codes`` is already in the MEX's own orientation -- rows
        # are slices, which is what :1207-1211's sum(c=='0', 1) above and
        # x_img_max = n_slices below both assume -- so it is passed straight
        # through. It was once passed as ``codes.T``,
        # to compensate for min_circle.py scaling the column where
        # CGAL_minR.cpp:75-84 scales the row; that defect was fixed 2026-09-11
        # and the
        # compensation came off with it. ctx is therefore the scaled SLICE
        # centre, which is the axis the hollow window below indexes.
        minR, ctx, cty = cgal_min_r_v35(codes, geom.tas_ratio)

        # :1218-1236 -- the [EXPERIMENTAL] hollow override, ungated. The window
        # is MATLAB 1-based on a 0-based centre: reproduced, not corrected.
        x_img_max = n_slices
        r_lo = max(1, math.floor(ctx))
        r_hi = min(x_img_max, math.ceil(ctx))
        c_lo = max(1, math.floor(cty))
        c_hi = min(geom.diodenum, math.ceil(cty))
        if r_hi >= r_lo and c_hi >= c_lo:
            window = shadow[r_lo - 1:r_hi, c_lo - 1:c_hi]
            n_unshadowed = int((~window).sum())
        else:
            n_unshadowed = 0                                       # empty range -> find([]) is empty  # noqa: E501
        override = (minR * geom.diodesize < 0.3) and n_unshadowed >= 1

        if override:
            _, fs, new_res = _habit_call(shadow, geom)            # `[~, images.FS(kk)]`
            habit = "s"
            is_hollow = 1
        else:
            habit, fs, new_res = _habit_call(shadow, geom)
            is_hollow = 0

        # :1256-1260 -- every output reassigned, is_hollow included
        # Two opt-in switches meet on this line, and both default to no-ops.
        # `resolve_ihollow` is the size-dependent rule: above its threshold the
        # hollow verdict is bypassed, because the author's 480 labels measured the
        # hollow test discarding 60-87 % real particles there. `jit` routes the
        # scan pass through arrayprobe_uiops.jit_kernels (6.33x, byte-identical).
        rj = calculate_reject_unified(
            codes, habit,
            resolve_ihollow(is_hollow,
                            size_um_from_minr(minR, geom.diodesize),
                            geom.hollow_size_rule),
            reject_config, jit=jit)
        is_hollow = rj.is_hollow

        # :1262-1267
        image_area = float(shadow.sum())
        disttoedge = min(abs(geom.diodenum - cty), cty)
        touching = rj.touching_edge
        touching_is_not_0 = (touching != "0") if isinstance(touching, str) else (touching != ord("0"))  # noqa: E501
        if rj.center_in == 1 and touching_is_not_0:
            with np.errstate(divide="ignore", invalid="ignore"):
                image_area = float(np.float64(image_area) * 2 * (rj.width - disttoedge) / rj.width)

        # :1270-1272
        area_r = 2 * math.sqrt(image_area / 3.1415926 / geom.tas_ratio)
        perimeter = particle_perimeter(codes) / math.sqrt(geom.tas_ratio)
        areas.append(image_area)
        perims.append(perimeter)
        sphericity = sphericity_mrdivide(areas, perims, geom.tas_ratio)

        # :1274-1280 -- Korolev correction retargeted onto minR
        if rj.reject_status == "H":
            minR = minR / rj.size_factor
            if habit != "s":
                out.warnings.append(f"WARNING: Habit should be spherical but is {habit}")

        # :1282-1285
        if rj.center_in == 0:
            habit = "C"

        # :1287-1291
        axis_ratio = rj.p_length / rj.width if rj.width != 0 else 0.0

        out.particles.append(ParticleMeasurement(
            minR=minR, ctx=ctx, cty=cty, FS=fs, holroyd_habit=habit, is_hollow=is_hollow,
            image_length=rj.p_length, image_width=rj.width, image_area=image_area,
            longest_y_within_a_slice=rj.longest_y, max_top_edge_touching=rj.max_top,
            max_bottom_edge_touching=rj.max_bottom, image_touching_edge=touching,
            auto_reject=rj.reject_status, percent_shadow=rj.percent_shadow_area,
            part_z=rj.part_z, sf=rj.size_factor, area_hole_ratio=rj.area_hole_ratio,
            max_hole_diameter=rj.max_hole_diameter, edge_at_max_hole=rj.edge_at_max_hole,
            center_in=rj.center_in, AreaR=area_r, Perimeter=perimeter, sphericity=sphericity,
            axis_ratio=axis_ratio, new_habit=new_res,
            diode_stats=row_stats.copy() if geom.i_calc_all_diode_stats else None,
        ))

    out.diode_stats_total = diode_stats
    out.csum_last = csum
    return out
