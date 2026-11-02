# SPDX-License-Identifier: BSD-3-Clause
"""``calculate_reject_unified.m`` (UIOOPS v3.5) -- reject-code logic, CHANGED
from v3.1.4 (:func:`arrayprobe.reject.calculate_reject_unified`).

Measured directly from `UIOPS-v3.5/joefinlon-UIOPS-039be82/calculate_reject_unified.m`
against the v3.1.4 source, not assumed. Real differences found:

1. **New required 4th argument, ``ihollow``.** v3.1.4 computes hollow status
   internally from a four-call ensemble vote (``is_it_hollow`` forward and
   reverse, ``is_it_hollow_sidescan`` forward and reverse) with elaborate
   habit-dependent tie-breaking (:297-309 of the v3.1.4 source). v3.5 drops
   that ensemble entirely: the caller (``imgProc_sm.m``, V8's scope --
   presumably the ungated experimental hollow rule documented elsewhere in the package,
   beside the whole-set sphericity computation) now decides hollow status itself, passing it in
   as ``ihollow``; this function just does ``is_hollow = ihollow`` and, if
   that came in true, calls ``is_it_hollow`` ONCE for the diameter/edge
   measurement the size correction needs.
2. **New output, ``center_in``.** ``center_in = 1`` unless
   ``p_length <= max(max_bottom, max_top)``, in which case ``center_in = 0``.
   This has no v3.1.4 equivalent; the note that habit ``'C'`` is
   reassigned in ``imgProc_sm.m`` when ``center_in == 0`` reads this output,
   external to this function and to ``holroyd``/``holroyd_new`` (V8's scope,
   not this one's).
3. **``is_it_hollow`` itself changed.** v3.1.4's version restricts the
   diameter scan to the middle third of the particle
   (``i > slices_third and i < slices - slices_third``); v3.5 removed that
   restriction entirely -- the "32-diode hollow packing,
   genuinely fixed" refers to this file's OTHER hollow routine
   (``is_it_hollow_sidescan``, no longer even called from here in v3.5); this
   is a separate, additional change to the un-sided scan. v3.1.4's bit-overlap
   test reconstructs 32-bit integers via ``bin2dec``/``bitshift`` across two
   16-bit halves; v3.5 replaces that with a direct elementwise
   ``bitand(image_buf(i,:)=='1', old=='1')`` on the character rows themselves.

**A second real MATLAB defect found while reading, not fixed:** the "side"
recompute of ``is_it_hollow`` on the transposed buffer assigns its status to
``hollow_status_side1``, a variable never read again -- ``hollow_status``
itself keeps whatever ``ihollow`` gave it. Only ``edge_at_max_hole`` and
``max_hole_diameter`` (genuine side effects the caller does use) come from
the second call; the recompute's own hollow/not-hollow verdict is dead code.
Preserved verbatim: this port never writes the recompute's status back into
``hollow_status``.

**A real MATLAB defect found while reading, not fixed:** the row-coverage
test at (the diff's) ``elseif n_lite > 0`` branch computes
``bufandold = bitand(image_buf(i,:)=='1', old=='1')`` -- an ARRAY, not a
scalar -- and then tests ``if bufandold > 0``. MATLAB's ``if`` on a
non-scalar array is true only when **every** element is nonzero, so this
branch (probably intended as "any bit overlaps") is true only when the ENTIRE
row overlaps the stored mask, which real diode data essentially never does.
Preserved here exactly, verified against a real Octave run rather than
"fixed" to the evidently-intended ``any(...)``.

**A genuine gap, not silently patched:** ``center_in`` is left UNASSIGNED by
the real MATLAB on the ``n_slices == 0`` early-return path -- measured
directly (Octave raises ``"element number 16 undefined in return list"`` on
a zero-slice case) -- the same shape of quirk V2 found in
``holroyd_new``/``holroyd_new_HVPS`` on zero-slice images. This port raises
:class:`ZeroSlicesUnassignedOutputs` on that path rather than inventing a
value for ``center_in``.

Confirmed against a real Octave 11.3.0 run of the unmodified v3.5 source,
210 cases (the earlier translation's own 105-particle reject bank, both ``ihollow``
values) -- see ``octave_oracle/run_v35_reject_oracle.m`` and
``tests/test_v35_reject.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from arrayprobe_uiops.reject_core import _vertical_split, mask_start_end, scan_slice

from .particle import shadow_mask

#: The module's honesty boundary, and the one place in either new port that
#: had none (found 2026-09-12, generating the API reference). The three
#: lookup helpers below are deliberately out: ``_z_d_lookup`` and
#: ``_edge_0_lookup`` read the Korolev tables, which are v3.5's data and not
#: an interface, and ``_Z_D``/``_SPOT_EDGE`` are those tables themselves.
__all__ = [
    "ZeroSlicesUnassignedOutputs",
    "RejectResultV35",
    "is_it_hollow",
    "calculate_reject_unified",
]


class ZeroSlicesUnassignedOutputs(RuntimeError):
    """The real MATLAB leaves ``center_in`` unassigned for a zero-slice image
    (measured: Octave errors "undefined in return list" on this path) --
    raised to match that refusal rather than inventing a value, the same
    rule already applied for ``holroyd_new``/``holroyd_new_HVPS``."""


@dataclass(frozen=True)
class RejectResultV35:
    """The result of :func:`calculate_reject_unified`. Adds ``center_in`` to
    the earlier translation's ``RejectResult`` fields; ``handles``
    is not a return value in v3.5 (its two fields are direct outputs
    instead), so this dataclass has no ``handles`` analogue.

    Source: the output list of ``calculate_reject_unified.m:1`` (UIOOPS v3.5)."""

    p_length: float
    width: float
    area: float
    longest_y: int
    max_top: int
    max_bottom: int
    touching_edge: object
    reject_status: str
    is_hollow: int
    percent_shadow_area: float
    part_z: float
    size_factor: float
    area_hole_ratio: float
    max_hole_diameter: float
    edge_at_max_hole: float
    center_in: int


def is_it_hollow(shadow: Any, slices: int, jit: bool = False) -> Any:
    """``calculate_reject_unified.m``'s v3.5 ``is_it_hollow`` -- CHANGED from
    the earlier translation's ``is_it_hollow``: no
    middle-third restriction on the diameter scan, and the row-overlap test
    is a direct elementwise ``bitand`` on the character rows rather than a
    ``bin2dec``/``bitshift`` reconstruction. See this module's docstring for
    the array-truthiness defect preserved in the coverage test below.

    The real MATLAB derives its own row width from ``size(image_buf)``
    rather than taking it as an argument (``im_width = size(image_buf)``,
    used only for ``mask_start_end``'s modulus) -- the caller passes the
    *same* buffer transposed for the "side" scan, so the width genuinely
    differs between the two calls this function receives, and a fixed
    ``bits_per_slice`` parameter (this port's first draft) breaks on the
    transposed call with a shape mismatch. ``bits_per_slice`` here is
    therefore read from ``shadow.shape[1]``, matching ``im_width(2))``.

    ``jit=True`` (opt-in, default off) dispatches to
    :func:`arrayprobe_uiops.jit_kernels.V35JitKernels.is_it_hollow`, a numba
    compilation of the exact body below (same state machine, same
    preserved ``bufandold.all()`` defect), fusing what would otherwise be
    one Python-level ``scan_slice`` dispatch per slice
    into one compiled call for the whole particle. Proven byte-identical to
    this body by a JIT identity test; requires numba
    (an optional extra), imported lazily only when ``jit=True`` is actually
    requested.
    """
    if jit:
        from . import jit_kernels
        return jit_kernels.load().is_it_hollow(shadow, slices)

    shadow = np.asarray(shadow)
    bits_per_slice = shadow.shape[1]

    start_img = 0  # 0 means "not yet found", matching MATLAB's 1-based sentinel
    end_img = 0
    for i in range(1, slices + 1):
        zero_amt = int(np.count_nonzero(shadow[i - 1]))
        if zero_amt > 0 and start_img == 0:
            start_img = i
        if zero_amt == 0 and start_img > 0:
            end_img = i
        if i == slices and end_img == 0:
            if start_img == 0:
                start_img = 1
            end_img = slices

    max_hole_diameter = 0
    edge_at_max_hole = 0
    status = 0
    old = None
    possibly_hollow = 0

    for i in range(start_img, end_img + 1):
        scan = scan_slice(shadow[i - 1])
        num_empty = scan.max_pos_lite - scan.min_pos_lite + 1 - scan.n_lite

        if num_empty > max_hole_diameter:
            max_hole_diameter = num_empty
            edge_at_max_hole = scan.max_pos_lite - scan.min_pos_lite + 1

        if possibly_hollow == 1 and status == 0:
            # `old` is set wherever `possibly_hollow` first becomes 1 (below), so by
            # construction it is never None here -- asserted rather than left for mypy
            # to (incorrectly) flag as possibly-None, and to document the invariant.
            assert old is not None
            lit_row = ~shadow[i - 1]  # image_buf(i,:) == '1'
            if scan.n_lite > 0 and scan.n_lite != scan.max_pos_lite - scan.min_pos_lite + 1:
                newandold = lit_row & old
                if not newandold.any():
                    status = 1
                else:
                    old = mask_start_end(scan.max_pos_lite, scan.min_pos_lite,
                                        shadow[i - 1], bits_per_slice)
            elif scan.n_lite > 0:
                bufandold = lit_row & old
                hole_size = int(old.sum())
                cover_size = int(bufandold.sum())
                # PRESERVED DEFECT (see module docstring): MATLAB's
                # `if bufandold > 0` on an array is "every element nonzero",
                # not "any element nonzero" -- replicated with `.all()`.
                if bufandold.size > 0 and bool(bufandold.all()):
                    if cover_size <= 0.65 * hole_size:
                        status = 1
                    possibly_hollow = 0
                    old = None
                elif i > 1:
                    status = 1
                else:
                    possibly_hollow = 0
                    old = None
            else:
                possibly_hollow = 0
        elif status == 0:
            if scan.n_lite > 0 and scan.n_lite != scan.max_pos_lite - scan.min_pos_lite + 1:
                old = mask_start_end(scan.max_pos_lite, scan.min_pos_lite,
                                    shadow[i - 1], bits_per_slice)
                possibly_hollow = 1

    return status, edge_at_max_hole, max_hole_diameter


def calculate_reject_unified(
    image_buffer: Any,
    habit: str,
    ihollow: int,
    config: Any,
    jit: bool = False,
) -> RejectResultV35:
    """v3.5's ``calculate_reject_unified.m``. ``config`` is a
    :class:`arrayprobe_uiops.reject_core.RejectConfig` (the same dataclass the v3.1.4
    port uses -- ``rej_zero_area``/``rej_split``/``rej_hollow``,
    ``shadowed_area``, ``max_edge_img_ar``, ``max_comp_img_ar`` are unchanged
    fields in the v3.5 source's own ``handles.*`` defaults).

    ``jit=True`` (opt-in, default off;
    ``_decoded/cip160906/V35_REJECT_JIT.md``) fuses the per-slice scanning
    loop below, and both :func:`is_it_hollow` calls in the hollow branch,
    into numba-compiled kernels (:mod:`arrayprobe_uiops.jit_kernels`) instead
    of one Python-level ``scan_slice`` dispatch per
    slice -- measured as this function's own dominant cost
    (``_decoded/cip160906/V35_JIT.md``: 7.367 s cumulative over 3,085 real
    CIP particles, 6.610 s of it inside ``scan_slice``). Writes the
    identical :class:`RejectResultV35` either way
    (checked by a JIT identity test); numba is imported lazily,
    only when ``jit=True`` is actually requested.
    """
    shadow = shadow_mask(image_buffer)
    if shadow.size == 0:
        # An empty image_buffer (no rows at all) -- np.atleast_2d would turn
        # this into a bogus one-row, zero-column shape, hiding the real
        # n_slices == 0 case the MATLAB source leaves center_in unassigned on.
        n_slices, bits_per_slice = 0, 0
    else:
        if shadow.ndim != 2:
            shadow = np.atleast_2d(shadow)
        n_slices, bits_per_slice = shadow.shape

    max_hole_diameter = 0.0
    edge_at_max_hole = 0.0
    min_length = -1
    max_length = -1
    max_width = 1
    min_width = bits_per_slice
    total_area = 0
    touch = 0
    width = 0.0
    ndrops = 0
    split = 0
    met_image = 0
    is_hollow = 0
    aspect_ratio = 0.0
    percent_shadow_area = 0.0
    area_hole_ratio = 0.0
    area = 0.0
    max_top = 0
    max_bottom = 0
    longest_y = 0
    part_z = -1.0
    size_factor = 1.0
    touching_edge: object = 0
    top_min_x = top_max_x = -1
    bottom_min_x = bottom_max_x = -1
    center_in = None  # unassigned unless the main branch below runs

    def result(p_length: Any, reject_status: Any) -> RejectResultV35:
        if center_in is None:
            raise ZeroSlicesUnassignedOutputs(
                "center_in is never assigned on the n_slices==0 path -- "
                "measured directly against the real v3.5 MATLAB source")
        return RejectResultV35(
            p_length=float(p_length), width=float(width), area=float(area),
            longest_y=longest_y, max_top=max_top, max_bottom=max_bottom,
            touching_edge=touching_edge, reject_status=reject_status,
            is_hollow=is_hollow, percent_shadow_area=float(percent_shadow_area),
            part_z=float(part_z), size_factor=float(size_factor),
            area_hole_ratio=float(area_hole_ratio),
            max_hole_diameter=float(max_hole_diameter),
            edge_at_max_hole=float(edge_at_max_hole), center_in=center_in,
        )

    if n_slices == 0:
        # center_in stays None: the real MATLAB never assigns it on this path
        # either, whichever reject_status it would have returned.
        raise ZeroSlicesUnassignedOutputs(
            "center_in is never assigned on the n_slices==0 path -- "
            "measured directly against the real v3.5 MATLAB source")

    if jit:
        from . import jit_kernels
        (longest_y, touch, bottom_min_x, bottom_max_x, top_min_x, top_max_x,
         max_width, min_width, min_length, max_length, total_area, split) = (
            jit_kernels.load().reject_scan_pass(shadow, n_slices, bits_per_slice,
                                                config.rej_split)
        )
    else:
        for i in range(1, n_slices + 1):
            scan = scan_slice(shadow[i - 1])
            longest_y = max(longest_y, scan.n_lite)

            if scan.n_lite > 0:
                if touch == 0:
                    if scan.max_pos_lite == bits_per_slice or scan.min_pos_lite == 1:
                        touch = 1
                if scan.min_pos_lite == 1:
                    if bottom_min_x == -1:
                        bottom_min_x = i
                    if bottom_max_x < i:
                        bottom_max_x = i
                if scan.max_pos_lite == bits_per_slice:
                    if top_min_x == -1:
                        top_min_x = i
                    if top_max_x < i:
                        top_max_x = i
                max_width = max(max_width, scan.max_pos_lite)
                min_width = min(min_width, scan.min_pos_lite)
                if min_length == -1:
                    min_length = i
                    max_length = i
                else:
                    max_length = i
                total_area += scan.n_lite

            if met_image == 0 and scan.n_lite > 0:
                met_image = 1
                ndrops += 1
                if ndrops > 1 and config.rej_split:
                    split = 1
            elif met_image == 1 and scan.n_lite == 0:
                met_image = 0

    area = total_area
    max_top = 0 if top_min_x == -1 else (top_max_x - top_min_x) + 1
    max_bottom = 0 if bottom_min_x == -1 else (bottom_max_x - bottom_min_x) + 1
    touching_edge = "t" if touch == 1 else "0"

    if total_area == 0:
        p_length = 0
        width = 0.0
    else:
        p_length = max_length - min_length + 1
        width = float(max_width - min_width + 1)
    # center_in is computed from p_length itself, after it is final -- matches
    # the real source's own order (this is the only assignment).
    center_in = 1
    if p_length <= max(max_bottom, max_top):
        center_in = 0

    if total_area > 0.8 * bits_per_slice * n_slices:
        return result(p_length, "A")
    if split == 1:
        return result(p_length, "s")

    vscan = scan_slice(_vertical_split(shadow[:n_slices]))
    v_n_lite = vscan.n_lite
    v_span = vscan.max_pos_lite - vscan.min_pos_lite + 1
    if v_n_lite == 1 and v_n_lite != v_span and not config.rej_split:
        return result(p_length, "s")

    if total_area > 0 and p_length > 0 and width > 0:
        aspect_ratio = p_length / width
        percent_shadow_area = total_area / (p_length * width) * 100
    else:
        aspect_ratio = 0.0
        percent_shadow_area = 0.0

    if total_area == 0 and config.rej_zero_area:
        return result(p_length, "z")
    if total_area == 0 and not config.rej_zero_area:
        return result(p_length, "0")
    if aspect_ratio > config.max_comp_img_ar or aspect_ratio < 1 / config.max_comp_img_ar:
        return result(p_length, "a")
    if touch == 1 and aspect_ratio > config.max_edge_img_ar:
        return result(p_length, "t")
    if percent_shadow_area < config.shadowed_area:
        return result(p_length, "p")
    if config.rej_hollow:
        hollow_status, edge_at_max_hole, max_hole_diameter = is_it_hollow(
            shadow[:n_slices], n_slices, jit=jit)
        is_hollow = int(ihollow)
        hollow_status = is_hollow
        if center_in == 1 and touching_edge != "0" and is_hollow == 1:
            # PRESERVED DEFECT: the real MATLAB assigns this call's status to
            # a DIFFERENT variable, `hollow_status_side1`, which is never
            # read again -- hollow_status itself keeps the `is_hollow` value
            # assigned above, untouched by this recompute. Only
            # edge_at_max_hole/max_hole_diameter (side effects the caller
            # does use) come from this second call.
            _hollow_status_side1, edge_at_max_hole, max_hole_diameter = is_it_hollow(
                shadow[:n_slices].T, bits_per_slice, jit=jit)
            del _hollow_status_side1
        if hollow_status == 1:
            ratio = 0.0 if edge_at_max_hole <= 0 else max_hole_diameter / edge_at_max_hole
            if ratio == 0:
                part_z, size_factor, reject_status, area_hole_ratio = 0.0, 1.0, "h", 0.0
            elif max_hole_diameter <= 1:
                part_z, size_factor, area_hole_ratio, reject_status = 0.0, 1.0, 0.0, "0"
            else:
                part_z = _z_d_lookup(ratio)
                size_factor = _edge_0_lookup(part_z)
                reject_status = "H"
                area_hole_ratio = area / max_hole_diameter
                if area_hole_ratio > 20 and habit == "i":
                    part_z, size_factor, reject_status = 0.0, 1.0, "u"
                elif area_hole_ratio > 35 and habit == "h":
                    part_z, size_factor, reject_status = 0.0, 1.0, "u"
                elif area_hole_ratio > 40 and habit != "s":
                    part_z, size_factor, reject_status = 0.0, 1.0, "u"
            return result(p_length, reject_status)
        part_z, size_factor, area_hole_ratio = -1.0, 1.0, 0.0

    return result(p_length, "0")


#: ``z_d = 0:.05:8.15`` and its two lookup tables, verbatim from the MATLAB
#: source (unchanged between v3.1.4 and v3.5) -- see
#: ``arrayprobe.reject`` for the same tables under the v3.1.4 port, kept as a
#: second copy here rather than imported, because :func:`calculate_reject_unified`
#: above is a from-scratch translation of a changed function, not a re-export.
# MATLAB's colon `0 : .05 : 8.15` is base + i*step (Octave 8.4 measured: all
# 164 entries equal i * 0.05, as in arrayprobe.reject.Z_D). The earlier
# round(i*0.05, 10) differed in 59 of 164 entries, and part_z is written to
# the file. Applied pass 6 (pass 5 item 4).
_Z_D = [i * 0.05 for i in range(164)]
_EDGE_0 = [
    1.000, 1.054, 1.083, 1.101, 1.095, 1.110, 1.148, 1.162, 1.155, 1.123,
    1.182, 1.121, 1.162, 1.210, 1.242, 1.134, 1.166, 1.202, 1.238, 1.270,
    1.294, 1.278, 1.130, 1.148, 1.170, 1.194, 1.218, 1.242, 1.265, 1.288,
    1.310, 1.331, 1.351, 1.369, 1.386, 1.400, 1.411, 1.416, 1.407, 1.074,
    1.080, 1.087, 1.096, 1.106, 1.117, 1.127, 1.139, 1.150, 1.162, 1.173,
    1.185, 1.197, 1.208, 1.220, 1.232, 1.243, 1.255, 1.266, 1.277, 1.289,
    1.300, 1.311, 1.322, 1.333, 1.344, 1.355, 1.366, 1.376, 1.387, 1.397,
    1.407, 1.418, 1.428, 1.438, 1.448, 1.458, 1.467, 1.477, 1.486, 1.496,
    1.505, 1.515, 1.524, 1.533, 1.542, 1.551, 1.559, 1.568, 1.577, 1.585,
    1.594, 1.602, 1.610, 1.618, 1.626, 1.634, 1.642, 1.650, 1.657, 1.665,
    1.673, 1.680, 1.687, 1.694, 1.702, 1.709, 1.716, 1.722, 1.729, 1.736,
    1.742, 1.749, 1.755, 1.761, 1.768, 1.774, 1.780, 1.786, 1.791, 1.797,
    1.803, 1.808, 1.813, 1.819, 1.824, 1.829, 1.834, 1.839, 1.843, 1.848,
    1.852, 1.857, 1.861, 1.865, 1.869, 1.872, 1.876, 1.880, 1.883, 1.886,
    1.889, 1.892, 1.895, 1.897, 1.899, 1.901, 1.903, 1.905, 1.906, 1.907,
    1.908, 1.908, 1.908, 1.908, 1.907, 1.905, 1.903, 1.900, 1.897, 1.892,
    1.885, 1.877, 1.865, 1.845,
]
_SPOT_EDGE = [
    0.003, 0.008, 0.017, 0.024, 0.033, 0.040, 0.047, 0.054, 0.062, 0.072,
    0.076, 0.088, 0.093, 0.096, 0.101, 0.119, 0.123, 0.127, 0.130, 0.134,
    0.139, 0.148, 0.175, 0.180, 0.184, 0.188, 0.192, 0.195, 0.199, 0.202,
    0.206, 0.209, 0.213, 0.217, 0.221, 0.225, 0.230, 0.235, 0.243, 0.327,
    0.334, 0.340, 0.345, 0.351, 0.355, 0.360, 0.365, 0.369, 0.373, 0.377,
    0.381, 0.385, 0.389, 0.393, 0.397, 0.400, 0.404, 0.408, 0.411, 0.415,
    0.419, 0.422, 0.426, 0.429, 0.433, 0.436, 0.439, 0.443, 0.446, 0.450,
    0.453, 0.457, 0.460, 0.463, 0.467, 0.470, 0.473, 0.477, 0.480, 0.484,
    0.487, 0.490, 0.494, 0.497, 0.501, 0.504, 0.507, 0.511, 0.514, 0.518,
    0.521, 0.525, 0.528, 0.532, 0.535, 0.539, 0.543, 0.547, 0.550, 0.554,
    0.558, 0.562, 0.566, 0.569, 0.572, 0.575, 0.578, 0.581, 0.584, 0.587,
    0.590, 0.593, 0.596, 0.598, 0.601, 0.605, 0.610, 0.614, 0.618, 0.623,
    0.627, 0.631, 0.635, 0.640, 0.644, 0.648, 0.653, 0.657, 0.662, 0.666,
    0.671, 0.676, 0.680, 0.685, 0.690, 0.695, 0.700, 0.705, 0.711, 0.716,
    0.721, 0.727, 0.733, 0.738, 0.744, 0.751, 757, 0.763, 0.770, 0.777,
    0.784, 0.792, 0.800, 0.808, 0.817, 0.826, 0.836, 0.846, 0.858, 0.870,
    0.884, 0.901, 0.921, 0.950,
]


def _z_d_lookup(ratio: float) -> float:
    """``z_d(find(spot_edge < ratio, 1, 'last'))`` -- the last index where
    ``spot_edge`` is strictly less than ``ratio``. Preserves ``0757`` (an
    unquoted literal 757, a missing-decimal-point typo already documented for
    v3.1.4 at ``calculate_reject_unified.m:54``) verbatim."""
    idx = [i for i, v in enumerate(_SPOT_EDGE) if v < ratio]
    return _Z_D[idx[-1]]


def _edge_0_lookup(part_z: float) -> float:
    """``edge_0(find(z_d <= part_z, 1, 'last'))``."""
    idx = [i for i, v in enumerate(_Z_D) if v <= part_z]
    return _EDGE_0[idx[-1]]
