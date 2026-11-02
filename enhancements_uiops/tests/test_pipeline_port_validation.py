# SPDX-License-Identifier: BSD-3-Clause
"""The enhancements driver forwards ``--port-validation`` and never adds it on its own.

``arrayprobe run`` refuses ``[run].engine = "3.1.4"`` without ``--port-validation`` (the v3.1.4
engine is the ORACLES-validation anchor only, and the flag stamps its output as port
validation). ``pipeline.run_port`` launches that command, so it must be able to pass the flag,
and must pass it only when its caller asks: inferring it from the config's engine would make the
declaration nobody's choice. The subprocess is replaced, so these tests run nothing.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from arrayprobe_enhancements import pipeline


def _captured_cmd(**kwargs) -> list[str]:
    done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with mock.patch.object(pipeline.subprocess, "run", return_value=done) as run:
        pipeline.run_port(Path("run.toml"), [Path("base.2DS")], **kwargs)
    return run.call_args.args[0]


class RunPortForwardsPortValidation(unittest.TestCase):
    def test_absent_by_default(self):
        self.assertNotIn("--port-validation", _captured_cmd())

    def test_present_when_asked(self):
        cmd = _captured_cmd(port_validation=True)
        self.assertEqual(cmd.count("--port-validation"), 1)
        self.assertEqual(cmd[3], "run")

    def test_independent_of_the_enhancements_flag(self):
        cmd = _captured_cmd(enhancements=True, port_validation=True)
        self.assertIn("--enhancements", cmd)
        self.assertIn("--port-validation", cmd)


class CommandLineForwardsPortValidation(unittest.TestCase):
    """``arrayprobe-enhanced run --port-validation`` reaches ``apply_enhancements``."""

    def _forwarded(self, argv: list[str]) -> bool:
        with mock.patch.object(pipeline, "load_config") as load, \
                mock.patch.object(pipeline, "apply_enhancements", return_value=[]) as apply:
            load.return_value.run = {"engine": "3.1.4"}
            pipeline.main(argv)
        return apply.call_args.kwargs["port_validation"]

    def test_flag_given(self):
        self.assertTrue(self._forwarded(["run", "run.toml", "base.2DS", "--port-validation"]))

    def test_flag_absent(self):
        self.assertFalse(self._forwarded(["run", "run.toml", "base.2DS"]))


if __name__ == "__main__":
    unittest.main()
