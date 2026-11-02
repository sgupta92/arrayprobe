# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 tests for outoffocus.py, the Korolev out-of-focus size correction.

Imports nothing from ``arrayprobe.reject`` or ``arrayprobe.sizedist`` (the v3.1.4 engine), so it
runs in a distribution that omits that engine. The v3.1.4 cases are in ``test_outoffocus.py``.
The named oracle for the on state is the v3.5 engine's own stored ``part_z``/``size_factor``.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

from arrayprobe_enhancements.outoffocus import (
    apply_outoffocus,
    correct_diameter,
    hollow_diagnostics,
)

_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PORT = _ROOT  # the pre-move port directory is the repository root
_DENSE_RAW = _PYTHON_PORT / "tests" / "data" / "demo_flight_dense_raw.2DS"

#: Run before the code under test in a subprocess: makes the v3.1.4 engine's reject and
#: sizedist modules unimportable, as in a distribution that omits them.
_BLOCKER = """
import importlib.abc, sys
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name in ("arrayprobe.reject", "arrayprobe.sizedist"):
            raise ModuleNotFoundError(f"No module named {name!r} (blocked)", name=name)
        return None
sys.meta_path.insert(0, _Block())
"""


def _run_blocked(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _BLOCKER + code], capture_output=True,
                          text=True, timeout=600)


class ImportsWithoutTheV314Engine(unittest.TestCase):
    def test_module_imports_without_v314_reject(self):
        r = _run_blocked(textwrap.dedent("""
            import arrayprobe_enhancements.outoffocus
            import arrayprobe_enhancements.pipeline
            """))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_registry_resolves_both_shipped_names_without_v314(self):
        # Release wiring (outoffocus and spot_edge_fix ship): the registry's own lookup reaches
        # both modules with the v3.1.4 reject/sizedist unimportable. A name registered without
        # an entry_point raises LookupError, which is not an ImportError and still proves the
        # name resolves; the module itself is imported directly in that case.
        r = _run_blocked(textwrap.dedent("""
            import importlib
            from arrayprobe_enhancements import registry
            for name in ("outoffocus", "spot_edge_fix"):
                assert name in registry.REGISTRY, name
                try:
                    registry.entry_point(name)
                except ImportError:
                    raise
                except LookupError:
                    importlib.import_module("arrayprobe_enhancements." + name)
                print("OK:" + name)
            """))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("OK:outoffocus", r.stdout)
        self.assertIn("OK:spot_edge_fix", r.stdout)

    def test_engine_314_without_engine_names_v35(self):
        r = _run_blocked(textwrap.dedent("""
            import numpy as np
            from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG
            from arrayprobe_enhancements import outoffocus
            class P:
                variables = {'holroyd_habit': np.zeros(1, int)}
            try:
                outoffocus.hollow_diagnostics(None, P(), [0], config=STOCK_V35_REJECT_CONFIG,
                                              engine='3.1.4')
            except ImportError as e:
                print('MSG:' + str(e))
            else:
                print('NO-ERROR')
            """))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MSG:", r.stdout)
        self.assertIn("engine='3.5'", r.stdout)
        self.assertNotIn("--engine 3.5", r.stdout)


def _load_run_flight():
    """The flight driver (``arrayprobe.driver.run_flight``; ``scripts/run_flight.py`` is its shim) by path -- registered under a private
    name, never ``sys.modules["run_flight"]``, the same isolation
    ``test_demo_flight_thresholds.py`` and ``make_demo_reference.py`` use."""
    spec = importlib.util.spec_from_file_location(
        "_test_outoffocus_run_flight",
        _PYTHON_PORT / "src" / "arrayprobe" / "driver" / "run_flight.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_test_outoffocus_run_flight"] = module
    spec.loader.exec_module(module)
    return module


def _write_aircraft_cdf(path, *, start_hms=(6, 6, 20), n=50, tas_mps=130.0):
    """A NETCDF3_CLASSIC ``Time``/``TAS`` series bracketing the dense demo flight's
    six-minute-six window (``make_demo_flight.build_dense_demo_flight``'s default
    ``start_hour=6, start_minute=6, start_second=40``, ``n_seconds=20`` -> raw HHMMSS
    060640..060659), built with real HH:MM:SS rollover arithmetic (not raw integer
    addition -- ``060658 + 5`` is not ``060663``) so every value stays a valid HHMMSS,
    same shape as ``make_demo_reference.write_aircraft_v35``."""
    h0, m0, s0 = start_hms
    total0 = h0 * 3600 + m0 * 60 + s0
    hhmmss = []
    for i in range(n):
        total = total0 + i
        hh, rem = divmod(total, 3600)
        mm, ss = divmod(rem, 60)
        hhmmss.append(hh * 10000 + mm * 100 + ss)
    hhmmss = np.asarray(hhmmss, dtype=np.float64)
    tas = np.full(n, tas_mps, dtype=np.float64)
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", n)
        ds.createVariable("Time", "f8", ("time",))[:] = hhmmss
        ds.createVariable("TAS", "f8", ("time",))[:] = tas
    return path




