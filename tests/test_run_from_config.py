# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe run`` -- one line: a config file, not a hand-built argv.

``arrayprobe.cli._run`` reads ``[run]`` from a TOML (``arrayprobe.config``) and builds
``scripts/run_flight.py``'s argv from it, then calls its unmodified ``main()``. No new
pipeline logic lives here or there -- these tests are about the plumbing: which engine
is chosen, which preset, which raw files, and that the resulting stamps are exactly
what the driver would have produced if a human had typed the equivalent flags.

**No flight runs, no raw decodes**: every test either resolves-only
(``--dry-run``, which runs ``preflight()`` and stops before S2) or patches
``run_flight.main`` with a spy so the real pipeline never executes. ``out`` is always
pointed into a tempdir -- never the default ``../_decoded`` relative to the test
runner's cwd, which would be the real, shared `_decoded/` this repository's validated
flights live in.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
SHIPPED_TOML = TOOLS / "oracles_2016_2ds.toml"

# Loaded exactly the way tests/test_run_flight_any_profile.py:46-49 does: by file
# path, under sys.modules["run_flight"], so this test file, arrayprobe.cli's
# _load_run_flight() and run_flight's own PROFILE global are all the SAME object.
_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules["make_demo_flight"] = make_demo_flight
_DEMO_SPEC.loader.exec_module(make_demo_flight)

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
run_flight = None  # bound in setUpModule, see below


def setUpModule():
    """Bind ``run_flight`` at RUN time, to whichever module object is REGISTERED then.

    ``discover`` imports every test module before running any. Binding at import time
    picked up the module registered at that moment, but
    ``tests/test_make_demo_flight.py:44-49`` re-registers a fresh ``run_flight`` while it
    RUNS (before this module runs, m < r), so ``cli._load_run_flight()`` then drove a module
    this file's spies and snapshots never saw -- green alone, two failures in the suite
    (2026-09-13). ``setUpModule`` runs after every earlier module's run-time effects and
    immediately before this module's tests, so both sides see one object. Never a private
    copy: if nothing is registered yet, register one, the same way every test does.
    """
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)

from tests._repo import needs_file, needs_v314_engine  # noqa: E402

from arrayprobe import cli  # noqa: E402 (after the run_flight/sys.modules setup above)


def _toml(text: str, dirpath: Path | None = None) -> Path:
    d = dirpath or Path(tempfile.mkdtemp())
    p = d / "run.toml"
    p.write_text(text, encoding="utf-8")
    return p


class _RunFlightStateIsolated(unittest.TestCase):
    """Snapshot/restore run_flight's module globals -- the same globals
    use_preset()/_apply_config() rebind -- so one test's --preset/--config
    cannot leak into the next (test_run_flight_any_profile.py's own pattern)."""

    def setUp(self):
        for name in ("PROFILE", "PROFILE_MODULE", "ACTIVE", "PROBE", "ORIENTATION",
                     "PROJECT", "D_CHOICE", "SA_METHOD", "PRES_PA", "TEMP_C", "ENGINE",
                     "PORT_VALIDATION"):
            self.addCleanup(setattr, run_flight, name, getattr(run_flight, name))


class RunIsRegisteredFirst(unittest.TestCase):
    def test_run_is_registered_first(self):
        # `run` first; what follows it is not this test's subject (Z16 registered `reprocess`
        # second on 2026-09-14, which the earlier "{run,read-binary" literal failed on).
        help_text = cli.build_parser().format_help()
        self.assertIn("{run,", help_text)


class OneDriverModule(unittest.TestCase):
    def test_the_cli_and_the_tests_share_one_driver_module(self):
        self.assertIs(cli._load_run_flight(), sys.modules["run_flight"])


