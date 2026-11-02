# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2 RAF Fast-2DC end to end on a real NCAR ``.2d`` window against GDL.

Golden: ``tests/data/gdl_soda2_raf_realfile_golden.json``, written by
``gdl_oracle/run_soda2_raf_realfile.py`` -- the vendored ``soda2_process_2d.pro``
under GDL on CAESAR rf05, probe C4, 35480-35540 s. Skipped when the golden is
absent (GDL did not complete; then the real-file run is a layer-3 smoke result).
The port re-run needs the raw file, named by ``ARRAYPROBE_RAF_F2DC_RAW`` (its
full path), and is gated behind ``ARRAYPROBE_SLOW``.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "data" / "gdl_soda2_raf_realfile_golden.json"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts" / "validation" / "gdl"))

from pathlib import Path as _P  # noqa: E402

from _slow import slow  # noqa: E402

# _release_fixture_guard: gdl_soda2_raf_realfile_golden.json is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "gdl_soda2_raf_realfile_golden.json").exists():
    raise unittest.SkipTest(
        "compares against a stored result computed from a real aircraft file, which this release "
        "does not distribute")


def _golden() -> dict | None:
    return json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.is_file() else None


@unittest.skipUnless(GOLDEN.is_file(), "Golden is not distributed with the package; the test "
                                       "needs files that are not part of this release")
class RafRealfileAgainstGdl(unittest.TestCase):

    # All eight fields identical since RAF takes soda2_particlesort.pro:12-16's
    # probe-clock default in spec_sort_locals (it had fallen to SPEC's buffertime).
    def test_golden_records_gdl_and_port_identical(self) -> None:
        g = _golden()
        assert g is not None
        self.assertEqual(g["header"]["gdl_status"], "OK")
        for k, e in g["fields"].items():
            with self.subTest(field=k):
                self.assertTrue(e["identical"], e)
                self.assertEqual(e["gdl_sha256"], e["port_sha256"])


# Its own class so the gate sits on a class, which is what
# tests/test_slow_gate_is_exercised.py's GATED_TESTS registers (2026-10-07).
@slow
@unittest.skipUnless(GOLDEN.is_file(), "Golden is not distributed with the package; the test "
                                       "needs files that are not part of this release")
class RafRealfilePortRerun(unittest.TestCase):

    def test_port_reproduces_the_gdl_digests(self) -> None:
        try:
            import run_soda2_raf_realfile as r
        except ImportError:  # the runner is a development tool the public tree does not ship
            self.skipTest("the helper script for this check is not part of this release")

        raw = r.raw_path()
        if raw is None or not raw.is_file():
            self.skipTest(r.RAW_UNSET)
        g = _golden()
        assert g is not None
        with tempfile.TemporaryDirectory() as d:
            p = r.port_fields(raw.as_posix(), Path(d).as_posix())
        for k, e in g["fields"].items():
            with self.subTest(field=k):
                self.assertEqual(r._digest(p[k]), e["gdl_sha256"])


class TheGoldenIsTracked(unittest.TestCase):
    """Ungated: the golden going missing must fail, not turn every test above into a skip."""

    def test_the_golden_is_tracked(self) -> None:
        self.assertTrue(GOLDEN.is_file(), GOLDEN)
        # The tracked golden records the real-file verdict this module's claims rest on.
        verdict = json.loads(GOLDEN.read_text(encoding="utf-8"))["header"]["verdict"]
        self.assertEqual(verdict, "IDENTICAL")


if __name__ == "__main__":
    unittest.main()
