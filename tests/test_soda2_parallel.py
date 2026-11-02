# SPDX-License-Identifier: BSD-3-Clause
"""The split SODA-2 buffer loop must be byte-identical to the serial one.

**Why this is a test and not a sentence.** *A byte-identical
claim is a test, not a sentence.* ``process_2d_parallel`` splits
``soda2_process_2d.pro:449-573`` across processes; the argument that this is
exact has three parts, and an argument is not a proof --

1. a buffer is addressable without reading its predecessors
   (``buffpoint[i]``), so ``f.seek`` + ``read2dbuffer`` needs no history;
2. the whole cross-buffer chain lives in ``_front_half``
   (``lastclock``/``lastbufftime``/``maxsfm`` for SPEC,
   ``lastclock``/``lastparticlecount`` for CIP), which the parallel path runs
   **serially in the parent** to record each chunk's carry-in, and
   ``lastdhist`` -- the one other cross-buffer read -- is refused rather than
   guessed (``op.stuckbits``);
3. every accumulation (``dhist``, ``numbuffs*``, ``istop``, ``pbpstartindex``,
   the ``num2process`` flush, the accumulator, the PBP writers) is replayed by
   the driver's own lines in buffer order, so no new arithmetic exists to be
   wrong.

So these tests compare the bytes: every ``ProcessData`` field with
``np.array_equal`` (never ``allclose``), and the ``.pbp.csv`` and ``.pbp.nc``
files the run writes.

**And they are load-bearing, not decorative.** The split's per-buffer work
(``_front_half``/``_tail_half``) is a *second written form* of the serial
loop's `:449-470` -- the serial loop calls the composed
``soda2_processbuffer`` instead, because that is a substitution surface a
split into halves cannot honour. Nothing but the comparisons below stops the
two forms drifting apart, which is why they run on both the CIP/SEA and the
SPEC route.

**The one exclusion, and how it is established rather than assumed.**
``pbp_writer.py:235`` writes ``Date Processed: <datetime.now().ctime()>`` into
the CSV's line 3, and ``process_2d.py:840`` sets ``ProcessData.date_processed``
from ``datetime.now()`` -- the ``'Creation Time'`` class of non-determinism
this project already excludes from byte comparisons. It is not taken on trust:
:meth:`ParallelMatchesSerialCip.test_two_serial_runs_differ_in_the_same_one_line`
runs the *serial* driver twice and requires the same single line to differ, so
the exclusion is measured against a run that had no parallelism in it at all.
Nothing else is excluded, and no comparison is loosened.

**Bounded, because a hang here is worse than no speedup.**
``tests/test_spec_parallel.py`` hung four suite runs on 2026-09-10/11 --
workers died at spawn with ``OSError: [WinError 6] The handle is invalid`` and
``ProcessPoolExecutor.map`` then waited forever. Every real driver run below
therefore happens in a **subprocess with a timeout**, the fix that module
adopted, so a hang is bounded and named instead of killing the run. Both sides
of every comparison go through the same helper, so serial and parallel differ
in the ``jobs`` argument and in nothing else about how they were run.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from tests._repo import needs_file  # noqa: E402
from tests._slow import slow

from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d
from arrayprobe_soda2.process_2d_parallel import (
    Soda2ParallelRefused,
    chunk_bounds,
)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CIP_FIXTURE = DATA / "soda2_sea_cip_fixture.sea"
SPEC_FIXTURE = DATA / "s2_spec_raw_fixture"
DMT_FIXTURE = DATA / "dmt_raw_synthetic.cip"

#: How long one driver run of a tracked fixture may take before the test gives
#: up on it. The fixtures are tens of kilobytes and a healthy run is a few
#: seconds. Generous rather than tight, for the reason ``test_spec_parallel``
#: gives: this bounds a hang, it does not police performance, and a timeout
#: that fired on a slow machine would be a false alarm about the one property
#: these tests exist to prove.
RUN_TIMEOUT_S = 300

#: ``ProcessData`` fields excluded from the comparison, each with its reason.
#: Nothing is excluded for being "close enough", and every run below writes to
#: the SAME output directory (moved aside between runs) so that no field is
#: excluded merely for naming a path.
EXCLUDED_FIELDS = {
    # `:677` `systime(/julian)`, via `process_2d.py:840` -- non-deterministic
    # by construction, the `'Creation Time'` class this project already
    # excludes from every byte comparison.
    "date_processed",
    # `house` is `process_hk(op, y=y)` for SPEC and `{op: op}` for SEA/CIP
    # (`:394`), both computed BEFORE the loop and carried into `ProcessData`
    # untouched -- the split cannot reach it. Excluded rather than compared
    # because `HouseData`'s repr truncates its arrays with `...`, which would
    # make the comparison weaker than it looks while appearing to be one.
    "house",
}

#: The CIP op ``test_soda2_cip_driver.py`` asserts against the GDL driver
#: golden, imported rather than retyped so the parallel path is exercised on
#: exactly the configuration the fidelity claim rests on.
sys.path.insert(0, str(HERE))


def _cip_op(outdir: Path) -> dict:
    from test_soda2_cip_driver import _cip_op as base
    op = base([33000])
    op["outdir"] = str(outdir.resolve()) + "/"
    op["particlefile"] = 1       # write the `.pbp.csv`
    op["ncdfparticlefile"] = 1   # and the `.pbp.nc`, so `ncdf_offset` is exercised
    op["savfile"] = 0            # the IDL SAVE embeds `date_processed`
    return op


def _dmt_op(outdir: Path) -> dict:
    """The DMT/PADS op ``test_soda2_dmt_driver.py`` asserts against its GDL
    driver golden (PIP, subformat 1), writing both PBP files."""
    from test_soda2_dmt_driver import _op as base
    op = base(str(DMT_FIXTURE), 1, "PIP")
    op["outdir"] = str(outdir.resolve()) + "/"
    op["particlefile"] = 1
    op["ncdfparticlefile"] = 1
    op["savfile"] = 0
    return op


def _spec_op(outdir: Path) -> dict:
    from test_soda2_process_2d import _base_op
    op = _base_op()
    op["outdir"] = str(outdir.resolve()) + "/"
    op["particlefile"] = 1
    op["savfile"] = 0
    return op


#: Run the driver out of process and dump what a byte comparison needs.
#: ``np.savez`` for the arrays (so the parent can use ``np.array_equal`` on the
#: real values, not on a digest that could collide) and JSON for the rest.
_CHILD = textwrap.dedent("""
    import faulthandler, json, pickle, sys
    from dataclasses import fields
    from pathlib import Path
    import numpy as np

    op_path, out_path, jobs, chunks, timeout_s, jit = sys.argv[1:7]
    # Dump every thread's stack 15 s before the parent's timeout kills this
    # child, so a hang names its frame instead of being anonymous -- the same
    # measure tests/test_spec_parallel.py added on 2026-09-11.
    faulthandler.dump_traceback_later(
        max(1.0, float(timeout_s) - 15), exit=False, file=sys.stderr)

    from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d
    op = pickle.loads(Path(op_path).read_bytes())
    d = soda2_process_2d(op, jobs=int(jobs), chunks=int(chunks), jit=int(jit) != 0)
    # Did the numba kernel actually run? `jit_kernels.load()` is called by
    # `label_blobs` only on a `jit=True` call and memoises into `_LOADED`, so
    # this is an OBSERVATION of engagement rather than an echo of the argument
    # -- which is what stops a jit-vs-no-jit identity test passing vacuously
    # because the flag never arrived. Read after the run, in the process that
    # ran it (a `jobs > 1` worker loads its own; see the note in
    # tests/test_soda2_jit_product_identity.py).
    import arrayprobe_soda2.jit_kernels as _jk
    kernel_loaded = _jk._LOADED is not None
    if d is None:
        Path(out_path + ".json").write_text(json.dumps(
            {"none": True, "kernel_loaded": kernel_loaded}))
        raise SystemExit(0)
    arrays, scalars = {}, {}
    for f in fields(ProcessData):
        v = getattr(d, f.name)
        if isinstance(v, np.ndarray):
            arrays[f.name] = v
        else:
            scalars[f.name] = repr(v)
    np.savez(out_path + ".npz", **arrays)
    Path(out_path + ".json").write_text(json.dumps(
        {"none": False, "scalars": scalars, "array_fields": sorted(arrays),
         "kernel_loaded": kernel_loaded}))
