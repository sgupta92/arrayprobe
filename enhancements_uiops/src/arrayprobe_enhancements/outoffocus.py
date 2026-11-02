# SPDX-License-Identifier: BSD-3-Clause
"""A12 -- the Korolev (2007) out-of-focus size correction, applied.

``calculate_reject_unified.m:330-331`` computes, inside the hollow block, a depth estimate
``part_z`` and a size factor ``size_factor`` for a drop whose shadow shows a Poisson spot;
``sizeDist.m:793`` -- ``particle_diameter_minR .* size_factor`` -- would apply it and is dead code
in every tree.  Two things stand between the port's output and a
corrected diameter, and this module does both, opt-in (user decisions #4 and #5, 2026-08-28):

1. **The diagnostics are only computed when the hollow block runs**, and the ORACLES production
   configuration skips it (``rej_hollow = 0``), so every production proc file carries
   ``size_factor = 1``.  :func:`hollow_diagnostics` re-runs the port's own
   ``calculate_reject_unified`` on each particle's reconstructed image with the hollow block
   *enabled* and returns ``part_z``/``size_factor``/``is_hollow`` -- **without touching the
   accept/reject decision**, which stays the production one.
2. **The factor is applied**: :func:`correct_diameter` divides, ``diam / size_factor``, with
   ``size_factor == 1`` leaving the diameter untouched by construction.  "Corrected", not
   "reconstructed".

**The direction (2026-09-15).**  Until this date the module *multiplied* --
``sizeDist.m:793``'s dead line, ``particle_diameter_minR .* size_factor``, transcribed -- and
that runs the correction **the wrong way**.  Korolev (2007, JTECH 24, §2 p. 377, Fig. 1) retrieves
the true diameter as ``D_0 = D_m / eta(Z_d)`` with ``eta = D_edge/D_0 >= 1`` for every ``Z_d``
(Fig. 3, p. 378; Appendix B's table, p. 388): an out-of-focus drop images *larger* than it is,
so the correction must make it *smaller*.  ``size_factor`` is that ``D_edge/D_0`` column
(``calculate_reject_unified.m:21`` table, looked up at ``:331``), so the true diameter is the
measured one **divided** by it.  v3.5's live line agrees: ``imgProc_sm.m:1276`` (v3.5)
``images.minR(kk) = images.minR(kk)/images.sf(kk)``, ported at ``arrayprobe_uiops/measure.py:241``.
``direction="korolev"`` (default) divides; ``direction="dead_line_v314"`` multiplies and exists
only so the 2026-08-29 / 2026-09-09 A/Bs that shipped with the multiply stay reproducible --
their numbers were made in the wrong direction (``CORRECTIONS.md`` A12 part).

**The area** (:func:`correct_area`).  Korolev (2007) states **no** area transform.  The
reconstruction replaces the diffraction image by a sphere of diameter ``D_0`` (§3, Eqs. 1-2:
the image's shaded area is itself a diffraction quantity, ``D_area^2 = D_edge^2 - D_spot^2``;
§9e: spherical particles only), so ``area_mode="sphere"`` (default) writes that sphere's
cross-section ``pi/4 * D_0^2`` for every corrected particle.  That is the reconstruction's own
consequence, not a quoted equation.  ``area_mode="keep"`` leaves the ring's shaded area, which
contradicts the reconstruction but changes fewer numbers.  Which one is "proper" is an open
question, so every result carries both mode values
(:class:`OutOfFocusResult`).  Perimeter is not touched in either mode.

Validation.  Step 1 has a real oracle: on a proc written under the *stock* configuration (the
hollow block ran), the recomputed ``part_z``/``size_factor`` must equal the stored columns
bit-for-bit for every particle -- the port's reject stage is Octave-validated, so this checks
the reconstruction-and-rerun path, not the arithmetic.  Step 2 is arithmetic pinned by tests.
The hollow-block outputs also carry the missing decimal in spot_edge and the swapped hole variables (``spot_edge`` typo, hole/edge swap), which are
inert on production output for the same reason and become live here; they are applied by the
caller from their own modules, never silently.

**v3.5** (``engine="3.5"``, 2026-09-14). ``calculate_reject_unified.m`` (v3.5) forces
``handles.rej_hollow = 1`` unconditionally at its own top (line 62 of the vendored source,
opened directly), the same way it hardcodes ``shadowed_area``/``max_edge_img_ar``/
``max_comp_img_ar`` (``arrayprobe_uiops/measure.py:57-60``'s ``STOCK_V35_REJECT_CONFIG``
already carries ``rej_hollow=True``) -- so under the *stock* v3.5 driver, unlike v3.1.4's
ORACLES production config (``rej_hollow=0``), the hollow block already runs on every particle
and ``_with_hollow``'s override is a no-op there. The diagnostic still earns its place: a
v3.5 run under a non-stock config with ``rej_hollow=False`` would skip the block for real, and
``hollow_diagnostics(engine="3.5")`` re-derives it the same way the v3.1.4 path does.

**The buffer contract (U2, resolved by reading, not assumed).** v3.5's own driver
(``arrayprobe_uiops/measure.py:178`` -- ``codes = _ascii(shadow)``) feeds
``calculate_reject_unified`` an ASCII-coded ``int64`` array (48/49); this module's
``reconstruct_particle_image`` (``arrayprobe/render.py``) returns a **boolean** array instead.
Both are accepted forms of the same input: ``arrayprobe_uiops.reject.calculate_reject_unified``
calls ``shadow_mask(image_buffer)`` first (``reject.py:220``), and ``arrayprobe.particle.
shadow_mask`` canonicalises a boolean array as-is and an ASCII-int array (max > 1) via
``== ord('0')`` to the identical boolean result (``particle.py:63-70``). So no transform is
needed between the two call sites; the reconstructed boolean image is fed straight through,
exactly as the v3.1.4 path already does.

**A known, narrow gap, not silently absorbed.** ``measure_record`` (``measure.py:210-247``)
calls ``calculate_reject_unified`` with the habit *before* the ``center_in == 0`` -> ``'C'``
reassignment (``:246-247``, after the reject call returns); this module reads ``holroyd_habit``
from the proc file, which stores the *post*-reassignment value. The two differ only for a
particle with ``center_in == 0`` whose pre-reassignment habit was ``'i'``/``'h'``/``'s'`` *and*
that reached the Korolev branch's area-hole-ratio downgrade in the same call -- the recomputed
``reject_status`` would then read ``'C'`` instead of the true habit at that one branch
(``calculate_reject_unified.m:291-299``). Not hit by the dense-flight equivalence test below;
flagged here rather than fixed, because fixing it would mean this module tracking a proc column
``holroyd_habit`` does not carry.
"""

