# SPDX-License-Identifier: BSD-3-Clause
"""Engine-parity sweep for ``run_flight.py`` -- a flag one engine ignores, and its class.

The defect: ``--jit`` was a silent no-op under ``--engine 3.5``. ``run_flight.py:1501`` passes
``jit=JIT`` to the v3.1.4 ``imgproc.imgproc_sm``; the v3.5 branch never read ``JIT`` at all, and
``arrayprobe_uiops/imgproc.py`` has no jit kernels to route to. Reading the source showed ``main()``
already had a CLI-level refusal for this combination (added 2026-09-15, before the defect was filed)
-- but **nothing exercised it**: no test anywhere in the suite named the refusal message, so a
guard that only looks like a control ("a rule addressed to attention is not a
control... build the check") sat untested since it was written. ``JitEngineParityTests`` below
is that check, plus a defense-in-depth assertion at the one real chokepoint
(``_imgproc_sm_chunk``) for any caller that reaches it without going through ``main()``'s own gate
-- the ``--_run-chunk`` worker branch is exactly such a caller: it parses ``JIT``/``ENGINE`` from
raw trailing argv tokens with no validation of its own, trusting the parent already checked.

Task 2 asked for the sweep this file's name promises: every option ``run_flight.py`` accepts under
``--engine 3.5`` that only reaches the v3.1.4 path, and the converse. ``EveryCliFlagIsClassified``
is the mechanical version -- it draws its two sides from different places, per the task's own
requirement:

* Side A, the argument parser itself, extracted by intercepting the real
  ``argparse.ArgumentParser.parse_args`` call ``main()`` makes (not retyped by hand, so it cannot
  silently drift from what the CLI actually accepts).
* Side B, a hand-maintained classification of every flag's engine sensitivity, checked in this
  file against the real gate code in ``main()`` (not merely asserted).

A flag ``ap.add_argument``-ed later and left out of Side B's classification fails
``test_every_flag_is_classified`` immediately -- the "cannot add to one without the other"
property the task asked for. ``ThresholdOverrideEngineParityTests`` covers the sibling defect, found
by this same sweep: ``--regime``/``--area-ratio-z``/``--default-int-arr-thresh`` (and their
``[thresholds]`` config-file equivalents) were accepted under ``--engine 3.5``, silently parsed
into module globals, and never consumed -- the identical "accepted, does nothing, says nothing"
shape, fixed the same way (a named refusal in ``main()``'s ``ENGINE == "3.5"`` block).
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import netCDF4
from tests._repo import needs_v314_engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"

# Loaded by path, under sys.modules, the same way test_run_from_config_v35.py and
# test_run_flight_non_spec_probes.py do -- scripts/ is not a package.
_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules["make_demo_flight"] = make_demo_flight
_DEMO_SPEC.loader.exec_module(make_demo_flight)

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
run_flight = None  # bound in setUpModule


def setUpModule():
    """Bind ``run_flight`` at run time to whichever module object is already registered, so this
    file, ``arrayprobe.cli`` and any sibling test module that imported it first all share one
    module -- test_run_from_config_v35.py's own pattern, for the same reason."""
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


class _RunFlightStateIsolated(unittest.TestCase):
    """Snapshot/restore run_flight's module globals -- test_run_from_config_v35.py's pattern,
    so one test's --engine/--jit/--regime cannot leak into the next."""

    def setUp(self):
        for name in ("PROFILE", "PROFILE_MODULE", "TAS_FILE", "ENGINE", "JIT", "PORT_VALIDATION",
                     "LIBM_POW", "ACTIVE", "PROBE",
                     "ORIENTATION", "PROJECT", "D_CHOICE", "SA_METHOD", "PRES_PA", "TEMP_C",
                     "REGIME_NAME", "AREA_RATIO_Z_OVERRIDE", "DEFAULT_IAT_OVERRIDE"):
            self.addCleanup(setattr, run_flight, name, getattr(run_flight, name))


