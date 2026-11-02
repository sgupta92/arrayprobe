# SPDX-License-Identifier: BSD-3-Clause
"""``--chunks`` under engine 3.1.4 with a TAS-file profile is refused.

``STOCK_V314`` sets ``time_in_seconds_from_tas``, so ``imgproc_sm`` builds ``Time_in_seconds``
as a running sum over the whole file (``imgProc_sm.m:724-778``). A chunk worker starts that sum
afresh at its first particle, and every particle after a seam then differs from the serial run:
2 ulp at a constant TAS, 5.65 s at a varying one.
v3.5 primes the seam;
v3.1.4 is kept for ORACLES validation, whose profiles leave the flag off, so the driver
refuses the combination instead. Both gates are exercised: ``main()`` before S2, and ``stage3``
for callers that reach it directly.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tests._repo import needs_v314_engine  # noqa: E402

import run_flight as rf  # noqa: E402
from arrayprobe.profiles import ORACLES_2016, STOCK_V314  # noqa: E402


class TestChunksRefusedUnderTasProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.raw = self.tmp / "base160906064017.2DS"
        self.raw.write_bytes(b"")
        self.tas = self.tmp / "tas.txt"
        self.tas.write_text("120000 170\n")
        self.saved = {k: getattr(rf, k) for k in ("ENGINE", "PROFILE", "log")}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(rf, k, v)

    def _main(self, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rf.main([str(self.raw), "--engine", "3.1.4", "--port-validation",
                          "--preset", "ORACLES_2016_2DS_H",
                          "--out", str(self.tmp / "out"), "--stages", "3", *extra])
        return rc, buf.getvalue()

    @needs_v314_engine
    def test_main_refuses_chunks_with_stock_v314_and_a_tas_file(self):
        rc, out = self._main("--profile", "stock-v3.1.4", "--tas-file", str(self.tas),
                             "--chunks", "2")
        self.assertEqual(rc, 2, out)
        self.assertIn("--chunks is not available under --engine 3.1.4", out)
        self.assertIn("stock-v3.1.4", out)

    def test_the_flag_is_what_triggers_it(self):
        # The refusal keys on the profile's own flag, not the profile's name.
        self.assertTrue(STOCK_V314.time_in_seconds_from_tas)
        self.assertFalse(ORACLES_2016.time_in_seconds_from_tas)

    def test_stage3_refuses_directly_before_spawning(self):
        rf.ENGINE = "3.1.4"
        rf.PROFILE = STOCK_V314
        rf.log = lambda *a, **k: None
        image = self.tmp / "base160906064017.H.cdf"
        image.write_bytes(b"")
        orig = rf.image_record_count
        rf.image_record_count = lambda _p: 10
        try:
            with self.assertRaisesRegex(ValueError, "running sum"):
                rf.stage3(image, self.tmp, chunks=2, accept_unstamped=True)
        finally:
            rf.image_record_count = orig


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(rf)


if __name__ == "__main__":
    unittest.main()
