# SPDX-License-Identifier: BSD-3-Clause
"""``soda2 run`` says where it has got to, and saying so changes no number.

THE INCIDENT, 2026-09-17. ``soda2_process_2d`` printed **nothing** for its whole
duration. On ACE-ENA RF18 -- dense cloud, per-particle output 287 MB against
07-07's 12.8 MB -- the SPEC pass ran **11.5 hours** in silence. From outside, a
healthy long run and a wedged one were identical: no output, CPU climbing, a log
whose last line was an unrelated numerical warning. The coordinator read it as
pathological and killed it. It was neither -- it had finished its per-particle
stage and was in accumulation. Roughly 24 CPU-hours went for a misreading that
one printed line per 20,000 buffers would have prevented.

WHAT THIS GUARDS. Two things, and the second matters more than the first:

1. The heartbeat exists, is **off by default** (so a library caller's output is
   unchanged), and names progress when asked for.
2. **It changes no computed number.** A progress line that perturbed the result
   would be a fidelity defect in a bug-for-bug port, however useful it was. The
   test runs the real driver over the tracked CIP fixture twice -- silent and
   reporting -- and compares every field of both results.

This follows the decode path's convention (``readers/spec.py``'s
``_report_part_progress``, pair J 2026-09-13), which solved exactly this for a
multi-GB decode whose parts were ~2 h silent.
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from arrayprobe_soda2.process_2d import (  # noqa: E402
    REPORT_EVERY_BUFFERS,
    soda2_process_2d,
)
from test_soda2_cip_driver import _cip_op  # noqa: E402
from test_soda2_process_2d import _P2D_FLOAT_FIELDS, _P2D_INT_FIELDS  # noqa: E402

PROGRESS_LOGGER = "arrayprobe_soda2.process_2d.progress"


class _Capture(logging.Handler):
    """Collects the progress logger's records without configuring anything global."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


class TheHeartbeatIsOffUnlessAskedFor(unittest.TestCase):
    def test_the_default_is_silent(self) -> None:
        """A library caller's output must not change because this was added."""
        import inspect
        default = inspect.signature(soda2_process_2d).parameters["report_every"].default
        self.assertEqual(0, default)

    def test_a_silent_run_logs_nothing(self) -> None:
        cap = _Capture()
        log = logging.getLogger(PROGRESS_LOGGER)
        log.addHandler(cap)
        try:
            soda2_process_2d(_cip_op([33000]))
        finally:
            log.removeHandler(cap)
        self.assertEqual([], cap.lines)

    def test_asking_for_it_produces_lines_that_name_progress(self) -> None:
        cap = _Capture()
        log = logging.getLogger(PROGRESS_LOGGER)
        log.addHandler(cap)
        old = log.level
        log.setLevel(logging.INFO)
        try:
            soda2_process_2d(_cip_op([33000]), report_every=1)
        finally:
            log.setLevel(old)
            log.removeHandler(cap)
        self.assertTrue(cap.lines, "report_every=1 produced no progress line")
        first = cap.lines[0]
        for token in ("buffer", "%", "elapsed", "ETA"):
            with self.subTest(token=token):
                self.assertIn(token, first)

    def test_the_interval_constant_is_sane(self) -> None:
        """Small enough to be useful on a long run, large enough not to spam."""
        self.assertGreaterEqual(REPORT_EVERY_BUFFERS, 1_000)
        self.assertLessEqual(REPORT_EVERY_BUFFERS, 100_000)


class ReportingChangesNoNumber(unittest.TestCase):
    """The fidelity half. Same fixture, same op, two settings, one result."""
    noisy: Any  # assigned in setUpClass/setUp; see there for the value
    silent: Any  # assigned in setUpClass/setUp; see there for the value

    @classmethod
    def setUpClass(cls) -> None:
        cls.silent = soda2_process_2d(_cip_op([33000]))
        cls.noisy = soda2_process_2d(_cip_op([33000]), report_every=1)

    def test_both_runs_returned_data(self) -> None:
        self.assertIsNotNone(self.silent)
        self.assertIsNotNone(self.noisy)

    def test_every_float_field_is_identical(self) -> None:
        for name in sorted(set(_P2D_FLOAT_FIELDS.values())):
            with self.subTest(field=name):
                a = np.asarray(getattr(self.silent, name))
                b = np.asarray(getattr(self.noisy, name))
                self.assertEqual(a.shape, b.shape)
                # Bit-for-bit, NaNs included: a heartbeat may not move a value
                # even in the last place.
                self.assertTrue(np.array_equal(a, b, equal_nan=True),
                                f"{name} differs between a silent and a reporting run")

    def test_every_integer_field_is_identical(self) -> None:
        for name in sorted(set(_P2D_INT_FIELDS.values())):
            with self.subTest(field=name):
                a = np.asarray(getattr(self.silent, name))
                b = np.asarray(getattr(self.noisy, name))
                self.assertTrue(np.array_equal(a, b),
                                f"{name} differs between a silent and a reporting run")

    def test_the_field_lists_are_not_empty(self) -> None:
        """Otherwise the two tests above would pass by checking nothing --
        the silent-guard failure this project keeps finding."""
        self.assertTrue(_P2D_FLOAT_FIELDS)
        self.assertTrue(_P2D_INT_FIELDS)


if __name__ == "__main__":
    unittest.main()
