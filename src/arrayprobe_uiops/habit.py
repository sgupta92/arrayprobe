# SPDX-License-Identifier: BSD-3-Clause
"""Holroyd-family habit classification -- UIOOPS v3.5 (``holroyd.m``,
``holroyd_new.m``, ``holroyd_new_HVPS.m``).

**Two schemes exist in v3.5, selected by ``iNewHabit`` at the call site**
(``imgProc_sm.m:1218-1248``): the original Holroyd (1987) tree, generalized
here to work for any probe resolution, and a second tree "modified according
as outlined in Schima et al. 2024" that comes in a 2D-S variant
(:func:`holroyd_new`) and an HVPS variant (:func:`holroyd_new_hvps`) -- two
separate MATLAB files, not one function parameterized by probe. This module
ports all three call targets.

**What changed in the original scheme (v3.1.4 -> v3.5's ``holroyd.m``),
measured by diffing the two files directly, not assumed from the docstring
claim that it is "a generalization":**

* ``probe_resolution`` changed from the v3.1.4 port's hardcoded ``0.025`` mm
  to ``handles.diodesize`` -- now a required argument here
  (:data:`PROBE_RESOLUTION` does not exist in this module on purpose).
* A second return value, ``F_fine_detail``, was added.
* The ``parabola_fit_center_is_in`` gate that made habit ``'C'`` unreachable
  in v3.1.4 was **deleted outright** -- v3.5's ``holroyd.m`` calls
  ``calc_stat`` unconditionally, with no ``else`` branch and no ``'C'``
  anywhere in the function. Confirmed by reading the whole file: v3.5's
  ``holroyd.m`` cannot itself emit ``'C'``.
* Three of the four length thresholds were re-expressed in physical units
  with the *same* numeric threshold (``d_length < 64`` -> ``d_length *
  probe_resolution < 1.6``, ``64*0.025 == 1.6``; ``d_length >= 64`` ->
  ``... >= 1.6``; ``d_length >= 32`` -> ``... >= 0.8``; ``x_length <= 7.0`` ->
  ``x_length * probe_resolution <= 0.175``, ``7.0*0.025 == 0.175``) -- pure
  generalization, verified by arithmetic, not new science.
* **The fourth is not a pure generalization.** v3.1.4's aggregate test is
  ``(d_length * probe_resolution > 6.4) or (d_length > 160.0)``; v3.5's is
  ``d_length * probe_resolution > 4.0`` with the ``d_length > 160.0`` disjunct
  *commented out* in the source (``holroyd.m:56``:
  ``%|| (d_length > 160.0))``). The threshold moved from 6.4 to 4.0 mm and the
  diode-count fallback was dropped entirely -- a real algorithmic change, not
  a unit rewrite. Preserved exactly as v3.5 has it; not "fixed" back to 6.4.

Reference: Holroyd, *J. Atmos. Oceanic Technol.* **4**, 498-511 (1987);
Schima, J., McFarquhar, G. M., Delene, D., Heymsfield, A., Bansemer, A.,
Schnaiter, M., Finlon, J. A., Järvinen, E., and Nehlert, F., *A Multi-Probe
Automated Classification of Ice Crystal Habits During the IMPACTS Campaign*,
J. Geophys. Res. Atmos., **129**, e2024JD040895 (2024),
doi:10.1029/2024JD040895 (habit codes only -- this port transcribes
the MATLAB, it does not independently verify the paper's claims).

``calc_stat`` (the 9-output helper) is **byte-identical** between v3.1.4's
``holroyd.m`` and v3.5's ``holroyd.m`` (diffed directly: only whitespace and
one cosmetic ``&``->``&&``), so :func:`holroyd` below reuses
:func:`arrayprobe.habit.calc_stat` and :class:`arrayprobe.habit.ShapeStats`
rather than re-translating them -- the same reuse discipline
``particle_physics.py`` used for ``single_vt`` before it moved here.

**The new scheme's ``calc_stat`` is also shared, between the two files.**
``holroyd_new.m`` and ``holroyd_new_HVPS.m`` diff to *zero* in their
``calc_stat`` subfunction (confirmed by direct diff) -- so
:func:`calc_stat_new` below serves both :func:`holroyd_new` and
:func:`holroyd_new_hvps`. It is a substantially different, richer
computation than the original scheme's ``calc_stat`` (TAS-ratio time-axis
scaling, front/back edge tracking for ``edge_diam_ratio``, a rotated-and-
**rounded** coordinate system feeding percentile-based width/length ratios
and a quadrant symmetry coefficient, and a max-gap statistic) -- not a
variant of the same function, a new one.

**The two decision trees over the new ``calc_stat`` differ in more than
tuning constants**, measured by diffing ``holroyd_new.m`` against
``holroyd_new_HVPS.m`` directly:

* Tuning coefficients differ (``C_1..C_4``); the 2D-S version alone has a
  fifth, ``C_5`` (plate).
* The 2D-S version identifies a column via a computed ``needed_ratio``
  compared against the aspect ratio; the HVPS version instead tests
  ``(a / (probe_resolution*1000) / d) < 1.6 - m_g/100 + (a_r-1)/5`` **or**
  ``a_r > 5`` -- a different test, not the same formula re-tuned.
  ``a`` here is the calc_stat area output already scaled to microns^2 by the
  caller (``a = a * (probe_resolution*1000)^2``), matching the MATLAB
  variable of the same name at this point in the function.
* The HVPS dendrite formula carries an extra ``* (1.4 - s_c)`` factor absent
  from the 2D-S formula.
* **The HVPS version has no plate branch and cannot emit habit ``'h'``
  (hexagonal) at all** -- confirmed by reading the whole decision tree, not
  inferred from the missing ``C_5``: its dendrite branch returns ``'d'``
  unconditionally where the 2D-S version splits ``'h'``/``'d'`` on
  ``w_l_m_p``, and the 2D-S version's entire plate-vs-dendrite fallback block
  before the final ``'i'`` is simply absent in the HVPS file.
* The tiny-particle threshold differs by probe geometry: ``d < 300`` microns
  (2D-S) vs. ``d < 1000`` microns (HVPS).

**A latent arity bug found while building this module's Octave oracle,
filed as V58 in the upstream-findings list.**
Both ``holroyd_new.m`` and
``holroyd_new_HVPS.m``'s ``n_slices == 0`` branch assigns only
``holroyd_habit = 'M'`` and returns, leaving the other 8 declared outputs
unassigned. ``imgProc_sm.m:1225-1248`` always requests all 9 outputs, so a
zero-slice call at that call site errors in real MATLAB/Octave with
"element number 9 undefined in return list" -- measured directly, not
inferred. ``holroyd.m`` had exactly this bug once (its own
``n_slices == 0`` branch carries the comment "need to assign a dummy value
~ Joe Finlon 11/3/19", i.e. the fix), but the fix was not carried over when
``holroyd_new.m``/``holroyd_new_HVPS.m`` were written. This module raises
:class:`ZeroSlicesUnassignedOutputs` in that case rather than silently
inventing values for the 8 unassigned outputs, matching MATLAB's own refusal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .habit_core import ShapeStats
from .habit_core import calc_stat as _calc_stat_v314
from .particle import shadow_mask

__all__ = [
    "MAX_TWOD_DATA_LENGTH",
    "ShapeStatsNew",
    "HolroydNewResult",
    "ZeroSlicesUnassignedOutputs",
    "holroyd",
    "holroyd_new",
    "holroyd_new_hvps",
    "calc_stat_new",
]

#: ``holroyd_new.m:214`` / ``holroyd_new_HVPS.m:175``. Same sentinel ceiling
#: as the v3.1.4/v3.5 ``holroyd.m`` calc_stat; see that module for the margin.
MAX_TWOD_DATA_LENGTH = 6000


class ZeroSlicesUnassignedOutputs(ValueError):
    """Raised where real MATLAB/Octave errors: a zero-slice call to
    ``holroyd_new``/``holroyd_new_HVPS`` requesting all 9 outputs.

    See the module docstring's "latent arity bug" note. Not a deviation --
    MATLAB itself refuses this call with "element number 9 undefined in
    return list" (measured under Octave 11.3.0); this is that refusal.
    """


@dataclass(frozen=True)
class ShapeStatsNew:
    """The 16 outputs of the new scheme's ``calc_stat``
    (``holroyd_new.m:211-674`` / ``holroyd_new_HVPS.m:172-635``, identical).

    Field order follows the MATLAB return list.
    """

    d_length: float
    w_width: float
    d: float
    a_angle: float
    area: float
    r2_correlation: float
    F_fine_detail: float
    O: float  # noqa: E741 -- the MATLAB variable name (opacity ratio)
    w_l_r_p: float
    w_l_m_p: float
    sym_coeff: float
    cir_area_ratio: float
    edge_diam_ratio: float
    max_gap: float
    aspect_ratio: float
    p_perimeter_change: float


@dataclass(frozen=True)
class HolroydNewResult:
    """The 9 outputs of ``holroyd_new``/``holroyd_new_hvps``, MATLAB order.

    Source: the output list of ``holroyd_new.m:7`` (UIOOPS v3.5)."""

    holroyd_habit: str
    F: float
    w_l_p: float
    c_r: float
    e_d_r: float
    m_g: float
    O: float  # noqa: E741 -- the MATLAB variable name (opacity ratio)
    a_r: float
    p: float


def holroyd(image_buffer: Any, probe_resolution: Any,
            bits_per_slice: Any = None) -> tuple[str, float]:
    """``holroyd.m:7-89`` (v3.5) -- classify one particle. Returns
    ``(holroyd_habit, F_fine_detail)``.

    ``probe_resolution`` is MATLAB's ``handles.diodesize`` (mm/diode) --
    required, no default: v3.5 made this probe-generic where v3.1.4 hardcoded
    it, and silently picking a value would be a fidelity decision this module
    does not get to make.
    ``bits_per_slice`` behaves as in
    the earlier translation's ``holroyd``: MATLAB's ``handles.bits_per_slice``,
    defaulting to the image's own width.

    Unlike v3.1.4's ``holroyd.m``, there is no
    ``parabola_fit_center_is_in`` gate to reproduce -- v3.5 deleted it, so
    this function's decision tree runs unconditionally, matching the source.
    """
    shadow = shadow_mask(image_buffer)
    if shadow.ndim != 2:
        shadow = np.atleast_2d(shadow)
    n_slices = shadow.shape[0]

    if n_slices == 0:
        return "M", 0.0  # holroyd.m:34-37 -- the dummy value is in the source

    if bits_per_slice is None:
        bits_per_slice = shadow.shape[1]
    s: ShapeStats = _calc_stat_v314(shadow, bits_per_slice)

    # holroyd.m:41-87 (v3.5). Order matters, as in the v3.1.4 tree.
    if s.area == 0:
        return "M", s.F_fine_detail
    if s.area < 25:
        return "t", s.F_fine_detail
    if (s.r2_correlation >= 0.4) or (
        (s.d_length * probe_resolution < 1.6)
        and ((s.x_length >= 4 * s.y_length) or (s.y_length >= 4 * s.x_length))
    ):
        if (s.a_angle > 30.0) and (s.a_angle < 60.0):
            return "o", s.F_fine_detail
        return "l", s.F_fine_detail
    # holroyd.m:56 (v3.5) -- threshold moved to 4.0 and the `d_length > 160`
    # disjunct is commented out in the source; see the module docstring.
    if s.d_length * probe_resolution > 4.0:
        return "a", s.F_fine_detail
    if s.S_ratio >= 0.7:
        return "g", s.F_fine_detail
    if s.d_length * probe_resolution >= 1.6:
        return ("g" if s.F_fine_detail <= 13 else "a"), s.F_fine_detail
    if s.F_fine_detail < 5.5:
        return "s", s.F_fine_detail
    if s.F_fine_detail < 10.0:
        return ("g" if s.d_length * probe_resolution >= 0.8 else "h"), s.F_fine_detail
    if (s.F_fine_detail < 16.0) or (s.x_length * probe_resolution <= 0.175):
        return "i", s.F_fine_detail
    return "d", s.F_fine_detail


def holroyd_new(image_buffer: Any, *, probe_resolution: Any, tas_ratio: Any,
                 bits_per_slice: Any = None) -> HolroydNewResult:
    """``holroyd_new.m:7-208`` -- the 2D-S "modified Holroyd" (Schima et al.
    2024, doi:10.1029/2024JD040895) scheme. See :func:`holroyd_new_hvps` for the HVPS
    variant -- the two are separate MATLAB files with real algorithmic differences, not one
    function parameterized by probe (module docstring).

    Every keyword is required -- see :func:`holroyd_new_hvps`.
    """
    return _holroyd_new_impl(image_buffer, probe_resolution, tas_ratio,
                              bits_per_slice, hvps=False)


def holroyd_new_hvps(image_buffer: Any, *, probe_resolution: Any, tas_ratio: Any,
                      bits_per_slice: Any = None) -> HolroydNewResult:
    """``holroyd_new_HVPS.m:7-169`` -- the HVPS "modified Holroyd" scheme.

    Every keyword is required -- see :func:`holroyd_new`.
    """
    return _holroyd_new_impl(image_buffer, probe_resolution, tas_ratio,
                              bits_per_slice, hvps=True)


def _holroyd_new_impl(image_buffer: Any, probe_resolution: Any, tas_ratio: Any,
                       bits_per_slice: Any, *, hvps: bool) -> HolroydNewResult:
    shadow = shadow_mask(image_buffer)
    if shadow.ndim != 2:
        shadow = np.atleast_2d(shadow)
    n_slices = shadow.shape[0]

    if n_slices == 0:
        # holroyd_new.m:61-64 / holroyd_new_HVPS.m:61-63 -- see
        # ZeroSlicesUnassignedOutputs's docstring: MATLAB itself errors here
        # when called (as imgProc_sm.m always calls it) for all 9 outputs.
        raise ZeroSlicesUnassignedOutputs(
            "holroyd_new%s('M', n_slices=0): only holroyd_habit is assigned "
            "in the source; the other 8 outputs are undefined, matching "
            "MATLAB's own 'element number 9 undefined in return list'"
            % ("_HVPS" if hvps else "")
        )

    if bits_per_slice is None:
        bits_per_slice = shadow.shape[1]

    # holroyd_new.m:65 / holroyd_new_HVPS.m:65 -- parabola_fit_center_is_in
    # is still the stub that always returns 1 (unlike v3.5's `holroyd.m`,
    # which deleted this gate outright). Its else-branch (unconditional
    # 'C') is therefore dead by the same construction as the v3.1.4 port's
    # `holroyd`, and is not reachable from this function.
    s = calc_stat_new(shadow, bits_per_slice, tas_ratio)

    d = s.d * probe_resolution * 1000
    a = s.area * (probe_resolution * 1000) ** 2
    w_l_p = s.w_l_r_p * probe_resolution * 1000
    w_l_m_p = s.w_l_m_p * probe_resolution * 1000
    m_g = s.max_gap * probe_resolution * 1000
    p = s.p_perimeter_change * probe_resolution * 1000
    F = s.F_fine_detail
    O = s.O  # noqa: E741 -- the MATLAB variable name (opacity ratio)
    c_r = s.cir_area_ratio
    e_d_r = s.edge_diam_ratio
    a_r = s.aspect_ratio

    def result(habit: Any) -> Any:
        return HolroydNewResult(habit, F, w_l_p, c_r, e_d_r, m_g, O, a_r, p)

    if a == 0:
        return result("M")

    t_threshold = 1000 if hvps else 300
    if d < t_threshold:
        return result("t")

    if (m_g > (d / 3)) or (m_g >= 10 * (probe_resolution * 1000)) or (a_r > 20):
        return result("o")

    if e_d_r > 0.5:
        return result("C")

    if hvps:
        # holroyd_new_HVPS.m:100-109 -- two independent linear tests, not one
        # needed_ratio formula.
        if (a / (probe_resolution * 1000) / d) < 1.6 - m_g / 100 + (a_r - 1) / 5:
            return result("l")
        if a_r > 5:
            return result("l")
    else:
        # holroyd_new.m:107-119.
        needed_ratio = (
            1
            + ((w_l_p * w_l_m_p) / 40000)
            + (60 / (d * (probe_resolution * 1000))) * w_l_p
            + (d * 0.0005)
        )
        needed_ratio = min(needed_ratio, 5)
        if a_r >= needed_ratio:
            return result("l")

    c_1, c_2, c_3, c_4 = (0.80, 0.50, 0.30, 0.35) if hvps else (1.0, 1.0, 1.0, 1.0)

    sphere_f = c_1 * ((13 - (d / 250) - (abs(1 - c_r) * 7.5)) / a_r)
    if d < 1000:
        graupel_f = c_2 * ((25 - ((1 - O) * 15) + (d - 1000) / 30 - (abs(1 - c_r) * 15)) / a_r)
    else:
        graupel_f = c_2 * ((25 - ((1 - O) * 15) + (d - 1000) / 300 - (abs(1 - c_r) * 15)) / a_r)

    if hvps:
        s_c = s.sym_coeff
        if d < 1000:
            dendrite_f = c_3 * ((35 + d * d / 3e5) * a_r * (1 + (1000 - d) / 200)) * (1.4 - s_c)
        else:
            dendrite_f = c_3 * ((35 + d * d / 3e5) * a_r) * (1.4 - s_c)
    else:
        if d < 1000:
            dendrite_f = c_3 * (35 + d * d / 3e5) * a_r * (1 + (1000 - d) / 200)
        else:
            dendrite_f = c_3 * (35 + d * d / 3e5) * a_r

    if d < 1000:
        aggregate_f = c_4 * (30 - (d - 1000) / 30 + s.sym_coeff * 10)
    else:
        aggregate_f = c_4 * (30 - (d - 1000) / 300 + s.sym_coeff * 10)

    if not hvps:
        plate_f = (1.0 * (50 - (((60 - w_l_m_p) / 10) * 8 / a_r)) * (2 * e_d_r + 1)
                   * (1 + (2500 / (d * d)) * probe_resolution))
        if d > 1000:
            plate_f = plate_f * (d / 1000)

    if F <= sphere_f:
        return result("s")
    if F <= graupel_f:
        return result("g")

    if F > dendrite_f:
        if hvps:
            return result("d")
        if w_l_m_p < 100 - e_d_r * 200:
            return result("h")
        return result("d")

    if F > aggregate_f:
        return result("a")

    if not hvps:
        if ((O < 0.3) and (d < 1000)) or (F > plate_f):
            if (d > 700) and (w_l_m_p > 100):
                return result("d")
            return result("h")

    return result("i")


def calc_stat_new(image_buffer: Any, bits_per_slice: Any, tas_ratio: Any) -> ShapeStatsNew:
    """``holroyd_new.m:211-674`` / ``holroyd_new_HVPS.m:172-635``, identical
    (diffed directly to zero) -- the new scheme's shape statistics.

    A literal scalar transcription, matching this port's own
    ``calc_stat_scalar`` in style and intent: correctness first, no
    vectorized twin (a future speed-work candidate --
    not
    attempted here). Python's IEEE-754 float arithmetic reproduces MATLAB's
    NaN propagation and NaN-comparisons-are-false semantics directly in a
    scalar loop, the same reasoning the v3.1.4 habit module's ``_finish``
    documents for its vectorized path; the risky divisions (by ``n_count``,
    which is legitimately 0 for an all-background image reaching this
    function before the caller's ``area == 0`` guard) are done in
    ``numpy.float64`` under an ``errstate`` that allows ``0/0 = nan`` and
    ``c/0 = inf`` rather than Python's ``ZeroDivisionError``.
    """
    shadow = shadow_mask(image_buffer)
    n_slices = shadow.shape[0]
    if n_slices <= 0:
        raise ValueError("calc_stat_new requires at least one slice")
    if shadow.shape[1] < bits_per_slice:
        raise IndexError(
            f"image has {shadow.shape[1]} diodes, fewer than bits_per_slice={bits_per_slice}"
        )

    min_x = float(MAX_TWOD_DATA_LENGTH * 3)
    min_y = float(bits_per_slice * 3)
    max_x = 0.0
    max_y = 0.0
    first_on_edge_x = -1.0
    last_on_edge_x = -2.0
    first_on_edge_y = -1
    last_on_edge_y = -2
    sum_x2 = sum_y2 = sum_x = sum_y = sum_xy = 0.0
    p_perimeter_change = 0.0
    n_count = 0
    spot_on_off = 0
    fully_on_count = 0
    partial_on_count = 0
    px: list[float] = []
    py: list[float] = []

    # holroyd_new.m:256-339 -- row-major scan, TAS-scaled x-axis.
    for i in range(1, n_slices + 1):
        fully_on_temp = 0
        min_y_temp = float(bits_per_slice * 3)
        max_y_temp = 0.0
        for j in range(1, bits_per_slice + 1):
            if shadow[i - 1, j - 1]:
                tx = i / tas_ratio
                ty = float(j)
                max_x = max(max_x, tx)
                min_x = min(min_x, tx)
                max_y = max(max_y, ty)
                max_y_temp = max(max_y_temp, ty)
                min_y_temp = min(min_y_temp, ty)
                min_y = min(min_y, ty)
                sum_x2 += tx * tx
                sum_y2 += ty * ty
                sum_x += tx
                sum_y += ty
                sum_xy += tx * ty
                n_count += 1
                px.append(tx)
                py.append(ty)
                fully_on_temp += 1
                if spot_on_off == 0:
                    spot_on_off = 1
                    p_perimeter_change += 1
                elif j == bits_per_slice:
                    p_perimeter_change += 1
            else:
                if spot_on_off == 1:
                    spot_on_off = 0
                    p_perimeter_change += 1
        if shadow[i - 1, 0]:
            tx_edge = i / tas_ratio
            if first_on_edge_x < 0:
                first_on_edge_x = tx_edge
            last_on_edge_x = tx_edge
        if shadow[i - 1, bits_per_slice - 1]:
            tx_edge = i / tas_ratio
            if first_on_edge_x < 0:
                first_on_edge_x = tx_edge
            last_on_edge_x = tx_edge
        if fully_on_temp != 0:
            partial_on_count += 1
            if fully_on_temp >= (max_y_temp - min_y_temp) * 0.8:
                fully_on_count += 1
    area = n_count / tas_ratio

    # holroyd_new.m:344-400 -- column-major scan, TAS-scaled increments.
    spot_on_off = 0
    fully_on_count_b = 0
    partial_on_count_b = 0
    for j in range(1, bits_per_slice + 1):
        fully_on_temp = 0
        min_x_temp = MAX_TWOD_DATA_LENGTH * 3
        max_x_temp = 0
        for i in range(1, n_slices + 1):
            if shadow[i - 1, j - 1]:
                max_x_temp = max(max_x_temp, i)
                min_x_temp = min(min_x_temp, i)
                fully_on_temp += 1
                if spot_on_off == 0:
                    spot_on_off = 1
                    p_perimeter_change += 1 / tas_ratio
                elif i == n_slices:
                    p_perimeter_change += 1 / tas_ratio
            else:
                if spot_on_off == 1:
                    spot_on_off = 0
                    p_perimeter_change += 1 / tas_ratio
        if shadow[0, j - 1]:
            if first_on_edge_y < 0:
                first_on_edge_y = j
            last_on_edge_y = j
        if fully_on_temp != 0:
            partial_on_count_b += 1
            if fully_on_temp >= (max_x_temp - min_x_temp) * 0.8:
                fully_on_count_b += 1

    # holroyd_new.m:402-412 computes x_length/y_length here and never uses
    # them again -- neither in the rest of the function nor in its output
    # list. A dead store in the source; not reproduced, since nothing reads
    # it there either (contrast imgProc_sm.m's size_mat, a dead store the
    # PORT once mistakenly gave a downstream use).

    with np.errstate(divide="ignore", invalid="ignore"):
        n_count_f = np.float64(n_count)
        sum_x_f, sum_y_f = np.float64(sum_x), np.float64(sum_y)
        sum_x2_f, sum_y2_f, sum_xy_f = np.float64(sum_x2), np.float64(sum_y2), np.float64(sum_xy)

        cross_xy = sum_xy_f - (sum_x_f * sum_y_f / n_count_f)
        cross_x2 = sum_x2_f - (sum_x_f * sum_x_f / n_count_f)
        cross_y2 = sum_y2_f - (sum_y_f * sum_y_f / n_count_f)

        slope = cross_xy / cross_x2
        # holroyd_new.m:421. MATLAB's sqrt of a negative real is imaginary, not
        # NaN, and `<` compares real parts. A particle confined to one slice
        # has cross_x2 == 0 in exact arithmetic; with tasRatio != 1 its x
        # coordinates are inexact and cross_x2 can come out a few ULP below
        # zero. MATLAB then gets abs(cross_xy)/(0 + b*1i), whose real part is
        # 0, so the `r2_correlation < 0.3` reset below fires; a float sqrt
        # would give NaN and skip it. The real part is kept.
        r2_prod = cross_x2 * cross_y2
        if r2_prod < 0:
            r2_correlation = 0.0
        else:
            r2_correlation = float(abs(cross_xy) / np.sqrt(r2_prod))

        angle_radian = float(np.arctan(slope))
        a_angle = angle_radian * (180.0 / math.pi)
        if a_angle < 0:
            a_angle += 180.0
            angle_radian += math.pi
        # holroyd_new.m:431-434 -- a reset absent from the old scheme's
        # calc_stat (arrayprobe.habit); present here.
        if r2_correlation < 0.3:
            a_angle = 0.0
            angle_radian = 0.0

        if (angle_radian > (math.pi / 2.0)) and (angle_radian <= math.pi):
            angle_radian = math.pi - angle_radian
        elif angle_radian > math.pi:  # pragma: no cover - see arrayprobe.habit's analog
            raise ValueError(f"HEY: something is wrong here  a_angle = {a_angle}")

        dmin_x = float(MAX_TWOD_DATA_LENGTH * 3)
        dmin_y = float(bits_per_slice)
        dmax_x = 0.0
        dmax_y = 0.0
        new_x_vals: list[float] = []
        new_y_vals: list[float] = []
        cos_a, sin_a = math.cos(angle_radian), math.sin(angle_radian)
        for k in range(n_count):
            # holroyd_new.m:454-455 -- rounded, unlike the old scheme's
            # calc_stat. round() here is MATLAB's round-half-away-from-zero;
            # Python's banker's-rounding `round()` differs at exact .5, which
            # a rotated real-valued coordinate essentially never lands on, so
            # this is not special-cased.
            new_x = _matlab_round(px[k] * cos_a + py[k] * sin_a)
            new_y = _matlab_round(py[k] * cos_a - px[k] * sin_a)
            new_x_vals.append(new_x)
            new_y_vals.append(new_y)
            if new_x > dmax_x:
                dmax_x = new_x
            if new_y > dmax_y:
                dmax_y = new_y
            if new_x < dmin_x:
                dmin_x = new_x
            if new_y < dmin_y:
                dmin_y = new_y

        d_length = dmax_x - dmin_x + 1
        w_width = dmax_y - dmin_y + 1
        d = max(d_length, w_width)

        widths_r: list[float] = []
        lengths_r: list[float] = []
        max_gap_x = -32768.0
        max_gap_y = -32768.0
        prev_x = 32768.0
        prev_y = 32768.0

        x_unique = sorted(set(new_x_vals))
        for curr_x in x_unique:
            col_ys = [new_y_vals[i] for i in range(n_count) if new_x_vals[i] == curr_x]
            if col_ys:
                widths_r.append(max(col_ys) - min(col_ys) + 1)
            if curr_x - prev_x > max_gap_x:
                max_gap_x = curr_x - prev_x
            prev_x = curr_x

        y_unique = sorted(set(new_y_vals))
        for curr_y in y_unique:
            row_xs = [new_x_vals[i] for i in range(n_count) if new_y_vals[i] == curr_y]
            if row_xs:
                lengths_r.append(max(row_xs) - min(row_xs) + 1)
            if curr_y - prev_y > max_gap_y:
                max_gap_y = curr_y - prev_y
            prev_y = curr_y

        if lengths_r and widths_r:
            p_low_x, p_high_x, p_higher_x = _prctile(lengths_r, (25, 75, 95))
            var_x = p_high_x - p_low_x
            var_higher_x = p_higher_x - p_high_x
            p_low_y, p_high_y, p_higher_y = _prctile(widths_r, (25, 75, 95))
            var_y = p_high_y - p_low_y
            var_higher_y = p_higher_y - p_high_y

            y_midpoint = dmax_y - w_width / 2
            x_midpoint = dmax_x - d_length / 2
            q1 = q2 = q3 = q4 = 0
            for i in range(n_count):
                xv, yv = new_x_vals[i], new_y_vals[i]
                if yv > y_midpoint and xv > x_midpoint:
                    q1 += 1
                if yv < y_midpoint and xv > x_midpoint:
                    q2 += 1
                if yv > y_midpoint and xv < x_midpoint:
                    q3 += 1
                if yv < y_midpoint and xv < x_midpoint:
                    q4 += 1
            if (q1 == 0 and q4 == 0) or (q2 == 0 and q3 == 0):
                sym_coeff = 0.0
            else:
                sym_1 = min(q1, q4) / max(q1, q4)
                sym_2 = min(q2, q3) / max(q2, q3)
                sym_coeff = sym_1 * sym_2
        else:
            var_x = var_higher_x = var_y = var_higher_y = sym_coeff = 0.0

        max_gap = max(max_gap_x, max_gap_y) - 1
        if max_gap < 0:
            max_gap = 32768.0

        edge_length_y = last_on_edge_y - first_on_edge_y + 1
        edge_length_x = last_on_edge_x - first_on_edge_x + 1
        # holroyd_new.m:643-647. `d` can be 0 for a degenerate image (the
        # scan finds nothing), and division there is MATLAB's IEEE 0/0=NaN /
        # c/0=inf, not Python's ZeroDivisionError -- do the risky divisions
        # in numpy float64, matching arrayprobe.habit's `_finish`.
        d_np = np.float64(d)
        area_np = np.float64(area)
        d_length_np, w_width_np = np.float64(d_length), np.float64(w_width)
        edge_diam_ratio = float(np.float64(edge_length_x) / d_np)
        if edge_length_y > 64:
            edge_diam_ratio = 1.0

        w_l_r_p = min(var_x, var_y)
        w_l_m_p = min(var_higher_x, var_higher_y)

        cir_area_ratio = float(area_np / (math.pi * (d_np / 2) ** 2))

        aspect_ratio = (1.0 if area < 1.5
                         else float(max(d_length_np / w_width_np, w_width_np / d_length_np)))

        f_fine_detail = float(np.float64(p_perimeter_change) * d_np / area_np)
        O = (  # noqa: E741 -- the MATLAB variable name (opacity ratio)
            ((fully_on_count / partial_on_count) + (fully_on_count_b / partial_on_count_b)) / 2
            if (partial_on_count != 0 and partial_on_count_b != 0) else 0.0
        )

    return ShapeStatsNew(
        d_length=float(d_length),
        w_width=float(w_width),
        d=float(d),
        a_angle=float(a_angle),
        area=float(area),
        r2_correlation=float(r2_correlation),
        F_fine_detail=float(f_fine_detail),
        O=float(O),
        w_l_r_p=float(w_l_r_p),
        w_l_m_p=float(w_l_m_p),
        sym_coeff=float(sym_coeff),
        cir_area_ratio=float(cir_area_ratio),
        edge_diam_ratio=float(edge_diam_ratio),
        max_gap=float(max_gap),
        aspect_ratio=float(aspect_ratio),
        p_perimeter_change=float(p_perimeter_change),
    )


def _matlab_round(x: float) -> float:
    """MATLAB/Octave ``round``: half away from zero, unlike Python's banker's
    rounding; NaN round-trips as NaN rather than raising, as MATLAB's does.
    ``holroyd_new.m:454-455``. A NaN here means the point's rotation angle
    was itself NaN (a single-slice or single-diode particle, see the
    ``slope`` comment above) -- the same degenerate case
    ``arrayprobe.habit``'s ``_finish`` documents for the old scheme.

    ``floor(x + 0.5)`` is not this function: the addition itself rounds, so
    ``0.49999999999999994`` and every odd integer above 2^52 come out one too
    high. ``x - floor(x)`` is exact for every finite double, so the half is
    tested on that instead (Octave golden: ``tests/data/v35_r10_particle_golden.json``).
    """
    if not math.isfinite(x):
        return x
    if x >= 0:
        f = math.floor(x)
        return f + 1 if x - f >= 0.5 else f
    c = math.ceil(x)
    return c - 1 if c - x >= 0.5 else c


def _prctile(data: Any, percentiles: Any) -> Any:
    """MATLAB/Octave ``prctile`` (linear interpolation between the empirical
    CDF's ``(i-0.5)/n`` plotting positions; extrapolates to min/max outside
    that range) -- ``holroyd_new.m:563-573`` calls it with a plain vector and
    no method argument, which is this variant.

    No existing port of ``prctile`` was found in ``arrayprobe`` to reuse
    (checked before writing this).
    """
    xs = sorted(data)
    n = len(xs)
    out = []
    for p in percentiles:
        if n == 1:
            out.append(float(xs[0]))
            continue
        pos = (p / 100.0) * n - 0.5  # 0-based position on the plotting-position scale
        if pos <= 0:
            out.append(float(xs[0]))
        elif pos >= n - 1:
            out.append(float(xs[-1]))
        else:
            lo = int(math.floor(pos))
            frac = pos - lo
            out.append(float(xs[lo] + frac * (xs[lo + 1] - xs[lo])))
    return out
