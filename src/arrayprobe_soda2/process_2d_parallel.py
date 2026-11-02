# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_process_2d.pro:449-573``'s buffer loop, split across processes.

**Not part of the port's reproduction.** SODA-2's IDL has no parallelism; this
module changes no computed number and exists only to make a flight fit in a
night. It is the SODA-2 half of the CIP end-to-end run and sits in the port rather than in
``enhancements_soda2/`` because *"speed work
is the one category that lives in BOTH spaces"*: it moves no written byte, is
opt-in, defaults to serial, and adds no dependency (``concurrent.futures`` and
``multiprocessing`` are stdlib).

Why the loop splits at all, and what had to be established first
----------------------------------------------------------------

The loop walks buffers. Splitting it needs to know, for each thing the body
touches, whether it is a function of that buffer alone. Read off
``process_2d.py``'s loop and the two buffer processors (CIP-1's
``processbuffer_cip.py``; ``processbuffer_spec.py``), **buffer-local**:

* ``buffpoint[i]`` addresses the buffer directly, so ``f.seek`` + ``read2dbuffer``
  needs no predecessor -- the property the whole split rests on, the same one
  ``readers/spec.read_binary_SPEC_parallel`` rests on for UIOOPS S2.
* ``bufftime[i]`` / ``timeindex`` / ``pth_tas[timeindex]``, and the SPEC
  ``nimages``/``imagepointers``/``hkpointers``/``probetas`` lookups, are all
  reads of arrays computed before the loop.
* ``process_buffer_tail`` -- the image processing, **97.3 % of the loop** --
  is a pure function of its own buffer, once ``lastdhist`` is dead (below).

**Not** buffer-local, and how each is handled:

1. ``misc``: ``lastclock``/``lastbufftime``/``maxsfm`` (SPEC,
   ``processbuffer_spec.py:321``, ``:363-364``) and
   ``lastclock``/``lastparticlecount`` (CIP, ``processbuffer_cip.py:166``,
   ``:170``). A genuine sequential chain -- and the whole of it lives in
   ``_front_half``. Its share of the loop depends on the probe: **2.7 %** on
   CIP (measured: read 3.63 ms, front 10.70 ms, tail 518.29 ms per buffer, 60
   real UND 2016-09-06 CIP buffers), and about 15 % of the split loop on a
   1 GB 2D-S file (sweep 4,384.2 s of 29,940.4 s, derived from
   the 2D-S SODA-2 replay launch log, 2026-09-25). So
   :func:`_iter_carry_in` runs that half **serially, in the parent**, for every
   buffer, and yields ``misc`` at each chunk's first buffer; each chunk goes
   to a worker as soon as its state exists, so the pool computes while the
   sweep continues. Each worker starts from the recorded state. The sweep and
   the workers call the same ``_front_half`` in the same order with the same
   inputs, and nothing in the tail feeds back into ``misc``.
2. ``lastdhist`` (``dhist[timeindex-1]``, trap S6-c) is read by
   ``process_buffer_tail`` **only under ``op.stuckbits``**
   (``processbuffer_tail.py:195-196``); it would otherwise couple a buffer's
   image processing to every earlier buffer's output. ``stuckbits`` is
   therefore **refused** with ``jobs > 1``, by name. Not worked around.
3. ``dhist``, ``numbuffsaccepted``, ``numbuffsrejected`` accumulate. Not
   merged here by any new arithmetic: the workers report each buffer's own
   ``p.dhist`` and accept/reject, and ``run_parallel_loop`` replays the
   driver's own ``+=`` lines in buffer order.
4. ``istop``/``istart``/``pbpstartindex``/``ncdf_offset`` and the
   10,000,000-particle flush (`:565-573`, trap S6-d) are a sequential counter.
   Same answer: replayed in buffer order from the per-buffer particle counts,
   so the flush lands on exactly the buffer it lands on serially.
