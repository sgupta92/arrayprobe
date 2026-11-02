# SPDX-License-Identifier: BSD-3-Clause
"""``[run].engine = "3.5"`` -- the last gap: ``arrayprobe run`` reaches the v3.5 engine
through the same one line ``scripts/run_flight.py`` already runs v3.1.4 through.

Companion to ``tests/test_run_from_config.py`` (Phase 1, v3.1.4) and
``tests/test_run_from_config_tas.py`` (Phase 2b, ``[run].tas_file``). This file is the
v3.5 half: engine 3.5 dispatches S2/S3/S4 to ``arrayprobe_uiops`` through ``uiops.engine("3.5")``,
S4c to the borrowed ORACLES-fork combine only with ``[combine].borrowed = true``, and every stamp
carries ``engine=3.5`` so the two engines' products cannot be mixed by the resume logic (since
2026-09-15, a v3.1.4 stamp names ``engine=3.1.4`` the same way -- see
``TheV314StampsCarryAnEnginePrefix`` below).

No flight runs, no raw decodes beyond the ~7 s synthetic demo flight
(``make_demo_flight.build_demo_flight``): every test's ``[run].out`` is
``"_decoded"`` relative to the TOML in its own tempdir, never the shared ``../_decoded``.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np
from tests import (
    _run_flight_state,
    _upstream,  # noqa: E402
)
from tests._driver import driver_source
from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
#: The repository root (the package root) -- where UIOPS-v3.5/ is vendored.
REPO_ROOT = ROOT
V35_TREE = _upstream.source("uiops35")

# Loaded exactly the way test_run_from_config_tas.py does: by file path, under
# sys.modules["make_demo_flight"]/["run_flight"], so this file, arrayprobe.cli's
# _load_run_flight() and run_flight's own module globals are all the SAME object.
_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules["make_demo_flight"] = make_demo_flight
_DEMO_SPEC.loader.exec_module(make_demo_flight)

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
run_flight = None  # bound in setUpModule, see below


def setUpModule():
    """Bind ``run_flight`` at RUN time, to whichever module object is registered then -- the same
    reason test_run_from_config.py/test_run_from_config_tas.py do this (2026-09-13 merge)."""
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)


from arrayprobe import cli  # noqa: E402 (after the run_flight/sys.modules setup above)


class _RunFlightStateIsolated(unittest.TestCase):
    """Snapshot/restore run_flight's module globals so one test's --preset/--config/--engine
    cannot leak into the next (test_run_from_config_tas.py's own pattern, plus ``ENGINE``)."""

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)


def _aircraft(path: Path, tas: float = 85.0) -> Path:
    """A synthetic aircraft TAS file matching the demo flight's three HHMMSS records
    (test_run_from_config_tas.py's own helper, copied)."""
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", 3)
        time_var = ds.createVariable("Time", "f8", ("time",))
        tas_var = ds.createVariable("TAS", "f8", ("time",))
        time_var[:] = [60640, 60641, 60642]
        tas_var[:] = [tas, tas, tas]
    return path


def _toml(root: Path, stages: str, *, engine: str, profile: str,
          tas_file: str | None, shattering: str | None, borrowed: bool) -> Path:
    """A run configuration naming ``engine``/``profile``/``stages``, always the ``DEMO_2DS_H``
    preset (the synthetic-flight preset -- no campaign data required). ``shattering`` is the
    ``[shattering].threshold_file`` value, or ``None`` to omit the section entirely (v3.5's plain
    call -> iaThreshType 0); ``borrowed`` is ``[combine].borrowed``."""
    lines = [
        "[fidelity]",
        f'profile = "{profile}"',
        "[run]",
        f'engine = "{engine}"',
        'preset = "DEMO_2DS_H"',
        'out = "_decoded"',
        f'stages = "{stages}"',
    ]
    if tas_file is not None:
        lines.append(f'tas_file = "{tas_file}"')
    if shattering is not None:
        lines.insert(2, "[shattering]")
        lines.insert(3, f'threshold_file = "{shattering}"')
    if borrowed:
        lines += ["[combine]", "borrowed = true"]
    p = root / "run.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _run_cli(toml: Path, *raws, port_validation: bool = False) -> tuple[int, str]:
    """Run ``arrayprobe run`` and return ``(rc, combined stdout+stderr)`` -- run_flight's own
    log() writes to stdout, but cli._run's own error prints (e.g. a bad [run] section) go to
    stderr, so both are captured and concatenated for the assertions here.

    ``port_validation`` is passed only for a config that names engine 3.1.4 (R4):
    that engine is refused without the flag and every other engine is refused with it."""
    out, err = io.StringIO(), io.StringIO()
    extra = ["--port-validation"] if port_validation else []
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(["run", str(toml), *(str(r) for r in raws), "--yes", *extra])
    return rc, out.getvalue() + err.getvalue()


