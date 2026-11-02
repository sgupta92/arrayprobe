# SPDX-License-Identifier: BSD-3-Clause
"""``jobs > 1`` **with the SODA-2 corrections live** -- the acceptance condition.

The author's ruling is that the default every non-ORACLES number comes from is the corrected
engine at its fastest settings, so *fast* and *corrected* must not be a choice. Until this was built
they were: ``process_2d_parallel.refuse_unsplittable`` refused ``jobs > 1`` whenever anything
was substituted through ``arrayprobe_soda2.enhancement_hooks``, because a correction is a
**function object** installed on a module global and a ``spawn``-started worker re-imports the
package and inherits none of it. ``arrayprobe soda2 run --jobs 4`` therefore exited 2 with the
enhancement package installed.

What this module asserts, and why each half is here
---------------------------------------------------

1. **The split reproduces the serial run exactly, with the corrections on.** Every
   ``ProcessData`` array with ``np.array_equal`` and every written file byte for byte, the
   same comparison ``test_soda2_parallel.py`` makes for the corrections-*off* case, reusing
   its ``_IdentityCase`` helpers rather than a second written form of them. A speed-up that
   moves a number is a defect here, not a trade-off.

2. **The corrections actually ran in the worker.** Byte-identity alone is *necessary and not
   sufficient*, and this lane has already been bitten by exactly that: a tidier refactor once
   produced byte-identical output with every correction silently bypassed. So
   :class:`TheWorkerReallyInstallsThem` starts a real ``ProcessPoolExecutor`` through the
   module's own initializer and reads back what the worker process has substituted, and
   :class:`CorrectedIsNotTheSameAsUncorrected` shows the corrections move a written byte on
   this fixture -- so "identical" above is not identical-because-nothing-happened.

3. **What still cannot be rebuilt by name is still refused.** The refusal narrowed from *any*
   live substitution to *a substitution this process cannot rebuild*; an ad-hoc callable
   passed straight to ``overridden`` has no reconstruction plan and stays refused, and so does
   the 2016 UND emulation's rebound driver call.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import numpy as np
from tests._optional import importable
from tests._slow import slow

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from arrayprobe_soda2.process_2d_parallel import Soda2ParallelRefused  # noqa: E402
from test_soda2_parallel import (  # noqa: E402  (after the sys.path insert)
    CIP_FIXTURE,
    RUN_TIMEOUT_S,
    _cip_op,
    _IdentityCase,
    _Run,
)

# Asked of a fresh interpreter, as the driver subprocess below will be: an in-process import
# can succeed after a sibling test module changed sys.path (CI, 2026-10-01), while the driver
# then fails to import the package and the test fails instead of skipping.
HAVE_PACKAGE = importable("arrayprobe_soda2_enhancements")

#: The driver run, out of process, with the shipped corrections resolved and applied exactly
#: the way ``arrayprobe soda2 run`` applies them (``cli.py:1343-1349``) -- so what this test
#: proves is what the CLI does, not a test-only arrangement of the same parts.
_CHILD = textwrap.dedent("""
    import faulthandler, json, pickle, sys
    from dataclasses import fields
    from pathlib import Path
    import numpy as np

    op_path, out_path, jobs, chunks, timeout_s, enh = sys.argv[1:7]
    faulthandler.dump_traceback_later(
        max(1.0, float(timeout_s) - 15), exit=False, file=sys.stderr)

    from arrayprobe_soda2 import enhancement_hooks
    from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d
    op = pickle.loads(Path(op_path).read_bytes())

    def run():
        return soda2_process_2d(op, jobs=int(jobs), chunks=int(chunks))

    record = {}
    if int(enh) != 0:
        from arrayprobe_soda2_enhancements.registry import apply, load_all, resolve
        load_all()
        with apply(resolve({n: True for n in load_all()})) as rec:
            record = {"applied": rec["applied"], "hook_points": rec["hook_points"],
                      # Read INSIDE the with block: what this process had substituted
                      # while the driver ran, observed rather than echoed.
                      "active": sorted(enhancement_hooks.active()),
                      # `getattr`, so that on a tree WITHOUT the fix this child
                      # still runs and the failure reported is the substantive one --
                      # the parallel run's refusal -- rather than an AttributeError on
                      # the instrumentation.
                      "plan": getattr(getattr(enhancement_hooks, "reconstruction_plan",
                                              lambda: None)(), "factory", None)}
            d = run()
    else:
        d = run()
        record = {"applied": [], "hook_points": {},
                  "active": sorted(enhancement_hooks.active()), "plan": None}
    if d is None:
        Path(out_path + ".json").write_text(json.dumps({"none": True, "enh": record}))
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
         "enh": record}))