5. The accumulator ``d`` and the PBP writers are reached **only** through the
   driver's own ``_flush``, which this module calls and does not reimplement.
   So ``soda2_particlesort`` sees one ordered array per flush, the same one it
   sees serially.

What a worker sends back is therefore per-buffer facts plus the particle
columns built by the driver's own ``_append_particle``; the parent does all the
arithmetic. Byte-identity is asserted on a real CIP fixture by
``tests/test_soda2_parallel.py`` -- a claim is a test.

**One thing this is NOT.** ``_front_half``/``_tail_half`` are a second written
form of the serial loop's `:449-470`, not the form the serial loop runs: the
serial loop calls the composed ``soda2_processbuffer`` as a module global
because that is a substitution surface. So a correction applied in the parent
process -- a SODA-2 enhancement through ``enhancement_hooks.overridden``, or
the 2016 UND emulation's recompile-and-rebind -- reaches the serial path and
does not reach a ``spawn``-started worker by itself. An earlier draft had the
serial loop call the halves directly; the suite showed it bypassed every
correction and the emulation, and it was reverted.

**Corrections are carried into the workers instead of being refused.**
The author's ruling is that the default is the corrected engine at its fastest
settings, so *fast* and *corrected* cannot be a choice. A substitution that is
installed with an ``enhancement_hooks.Reconstruction`` -- a factory name and a
picklable payload, which is what
``arrayprobe_soda2_enhancements.registry.apply`` installs -- is rebuilt inside
each worker by :func:`_init_worker` before any chunk runs, so the sweep in the
parent and the tails in the workers call the same callables. Each worker reports
what it substituted (``_ChunkResult.hooks``) and
:func:`run_parallel_loop` refuses a chunk whose worker disagrees with the
parent, because byte-identity alone would not notice corrections that failed to
install. :func:`refuse_unsplittable` still refuses what cannot be rebuilt by
name: an ad-hoc callable installed with no plan, and a rebound driver call.
``tests/test_soda2_parallel_enhancements.py`` is the proof, corrections on.