class V35DenseFlightOracle(unittest.TestCase):
    """Fact 0.2 in the S4 plan: the tracked v3.5 demo proc has 5 particles and none in
    the Korolev branch (``part_z > 0`` count 0), so an equivalence proof against it is
    vacuous. This decodes the tracked *dense* raw with the v3.5 engine in-test (via
    ``scripts/run_flight.py``'s own S2/S3 dispatch, ``ENGINE="3.5"``/``PROFILE=STOCK_V35``
    -- the same call the real pipeline makes, not a hand-rolled one) and checks that
    ``hollow_diagnostics(engine="3.5")`` reproduces every particle's stored
    ``part_z``/``size_factor``/``image_hollow`` exactly."""

    @classmethod
    def setUpClass(cls):
        from arrayprobe.profiles import STOCK_V35

        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name)
        cls.run_flight = _load_run_flight()
        rf = cls.run_flight
        cls._real_log = rf.log
        rf.log = lambda *a, **kw: None
        cls._saved = (rf.ENGINE, rf.PROFILE, rf.TAS_FILE)
        aircraft = _write_aircraft_cdf(out / "dense_aircraft.cdf")
        rf.ENGINE = "3.5"
        rf.PROFILE = STOCK_V35
        rf.TAS_FILE = str(aircraft)
        cls.image = rf.stage2(_DENSE_RAW, out)
        cls.proc = rf.stage3(cls.image, out)
        # The same S3 once more with v3.5's Korolev line neutralised: the reject result's
        # size_factor forced to 1.0, so measure.py:241's `minR / rj.size_factor` leaves minR
        # as measured.  Nothing else in measure_record reads size_factor, so this proc's
        # image_diam_minR is v3.5's *uncorrected* diameter for every particle -- the input
        # the equivalence test divides.
        import arrayprobe_uiops.measure as v35_measure
        real = v35_measure.calculate_reject_unified

        def unit_sf(*a, **kw):
            return dataclasses.replace(real(*a, **kw), size_factor=1.0)

        raw_dir = out / "uncorrected"
        raw_dir.mkdir()
        with mock.patch.object(v35_measure, "calculate_reject_unified", unit_sf):
            cls.proc_uncorrected = rf.stage3(cls.image, raw_dir)

    @classmethod
    def tearDownClass(cls):
        rf = cls.run_flight
        rf.ENGINE, rf.PROFILE, rf.TAS_FILE = cls._saved
        rf.log = cls._real_log
        cls._tmp.cleanup()

    def test_recomputed_diagnostics_equal_the_stored_columns_for_every_particle(self):
        from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG

        with netCDF4.Dataset(self.image) as img, netCDF4.Dataset(self.proc) as proc:
            n = proc.variables["image_diam_minR"].shape[0]
            self.assertGreater(n, 0, "the dense flight decoded no particles")
            part_z_stored = np.asarray(proc.variables["part_z"][:], float)
            sf_stored = np.asarray(proc.variables["size_factor"][:], float)
            hollow_stored = np.asarray(proc.variables["image_hollow"][:]).astype(int)
            idx = np.arange(n)
            part_z, sf, hollow = hollow_diagnostics(
                img, proc, idx, config=STOCK_V35_REJECT_CONFIG, engine="3.5")
        np.testing.assert_array_equal(part_z, part_z_stored)
        np.testing.assert_array_equal(sf, sf_stored)
        np.testing.assert_array_equal(hollow, hollow_stored)
        korolev = int((part_z_stored > 0).sum())
        # Report only -- not asserted greater than zero: if the dense demo also turns
        # out vacuous for this branch, that is a fact to report, not to fabricate past.
        print(f"\nV35DenseFlightOracle: {n} particles, {korolev} in the Korolev branch "
              f"(part_z > 0)", file=sys.stderr)

    def _columns(self):
        with netCDF4.Dataset(self.proc) as p, netCDF4.Dataset(self.proc_uncorrected) as u:
            return (np.asarray(p.variables["image_diam_minR"][:], float),
                    np.asarray(u.variables["image_diam_minR"][:], float),
                    np.asarray(p.variables["size_factor"][:], float),
                    np.asarray(p.variables["image_auto_reject"][:]).astype(int))

    def test_korolev_direction_equals_what_v35_itself_writes(self):
        """The equivalence proof (K2 plan E3): v3.5 already applies the correction
        (imgProc_sm.m:1274-1276, measure.py:240-241).  On every particle v3.5 corrected
        (reject status 'H'), ``correct_diameter(direction="korolev")`` of the uncorrected
        diameter equals v3.5's stored one exactly; the dead line does not."""
        corrected, uncorrected, sf, reject = self._columns()
        hit = np.flatnonzero((reject == ord("H")) & (sf != 1.0))
        self.assertGreater(hit.size, 0, "no v3.5-corrected particle -- the proof would be vacuous")
        np.testing.assert_array_equal(
            correct_diameter(uncorrected[hit], sf[hit], direction="korolev"), corrected[hit])
        dead = correct_diameter(uncorrected[hit], sf[hit], direction="dead_line_v314")
        self.assertTrue((dead > corrected[hit]).all())
        rest = np.setdiff1d(np.arange(corrected.size), hit)
        np.testing.assert_array_equal(corrected[rest], uncorrected[rest])
        print(f"\nV35 equivalence: {hit.size} v3.5-corrected particles, korolev == v3.5",
              file=sys.stderr)

    def test_a_v35_proc_is_not_corrected_twice(self):
        from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG

        corrected, _, sf, reject = self._columns()
        with netCDF4.Dataset(self.image) as img, netCDF4.Dataset(self.proc) as proc:
            res = apply_outoffocus(img, proc, config=STOCK_V35_REJECT_CONFIG, engine="3.5")
        self.assertEqual((res.direction, res.area_mode), ("korolev", "sphere"))
        done = reject == ord("H")
        np.testing.assert_array_equal(res.corrected_diam[done], corrected[done])


if __name__ == "__main__":
    unittest.main()