""")


def _run_driver(op: dict, tmp: Path, tag: str, *, jobs: int, chunks: int = 0,
                enhancements: bool = True) -> _Run:
    """One driver run, out of process, bounded -- ``test_soda2_parallel._run_driver`` with
    one more axis. Same one shared output directory for the reason given there: two runs in
    two directories differ in bytes that have nothing to do with the split."""
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
            str(chunks), str(RUN_TIMEOUT_S), str(int(bool(enhancements)))]
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=RUN_TIMEOUT_S, cwd=str(HERE.parent))
    except subprocess.TimeoutExpired as exc:
        err = exc.stderr
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        raise AssertionError(
            f"soda2_process_2d(jobs={jobs}, enhancements={enhancements}) did not finish in "
            f"{RUN_TIMEOUT_S}s on a tracked fixture; see test_soda2_parallel._run_driver's "
            "note on the WinError 6 spawn-handle class of hang.\n"
            + (err or "")[-3000:]) from exc
    if done.returncode != 0:
        raise AssertionError(
            f"the driver subprocess exited {done.returncode} "
            f"(jobs={jobs}, enhancements={enhancements})\n"
            f"stdout: {done.stdout[-2000:]}\nstderr: {done.stderr[-3000:]}")
    meta = json.loads(Path(str(stem) + ".json").read_text())
    kept = tmp / f"{tag}.out.d"
    if kept.exists():
        shutil.rmtree(kept)
    shutil.copytree(live, kept)
    run = _Run(Path(str(stem) + ".npz"), meta, kept)
    run.enh = meta["enh"]  # type: ignore[attr-defined]
    return run


@unittest.skipUnless(HAVE_PACKAGE, "arrayprobe-soda2-enhancements is not installed")
class TheWorkerReallyInstallsThem(unittest.TestCase):
    """The mechanism, read back from a real worker process rather than argued about.

    Cheap (no driver run), and it is the half that byte-identity cannot prove: it observes
    ``enhancement_hooks.active()`` *inside* a spawned worker started through this module's own
    ``_init_worker``, which is the code path a split run uses."""

    def _plan(self):
        from arrayprobe_soda2_enhancements._adapter import WORKER_FACTORY
        from arrayprobe_soda2_enhancements.registry import load_all, resolve

        from arrayprobe_soda2 import enhancement_hooks
        load_all()
        return enhancement_hooks.Reconstruction(
            factory=WORKER_FACTORY,
            payload={k: bool(v) for k, v in sorted(resolve({n: True for n in load_all()}).items())})

    def test_the_plan_is_plain_data_and_pickles(self) -> None:
        """The property the whole fix rests on: what crosses to the worker is a string and a
        dict of booleans, not a closure. A function object would not pickle at all."""
        import pickle
        plan = self._plan()
        again = pickle.loads(pickle.dumps(plan))
        self.assertEqual(again, plan)
        self.assertIsInstance(plan.factory, str)
        self.assertTrue(all(isinstance(k, str) and isinstance(v, bool)
                            for k, v in plan.payload.items()))

    def test_a_spawned_worker_has_every_hook_point_substituted(self) -> None:
        from concurrent.futures import ProcessPoolExecutor

        from arrayprobe_soda2.process_2d_parallel import _init_worker, worker_substitution

        plan = self._plan()
        # `ctx` and `misc_template` are not read by `worker_substitution`, so this probes the
        # substitution half of the initializer and nothing else.
        with ProcessPoolExecutor(max_workers=1, initializer=_init_worker,
                                 initargs=(None, None, plan)) as pool:
            in_worker = pool.submit(worker_substitution).result(timeout=120)
        from arrayprobe_soda2 import enhancement_hooks
        self.assertEqual(len(in_worker), len(enhancement_hooks.HOOK_POINTS),
                         "the worker did not install every shipped correction")
        for point, qualname in sorted(in_worker.items()):
            with self.subTest(point=point):
                self.assertTrue(qualname.startswith("arrayprobe_soda2_enhancements"),
                                f"{point} in the worker is {qualname}, not a correction")

    def test_this_process_is_pristine_so_the_worker_result_is_not_inherited(self) -> None:
        """The control: nothing is substituted *here*, so the twelve points the worker
        reported were installed by the worker itself."""
        from arrayprobe_soda2 import enhancement_hooks
        self.assertEqual(enhancement_hooks.active(), {})
        self.assertIsNone(enhancement_hooks.reconstruction_plan())


@unittest.skipUnless(HAVE_PACKAGE, "arrayprobe-soda2-enhancements is not installed")
class RefusedWhenItCannotBeRebuilt(unittest.TestCase):
    """The narrowed refusal: *this process cannot rebuild it*, not *anything is substituted*."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="soda2enh_")
        self.addCleanup(self.tmpdir.cleanup)
        self.op = _cip_op(Path(self.tmpdir.name))

    def test_an_ad_hoc_callable_with_no_plan_is_still_refused(self) -> None:
        from arrayprobe_soda2 import enhancement_hooks as hooks
        from arrayprobe_soda2.process_2d import soda2_process_2d

        def not_the_port(*a, **k):  # pragma: no cover - never called
            raise AssertionError("the substitute must not run")

        with hooks.overridden({"fillholes": not_the_port}):
            self.assertIsNone(hooks.reconstruction_plan())
            with self.assertRaises(Soda2ParallelRefused) as cm:
                soda2_process_2d(dict(self.op), jobs=2)
        self.assertIn("no reconstruction plan", str(cm.exception))

    def test_a_plan_that_rebuilds_different_points_is_refused_at_install(self) -> None:
        """The plan is checked, not trusted: ``overridden`` calls the factory and compares
        the point names, so a plan that has drifted from the substitution fails here rather
        than quietly carrying a different set of corrections into a worker."""
        from arrayprobe_soda2_enhancements._adapter import WORKER_FACTORY
        from arrayprobe_soda2_enhancements.registry import load_all, resolve

        from arrayprobe_soda2 import enhancement_hooks as hooks
        load_all()
        full = {k: bool(v) for k, v in resolve({n: True for n in load_all()}).items()}
        plan = hooks.Reconstruction(factory=WORKER_FACTORY, payload=full)
        with self.assertRaises(hooks.HookError) as cm:
            with hooks.overridden({"fillholes": lambda *a, **k: None},
                                  reconstruction=plan):
                pass  # pragma: no cover - the install must raise
        self.assertIn("rebuilds hook points", str(cm.exception))

    def test_a_factory_that_is_not_module_colon_callable_is_refused(self) -> None:
        from arrayprobe_soda2 import enhancement_hooks as hooks
        plan = hooks.Reconstruction(factory="no_colon_here", payload={})
        with self.assertRaises(hooks.HookError) as cm:
            with hooks.overridden({"fillholes": lambda *a, **k: None}, reconstruction=plan):
                pass  # pragma: no cover
        self.assertIn("module:callable", str(cm.exception))


