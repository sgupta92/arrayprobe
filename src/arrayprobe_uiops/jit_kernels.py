# SPDX-License-Identifier: BSD-3-Clause
"""S3's opt-in accelerated kernels for the v3.5 engine --
``imgproc_sm_v35(..., jit=True)``.

**Space: the port.** Every function here returns the same value as the one it
replaces, bit for bit, so a run with ``jit=True`` writes the same bytes as one
without (``tests/test_v35_imgproc_jit_identity.py`` runs both and compares the
files). It is opt-in and defaults off; numba is imported only when a caller
asks for it, never by ``import arrayprobe_uiops`` (same posture as
:mod:`arrayprobe.jit_kernels`).

**``arrayprobe/jit_kernels.py`` is the pattern, not the answer copied.** One should
not assume the v3.1.4 kernel list (``dec2bin_concat``,
``particle_perimeter``, ``cgal_min_r``) transfers as a set, because v3.5's
measurement loop (:func:`arrayprobe_uiops.measure.measure_record`) is not
v3.1.4's: it calls a v3.5-only ``cgal_min_r_v35`` (a different function, with
a ``tas_ratio`` input and a 3-output centre return -- see
:mod:`arrayprobe_uiops.min_circle`), and its hottest single cost center measured
below turned out to be ``calculate_reject_unified``, which is not on v3.1.4's
list at all. Measured on a real v3.5 CIP production pass (naming
the kernels with numbers), 50 records / 3,085 particles of
``_decoded/cip160906/sea_s1.CIP.cdf`` under the real production call
(``iRectEllipse=0, iCalcAllDiodeStats=0, iQC=0, iNewHabit=0, tas_ratio=None``
-- ``_decoded/cip160906/v35_prod/proc.sea_s1.CIP.nc.call``), cProfile
cumulative time (instrumented, so useful for ranking, not for absolute
wall-clock proportions):

============================================  =======  ============
function                                       calls    cumulative s
============================================  =======  ============
``calculate_reject_unified`` (v35 reject.py)     3,085         7.367
``dec2bin_concat`` (matlab_compat.py)            9,255         5.874
``cgal_min_r_v35`` (v35 min_circle.py)           3,085         4.124
``particle_perimeter`` (arrayprobe, shared)      3,085   3.050 (3.043 self)
============================================  =======  ============

Two of these are ported here; two are not, and this module says why for each:

``dec2bin_concat``
    All 9,255 calls measured above trace to :mod:`arrayprobe_uiops.imgproc`'s
    own three call sites (the framing unpack, once per particle, plus the two
    housekeeping unpacks inside ``_particle_time_dmt_v35``, CIP/PIP timing
    only) -- none come from ``reject.py``. It is the exact same
    ``arrayprobe.matlab_compat.dec2bin_concat`` v3.1.4 accelerates (imported
    by name in ``imgproc.py``, never re-translated for v3.5), so v3.1.4's
    already-proven, already-tested fused-NumPy kernel
    (:func:`arrayprobe.jit_kernels.dec2bin_concat`, no numba needed) is
    reused directly below rather than copied -- one proof of exactness, not
    two.
``particle_perimeter``
    Also the exact same ``arrayprobe.particle_perimeter.particle_perimeter``
    v3.1.4 accelerates (``measure.py``'s own module docstring: "the
    byte-identical ``arrayprobe.particle_perimeter``; this module
    re-translates none of them"). v3.1.4's compiled numba kernel
    (:func:`arrayprobe.jit_kernels.JitKernels.particle_perimeter`) is reused
    directly for the same reason. *Reaching* the call, which is inside
    :func:`arrayprobe_uiops.measure.measure_record` rather than in
    :mod:`arrayprobe_uiops.imgproc` itself, is the harder part -- see
    ``imgproc.py``'s ``_patched_measure_perimeter``.

``cgal_min_r_v35`` -- **still left unported, measured, not guessed.** v3.5's
    call is not v3.1.4's ``cgal_min_r``: it takes ``tas_ratio`` and returns a
    3-tuple ``(diameter, ctx, cty)`` (the enclosing circle's centre, new in
    v3.5), computed by scaling one axis in exact ``Fraction`` arithmetic
    before Welzl's algorithm (:mod:`arrayprobe_uiops.min_circle`). v3.1.4's
    ``_welzl_kernel`` neither takes a scale nor returns a centre, so it is
    not a drop-in; an exact numba equivalent would be new kernel code (a
    homogeneous-coordinate Welzl pass that also carries the winning centre
    through every branch), not a reuse, and proving *that* exact needs more
    fuzz-testing than one session's time-box affords carefully. Real CIP
    production always runs ``tas_ratio == 1.0`` exactly (``tas_ratio=None``
    in the call above; probetype 1 never reads ``varargin{3}``'s series --
    see ``imgproc_sm_v35``'s own probetype guard), which would let such a
    kernel degenerate to v3.1.4's existing int64 Welzl pass for the radius
    and add only the centre bookkeeping -- still the next highest-value
    target, still not attempted.

``calculate_reject_unified`` -- **ported 2026-09-18**,
    the session that measured it
    as the single largest cost centre above. ``arrayprobe/jit_kernels.py``'s
    docstring called reject's hot kernels "already numba-compiled in
    reject.py" -- true only for ``is_it_hollow_sidescan`` there (v3.1.4's
    *other* hollow scan), and not reached by the v3.5 engine at all: v3.5's
    ``calculate_reject_unified`` (this module's own, `arrayprobe_uiops/reject.py`)
    has its own rewritten ``is_it_hollow`` (no middle-third restriction, a
    direct ``bitand`` instead of a pack/bitshift reconstruction) that never
    called anything from v3.1.4's ``reject.py`` except the shared
    ``scan_slice`` -- see that module's corrected docstring for the full
    accounting.

    The real cost was never "interpreted Python" so much as **per-slice
    dispatch overhead**: ``scan_slice`` already dispatches to a numba kernel
    whenever numba is importable (unconditionally, not opt-in -- see
    ``reject.HAVE_NUMBA`` in the earlier translation), but it still pays a Python-level call,
    an ``np.asarray``/``ascontiguousarray`` conversion and a
    :class:`~arrayprobe_uiops.reject_core.SliceScan` construction on *every one* of the
    47,198 calls the profile counted. The fix here fuses each whole
    per-particle loop into one compiled call instead of one call per slice:

    ``reject_scan_pass``
        ``calculate_reject_unified``'s own per-slice pass (longest_y, touch,
        the bottom/top edge extents, max/min width, area, the split
        detector) -- every particle takes this path, and the real production
        config (``ORACLES_PRODUCTION_V35``, ``rej_hollow=False``) means this
        pass is *all* of what the profile above measured; the hollow branch
        below never ran in that profile.
    ``is_it_hollow``
        v3.5's rewritten hollow scan -- not exercised by the production
        config above (``rej_hollow=False``), but reachable from
        ``STOCK_V35_REJECT_CONFIG`` and any fork with ``rej_hollow=True``,
        and explicitly the function the porting brief named for its
        preserved defects (the ``ihollow``-overwrite at ``reject.py:364-365``,
        the discarded ``hollow_status_side1`` at :367-375, the array-truthiness
        ``bufandold.all()`` defect inside ``is_it_hollow`` itself). Proven
        identical on real CIP image content under a ``rej_hollow=True``
        variant of the production config, since production itself never
        takes this branch.

    Left on the Python path, and why: the Korolev lookup
    (``_z_d_lookup``/``_edge_0_lookup``) and the habit-dependent
    ``area_hole_ratio`` checks run once per particle, not once per slice --
    not measured hot, and numba's limited string handling would make the
    ``habit`` comparisons (``habit == "i"``, ``habit == "h"``) more trouble
    than the near-zero benefit justifies. ``_vertical_split``'s one
    ``scan_slice`` call (once per particle, not per slice) is likewise
    left calling the existing shared dispatcher unchanged.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["V35JitKernels", "load"]

#: Guards the njit-decoration in V35JitKernels.__init__ against running twice
#: in one process -- see that method's docstring comment for why a second
#: construction is a real, reachable case, not hypothetical.
_KERNELS_COMPILED = False


# --------------------------------------------------------------------------
# Pure-Python kernel bodies for calculate_reject_unified's two hot loops.
# numba compiles them on first use, in load() below -- see that function's
# docstring for why the leaf kernels (_scan_row_kernel, _mask_start_end_kernel)
# must be compiled, and their MODULE GLOBALS rebound to the compiled
# Dispatcher, before the composite kernels that call them by name are
# themselves compiled (mirrors arrayprobe.reject._ensure_numba_loaded's own
# ordering, which the same constraint applies to).
# --------------------------------------------------------------------------


def _scan_row_kernel(row: Any) -> Any:
    """Same value as ``arrayprobe_uiops.reject_core.scan_slice`` on one boolean row:
    ``(min_pos, max_pos, n_lite)``, 1-based, ``(0, 0, 0)`` when empty. A
    separate copy rather than an import, because the shared function's own
    numba dispatch is rebound as a module global the first time *it* runs
    (``reject._ensure_numba_loaded`` in the earlier translation) -- importing that name here
    would race whichever module loads numba first. Proven equal to the
    shared dispatcher by fuzz in ``test_v35_reject_jit_identity.py``."""
    n = row.shape[0]
    min_pos = 0
    max_pos = 0
    n_lite = 0
    for k in range(n):
        if row[k]:
            if min_pos == 0:
                min_pos = k + 1
            max_pos = k + 1
            n_lite += 1
    return min_pos, max_pos, n_lite


def _mask_start_end_kernel(end_mask: Any, start_mask: Any, row: Any, bits_per_slice: Any) -> Any:
    """Same value as ``arrayprobe_uiops.reject_core.mask_start_end`` (v3.5's
    ``is_it_hollow`` never calls the ``end_mask > bits_per_slice``
    auto-extend arm -- see that function's docstring -- but the ``max()`` is
    kept anyway, verbatim, rather than assumed away)."""
    if start_mask == 0 and end_mask == 0:
        return ~row
    size = bits_per_slice if bits_per_slice > end_mask else end_mask
    result = np.zeros(size, dtype=np.bool_)
    result[start_mask - 1:end_mask] = ~row[start_mask - 1:end_mask]
    return result


def _reject_scan_pass_kernel(shadow: Any, n_slices: Any, bits_per_slice: Any,
                             rej_split: Any) -> Any:
    """``calculate_reject_unified``'s own per-slice pass (v3.5 reject.py,
    the loop immediately before ``center_in`` is computed) -- every particle
    takes this path, fused into one compiled call instead of ``n_slices``
    separate ``scan_slice`` dispatches. ``met_image``/``ndrops`` are
    loop-local bookkeeping the caller never reads back, so they are not
    returned (matching what the Python body itself discards)."""
    longest_y = 0
    touch = 0
    bottom_min_x = -1
    bottom_max_x = -1
    top_min_x = -1
    top_max_x = -1
    max_width = 1
    min_width = bits_per_slice
    min_length = -1
    max_length = -1
    total_area = 0
    met_image = 0
    ndrops = 0
    split = 0

    for i in range(1, n_slices + 1):
        min_pos, max_pos, n_lite = _scan_row_kernel(shadow[i - 1])
        if n_lite > longest_y:
            longest_y = n_lite

        if n_lite > 0:
            if touch == 0:
                if max_pos == bits_per_slice or min_pos == 1:
                    touch = 1
            if min_pos == 1:
                if bottom_min_x == -1:
                    bottom_min_x = i
                if bottom_max_x < i:
                    bottom_max_x = i
            if max_pos == bits_per_slice:
                if top_min_x == -1:
                    top_min_x = i
                if top_max_x < i:
                    top_max_x = i
            if max_pos > max_width:
                max_width = max_pos
            if min_pos < min_width:
                min_width = min_pos
            if min_length == -1:
                min_length = i
                max_length = i
            else:
                max_length = i
            total_area += n_lite

        if met_image == 0 and n_lite > 0:
            met_image = 1
            ndrops += 1
            if ndrops > 1 and rej_split:
                split = 1
        elif met_image == 1 and n_lite == 0:
            met_image = 0

    return (longest_y, touch, bottom_min_x, bottom_max_x, top_min_x, top_max_x,
            max_width, min_width, min_length, max_length, total_area, split)


def _is_it_hollow_kernel(shadow: Any, slices: Any) -> Any:
    """v3.5's ``is_it_hollow`` (``arrayprobe_uiops/reject.py``), fused into one
    compiled call. Line-for-line translation of that function's body --
    including the ``possibly_hollow``/``status`` state machine and the
    PRESERVED DEFECT documented there (MATLAB's ``if bufandold > 0`` on an
    array means "every element nonzero", replicated with ``.all()``, not the
    evidently-intended ``.any()``).

    ``old``'s ``None`` sentinel becomes a same-shape placeholder array that is
    never read before being freshly assigned -- the same invariant the
    Python body's own comment (and ``reject._is_it_hollow_sidescan_kernel`` in the earlier
    translation, the precedent this mirrors) relies on: every branch that reads ``old``
    is reached only under ``possibly_hollow == 1``, and the only two sites
    that set ``possibly_hollow = 1`` assign ``old`` in the same breath.
    ``old`` is always exactly ``bits_per_slice`` wide here (unlike the
    sidescan kernel's capped-at-32 caller, v3.5's ``bits_per_slice`` is the
    row's own true width, so ``mask_start_end``'s ``end_mask`` -- itself a
    valid column position -- can never exceed it), so the placeholder and
    every real assignment share one fixed shape per call, which is what lets
    numba type ``old`` as a stable loop-carried variable.
    """
    bits_per_slice = shadow.shape[1]

    start_img = 0
    end_img = 0
    for i in range(1, slices + 1):
        zero_amt = shadow[i - 1].sum()  # counts LIT pixels -- MATLAB's own naming, preserved
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
    possibly_hollow = 0
    old = np.zeros(bits_per_slice, dtype=np.bool_)  # placeholder; see docstring

    for i in range(start_img, end_img + 1):
        row = shadow[i - 1]
        min_pos, max_pos, n_lite = _scan_row_kernel(row)
        num_empty = max_pos - min_pos + 1 - n_lite

        # v3.5 removed v3.1.4's middle-third restriction here -- no i/span
        # guard, unlike arrayprobe.reject.is_it_hollow. Preserved by omission.
        if num_empty > max_hole_diameter:
            max_hole_diameter = num_empty
            edge_at_max_hole = max_pos - min_pos + 1

        lit_row = ~row

        if possibly_hollow == 1 and status == 0:
            if n_lite > 0 and n_lite != max_pos - min_pos + 1:
                newandold = lit_row & old
                if not newandold.any():
                    status = 1
                else:
                    old = _mask_start_end_kernel(max_pos, min_pos, row, bits_per_slice)
            elif n_lite > 0:
                bufandold = lit_row & old
                hole_size = old.sum()
                cover_size = bufandold.sum()
                # PRESERVED DEFECT: see this function's own docstring.
                if bufandold.shape[0] > 0 and bufandold.all():
                    if cover_size <= 0.65 * hole_size:
                        status = 1
                    possibly_hollow = 0
                elif i > 1:
                    status = 1
                else:
                    possibly_hollow = 0
            else:
                possibly_hollow = 0
        elif status == 0:
            if n_lite > 0 and n_lite != max_pos - min_pos + 1:
                old = _mask_start_end_kernel(max_pos, min_pos, row, bits_per_slice)
                possibly_hollow = 1

    return status, edge_at_max_hole, max_hole_diameter


class V35JitKernels:
    """Wraps :mod:`arrayprobe.jit_kernels`'s already-compiled, already-proven
    kernels for the two v3.5 call sites that use the identical underlying
    function (``particle_perimeter``, ``dec2bin_concat``), plus this
    module's own compiled kernels for ``calculate_reject_unified``'s two hot
    loops, which have no earlier kernel to reuse -- v3.5's ``arrayprobe_uiops.reject`` is a
    from-scratch translation of a changed MATLAB function (see its module
    docstring), not the file the earlier translation accelerates."""

    def __init__(self, v314_kernels: Any, njit: Any) -> None:
        self.particle_perimeter = v314_kernels.particle_perimeter
        self.dec2bin_concat = v314_kernels.dec2bin_concat

        # Leaf kernels first, and REBOUND AS MODULE GLOBALS (not just local
        # names) before the composite kernels below are decorated -- numba
        # resolves a called name against the function's __globals__ at
        # compile time (lazy, on first actual invocation), so
        # _reject_scan_pass_kernel/_is_it_hollow_kernel must see the
        # already-compiled Dispatcher, not the plain Python function, when
        # numba gets around to typing their bodies. Mirrors
        # arrayprobe.reject._ensure_numba_loaded's own ordering exactly.
        #
        # IDEMPOTENT, unlike a naive rebind: _LOADED normally makes this
        # class a per-process singleton, but a caller can legitimately reset
        # _LOADED (this module's own tests do, to exercise the "numba
        # missing" error path) and construct a second instance in the same
        # process. numba refuses to re-`njit` a function that is already a
        # compiled Dispatcher (measured: raises TypeError), so the module
        # globals are decorated at most once per process, guarded by
        # _KERNELS_COMPILED -- exactly the boolean-flag shape
        # arrayprobe.reject._ensure_numba_loaded uses for the same reason.
        global _scan_row_kernel, _mask_start_end_kernel
        global _reject_scan_pass_kernel, _is_it_hollow_kernel
        global _KERNELS_COMPILED
        if not _KERNELS_COMPILED:
            opts = {"cache": True, "boundscheck": True}  # fastmath stays OFF (correctness)
            _scan_row_kernel = njit(**opts)(_scan_row_kernel)
            _mask_start_end_kernel = njit(**opts)(_mask_start_end_kernel)
            _reject_scan_pass_kernel = njit(**opts)(_reject_scan_pass_kernel)
            _is_it_hollow_kernel = njit(**opts)(_is_it_hollow_kernel)
            _KERNELS_COMPILED = True
        self._scan_row = _scan_row_kernel  # exposed for direct fuzzing, mirrors
                                            # arrayprobe.jit_kernels.JitKernels's
                                            # own _perimeter/_hull/_welzl attributes
        self._mask_start_end = _mask_start_end_kernel
        self._scan_pass = _reject_scan_pass_kernel
        self._hollow = _is_it_hollow_kernel

    def reject_scan_pass(self, shadow: Any, n_slices: Any, bits_per_slice: Any,
                         rej_split: Any) -> Any:
        """Drop-in for ``calculate_reject_unified``'s own per-slice loop.
        Returns ``(longest_y, touch, bottom_min_x, bottom_max_x, top_min_x,
        top_max_x, max_width, min_width, min_length, max_length, total_area,
        split)`` -- every local the loop computes that the rest of the
        function reads afterward."""
        arr = np.ascontiguousarray(np.asarray(shadow, dtype=bool))
        result = self._scan_pass(arr, int(n_slices), int(bits_per_slice), bool(rej_split))
        return tuple(int(v) for v in result)

    def is_it_hollow(self, shadow: Any, slices: Any) -> Any:
        """Drop-in for :func:`arrayprobe_uiops.reject.is_it_hollow`. Returns
        ``(status, edge_at_max_hole, max_hole_diameter)``."""
        arr = np.ascontiguousarray(np.asarray(shadow, dtype=bool))
        status, edge_at_max_hole, max_hole_diameter = self._hollow(arr, int(slices))
        return int(status), int(edge_at_max_hole), int(max_hole_diameter)


_LOADED: V35JitKernels | None = None


def load() -> V35JitKernels:
    """Import numba (via :mod:`arrayprobe.jit_kernels`) and compile this
    module's own kernels, once per process. Raises with a v3.5-specific
    message if numba is absent; the default (``jit=False``) path -- for
    ``imgproc_sm_v35``, ``calculate_reject_unified`` and ``is_it_hollow``
    alike -- never calls this."""
    global _LOADED
    if _LOADED is None:
        from arrayprobe import jit_kernels as _v314

        try:
            v314_kernels = _v314.load()
            from numba import njit
        except ImportError as exc:
            raise ModuleNotFoundError(
                "imgproc_sm_v35(jit=True) / calculate_reject_unified(jit=True) / "
                "is_it_hollow(jit=True) need numba, an optional extra: "
                'pip install "arrayprobe[jit]" ("arrayprobe[pinned]" installs the tested pin). '
                "The default "
                "(jit=False) writes the same bytes without it."
            ) from exc
        _LOADED = V35JitKernels(v314_kernels, njit)
    return _LOADED
