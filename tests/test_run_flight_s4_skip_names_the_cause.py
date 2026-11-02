# SPDX-License-Identifier: BSD-3-Clause
"""S4's missing-TAS skip does not blame S2 for not running when S2 just ran.

Found 2026-09-26 by a cold-user walk: a one-second demo flight decodes one image record and
writes no ``<stem>.tas.csv``. The log read ``S2 done ... 1 H / 0 V records`` and then ``S4 SKIP
... no <stem>.tas.csv (S2 must run first)`` -- sending the user back to re-run a stage that had
run. The skip now says the decode is there and wrote no airspeed record.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import _run_flight_state  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
sys.modules.setdefault(_SPEC.name, importlib.util.module_from_spec(_SPEC))
run_flight = sys.modules[_SPEC.name]
if not hasattr(run_flight, "main"):
    _SPEC.loader.exec_module(run_flight)

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe.tools.make_demo_flight import build_demo_flight  # noqa: E402


class TheSkipNamesTheCause(unittest.TestCase):

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.lines: list[str] = []
        real_log = run_flight.log
        run_flight.log = lambda msg, *a, **k: self.lines.append(str(msg))
        self.addCleanup(setattr, run_flight, "log", real_log)

    @needs_v314_engine
    def test_a_decode_with_no_tas_csv_is_not_told_to_run_s2(self):
        raw = build_demo_flight(self.root / "base160101000000.2DS", n_seconds=1)
        with redirect_stdout(io.StringIO()):
            rc = run_flight.main(["--preset", "DEMO_2DS_H", "--engine", "3.1.4",
                                  "--port-validation", "--yes",
                                  "--stages", "234", "--out", str(self.root / "out"), str(raw)])
        skips = [m for m in self.lines if m.startswith("S4 SKIP")]
        self.assertEqual(rc, 1)
        self.assertEqual(len(skips), 1, self.lines[-10:])
        self.assertNotIn("S2 must run first", skips[0])
        self.assertIn("wrote no base160101000000.tas.csv", skips[0])

    def test_with_no_decode_at_all_it_still_says_run_s2(self):
        out = self.root / "out"
        out.mkdir()
        proc = out / "proc.base160101000000.H.nc"
        run_flight.stage4(proc, "base160101000000", out)
        self.assertTrue(any("S2 must run first" in m for m in self.lines), self.lines)


if __name__ == "__main__":
    unittest.main()
