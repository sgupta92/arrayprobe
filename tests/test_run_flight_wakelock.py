# SPDX-License-Identifier: BSD-3-Clause
"""A long run must not lose wall-clock to the machine suspending.

**Measured, not assumed.** Differencing consecutive progress timestamps in every
campaign run log on 2026-09-01 -- a gap far larger than that log's median gap,
followed by the process resuming at its previous rate, is a suspend rather than
slow work -- gives **39.8 hours** lost across the campaign: 15.6 h in flight
09/20, 13.1 h in 09/25's first file, 6.4 h in 09/12, 4.6 h in 09/14. No work was
lost; days were.

The project's standing guidance was "do not negotiate that the machine will be
awake", which is an instruction addressed to attention. This is the control:
``run_flight.py`` holds a system wake lock for the duration of a run.

**What these tests can and cannot establish.** They check that the context
manager is correctly shaped -- that it always restores state, that it is a no-op
when disabled, that it never raises on a platform without the API. They cannot
check that Windows actually stayed awake; that is an assertion about the OS, and
the honest evidence for it will be the absence of a suspend gap in the next
campaign log. Stated here so a reader does not mistake a green suite for proof
that the machine stayed up.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from tests._driver import driver_source

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "run_flight_wl", ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
# Registered in sys.modules before exec: with `from __future__ import annotations`,
# dataclasses resolves a string annotation by looking the defining module up in
# sys.modules, and gets None if it was never put there. Added 2026-09-08, when
# run_flight gained a dataclass and every loader written this way broke at import.
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)
class TheWakeLockIsWellBehaved(unittest.TestCase):
    def test_disabled_is_a_no_op_and_reports_it(self):
        with run_flight.keep_awake(enabled=False) as taken:
            self.assertFalse(taken, "a disabled lock must report that it took nothing")

    def test_it_yields_and_restores_without_raising(self):
        """The finally-clause must run even when the body raises, or a crashed
        run would leave the machine unable to sleep until reboot."""
        class Boom(RuntimeError):
            pass

        with self.assertRaises(Boom):
            with run_flight.keep_awake():
                raise Boom
        # Reaching here at all is the assertion: __exit__ ran and did not mask
        # the exception, and did not raise one of its own on the way out.

    def test_it_reports_truthfully_on_this_platform(self):
        """`taken` must describe what happened, not what was wanted -- a run
        that silently failed to take the lock looks exactly like one that
        succeeded, until the next 13-hour gap."""
        with run_flight.keep_awake() as taken:
            if sys.platform != "win32":
                self.assertFalse(
                    taken, "only Windows has SetThreadExecutionState; a non-Windows "
                           "run must report that it did not inhibit sleep")
            else:
                self.assertIsInstance(taken, bool)

    def test_the_flags_are_the_documented_ones(self):
        """ES_CONTINUOUS makes the request persist rather than resetting one
        timer; ES_SYSTEM_REQUIRED asks the system not to sleep. Display sleep is
        deliberately not requested -- a batch run does not need the screen."""
        self.assertEqual(run_flight._ES_CONTINUOUS, 0x80000000)
        self.assertEqual(run_flight._ES_SYSTEM_REQUIRED, 0x00000001)
        self.assertFalse(
            hasattr(run_flight, "_ES_DISPLAY_REQUIRED"),
            "display-sleep inhibition was deliberately not requested; adding it "
            "is a behaviour change that should be a decision, not a drift")

    def test_the_runner_wraps_its_entry_point(self):
        """The lock must wrap the entry point, not main(), so importing this
        module in a test never touches the OS power state."""
        source = driver_source("run_flight.py").read_text(encoding="utf-8")
        self.assertIn("_run_with_wakelock(main)", source)
        self.assertIn("def _run_with_wakelock", source)


if __name__ == "__main__":
    unittest.main()
