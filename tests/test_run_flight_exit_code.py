# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py``'s exit code -- the ``regression_admission.py``'s
incident (2026-09-11): the driver reported success (``rc == 0``) for a run
that silently dropped a requested file, in two independent shapes found the
same night: a ``BrokenProcessPool`` swallowed by the batch-tolerant
catch-all, and an ``S4 SKIP`` on a missing prerequisite that nothing above it
noticed. Neither shape had a test before this file; both are regression
tests for the fix, not the original defect.

Also covers the S2 parallel-decode serial fallback that shares the same
incident report: a worker-pool death that spec.py's own retries could not
recover must degrade to the serial decode rather than lose the file, and
that degradation must be recorded somewhere other than a log line (a
separate, non-provenance-compared sidecar) without tripping ``rc``, since a
fallback that produced the file correctly did reach every requested stage.
"""

from __future__ import annotations

import concurrent.futures
import concurrent.futures.process
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_v314_engine  # noqa: E402

_TOOLS = Path(__file__).resolve().parent.parent / "scripts"

_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", _TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules["make_demo_flight"] = make_demo_flight
_DEMO_SPEC.loader.exec_module(make_demo_flight)
_build_raw_flight = make_demo_flight.build_demo_flight

_SPEC = importlib.util.spec_from_file_location("run_flight", _TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)


class MainExitCodeTests(unittest.TestCase):
    """``main()``'s return value, driven end to end through real argv --
    the same entry point an orchestrator's return code actually observes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.raw = self.out / "base160906064000.2DS"
        _build_raw_flight(self.raw)
        self._real_log = run_flight.log
        run_flight.log = lambda *a, **kw: None
        self.addCleanup(setattr, run_flight, "log", self._real_log)

    @needs_v314_engine
    def test_happy_path_is_rc_zero(self):
        rc = run_flight.main(["--stages", "234c", "--engine", "3.1.4", "--port-validation",
                              "--preset", "ORACLES_2016_2DS_H", "--yes",
                              "--out", str(self.out), str(self.raw)])
        self.assertEqual(rc, 0)

    @needs_v314_engine
    def test_missing_raw_file_is_rc_one(self):
        ghost = self.out / "base160906099999.2DS"
        rc = run_flight.main(["--stages", "234c", "--engine", "3.1.4", "--port-validation",
                              "--preset", "ORACLES_2016_2DS_H",
                              "--out", str(self.out), str(ghost)])
        self.assertEqual(rc, 1)

    @needs_v314_engine
    def test_a_silently_missing_s4_prerequisite_is_rc_one(self):
        """The actual incident: S2/S3 ran, then the tas.csv sidecar S4
        needs went missing before S4 ran (a race, an external delete -- the
        mechanism does not matter here), and the run used to still exit 0.
        """
        image = run_flight.stage2(self.raw, self.out)
        run_flight.stage3(image, self.out)
        (self.out / f"{self.raw.stem}.tas.csv").unlink()
        rc = run_flight.main(["--stages", "4", "--engine", "3.1.4", "--port-validation",
                              "--preset", "ORACLES_2016_2DS_H", "--yes",
                              "--out", str(self.out), str(self.raw)])
        self.assertEqual(rc, 1)

    @needs_v314_engine
    def test_an_uncaught_exception_still_sets_rc_one(self):
        """regression_admission.py's incident: a BrokenProcessPool (or any
        other exception) caught by the batch-tolerant catch-all used to
        leave rc at 0 -- "one bad file must not take the other four down"
        was implemented as "and must not be noticed either."
        """
        real_stage3 = run_flight.stage3

        def _boom(*a, **kw):
            raise concurrent.futures.process.BrokenProcessPool("synthetic")
        run_flight.stage3 = _boom
        self.addCleanup(setattr, run_flight, "stage3", real_stage3)
        rc = run_flight.main(["--stages", "234", "--engine", "3.1.4", "--port-validation",
                              "--preset", "ORACLES_2016_2DS_H", "--yes",
                              "--out", str(self.out), str(self.raw)])
        self.assertEqual(rc, 1)

    @needs_v314_engine
    def test_a_requested_attributed_sibling_that_was_not_written_is_rc_one(self):
        """2026-09-21's total outage, in its second half. ``--attributed`` was accepted, the
        exporter raised, ``write_attributed`` logged ``S4c ATTRIBUTED skipped`` and swallowed it
        so a finished flight is never lost to a metadata step -- and the driver then printed
        ``ALL DONE`` and returned **0**, telling anything scripting on exit status that the
        sibling exists. The swallow stays (the faithful product is already written and is
        unaffected); the 0 does not.

        The failure is injected at the exporter, not at ``write_attributed``, so the real
        swallow path runs -- that is the path whose rc this test is about.
        """
        from arrayprobe import attributed_export as ae
        real_export = ae.export

        def _boom(*a, **kw):
            raise ae.StampParseError("synthetic")
        ae.export = _boom
        self.addCleanup(setattr, ae, "export", real_export)
        rc = run_flight.main(["--stages", "234c", "--engine", "3.1.4", "--port-validation",
                              "--preset", "ORACLES_2016_2DS_H", "--yes",
                              "--attributed", "--out", str(self.out), str(self.raw)])
        self.assertEqual(rc, 1)

    @needs_v314_engine
    def test_the_same_run_with_a_working_exporter_is_rc_zero_and_writes_the_sibling(self):
        """The other half of the pair: the new check must fire on the failure and **only** on it.

        It also proves the export works end to end on a product this driver actually wrote --
        which is the case that was broken for every real product until 2026-09-21, because the
        S4c combine stamp nests the whole S4 stamp inside ``inputs_built_with=(...)``.
        """
        rc = run_flight.main(["--stages", "234c", "--engine", "3.1.4", "--port-validation",
                              "--preset", "ORACLES_2016_2DS_H", "--yes",
                              "--attributed", "--out", str(self.out), str(self.raw)])
        self.assertEqual(rc, 0)
        siblings = list(self.out.glob("*.combined.*.attributed.nc"))
        self.assertEqual(len(siblings), 1, f"expected one attributed sibling, got {siblings}")

    @needs_v314_engine
    def test_a_partial_combine_when_this_run_requested_s4_is_rc_one(self):
        """Two raw files named into one flight; the second is a ghost, so its
        S4 never runs and the combine stitches one of two -- the exact shape
        of the 2026-09-10 four-flight regression's dropped file.
        """
        ghost = self.out / f"base{self.raw.stem[4:10]}999999.2DS"
        rc = run_flight.main(
            ["--stages", "234c", "--engine", "3.1.4", "--port-validation",
             "--preset", "ORACLES_2016_2DS_H",
             "--out", str(self.out), str(self.raw), str(ghost)])
        self.assertEqual(rc, 1)


