# SPDX-License-Identifier: BSD-3-Clause
"""``[run].tas_file`` / ``--tas-file`` -- Phase 2b: threading stock
``imgProc_sm``'s aircraft TAS file through ``arrayprobe run`` so ``STOCK_V314``
reaches S3 and S4, end to end, from one configuration file.

Companion to ``tests/test_run_from_config.py`` (Phase 1): that file proved
``STOCK_V314`` reaches S2 without refusal but explicitly left threading a
``tas_file`` argument through S3 out of scope
(``tests/test_run_flight_any_profile.py``'s own docstring: "real, known, and
NOT fixed here"). This is that follow-up, done.

No flight runs, no raw decodes beyond the ~7 s synthetic demo flight
(``make_demo_flight.build_demo_flight``): every test's ``[run].out``
is ``"_decoded"`` relative to the TOML in its own tempdir, never the shared
``../_decoded``.
"""

from __future__ import annotations

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
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"

# Loaded exactly the way test_run_from_config.py does: by file path, under
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
    """Bind ``run_flight`` at RUN time, to whichever module object is registered
    then -- ``test_run_from_config.py``'s ``setUpModule``, for the same reason.

    Other test modules register their own ``run_flight`` into ``sys.modules`` when
    they are imported or run, and ``cli._load_run_flight()`` drives whichever is
    registered. Bound at import time, this file snapshotted and restored one object
    while ``arrayprobe run`` rebound another, and the ``PROFILE``/``TAS_FILE`` it
    left behind made ``test_run_flight_exit_code`` refuse with rc 2 when this
    module ran first (found at the pair B/D merge, 2026-09-13). Never a private copy.
    """
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)

from tests import _run_flight_state  # noqa: E402
from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import cli  # noqa: E402 (after the run_flight/sys.modules setup above)
from arrayprobe.profiles import ORACLES_PRODUCTION, STOCK_V314  # noqa: E402


class _RunFlightStateIsolated(unittest.TestCase):
    """Snapshot/restore run_flight's module globals -- the same globals
    use_preset()/_apply_config() rebind -- so one test's --preset/--config/
    --tas-file cannot leak into the next (test_run_from_config.py's own
    pattern; ``TAS_FILE`` is added to the restored list here because this
    module is what starts rebinding it)."""

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)


def _toml(root: Path, stages: str, tas_file: str | None = None,
          profile: str = "STOCK_V314") -> Path:
    """A run configuration naming ``profile``, the shattering threshold that
    reproduces the ORACLES call, and ``stages``; ``tas_file`` (relative to
    ``root``, matching where :func:`_aircraft` writes it) is appended only
    when given, exactly as a real config would omit the key entirely."""
    lines = [
        "[fidelity]",
        f'profile = "{profile}"',
        "[shattering]",
        'threshold_file = "2DS_intArrThreshold_MISSING.cdf"',
        "[run]",
        'engine = "3.1.4"',
        'preset = "ORACLES_2016_2DS_H"',
        'out = "_decoded"',
        f'stages = "{stages}"',
    ]
    if tas_file is not None:
        lines.append(f'tas_file = "{tas_file}"')
    p = root / "run.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _aircraft(path: Path, tas: float = 85.0) -> Path:
    """A synthetic aircraft TAS file matching the demo flight's three HHMMSS
    records (imgproc.py:981-983's lookup key): dimension ``time``(3), ``Time``
    = [60640, 60641, 60642] (hour 6 / minute 6 / second 40-42, the demo's own
    default start), ``TAS`` = [tas]*3 -- NETCDF3_CLASSIC, matching every file
    this port writes.
    """
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", 3)
        time_var = ds.createVariable("Time", "f8", ("time",))
        tas_var = ds.createVariable("TAS", "f8", ("time",))
        time_var[:] = [60640, 60641, 60642]
        tas_var[:] = [tas, tas, tas]
    return path


