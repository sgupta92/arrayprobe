# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe read-binary`` says what it wrote, and refuses what it cannot honour.

Found 2026-09-26 by a cold-user walk with the tracked demo 2D-S file:

* ``--format sea`` printed ``wrote <outfile>`` -- a path that was never created (SEA writes
  ``<outfile>.CIP.cdf`` / ``.2DC.cdf``, PMS three ``<outfile>.*.cdf``), exit 0, and left the
  real products unstamped;
* handed a 2D-S file, the SEA reader found no record it recognised and wrote empty products,
  exit 0, with nothing to say it had read nothing;
* ``--channels H`` with ``--format sea`` was accepted and ignored;
* ``--format dmt`` on the same file raised ``DecompressionError`` as a traceback;
* a missing input under ``--format spec`` created two empty ``.H``/``.V.cdf`` files and then
  raised ``FileNotFoundError``.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import cli

RAW_2DS = Path(__file__).resolve().parent / "data" / "demo_flight_v314_raw.2DS"


@unittest.skipUnless(RAW_2DS.is_file(), "Tracked demo raw file is not distributed with the "
                                        "package")
class ReadBinaryRefusals(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = cli.main(["read-binary", *argv])
            except SystemExit as exc:      # argparse's parser.error
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    @needs_v314_engine
    def test_a_wrong_format_is_refused_in_one_line(self):
        """A 2D-S file read as SEA: the reader dies where read_binary_SEA.m dies (an end of file
        inside the directory loop, SEA F5), so the command refuses in one line, exit 1."""
        out = self.root / "s"
        rc, stdout, stderr = self._run(str(RAW_2DS), str(out), "--format", "sea",
                                       "--engine", "3.1.4")
        self.assertEqual(rc, 1)
        self.assertIn("did not decode", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn(f"wrote {out} ", stdout)

    @needs_v314_engine
    def test_channels_with_a_non_spec_format_is_refused(self):
        rc, _out, stderr = self._run(str(RAW_2DS), str(self.root / "s"), "--format", "sea",
                                     "--channels", "H", "--engine", "3.1.4")
        self.assertEqual(rc, 2)
        self.assertIn("takes no --channels", stderr)

    @needs_v314_engine
    def test_a_decode_error_is_one_line(self):
        rc, _out, stderr = self._run(str(RAW_2DS), str(self.root / "d.nc"), "--format", "dmt",
                                     "--engine", "3.1.4")
        self.assertEqual(rc, 1)
        self.assertIn("did not decode", stderr)
        self.assertNotIn("Traceback", stderr)

    @needs_v314_engine
    def test_a_missing_input_writes_nothing(self):
        rc, _out, stderr = self._run(str(self.root / "nope.2DS"), str(self.root / "x"),
                                     "--format", "spec", "--profile", "stock-v3.1.4",
                                     "--engine", "3.1.4")
        self.assertEqual(rc, 2)
        self.assertIn("not a file", stderr)
        self.assertEqual(list(self.root.iterdir()), [])

    @needs_v314_engine
    def test_the_spec_happy_path_still_works_and_defaults_to_both_channels(self):
        rc, stdout, _err = self._run(str(RAW_2DS), str(self.root / "demo"), "--format", "spec",
                                     "--profile", "oracles-production", "--engine", "3.1.4")
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "demo.H.cdf").is_file())
        self.assertTrue((self.root / "demo.V.cdf").is_file())
        self.assertIn("records:", stdout)


if __name__ == "__main__":
    unittest.main()