One resource difference, stated because it is real: serial flushes at
``num2process`` particles and frees ``x``; here a finished chunk's columns are
held until the replay reaches them, and chunks that finish ahead of the one
being replayed wait in memory, so peak memory is higher for a run that would
flush. The
columns are typed arrays rather than the serial path's Python lists, which
more than pays for it below the flush threshold (~176 B/particle against
~1.3 kB), and above it the run is >= 10,000,000 particles either way.
"""
from __future__ import annotations

import logging
import multiprocessing
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np

from .processbuffer_cip import CipMisc
from .processbuffer_spec import NullBuffer, SpecMisc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .particlesort import Accumulator, ParticlesortOptions
    from .process_2d import _LoopContext

__all__ = ["Soda2ParallelRefused", "chunk_bounds", "refuse_unsplittable",
           "run_parallel_loop"]

_log = logging.getLogger("arrayprobe_soda2.process_2d.progress")


class Soda2ParallelRefused(NotImplementedError):
    """``jobs > 1`` asked for on a run whose loop this module cannot split
    exactly. Never downgraded to a warning: the alternative to refusing is a
    number that is wrong in a way nothing would catch."""


@dataclass
class _ChunkResult:
    """One contiguous buffer range's output, as its worker reports it.

    Per-buffer arrays are in buffer order, one entry per buffer in ``[lo, hi)``.
    ``x`` holds the particles of the accepted buffers, concatenated in the same
    order the serial loop appends them."""

    lo: int
    hi: int
    x: dict[str, np.ndarray]
    counts: np.ndarray          # particles contributed by each buffer (0 if not accepted)
    accepted: np.ndarray        # bool: neither a NullBuffer nor rejectbuffer != 0
    is_null: np.ndarray         # bool: the front half returned a NullBuffer
    timeindex: np.ndarray       # int64
    dhist: np.ndarray           # (nbuffers, numdiodes) int16, zero rows where is_null
    #: `enhancement_hooks.active()` AS THE WORKER SAW IT while this chunk ran
    #: Reported rather than assumed, so `run_parallel_loop` can refuse
    #: a result computed by a worker whose corrections failed to install --
    #: byte-identity alone would not catch that, and the SODA-2 lane has already
    #: been bitten once by output that matched with every correction bypassed.
    hooks: dict[str, str]


def chunk_bounds(firstbuff: int, lastbuff: int, nchunks: int) -> list[tuple[int, int]]:
    """Split ``[firstbuff, lastbuff]`` (inclusive, the driver's own range) into
    at most ``nchunks`` contiguous half-open ranges, none empty.

    Contiguous and in order, so an ordered concatenation of the chunks is the
    serial sequence -- the same partition property
    a range-iteration test pins for the UIOOPS decode.
    """
    n = lastbuff + 1 - firstbuff
    if n <= 0:
        return []
    k = max(1, min(int(nchunks), n))
    edges = [firstbuff + (n * j) // k for j in range(k + 1)]
    return [(a, b) for a, b in zip(edges[:-1], edges[1:], strict=True) if b > a]


def _misc_state(misc: SpecMisc | CipMisc) -> dict[str, float | int]:
    """The carry-in chain, and nothing else: the ``(*pmisc)`` fields a buffer
    processor *reads from its predecessor*. Everything else on ``misc``
    (``nimages``, the pointer arrays, ``probetas``, ``aircrafttas``) is
    rewritten from the index by ``_front_half`` before it is read, so it is
    not state and is deliberately not carried."""
    if isinstance(misc, CipMisc):
        return {"lastclock": float(misc.lastclock),
                "lastparticlecount": int(misc.lastparticlecount)}
    return {"lastclock": float(misc.lastclock),
            "lastbufftime": float(misc.lastbufftime),
            "maxsfm": float(misc.maxsfm)}


def _misc_from_state(template: SpecMisc | CipMisc,
                     state: dict[str, float | int]) -> SpecMisc | CipMisc:
    return replace(template, **state)  # type: ignore[arg-type]


def _iter_carry_in(ctx: _LoopContext, bounds: list[tuple[int, int]],
                   misc: SpecMisc | CipMisc) -> Iterator[tuple[int, dict[str, float | int]]]:
    """The one part of the loop that cannot be split: walk every buffer's
    ``_front_half`` in order, in this process, and yield ``(j, misc state)`` as
    the walk reaches chunk ``j``'s first buffer.

    A generator, so :func:`run_parallel_loop` can hand chunk ``j`` to a worker
    the moment its start state exists and keep walking while the workers
    compute; the states are the same values either way. ``_front_half`` is the
    serial loop's own, so the states are the ones the serial loop has at those
    buffers, by construction rather than by argument.
    """
    from .process_2d import _front_half

    starts = {lo: j for j, (lo, _hi) in enumerate(bounds)}
    lo0, hi_last = bounds[0][0], bounds[-1][1]
    with open(ctx.fn_list[0], "rb") as f:
        for i in range(lo0, hi_last):
            if i in starts:
                yield starts[i], _misc_state(misc)
            _front_half(ctx, i, f, misc)


#: Set once per worker process by :func:`_init_worker`; never mutated after.
_CTX: _LoopContext | None = None
_MISC_TEMPLATE: SpecMisc | CipMisc | None = None
#: The worker's own ``enhancement_hooks.overridden`` block, entered by
#: :func:`_init_worker` and held open for the process's life. Kept so the
#: substitution cannot be garbage-collected out from under the chunks, and so
#: :func:`worker_substitution` can report it.
_HOOKS: Any | None = None


def _init_worker(ctx: _LoopContext, misc_template: SpecMisc | CipMisc,
                 plan: Any = None) -> None:
    """One worker process's setup: the loop context, the ``misc`` template, and
    -- the parent's enhancement substitution rebuilt from ``plan``.

    ``plan`` is an ``enhancement_hooks.Reconstruction`` (plain data: an
    importable ``"module:callable"`` and a picklable payload) or ``None``. It is
    rebuilt and installed **here**, before any chunk runs, so a worker's
    ``_front_half``/``_tail_half`` call exactly the callables the parent's
    carry-in sweep called. The ``with`` block is entered and deliberately never
    exited: the substitution is this process's whole life, and the process is
    torn down by the pool.

    A failure to rebuild raises here, which the pool surfaces on the first
    ``map`` result. That is the right direction: a worker that silently fell
    back to the port's own functions would produce uncorrected numbers under a
    run the user asked corrections for, which is the one outcome this module
    exists to prevent.
    """
    global _CTX, _MISC_TEMPLATE, _HOOKS
    _CTX = ctx
    _MISC_TEMPLATE = misc_template
    if plan is not None:
        import atexit

        from . import enhancement_hooks
        repl = plan.build()
        cm = enhancement_hooks.overridden(repl, reconstruction=plan)
        cm.__enter__()
        _HOOKS = cm
        # Closed at `atexit` rather than left to the interpreter's final garbage
        # collection: an un-exited `@contextmanager` generator is finalised after
        # `sys.meta_path` is gone, and `overridden`'s `finally` does an
        # `importlib.import_module` -- which then raises "Python is likely
        # shutting down" onto every worker's stderr. Harmless, but it would put
        # a traceback in the log of every successful split run.
        atexit.register(cm.__exit__, None, None, None)


def worker_substitution() -> dict[str, str]:
    """What this process has substituted -- ``enhancement_hooks.active()``.

    A worker-side observation rather than an echo of the argument, so a test can
    assert the corrections really are installed *in the worker* and not merely
    that a plan was passed to it.
    """
    from . import enhancement_hooks
    return enhancement_hooks.active()


def _run_chunk(task: tuple[int, int, dict[str, float | int], int]) -> _ChunkResult:
    """One chunk, in a worker process: the driver's loop body minus the
    bookkeeping, for buffers ``[lo, hi)``.

    Calls ``_front_half`` and ``_tail_half`` -- a second written form of the
    serial loop's `:449-470`, see the module docstring -- and appends particles
    with ``_append_particle``, which IS the serial loop's own row builder, so
    nothing about a particle's *value* depends on having come through here.
    """
    from .process_2d import _X_KEYS, _append_particle, _front_half, _new_x, _tail_half, _x_to_arrays

    lo, hi, misc_state, report_every = task
    ctx, template = _CTX, _MISC_TEMPLATE
    assert ctx is not None and template is not None, "worker initializer did not run"
    misc = _misc_from_state(template, misc_state)

    # Dead by refusal: `run_parallel_loop` rejects `stuckbits`, the only reader
    # (`processbuffer_tail.py:195-196`). Shaped so the tail's own shape check
    # (`:170-174`) sees what it sees serially.
    lastdhist = np.zeros(ctx.numdiodes, dtype=np.int32)

    x = _new_x()
    n_buf = hi - lo
    counts = np.zeros(n_buf, dtype=np.int64)
    accepted = np.zeros(n_buf, dtype=bool)
    is_null = np.zeros(n_buf, dtype=bool)
    timeindex = np.zeros(n_buf, dtype=np.int64)
    dhist = np.zeros((n_buf, ctx.numdiodes), dtype=np.int16)

    started = time.monotonic()
    with open(ctx.fn_list[0], "rb") as f:
        for k, i in enumerate(range(lo, hi)):
            front, b_time, ti, aircrafttas_i = _front_half(ctx, i, f, misc)
            p = _tail_half(ctx, front, lastdhist)
            timeindex[k] = ti
            if isinstance(p, NullBuffer):
                is_null[k] = True
            else:
                dhist[k, :] = p.dhist
                if p.rejectbuffer == 0:
                    accepted[k] = True
                    n = int(p.diam.size)
                    counts[k] = n
                    for j in range(n):
                        _append_particle(x, p, b_time, aircrafttas_i, j)
            if report_every > 0 and (k + 1) % report_every == 0:
                print(f"  ...chunk {lo}-{hi} buffer {k + 1}/{n_buf}, "
                      f"{time.monotonic() - started:.1f} s", flush=True)

    arrays = _x_to_arrays(x)
    return _ChunkResult(lo=lo, hi=hi, x={key: arrays[key] for key in _X_KEYS},
                        counts=counts, accepted=accepted, is_null=is_null,
                        timeindex=timeindex, dhist=dhist,
                        hooks=worker_substitution())


def refuse_unsplittable(op: Mapping[str, Any], fn_list: Sequence[Any],
                        jobs: int) -> None:
    """Every configuration whose loop this module cannot split exactly, refused
    by name and by the line that makes it so.

    Called from ``soda2_process_2d`` **before anything is opened or read** --
    beside the driver's other configuration refusals (`:478-520`) rather than
    at the point of the split -- because a refusal raised later would leave the
    PBP writers open behind it (the shape of SODA-2 register entry S6-f), and a configuration error
    should cost no file.
    """
    if int(op.get("stuckbits", 0)) != 0:
        raise Soda2ParallelRefused(
            "jobs > 1 with op.stuckbits set: `process_buffer_tail` then reads "
            "`lastdhist = dhist[timeindex-1]` (processbuffer_tail.py:195-196), "
            "which is every earlier buffer's output, so a buffer's image "
            f"processing is not buffer-local. Run with jobs=1 (got jobs={jobs}).")
    if len(fn_list) != 1:
        raise Soda2ParallelRefused(
            "jobs > 1 with more than one raw file: the split carries no "
            "per-buffer file index or per-file pointer "
            "(soda2_process_2d.pro:364-391), and SPEC stops at :376 anyway; "
            f"run with jobs=1 (got {len(fn_list)} files).")
    if int(op.get("activetimefrommissed", 0)) == 1:
        raise Soda2ParallelRefused(
            "jobs > 1 with op.activetimefrommissed: soda2_process_2d.pro:493 is "
            "an IDL `stop` ('Under development'), raised serially per buffer; "
            "run with jobs=1 to get that error where the IDL gives it.")

    # A SODA-2 correction, or the 2016 UND emulation, is applied by replacing a
    # module-global binding IN THIS PROCESS (`enhancement_hooks.overridden`,
    # recompile-and-rebind). A `spawn`-started
    # worker re-imports the package and inherits none of it -- so a split run
    # whose workers did nothing about it would apply the substitution to the
    # carry-in sweep, which happens in the parent, and NOT to the tails, which
    # are 97 % of the work. Every number would then be some unnamed mixture.
    #
    # That was lifted for the case where the substitution can be REBUILT in the
    # worker from plain data: `enhancement_hooks.reconstruction_plan()` is the
    # installer's statement of how, `_init_worker` performs it, and
    # `tests/test_soda2_parallel_enhancements.py` proves the split is then
    # byte-identical to serial with the same corrections on. What stays refused
    # is what still cannot be rebuilt by name: an ad-hoc callable passed through
    # `overridden` with no plan, and a rebound driver call (the emulation's
    # recompile-and-rebind, which replaces the composed `soda2_processbuffer`
    # that the split does not call at all). Read from the port's own hook
    # registry rather than a list typed here, so a hook point added later is
    # covered without this function being edited.
    from . import enhancement_hooks, process_2d
    substituted = sorted(n for n, ok in enhancement_hooks.pristine().items() if not ok)
    rebound = sorted(n for n, fn in process_2d._PRISTINE_CALLS.items()
                     if getattr(process_2d, n, None) is not fn)
    if rebound:
        raise Soda2ParallelRefused(
            f"jobs > 1 with a rebound driver call {rebound}: it replaces the "
            "composed `soda2_processbuffer`, which the split does not call -- it "
            "calls `_front_half`/`_tail_half` -- so there is nothing for a worker "
            "to honour and no way to rebuild it by name. Run with jobs=1.")
    if substituted and enhancement_hooks.reconstruction_plan() is None:
        raise Soda2ParallelRefused(
            f"jobs > 1 with a live in-process substitution (hook points "
            f"{substituted}) that carries no reconstruction plan: a spawn-started "
            "worker re-imports the package and inherits no monkey-patch, so the "
            "split would apply it to the serial carry-in pass and not to the "
            "per-buffer tails. Install the substitution with "
            "`enhancement_hooks.overridden(repl, reconstruction=...)` -- which is "
            "what `arrayprobe_soda2_enhancements.registry.apply` does, so the "
            "shipped corrections DO split -- or run with jobs=1. This "
            "refusal is about the substitution and NOT about `jit`, which installs "
            "nothing and is unaffected.")


def run_parallel_loop(
    ctx: _LoopContext,
    firstbuff: int,
    lastbuff: int,
    misc: SpecMisc | CipMisc,
    *,
    jobs: int,
    chunks: int = 0,
    report_every: int = 0,
    d: Accumulator,
    dhist: np.ndarray,
    numbuffsaccepted: np.ndarray,
    numbuffsrejected: np.ndarray,
    pbpstartindex: np.ndarray,
    num2process: int,
    psopts: ParticlesortOptions,
    flush: Callable[..., int],
    csv_f: Any,
    ncdf_ds: Any,
) -> tuple[int, int, dict[str, np.ndarray]]:
    """Run `:449-573` across ``jobs`` processes and replay the driver's
    bookkeeping over the result.

    Mutates ``dhist``, ``numbuffsaccepted``, ``numbuffsrejected``,
    ``pbpstartindex`` and (through ``flush``) ``d`` and the PBP writers exactly
    as the serial loop does, and returns the ``(istop, ncdf_offset, x)`` the
    serial loop would be holding when it fell out -- so everything after the
    loop in ``soda2_process_2d`` is reached in the same state.
    """
    # Re-checked here as well as at the driver's top, so an in-tree caller that
    # reaches this function directly cannot skip the refusals.
    refuse_unsplittable(ctx.op, ctx.fn_list, jobs)
    bounds = chunk_bounds(firstbuff, lastbuff, chunks if chunks > 0 else 4 * jobs)
    if not bounds:  # the caller's `(lastbuff - firstbuff) <= 0` already returned
        return -1, 0, {}

    # A copy, so the sweep leaves the caller's `misc` untouched and the workers'
    # template is the driver's pristine initial state (`:39-41`).
    template = replace(misc)

    # What this parent has substituted, and how a worker rebuilds it. Read
    # here rather than passed in, so the driver signature does not have to carry
    # an enhancements concept the port does not own; `refuse_unsplittable` above
    # has already established that a live substitution comes with a plan.
    from . import enhancement_hooks
    plan = enhancement_hooks.reconstruction_plan()
    expected_hooks = enhancement_hooks.active()

    # A worker's own liveness interval, in buffers. Not `report_every` (20,000
    # buffers, the whole-run figure) -- a chunk is typically far smaller than
    # that and would print nothing, leaving `--worker-stall-min`-class watchdogs
    # and a human reading the log with a silent process. Pair J's lesson on the
    # UIOOPS decode (`readers/spec._report_part_progress`), applied here.
    worker_every = min(report_every, 100) if report_every > 0 else 0
    replay = _Replayer(d=d, dhist=dhist, numbuffsaccepted=numbuffsaccepted,
                       numbuffsrejected=numbuffsrejected, pbpstartindex=pbpstartindex,
                       num2process=num2process, psopts=psopts, flush=flush,
                       csv_f=csv_f, ncdf_ds=ncdf_ds)
    t0 = time.monotonic()
    t_replay = 0.0
    n_particles = 0
    # ``spawn`` on every platform: a ``fork``-started worker (Linux's default)
    # inherits the parent's already-installed enhancement hooks, and
    # ``_init_worker`` then refuses to install them a second time. Windows
    # and macOS spawn already; this makes Linux compute the same way.
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init_worker,
                             initargs=(ctx, template, plan),
                             mp_context=multiprocessing.get_context("spawn")) as pool:
        # Chunk j is submitted the moment the sweep has recorded its start
        # state, so the workers compute while the parent keeps sweeping. The
        # states are the ones a finished sweep would have handed over.
        futures: list[Any] = [
            pool.submit(_run_chunk, (lo, hi, state, worker_every))
            for (lo, hi), (_j, state)
            in zip(bounds, _iter_carry_in(ctx, bounds, replace(misc)), strict=True)]
        t_sweep = time.monotonic() - t0
        if report_every > 0:
            _log.info("  ...carry-in sweep: %d buffers in %.1f s; %d chunks over %d jobs",
                      bounds[-1][1] - bounds[0][0], t_sweep, len(bounds), jobs)
        # Collected in submission order, which is buffer order, and replayed as
        # each arrives -- the replay depends on that order and on nothing else
        # about scheduling. A chunk that finishes early waits for its turn.
        for j in range(len(futures)):
            part = futures[j].result()
            futures[j] = None  # released once replayed
            # The worker's own report of what it had substituted while it ran
            # Not a formality: a worker whose corrections failed to
            # install would still return well-shaped arrays, and the parent
            # would replay them into a product that names those corrections in
            # its sidecar. Checked per chunk, against the parent's own live set.
            if part.hooks != expected_hooks:
                raise Soda2ParallelRefused(
                    f"chunk {part.lo}-{part.hi} was computed by a worker whose "
                    f"substitution was {sorted(part.hooks)}, but this process has "
                    f"{sorted(expected_hooks)} live. The split would mix corrected "
                    "and uncorrected buffers into one product; refused rather than "
                    "written.")
            t_r = time.monotonic()
            replay.feed(part)
            t_replay += time.monotonic() - t_r
            n_particles += int(part.counts.sum())
            if report_every > 0:
                _log.info("  ...chunk %d-%d done (%d/%d), %.1f min elapsed",
                          part.lo, part.hi, j + 1, len(futures),
                          (time.monotonic() - t0) / 60.0)

    out = replay.finish()
    if report_every > 0:
        # Where the time went, so a disappointing speedup is diagnosable from
        # the log instead of re-measured. `sweep` is the serial carry-in pass,
        # which the pool overlaps; `pool` is the wall time after the sweep until
        # the last chunk was replayed, less the replay itself; `replay` is the
        # driver's own bookkeeping, plus any `num2process` flush it triggers,
        # summed over the chunks as they arrived. It holds no final flush: the
        # single final `_flush` happens in `soda2_process_2d` AFTER this
        # returns. The accumulation that flush performs (`soda2_particlesort`
        # and the PBP writes) is serial in both paths and is the remaining floor
        # on the WHOLE run; it is not parallelised and this line does not
        # pretend to cover it.
        total = time.monotonic() - t0
        _log.info("  ...split loop: sweep %.1f s, pool %.1f s, replay %.1f s "
                  "(%d particles; the final flush is the driver's, after this)",
                  t_sweep, total - t_sweep - t_replay, t_replay, n_particles)
    return out


class _Replayer:
    """`:495-573`, buffer by buffer, fed one chunk result at a time in buffer order.

    Line for line the serial body's second half, with ``p.dhist``,
    ``p.rejectbuffer`` and ``p.diam.size`` read out of a chunk result instead of
    off a buffer just processed. The arithmetic is the driver's, so the int16
    ``numbuffs*`` wrap, the int32 ``dhist`` accumulation and the ``istop``
    counter are whatever they are serially -- no wider working type is
    introduced anywhere.

    Fed as chunks arrive, so the bookkeeping and any ``num2process`` flush run
    while later chunks are still in the pool. Particle columns are kept as the
    chunks' own arrays and concatenated only when a flush needs them. A flush is
    handed every particle fed and not yet flushed; ``_flush`` reads
    ``x[key][:istop + 1]`` of it and nothing beyond, and those are the particles
    of the buffers replayed so far, in order -- the values the serial ``x``
    holds at that buffer. The columns share one dtype per key in every chunk
    (``_x_to_arrays``), so a concatenation's dtype does not depend on which
    chunks it spans.
    """

    def __init__(self, *, d: Accumulator, dhist: np.ndarray, numbuffsaccepted: np.ndarray,
                 numbuffsrejected: np.ndarray, pbpstartindex: np.ndarray,
                 num2process: int, psopts: ParticlesortOptions,
                 flush: Callable[..., int], csv_f: Any, ncdf_ds: Any) -> None:
        from .process_2d import _X_KEYS

        self.keys = list(_X_KEYS)
        self.d = d
        self.dhist = dhist
        self.numbuffsaccepted = numbuffsaccepted
        self.numbuffsrejected = numbuffsrejected
        self.pbpstartindex = pbpstartindex
        self.num2process = num2process
        self.psopts = psopts
        self.flush = flush
        self.csv_f = csv_f
        self.ncdf_ds = ncdf_ds
        #: The fed chunks' columns not yet wholly flushed, in buffer order, and
        #: how many particles at the front of the first have been flushed.
        self.pending: list[dict[str, np.ndarray]] = []
        self.head = 0
        self.istop = -1
        self.ncdf_offset = 0

    def _block(self) -> dict[str, np.ndarray]:
        """Every particle fed and not yet flushed, in order."""
        if not self.pending:
            from .process_2d import _new_x, _x_to_arrays
            return _x_to_arrays(_new_x())
        return {key: np.concatenate([self.pending[0][key][self.head:]]
                                    + [cols[key] for cols in self.pending[1:]])
                for key in self.keys}

    def _consume(self, n: int) -> None:
        """Drop the first ``n`` pending particles, the ones a flush just wrote."""
        while n > 0 and self.pending:
            left = self.pending[0][self.keys[0]].size - self.head
            if n < left:
                self.head += n
                return
            n -= left
            self.pending.pop(0)
            self.head = 0
        if n > 0:
            raise AssertionError("a flush consumed more particles than were replayed")

    def feed(self, part: _ChunkResult) -> None:
        self.pending.append(part.x)
        dhist = self.dhist
        for k, i in enumerate(range(part.lo, part.hi)):
            ti = int(part.timeindex[k])
            if not part.is_null[k]:
                dhist[ti, :] = dhist[ti, :] + part.dhist[k, :]
            # `lastdhist = dhist[max(ti-1,0), :]` is not carried here: it feeds
            # only the next `process_buffer_tail`, which has already run, and
            # `stuckbits` -- its one reader -- is refused above.
            if not part.accepted[k]:
                self.numbuffsrejected[ti] += 1
            else:
                self.numbuffsaccepted[ti] += 1
                n = int(part.counts[k])
                istart = self.istop + 1
                self.istop = istart + n - 1
                self.pbpstartindex[i] = istart + self.ncdf_offset  # `:507`
            if self.istop + 500 > self.num2process:
                self.ncdf_offset += self.flush(
                    self.psopts, self._block(), self.d, self.istop, csv_f=self.csv_f,
                    ncdf_ds=self.ncdf_ds, ncdf_offset=self.ncdf_offset)
                self._consume(self.istop + 1)
                self.istop = -1

    def finish(self) -> tuple[int, int, dict[str, np.ndarray]]:
        """What the serial loop holds when it falls out: ``(istop,
        ncdf_offset, x)``, ``x`` being the particles not yet flushed."""
        return self.istop, self.ncdf_offset, self._block()
