# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.timing_closure`` -- the McFarquhar et al. (2017) p. 11.20 closure check.

Synthetic cases pin the arithmetic (agreement, disagreement, midnight rollover, the
too-few-records/particles refusals); a real-data case runs it against an actual ORACLES
decoded/proc pair and reports the result without asserting a verdict -- there is no
published tolerance to assert against, and the measured numbers on real data are
recorded here as a fact about this file, not a pass/fail.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

import numpy as np

from arrayprobe import ncio
from arrayprobe.timing_closure import check_closure


def _write_decoded_fixture(path, hour, minute, second, millisec):
    n = len(hour)
    f = ncio.create(str(path), "clobber")
    t_dim = ncio.def_dim(f, "time", n)
    varids = {}
    for name, _values in (("hour", hour), ("minute", minute),
                         ("second", second), ("millisec", millisec)):
        varids[name] = ncio.def_var(f, name, "double", [t_dim])
    ncio.end_def(f)
    for name, values in (("hour", hour), ("minute", minute),
                         ("second", second), ("millisec", millisec)):
        ncio.put_var(f, varids[name], np.asarray(values, dtype=np.float64))
    ncio.close(f)


def _write_proc_fixture(path, time_in_seconds):
    n = len(time_in_seconds)
    f = ncio.create(str(path), "clobber")
    t_dim = ncio.def_dim(f, "time", n)
    varid = ncio.def_var(f, "Time_in_seconds", "double", [t_dim])
    ncio.end_def(f)
    ncio.put_var(f, varid, np.asarray(time_in_seconds, dtype=np.float64))
    ncio.close(f)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class SyntheticClosure(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.decoded = Path(self._tmp.name) / "decoded.cdf"
        self.proc = Path(self._tmp.name) / "proc.nc"

    def tearDown(self):
        self._tmp.cleanup()

    def test_exact_agreement(self):
        # Records span exactly 100 s (10:00:00.000 to 10:01:40.000); particle
        # clock spans the same 100 s.
        _write_decoded_fixture(self.decoded, [10, 10], [0, 1], [0, 40], [0, 0])
        _write_proc_fixture(self.proc, [5.0, 105.0])
        result = check_closure(self.decoded, self.proc)
        self.assertAlmostEqual(result.record_clock_span_s, 100.0)
        self.assertAlmostEqual(result.particle_clock_span_s, 100.0)
        self.assertAlmostEqual(result.difference_s, 0.0)
        self.assertAlmostEqual(result.ratio, 1.0)
        self.assertEqual(result.n_records, 2)
        self.assertEqual(result.n_particles, 2)

    def test_disagreement_is_reported_not_hidden(self):
        # Record span 100 s; particle clock only covers 50 s -- e.g. a TAS
        # assumption twice the real airspeed.
        _write_decoded_fixture(self.decoded, [10, 10], [0, 1], [0, 40], [0, 0])
        _write_proc_fixture(self.proc, [0.0, 50.0])
        result = check_closure(self.decoded, self.proc)
        self.assertAlmostEqual(result.difference_s, -50.0)
        self.assertAlmostEqual(result.ratio, 0.5)

    def test_midnight_rollover_corrected_once(self):
        # First record 23:59:50, last record 00:00:10 the same flight --
        # a 20 s span across midnight.
        _write_decoded_fixture(self.decoded, [23, 0], [59, 0], [50, 10], [0, 0])
        _write_proc_fixture(self.proc, [0.0, 20.0])
        result = check_closure(self.decoded, self.proc)
        self.assertAlmostEqual(result.record_clock_span_s, 20.0)
        self.assertAlmostEqual(result.ratio, 1.0)

    def test_an_insufficient_rollover_correction_refuses_rather_than_guesses(self):
        # A real HH:MM:SS.mmm pair can never be more than 24h apart, so the
        # default day_rollover_h always suffices -- this proves the *mechanism*
        # (a caller-supplied correction too small to fix a real rollover is not
        # silently accepted) using a deliberately undersized correction rather
        # than an unreachable "more than a day" input.
        _write_decoded_fixture(self.decoded, [23, 0], [59, 0], [50, 10], [0, 0])
        _write_proc_fixture(self.proc, [0.0, 20.0])
        with self.assertRaises(ValueError):
            check_closure(self.decoded, self.proc, day_rollover_h=0.001)

    def test_refuses_a_single_record_decoded_file(self):
        _write_decoded_fixture(self.decoded, [10], [0], [0], [0])
        _write_proc_fixture(self.proc, [0.0, 20.0])
        with self.assertRaises(ValueError):
            check_closure(self.decoded, self.proc)

    def test_refuses_a_single_particle_proc_file(self):
        _write_decoded_fixture(self.decoded, [10, 10], [0, 1], [0, 40], [0, 0])
        _write_proc_fixture(self.proc, [5.0])
        with self.assertRaises(ValueError):
            check_closure(self.decoded, self.proc)

    def test_zero_record_span_gives_nan_ratio_not_a_crash(self):
        _write_decoded_fixture(self.decoded, [10, 10], [0, 0], [0, 0], [0, 0])
        _write_proc_fixture(self.proc, [0.0, 5.0])
        result = check_closure(self.decoded, self.proc)
        self.assertEqual(result.record_clock_span_s, 0.0)
        self.assertTrue(np.isnan(result.ratio))


class RealDataClosure(unittest.TestCase):
    """A genuine ORACLES decoded/proc pair, if one is present locally (gitignored
    reference data -- this project's convention, see ``ARRAYPROBE_REFERENCE_DATA``
    and ``tests/test_run_flight.py`` for the same skip-if-absent pattern).

    **This test asserts nothing about the measured ratio.** No published tolerance
    exists (see the module docstring), and this project's own doctrine is to report
    a real measurement rather than hide or explain away one that looks surprising.
    On the one pair checked while building this module (``base160906064343``, V
    channel), the particle-clock span (~3513 s) was roughly 1/8th of the
    record-clock span (~28423 s) -- a large, real, unexplained divergence, recorded
    here as a measurement rather than diagnosed, exactly like the HVPS over-count in
    ``docs/10-known-gaps.md``: a question for further investigation, not
    a defect claim by this test.
    """

    def test_runs_against_a_real_pair_and_reports_the_numbers(self):
        root = Path(__file__).resolve().parents[1] / "_decoded"
        decoded = root / "base160906064343.V.cdf"
        proc = root / "proc.base160906064343.V.nc"
        if not (decoded.is_file() and proc.is_file()):
            self.skipTest("no local decoded/proc pair for base160906064343 V channel")
        result = check_closure(decoded, proc)
        self.assertGreater(result.n_records, 0)
        self.assertGreater(result.n_particles, 0)
        self.assertGreater(result.record_clock_span_s, 0.0)
        # Reported, not asserted: this is the honest range observed while this
        # module was built, kept loose enough to survive re-runs on the same
        # file without becoming a brittle pin on an unexplained number.
        print(f"\n[timing_closure real-data check] base160906064343 V: "
              f"particle_span={result.particle_clock_span_s:.1f}s "
              f"record_span={result.record_clock_span_s:.1f}s "
              f"ratio={result.ratio:.4f}")


_TOOL = Path(__file__).resolve().parent.parent / "scripts" / "check_timing_closure.py"
check_timing_closure_tool = None
if _TOOL.is_file():  # the script is a repository tool; the public tree does not carry it
    _SPEC = importlib.util.spec_from_file_location("check_timing_closure_tool", _TOOL)
    assert _SPEC is not None and _SPEC.loader is not None
    check_timing_closure_tool = importlib.util.module_from_spec(_SPEC)
    sys.modules[_SPEC.name] = check_timing_closure_tool
    _SPEC.loader.exec_module(check_timing_closure_tool)


@unittest.skipIf(check_timing_closure_tool is None, "the timing-closure tool is not shipped")
@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class ToolWrapper(unittest.TestCase):
    """The CLI a person runs -- a thin wrapper, per compare_nc.py's own convention
    of holding no logic the module does not already have (and already tests)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.decoded = Path(self._tmp.name) / "decoded.cdf"
        self.proc = Path(self._tmp.name) / "proc.nc"
        _write_decoded_fixture(self.decoded, [10, 10], [0, 1], [0, 40], [0, 0])
        _write_proc_fixture(self.proc, [5.0, 105.0])

    def tearDown(self):
        self._tmp.cleanup()

    def test_reports_and_exits_zero_on_agreement(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = check_timing_closure_tool.main([str(self.decoded), str(self.proc)])
        self.assertEqual(rc, 0)
        self.assertIn("ratio (particle/record) : 1.0000", out.getvalue())
        self.assertIn("No published tolerance", out.getvalue())

    def test_missing_file_is_a_usage_error(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = check_timing_closure_tool.main(["nope.cdf", str(self.proc)])
        self.assertEqual(rc, 1)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class ReachableFromTheFrontDoor(unittest.TestCase):
    """``arrayprobe validate timing-closure`` -- added 2026-09-10.

    The check existed and was tested, but only as a standalone script,
    which a new user has no reason to find: nothing in ``arrayprobe --help`` mentioned
    it. The literature asks for this check (McFarquhar et al. 2017 p. 11.20) and the
    plan's row 6 asks for it *as an* ``arrayprobe validate`` *check* specifically, which
    is a discoverability requirement, not an implementation one.

    So these assertions are about the front door, not the arithmetic -- the arithmetic
    is pinned above and the CLI adds none of its own. What must hold is that the
    subcommand exists, produces the same numbers as the module, and **still refuses to
    verdict**: the "no published tolerance" sentence is load-bearing, because a check
    that shipped a threshold would have that threshold cited back at it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.decoded = Path(self._tmp.name) / "decoded.cdf"
        self.proc = Path(self._tmp.name) / "proc.nc"
        _write_decoded_fixture(self.decoded, [10, 10], [0, 1], [0, 40], [0, 0])
        _write_proc_fixture(self.proc, [5.0, 105.0])

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_subcommand_is_registered(self):
        from arrayprobe.cli import build_parser
        text = build_parser().format_help()
        self.assertIn("validate", text)

    def test_it_reports_the_same_numbers_as_the_module(self):
        from arrayprobe import cli
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["validate", "timing-closure",
                           str(self.decoded), str(self.proc)])
        self.assertEqual(rc, 0)
        printed = out.getvalue()
        expected = check_closure(self.decoded, self.proc)
        self.assertIn(f"ratio (particle/record) : {expected.ratio:.4f}", printed)
        self.assertIn(f"difference          : {expected.difference_s:+.3f} s", printed)

    def test_it_still_refuses_to_verdict(self):
        from arrayprobe import cli
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["validate", "timing-closure",
                           str(self.decoded), str(self.proc)])
        self.assertEqual(rc, 0)
        self.assertIn("No published tolerance", out.getvalue())

    def test_a_missing_file_is_a_usage_error_here_too(self):
        from arrayprobe import cli
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["validate", "timing-closure", "nope.cdf", str(self.proc)])
        self.assertEqual(rc, 1)

    def test_disagreement_survives_the_wrapper(self):
        """The wrapper must not smooth a disagreement into agreement.

        Without this the three tests above pass on a CLI that prints a constant.
        """
        from arrayprobe import cli
        skewed = Path(self._tmp.name) / "skewed.nc"
        _write_proc_fixture(skewed, [5.0, 55.0])
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["validate", "timing-closure",
                           str(self.decoded), str(skewed)])
        self.assertEqual(rc, 0)
        self.assertNotIn("ratio (particle/record) : 1.0000", out.getvalue())


if __name__ == "__main__":
    unittest.main()
