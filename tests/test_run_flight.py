# SPDX-License-Identifier: BSD-3-Clause
"""``scripts/run_flight.py`` -- the skip/redo decision.

The runner's whole restart story rests on one assumption: *an existing output is
a finished output, produced by the call I am about to make*.  The first half of
that has been true since the ``_inflight``/``.partial`` staging went in.  The
second half was silently false until 2026-08-20.

``sizeDist``'s optional twelfth argument decides whether inter-arrival shattering
identification runs at all (``sizeDist.m:866``), and the two calls differ by 58%
of the accepted particles on the 09/06/2016 2D-S flight.  The product cannot be
asked which one it was: ``:1693-1704`` writes ``Shattering Algorithm`` from
``applyIntArrThresh`` alone, so a file built with no twelfth argument claims the
algorithm was applied when nothing ran.  Hence a ``.call`` sidecar,
and hence these tests -- the failure they guard against is a run that *skips* work
it should have redone, which produces no error and a plausible-looking file.

The default call is :data:`run_flight.IAT_FILE`, the ORACLES production form,
which is what reproduces the archived product.  These tests pin the *mechanism*,
not that default: they must keep passing if the default ever changes, so every
case names its call explicitly.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4

#: Tests here call ``register_profile()``, which mutates a module-level registry
#: that outlives the test. Nothing restored it, so a profile registered by one
#: test stayed visible to every later test IN THE WHOLE SUITE -- and
#: ``test_docs_site.test_profile_table_matches_profiles_py`` reads that live
#: registry, so it passed alone and failed under ``unittest discover`` (found
#: 2026-09-10). Snapshot and restore, so registering is local to this file.
_REGISTRY_BEFORE: dict = {}


# The shared helper also restores _V35_TREE_PROFILES, the register-once caches
# and the registering modules' sys.modules entries (tests/_profile_registry_guard.py).
from tests import _run_flight_state  # noqa: E402
from tests._profile_registry_guard import module_hooks  # noqa: E402
from tests._repo import needs_v314_engine  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "run_flight", Path(__file__).resolve().parent.parent / "scripts" / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)

# The registry restore and the driver-state restore both run as module cleanups, so
# they unwind in reverse of setup: run_flight's globals first, then the registry.
_registry_setup, _registry_teardown = module_hooks()


def setUpModule():  # noqa: N802 -- unittest's name
    _registry_setup()
    unittest.addModuleCleanup(_registry_teardown)
    _run_flight_state.preserve_module(run_flight)


STEM = "base160906064403"


class LoadTasInfoTests(unittest.TestCase):
    """``load_tas_info`` -- the port of ``loadTASinfo_2DS.m``, already load-bearing
    for S4 (``sd_step`` reads TAS through it) but previously untested on its own.

    Matches the shim's own documented contract
    (``octave_oracle/shims/loadTASinfo_2DS.m``): a nine-column CSV, only the
    first two columns (``timehhmmss``, ``tas``) kept, and a trailing all-zero
    row -- MATLAB's ``dlmread`` artifact from a file ending in a newline --
    dropped rather than treated as a real (0, 0) sample.
    """

    def _write(self, tmp, rows):
        path = Path(tmp) / "t.tas.csv"
        path.write_text("\n".join(",".join(str(v) for v in row) for row in rows) + "\n")
        return path

    def test_first_two_columns_are_time_and_tas(self):
        rows = [
            [164129.0, 170.5, 0, 0, 0, 0, 0, 0, 0],
            [164130.0, 171.2, 0, 0, 0, 0, 0, 0, 0],
        ]
        with tempfile.TemporaryDirectory() as d:
            timehhmmss, tas = run_flight.load_tas_info(self._write(d, rows))
        self.assertEqual(list(timehhmmss), [164129.0, 164130.0])
        self.assertEqual(list(tas), [170.5, 171.2])

    def test_trailing_all_zero_row_is_dropped(self):
        rows = [
            [164129.0, 170.5, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
        ]
        with tempfile.TemporaryDirectory() as d:
            timehhmmss, tas = run_flight.load_tas_info(self._write(d, rows))
        self.assertEqual(list(timehhmmss), [164129.0])
        self.assertEqual(list(tas), [170.5])

    def test_a_genuine_zero_tas_row_survives_if_not_trailing(self):
        """The drop rule is specifically the *last* row, not any zero row."""
        rows = [
            [164129.0, 0.0, 0, 0, 0, 0, 0, 0, 0],
            [164130.0, 171.2, 0, 0, 0, 0, 0, 0, 0],
        ]
        with tempfile.TemporaryDirectory() as d:
            timehhmmss, tas = run_flight.load_tas_info(self._write(d, rows))
        self.assertEqual(list(timehhmmss), [164129.0, 164130.0])
        self.assertEqual(list(tas), [0.0, 171.2])

    def test_single_row_no_trailing_zero_is_kept(self):
        rows = [[164129.0, 170.5, 0, 0, 0, 0, 0, 0, 0]]
        with tempfile.TemporaryDirectory() as d:
            timehhmmss, tas = run_flight.load_tas_info(self._write(d, rows))
        self.assertEqual(list(timehhmmss), [164129.0])
        self.assertEqual(list(tas), [170.5])


class CallLabelTests(unittest.TestCase):
    def test_no_threshold_file_and_a_named_one_are_different_labels(self):
        self.assertNotEqual(run_flight.iat_call_label(None),
                            run_flight.iat_call_label("2DS_intArrThreshold.cdf"))

    def test_label_is_stable_for_the_same_call(self):
        # Two separate calls: the label must not depend on call order or hidden state.
        first = run_flight.iat_call_label(None)
        second = run_flight.iat_call_label(None)
        self.assertEqual(first, second)

    def test_empty_string_is_the_no_file_call(self):
        # argparse hands back '' for `--iat-file ''`, and MATLAB's
        # `length(varargin) == 1` would be TRUE for it -- but the runner treats a
        # blank as "not given", so the label must agree with what stage4 does.
        self.assertEqual(run_flight.iat_call_label(""), run_flight.iat_call_label(None))


class SdIsCurrentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.sd = self.out / f"sd.{STEM}.H.nc"
        self.call = self.out / f"sd.{STEM}.H.nc.call"
        self.addCleanup(self._tmp.cleanup)

    def test_absent_output_is_not_current(self):
        self.assertFalse(run_flight.sd_is_current(self.out, STEM, None))

    def test_output_with_a_matching_call_is_current(self):
        self.sd.touch()
        self.call.write_text(run_flight.sd_call_label(None) + "\n")
        self.assertTrue(run_flight.sd_is_current(self.out, STEM, None))

    def test_output_built_with_the_other_call_is_NOT_current(self):
        """The regression that motivated the sidecar, in both directions."""
        self.sd.touch()
        self.call.write_text(run_flight.sd_call_label(None))
        self.assertFalse(
            run_flight.sd_is_current(self.out, STEM, run_flight.IAT_FILE))
        self.call.write_text(run_flight.sd_call_label(run_flight.IAT_FILE))
        self.assertFalse(run_flight.sd_is_current(self.out, STEM, None))

    def test_output_with_no_sidecar_is_not_current(self):
        """Every sd file written before 2026-08-20 is in this state.

        Fails CLOSED: an unlabelled file is redone rather than trusted, for
        either call.  Guessing which one produced it is exactly the inference the
        sidecar exists to make unnecessary.
        """
        self.sd.touch()
        self.assertFalse(run_flight.sd_is_current(self.out, STEM, None))
        self.assertFalse(
            run_flight.sd_is_current(self.out, STEM, run_flight.IAT_FILE))

    def test_a_sidecar_without_its_output_is_not_current(self):
        self.call.write_text(run_flight.sd_call_label(None))
        self.assertFalse(run_flight.sd_is_current(self.out, STEM, None))

    def test_trailing_whitespace_in_the_sidecar_is_tolerated(self):
        self.sd.touch()
        self.call.write_text(run_flight.sd_call_label(None) + "\n\n")
        self.assertTrue(run_flight.sd_is_current(self.out, STEM, None))


class Stage4DoesNotDestroyExistingOutputTests(unittest.TestCase):
    """Real incident, 2026-08-27: ``stage4`` used to ``target.unlink()`` the
    moment it decided a redo was needed, *before* checking whether the redo
    could actually happen. Running ``--stages 4`` on a file whose ``.call``
    sidecar didn't match, when its ``proc.*.nc`` had *also* separately been
    lost, deleted the last surviving ``sd.*.nc`` for two real flights
    (``base160906075333``, ``base160906095907``) and then bailed out with
    nothing to replace it -- a real, silent, unrecoverable data-loss bug
    (``Path.unlink()`` does not go through the Recycle Bin on Windows).

    The fix: don't delete the stale target at all. ``os.replace(partial,
    target)`` on the success path already overwrites it atomically once a
    real replacement exists; the explicit unlink was never load-bearing for
    that path and was the entire bug on the failure path.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.sd = self.out / f"sd.{STEM}.H.nc"
        self.call = self.out / f"sd.{STEM}.H.nc.call"
        self.proc_file = self.out / f"proc.{STEM}.H.nc"   # deliberately never created
        self.sentinel = b"the only surviving copy"
        self.sd.write_bytes(self.sentinel)
        # A stale/missing .call sidecar is exactly what triggers "S4 redo".
        self.call.write_text(run_flight.iat_call_label(None))

    def test_redo_needed_but_proc_file_missing_leaves_existing_sd_untouched(self):
        result = run_flight.stage4(self.proc_file, STEM, self.out,
                                    iat_file=run_flight.IAT_FILE)
        self.assertTrue(self.sd.exists(),
                         "stage4 deleted the existing sd file without replacing it")
        self.assertEqual(self.sd.read_bytes(), self.sentinel)
        self.assertEqual(result, self.sd)

    def test_redo_needed_but_tas_csv_missing_leaves_existing_sd_untouched(self):
        # proc_file present this time, but the TAS sidecar (checked first) is not.
        # It is stamped, so this stays a test of the redo path rather than of the
        # provenance refusal (which has its own tests, and is checked earlier).
        self.proc_file.touch()
        run_flight.write_stamp(self.proc_file, run_flight.proc_call_label())
        result = run_flight.stage4(self.proc_file, STEM, self.out,
                                    iat_file=run_flight.IAT_FILE)
        self.assertTrue(self.sd.exists())
        self.assertEqual(self.sd.read_bytes(), self.sentinel)
        self.assertEqual(result, self.sd)