@needs_file("scripts/oracles_2016_2ds.toml")
class DryRunFromTheShippedConfig(_RunFlightStateIsolated):
    """copy the shipped ORACLES 2016 2D-S config under a tempdir's own scripts/, so its
    ``out = "../_decoded"`` resolves to a sibling _decoded INSIDE the tempdir --
    never the real, shared _decoded/ this repo's validated flights live in."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        tools_dir = root / "scripts"
        tools_dir.mkdir()
        self.toml = tools_dir / SHIPPED_TOML.name
        shutil.copy(SHIPPED_TOML, self.toml)
        self.raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(self.raw, n_seconds=3)

    def test_dry_run_from_the_shipped_config_resolves_everything_from_the_file(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["run", str(self.toml), str(self.raw), "--dry-run",
                           "--port-validation"])
        log = buf.getvalue()
        self.assertEqual(rc, 0, log)
        from arrayprobe.profiles import ORACLES_PRODUCTION
        self.assertIs(run_flight.PROFILE, ORACLES_PRODUCTION)
        self.assertEqual(run_flight.ACTIVE.name, "ORACLES_2016_2DS_H")
        self.assertIn("config ", log)
        self.assertIn("-> profile", log)


class MissingEngineOrPreset(unittest.TestCase):
    def test_missing_engine_or_preset_is_exit_2_and_runs_nothing(self):
        toml = _toml('[fidelity]\nprofile = "STOCK_V314"\n')
        with mock.patch.object(run_flight, "main") as spy:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli.main(["run", str(toml), "--dry-run"])
        self.assertEqual(rc, 2)
        self.assertIn("[run].engine", err.getvalue())
        spy.assert_not_called()


class Engine35ReachesTheDriver(_RunFlightStateIsolated):
    """Since 2026-09-13 (the last gap), ``[run].engine = "3.5"`` is no longer refused at
    ``cli._run`` -- it dispatches to ``scripts/run_flight.py --engine 3.5``, which does its own
    engine/profile validation. ``run_flight.main`` is mocked here on purpose: this test is about
    the plumbing (``_run`` builds the right argv), not the driver's own gates, which
    ``tests/test_run_from_config_v35.py`` exercises for real."""

    def test_engine_35_is_forwarded_to_the_driver(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _toml('[fidelity]\nprofile = "stock-v3.5"\n'
                     '[run]\nengine = "3.5"\npreset = "ORACLES_2016_2DS_H"\n', root)
        raw = root / "base160101000000.2DS"
        raw.write_bytes(b"")
        with mock.patch.object(run_flight, "main", return_value=0) as spy:
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                rc = cli.main(["run", str(toml), str(raw), "--dry-run"])
        self.assertEqual(rc, 0, err.getvalue())
        spy.assert_called_once()
        (argv,), _ = spy.call_args
        self.assertEqual(argv[argv.index("--engine") + 1], "3.5")


class StockV314ReachesS2(_RunFlightStateIsolated):
    @needs_v314_engine
    def test_stock_v314_reaches_s2_without_any_refusal(self):
        # stages is explicit here, restricted to "2": this test asserts only
        # S2/profile-switch behaviour (PROFILE, image_call_label), and since
        # Phase 2b, "3" in stages under STOCK_V314 is refused before S2
        # ever runs unless a --tas-file / [run].tas_file is given
        # (imgProc_sm.m:183-185 needs the aircraft file) --
        # tests/test_run_from_config_tas.py covers that refusal and the
        # full S2->S3->S4 path with one given. This test's own scope (does
        # the OLD "only ORACLES_PRODUCTION runs" refusal, removed 2026-09-10,
        # stay gone for S2) is unaffected by stages="2".
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _toml('[fidelity]\nprofile = "STOCK_V314"\n'
                     '[run]\nengine = "3.1.4"\npreset = "ORACLES_2016_2DS_H"\n'
                     'out = "_decoded"\nstages = "2"\n', root)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["run", str(toml), str(raw), "--dry-run", "--port-validation"])
        self.assertEqual(rc, 0, buf.getvalue())
        from arrayprobe.profiles import STOCK_V314
        self.assertIs(run_flight.PROFILE, STOCK_V314)
        self.assertIn(f"profile={STOCK_V314.name}", run_flight.image_call_label(channels="H"))


@needs_file("scripts/oracles_2016_2ds.toml")
class ValidatedCallStampsAreByteIdentical(_RunFlightStateIsolated):
    """The done-criterion: what `arrayprobe run` under the shipped config makes
    S2/S3/S4 *stamp* is byte-identical to real, on-disk sidecars from a validated
    2016 flight. All three pasted below are ``_decoded/*base160912071923*`` on this
    machine, read 2026-09-13; mtimes 2026-09-10 (well after 2026-08-28, the
    reject-threshold correction; no earlier stamp is trusted).
    The plan's suggested example, base160910071623, turned out to have
    only stockreject/diodecorrected sd variants and one plain sd sidecar
    (sd.base160910102201.H.nc.call) dated 2026-08-29 that predates the current
    two-part sd_call_label format (it holds only ``iat_file=...``, no trailing
    ``profile=... reject=(...)`` -- an older-format sidecar, not a mismatch to
    chase); base160912071923 was picked instead because all three of its sidecars
    are current-format and same-day.

    Since 2026-09-15 every freshly-resolved v3.1.4 label carries an added
    ``engine=3.1.4 `` prefix these on-disk goldens (captured before that date) do not, so the
    comparison below is in two parts: the fresh label equals the golden plus that one prefix, and
    the OLD, real, on-disk text is still read as ``current`` against the new label via
    ``_stamps_equivalent`` -- an already-validated flight's sidecar does not go stale on this
    wording change alone.

    Since R4 (2026-09-30) every v3.1.4 run needs ``--port-validation`` and its labels
    also carry ``port_validation=on`` directly after ``engine=3.1.4``. The three
    ``_stamps_equivalent`` assertions are unchanged: they are the proof that the real 2026-09-10
    on-disk sidecars stay current under the new label.
    """

    # _decoded/base160912071923.H.cdf.call, read 2026-09-13, mtime 2026-09-10.
    _DECODE_STAMP = "profile=oracles-production spec_buffer_guard=False hvps_reader=hvps channels=H"
    # _decoded/proc.base160912071923.H.nc.call, read 2026-09-13, mtime 2026-09-10.
    _PROC_STAMP = ("profile=oracles-production reject=(rej_zero_area=True,rej_split=True,"
                   "rej_hollow=False,shadowed_area=25,max_edge_img_ar=4,max_comp_img_ar=4) "
                   "shadow_diode=none")
    # _decoded/sd.base160912071923.H.nc.call, read 2026-09-13, mtime 2026-09-10.
    # The 2026-09-17 stamp change appends a third fragment naming the S4 tree/area_ratio_z/
    # default_int_arr_thresh fields that were computed but never stamped before -- "(default)"
    # because this preset (ORACLES, tree=production, no --regime/override) resolves to exactly
    # the historical hard-coded values, tagged rather than left unnamed. The pre-2026-09-17
    # on-disk sidecar this golden otherwise reproduces has none of this fragment, and
    # _stamps_equivalent still reads it as current below -- the same precedent engine= set.
    _SD_STAMP = ("iat_file=2DS_intArrThreshold_MISSING.cdf " + _PROC_STAMP
                + " tree=production area_ratio_z=0.5 (default)"
                + " default_int_arr_thresh=6e-06 (default)")

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        tools_dir = root / "scripts"
        tools_dir.mkdir()
        self.toml = tools_dir / SHIPPED_TOML.name
        shutil.copy(SHIPPED_TOML, self.toml)
        self.raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(self.raw, n_seconds=3)

    def test_the_validated_call_stamps_are_byte_identical_to_the_pre_change_sidecars(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["run", str(self.toml), str(self.raw), "--dry-run",
                           "--port-validation"])
        self.assertEqual(rc, 0, buf.getvalue())
        image_label = run_flight.image_call_label(channels="H")
        proc_label = run_flight.proc_call_label()
        sd_label = run_flight.sd_call_label(run_flight.IAT_FILE)
        # The fresh label is the golden plus the engine=3.1.4 prefix and, since R4, the
        # port_validation=on token that every v3.1.4 run now writes.
        prefix = "engine=3.1.4 port_validation=on "
        self.assertEqual(image_label, prefix + self._DECODE_STAMP)
        self.assertEqual(proc_label, prefix + self._PROC_STAMP)
        self.assertEqual(sd_label, prefix + self._SD_STAMP)
        # And the OLD, real, on-disk text -- no engine= key at all -- is still read as CURRENT
        # against the new label, so this validated flight's sidecar does not go stale.
        self.assertTrue(run_flight._stamps_equivalent(self._DECODE_STAMP, image_label))
        self.assertTrue(run_flight._stamps_equivalent(self._PROC_STAMP, proc_label))
        self.assertTrue(run_flight._stamps_equivalent(self._SD_STAMP, sd_label))


class CommandLineRawWinsOverTheFile(unittest.TestCase):
    @needs_v314_engine
    def test_command_line_raw_wins_over_the_file(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _toml('[fidelity]\nprofile = "STOCK_V314"\n'
                     '[run]\nengine = "3.1.4"\npreset = "ORACLES_2016_2DS_H"\n'
                     'raw = ["nothing_*.2DS"]\nout = "_decoded"\n', root)
        positional_raw = root / "base160101000000.2DS"
        positional_raw.write_bytes(b"")
        with mock.patch.object(run_flight, "main", return_value=0) as spy:
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["run", str(toml), str(positional_raw), "--dry-run"])
        self.assertEqual(rc, 0)
        spy.assert_called_once()
        (argv,), _ = spy.call_args
        self.assertIn(str(positional_raw), argv)
        self.assertNotIn("nothing_*.2DS", " ".join(argv))


if __name__ == "__main__":
    unittest.main()
