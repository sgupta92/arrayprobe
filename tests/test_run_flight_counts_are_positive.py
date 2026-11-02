# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py``'s ``--jobs``, ``--chunks`` and ``--s2-jobs`` refuse a count below 1.

Error catalogue, 2026-09-29:
``--jobs 0`` ran serially and exited 0, because every consumer tests ``> 1``. A count below 1 is
now an argparse error, exit 2, one line.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_flight  # noqa: E402


class CountsBelowOneAreRefused(unittest.TestCase):
    def _exit(self, *flags: str) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            run_flight.main(["raw.2DS", "--preset", "DEMO_2DS_H", "--engine", "3.5",
                             *flags])
        return cm.exception.code, err.getvalue()

    def test_zero_and_negative_counts_exit_two_naming_the_flag(self):
        for flag in ("--jobs", "--chunks", "--s2-jobs", "--enh-jobs"):
            for value in ("0", "-3"):
                with self.subTest(flag=flag, value=value):
                    code, err = self._exit(flag, value)
                    self.assertEqual(code, 2)
                    self.assertIn(flag, err)
                    self.assertIn("less than 1", err)
                    self.assertNotIn("Traceback", err)

    def test_the_type_accepts_one_and_more(self):
        self.assertEqual(run_flight._at_least_one("1"), 1)
        self.assertEqual(run_flight._at_least_one("8"), 8)


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