@unittest.skipUnless(HAVE_PACKAGE, "arrayprobe-soda2-enhancements is not installed")
@unittest.skipUnless(CIP_FIXTURE.is_file(), f"missing fixture {CIP_FIXTURE}")
@slow  # real process pools through a bounded subprocess; the family
# tests/test_soda2_parallel.py::ParallelMatchesSerialCip is gated for.
class ParallelMatchesSerialWithCorrectionsOn(_IdentityCase, unittest.TestCase):
    """**The acceptance condition.** The whole point of the work: with every shipped
    SODA-2 correction applied, the split run and the serial run are the same run."""

    op_builder = staticmethod(_cip_op)
    jobs = 3
    chunks = 5

    def _assert_corrections_ran(self, run: _Run, what: str) -> None:
        enh = run.enh  # type: ignore[attr-defined]
        self.assertTrue(enh["applied"], f"{what}: no correction was applied at all")
        self.assertEqual(len(enh["active"]), 12,
                         f"{what}: {len(enh['active'])} hook points were live, not 12")
        self.assertIsNotNone(enh["plan"], f"{what}: the substitution carried no plan")

    def test_every_process_data_array_is_identical(self) -> None:
        ser = _run_driver(self.op, self.tmp, "eser", jobs=1)
        par = _run_driver(self.op, self.tmp, "epar", jobs=self.jobs, chunks=self.chunks)
        self._assert_corrections_ran(ser, "serial")
        self._assert_corrections_ran(par, "parallel")
        self._assert_arrays_identical(ser, par, "corrected serial-vs-parallel")

    def test_every_written_file_is_identical_apart_from_its_timestamp(self) -> None:
        ser = _run_driver(self.op, self.tmp, "eserf", jobs=1)
        par = _run_driver(self.op, self.tmp, "eparf", jobs=self.jobs, chunks=self.chunks)
        self._assert_corrections_ran(par, "parallel")
        self._assert_files_identical(ser, par, "corrected serial-vs-parallel")

    def test_two_serial_runs_carry_the_same_one_difference(self) -> None:
        """The exclusions' control, with the corrections on: two runs with no parallelism in
        either must differ in exactly the same one place."""
        a = _run_driver(self.op, self.tmp, "esa", jobs=1)
        time.sleep(1.1)  # so `ctime()`, which has 1 s resolution, actually moves
        b = _run_driver(self.op, self.tmp, "esb", jobs=1)
        self._assert_arrays_identical(a, b, "corrected serial-vs-serial")
        self.assertTrue(self._assert_files_identical(a, b, "corrected serial-vs-serial"),
                        "two serial corrected runs a second apart were byte-identical, so "
                        "the timestamp exclusion above excuses a difference that does not "
                        "exist -- tighten it")