""")

FIRST_LABEL = "\n--- first attempt ---\n"
SECOND_LABEL = "\n--- second attempt ---\n"


class _Run:
    """One driver run's outputs: the ``ProcessData`` arrays, the non-array
    fields, and a digest per written file."""

    def __init__(self, npz: Path, meta: dict, outdir: Path) -> None:
        self.arrays = dict(np.load(npz)) if npz.is_file() else {}
        self.meta = meta
        self.outdir = outdir
        self.files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(outdir.iterdir())}


def _run_driver(op: dict, tmp: Path, tag: str, *, jobs: int, chunks: int = 0,
                jit: bool = False) -> _Run:
    """One ``soda2_process_2d`` run, out of process, bounded by a timeout.

    **Why a subprocess even for ``jobs=1``.** So that the two sides of every
    comparison below differ in the ``jobs`` argument and in nothing else --
    not in which process they ran in, not in whether a pool had ever been
    created in that interpreter. The timeout is what bounds the parallel side;
    applying it to both costs a second and removes a variable.

    **Why every run writes to the same directory.** ``op.outdir`` is written
    into the output itself (the ``.pbp.nc``'s ``OUTDIR`` attribute,
    ``pbp_writer.py``) and into ``ProcessData.op`` and the ``*_path`` fields.
    Two runs in two directories would therefore differ in bytes that have
    nothing to do with the split, and the comparison would need three more
    exclusions to hide it. So the run writes to one shared path and its output
    is moved aside afterwards -- leaving exactly one non-deterministic thing in
    the whole comparison, the processing timestamp.
    """
    import pickle
    live = tmp / "live"
    if live.exists():
        shutil.rmtree(live)
    live.mkdir(parents=True)
    op = dict(op)
    op["outdir"] = str(live.resolve()) + "/"
    op_path = tmp / f"{tag}.op.pkl"
    op_path.write_bytes(pickle.dumps(op))
    stem = tmp / f"{tag}.out"
    argv = [sys.executable, "-c", _CHILD, str(op_path), str(stem), str(jobs),
            str(chunks), str(RUN_TIMEOUT_S), str(int(bool(jit)))]

    def attempt():
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=RUN_TIMEOUT_S, cwd=str(HERE.parent))

    try:
        done = attempt()
        if done.returncode != 0 and "WinError 6" in done.stderr:
            # ONE retry, for this signature only, and for the reason
            # tests/test_spec_parallel.py gives at length: the worker-side
            # stack is the child failing to acquire its OWN call queue's
            # semaphore -- a handle that did not survive spawn, nothing this
            # package computed. Retried rather than skipped, because a skip
            # would also hide a real break in the split loop.
            first = done
            time.sleep(2.0)
            done = attempt()
            if done.returncode != 0:
                raise AssertionError(
                    "the driver subprocess failed TWICE with the spawn-handle "
                    "signature, so this is not transient handle pressure"
                    + FIRST_LABEL + first.stderr[-1200:]
                    + SECOND_LABEL + done.stderr[-1200:])
    except subprocess.TimeoutExpired as exc:
        err = exc.stderr
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        raise AssertionError(
            f"soda2_process_2d(jobs={jobs}) did not finish in {RUN_TIMEOUT_S}s on a "
            f"tracked fixture. Every occurrence of this class of hang so far has been "
            "worker processes dying at spawn with WinError 6, after which pool.map "
            "waits forever -- it killed four suite runs on 2026-09-10/11. Re-run this "
            "module alone on an idle machine before reading it as a break in "
            "process_2d_parallel.\n--- child stderr, last 3000 chars (faulthandler "
            "dump if the hang lasted long enough) ---\n" + (err or "")[-3000:]) from exc
    if done.returncode != 0:
        raise AssertionError(f"the driver subprocess exited {done.returncode}\n"
                             f"stdout: {done.stdout[-2000:]}\n"
                             f"stderr: {done.stderr[-3000:]}")
    meta = json.loads(Path(str(stem) + ".json").read_text())
    kept = tmp / f"{tag}.out.d"
    if kept.exists():
        shutil.rmtree(kept)
    shutil.copytree(live, kept)
    return _Run(Path(str(stem) + ".npz"), meta, kept)


class ChunkBoundsPartitionTheRange(unittest.TestCase):
    """The split's own arithmetic. A range that dropped or duplicated a buffer
    would change the output without any per-buffer logic being wrong, which is
    the failure the whole parallel path is exposed to -- the same property
    ``test_spec_parallel.py::RangeIteration`` pins for the UIOOPS decode."""

    def test_the_chunks_reassemble_the_drivers_own_inclusive_range(self) -> None:
        for first, last, k in ((0, 99, 4), (7, 7, 3), (3, 10, 1), (0, 10, 7),
                               (100, 949, 24), (5, 6, 2)):
            with self.subTest(first=first, last=last, k=k):
                bounds = chunk_bounds(first, last, k)
                walked = [i for lo, hi in bounds for i in range(lo, hi)]
                self.assertEqual(walked, list(range(first, last + 1)))

    def test_no_chunk_is_empty_even_with_more_chunks_than_buffers(self) -> None:
        bounds = chunk_bounds(0, 2, 64)
        self.assertEqual(bounds, [(0, 1), (1, 2), (2, 3)])
        for lo, hi in bounds:
            self.assertGreater(hi, lo)

    def test_the_chunks_are_contiguous_and_in_buffer_order(self) -> None:
        bounds = chunk_bounds(12, 200, 9)
        for (_, hi), (lo, _) in zip(bounds, bounds[1:], strict=False):
            self.assertEqual(hi, lo)

    def test_an_empty_range_is_no_chunks_not_an_error(self) -> None:
        self.assertEqual(chunk_bounds(5, 4, 4), [])


class SerialStaysSerial(unittest.TestCase):
    """``jobs=1`` must not pay for a pool, so a caller can pass it blindly --
    and, more importantly, so the default run of a bug-for-bug port never
    enters code the IDL has no counterpart for."""

    def test_one_job_never_reaches_the_parallel_module(self) -> None:
        import arrayprobe_soda2.process_2d_parallel as par
        calls = []
        real = par.run_parallel_loop
        par.run_parallel_loop = lambda *a, **k: calls.append(k.get("jobs"))
        try:
            with tempfile.TemporaryDirectory() as td:
                soda2_process_2d(_cip_op(Path(td)))
        finally:
            par.run_parallel_loop = real
        self.assertEqual(calls, [], "jobs=1 built a process pool")

    def test_the_default_is_serial(self) -> None:
        import inspect
        sig = inspect.signature(soda2_process_2d)
        self.assertEqual(sig.parameters["jobs"].default, 1)
        self.assertEqual(sig.parameters["chunks"].default, 0)

    def test_zero_or_negative_jobs_is_refused(self) -> None:
        for bad in (0, -1):
            with self.subTest(jobs=bad), self.assertRaises(ValueError):
                with tempfile.TemporaryDirectory() as td:
                    soda2_process_2d(_cip_op(Path(td)), jobs=bad)


class RefusedRatherThanGuessed(unittest.TestCase):
    """Where the loop is not splittable, ``jobs > 1`` raises and names the
    line. The alternative to refusing is a number that is wrong in a way
    nothing downstream would catch."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="soda2par_")
        self.addCleanup(self.tmpdir.cleanup)
        self.op = _cip_op(Path(self.tmpdir.name))

    def test_stuckbits_is_refused_because_lastdhist_is_then_live(self) -> None:
        op = dict(self.op)
        op["stuckbits"] = 1
        with self.assertRaises(Soda2ParallelRefused) as cm:
            soda2_process_2d(op, jobs=2)
        self.assertIn("processbuffer_tail.py:195-196", str(cm.exception))
        self.assertIn("stuckbits", str(cm.exception))

    def test_activetimefrommissed_is_refused_by_line(self) -> None:
        op = dict(self.op)
        op["activetimefrommissed"] = 1
        with self.assertRaises(Soda2ParallelRefused) as cm:
            soda2_process_2d(op, jobs=2)
        self.assertIn("soda2_process_2d.pro:493", str(cm.exception))

    def test_a_refusal_writes_no_file(self) -> None:
        """The refusals run beside the driver's other configuration checks,
        before the PBP writers are opened (`:190-354`) -- so a refused run
        leaves nothing behind. Without this, a refusal would join S6-f's
        family of early exits that leave an open, half-written file."""
        op = dict(self.op)
        op["stuckbits"] = 1
        outdir = Path(op["outdir"])
        with self.assertRaises(Soda2ParallelRefused):
            soda2_process_2d(op, jobs=2)
        self.assertEqual(sorted(p.name for p in outdir.iterdir()), [],
                         "a refused parallel run wrote (and left open) a file")

    def test_a_live_hook_substitution_is_refused(self) -> None:
        """A SODA-2 correction is applied by replacing a module-global binding
        in the parent process. A ``spawn``-started worker inherits none of it,
        so the split would apply the correction to the serial carry-in pass and
        not to the tails -- 97 % of the work. The mixture is refused.

        This is the failure mode that made the whole front/tail refactor
        dangerous: the driver's per-buffer call and every hook inside it are a
        substitution surface, and a split that bypassed them would have gone on
        producing numbers."""
        from arrayprobe_soda2 import enhancement_hooks as hooks

        def not_the_port(*a, **k):  # pragma: no cover - never called
            raise AssertionError("the substitute must not run")

        with hooks.overridden({"fillholes": not_the_port}):
            self.assertFalse(hooks.pristine()["fillholes"], "the fixture did not substitute")
            with self.assertRaises(Soda2ParallelRefused) as cm:
                soda2_process_2d(dict(self.op), jobs=2)
        self.assertIn("fillholes", str(cm.exception))
        self.assertIn("inherits no monkey-patch", str(cm.exception))

    def test_a_rebound_driver_call_is_refused(self) -> None:
        """A 2016 emulation recompiles
        ``processbuffer_spec.py`` and rebinds ``process_2d.soda2_processbuffer``,
        because its target is inline in ``process_spec_buffer`` with no named
        call to patch. The split calls the two halves separately and cannot
        honour a replaced composition."""
        from arrayprobe_soda2 import process_2d as p2d
        orig = p2d.soda2_processbuffer
        p2d.soda2_processbuffer = lambda *a, **k: None  # type: ignore[assignment]
        try:
            with self.assertRaises(Soda2ParallelRefused) as cm:
                soda2_process_2d(dict(self.op), jobs=2)
        finally:
            p2d.soda2_processbuffer = orig  # type: ignore[assignment]
        self.assertIn("soda2_processbuffer", str(cm.exception))

    def test_the_refusal_is_not_a_warning(self) -> None:
        """A ``NotImplementedError`` subclass, so nothing swallows it as a
        soft failure and produces output anyway."""
        self.assertTrue(issubclass(Soda2ParallelRefused, NotImplementedError))


