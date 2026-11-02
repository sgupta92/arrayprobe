# SPDX-License-Identifier: BSD-3-Clause
"""A path that does not exist is a one-line exit 2 naming it, from each subcommand below.

Found 2026-09-26 by a cold-user walk:

* ``arrayprobe provenance <typo>`` printed the typo as an ``unstamped`` product and exited 0 --
  indistinguishable from a real product that lost its sidecar;
* ``arrayprobe attributed <typo>`` said the file "carries no .call sidecar"; and on a real
  unstamped product it raised ``MissingStampError`` as a traceback whose advice was the Python
  keyword ``accept_unstamped=True``, not the flag;
* ``arrayprobe tas-from-nasa-ames <typo>`` raised ``FileNotFoundError``, exit 1.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests._repo import PKG_ROOT, needs_v314_engine  # noqa: E402

import arrayprobe.tools
from arrayprobe import cli

# The release holds the NASA-Ames TAS reader back (scripts/release_allowlist.txt, the row for
# the module READER names below), and the allowlist itself does not ship. So the view
# is decided from the module's presence, and the allowlist's presence says which view must hold.
READER = "arrayprobe.tools.nasa_ames_tas"
ALLOWLIST = PKG_ROOT / "scripts" / "release_allowlist.txt"


def reader_ships() -> bool:
    return importlib.util.find_spec(READER) is not None


class MissingPathsAreRefused(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.missing = self.root / "no_such_product.nc"

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, out.getvalue() + err.getvalue()

    def test_provenance(self):
        rc, text = self._run("provenance", str(self.missing))
        self.assertEqual(rc, 2)
        self.assertIn("not found", text)
        self.assertIn("no_such_product.nc", text)

    def test_provenance_still_reports_an_orphan_sidecar_and_a_real_directory(self):
        Path(str(self.missing) + ".call").write_text("engine=3.5 profile=stock-v3.5\n",
                                                     encoding="utf-8")
        rc, text = self._run("provenance", str(self.missing), str(self.root))
        self.assertEqual(rc, 0)
        self.assertIn("orphan-stamp", text)

    def test_attributed(self):
        rc, text = self._run("attributed", str(self.missing))
        self.assertEqual(rc, 2)
        self.assertIn("not a file", text)
        self.assertNotIn("sidecar", text)

    @needs_v314_engine
    def test_the_per_stage_commands(self):
        """imgproc, sizedist and combine let FileNotFoundError out as a traceback, exit 1."""
        argvs = {
            "imgproc": ["imgproc", str(self.missing), str(self.root / "o.nc"), "2DS", "1", "1",
                        "X", "--profile", "oracles-production", "--engine", "3.1.4"],
            "sizedist": ["sizedist", str(self.missing), str(self.root / "sd.nc"), "--tas-csv",
                         str(self.root / "x.tas.csv"), "2DS", "6", "1", "80000", "0", "X",
                         "20160906 000000", "--tree", "production", "--engine", "3.1.4"],
            "combine": ["combine", str(self.missing), str(self.root / "c.nc"), "--flight-date",
                        "20160906", "--summary-time", "16_09_06_06_40_17", "--engine", "3.1.4"],
        }
        for name, argv in argvs.items():
            with self.subTest(command=name):
                rc, text = self._run(*argv)
                self.assertEqual(rc, 2)
                self.assertIn(f"arrayprobe {name}:", text)
                self.assertNotIn("Traceback", text)

    @needs_v314_engine
    def test_imgproc_names_the_flag_not_the_keyword(self):
        rc, text = self._run("imgproc", str(self.missing), str(self.root / "o.nc"), "2DS", "1",
                             "1", "X", "--profile", "stock-v3.1.4", "--engine", "3.1.4")
        self.assertEqual(rc, 2)
        self.assertIn("--tas-file", text)
        rc, text = self._run("imgproc", str(self.missing), str(self.root / "o.nc"), "2DS", "1",
                             "1", "X", "--profile", "bogus", "--engine", "3.1.4")
        self.assertEqual(rc, 2)
        self.assertIn("unknown fidelity profile", text)

    def _tas_from_nasa_ames(self):
        return self._run("tas-from-nasa-ames", str(self.missing), "--out",
                         str(self.root / "t.tas.csv"), "--flight-date", "2016-09-06")

    def _assert_refused_as_not_shipped(self, rc, text):
        self.assertEqual(rc, 2)
        self.assertIn("not available in this release", text)
        self.assertIn("arrayprobe.tools.nasa_ames_tas", text)
        self.assertIn("make-tas-file", text)
        self.assertNotIn("Traceback", text)
        self.assertFalse((self.root / "t.tas.csv").exists())

    def test_tas_from_nasa_ames(self):
        rc, text = self._tas_from_nasa_ames()
        if not reader_ships():
            # Release view: the reader is held back, so the subcommand refuses by name.
            self._assert_refused_as_not_shipped(rc, text)
            return
        self.assertEqual(rc, 2)
        self.assertIn("cannot read", text)
        self.assertFalse((self.root / "t.tas.csv").exists())

    def test_without_the_reader_the_refusal_is_exit_2_naming_why(self):
        """The release view, simulated in any tree: the reader's import fails.

        Before 2026-10-17 this path raised ``SystemExit(str)``, which escaped ``cli.main`` and
        exited 1, where every other refusal prints to stderr and returns 2.
        """
        missing = object()
        saved_attr = getattr(arrayprobe.tools, "nasa_ames_tas", missing)
        try:
            with mock.patch.dict(sys.modules, {READER: None}):
                rc, text = self._tas_from_nasa_ames()
        finally:
            if saved_attr is missing:
                if hasattr(arrayprobe.tools, "nasa_ames_tas"):
                    delattr(arrayprobe.tools, "nasa_ames_tas")
            else:
                arrayprobe.tools.nasa_ames_tas = saved_attr
        self._assert_refused_as_not_shipped(rc, text)
        if saved_attr is not missing:
            self.assertIs(sys.modules[READER], saved_attr)

    def test_the_development_view_ships_the_reader(self):
        """Negative check: where the allowlist is present, the release branch above must not
        be taken -- an accidental drop of the reader fails here instead of passing silently."""
        if not ALLOWLIST.is_file():
            self.skipTest("release view: scripts/release_allowlist.txt does not ship, and the "
                          "reader is held back by it")
        self.assertTrue(reader_ships(), f"{READER} is missing from a development tree")


if __name__ == "__main__":
    unittest.main()
