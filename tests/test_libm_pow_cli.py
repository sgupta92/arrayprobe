# SPDX-License-Identifier: BSD-3-Clause
"""B9 (2026-09-29): ``run_flight.py --libm-pow`` routes engine 3.1.4's S4 ``massBL``
power through libm, is stamped into the sd ``.call`` only when on, and is refused on engine 3.5,
which always uses libm. The arithmetic (both states) is ``test_sizedist_libm_pow.py``; this file
covers the wiring.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)
run_flight = sys.modules[_spec.name]


class TestLibmPowStamp(unittest.TestCase):
    def setUp(self):
        for name in ("LIBM_POW", "ENGINE"):
            self.addCleanup(setattr, run_flight, name, getattr(run_flight, name))
        run_flight.ENGINE = "3.1.4"

    def test_default_stamp_carries_no_libm_key(self):
        """Absent at the default, so no sd stamp written before B9 goes stale."""
        run_flight.LIBM_POW = False
        self.assertNotIn("libm_pow", run_flight.sd_call_label(run_flight.IAT_FILE))

    def test_on_is_stamped(self):
        run_flight.LIBM_POW = True
        self.assertIn(" libm_pow=on", run_flight.sd_call_label(run_flight.IAT_FILE))

    def test_default_is_off(self):
        self.assertFalse(run_flight.LIBM_POW)


class TestLibmPowRefusedOnEngine35(unittest.TestCase):
    MY_REFUSAL = "--libm-pow is engine 3.1.4 only"

    def _run(self, engine):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "x.2DS"
            raw.write_bytes(b"")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    rc = run_flight.main(["--preset", "ORACLES_2016_2DS_H", "--engine", engine,
                                          *(["--port-validation"] if engine == "3.1.4" else []),
                                          "--libm-pow", "--dry-run", "--yes", str(raw)])
                except SystemExit as exc:
                    rc = exc.code
        return rc, buf.getvalue()

    def setUp(self):
        for name in ("LIBM_POW", "ENGINE", "PROFILE", "WRITE_PROVENANCE", "JIT"):
            self.addCleanup(setattr, run_flight, name, getattr(run_flight, name))

    def test_engine_35_refuses(self):
        rc, out = self._run("3.5")
        self.assertEqual(rc, 2)
        self.assertIn(self.MY_REFUSAL, out, "refused, but not by this guard")

    def test_engine_314_is_not_refused_by_this_guard(self):
        _, out = self._run("3.1.4")
        self.assertNotIn(self.MY_REFUSAL, out)


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