class StockV314RunsEndToEnd(_RunFlightStateIsolated):
    """T1 -- the done-criterion: STOCK_V314 reaches S4 from one file, one line."""

    @needs_v314_engine
    def test_stock_v314_reaches_s4_from_one_file_and_one_line(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")
        toml = _toml(root, "234", "aircraft.cdf")

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["run", str(toml), str(raw), "--yes", "--port-validation"])
        self.assertEqual(rc, 0, buf.getvalue())

        decoded = root / "_decoded"
        proc = decoded / "proc.base160101000000.H.nc"
        sd = decoded / "sd.base160101000000.H.nc"
        self.assertTrue(proc.is_file(), buf.getvalue())
        self.assertTrue(sd.is_file(), buf.getvalue())

        proc_stamp = run_flight.read_stamp(proc)
        self.assertEqual(proc_stamp, run_flight.proc_call_label())
        self.assertTrue((proc_stamp or "").endswith(" tas_file=aircraft.cdf"), proc_stamp)

        sd_stamp = run_flight.read_stamp(sd)
        self.assertEqual(sd_stamp, run_flight.sd_call_label(run_flight.IAT_FILE))
        # Engine 3.1.4 reproduces the archived record: none of engine 3.5's default-on
        # corrections, nor the post-S4 plausibility gate, may reach its stamps.
        for stamp in (proc_stamp or "", sd_stamp or ""):
            for token in ("bins=", "time_sv_fix=", "zero_sv_seconds=", "time_grid_fix=",
                          "particle_clock_fix=", "plausibility=", "accept_implausible="):
                self.assertNotIn(token, stamp)


class TheAircraftFileReachesTheComputation(_RunFlightStateIsolated):
    """T2 -- the file is consumed, not merely accepted: ``Time_in_seconds``
    scales inversely with the TAS the aircraft file carries."""

    def _time_in_seconds(self, tas_mps: float) -> np.ndarray:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf", tas=tas_mps)
        toml = _toml(root, "23", "aircraft.cdf")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["run", str(toml), str(raw), "--yes", "--port-validation"])
        self.assertEqual(rc, 0, buf.getvalue())
        proc = root / "_decoded" / "proc.base160101000000.H.nc"
        with netCDF4.Dataset(proc) as ds:
            return np.asarray(ds.variables["Time_in_seconds"][:], dtype=float).ravel()

    @needs_v314_engine
    def test_time_in_seconds_scales_with_the_tas_in_the_file(self):
        # part_time * (ds/1e3/speed) (imgproc.py:988): halving speed doubles
        # the result, so 340 -> 85 (4x slower) must scale the array by 4x.
        a = self._time_in_seconds(85.0)
        b = self._time_in_seconds(340.0)
        np.testing.assert_allclose(a, 4 * b)


