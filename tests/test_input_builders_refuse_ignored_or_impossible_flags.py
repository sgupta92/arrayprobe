# SPDX-License-Identifier: BSD-3-Clause
"""``make-tas-file`` and ``make-demo-flight`` refuse a flag they would ignore, or a value that
cannot mean what it says, instead of writing a file.

Found 2026-09-26 by a cold-user walk:

* ``make-tas-file --from-tas-csv x --start-hhmmss 120000 --seconds 99`` and ``... --date D
  --search DIR`` wrote the whole csv's series, exit 0, as if those flags had trimmed or checked
  it;
* ``make-tas-file --constant-tas -5`` wrote a negative airspeed (the pipeline's policy then set
  every second aside for 170 m/s), and ``--seconds -3`` was a ``ValueError`` traceback;
* ``make-demo-flight --seconds 1`` (or 0) wrote a flight that decodes to no airspeed record
  (``<stem>.tas.csv``), exit 0, and the run then failed at S4;
  ``--tas-mps -1`` was accepted.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from arrayprobe import cli


class _Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.csv = self.root / "base160101000000.tas.csv"
        self.csv.write_text("60640.0,130.0,,,,,,,\n60641.0,130.0,,,,,,,\n60642.0,130.0,,,,,,,\n",
                            encoding="utf-8")

    def _run(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                rc = cli.main(list(argv))
            except SystemExit as exc:
                rc = exc.code
        return rc, err.getvalue()


class MakeTasFile(_Tmp):

    def test_flags_the_source_does_not_read_are_refused(self):
        out = self.root / "a.cdf"
        cases = [
            ("--from-tas-csv", str(self.csv), "--start-hhmmss", "120000", "--seconds", "99"),
            ("--from-tas-csv", str(self.csv), "--date", "20160101", "--search", str(self.root)),
            ("--constant-tas", "130", "--start-hhmmss", "0", "--seconds", "3",
             "--date", "20160101"),
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                rc, err = self._run("make-tas-file", str(out), *extra)
                self.assertEqual(rc, 2)
                self.assertIn("not read", err)
                self.assertFalse(out.exists())

    def test_an_impossible_constant_series_is_refused(self):
        out = self.root / "b.cdf"
        for tas, seconds in (("-5", "3"), ("0", "3"), ("130", "-3"), ("130", "0")):
            with self.subTest(tas=tas, seconds=seconds):
                rc, err = self._run("make-tas-file", str(out), "--constant-tas", tas,
                                    "--start-hhmmss", "0", "--seconds", seconds)
                self.assertEqual(rc, 2)
                self.assertNotIn("Traceback", err)
                self.assertFalse(out.exists())

    def test_the_documented_forms_still_write(self):
        rc, _ = self._run("make-tas-file", str(self.root / "c.cdf"), "--from-tas-csv",
                          str(self.csv))
        self.assertEqual(rc, 0)
        rc, _ = self._run("make-tas-file", str(self.root / "d.cdf"), "--constant-tas", "130",
                          "--start-hhmmss", "60640", "--seconds", "3")
        self.assertEqual(rc, 0)


class MakeDemoFlight(_Tmp):

    def test_a_flight_too_short_to_decode_is_refused(self):
        for seconds in ("1", "0"):
            path = self.root / f"base16010100000{seconds}.2DS"
            with self.subTest(seconds=seconds):
                rc, err = self._run("make-demo-flight", str(path), "--seconds", seconds)
                self.assertEqual(rc, 2)
                self.assertIn("at least 2", err)
                self.assertFalse(path.exists())

    def test_a_non_positive_airspeed_is_refused(self):
        path = self.root / "base160101000000.2DS"
        rc, _ = self._run("make-demo-flight", str(path), "--tas-mps", "-1")
        self.assertEqual(rc, 2)
        self.assertFalse(path.exists())

    def test_two_seconds_is_accepted(self):
        rc, _ = self._run("make-demo-flight", str(self.root / "base160101000000.2DS"),
                          "--seconds", "2")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
