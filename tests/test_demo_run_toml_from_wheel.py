# SPDX-License-Identifier: BSD-3-Clause
"""The README Quickstart works from a plain ``pip install``: ``make-demo-flight
--with-config`` writes a ``run.toml`` that runs the demo end to end with no
``examples/`` folder, and makes the same choices as ``examples/start_here/run.toml``."""
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests._repo import repo_only

from arrayprobe.tools import make_demo_flight

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "start_here" / "run.toml"


@repo_only
class TheWrittenConfigMatchesTheExample(unittest.TestCase):
    def test_same_choices_as_examples_start_here(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "demo" / "base160101000000.2DS"
            self.assertEqual(make_demo_flight.main([str(raw), "--dense", "--with-config"]), 0)
            written = tomllib.loads((raw.parent / "run.toml").read_text(encoding="utf-8"))
        example = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
        # The two paths differ by design (relative to each file's own folder); the rest is equal.
        for cfg in (written, example):
            cfg["run"].pop("out")
            cfg["run"].pop("tas_file")
        self.assertEqual(written, example)


class TheWrittenConfigRunsTheDemoEndToEnd(unittest.TestCase):
    def test_run_from_an_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            cmd = [sys.executable, "-m", "arrayprobe"]
            make = subprocess.run(cmd + ["make-demo-flight", "--dense", "--with-config",
                                         "demo/base160101000000.2DS"],
                                  cwd=tmp, env=env, capture_output=True, text=True, timeout=600)
            self.assertEqual(make.returncode, 0, make.stderr)
            self.assertFalse((Path(tmp) / "examples").exists())
            run = subprocess.run(cmd + ["run", "demo/run.toml", "demo/base160101000000.2DS",
                                        "--yes"],
                                 cwd=tmp, env=env, capture_output=True, text=True, timeout=600)
            self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
            self.assertIn("ALL DONE", run.stdout + run.stderr)
            self.assertTrue((Path(tmp) / "demo" / "base160101000000.combined.H.2DS.cdf").exists())


if __name__ == "__main__":
    unittest.main()