class Stage3ChunkTests(unittest.TestCase):
    """S3 must be asked for ONE chunk covering the whole file.

    ``imgProc_sm``'s ``n``/``nEvery`` select a chunk, not a stride: records
    ``(n-1)*nEvery + 1`` .. ``min(n*nEvery, img_count)``.  The runner passed
    ``n = nEvery = 1`` until 2026-08-20, which is "the chunk containing record 1",
    so each file yielded only its first record's particles -- 1 for
    ``base160906075333``, 122 for ``base160906095907``, against 73,429 from the
    first 500 records of the same file when asked correctly.

    It never errored and the proc files it wrote were structurally valid, so the
    only signal was a particle count that looked low, and low is not obviously
    wrong for a probe. That is what makes it worth a test rather than a comment.
    """

    @needs_v314_engine
    def test_stage3_asks_for_every_record_in_one_chunk(self):
        seen = {}

        def fake_imgproc_sm(infile, outfile, probename, n, n_every, project, **kw):
            seen.update(n=n, n_every=n_every)
            Path(outfile).touch()

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            image = out / f"{STEM}.H.cdf"
            image.touch()
            real_count = run_flight.image_record_count
            real_proc = run_flight.imgproc.imgproc_sm
            real_log = run_flight.log
            run_flight.image_record_count = lambda _p: 227590
            run_flight.imgproc.imgproc_sm = fake_imgproc_sm
            try:
                run_flight.log = lambda _m: None
                run_flight.stage3(image, out)
            finally:
                # log was never restored before 2026-09-13: every later module sharing
                # this run_flight object then printed nothing, and four arrayprobe-run
                # refusal tests that read the printed reason failed in the suite.
                run_flight.log = real_log
                run_flight.image_record_count = real_count
                run_flight.imgproc.imgproc_sm = real_proc

        self.assertEqual(seen["n"], 1, "n must be 1: the first (and only) chunk")
        self.assertEqual(seen["n_every"], 227590,
                         "nEvery must span the file, or records are silently dropped")


class _FakeProc:
    """A finished worker, as ``stage3``'s bounded wait (P10) sees one: it polls
    rather than blocks, so a fake needs ``poll`` and a ``pid``, not only ``wait``."""

    pid = 0

    def __init__(self, rc):
        self._rc = rc

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        return self._rc