if TYPE_CHECKING:  # the mixin type-checks as a TestCase; at runtime it stays a
    _MixinBase = unittest.TestCase  # plain object so the loader never collects it
else:
    _MixinBase = object


class _IdentityCase(_MixinBase):
    """Shared comparison: every array with ``np.array_equal``, every written
    file byte for byte.

    A **mixin**, not a ``TestCase``: ``unittest``'s loader collects every
    ``TestCase`` subclass in a module whatever it is called, so a
    ``_IdentityCase(TestCase)`` base would be run on its own with no
    ``op_builder`` and report three errors that mean nothing. Concrete cases
    below inherit ``(_IdentityCase, unittest.TestCase)``."""

    op_builder: staticmethod
    jobs = 3
    chunks = 5

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="soda2par_")
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name)
        self.op = type(self).op_builder(self.tmp)

    def _assert_arrays_identical(self, a: _Run, b: _Run, what: str) -> None:
        self.assertFalse(a.meta["none"] or b.meta["none"],
                         "the driver returned None -- the fixture's window is empty, "
                         "so this test would compare nothing")
        compared = [f.name for f in fields(ProcessData) if f.name not in EXCLUDED_FIELDS]
        self.assertGreater(len(compared), 30, "the field list shrank; check ProcessData")
        seen = 0
        for name in compared:
            if name not in a.arrays:
                self.assertNotIn(name, b.arrays, f"{name}: array on one side only")
                with self.subTest(field=name):
                    self.assertEqual(a.meta["scalars"].get(name),
                                     b.meta["scalars"].get(name), f"{what}/{name}")
                continue
            seen += 1
            x, y = a.arrays[name], b.arrays[name]
            with self.subTest(field=name):
                self.assertEqual(x.dtype, y.dtype, f"{what}/{name} dtype")
                self.assertEqual(x.shape, y.shape, f"{what}/{name} shape")
                # array_equal, never allclose: this is a byte-identity claim.
                self.assertTrue(np.array_equal(x, y), f"{what}/{name} values differ")
        self.assertGreater(seen, 25, f"only {seen} arrays were compared")

    def _differing_lines(self, a: _Run, b: _Run, name: str) -> list[int]:
        la = (a.outdir / name).read_text().splitlines()
        lb = (b.outdir / name).read_text().splitlines()
        self.assertEqual(len(la), len(lb), f"{name}: different line counts")
        return [j for j, (u, v) in enumerate(zip(la, lb, strict=True), start=1)
                if u != v]

    def _assert_files_identical(self, a: _Run, b: _Run, what: str) -> list[str]:
        """Every written file, byte for byte where it can be, and by content
        where one non-deterministic string is embedded in it. Returns the names
        of the files that were not byte-identical, so a caller can require that
        the *same* files carry the difference on a serial-vs-serial control."""
        self.assertEqual(sorted(a.files), sorted(b.files),
                         f"{what}: different files were produced")
        self.assertTrue(a.files, "the run wrote no files, so this proves nothing")
        inexact = []
        for name, digest in sorted(a.files.items()):
            with self.subTest(file=name):
                if digest == b.files[name]:
                    continue
                inexact.append(name)
                if name.endswith(".csv"):
                    # `pbp_writer.py:235` writes `Date Processed:
                    # <datetime.now().ctime()>` as line 3. That line, only.
                    self.assertEqual(self._differing_lines(a, b, name), [3],
                                     f"{what}: {name} differs beyond its line-3 "
                                     "timestamp")
                elif name.endswith(".nc"):
                    self._assert_ncdf_identical(a.outdir / name, b.outdir / name, what)
                else:
                    self.fail(f"{what}: {name} differs and has no stated exclusion")
        return inexact

    def _assert_ncdf_identical(self, pa: Path, pb: Path, what: str) -> None:
        """The ``.pbp.nc``: every variable with ``np.array_equal``, every
        attribute but ``DateProcessed`` (``pbp_writer.py:319``,
        ``datetime.now().ctime()``). The file's bytes differ only in those 24
        characters -- but asserting on a byte offset would be asserting on
        netCDF3's header layout, so this asserts on the content instead."""
        import netCDF4
        x, y = netCDF4.Dataset(pa), netCDF4.Dataset(pb)
        try:
            self.assertEqual(sorted(x.variables), sorted(y.variables))
            for v in sorted(x.variables):
                xa, ya = np.asarray(x[v][:]), np.asarray(y[v][:])
                self.assertEqual(xa.dtype, ya.dtype, f"{what}: {pa.name}/{v} dtype")
                self.assertTrue(np.array_equal(xa, ya),
                                f"{what}: {pa.name}/{v} values differ")
            self.assertEqual(sorted(x.ncattrs()), sorted(y.ncattrs()))
            differing = [k for k in x.ncattrs()
                         if repr(x.getncattr(k)) != repr(y.getncattr(k))]
            self.assertEqual(differing, ["DateProcessed"],
                             f"{what}: {pa.name} attributes differ beyond "
                             "DateProcessed")
        finally:
            x.close()
            y.close()

    def test_every_process_data_array_is_identical(self) -> None:
        ser = _run_driver(self.op, self.tmp, "ser", jobs=1)
        par = _run_driver(self.op, self.tmp, "par", jobs=self.jobs, chunks=self.chunks)
        self._assert_arrays_identical(ser, par, "serial-vs-parallel")

    def test_every_written_file_is_identical_apart_from_its_timestamp(self) -> None:
        ser = _run_driver(self.op, self.tmp, "serf", jobs=1)
        par = _run_driver(self.op, self.tmp, "parf", jobs=self.jobs, chunks=self.chunks)
        self.par_inexact = self._assert_files_identical(ser, par, "serial-vs-parallel")

    def test_two_serial_runs_carry_the_same_one_difference(self) -> None:
        """The control for the exclusions above, drawn from a different place
        (*a check must draw its two sides from different places*):
        two runs with **no parallelism in either** must differ in exactly the
        same way. If a future change made the timestamps deterministic, this
        fails and the exclusions above stop being excused."""
        a = _run_driver(self.op, self.tmp, "sa", jobs=1)
        time.sleep(1.1)  # so `ctime()`, which has 1 s resolution, actually moves
        b = _run_driver(self.op, self.tmp, "sb", jobs=1)
        self._assert_arrays_identical(a, b, "serial-vs-serial")
        inexact = self._assert_files_identical(a, b, "serial-vs-serial")
        self.assertTrue(
            inexact,
            "two SERIAL runs a second apart produced byte-identical files, so the "
            "timestamp exclusion in the parallel tests is excusing a difference "
            "that serial runs do not actually have -- tighten those tests.")