class StockV35ReachesS4c(_RunFlightStateIsolated):
    """T1 -- the done-criterion: engine 3.5 reaches S4c from one file, one line."""

    def test_stock_v35_reaches_s4c_from_one_file_and_one_line(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")
        toml = _toml(root, "234c", engine="3.5", profile="stock-v3.5",
                     tas_file="aircraft.cdf", shattering=None, borrowed=True)

        rc, out = _run_cli(toml, raw)
        self.assertEqual(rc, 0, out)

        decoded = root / "_decoded"
        image = decoded / "base160101000000.H.nc"
        proc = decoded / "proc.base160101000000.H.nc"
        sd = decoded / "sd.base160101000000.H.nc"
        combined = decoded / "base160101000000.combined.H.2DS.cdf"
        self.assertTrue(image.is_file(), out)
        self.assertTrue(proc.is_file(), out)
        self.assertTrue(sd.is_file(), out)
        self.assertTrue(combined.is_file(), out)

        image_stamp = run_flight.read_stamp(image)
        # The raw-input inventory keys S2 appends describe the input, not the configuration.
        self.assertEqual(run_flight._strip_inventory(image_stamp or ""),
                         run_flight.image_call_label())
        self.assertTrue(
            (image_stamp or "").startswith("engine=3.5 profile=stock-v3.5 software=UIOOPS_v3.5"),
            image_stamp)

        proc_stamp = run_flight.read_stamp(proc)
        self.assertEqual(proc_stamp, run_flight.proc_call_label())
        self.assertIn("iNewHabit=0", proc_stamp)
        self.assertIn(" tas_file=aircraft.cdf", proc_stamp)

        sd_stamp = run_flight.read_stamp(sd)
        # The written stamp adds what the run measured (time/sample-volume counts, the
        # plausibility verdict), which the configured label never carries.
        self.assertEqual(run_flight._strip_plausibility(run_flight._strip_time_sv_counts(sd_stamp)),
                         run_flight.sd_call_label(""))
        self.assertIn("iaThreshType=0", sd_stamp)
        self.assertEqual(sd_stamp.count("engine=3.5"), 1, sd_stamp)

        with netCDF4.Dataset(proc) as ds:
            self.assertEqual(ds.data_model, "NETCDF4")
            got = np.asarray(ds.variables["Time_in_seconds"][:], dtype=float).ravel()
        self.assertAlmostEqual(float(got[0]), 35.934322, places=3)

        import arrayprobe_uiops.combine as v35_combine
        call_text = (combined.with_name(combined.name + ".call")).read_text(encoding="utf-8")
        self.assertEqual(call_text.splitlines()[0], v35_combine.CALL_STAMP)


class TheV314StampsCarryAnEnginePrefix(_RunFlightStateIsolated):
    """T2 -- since 2026-09-15, ``_engine_prefix()``/``config_label`` name
    ``engine=3.1.4`` under the default engine too, matching v3.5's stamps -- so a product's own
    sidecar answers "which engine wrote this" under either engine, with no need to read source.
    Renamed from ``TheV314StampsCarryNoEnginePrefix``, which asserted the opposite of this."""

    def test_the_v314_stamps_carry_an_engine_prefix(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")
        toml = _toml(root, "234", engine="3.1.4", profile="STOCK_V314",
                     tas_file="aircraft.cdf", shattering=None, borrowed=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["run", str(toml), str(raw), "--dry-run",
                           "--port-validation"])
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertTrue(run_flight.image_call_label().startswith("engine=3.1.4 "))
        self.assertTrue(run_flight.proc_call_label().startswith("engine=3.1.4 "))
        sd_label = run_flight.sd_call_label(run_flight.IAT_FILE)
        self.assertTrue(sd_label.startswith("engine=3.1.4 "))
        # Exactly one occurrence: config_label's own engine=3.1.4 prefix must be stripped from
        # the `inner` half sd_call_label folds in, or the label doubles it.
        self.assertEqual(sd_label.count("engine=3.1.4"), 1, sd_label)


class CrossEngineProcIsRefused(_RunFlightStateIsolated):
    """T3 -- a v3.1.4 proc under a v3.5 run is stale, and vice versa: the stamp, not existence,
    decides."""

    def test_a_v314_proc_is_refused_by_a_v35_run_and_vice_versa(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")

        toml_314 = _toml(root, "23", engine="3.1.4", profile="STOCK_V314",
                         tas_file="aircraft.cdf", shattering=None, borrowed=False)
        rc, out = _run_cli(toml_314, raw, port_validation=True)
        self.assertEqual(rc, 0, out)

        toml_35 = _toml(root, "4", engine="3.5", profile="stock-v3.5",
                        tas_file="aircraft.cdf", shattering=None, borrowed=False)
        rc, out = _run_cli(toml_35, raw)
        self.assertEqual(rc, 1, out)
        self.assertIn("REFUSED", out)
        self.assertIn("was built with", out)
        self.assertEqual(list((root / "_decoded").glob("sd.*")), [])

    def test_a_v35_proc_is_refused_by_a_v314_run(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")

        toml_35 = _toml(root, "23", engine="3.5", profile="stock-v3.5",
                        tas_file="aircraft.cdf", shattering=None, borrowed=False)
        rc, out = _run_cli(toml_35, raw)
        self.assertEqual(rc, 0, out)

        toml_314 = _toml(root, "4", engine="3.1.4", profile="STOCK_V314",
                         tas_file="aircraft.cdf", shattering=None, borrowed=False)
        rc, out = _run_cli(toml_314, raw, port_validation=True)
        self.assertEqual(rc, 1, out)
        self.assertIn("REFUSED", out)
        self.assertIn("was built with", out)
        # The proc file really was built by the v3.5 run: the stamp the message quotes (read
        # from the .call sidecar the v3.5 run wrote) must name the engine, not merely differ
        # from the v3.1.4 run's wanted label for some other reason (e.g. a different profile
        # name) -- config_label's engine=3.5 prefix specifically.
        self.assertIn("engine=3.5", out)


class Engine35RefusesUnsupportedFlags(_RunFlightStateIsolated):
    """T4 -- --diode-corrected and a missing threshold file are refused before preflight,
    not silently downgraded.

    ``--chunks`` is in this list for a NARROWER reason since 2026-09-17: it is no
    longer refused under engine 3.5 as such -- CIP/PIP, 2DC/2DP and Fast2DC chunk
    bit-identically -- but this fixture's probe is a **2DS**, probetype 2, whose
    ``Time_in_seconds`` accumulates across the whole file (``imgProc_sm.m:1131-1180``), so a
    chunked run would be different output. The refusal asserted below is that probetype gate,
    not a blanket one; ``tests/test_v35_imgproc_merge_chunks.py`` covers the chunkable side.
    """

    def test_engine_35_accepts_diode_corrected_and_refuses_a_missing_threshold_file(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")
        toml = _toml(root, "234", engine="3.5", profile="stock-v3.5",
                     tas_file="aircraft.cdf", shattering=None, borrowed=False)
        out_dir = root / "_decoded"

        def _direct(*extra):
            buf = io.StringIO()
            with redirect_stdout(buf):
                # --preset is required since 2026-09-15; --config's own
                # [run].preset = "DEMO_2DS_H" (via _toml) is not read until AFTER argparse, so a
                # direct invocation still has to name it on the command line too.
                rc = run_flight.main([str(raw), "--config", str(toml), "--engine", "3.5",
                                      "--preset", "DEMO_2DS_H", "--out", str(out_dir), *extra])
            return rc, buf.getvalue()

        # ``--chunks`` is DELIBERATELY NOT TESTED HERE ANY MORE, and this is the second
        # time this block has had to narrow.  It first asserted a blanket "engine 3.5
        # cannot chunk"; that stopped being true on 2026-09-17, when probetypes 0, 1 and
        # 3 became chunkable, so it narrowed to the probetype-2 refusal naming
        # ``imgProc_sm.m:1131-1180``'s accumulation.  On 2026-09-18 that stopped being
        # true too: prefix-priming hands each chunk the two float64 scalars the
        # serial run held at its first record, and probetype 2 chunks bit-for-bit.
        #
        # What survives is far narrower than a flag refusal -- ``--chunks`` with
        # ``iQC=1``, because ``qc_image`` can change an image's width and so
        # ``:850-853``'s return can fire mid-file where a header-only prefix scan cannot
        # see it.  ``_toml`` above cannot set ``iQC``, so asserting it here would mean
        # widening the helper for one case; it is covered where the mechanism lives.
        #
        # The POSITIVE proof lives in two places rather than here, because this class is
        # about refusals: ``tests/test_v35_sizedist_chunk_priming.py`` (engine level, all
        # 40 variables byte-equal, a one-ULP mutation detected, and an unprimed control
        # that disagrees) and ``tests/test_run_flight_chunk_priming.py`` (the driver's
        # argv round-trip, three real subprocesses).

        # ``--s2-jobs`` is not refused either: the v3.5 decode has a byte-identical parallel
        # form (tests/test_v35_spec_parallel.py, and through this driver
        # tests/test_run_flight_v35_s2_jobs.py); test_engine_flag_parity.py asserts acceptance.

        # ``--diode-corrected`` is accepted since imgproc_sm_v35 took shadow_diode=
        # (tests/test_v35_shadow_diode.py, and test_engine_flag_parity.py asserts acceptance);
        # a dry run here, so the no-write assertion below still holds.
        rc, out = _direct("--diode-corrected", "--dry-run", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("--diode-corrected is not available", out)

        rc, out = _direct("--iat-file", str(root / "nope.cdf"))
        self.assertEqual(rc, 2, out)
        self.assertIn("does not exist", out)

        self.assertFalse(out_dir.exists() and list(out_dir.glob("*.H.nc")))


class StageCUnderThirtyFiveNeedsTheBorrowedKey(_RunFlightStateIsolated):
    """T5 -- opt-in both ways: engine 3.5 refuses 'c' without the key, engine 3.1.4 refuses
    the key."""

    def test_stage_c_under_35_needs_the_borrowed_key_and_314_refuses_it(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")

        toml_35 = _toml(root, "234c", engine="3.5", profile="stock-v3.5",
                        tas_file="aircraft.cdf", shattering=None, borrowed=False)
        rc, out = _run_cli(toml_35, raw)
        self.assertEqual(rc, 2, out)
        self.assertIn("[combine].borrowed", out)

        toml_314 = _toml(root, "234", engine="3.1.4", profile="STOCK_V314",
                         tas_file="aircraft.cdf", shattering=None, borrowed=True)
        rc, out = _run_cli(toml_314, raw, port_validation=True)
        self.assertEqual(rc, 2, out)
        self.assertIn("--engine 3.5 only", out)


class ProfileAndEngineMustAgree(_RunFlightStateIsolated):
    """T6 -- each engine refuses the other's profile before preflight."""

    def test_profile_and_engine_must_agree(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)

        toml_a = _toml(root, "2", engine="3.5", profile="STOCK_V314",
                       tas_file=None, shattering=None, borrowed=False)
        rc, out = _run_cli(toml_a, raw)
        self.assertEqual(rc, 2, out)
        # The message stopped saying "stock-v3.5 only" on 2026-09-17, when the
        # gate widened from `PROFILE is not STOCK_V35` to `is_v35_flavoured` so that
        # oracles-production-v3.5 could run: the engine reads only reject_thresholds, so
        # pinning the profile's identity pinned its thresholds too. What must still hold
        # is that a profile citing the v3.1.4 tree is refused, and the refusal says why.
        self.assertIn("--engine 3.5 needs a v3.5 profile", out)
        self.assertIn("stock-v3.1.4", out)

        toml_b = _toml(root, "2", engine="3.1.4", profile="stock-v3.5",
                       tas_file=None, shattering=None, borrowed=False)
        rc, out = _run_cli(toml_b, raw, port_validation=True)
        self.assertEqual(rc, 2, out)
        self.assertIn("--engine 3.5", out)


class TheOneLinePassesEngineAndBorrowedCombine(unittest.TestCase):
    """T7 -- ``cli._run`` forwards both, and only forwards --borrowed-combine when the key is
    set (test_run_from_config.py::Engine35ReachesTheDriver covers --engine alone)."""

    def test_forwards_engine_and_borrowed_combine_when_set(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _toml(root, "234c", engine="3.5", profile="stock-v3.5",
                     tas_file="aircraft.cdf", shattering=None, borrowed=True)
        raw = root / "base160101000000.2DS"
        raw.write_bytes(b"")
        with mock.patch.object(run_flight, "main", return_value=0) as spy:
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["run", str(toml), str(raw), "--yes"])
        self.assertEqual(rc, 0)
        spy.assert_called_once()
        (argv,), _ = spy.call_args
        self.assertEqual(argv[argv.index("--engine") + 1], "3.5")
        self.assertIn("--borrowed-combine", argv)

    def test_does_not_forward_borrowed_combine_when_absent(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _toml(root, "234", engine="3.5", profile="stock-v3.5",
                     tas_file="aircraft.cdf", shattering=None, borrowed=False)
        raw = root / "base160101000000.2DS"
        raw.write_bytes(b"")
        with mock.patch.object(run_flight, "main", return_value=0) as spy:
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["run", str(toml), str(raw), "--yes"])
        self.assertEqual(rc, 0)
        (argv,), _ = spy.call_args
        self.assertNotIn("--borrowed-combine", argv)


class ADirectConfigRunMustNameTheFilesEngine(_RunFlightStateIsolated):
    """T8 -- a direct ``run_flight.py --config`` invocation must say ``--engine`` too; only
    ``arrayprobe run`` is allowed to pass it implicitly on the file's behalf."""

    def test_a_direct_config_run_must_name_the_files_engine(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")
        # stages="2" deliberately: this test is about the engine-naming requirement, not
        # --tas-file threading (which a direct --config invocation does not pick up from
        # [run].tas_file at all -- only cli._run's argv-building does that).
        toml = _toml(root, "2", engine="3.5", profile="stock-v3.5",
                     tas_file="aircraft.cdf", shattering=None, borrowed=False)
        out_dir = root / "_decoded"

        # --stages passed explicitly on BOTH calls: a direct --config invocation does not read
        # [run].stages either (only cli._run's argv-building does), so without this the argparse
        # default ("234") would ask for --tas-file, muddying what this test is actually about.
        buf = io.StringIO()
        with redirect_stdout(buf):
            # --preset required since 2026-09-15; not what this test is about, so
            # named just to get past argparse.
            rc = run_flight.main([str(raw), "--config", str(toml), "--stages", "2",
                                  "--preset", "DEMO_2DS_H", "--out", str(out_dir), "--dry-run"])
        self.assertEqual(rc, 2, buf.getvalue())
        # The exact phrase _apply_config's [run].engine-vs---engine disagreement check prints,
        # not merely "--engine 3.5" somewhere -- the PROFILE-is-STOCK_V35 gate in main() also
        # happens to mention "--engine 3.5" for this same config (both profile and engine name
        # v3.5), so a looser substring check would not fail if only this dedicated check were
        # deleted.
        self.assertIn("a direct run must say --engine 3.5", buf.getvalue())

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = run_flight.main([str(raw), "--config", str(toml), "--engine", "3.5",
                                   "--stages", "2", "--preset", "DEMO_2DS_H",
                                   "--out", str(out_dir), "--dry-run"])
        self.assertEqual(rc2, 0, buf2.getvalue())


class TheDriverReachesV35OnlyThroughTheSelector(unittest.TestCase):
    """T9 -- ``uiops.engine("3.5")`` is the only path from run_flight.py to arrayprobe_uiops's
    engine.

    One named exception, :data:`SHARED`: ``decode_naming``, the single source of every stage-2
    decode name. It is code both engines share (the engine is one of its arguments), not the v3.5
    engine, and ``uiops.CATALOGUE`` has no entry for it, so the driver imports it by name, as
    ``arrayprobe.cli`` and ``arrayprobe.triage_server`` do. Adding a module here is a decision.

    ``product_sanity`` joined it with the post-S4 plausibility gate (``_s4_plausibility_gate``):
    a read-only netCDF4/numpy checker that imports no engine and reads sd/proc files written by
    either engine, so it is shared tooling, not the v3.5 engine, and ``uiops.CATALOGUE`` (the
    v3.1.4 port's modules) has no entry through which the selector could reach it.
    """

    SHARED = frozenset({"decode_naming", "product_sanity"})

    def test_no_direct_import_of_arrayprobe_v35(self):
        source = driver_source("run_flight.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("arrayprobe_uiops", alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                # *_core modules are the shared leaves moved out of v3.1.4 in the split
                # (2026-10-09); the driver takes shared code from them, not the engine.
                if node.module.startswith("arrayprobe_uiops.") and node.module.endswith("_core"):
                    continue
                if (node.module == "arrayprobe_uiops"
                        and {a.name for a in node.names} <= self.SHARED):
                    continue
                self.assertNotIn("arrayprobe_uiops", node.module)
        self.assertIn('uiops.engine("3.5")', source)

    def test_the_shared_exception_does_not_admit_the_engine(self):
        """The exception fires on the engine: ``from arrayprobe_uiops import imgproc`` is
        refused."""
        node = ast.parse("from arrayprobe_uiops import imgproc").body[0]
        self.assertIsInstance(node, ast.ImportFrom)
        self.assertFalse({a.name for a in node.names} <= self.SHARED)

    def test_the_selector_resolves_to_the_real_v35_modules(self):
        import arrayprobe_uiops.imgproc
        self.assertIs(run_flight._v35().module("imgproc"), arrayprobe_uiops.imgproc)


class SpawnWorkerForwardsEngine(unittest.TestCase):
    """T10 -- a --jobs worker gets the parent's --engine, not the argparse default."""

    def test_spawn_worker_forwards_engine(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        ns = types.SimpleNamespace(
            stages="234", out=root, chunks=1, s2_jobs=1, iat_file="",
            preset="DEMO_2DS_H", tas_file=None, presets=None, config=None,
            allow_mixed_config=False, accept_unstamped=False, diode_corrected=False,
            engine="3.5", worker_stall_min=30.0,  # forwarded by _spawn_worker since pair G
        )
        with mock.patch.object(run_flight.subprocess, "Popen",
                               return_value=mock.Mock()) as popen:
            run_flight._spawn_worker([root / "a.2DS"], ns, root / "worker.log")
        cmd = popen.call_args.args[0]
        self.assertIn("--engine", cmd)
        self.assertEqual(cmd[cmd.index("--engine") + 1], "3.5")


@repo_only
class V35CallValuesAreTheCitedOnes(unittest.TestCase):
    """T11, adjusted by the coordinator's check (2026-09-13): every V35_CALL value is v3.5's OWN
    vendored default, not a v3.1.4/fork imitation -- two sides from two places, the constant and
    the vendored source it cites."""

    def test_v35_call_values_are_the_cited_ones(self):
        self.assertEqual(
            run_flight.V35_CALL,
            run_flight.V35Call(
                i_rect_ellipse=0, i_calc_all_diode_stats=0, i_qc=0, i_new_habit=0,
                i_create_aspect_ratio=0, i_create_bad=0, i_save_int_arr_sv=0,
                software="UIOOPS_v3.5", provenance=run_flight.V35_CALL.provenance,
            ),
        )
        version_txt = V35_TREE / "version.txt"
        self.assertEqual(version_txt.read_text(encoding="utf-8").strip(),
                         run_flight.V35_CALL.software)

    def test_the_sizedist_literals_match_the_vendored_commented_out_defaults(self):
        # sizeDist.m:91-94 -- the commented-out hardcoded variables Joe Finlon moved into the
        # argument list 11/17/17, each captioned "Default" in the vendored source itself.
        sizedist_m = (V35_TREE / "sizeDist.m").read_text(encoding="utf-8")
        lines = sizedist_m.splitlines()
        block = "\n".join(lines[91:94])  # 0-based slice for 1-based lines 92-94
        self.assertIn("iCreateBad = 0", block)
        self.assertIn("iCreateAspectRatio = 0", block)
        self.assertIn("iSaveIntArrSV = 0", block)
        self.assertEqual(run_flight.V35_CALL.i_create_bad, 0)
        self.assertEqual(run_flight.V35_CALL.i_create_aspect_ratio, 0)
        self.assertEqual(run_flight.V35_CALL.i_save_int_arr_sv, 0)

    def test_imgproc_literals_match_the_vendored_commented_out_defaults(self):
        # imgProc_sm.m:115,117-120 -- same pattern, for iRectEllipse/iCalcAllDiodeStats.
        imgproc_m = (V35_TREE / "imgProc_sm.m").read_text(encoding="utf-8")
        lines = imgproc_m.splitlines()
        self.assertIn("iRectEllipse = 0", lines[114])  # 1-based :115
        self.assertIn("iCalcAllDiodeStats = 0", lines[119])  # 1-based :120
        self.assertEqual(run_flight.V35_CALL.i_rect_ellipse, 0)
        self.assertEqual(run_flight.V35_CALL.i_calc_all_diode_stats, 0)


if __name__ == "__main__":
    unittest.main()
