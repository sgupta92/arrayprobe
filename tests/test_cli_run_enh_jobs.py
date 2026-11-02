# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe run --enh-jobs N`` reaches the driver as ``--enh-jobs N``, as ``--jobs`` does.

The driver's own option (the enhancement pass's worker count) is covered by
``tests/test_run_flight_enh_jobs.py``; this pins the wrapper half. The driver's ``main`` is
replaced by a recorder, so nothing runs and the argv the wrapper built is what is read.
"""
from __future__ import annotations

import io
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from arrayprobe import cli


def _argv_for(*flags: str) -> list[str]:
    root = Path(tempfile.mkdtemp())
    toml = root / "run.toml"
    toml.write_text(
        '[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\npreset = "DEMO_2DS_H"\n',
        encoding="utf-8")
    seen: list[list[str]] = []

    def record(argv):
        seen.append(list(argv))
        return 0

    fake = types.SimpleNamespace(PRESETS={}, main=record)
    with mock.patch.object(cli, "_load_run_flight", return_value=fake), \
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        rc = cli.main(["run", str(toml), str(root / "raw.2DS"), *flags])
    assert rc == 0 and seen, "the wrapper never reached the driver"
    return seen[0]


def _value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


class TheWrapperForwardsEnhJobs(unittest.TestCase):

    def test_a_count_reaches_the_driver(self):
        self.assertEqual(_value(_argv_for("--enh-jobs", "2"), "--enh-jobs"), "2")

    def test_the_default_is_one_like_jobs(self):
        argv = _argv_for()
        self.assertEqual(_value(argv, "--enh-jobs"), "1")
        self.assertEqual(_value(argv, "--jobs"), "1")

    def test_it_is_independent_of_jobs(self):
        argv = _argv_for("--jobs", "3", "--enh-jobs", "2")
        self.assertEqual((_value(argv, "--jobs"), _value(argv, "--enh-jobs")), ("3", "2"))


class WithoutRunOutTheOutputSitsBesideTheConfig(unittest.TestCase):
    """A config with no ``[run].out`` writes to ``<config dir>/output``, never to a path
    that depends on the directory the command was typed in."""

    def test_the_default_out_is_the_config_directory_s_output(self):
        root = Path(tempfile.mkdtemp())
        toml = root / "run.toml"
        toml.write_text(
            '[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\npreset = "DEMO_2DS_H"\n',
            encoding="utf-8")
        seen: list[list[str]] = []

        def record(argv):
            seen.append(list(argv))
            return 0

        fake = types.SimpleNamespace(PRESETS={}, main=record)
        with mock.patch.object(cli, "_load_run_flight", return_value=fake), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli.main(["run", str(toml), str(root / "raw.2DS")])
        self.assertEqual(rc, 0)
        self.assertTrue(seen, "the wrapper never reached the driver")
        self.assertEqual(Path(_value(seen[0], "--out")), (root / "output").resolve())


if __name__ == "__main__":
    unittest.main()