class Refusals(_RunFlightStateIsolated):
    """T3/T3b/T3c/T3d/T3e -- the four ambiguous calls refused before S2 ever
    runs, and the one case (stages without '3') that must not ask at all."""

    @staticmethod
    def _run(toml, *raws):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["run", str(toml), *(str(r) for r in raws), "--yes",
                           "--port-validation"])
        return rc, buf.getvalue()

    @needs_v314_engine
    def test_needed_and_missing_is_exit_2_before_s2(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        toml = _toml(root, "234")  # no tas_file; STOCK_V314 needs one
        rc, out = self._run(toml, raw)
        self.assertEqual(rc, 2, out)
        self.assertIn("pass --tas-file", out)
        decoded = root / "_decoded"
        h_cdfs = list(decoded.glob("*.H.cdf")) if decoded.exists() else []
        self.assertEqual(h_cdfs, [], "S2 must never have run")

    @needs_v314_engine
    def test_given_under_a_profile_that_never_reads_one_is_exit_2(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        _aircraft(root / "aircraft.cdf")
        toml = _toml(root, "234", "aircraft.cdf", profile="ORACLES_PRODUCTION")
        rc, out = self._run(toml, raw)
        self.assertEqual(rc, 2, out)
        self.assertIn("never reads one", out)

    @needs_v314_engine
    def test_missing_file_is_exit_2(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        toml = _toml(root, "234", "nope.cdf")  # never written
        rc, out = self._run(toml, raw)
        self.assertEqual(rc, 2, out)
        self.assertIn("does not exist", out)

    @needs_v314_engine
    def test_two_flights_with_one_file_is_exit_2(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw1 = root / "base160101000000.2DS"
        raw2 = root / "base160102000000.2DS"
        make_demo_flight.build_demo_flight(raw1, n_seconds=3)
        make_demo_flight.build_demo_flight(raw2, n_seconds=3)
        _aircraft(root / "aircraft.cdf")
        toml = _toml(root, "234", "aircraft.cdf")
        rc, out = self._run(toml, raw1, raw2)
        self.assertEqual(rc, 2, out)
        self.assertIn("One flight per run", out)

    @needs_v314_engine
    def test_stages_2_never_asks_for_a_tas_file(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        toml = _toml(root, "2")  # no tas_file, and none is asked for
        rc, out = self._run(toml, raw)
        self.assertEqual(rc, 0, out)


class StampIsUntouchedWhenTheProfileDoesNotReadTheFile(_RunFlightStateIsolated):
    """T4 -- ``config_label``'s suffix is gated on the PROFILE, not merely on
    whether a ``TAS_FILE`` happens to be set, so every ORACLES stamp stays
    byte-identical (pinned by
    ``tests/test_run_from_config.py::ValidatedCallStampsAreByteIdentical``)."""

    def test_config_label_ignores_tas_file_for_oracles_profiles(self):
        run_flight.TAS_FILE = "C:/x/aircraft.cdf"
        self.assertNotIn("tas_file=", run_flight.config_label(ORACLES_PRODUCTION))
        self.assertTrue(
            run_flight.config_label(STOCK_V314).endswith(" tas_file=aircraft.cdf"))


class ChunkWorkerCarriesTheTasFile(_RunFlightStateIsolated):
    """T5 -- both re-exec sites agree: ``stage3``'s ``cmd_base`` builds the
    positional and the ``--_run-chunk`` branch on the other end consumes it."""

    @needs_v314_engine
    def test_cmd_base_carries_the_file_and_run_chunk_consumes_it(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        tas = root / "aircraft.cdf"
        _aircraft(tas, tas=85.0)
        toml = _toml(root, "2")  # decode only; S3 is driven directly below
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["run", str(toml), str(raw), "--yes", "--port-validation"])
        self.assertEqual(rc, 0, buf.getvalue())
        image = root / "_decoded" / "base160101000000.H.cdf"
        self.assertTrue(image.is_file())
        out_dir = root / "_decoded"

        # (a) cmd_base builds the positional -- no subprocess actually runs. Under engine
        # 3.5: since 2026-09-23 v3.1.4 refuses --chunks for a TAS-file profile
        # before spawning, so 3.5 -- which primes each seam -- is where a chunked run still
        # carries TAS_FILE to its workers.
        run_flight.ENGINE = "3.5"
        run_flight.TAS_FILE = str(tas)
        popen_result = mock.Mock(wait=mock.Mock(return_value=1),
                                 poll=mock.Mock(return_value=1))
        with mock.patch.object(run_flight.subprocess, "Popen",
                               return_value=popen_result) as popen:
            with self.assertRaises(RuntimeError):
                run_flight.stage3(image, out_dir, chunks=2)
        cmd = popen.call_args_list[0].args[0]
        self.assertIn(str(tas), cmd)
        self.assertEqual(cmd.index(str(tas)), cmd.index("--_run-chunk") + 6,
                         "TAS_FILE must sit right after PROFILE_MODULE in cmd_base")

        # (b) the --_run-chunk branch on the other end consumes it, for real.
        chunk_out = out_dir / "chunk1.nc"
        rc2 = run_flight.main([
            "--_run-chunk", str(image), run_flight.PROBE, run_flight.PROJECT,
            "stock-v3.1.4", "", str(tas), "0", str(chunk_out), "1", "3",
        ])
        self.assertEqual(rc2, 0)
        self.assertTrue(chunk_out.is_file())
        with netCDF4.Dataset(chunk_out) as ds:
            got = np.asarray(ds.variables["Time_in_seconds"][:], dtype=float).ravel()
        # Measured by the planner against this exact file (planning measurement S1): TAS=85
        # gives Time_in_seconds[0] ~= 35.934322. A tolerant comparison -- what
        # matters here is that the TAS-based value was used at all (the 170 m/s
        # fallback would read ~17.97, easily distinguished).
        self.assertAlmostEqual(float(got[0]), 35.934322, places=3)


class TheOneLineForwardsTasFile(unittest.TestCase):
    """T6 -- ``arrayprobe.cli._run`` builds ``--tas-file`` from ``[run].tas_file``."""

    @needs_v314_engine
    def test_run_passes_tas_file_resolved_against_the_config(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        toml = _toml(root, "234", "aircraft.cdf")  # file need not exist: main() is a spy
        raw = root / "base160101000000.2DS"
        raw.write_bytes(b"")
        with mock.patch.object(run_flight, "main", return_value=0) as spy:
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["run", str(toml), str(raw), "--yes"])
        self.assertEqual(rc, 0)
        spy.assert_called_once()
        (argv,), _ = spy.call_args
        self.assertEqual(argv[argv.index("--tas-file") + 1],
                         str((root / "aircraft.cdf").resolve()))


if __name__ == "__main__":
    unittest.main()
