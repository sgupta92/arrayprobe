# SPDX-License-Identifier: BSD-3-Clause
"""Reject helpers both UIOOPS engines share: RejectConfig, mask_start_end, _vertical_split."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RejectConfig:
    """The six thresholds ``calculate_reject_unified.m:71-77`` assigns itself.

    Seven *assignments*, six *thresholds*: ``:74`` sets
    ``handles.bits_per_slice = n_size(2)``, which is the image width read off
    the data rather than a constant, so it is not a configurable threshold and
    is not a field here.

    Every one of these is written into ``handles`` at the **top of the
    function**, unconditionally, overwriting whatever the caller had set.  So in
    stock UIOOPS they are constants with the values below, and a run script that
    sets ``handles.shadowed_area`` has no effect whatsoever.

    Exposing them as a frozen dataclass (thresholds-as-data) is a
    possible later step.

    **It IS carried on the fidelity profile, and the history of that is the
    point.**  An earlier reading held that it is "emphatically *not* a
    :class:`~arrayprobe.profiles.FidelityProfile` field -- the two MATLAB trees
    agree on every value here, so there is no divergence to name."  That was
    measured wrong 2026-08-28: the tree that actually produced the archived
    ORACLES products carries three different values (``rej_hollow=0``,
    ``max_edge_img_ar=4``, ``max_comp_img_ar=4``), and because nothing wired
    them to the profile, every ORACLES file had been running on stock thresholds
    and losing ~40 % of the particles the archive keeps in the used bins.  The
    profile carries ``ORACLES_PRODUCTION_REJECT_CONFIG``.

    The reason the error survived so long is worth keeping with the code: the
    claim was checked against a near-clear-air file on which those thresholds
    can barely fire.  An output-pinned claim is only as strong as the file that
    pinned it.
    """

    #: ``:71``.  Reject a zero-area particle as ``'z'`` rather than passing it
    #: through as ``'0'``.
    rej_zero_area: bool = True

    #: ``:72``.  Reject a particle that goes dark and lights up again.  Also
    #: gates the (dead) vertical-split re-check at :245, which requires this to
    #: be *False* -- so the two split tests are mutually exclusive by
    #: construction and only the first can ever fire.
    rej_split: bool = True

    #: ``:73``.  Run the Korolev hollow analysis at all.
    rej_hollow: bool = True

    #: ``:75``.  Minimum percent of the bounding rectangle that must be
    #: shadowed; below it the particle is rejected ``'p'``.
    shadowed_area: float = 25

    #: ``:76``.  Aspect-ratio ceiling for a particle **touching the array edge**
    #: (reject ``'t'``).  The netCDF description at ``imgProc_sm.m:325-329``
    #: swaps this with the next one.
    max_edge_img_ar: float = 6

    #: ``:77``.  Aspect-ratio ceiling for a fully-contained particle, applied in
    #: both directions -- above it, or below its reciprocal, reject ``'a'``.
    #: The reciprocal arm is dated in the source: "Second critirion added on Dec
    #: 2nd, 2013 by Will for small aspect ratio" (:269).
    max_comp_img_ar: float = 5


DEFAULT_REJECT_CONFIG = RejectConfig()
"""The stock v3.1.4 thresholds -- and the named ORACLES variant tree's, whose
``calculate_reject_unified.m`` is byte-identical to stock. ``arrayprobe.reject`` re-exports
this object."""

ORACLES_PRODUCTION_REJECT_CONFIG = RejectConfig(
    rej_hollow=False,
    max_edge_img_ar=4,
    max_comp_img_ar=4,
)
"""The ORACLES fork's dated reject edits, the ORACLES-variant ``calculate_reject_unified.m:73-77``
(``rej_hollow`` 1->0, ``max_edge_img_ar`` 6->4, ``max_comp_img_ar`` 5->4). Shared by both
engines (``ORACLES_PRODUCTION`` and ``ORACLES_PRODUCTION_V35``); ``arrayprobe.reject``
re-exports this object with the full provenance."""


def mask_start_end(end_mask: int, start_mask: int, shadow_row, bits_per_slice: int) -> np.ndarray:
    """``:683-702`` -- blank everything outside ``[start_mask, end_mask]``.

    Source: ``calculate_reject_unified.m`` (UIOOPS v3.1.4), ``mask_start_end`` from ``:683``; bare
    line references here are into that file.

    Returns the row's **lit** diodes (``True`` = lit = a hole) with everything
    outside the particle's own span forced to False, which is what the caller
    then counts and intersects.  MATLAB builds this as a char row of ``'0'``
    with the original characters pasted back into the window.

    Two MATLAB mechanics folded into that boolean array:

    * ``result`` starts as the numeric scalar ``0`` and ``result(1:n) = '0'``
      assigns the *code* 48 into a double array, so ``result`` is numeric until
      ``char()`` converts it back at :701.  Round-trips exactly; no effect.
    * When ``end_mask > bits_per_slice`` -- which happens in
      :func:`is_it_hollow_sidescan`, where ``bits_per_slice`` is capped at 32
      but the scan runs the full slice count -- MATLAB **auto-extends**
      ``result`` and pads the gap with numeric ``0``, i.e. NUL characters,
      not ``'0'``.  Harmless: NUL is not ``'1'`` so the hole count skips it, and
      the packers only ever read the first ``bits_per_slice`` entries.  False
      is the faithful boolean for both.

    The ``start_mask == 0 & end_mask == 0`` arm at :687 returns the row
    unmasked.  Unreachable: every call site guards on ``n_lite > 0``, and a
    non-empty slice has positions of at least 1.
    """
    shadow_row = np.asarray(shadow_row, dtype=bool)
    if start_mask == 0 and end_mask == 0:
        return ~shadow_row
    result = np.zeros(max(bits_per_slice, end_mask), dtype=bool)
    window = slice(start_mask - 1, end_mask)
    result[window] = ~shadow_row[window]
    return result


def _vertical_split(shadow) -> np.ndarray:
    """``:138-142`` -- the accumulator behind the (dead) second split test.

    MATLAB writes ``vertical_split = vertical_split & image_buffer(i,:)``, an
    ``&`` between **char** rows.  Both ``'0'`` (48) and ``'1'`` (49) are
    non-zero, so the result is ``true`` at every position from the second slice
    onward, and the ``scan_slice(vertical_split)`` at :239 then looks for the
    character ``'0'`` in a logical array -- comparing 1 against 48, which is
    false everywhere.  So for any multi-slice particle the scan reports an empty
    slice and the test at :245 can never fire.

    A single-slice particle escapes: the loop body runs once and takes the
    ``else`` arm, leaving ``vertical_split`` as the char row itself, which scans
    normally.

    Both cases return the row this port must scan for shadow.  For the
    multi-slice case that is an all-lit row -- nothing to find -- which is the
    faithful equivalent of "all logical true, compared against ``'0'``".
    """
    if shadow.shape[0] == 1:
        return shadow[0]
    return np.zeros(shadow.shape[1], dtype=bool)


@dataclass(frozen=True)
class SliceScan:
    """The three outputs of ``scan_slice`` (``:379``).  Positions are 1-based.

    Source: ``scan_slice`` in ``calculate_reject_unified.m:379-406`` (UIOOPS v3.1.4)."""

    min_pos_lite: int
    max_pos_lite: int
    n_lite: int


_SCAN_LOADED = False
_SCAN_HAVE_NUMBA = False


def _ensure_scan_numba_loaded() -> None:
    """JIT-decorate :func:`_scan_slice_kernel` once, on first use (numba stays lazy and optional).

    ``arrayprobe.reject._ensure_numba_loaded`` calls this and rebinds its own
    ``_scan_slice_kernel`` name to the result, so its sidescan kernel sees the dispatcher."""
    global _SCAN_LOADED, _SCAN_HAVE_NUMBA, _scan_slice_kernel
    if _SCAN_LOADED:
        return
    try:
        from numba import njit
    except ImportError:  # pragma: no cover - numba is an optional extra
        njit = None  # type: ignore[assignment]
    _SCAN_HAVE_NUMBA = njit is not None
    if _SCAN_HAVE_NUMBA:
        _scan_slice_kernel = njit(cache=True, boundscheck=True)(_scan_slice_kernel)
    _SCAN_LOADED = True


def scan_slice(shadow_row) -> SliceScan:
    """``calculate_reject_unified.m:379-406`` -- extent of the shadow in one slice.

    Returns the first and last shadowed diode (1-based) and how many are
    shadowed.  All three are 0 when the slice is empty.

    Note what this does *not* return: the shadowed diodes need not be
    contiguous, and the gap ``max_pos - min_pos + 1 - n_lite`` is precisely what
    the hollow scans call a hole.

    Dispatches to the numba kernel when available (:data:`HAVE_NUMBA`); numba is imported
    lazily on first call, never at module load.
    """
    arr = np.asarray(shadow_row, dtype=bool)
    _ensure_scan_numba_loaded()
    if _SCAN_HAVE_NUMBA:
        min_pos, max_pos, n_lite = _scan_slice_kernel(np.ascontiguousarray(arr))
    else:
        min_pos, max_pos, n_lite = _scan_slice_reference(arr)
    return SliceScan(int(min_pos), int(max_pos), int(n_lite))


def _scan_slice_reference(shadow_row):
    """Pure-Python body of :func:`scan_slice` -- the numba equivalence oracle."""
    lit_positions = np.flatnonzero(shadow_row) + 1
    n_lite = int(lit_positions.size)
    if n_lite == 0:
        return 0, 0, 0
    return int(lit_positions[0]), int(lit_positions[-1]), n_lite


def _scan_slice_kernel(shadow_row):
    lit_positions = np.flatnonzero(shadow_row)
    n_lite = lit_positions.size
    if n_lite == 0:
        return 0, 0, 0
    return lit_positions[0] + 1, lit_positions[-1] + 1, n_lite