def _write_empty_chunk(chunk_path: Path) -> None:
    """What a successful worker leaves: a chunk file whose ``time`` dimension the
    parent reads, and the ``.done`` record claiming the same count (P10)."""
    with netCDF4.Dataset(str(chunk_path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", 0)
    chunk_path.with_name(chunk_path.name + ".done").write_text("0\n")


class Stage3ChunkedTests(unittest.TestCase):
    """S3p tier 3 wired in: ``chunks > 1`` spawns one subprocess per chunk and
    merges the results, rather than running everything in one call."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.image = self.out / f"{STEM}.H.cdf"
        self.image.touch()
        self._real_count = run_flight.image_record_count
        self._real_popen = run_flight.subprocess.Popen
        self._real_merge = run_flight.imgproc.merge_chunks
        self._real_log = run_flight.log
        run_flight.image_record_count = lambda _p: 1000
        run_flight.log = lambda *a, **kw: None
        self.addCleanup(setattr, run_flight, "image_record_count", self._real_count)
        self.addCleanup(setattr, run_flight.subprocess, "Popen", self._real_popen)
        self.addCleanup(setattr, run_flight.imgproc, "merge_chunks", self._real_merge)
        self.addCleanup(setattr, run_flight, "log", self._real_log)

    def _fake_popen_touching_output(self):
        """Each spawned worker's command ends in the chunk path it must write;
        the fake just touches it, standing in for a real imgproc_sm call."""
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            # [sys.executable, script, "--_run-chunk", image, probe, project,
            #  profile_name, profile_module, tas_file, worker_stall_min,
            #  chunk_path, n, n_every]
            _write_empty_chunk(Path(cmd[10]))
            return _FakeProc(0)
        run_flight.subprocess.Popen = fake_popen
        return seen_cmds

    @needs_v314_engine
    def test_spawns_one_worker_per_chunk_with_ceil_divided_n_every(self):
        seen_cmds = self._fake_popen_touching_output()
        merged = {}
        run_flight.imgproc.merge_chunks = (
            lambda paths, outfile, *a, **kw: merged.update(paths=paths, outfile=outfile)
            or Path(outfile).touch()
        )
        run_flight.stage3(self.image, self.out, chunks=3)
        self.assertEqual(len(seen_cmds), 3)
        # 1000 records / 3 chunks -> n_every = 334 (ceil), chunk indices 1..3
        indices_and_n_every = [(cmd[11], cmd[12]) for cmd in seen_cmds]
        self.assertEqual(indices_and_n_every, [("1", "334"), ("2", "334"), ("3", "334")])
        # PROBE/PROJECT/PROFILE are threaded to each worker's command line so a
        # fresh subprocess doesn't silently fall back to this module's import-time
        # defaults (found while generalising PROFILE).
        for cmd in seen_cmds:
            self.assertEqual(cmd[4], run_flight.PROBE)
            self.assertEqual(cmd[5], run_flight.PROJECT)
            self.assertEqual(cmd[6], run_flight.PROFILE.name)
            # PROFILE_MODULE travels the same way (2026-09-10); "" means
            # "nothing to import", the shipped-profile case this default run is.
            self.assertEqual(cmd[7], "")
            self.assertEqual(cmd[8], "")      # TAS_FILE: none in this default run
            self.assertEqual(cmd[9], "30.0")  # the default --worker-stall-min
        self.assertEqual(len(merged["paths"]), 3)

    @needs_v314_engine
    def test_chunk_files_are_cleaned_up_after_a_successful_merge(self):
        self._fake_popen_touching_output()
        chunk_paths_seen = []

        def fake_merge(paths, outfile, *a, **kw):
            chunk_paths_seen.extend(paths)
            for p in paths:
                self.assertTrue(Path(p).exists(), "merge must see the chunk files")
            Path(outfile).touch()
        run_flight.imgproc.merge_chunks = fake_merge
        run_flight.stage3(self.image, self.out, chunks=2)
        for p in chunk_paths_seen:
            self.assertFalse(Path(p).exists(), "chunk files must not survive a successful run")

    @needs_v314_engine
    def test_a_failed_chunk_raises_and_does_not_call_merge(self):
        run_flight.subprocess.Popen = lambda cmd, **kw: (
            _write_empty_chunk(Path(cmd[10])) or _FakeProc(1)  # writes output anyway; rc still 1
        )
        merge_called = []
        run_flight.imgproc.merge_chunks = lambda *a, **kw: merge_called.append(1)
        with self.assertRaises(RuntimeError):
            run_flight.stage3(self.image, self.out, chunks=2)
        self.assertFalse(merge_called)

    @needs_v314_engine
    def test_chunks_1_does_not_spawn_any_subprocess(self):
        spawned = []
        real_imgproc_sm = run_flight.imgproc.imgproc_sm
        run_flight.subprocess.Popen = lambda *a, **kw: spawned.append(1)
        run_flight.imgproc.imgproc_sm = lambda *a, **kw: Path(a[1]).touch()
        try:
            run_flight.stage3(self.image, self.out, chunks=1)
        finally:
            run_flight.imgproc.imgproc_sm = real_imgproc_sm
        self.assertEqual(spawned, [])


class RunChunkModeTests(unittest.TestCase):
    """The hidden ``--_run-chunk`` re-exec entry point ``stage3`` spawns.

    Its argv is ``image probe project profile profile_module tas_file
    worker_stall_min out n n_every``; each test passes ``"0"`` for the stall
    budget, so no in-process faulthandler timer is armed."""

    def setUp(self):
        # The worker writes <out>.done beside its output (P10), so each test
        # runs in a scratch directory and that record never lands in the tree.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tmp.name)

    def test_dispatches_to_imgproc_sm_chunk_with_parsed_args(self):
        seen = {}
        real = run_flight._imgproc_sm_chunk
        real_probe, real_project, real_profile = (
            run_flight.PROBE, run_flight.PROJECT, run_flight.PROFILE)
        run_flight._imgproc_sm_chunk = (
            lambda image, out, n, n_every, progress=None, prime=None: seen.update(
                image=image, out=out, n=n, n_every=n_every, progress=progress,
                prime=prime)
        )
        try:
            rc = run_flight.main(
                ["--_run-chunk", "img.cdf", "2DS", "ORACLES",
                 "oracles-production", "", "", "0", "out.chunk1", "1", "500"]
            )
        finally:
            run_flight._imgproc_sm_chunk = real
            run_flight.PROBE, run_flight.PROJECT, run_flight.PROFILE = (
                real_probe, real_project, real_profile)
        self.assertEqual(rc, 0)
        self.assertEqual(seen["image"], Path("img.cdf"))
        self.assertEqual(seen["out"], Path("out.chunk1"))
        self.assertEqual((seen["n"], seen["n_every"]), (1, 500))
        # No prime= token in this argv, so the worker must pass None rather than
        # invent a pair. A chunk primed with a value no serial run held
        # writes a file that looks like a serial run and is not.
        self.assertIsNone(seen["prime"])

    def test_a_prime_token_reaches_the_chunk_call_as_two_exact_floats(self):
        """The prime pair travels as ``float.hex()`` and must arrive unrounded.

        This is the half an in-process test CAN see: that ``main()`` parses the
        token into the exact float64 values the parent computed. The other half
        -- that a real subprocess then reproduces the serial run -- is
        ``test_run_flight_chunk_priming.py``, which spawns actual workers.
        """
        seen = {}
        real = run_flight._imgproc_sm_chunk
        real_probe, real_project, real_profile = (
            run_flight.PROBE, run_flight.PROJECT, run_flight.PROFILE)
        # ENGINE too, and this is not belt-and-braces: --_run-chunk sets the
        # module global from its `engine=` token, and this is the first test in
        # the module to pass one. Leaving it at "3.5" put ten later tests in
        # this file on the v3.5 branch and broke them -- a fresh subprocess is
        # exactly what makes that safe in production and exactly what a
        # same-process test does not get.
        real_engine = run_flight.ENGINE
        run_flight._imgproc_sm_chunk = (
            lambda *a, prime=None, **kw: seen.update(prime=prime))
        # Deliberately values whose decimal repr would lose bits if the token
        # were written with str(): the hex form is what makes this exact.
        pair = (1234567.890123456, 0.1 + 0.2)
        try:
            rc = run_flight.main(
                ["--_run-chunk", "img.cdf", "2DS", "ORACLES",
                 "oracles-production", "", "", "0", "out.chunk2", "2", "500",
                 "engine=3.5", f"prime={pair[0].hex()},{pair[1].hex()}"]
            )
        finally:
            run_flight._imgproc_sm_chunk = real
            run_flight.PROBE, run_flight.PROJECT, run_flight.PROFILE = (
                real_probe, real_project, real_profile)
            run_flight.ENGINE = real_engine
        self.assertEqual(rc, 0)
        self.assertIsNotNone(seen["prime"])
        import struct
        for got, want in zip(seen["prime"], pair, strict=True):
            self.assertEqual(struct.pack("<d", got), struct.pack("<d", want),
                             "the prime pair must survive argv as BYTES")

    def test_sets_probe_project_and_profile_from_argv(self):
        """A chunk worker is a fresh subprocess that starts at this module's
        import-time defaults -- found while generalising PROFILE to any
        registered profile (2026-09-10). PROBE/PROJECT had
        the identical gap already; all three are threaded through argv now."""
        real_probe, real_project, real_profile = (
            run_flight.PROBE, run_flight.PROJECT, run_flight.PROFILE)
        real_chunk = run_flight._imgproc_sm_chunk
        run_flight._imgproc_sm_chunk = lambda *a, **kw: None
        try:
            run_flight.main(
                ["--_run-chunk", "img.cdf", "HVPS", "PECAN",
                 "stock-v3.1.4", "", "", "0", "out.chunk1", "1", "500"]
            )
            self.assertEqual(run_flight.PROBE, "HVPS")
            self.assertEqual(run_flight.PROJECT, "PECAN")
            from arrayprobe.profiles import STOCK_V314
            self.assertIs(run_flight.PROFILE, STOCK_V314)
        finally:
            run_flight._imgproc_sm_chunk = real_chunk
            run_flight.PROBE, run_flight.PROJECT, run_flight.PROFILE = (
                real_probe, real_project, real_profile)

    @needs_v314_engine
    def test_a_registered_profiles_module_is_imported_before_the_lookup(self):
        """The actual incident (2026-09-10): a profile added with
        register_profile() is invisible to PROFILES in a fresh --_run-chunk
        subprocess unless the module that registered it is imported first --
        which is exactly what a fresh process never does on its own."""
        import dataclasses
        import sys
        import tempfile

        from arrayprobe.profiles import STOCK_V314

        d = tempfile.mkdtemp()
        self.addCleanup(lambda: sys.path.remove(d) if d in sys.path else None)
        sys.path.insert(0, d)
        mod_name = "_test_chunk_profile_module"
        fields = dataclasses.asdict(STOCK_V314)
        fields["reject_thresholds"] = STOCK_V314.reject_thresholds
        fields["name"] = "test-chunk-fork"
        fields["description"] = "registered by test_run_flight.py"
        args = ", ".join(f"{k}={v!r}" for k, v in fields.items())
        Path(d, f"{mod_name}.py").write_text(
            "from arrayprobe.profiles import FidelityProfile, register_profile\n"
            "from arrayprobe.reject import RejectConfig\n"
            f"register_profile(FidelityProfile({args}))\n",
            encoding="utf-8")
        self.addCleanup(sys.modules.pop, mod_name, None)

        real_probe, real_project, real_profile = (
            run_flight.PROBE, run_flight.PROJECT, run_flight.PROFILE)
        real_chunk = run_flight._imgproc_sm_chunk
        run_flight._imgproc_sm_chunk = lambda *a, **kw: None
        try:
            rc = run_flight.main(
                ["--_run-chunk", "img.cdf", "2DS", "ORACLES",
                 "test-chunk-fork", mod_name, "", "0", "out.chunk1", "1", "500"]
            )
            self.assertEqual(rc, 0)
            self.assertEqual(run_flight.PROFILE.name, "test-chunk-fork")
        finally:
            run_flight._imgproc_sm_chunk = real_chunk
            run_flight.PROBE, run_flight.PROJECT, run_flight.PROFILE = (
                real_probe, real_project, real_profile)

    def test_a_chunk_reports_progress(self):
        """A chunk ran silently until 2026-08-30, so its own log file stayed
        empty for the whole pass: on a 222,693-record file, two hours in which
        the only sign of life was an output file growing. The callback is the
        same throttled one a single-chunk run uses."""
        lines = []
        real_log, real_chunk = run_flight.log, run_flight._imgproc_sm_chunk
        run_flight.log = lines.append
        # Call the callback the way imgproc_sm does: (records_done, last_record).
        run_flight._imgproc_sm_chunk = (
            lambda image, out, n, n_every, progress=None, prime=None: progress(5, 500)
        )
        try:
            run_flight.main(
                ["--_run-chunk", "img.cdf", "2DS", "ORACLES",
                 "oracles-production", "", "", "0", "out.chunk1", "1", "500"]
            )
        finally:
            run_flight.log, run_flight._imgproc_sm_chunk = real_log, real_chunk
        self.assertTrue(any("5/500" in ln for ln in lines), lines)


class PreflightTests(unittest.TestCase):
    """The preflight must not quote an eight-hour estimate for an S4-only redo."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "out"
        self.out.mkdir()
        self.raw = Path(self._tmp.name) / f"{STEM}.2DS"
        self.raw.write_bytes(b"\0" * 1024)
        self.addCleanup(self._tmp.cleanup)

    def _lines(self, iat_file=None):
        printed = []
        real = run_flight.log
        run_flight.log = printed.append
        try:
            run_flight.preflight([self.raw], self.out, iat_file)
        finally:
            run_flight.log = real
        return printed

    def test_a_stale_sd_with_a_proc_file_reports_S4_only(self):
        proc = self.out / f"proc.{STEM}.H.nc"
        proc.touch()
        # The proc file needs its own stamp now: an unstamped one is refused
        # rather than reported on, which is its own test below.
        run_flight.write_stamp(proc, run_flight.proc_call_label())
        (self.out / f"sd.{STEM}.H.nc").touch()
        (self.out / f"sd.{STEM}.H.nc.call").write_text(
            run_flight.sd_call_label(None))
        self.assertTrue(any(
            "S4 only" in line
            for line in self._lines(iat_file=run_flight.IAT_FILE)))

    def test_no_proc_file_reports_the_whole_chain(self):
        self.assertTrue(any("to do" in line for line in self._lines()))

    def test_a_current_sd_reports_done(self):
        (self.out / f"sd.{STEM}.H.nc").touch()
        (self.out / f"sd.{STEM}.H.nc.call").write_text(
            run_flight.sd_call_label(run_flight.IAT_FILE))
        lines = self._lines(iat_file=run_flight.IAT_FILE)
        self.assertTrue(any("done" in line for line in lines))
        self.assertFalse(any("S4 only" in line for line in lines))


class PartitionRoundRobinTests(unittest.TestCase):
    """S3p tier 1: files must split across workers without losing or duplicating any."""

    def test_even_split(self):
        files = [Path(f"f{i}.2DS") for i in range(6)]
        groups = run_flight.partition_round_robin(files, 3)
        self.assertEqual(len(groups), 3)
        self.assertEqual(sum(len(g) for g in groups), 6)
        self.assertEqual(sorted(str(f) for g in groups for f in g),
                         sorted(str(f) for f in files))

    def test_more_jobs_than_files_drops_empty_groups(self):
        files = [Path("a.2DS"), Path("b.2DS")]
        groups = run_flight.partition_round_robin(files, 5)
        self.assertEqual(len(groups), 2, "no empty worker groups")
        self.assertEqual(sum(len(g) for g in groups), 2)

    def test_uneven_split_round_robins_rather_than_clustering(self):
        # 7 files, 3 jobs: sizes 3/2/2, and worker 1 (index 0) must NOT get
        # files 0,1,2 contiguously -- it should get 0,3,6, spreading out any
        # size pattern in the input order (see partition_round_robin's own
        # docstring for why that matters).
        files = [Path(f"f{i}.2DS") for i in range(7)]
        groups = run_flight.partition_round_robin(files, 3)
        self.assertEqual([len(g) for g in groups], [3, 2, 2])
        self.assertEqual([f.name for f in groups[0]], ["f0.2DS", "f3.2DS", "f6.2DS"])

    def test_single_job_is_one_group_with_everything(self):
        files = [Path("a.2DS"), Path("b.2DS"), Path("c.2DS")]
        groups = run_flight.partition_round_robin(files, 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 3)


class RunParallelTests(unittest.TestCase):
    """The dispatch loop, with Popen faked so no real subprocess is spawned."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._real_popen = run_flight.subprocess.Popen
        self._real_log = run_flight.log
        self.logged = []
        run_flight.log = self.logged.append
        self.addCleanup(setattr, run_flight, "log", self._real_log)

    def _fake_args(self, jobs):
        class _Args:
            pass
        a = _Args()
        a.out = self.out
        a.stages = "234"
        a.iat_file = run_flight.IAT_FILE
        a.jobs = jobs
        a.chunks = 1
        a.diode_corrected = False
        a.accept_unstamped = False
        a.s2_jobs = 1
        a.preset = run_flight.ORACLES_2016_2DS_H.name
        a.presets = None
        a.config = None
        a.allow_mixed_config = False
        a.tas_file = None
        a.worker_stall_min = 30.0
        a.engine = "3.1.4"  # --engine is required; _spawn_worker reads it
        return a

    def test_all_workers_succeed(self):
        # Module-level _FakeProc (poll/wait/pid): pair G's run_parallel waits
        # through _await_workers, which polls rather than blocks.
        run_flight.subprocess.Popen = lambda *a, **kw: _FakeProc(0)
        try:
            files = [Path(f"f{i}.2DS") for i in range(4)]
            rc = run_flight.run_parallel(self._fake_args(2), files)
        finally:
            run_flight.subprocess.Popen = self._real_popen
        self.assertEqual(rc, 0)
        self.assertTrue(any("all workers done" in ln for ln in self.logged))

    def test_a_failed_worker_is_reported_and_nonzero_exit(self):
        calls = {"n": 0}

        def fake_popen(cmd, **kw):
            calls["n"] += 1
            return _FakeProc(1 if calls["n"] == 1 else 0)
        run_flight.subprocess.Popen = fake_popen
        try:
            files = [Path(f"f{i}.2DS") for i in range(3)]
            rc = run_flight.run_parallel(self._fake_args(2), files)
        finally:
            run_flight.subprocess.Popen = self._real_popen
        self.assertEqual(rc, 1)
        self.assertTrue(any("FAILED" in ln for ln in self.logged))

    def test_worker_command_includes_the_assigned_files_and_shared_options(self):
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            return _FakeProc(0)
        run_flight.subprocess.Popen = fake_popen
        try:
            files = [Path("a.2DS"), Path("b.2DS")]
            run_flight.run_parallel(self._fake_args(2), files)
        finally:
            run_flight.subprocess.Popen = self._real_popen
        self.assertEqual(len(seen_cmds), 2)
        flat = " ".join(seen_cmds[0])
        self.assertIn("--stages", flat)
        self.assertIn("234", flat)
        self.assertIn("--iat-file", flat)
        self.assertIn("a.2DS", flat)

    def test_more_jobs_than_files_spawns_one_worker_per_file(self):
        spawned = []

        def fake_popen(cmd, **kw):
            spawned.append(cmd)
            return _FakeProc(0)
        run_flight.subprocess.Popen = fake_popen
        try:
            files = [Path("a.2DS"), Path("b.2DS")]
            run_flight.run_parallel(self._fake_args(10), files)
        finally:
            run_flight.subprocess.Popen = self._real_popen
        self.assertEqual(len(spawned), 2, "never more workers than files")


class FlightGroupingTests(unittest.TestCase):
    def test_flight_group_is_the_yymmdd_slice(self):
        self.assertEqual(run_flight.flight_group("base160906104932"), "160906")

    def test_combine_out_path_uses_the_earliest_stem_in_filename_order(self):
        out = run_flight.combine_out_path(
            ["base160906104932", "base160906064017", "base160906125407"], Path("/x")
        )
        self.assertEqual(out, Path("/x/base160906064017.combined.H.2DS_2.cdf"))

    def test_only_engine_3_1_4_appends_the_underscore_2(self):
        # Author decision 2026-10-15: v3.5 and SODA-2 write no `_2`; v3.1.4 keeps
        # combine_sizedist.m:199's name so it matches the archived products.
        from unittest import mock
        stems = ["base160906064017"]
        for engine, name in (("3.1.4", "base160906064017.combined.H.2DS_2.cdf"),
                             ("3.5", "base160906064017.combined.H.2DS.cdf"),
                             ("soda2", "base160906064017.combined.H.2DS.cdf")):
            with self.subTest(engine=engine), mock.patch.object(run_flight, "ENGINE", engine):
                self.assertEqual(run_flight.combine_out_path(stems, Path("/x")).name, name)


class StageCombineTests(unittest.TestCase):
    """S4c wired into the runner: every sd.* file for a flight -> one product."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._real_log = run_flight.log
        self.logged = []
        run_flight.log = self.logged.append
        self.addCleanup(setattr, run_flight, "log", self._real_log)

    def _write_sd(self, stem, time):
        import numpy as np
        from tests.test_combine import _write_sd_fixture
        bin_mid = np.array([0.01, 0.02])
        n = len(time)
        target = self.out / f"sd.{stem}.H.nc"
        _write_sd_fixture(
            target, time, bin_mid,
            conc_minR=np.zeros((2, n)), conc_AreaR=np.zeros((2, n)),
            n=np.zeros(n), reject_ratio=np.zeros(n),
            count=np.zeros((2, n)), mean_area_ratio=np.zeros((2, n)),
        )
        # Stamped as S4 would stamp it: the combine refuses files whose
        # configuration is unknown (test_run_flight_provenance.py).
        run_flight.write_stamp(target, run_flight.sd_call_label(run_flight.IAT_FILE))

    def test_no_sd_files_present_returns_none(self):
        result = run_flight.stage_combine(["base160906064017"], self.out)
        self.assertIsNone(result)

    def test_one_flight_file_combines_and_writes_the_named_output(self):
        import numpy as np

        from arrayprobe.matlab_compat import datenum
        t0 = datenum(2016, 9, 6, 6, 40, 17)
        self._write_sd("base160906064017", np.array([t0, t0 + 1 / 86400]))
        target = run_flight.stage_combine(["base160906064017"], self.out)
        self.assertEqual(target, self.out / "base160906064017.combined.H.2DS_2.cdf")
        self.assertTrue(target.exists())

    def test_a_finished_target_is_skipped_not_rebuilt(self):
        import numpy as np

        from arrayprobe.matlab_compat import datenum
        t0 = datenum(2016, 9, 6, 6, 40, 17)
        self._write_sd("base160906064017", np.array([t0, t0 + 1 / 86400]))
        first = run_flight.stage_combine(["base160906064017"], self.out)
        mtime = first.stat().st_mtime
        second = run_flight.stage_combine(["base160906064017"], self.out)
        self.assertEqual(second.stat().st_mtime, mtime)
        self.assertTrue(any("skip" in ln for ln in self.logged))

    def test_a_partial_flight_still_combines_what_is_ready(self):
        import numpy as np

        from arrayprobe.matlab_compat import datenum
        t0 = datenum(2016, 9, 6, 6, 40, 17)
        self._write_sd("base160906064017", np.array([t0, t0 + 1 / 86400]))
        # base160906104932's sd file is deliberately absent -- S4 hasn't run yet.
        target = run_flight.stage_combine(
            ["base160906064017", "base160906104932"], self.out
        )
        self.assertIsNotNone(target)
        self.assertTrue(target.exists())
        self.assertTrue(any("PARTIAL" in ln for ln in self.logged))

    def _write_corrected_sd(self, stem, time, diodes):
        """An sd file as S4 writes it after a diode-corrected S3: the
        `.diodecorrected` name, stamped with the diode list."""
        import numpy as np
        from tests.test_combine import _write_sd_fixture
        n = len(time)
        target = run_flight.sd_path(stem, self.out, diodes)
        _write_sd_fixture(
            target, time, np.array([0.01, 0.02]),
            conc_minR=np.zeros((2, n)), conc_AreaR=np.zeros((2, n)),
            n=np.zeros(n), reject_ratio=np.zeros(n),
            count=np.zeros((2, n)), mean_area_ratio=np.zeros((2, n)),
        )
        run_flight.write_stamp(
            target, run_flight.sd_call_label(run_flight.IAT_FILE, shadow_diode=diodes))

    def _stitched_by(self, stems, **kw):
        """Run stage_combine with the real combine replaced by a recorder, and
        return the sd paths it was handed."""
        seen = []

        def fake(sd_files, outfile, **_):
            seen.append([Path(p) for p in sd_files])
            Path(outfile).write_bytes(b"stub")
        real = run_flight.combine.combine_sizedist
        run_flight.combine.combine_sizedist = fake
        self.addCleanup(setattr, run_flight.combine, "combine_sizedist", real)
        run_flight.stage_combine(stems, self.out, **kw)
        self.assertEqual(len(seen), 1, "the combine was not called exactly once")
        return seen[0]

    def test_diode_corrected_combine_stitches_the_corrected_sd_of_an_override_stem(self):
        """Regression test, 2026-09-06. Under --diode-corrected the combine
        built the plain `sd.<stem>.H.nc` name for every stem, so it stitched
        the UNCORRECTED sd of a stem whose corrected one had just been
        produced -- its own provenance line said shadow_diode=none. The
        2016-09-10 review run re-framed both masked files correctly and then
        reproduced the uncorrected product's 12 differing cells exactly.
        Combining the corrected files by hand gave 5,064 / 5,064."""
        import numpy as np

        from arrayprobe.matlab_compat import datenum
        masked = "base160910071623"            # in SHADOW_DIODE_OVERRIDES, diode 77
        plain = "base160910102201"             # not in the table
        self.assertIn(masked, run_flight.SHADOW_DIODE_OVERRIDES)
        self.assertNotIn(plain, run_flight.SHADOW_DIODE_OVERRIDES)
        t0 = datenum(2016, 9, 10, 7, 16, 23)
        t = np.array([t0, t0 + 1 / 86400])
        self._write_sd(masked, t)                      # the uncorrected one, also present
        self._write_corrected_sd(masked, t, run_flight.SHADOW_DIODE_OVERRIDES[masked])
        self._write_sd(plain, t)

        stitched = self._stitched_by([masked, plain], allow_mixed=True, diode_corrected=True)
        self.assertEqual([p.name for p in stitched],
                         [f"sd.{masked}.H.diodecorrected.nc", f"sd.{plain}.H.nc"])

    def test_without_the_flag_the_combine_stitches_the_plain_sd_files(self):
        import numpy as np

        from arrayprobe.matlab_compat import datenum
        masked = "base160910071623"
        t0 = datenum(2016, 9, 10, 7, 16, 23)
        t = np.array([t0, t0 + 1 / 86400])
        self._write_sd(masked, t)
        self._write_corrected_sd(masked, t, run_flight.SHADOW_DIODE_OVERRIDES[masked])
        stitched = self._stitched_by([masked])
        self.assertEqual([p.name for p in stitched], [f"sd.{masked}.H.nc"])


class WorkerStagesTests(unittest.TestCase):
    """'c' never reaches a worker: combine needs the whole flight's file list,
    which round-robin can split across workers -- see run_flight.main()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._real_popen = run_flight.subprocess.Popen
        self._real_log = run_flight.log
        run_flight.log = lambda *a, **kw: None
        self.addCleanup(setattr, run_flight, "log", self._real_log)
        self.addCleanup(setattr, run_flight.subprocess, "Popen", self._real_popen)

    def test_c_is_stripped_from_the_worker_command(self):
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            return _FakeProc(0)
        run_flight.subprocess.Popen = fake_popen

        class _Args:
            pass
        args = _Args()
        args.out = self.out
        args.stages = "234c"
        args.iat_file = run_flight.IAT_FILE
        args.jobs = 2
        args.chunks = 3
        args.diode_corrected = False
        args.accept_unstamped = False
        args.s2_jobs = 1
        args.preset = run_flight.ORACLES_2016_2DS_H.name
        args.presets = None
        args.config = None
        args.allow_mixed_config = False
        args.tas_file = None
        args.worker_stall_min = 30.0
        args.engine = "3.1.4"  # --engine is required; _spawn_worker reads it
        run_flight.run_parallel(args, [Path("a.2DS"), Path("b.2DS")])
        for cmd in seen_cmds:
            i = cmd.index("--stages")
            self.assertEqual(cmd[i + 1], "234")

    def test_diode_corrected_is_forwarded_to_each_worker(self):
        """Regression test, 2026-08-27: --diode-corrected used to be silently
        dropped for every worker under --jobs > 1, since _spawn_worker only
        ever forwarded the flags it explicitly listed."""
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            return _FakeProc(0)
        run_flight.subprocess.Popen = fake_popen

        class _Args:
            pass
        args = _Args()
        args.out = self.out
        args.stages = "34"
        args.iat_file = run_flight.IAT_FILE
        args.jobs = 2
        args.chunks = 1
        args.diode_corrected = True
        args.accept_unstamped = False
        args.s2_jobs = 1
        args.preset = run_flight.ORACLES_2016_2DS_H.name
        args.presets = None
        args.config = None
        args.allow_mixed_config = False
        args.tas_file = None
        args.worker_stall_min = 30.0
        args.engine = "3.1.4"  # --engine is required; _spawn_worker reads it
        run_flight.run_parallel(args, [Path("a.2DS"), Path("b.2DS")])
        self.assertTrue(seen_cmds, "expected at least one worker to be spawned")
        for cmd in seen_cmds:
            self.assertIn("--diode-corrected", cmd)

    def test_diode_corrected_false_is_not_forwarded(self):
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            return _FakeProc(0)
        run_flight.subprocess.Popen = fake_popen

        class _Args:
            pass
        args = _Args()
        args.out = self.out
        args.stages = "34"
        args.iat_file = run_flight.IAT_FILE
        args.jobs = 2
        args.chunks = 1
        args.diode_corrected = False
        args.accept_unstamped = False
        args.s2_jobs = 1
        args.preset = run_flight.ORACLES_2016_2DS_H.name
        args.presets = None
        args.config = None
        args.allow_mixed_config = False
        args.tas_file = None
        args.worker_stall_min = 30.0
        args.engine = "3.1.4"  # --engine is required; _spawn_worker reads it
        run_flight.run_parallel(args, [Path("a.2DS"), Path("b.2DS")])
        self.assertTrue(seen_cmds, "expected at least one worker to be spawned")
        for cmd in seen_cmds:
            self.assertNotIn("--diode-corrected", cmd)

    def test_s2_jobs_is_forwarded_to_each_worker(self):
        """Regression test, 2026-09-06: --s2-jobs was silently dropped for
        every worker under --jobs > 1 -- the third flag to go missing from
        _spawn_worker's explicit list (after --diode-corrected and
        --accept-unstamped). A flight launched as `--jobs 2 --s2-jobs 6`
        decoded serially in both workers with nothing in any log to say so.
        Found by reading the list before the 2026-09-06 review run."""
        seen_cmds = []

        def fake_popen(cmd, **kw):
            seen_cmds.append(cmd)
            return _FakeProc(0)
        run_flight.subprocess.Popen = fake_popen

        class _Args:
            pass
        args = _Args()
        args.out = self.out
        args.stages = "234"
        args.iat_file = run_flight.IAT_FILE
        args.jobs = 2
        args.chunks = 1
        args.diode_corrected = False
        args.accept_unstamped = False
        args.s2_jobs = 6
        args.preset = run_flight.ORACLES_2016_2DS_H.name
        args.presets = None
        args.config = None
        args.allow_mixed_config = False
        args.tas_file = None
        args.worker_stall_min = 30.0
        args.engine = "3.1.4"  # --engine is required; _spawn_worker reads it
        run_flight.run_parallel(args, [Path("a.2DS"), Path("b.2DS")])
        self.assertTrue(seen_cmds, "expected at least one worker to be spawned")
        for cmd in seen_cmds:
            i = cmd.index("--s2-jobs")
            self.assertEqual(cmd[i + 1], "6")

    def test_jit_is_forwarded_to_each_worker_and_absent_by_default(self):
        """--jit must reach every --jobs worker, the lesson of the four
        flags that went missing from this list before it."""
        for flag_on in (True, False):
            seen_cmds = []

            def fake_popen(cmd, _seen=seen_cmds, **kw):
                _seen.append(cmd)
                return _FakeProc(0)
            run_flight.subprocess.Popen = fake_popen

            class _Args:
                pass
            args = _Args()
            args.out = self.out
            args.stages = "234"
            args.iat_file = run_flight.IAT_FILE
            args.jobs = 2
            args.chunks = 1
            args.diode_corrected = False
            args.accept_unstamped = False
            args.s2_jobs = 1
            args.jit = flag_on
            args.preset = run_flight.ORACLES_2016_2DS_H.name
            args.presets = None
            args.config = None
            args.allow_mixed_config = False
            args.tas_file = None
            args.worker_stall_min = 30.0
            args.engine = "3.1.4"  # --engine is required; _spawn_worker reads it
            run_flight.run_parallel(args, [Path("a.2DS"), Path("b.2DS")])
            self.assertTrue(seen_cmds)
            for cmd in seen_cmds:
                self.assertEqual("--jit" in cmd, flag_on)


class DiodeCorrectedChunksRejectedTests(unittest.TestCase):
    """--diode-corrected + --chunks > 1 must fail loudly, not silently run
    stage3_corrected() serially while claiming chunked behavior (2026-08-27
    audit finding). The check runs before preflight, so a nonexistent raw
    file is fine here -- it must never be reached."""

    def setUp(self):
        self._real_log = run_flight.log
        self.logged = []
        run_flight.log = self.logged.append
        self.addCleanup(setattr, run_flight, "log", self._real_log)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "out"

    @needs_v314_engine
    def test_rejected_before_preflight(self):
        rc = run_flight.main(
            ["--diode-corrected", "--chunks", "2", "--engine", "3.1.4", "--port-validation",
             "--preset", "ORACLES_2016_2DS_H",
             "--out", str(self.out), "does_not_exist.2DS"]
        )
        # 2, not 1, since 2026-09-20: the guard fires before preflight, so nothing ran,
        # and a refused command line is 2 everywhere else in main(). It was one of the
        # two places that answered a refusal with the code a failed flight uses --
        # tests/test_run_flight_profile_flag.py states the convention and pins the other.
        self.assertEqual(rc, 2)
        self.assertTrue(any("does not support --chunks" in ln for ln in self.logged))
        self.assertFalse(
            any("PREFLIGHT" in ln for ln in self.logged), "guard must fire before preflight"
        )

    @needs_v314_engine
    def test_chunks_1_does_not_trip_the_guard(self):
        # Still fails (the file doesn't exist) but for a DIFFERENT reason --
        # confirms chunks=1 reaches preflight instead of the new guard.
        rc = run_flight.main(
            ["--diode-corrected", "--chunks", "1", "--engine", "3.1.4", "--port-validation",
             "--preset", "ORACLES_2016_2DS_H",
             "--out", str(self.out), "does_not_exist.2DS", "--dry-run"]
        )
        self.assertEqual(rc, 1)
        self.assertFalse(any("does not support --chunks" in ln for ln in self.logged))
        self.assertTrue(any("PREFLIGHT" in ln for ln in self.logged))


class AStaleCombinedProductDoesNotBlockItsReplacement(unittest.TestCase):
    """The combine step used to skip on *existence* alone.

    20170824 is why this test exists. Its first run lost one of the flight's
    two raw files to a page-in fault, so the combine stitched one file and
    wrote a product that validated at 100.0000 % against the reference -- a
    real figure covering only what that one file spanned. The relaunch
    reprocessed the missing file correctly and then **skipped the combine**,
    because a product with the right name was already on disk. The flight read
    as finished for eight hours and was not.

    ``files_stitched`` is the dimension that settles it, and it is written by
    the original for exactly this purpose.
    """

    def _product(self, path: Path, n_files: int) -> None:
        """A minimal stand-in carrying only the dimension under test."""
        with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
            ds.createDimension("files_stitched", n_files)
            ds.createDimension("time", 3)

    def test_reads_the_file_count_back(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "p.cdf"
            self._product(p, 2)
            self.assertEqual(run_flight._files_stitched(p), 2)

    def test_a_partial_product_is_reported_as_stale(self):
        """One file stitched where two are ready must NOT count as current."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "p.cdf"
            self._product(p, 1)
            self.assertNotEqual(
                run_flight._files_stitched(p), 2,
                "a one-file product must not be mistaken for a two-file one")

    def test_an_unreadable_product_is_stale_not_trusted(self):
        """Fail toward rebuilding. Trusting a file we cannot read is how the
        original bug behaved, and it is the expensive direction to be wrong in."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "truncated.cdf"
            p.write_bytes(b"not a netCDF file at all")
            self.assertEqual(run_flight._files_stitched(p), 0)

    def test_a_missing_product_is_stale(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run_flight._files_stitched(Path(d) / "absent.cdf"), 0)

    def test_an_unreadable_product_says_why_before_rebuilding(self):
        """The rebuild is right; being silent about it was not (2026-09-06).

        This machine reads the archive over a Box mount, and 20170824's first
        run died with a Windows page-in fault on a file that then re-read fine
        in 24 s. A transient mount fault and a truncated product produced
        *identical* behaviour: a silent decision to reprocess a flight for
        about three hours. The log line is what makes them distinguishable
        afterwards, so it is the thing worth pinning.
        """
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "truncated.cdf"
            p.write_bytes(b"not a netCDF file at all")
            written = []
            original = run_flight.log
            run_flight.log = written.append
            try:
                self.assertEqual(run_flight._files_stitched(p), 0)
            finally:
                run_flight.log = original
            self.assertTrue(written, "the failure was not logged at all")
            joined = "\n".join(written)
            self.assertIn("truncated.cdf", joined)
            self.assertIn("files_stitched", joined)
            self.assertIn("stale", joined)
            # The exception type, so a mount fault is not mistaken for a
            # corrupt product by the next person reading the log.
            self.assertRegex(joined, r"\((OSError|FileNotFoundError|"
                                     r"RuntimeError|[A-Za-z]*Error):")

    def test_a_product_without_the_dimension_also_says_why(self):
        """A netCDF file that opens but carries no ``files_stitched`` is a
        different failure from one that will not open, and reads as the same
        ``0``. Both now name themselves."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nodim.cdf"
            with netCDF4.Dataset(str(p), "w", format="NETCDF3_CLASSIC") as ds:
                ds.createDimension("time", 3)
            written = []
            original = run_flight.log
            run_flight.log = written.append
            try:
                self.assertEqual(run_flight._files_stitched(p), 0)
            finally:
                run_flight.log = original
            joined = "\n".join(written)
            self.assertIn("no files_stitched dimension", joined)

    def test_a_good_product_logs_nothing(self):
        """A check that fires on the happy path is noise, and noise gets
        ignored -- the property the sync-state mechanism depends on too."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "p.cdf"
            self._product(p, 2)
            written = []
            original = run_flight.log
            run_flight.log = written.append
            try:
                self.assertEqual(run_flight._files_stitched(p), 2)
            finally:
                run_flight.log = original
            self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