@unittest.skipUnless(CIP_FIXTURE.is_file(), f"missing fixture {CIP_FIXTURE}")
@slow  # real process pools through a bounded subprocess; the family
# tests/test_spec_parallel.py::ParallelMatchesSerial is gated for.
class ParallelMatchesSerialCip(_IdentityCase, unittest.TestCase):
    """The SEA/CIP route -- the one tonight's CIP deliverable runs, and the
    configuration ``test_soda2_cip_driver.py`` asserts against GDL."""

    op_builder = staticmethod(_cip_op)


@unittest.skipUnless(SPEC_FIXTURE.is_file(), f"missing fixture {SPEC_FIXTURE}")
@slow  # same family as ParallelMatchesSerialCip above.
class ParallelMatchesSerialSpec(_IdentityCase, unittest.TestCase):
    """The SPEC route, whose carry-in chain is three scalars rather than two
    (``lastclock``, ``lastbufftime``, ``maxsfm``) -- and ``maxsfm`` is the one
    that chains only across buffers sharing a ``buffer.time``, so it is the
    field a carry-in bug would show up in first."""

    op_builder = staticmethod(_spec_op)
    jobs = 2
    chunks = 3


@unittest.skipUnless(DMT_FIXTURE.is_file(), f"missing fixture {DMT_FIXTURE}")
@slow  # same family as ParallelMatchesSerialCip above.
@needs_file("tests/test_soda2_dmt_driver.py")  # its fixture helpers
class ParallelMatchesSerialDmt(_IdentityCase, unittest.TestCase):
    """The DMT/PADS route: the CIP carry-in chain (``lastclock``,
    ``lastparticlecount``) through ``read2dbuffer_dmt``'s buffers, which carry
    no ``stoptime``, and the forward deadtime of ``soda2_particlesort.pro:126``."""

    op_builder = staticmethod(_dmt_op)
    jobs = 2
    chunks = 4