def _aircraft(path: Path, tas: float = 85.0) -> Path:
    """A synthetic aircraft TAS file matching the demo flight's three HHMMSS records --
    test_run_from_config_v35.py's own helper, duplicated here so this file stays self-contained
    (it does not own that file and must not edit it)."""
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", 3)
        time_var = ds.createVariable("Time", "f8", ("time",))
        tas_var = ds.createVariable("TAS", "f8", ("time",))
        time_var[:] = [60640, 60641, 60642]
        tas_var[:] = [tas, tas, tas]
    return path


def _v35_toml(root: Path, **extra_lines: str) -> Path:
    """A minimal ``[fidelity]``/``[run]`` config naming the stock-v3.5 profile and engine, always
    the synthetic ``DEMO_2DS_H`` preset (no campaign data required). ``extra_lines`` are appended
    as ``key = value`` pairs inside whichever ``[section]`` the caller already opened via a raw
    string in the value -- kept simple since callers here only ever add ``[thresholds]``."""
    lines = [
        "[fidelity]",
        'profile = "stock-v3.5"',
        "[run]",
        'engine = "3.5"',
        'preset = "DEMO_2DS_H"',
        'out = "_decoded"',
        'stages = "234"',
        'tas_file = "aircraft.cdf"',
    ]
    for raw in extra_lines.values():
        lines.append(raw)
    p = root / "run.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _demo_root() -> Path:
    root = Path(tempfile.mkdtemp())
    raw = root / "base160101000000.2DS"
    make_demo_flight.build_demo_flight(raw, n_seconds=3)
    _aircraft(root / "aircraft.cdf")
    return root, raw