from __future__ import annotations

import dataclasses
import time
from typing import NamedTuple

import numpy as np
from arrayprobe_uiops.reject_core import RejectConfig

__all__ = ["hollow_diagnostics", "correct_diameter", "correct_area", "apply_outoffocus",
           "OutOfFocusResult", "DIRECTIONS", "AREA_MODES"]

_ENGINES = ("3.1.4", "3.5")


def _v314_calculate_reject_unified():
    """The v3.1.4 engine's ``calculate_reject_unified``, imported only on the ``engine="3.1.4"``
    path, so this module imports and runs on v3.5 without the earlier translation."""
    try:
        from arrayprobe.reject import calculate_reject_unified
    except ImportError as exc:
        raise ImportError(
            "outoffocus engine='3.1.4' needs the v3.1.4 validation engine (arrayprobe.reject), "
            "which this distribution omits; pass engine='3.5'") from exc
    return calculate_reject_unified

#: ``"korolev"``: ``D_0 = D_m / size_factor`` (Korolev 2007 §2 p. 377; v3.5 ``imgProc_sm.m:1276``).
#: ``"dead_line_v314"``: ``D_m * size_factor`` (``sizeDist.m:793``, dead, the wrong direction).
DIRECTIONS = ("korolev", "dead_line_v314")

#: ``"sphere"``: corrected particles get ``pi/4 * D_0^2``; ``"keep"``: the image's shaded area.
AREA_MODES = ("sphere", "keep")


class OutOfFocusResult(NamedTuple):
    """What :func:`apply_outoffocus` returns -- labelled with both mode values, because a
    corrected diameter or area means nothing without them."""

    indices: np.ndarray
    corrected_diam: np.ndarray
    size_factor: np.ndarray
    part_z: np.ndarray
    is_hollow: np.ndarray
    corrected_area: np.ndarray
    direction: str
    area_mode: str


def _with_hollow(config: RejectConfig) -> RejectConfig:
    return dataclasses.replace(config, rej_hollow=True)