@unittest.skipUnless(CIP_FIXTURE.is_file(), f"missing fixture {CIP_FIXTURE}")
@slow  # same family.
class MoreChunksThanBuffers(unittest.TestCase):
    """Over-partitioning must not be an error, and must not change a byte.

    Worth pinning for the reason ``test_spec_parallel.py`` pins it for the
    decode: the split is computed from a count, and an empty range must be
    dropped rather than handed to a worker."""

    def test_sixty_four_chunks_over_a_handful_of_buffers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="soda2par_") as td:
            tmp = Path(td)
            op = _cip_op(tmp)
            ser = _run_driver(op, tmp, "s", jobs=1)
            par = _run_driver(op, tmp, "p", jobs=3, chunks=64)
            for name in sorted(ser.arrays):
                with self.subTest(field=name):
                    self.assertTrue(np.array_equal(ser.arrays[name], par.arrays[name]),
                                    f"{name} differs at chunks=64")

# _release_fixture_guard: real-data derived fixtures are excluded from the release
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402

_RFG_EXCLUDED = ('dmt_raw_synthetic.cip',)
if not all((_rfg_pathlib.Path(__file__).resolve().parent / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "real-data derived fixtures (UIOPS PECAN DMT / minimal-example 2D-S samples) "
        "are not shipped in the release")

if __name__ == "__main__":
    unittest.main()