def _direct(root: Path, raw: Path, toml: Path, *extra) -> tuple[int, str]:
    """Call ``run_flight.main`` exactly as a direct (non ``arrayprobe run``) invocation would,
    capturing stdout -- the same helper shape test_run_from_config_v35.py's own ``_direct`` uses,
    duplicated for the reason ``_aircraft`` is."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_flight.main([str(raw), "--config", str(toml), "--engine", "3.5",
                              "--preset", "DEMO_2DS_H", "--out", str(root / "_decoded"), *extra])
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------------------------
# Task 1 -- the defect itself: --jit under --engine 3.5.
# ---------------------------------------------------------------------------------------------

class JitEngineParityTests(_RunFlightStateIsolated):

    def test_jit_is_no_longer_refused_under_engine_35(self):
        """--jit was refused here until 2026-09-18, when arrayprobe_uiops.jit_kernels landed.

        This test was written the other way round earlier the same day, asserting the refusal
        fires -- and it did, correctly, for the three days when v3.5 had no kernels to route to.
        It is inverted rather than deleted so the transition is visible in one place: the
        refusal is gone, and the reason it is gone is that the capability now exists
        (tests/test_v35_imgproc_jit_identity.py proves byte-identity on a real production CIP
        file, 1.79x measured). What must NOT come back is the third state -- accepted and
        silently ignored -- which is what the defect was actually about.
        """
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root)
        rc, out = _direct(root, raw, toml, "--jit")
        self.assertNotIn("--jit is not available", out)
        self.assertNotIn("no v3.5 jit kernels", out)

    def test_diode_corrected_is_accepted_under_engine_35(self):
        """--diode-corrected was refused under 3.5 until imgproc_sm_v35 gained shadow_diode=
        (tests/test_v35_shadow_diode.py). Inverted rather than deleted, as the --jit test above
        was: the refusal is gone because the capability exists, and the driver forwards the
        mask (tests/test_v35_shadow_diode.py::DriverForwardsTheMask)."""
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root)
        rc, out = _direct(root, raw, toml, "--diode-corrected", "--dry-run", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("--diode-corrected is not available", out)
        self.assertNotIn("diode masking: off", out)

    def test_an_unmasked_engine_35_run_suggests_tuning(self):
        """Author decision 4 (masking tuning): masking is off by
        default, and a v3.5 run without it prints one line naming the tuner."""
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root)
        rc, out = _direct(root, raw, toml, "--dry-run", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("diode masking: off (suggested: run `arrayprobe tune diodes`", out)

    def test_s2_jobs_is_accepted_under_engine_35(self):
        """arrayprobe_uiops.spec.read_binary_spec_v35_parallel exists and is byte-identical to the
        serial decode (tests/test_v35_spec_parallel.py), so main() no longer refuses the flag
        for a probetype-2 preset. --dry-run stops before any stage, after every gate."""
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root)
        rc, out = _direct(root, raw, toml, "--s2-jobs", "2", "--dry-run",
                          "--tas-file", str(root / "aircraft.cdf"))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("not available under --engine 3.5", out)

    def test_jit_is_forwarded_to_the_v35_call_not_dropped(self):
        """The whole point of the fix: the flag must REACH imgproc_sm_v35, not be accepted and
        discarded. run_flight.py:1509 passes jit=JIT; this asserts it arrives."""
        run_flight.ENGINE = "3.5"
        run_flight.JIT = True
        run_flight.PROFILE = run_flight.STOCK_V35
        run_flight.TAS_FILE = None
        # A CIP (probetype 1), deliberately: the probetype-2 branch reads an aircraft TAS
        # series before dispatching, so a 2D-S here would fail on the missing file rather
        # than on the thing under test.
        run_flight.PROBE = "CIP"
        captured = {}

        class _FakeV35:
            def module(self, _name):
                return self

            PROBES_V35 = run_flight._v35().module("imgproc").PROBES_V35

            def imgproc_sm_v35(self, *a, **kw):
                captured.update(kw)
                return 0

        with mock.patch.object(run_flight, "_v35", lambda: _FakeV35()):
            run_flight._imgproc_sm_chunk(Path("in.cdf"), Path("out.nc"), 1, 10)
        self.assertIn("jit", captured)
        self.assertTrue(captured["jit"])

    @needs_v314_engine
    def test_jit_still_reaches_the_v314_call(self):
        """Positive control: the flag that engine 3.5 refuses must still work on the engine it was
        built for -- run_flight.py:1501 passes jit=JIT to imgproc.imgproc_sm."""
        run_flight.ENGINE = "3.1.4"
        run_flight.JIT = True
        run_flight.PROFILE = run_flight.ORACLES_PRODUCTION
        run_flight.TAS_FILE = None
        captured = {}

        def _fake_imgproc_sm(*a, **kw):
            captured.update(kw)
            return 0

        with mock.patch.object(run_flight.imgproc, "imgproc_sm", _fake_imgproc_sm):
            run_flight._imgproc_sm_chunk(Path("in.cdf"), Path("out.nc"), 1, 10)
        self.assertIn("jit", captured)
        self.assertTrue(captured["jit"])

    def test_imgproc_sm_chunk_is_fine_under_v35_without_jit(self):
        """The assertion added for the fix must not fire on the ordinary, unremarkable case --
        ENGINE 3.5 with JIT off reaches the real v35 dispatch (mocked here) rather than raising."""
        run_flight.ENGINE = "3.5"
        run_flight.JIT = False
        run_flight.PROFILE = run_flight.STOCK_V35
        run_flight.TAS_FILE = None
        run_flight.PROBE = "2DS"
        run_flight.PROJECT = "DEMO"
        with mock.patch.object(run_flight, "_v35") as fake_v35, \
             mock.patch.object(run_flight, "_aircraft_series", return_value=(None, None)):
            fake_module = mock.Mock()
            fake_module.PROBES_V35 = {"2DS": mock.Mock(probetype=2)}
            fake_module.imgproc_sm_v35.return_value = 0
            fake_v35.return_value.module.return_value = fake_module
            run_flight._imgproc_sm_chunk(Path("in.cdf"), Path("out.nc"), 1, 10)
            self.assertTrue(fake_module.imgproc_sm_v35.called)


# ---------------------------------------------------------------------------------------------
# Task 2, finding 1 -- the sibling defect: the S4 threshold overrides under --engine 3.5.
# ---------------------------------------------------------------------------------------------

class ThresholdOverrideEngineParityTests(_RunFlightStateIsolated):

    def test_regime_is_accepted_under_engine_35_from_the_command_line(self):
        """Refused until the regime thresholds are wired in: the regime's two S4
        values now reach v3.5 sizedist.run's keywords (tests/test_regime_v35_driver.py)."""
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root)
        rc, out = _direct(root, raw, toml, "--regime", "liquid-warm", "--dry-run", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("not available under --engine 3.5", out)
        self.assertIn("thresholds area_ratio_z (S4, v3.5) = 0.5 (regime:liquid-warm)", out)
        self.assertIn("thresholds default_int_arr_thresh (S4, v3.5) = 6e-06 (regime:liquid-warm)",
                      out)

    def test_area_ratio_z_is_accepted_under_engine_35_from_the_command_line(self):
        """Was refused until the v3.5 keyword existed (``arrayprobe_uiops.sizedist.run``'s
        ``area_ratio_z``, sizeDist.m:1162; tests/test_v35_area_ratio_z.py): now it reaches S4."""
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root)
        rc, out = _direct(root, raw, toml, "--area-ratio-z", "0.5", "--dry-run", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("not available under --engine 3.5", out)
        self.assertIn("area_ratio_z (S4, 'z' reject, v3.5 sizeDist.m:1162) = 0.5", out)

    def test_area_ratio_z_outside_zero_to_one_is_refused_under_engine_35(self):
        for bad in ("1.5", "-0.1", "nan", "inf"):
            with self.subTest(value=bad):
                root, raw = _demo_root()
                self.addCleanup(shutil.rmtree, root, ignore_errors=True)
                toml = _v35_toml(root)
                rc, out = _direct(root, raw, toml, f"--area-ratio-z={bad}", "--dry-run", "--yes")
                self.assertEqual(rc, 2, out)
                self.assertIn("[0, 1]", out)

    def test_area_ratio_z_zero_is_the_gate_off_and_is_accepted_under_engine_35(self):
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root)
        rc, out = _direct(root, raw, toml, "--area-ratio-z", "0", "--dry-run", "--yes")
        self.assertEqual(rc, 0, out)

    def test_a_config_thresholds_area_ratio_z_is_accepted_under_engine_35(self):
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root, thresholds="[thresholds]\narea_ratio_z = 0.5\n")
        rc, out = _direct(root, raw, toml, "--dry-run", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("not available under --engine 3.5", out)
        self.assertIn("area_ratio_z (S4, 'z' reject, v3.5 sizeDist.m:1162) = 0.5", out)

    def test_default_int_arr_thresh_is_accepted_under_engine_35_from_the_command_line(self):
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root)
        rc, out = _direct(root, raw, toml, "--default-int-arr-thresh", "1e-5", "--dry-run",
                          "--yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("thresholds default_int_arr_thresh (S4, v3.5) = 1e-05 (user:cli)", out)

    def test_default_int_arr_thresh_outside_its_range_is_refused_under_engine_35(self):
        for bad in ("-1e-6", "nan", "inf"):
            with self.subTest(value=bad):
                root, raw = _demo_root()
                self.addCleanup(shutil.rmtree, root, ignore_errors=True)
                toml = _v35_toml(root)
                rc, out = _direct(root, raw, toml, f"--default-int-arr-thresh={bad}",
                                  "--dry-run", "--yes")
                self.assertEqual(rc, 2, out)
                self.assertIn(">= 0", out)

    def test_a_config_file_thresholds_regime_is_also_accepted(self):
        """The sharper of the two paths: _apply_config writes [thresholds].regime straight into
        the REGIME_NAME global (not into args.regime), so the v3.5 S4 values are read from the
        global (_v35_s4_thresholds), and a config-sourced regime reaches them too."""
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _v35_toml(root, thresholds='[thresholds]\nregime = "ice"\n')
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main([str(raw), "--config", str(toml), "--engine", "3.5",
                                  "--preset", "DEMO_2DS_H", "--out", str(root / "_decoded"),
                                  "--dry-run", "--yes"])
        out = buf.getvalue()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("not available under --engine 3.5", out)
        self.assertIn("thresholds area_ratio_z (S4, v3.5) = 0.2 (regime:ice)", out)

    @needs_v314_engine
    def test_engine_314_is_unaffected_by_the_new_gate(self):
        """The new checks must not fire for the engine they were never about."""
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main([str(raw), "--preset", "DEMO_2DS_H", "--engine", "3.1.4",
                                  "--port-validation",
                                  "--regime", "liquid-warm", "--out", str(root / "_decoded"),
                                  "--dry-run", "--yes"])
        out = buf.getvalue()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("not available under --engine 3.5", out)


# ---------------------------------------------------------------------------------------------
# Task 2 -- the mechanical sweep: every CLI flag must be classified, and every classification
# must be exercised against the real dispatch code, not merely asserted.
# ---------------------------------------------------------------------------------------------

def _real_parser() -> argparse.ArgumentParser:
    """The actual ``argparse.ArgumentParser`` ``main()`` builds -- Side A of the sweep, extracted
    from the real object rather than retyped, by intercepting the one ``parse_args`` call ``main``
    makes on it (the small throwaway ``--presets`` pre-parser uses ``parse_known_args``, a
    different method, so it is not captured here)."""
    captured: dict[str, argparse.ArgumentParser] = {}
    original = argparse.ArgumentParser.parse_args

    def _capture(self, *a, **kw):
        captured["ap"] = self
        return original(self, *a, **kw)

    buf = io.StringIO()
    with mock.patch.object(argparse.ArgumentParser, "parse_args", _capture), \
         redirect_stdout(buf):
        with unittest_assertRaisesSystemExit():
            run_flight.main(["--help"])
    return captured["ap"]


class unittest_assertRaisesSystemExit:
    """``--help`` always exits; a tiny context manager so ``_real_parser`` reads as one line."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is SystemExit


#: Side B: every CLI flag's engine sensitivity, by dest name -- hand-maintained and checked
#: (test_every_flag_is_classified) against Side A, the real parser, so a flag added to argparse
#: and left out here fails immediately rather than silently defaulting to "nobody checked".
#:
#: "engine_agnostic"        -- meaningful and consumed the same way under either engine, OR its
#:                              own engine-sensitivity is verified by a different, existing test
#:                              named in the comment (chunks, iat_file: partial/conditional
#:                              refusals, not a blanket one, so this sweep does not re-derive
#:                              their exact condition).
#: "engine_314_only_refused" -- meaningful under v3.1.4 only; main() must refuse it under
#:                              --engine 3.5, and this file exercises that refusal directly.
#: "engine_35_only_refused"  -- the converse: meaningful under v3.5 only; main() must refuse it
#:                              under any other --engine.
#: "both_engines"           -- has a tested meaning on each engine (same flag, one spelling),
#:                              so neither engine's gate may refuse it; the ones whose
#:                              acceptance is cheap to drive through a dry-run carry a trigger
#:                              in ``_TRIGGER_BOTH`` and are exercised under both engines.
#: "selector"                -- --engine itself; not classified relative to itself.
FLAG_CLASSIFICATION: dict[str, str] = {
    "raw": "engine_agnostic",
    "out": "engine_agnostic",
    "stages": "engine_agnostic",
    "yes": "engine_agnostic",
    "dry_run": "engine_agnostic",
    "jobs": "engine_agnostic",           # forwarding: test_worker_argument_forwarding.py
    "enh_jobs": "engine_agnostic",       # the enhancement pass's worker count, either engine
    "s2_jobs": "both_engines",           # 3.5: tests/test_v35_spec_parallel.py
    "chunks": "engine_agnostic",         # partial under 3.5, probe-conditional (see above)
    "jit": "both_engines",
    "protective": "engine_agnostic",   # decided by probetype, never by engine
    "protective_worker": "engine_agnostic",   # internal, parent applies once
    "worker_stall_min": "engine_agnostic",
    "resume_chunks": "engine_agnostic",  # which chunks the parent respawns; each chunk is built
                                         # the same way on either engine
    "tas_from_probe": "engine_agnostic",  # CIP airspeed from the 2D-S housekeeping; v3.1.4 on CIP
                                          # is refused (CIP rule) before this flag is read
    "iat_file": "engine_agnostic",       # v3.5 has its own existence check, above
    "iat_source": "engine_314_only_refused",  # the HVPS per-flight threshold table resolves
                                             # a v3.1.4 sizeDist call; _resolve_iat_source
                                             # refuses any other engine before the probe
    "tas_file": "engine_agnostic",       # profile-scoped, not engine-scoped; read by both engines
    "tas_source": "engine_agnostic",     # resolves the chain for either engine;
                                         # refused together with --tas-file, not with --engine
    "tas_ratio": "engine_35_only_refused",  # v3.5 decoder input; refused on --engine 3.1.4
    "accept_implausible": "engine_agnostic",  # post-S4 plausibility gate, same for either engine
    "tas_search": "engine_agnostic",     # the chain's search directories, same scope as source
    "tas_grid": "engine_agnostic",       # S4's time vector; both engines' sizeDist walk it alike
    "tas_cutoff_mps": "engine_agnostic",  # TasPolicy override, engine-independent
    "tas_default_mps": "engine_agnostic",  # TasPolicy override, engine-independent
    "diode_corrected": "both_engines",   # v3.5: imgproc_sm_v35(shadow_diode=)
    "accept_flagged": "engine_agnostic",   # raw-input inventory preflight, before any engine
    "accept_unstamped": "engine_agnostic",
    "accept_preset_mismatch": "engine_agnostic",  # preset check before any engine
    "allow_mixed_config": "engine_agnostic",
    "preset": "engine_agnostic",
    "presets": "engine_agnostic",
    "engine": "selector",
    "attributed": "engine_agnostic",     # post-combine export; reads the .call sidecar generically
    "borrowed_combine": "engine_35_only_refused",
    "regime": "both_engines",            # v3.5: sizedist.run(area_ratio_z=,
                                         # default_int_arr_thresh=) + S3 reject_config; regime
                                         # slice 4, tests/test_regime_v35_driver.py
    "area_ratio_z": "both_engines",      # v3.5: sizedist.run(area_ratio_z=), sizeDist.m:1162,
                                         # Octave shadowing-copy oracle; tests/test_v35_area_
                                         # ratio_z.py, test_v35_area_ratio_z_oracle.py
    "default_int_arr_thresh": "both_engines",  # v3.5: sizedist.run(default_int_arr_thresh=)
    # S4 case inputs, both engines' sizedist.run(tas_max=, pecan_params=); no _TRIGGER_BOTH
    # entry, because DEMO_2DS_H's case refuses both: tests/test_run_flight_s4_case_inputs.py.
    "tas_max": "both_engines",
    "pecan_params": "both_engines",
    "libm_pow": "engine_314_only_refused",        # B9; engine 3.5 always uses libm pow
    "port_validation": "engine_314_only_refused",  # R4: required with 3.1.4, refused
                                                   # under any other engine (its own test module)
    "config": "engine_agnostic",
    # Added 2026-09-21. Each is classified from what the driver actually does with it, not
    # from where it was introduced -- checked against run_flight.main's own refusals.
    "enhancements": "engine_agnostic",   # applies [enhancements] to finished products; the
                                         # applicability table is per-engine, the flag is not
    "write_provenance": "engine_agnostic",  # refuses --engine 3.5 AND --chunks/--jobs alike:
                                         # a combination refusal, not an engine one
    "profile": "engine_agnostic",        # profiles are cited per engine; the flag selects one
                                         # and main refuses a v3.1.4-cited profile under 3.5
    "probe_case": "engine_35_only_refused",        # sizeDist's probe-case registry is v3.5 only
    "probe_case_module": "engine_35_only_refused",  # its import-time registration, same scope
    "time_offset_s": "engine_35_only_refused",     # arrayprobe_uiops sizeDist keyword (a66fc88)
    "time_offset_evidence": "engine_35_only_refused",  # required with it, same scope
    "time_offset_tas_clock": "engine_35_only_refused",  # required with it, same scope
    "stray_pixel": "engine_35_only_refused",       # stray-pixel rule: resolve_stray_pixel refuses
                                                   # --stray-pixel on under any other engine;
                                                   # "off" resolves off there (a no-op)
    "ncar_2dc_timing": "engine_35_only_refused",   # resolve_ncar_2dc_timing refuses
                                                   # --ncar-2dc-timing on under 3.1.4; "off"
                                                   # resolves off there (a no-op)
}

#: One (flag, cli-args-to-trigger-it) pair per "engine_314_only_refused" entry above, used to
#: actually exercise main() rather than trust the classification text.
_TRIGGER_314_ONLY: dict[str, tuple[str, ...]] = {
    "jit": ("--jit",),
    "libm_pow": ("--libm-pow",),
    "port_validation": ("--port-validation",),  # R4: the converse refusal
    "iat_source": ("--iat-source", "flight-table"),
}

#: One trigger per "both_engines" entry: accepted (dry-run exit 0) under 3.1.4 and under 3.5.
_TRIGGER_BOTH: dict[str, tuple[str, ...]] = {
    "area_ratio_z": ("--area-ratio-z", "0.5"),
    "diode_corrected": ("--diode-corrected",),
    "regime": ("--regime", "liquid-warm"),
    "default_int_arr_thresh": ("--default-int-arr-thresh", "1e-5"),
}


class EveryCliFlagIsClassified(_RunFlightStateIsolated):

    def test_every_flag_is_classified(self):
        """Side A (the real parser) vs Side B (FLAG_CLASSIFICATION above): a flag on one side and
        not the other fails here. This is the "cannot add an option to one without the other"
        check Task 2 asked for."""
        ap = _real_parser()
        dests = {a.dest for a in ap._actions if a.dest != "help"}
        classified = set(FLAG_CLASSIFICATION)
        self.assertEqual(
            dests - classified, set(),
            "run_flight.py grew a new CLI flag with no engine-sensitivity classification in "
            "FLAG_CLASSIFICATION (test_engine_flag_parity.py) -- classify it before shipping, "
            "the same way a new probe must be classified in run_flight.S2_READERS")
        self.assertEqual(
            classified - dests, set(),
            "FLAG_CLASSIFICATION names a flag run_flight.py's parser no longer has -- stale entry")

    def test_every_engine_314_only_flag_is_actually_refused_under_engine_35(self):
        """Side B's claim, checked against Side A's dispatch code by actually running it --
        reading the gate tuple and trusting it is exactly the failure mode that let --jit go
        untested from 2026-09-15 until the --jit fix."""
        for dest, cls in sorted(FLAG_CLASSIFICATION.items()):
            if cls != "engine_314_only_refused":
                continue
            with self.subTest(flag=dest):
                root, raw = _demo_root()
                try:
                    toml = _v35_toml(root)
                    rc, out = _direct(root, raw, toml, *_TRIGGER_314_ONLY[dest])
                    self.assertEqual(rc, 2, f"--{dest.replace('_', '-')} was NOT refused under "
                                            f"--engine 3.5:\n{out}")
                finally:
                    shutil.rmtree(root, ignore_errors=True)

    @needs_v314_engine
    def test_every_both_engines_flag_is_accepted_under_each_engine(self):
        """The class the new classification adds: a flag meant for both engines must not be
        refused by either gate. Exercised by running ``main`` in ``--dry-run`` under each."""
        self.assertEqual(
            {d for d in _TRIGGER_BOTH if FLAG_CLASSIFICATION.get(d) != "both_engines"}, set(),
            "a _TRIGGER_BOTH entry whose flag is not classified both_engines")
        start_profile = run_flight.PROFILE
        for dest in sorted(_TRIGGER_BOTH):
            for engine in ("3.1.4", "3.5"):  # 3.1.4 first: run_flight keeps PROFILE across calls
                if engine == "3.1.4":
                    # ...so a second flag's 3.1.4 run starts from the profile the first flag's
                    # 3.1.4 run had, not the stock-v3.5 its 3.5 run left behind.
                    run_flight.PROFILE = start_profile
                with self.subTest(flag=dest, engine=engine):
                    root, raw = _demo_root()
                    try:
                        buf = io.StringIO()
                        with redirect_stdout(buf):
                            rc = run_flight.main(
                                [str(raw), "--preset", "DEMO_2DS_H", "--engine", engine,
                                 "--out", str(root / "_decoded"), "--dry-run", "--yes",
                                 *(["--tas-file", str(root / "aircraft.cdf")]
                                   if engine == "3.5" else ["--port-validation"]),
                                 *_TRIGGER_BOTH[dest]] +
                                (["--profile", "stock-v3.5"] if engine == "3.5" else []))
                        self.assertEqual(rc, 0, buf.getvalue())
                        self.assertNotIn("not available under --engine", buf.getvalue())
                    finally:
                        shutil.rmtree(root, ignore_errors=True)

    @needs_v314_engine
    def test_the_engine_35_only_flag_is_refused_under_engine_314(self):
        """The converse direction, for completeness: --borrowed-combine is meaningless (and
        refused) under any engine but 3.5 -- also covered by
        test_run_from_config_v35.py::StageCUnderThirtyFiveNeedsTheBorrowedKey, exercised again
        here so it is caught by this sweep's own machinery too, not only by a hand-written test
        that has to be remembered to be kept in sync."""
        root, raw = _demo_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main([str(raw), "--preset", "DEMO_2DS_H", "--engine", "3.1.4",
                                  "--port-validation",
                                  "--stages", "234c", "--borrowed-combine",
                                  "--out", str(root / "_decoded"), "--yes"])
        out = buf.getvalue()
        self.assertEqual(rc, 2, out)
        self.assertIn("--engine 3.5 only", out)


# ---------------------------------------------------------------------------------------------
# Task 3 (2026-09-18) -- --regime was documented in --help with no hint that --engine 3.5
# refuses it outright (run_flight.py's ENGINE == "3.5" block, exercised above by
# ThresholdOverrideEngineParityTests): a user only learned of the restriction by hitting the
# runtime refusal, found while getting ARM ENA data running on v3.5 for the first time.
# --area-ratio-z / --default-int-arr-thresh share the identical gate (same tuple, same message)
# and so share the same fix. Side A is the real parser's own --help text, the same one
# EveryCliFlagIsClassified reads above -- not retyped, so this cannot silently drift from what
# --help actually prints.
#
# Deliberately scoped to these three, not swept over every "engine_314_only_refused" entry in
# FLAG_CLASSIFICATION: --diode-corrected is now accepted under both engines (classified
# both_engines above), so it has no engine restriction to name in its --help text.
# ---------------------------------------------------------------------------------------------

#: The two threshold flags that were gated by run_flight.py's ENGINE == "3.5" block until regime
#: slice 4 lifted it (``--area-ratio-z`` left it earlier, when v3.5 gained its own keyword). Their
#: help must now name both engines and no refusal.
_THRESHOLD_FLAGS_FORMERLY_314_ONLY: tuple[str, ...] = ("regime", "default_int_arr_thresh")


class ThresholdFlagHelpNamesTheEngineRestriction(unittest.TestCase):

    def test_the_two_threshold_flags_say_both_engines_in_their_own_help(self):
        ap = _real_parser()
        by_dest = {a.dest: a for a in ap._actions}
        for dest in _THRESHOLD_FLAGS_FORMERLY_314_ONLY:
            with self.subTest(flag=dest):
                help_text = by_dest[dest].help or ""
                self.assertIn("BOTH ENGINES", help_text)
                self.assertIn("3.5", help_text)
                self.assertNotIn("refused", help_text)
                self.assertNotIn("3.1.4 ONLY", help_text)

    def test_area_ratio_z_help_names_both_engines_and_the_v35_range(self):
        ap = _real_parser()
        help_text = {a.dest: a for a in ap._actions}["area_ratio_z"].help or ""
        self.assertIn("3.1.4", help_text)
        self.assertIn("3.5", help_text)
        self.assertIn("[0, 1]", help_text)
        self.assertIn("sizeDist.m:1162", help_text)
        self.assertNotIn("refused", help_text)

    def test_every_threshold_flag_is_classified_both_engines(self):
        """Side check against EveryCliFlagIsClassified's record: no threshold flag is engine-3.1.4
        only any more, so this file cannot drift from FLAG_CLASSIFICATION."""
        for dest in ("regime", "area_ratio_z", "default_int_arr_thresh"):
            self.assertEqual(FLAG_CLASSIFICATION[dest], "both_engines", dest)


if __name__ == "__main__":
    unittest.main()