def hollow_diagnostics(image_ds, proc_ds, indices, *, config: RejectConfig, engine: str = "3.1.4",
                      jobs: int = 1, result_timeout_s: float = 3600.0):
    """``part_z``, ``size_factor``, ``is_hollow`` for ``indices``, hollow block enabled.

    ``config`` is the reject configuration the proc was made with (for ORACLES products,
    ``ORACLES_PRODUCTION_REJECT_CONFIG``; for v3.5, ``STOCK_V35_REJECT_CONFIG``); only
    ``rej_hollow`` is overridden.  The returned arrays are what ``calculate_reject_unified.m``
    would have written had the block run; the proc's own reject code is not consulted or
    changed.

    ``engine="3.1.4"`` (default, unchanged since before this parameter existed) uses
    :func:`arrayprobe.reject.calculate_reject_unified`, the three-argument v3.1.4 form, imported
    only on that path, so this module imports and runs on v3.5 without the earlier translation.
    ``engine="3.5"`` uses :func:`arrayprobe_uiops.reject.calculate_reject_unified`, the four-argument
    v3.5 form -- ``ihollow`` comes from the proc's own ``image_hollow`` column, which
    ``arrayprobe_uiops.reject``'s ``is_hollow = int(ihollow)`` (line 364) means equals exactly
    the value the original run passed in, so replaying it here reproduces the same call.

    ``jobs`` (default 1, opt-in) above 1 runs the per-particle reject calls in a
    :class:`concurrent.futures.ProcessPoolExecutor` of that many workers. The caller's indices
    are cut into contiguous blocks only where the parent record changes, the images are
    reconstructed here exactly as the serial path does, and the blocks' results are joined in
    submission order, so the returned arrays equal the serial ones element for element.
    ``jobs=1`` runs the serial loop below, unchanged. All the blocks' results together are
    awaited at most ``result_timeout_s`` seconds; a worker that never answers raises
    :class:`TimeoutError` rather than waiting forever, and on that or any other error the pool's
    worker processes are terminated, so a wedged worker cannot hold the process at exit.
    """
    if engine not in _ENGINES:
        raise ValueError(f"unknown engine {engine!r}, expected one of {_ENGINES}")
    if int(jobs) != jobs or jobs < 1:
        raise ValueError(f"jobs must be a positive integer, got {jobs!r}")
    if jobs > 1 and len(indices) > 0:
        return _hollow_diagnostics_parallel(image_ds, proc_ds, indices, config=config,
                                            engine=engine, jobs=int(jobs),
                                            result_timeout_s=result_timeout_s)
    cfg = _with_hollow(config)
    habits = np.asarray(proc_ds.variables["holroyd_habit"][:]).astype(int)
    n = len(indices)
    part_z = np.empty(n)
    size_factor = np.empty(n)
    is_hollow = np.empty(n, dtype=np.int8)
    if engine == "3.5":
        from arrayprobe_uiops.reject import calculate_reject_unified as calculate_reject_unified_v35
        ihollow_col = np.asarray(proc_ds.variables["image_hollow"][:]).astype(int)
        images = _images_in_order(image_ds, proc_ds, indices)
        for k, (idx, img) in enumerate(zip(indices, images)):
            h = habits[idx]
            rv = calculate_reject_unified_v35(
                img, chr(h) if h else "0", int(ihollow_col[idx]), cfg)
            part_z[k] = rv.part_z
            size_factor[k] = rv.size_factor
            is_hollow[k] = int(rv.is_hollow)
        return part_z, size_factor, is_hollow
    calculate_reject_unified = _v314_calculate_reject_unified()
    images = _images_in_order(image_ds, proc_ds, indices)
    for k, (idx, img) in enumerate(zip(indices, images)):
        h = habits[idx]
        r = calculate_reject_unified(img, chr(h) if h else "0", cfg)
        part_z[k] = r.part_z
        size_factor[k] = r.size_factor
        is_hollow[k] = int(r.is_hollow)
    return part_z, size_factor, is_hollow


#: Blocks submitted per worker by :func:`_hollow_diagnostics_parallel`, so a slow block does
#: not leave the other workers idle at the end.
_BLOCKS_PER_JOB = 4