@unittest.skipUnless(HAVE_PACKAGE, "arrayprobe-soda2-enhancements is not installed")
@unittest.skipUnless(CIP_FIXTURE.is_file(), f"missing fixture {CIP_FIXTURE}")
@slow  # same family.
class CorrectedIsNotTheSameAsUncorrected(unittest.TestCase):
    """Non-vacuity. Byte-identity between two runs proves nothing if the corrections move no
    byte on this fixture -- the identity test above would then pass with the substitution
    bypassed entirely. So: corrected and uncorrected must DIFFER, and the difference must be
    the same whether the corrected run was split or not."""

    def test_the_corrections_change_the_product_and_the_split_does_not(self) -> None:
        with tempfile.TemporaryDirectory(prefix="soda2enh_") as td:
            tmp = Path(td)
            op = _cip_op(tmp)
            off = _run_driver(op, tmp, "off", jobs=1, enhancements=False)
            on_ser = _run_driver(op, tmp, "ons", jobs=1, enhancements=True)
            on_par = _run_driver(op, tmp, "onp", jobs=3, chunks=5, enhancements=True)
            self.assertEqual(off.enh["active"], [],  # type: ignore[attr-defined]
                             "the enhancements-off run had a substitution live")
            differing = sorted(name for name in off.arrays
                               if not np.array_equal(off.arrays[name],
                                                     on_ser.arrays.get(name)))
            self.assertTrue(
                differing,
                "every ProcessData array is the same with the corrections on as with them "
                "off, on this fixture -- so the byte-identity test above cannot distinguish "
                "'the split preserved the corrections' from 'the split dropped them'. Pick "
                "a fixture the corrections reach, or assert engagement instead.")
            for name in differing:
                with self.subTest(field=name):
                    self.assertTrue(
                        np.array_equal(on_ser.arrays[name], on_par.arrays[name]),
                        f"{name} differs between corrected serial and corrected parallel")


if __name__ == "__main__":
    unittest.main()