class S2DecodeSidecarTests(unittest.TestCase):
    """The ``.decode`` sidecar and the serial fallback it records -- kept
    separate from ``.call`` on purpose (``.call`` is compared for exact
    equality to decide staleness; decode mode is a performance fact, not a
    fidelity one, and putting it there would make a byte-identical parallel
    and serial-fallback decode of the same file compare unequal)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.raw = self.out / "base160906064000.2DS"
        _build_raw_flight(self.raw)
        self._real_log = run_flight.log
        run_flight.log = lambda *a, **kw: None
        self.addCleanup(setattr, run_flight, "log", self._real_log)

    @needs_v314_engine
    def test_serial_decode_records_mode_serial(self):
        image = run_flight.stage2(self.raw, self.out)
        decode = Path(str(image) + ".decode")
        self.assertTrue(decode.exists())
        self.assertIn("mode=serial", decode.read_text())

    @needs_v314_engine
    def test_a_worker_pool_death_falls_back_and_main_still_exits_zero(self):
        real_parallel = run_flight.spec.read_binary_SPEC_parallel

        def _dies(*a, **kw):
            raise concurrent.futures.process.BrokenProcessPool("synthetic")
        run_flight.spec.read_binary_SPEC_parallel = _dies
        self.addCleanup(setattr, run_flight.spec, "read_binary_SPEC_parallel", real_parallel)

        rc = run_flight.main(
            ["--stages", "234c", "--s2-jobs", "4", "--engine", "3.1.4", "--port-validation",
             "--preset", "ORACLES_2016_2DS_H", "--yes",
             "--out", str(self.out), str(self.raw)])
        self.assertEqual(
            rc, 0,
            "a fallback that produced the file correctly reached every "
            "requested stage -- degradation belongs in the record, not the "
            "exit code")
        decode = self.out / f"{self.raw.stem}.H.cdf.decode"
        self.assertIn("serial_fallback", decode.read_text())
        # The .call sidecar (compared for staleness) must be untouched by the
        # decode mode -- a byte-identical parallel and fallback decode must
        # keep comparing equal on resume.
        call_text = (self.out / f"{self.raw.stem}.H.cdf.call").read_text()
        self.assertNotIn("serial_fallback", call_text)
        self.assertNotIn("decode", call_text)

    @needs_v314_engine
    def test_the_parallel_decode_is_asked_to_report_every_20000_windows(self):
        """Pair J (2026-09-13): the per-part liveness lines exist only if stage2
        asks for them, at the interval its serial branch already logs at."""
        seen: dict = {}
        real_parallel = run_flight.spec.read_binary_SPEC_parallel

        def _records_then_dies(*a, **kw):
            seen.update(kw)
            raise concurrent.futures.process.BrokenProcessPool("synthetic")
        run_flight.spec.read_binary_SPEC_parallel = _records_then_dies
        self.addCleanup(setattr, run_flight.spec, "read_binary_SPEC_parallel", real_parallel)

        run_flight.stage2(self.raw, self.out, s2_jobs=4)  # falls back to serial, completes
        self.assertEqual(seen.get("report_every"), 20000)


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