def _record_aligned_blocks(parents, n_blocks: int) -> list:
    """``(lo, hi)`` bounds cutting ``parents`` (in the caller's order) into about ``n_blocks``
    contiguous blocks, each cut placed only where the parent record changes, so no run of
    particles sharing a record is split across two blocks."""
    parents = np.asarray(parents).reshape(-1)
    n = len(parents)
    if n == 0:
        return []
    target = max(1, -(-n // max(1, n_blocks)))
    bounds = []
    lo = 0
    while lo < n:
        hi = min(n, lo + target)
        while hi < n and parents[hi] == parents[hi - 1]:
            hi += 1
        bounds.append((lo, hi))
        lo = hi
    return bounds


def _diagnose_block(images, habit_chars, ihollows, cfg, engine):
    """The serial loop's body over one block; run in a worker process by
    :func:`_hollow_diagnostics_parallel`. ``cfg`` already has the hollow block enabled."""
    n = len(images)
    part_z = np.empty(n)
    size_factor = np.empty(n)
    is_hollow = np.empty(n, dtype=np.int8)
    if engine == "3.5":
        from arrayprobe_uiops.reject import calculate_reject_unified as calculate_reject_unified_v35
        for k, (img, h, ih) in enumerate(zip(images, habit_chars, ihollows)):
            rv = calculate_reject_unified_v35(img, h, ih, cfg)
            part_z[k] = rv.part_z
            size_factor[k] = rv.size_factor
            is_hollow[k] = int(rv.is_hollow)
        return part_z, size_factor, is_hollow
    calculate_reject_unified = _v314_calculate_reject_unified()
    for k, (img, h) in enumerate(zip(images, habit_chars)):
        r = calculate_reject_unified(img, h, cfg)
        part_z[k] = r.part_z
        size_factor[k] = r.size_factor
        is_hollow[k] = int(r.is_hollow)
    return part_z, size_factor, is_hollow


def _terminate_pool(pool):
    """Stop a process pool on an error path without waiting for its running work.

    ``shutdown(wait=False)`` alone leaves a running worker alive, and the interpreter's exit hook
    then joins it, so a wedged worker would hang the process at exit. The workers are terminated
    first (``terminate_workers`` where the standard library has it, otherwise each process)."""
    terminate = getattr(pool, "terminate_workers", None)
    if terminate is not None:
        terminate()
    else:
        for proc in list((getattr(pool, "_processes", None) or {}).values()):
            if proc.is_alive():
                proc.terminate()
    pool.shutdown(wait=False, cancel_futures=True)


def _hollow_diagnostics_parallel(image_ds, proc_ds, indices, *, config, engine, jobs,
                                 result_timeout_s):
    """:func:`hollow_diagnostics` with ``jobs > 1``: record-aligned blocks in a process pool,
    joined in order. The images are reconstructed in this process (the datasets stay here);
    only the reject calls run in the workers."""
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    cfg = _with_hollow(config)
    idx = np.asarray(indices, dtype=np.int64).reshape(-1)
    habits = np.asarray(proc_ds.variables["holroyd_habit"][:]).astype(int)
    ihollow_col = (np.asarray(proc_ds.variables["image_hollow"][:]).astype(int)
                   if engine == "3.5" else None)
    columns = (np.asarray(proc_ds.variables["parent_rec_num"][:]),
               np.asarray(proc_ds.variables["position"][:]))
    parents = np.asarray(columns[0])[idx]
    blocks = _record_aligned_blocks(parents, jobs * _BLOCKS_PER_JOB)
    pool = ProcessPoolExecutor(max_workers=jobs)
    futures = []
    try:
        for lo, hi in blocks:
            sub = idx[lo:hi]
            images = _reconstruct_by_record(image_ds, proc_ds, sub, columns=columns)
            habit_chars = [chr(h) if h else "0" for h in (int(habits[i]) for i in sub)]
            ihollows = ([int(ihollow_col[i]) for i in sub] if ihollow_col is not None
                        else [0] * len(sub))
            futures.append(pool.submit(_diagnose_block, images, habit_chars, ihollows,
                                       cfg, engine))
        parts = []
        deadline = time.monotonic() + result_timeout_s
        for fut in futures:
            try:
                parts.append(fut.result(timeout=max(0.0, deadline - time.monotonic())))
            except FutureTimeout as exc:
                raise TimeoutError(
                    f"the out-of-focus worker blocks gave no result in {result_timeout_s} s"
                ) from exc
    except BaseException:
        for fut in futures:
            fut.cancel()
        _terminate_pool(pool)
        raise
    pool.shutdown(wait=True)
    part_z = np.concatenate([p[0] for p in parts])
    size_factor = np.concatenate([p[1] for p in parts])
    is_hollow = np.concatenate([p[2] for p in parts]).astype(np.int8, copy=False)
    return part_z, size_factor, is_hollow


#: Particles reconstructed per batch by :func:`_images_in_order`. Bounds the images held in
#: memory at once; a record split across two batches is read once per batch, which changes
#: the number of reads and nothing else.
_BATCH = 4096


def _images_in_order(image_ds, proc_ds, indices):
    """Yield the 2D-S-framed silhouette of each of ``indices``, in the caller's order.

    The images are those :func:`arrayprobe.render.reconstruct_particle_image` returns (its
    default ``probe``, as :func:`hollow_diagnostics` always called it), built in batches of
    :data:`_BATCH` by :func:`_reconstruct_by_record` with the two proc columns read once.
    """
    idx = np.asarray(indices, dtype=np.int64).reshape(-1)
    if len(idx) == 0:
        return
    columns = (np.asarray(proc_ds.variables["parent_rec_num"][:]),
               np.asarray(proc_ds.variables["position"][:]))
    for lo in range(0, len(idx), _BATCH):
        yield from _reconstruct_by_record(image_ds, proc_ds, idx[lo:lo + _BATCH],
                                          columns=columns)


def _reconstruct_by_record(image_ds, proc_ds, indices, *, probe: str = "2DS",
                           columns=None) -> list:
    """The silhouettes of ``indices``, in the caller's order, reading each parent record once.

    Byte-identical by construction to calling
    :func:`arrayprobe.render.reconstruct_particle_image` once per index: ``parent_rec_num`` and
    ``position`` are read as whole columns, the particles are visited grouped by parent
    record, and each record's ``data`` block is read once and then sliced and bit-expanded
    per particle with the same offset, inversion and ``dec2bin_concat`` call the per-particle
    function uses. Only the number of netCDF reads changes. ``columns``, when given, is
    ``(parent_rec_num, position)`` already read in full from ``proc_ds``.
    """
    from arrayprobe.constants import IMGPROC_CONFIG
    from arrayprobe.matlab_compat import dec2bin_concat
    from arrayprobe.render import DRAWABLE_PROBES

    if probe not in DRAWABLE_PROBES:
        raise ValueError(f"probe {probe!r} is not drawable here; drawable: {DRAWABLE_PROBES}")
    cfg = IMGPROC_CONFIG[probe]
    idx = np.asarray(indices, dtype=np.int64).reshape(-1)
    out: list = [None] * len(idx)
    if len(idx) == 0:
        return out
    if columns is None:
        columns = (np.asarray(proc_ds.variables["parent_rec_num"][:]),
                   np.asarray(proc_ds.variables["position"][:]))
    parent_col, position_col = columns
    parents = np.array([int(parent_col[i]) for i in idx], dtype=np.int64)  # 1-based
    order = np.argsort(parents, kind="stable")
    data_var = image_ds.variables["data"]
    current_rec = None
    block = None
    for k in order:
        i = int(idx[k])
        rec = int(parents[k])
        if rec != current_rec:
            block = data_var[rec - 1, :, :]
            current_rec = rec
        start, end = (int(v) for v in position_col[i])
        slice_start = start - 1 + cfg.image_slice_offset
        assert block is not None  # set on the first record: current_rec starts as None
        data_slice = np.asarray(block[slice_start:end, :])
        ind_matrix = 65535 - data_slice if cfg.image_invert else data_slice
        c = dec2bin_concat(ind_matrix, cfg.image_word_bits)
        out[k] = c == ord("0")
    return out


def correct_diameter(diam, size_factor, *, direction: str = "korolev"):
    """The out-of-focus diameter correction.

    ``direction="korolev"`` (default): ``diam / size_factor`` -- Korolev (2007) §2 p. 377,
    ``D_0 = D_m / eta(Z_d)``, and v3.5's live ``imgProc_sm.m:1276`` (``minR/sf``).
    ``direction="dead_line_v314"``: ``diam * size_factor`` -- the dead ``sizeDist.m:793`` line,
    which applies the correction in the wrong direction; kept only to reproduce the A/Bs made
    with it.  Both are the identity at ``size_factor == 1``.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r}, expected one of {DIRECTIONS}")
    diam = np.asarray(diam, float)
    sf = np.asarray(size_factor, float)
    if diam.shape != sf.shape:
        raise ValueError(f"shape mismatch {diam.shape} vs {sf.shape}")
    if np.any(sf <= 0):
        # edge_0 (calculate_reject_unified.m:21) is >= 1 everywhere and the default is 1; a
        # non-positive factor is a corrupt input, and dividing by it would be silent.
        raise ValueError("size_factor must be positive")
    if direction == "korolev":
        return diam / sf
    return diam * sf


def correct_area(area, corrected_diam, size_factor, *, area_mode: str = "sphere"):
    """The image area to carry with a corrected particle.

    ``area_mode="sphere"`` (default): for every particle with ``size_factor != 1``, the
    cross-section of the sphere Korolev's reconstruction retrieves, ``pi/4 * D_0**2`` --
    written with the same operation order as ``sizeDist.m:848``'s denominator
    (``sizedist.py``: ``np.pi / 4 * particle_diameter_minR ** 2``), so its area ratio is 1.0.
    The paper gives no area equation; this is the reconstruction's consequence (§3 Eqs. 1-2,
    §9e), not a quoted formula.  Unit-factor particles keep their area exactly.
    ``area_mode="keep"``: ``area`` unchanged for every particle.
    """
    if area_mode not in AREA_MODES:
        raise ValueError(f"unknown area_mode {area_mode!r}, expected one of {AREA_MODES}")
    area = np.asarray(area, float)
    d0 = np.asarray(corrected_diam, float)
    sf = np.asarray(size_factor, float)
    if not (area.shape == d0.shape == sf.shape):
        raise ValueError(f"shape mismatch {area.shape} vs {d0.shape} vs {sf.shape}")
    if area_mode == "keep":
        return area.copy()
    return np.where(sf != 1.0, np.pi / 4 * d0 ** 2, area)


def apply_outoffocus(image_ds, proc_ds, *, config: RejectConfig, indices=None,
                     engine: str = "3.1.4", direction: str = "korolev",
                     area_mode: str = "sphere", jobs: int = 1) -> OutOfFocusResult:
    """Corrected ``image_diam_minR`` and ``image_area`` for ``indices`` (default: all).

    Returns an :class:`OutOfFocusResult` -- ``(indices, corrected_diam, size_factor, part_z,
    is_hollow, corrected_area, direction, area_mode)``.  Reads only; the caller decides where
    to write (a sidecar or a copy of the proc), never the port's file.

    ``engine`` names the engine that **wrote the proc** as well as the hollow detection used:
    under ``"3.5"`` with ``direction="korolev"``, particles v3.5 already divided (stored reject
    ``'H'``) are left as written.  To run v3.5's hollow detection on a v3.1.4-written proc,
    compose :func:`hollow_diagnostics` (``engine="3.5"``), :func:`correct_diameter` and
    :func:`correct_area` directly -- this function would wrongly skip that proc's ``'H'``
    particles, which v3.1.4 never divided.

    ``jobs`` (default 1) is handed to :func:`hollow_diagnostics` unchanged; it changes how the
    per-particle reject calls are scheduled, never the result, and is written nowhere.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r}, expected one of {DIRECTIONS}")
    if area_mode not in AREA_MODES:
        raise ValueError(f"unknown area_mode {area_mode!r}, expected one of {AREA_MODES}")
    n_all = proc_ds.variables["image_diam_minR"].shape[0]
    idx = np.arange(n_all) if indices is None else np.asarray(indices, int)
    part_z, sf, hollow = hollow_diagnostics(image_ds, proc_ds, idx, config=config, engine=engine,
                                            jobs=jobs)
    diam = np.asarray(proc_ds.variables["image_diam_minR"][:], float)[idx]
    area = np.asarray(proc_ds.variables["image_area"][:], float)[idx]
    apply_sf = sf
    if engine == "3.5" and direction == "korolev":
        # A v3.5 proc already carries Korolev's division for every particle whose reject
        # status was 'H' (imgProc_sm.m:1274-1276 v3.5; measure.py:240-241 divides, and
        # imgproc.py:708 stores image_auto_reject = ord(reject_status)).  Dividing those again
        # would double-correct, so their diameter is taken as already D_0.  Not applied under
        # "dead_line_v314", which reproduces what shipped: a multiply over every factor (on a
        # v3.5 proc that undid v3.5's own division for those particles).
        already = np.asarray(proc_ds.variables["image_auto_reject"][:]).astype(int)[idx] == ord("H")
        apply_sf = np.where(already, 1.0, sf)
    d0 = correct_diameter(diam, apply_sf, direction=direction)
    return OutOfFocusResult(idx, d0, sf, part_z, hollow,
                            correct_area(area, d0, sf, area_mode=area_mode),
                            direction, area_mode)
