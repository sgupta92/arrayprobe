# SPDX-License-Identifier: BSD-3-Clause
"""A mistyped config path or decoded directory gets one actionable line, rc 2, no traceback."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr

from arrayprobe import cli


def _run(argv):
    err = io.StringIO()
    with redirect_stderr(err):
        rc = cli.main(argv)
    return rc, err.getvalue()


class TestMissingInputsAreActionable(unittest.TestCase):
    def test_run_with_a_missing_config_names_the_file_and_what_to_do(self):
        rc, msg = _run(["run", "missing.toml"])
        self.assertEqual(rc, 2)
        self.assertIn("missing.toml", msg)
        self.assertIn("does not exist", msg)
        self.assertIn("examples/start_here/run.toml", msg)
        self.assertNotIn("Errno", msg)
        self.assertNotIn("Traceback", msg)
        self.assertEqual(len(msg.strip().splitlines()), 1)

    def test_gallery_with_a_missing_decoded_dir_names_the_directory(self):
        with tempfile.TemporaryDirectory() as d:
            nodir = os.path.join(d, "nodir")
            rc, msg = _run(["gallery", "--decoded-dir", nodir, "--flight", "x.H",
                            "--out", os.path.join(d, "out")])
        self.assertEqual(rc, 2)
        self.assertIn("--decoded-dir", msg)
        self.assertIn(nodir, msg)
        self.assertIn("proc.x.H.nc", msg)
        self.assertNotIn("Traceback", msg)


if __name__ == "__main__":
    unittest.main()
