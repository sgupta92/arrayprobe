# SPDX-License-Identifier: BSD-3-Clause
"""``[run].presets`` / ``probe_case`` / ``probe_case_module`` reach the driver's argv.

``arrayprobe run`` builds ``run_flight``'s argv from the config. Until these keys existed an ARM
ENA 2D-S run through it never named its probe case and sized on the HVPS bin table. Plumbing
only: nothing is processed here (a stub driver captures the argv; the refusal case stops at the
driver's preflight).
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arrayprobe import cli
from arrayprobe.config import ConfigError, load_config
from arrayprobe_uiops.probe_cases import register_v35_2ds_ladder_fix

#: The shipped generic probe case; it is only the name the config carries and the driver forwards.
CASE = register_v35_2ds_ladder_fix().name

BASE = """
[fidelity]
profile = "stock-v3.5"
[enhancements]
[run]
engine = "3.5"
preset = "P"
out = "o"
"""
EXTRA = f"""presets = "my.presets.toml"
probe_case = "{CASE}"
probe_case_module = "arrayprobe_uiops.probe_cases"
"""


class _Stub:
    PRESETS: dict = {}

    def __init__(self):
        self.argv = None

    def main(self, argv):
        self.argv = list(argv)
        return 0


def _argv_for(text: str, root: Path) -> list[str]:
    cfgp = root / "run.toml"
    cfgp.write_text(text, encoding="utf8")
    stub = _Stub()
    ns = cli.build_parser().parse_args(["run", str(cfgp), str(root / "x.2DS")])
    with mock.patch.object(cli, "_load_run_flight", return_value=stub), \
            contextlib.redirect_stdout(io.StringIO()):
        rc = ns.func(ns)
    assert rc == 0 and stub.argv is not None
    return stub.argv


class TestRunKeysForwarded(unittest.TestCase):
    def test_all_three_keys_are_forwarded_as_the_hand_written_flags(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            argv = _argv_for(BASE + EXTRA, root)
            self.assertEqual(argv[argv.index("--presets") + 1],
                             str((root / "my.presets.toml").resolve()))
            self.assertEqual(argv[argv.index("--probe-case") + 1], CASE)
            self.assertEqual(argv[argv.index("--probe-case-module") + 1],
                             "arrayprobe_uiops.probe_cases")

    def test_absent_keys_leave_the_argv_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            argv = _argv_for(BASE, Path(d).resolve())
            for flag in ("--presets", "--probe-case", "--probe-case-module"):
                self.assertNotIn(flag, argv)

    def test_keys_must_be_strings(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "run.toml"
            p.write_text(BASE + "probe_case = 3\n", encoding="utf8")
            with self.assertRaises(ConfigError):
                load_config(p)

    def test_an_unknown_probe_case_is_refused_before_anything_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            cfgp = root / "run.toml"
            cfgp.write_text(BASE.replace('preset = "P"', 'preset = "ORACLES_2016_2DS_H"')
                            + 'probe_case = "no-such-case"\n', encoding="utf8")
            raw = root / "base160906064017.2DS"
            raw.write_bytes(b"")
            # A fresh process, as a user meets it: in-process, probe cases and presets other
            # tests registered stay registered and the refusal is not the one under test.
            env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
            p = subprocess.run([sys.executable, "-m", "arrayprobe", "run", str(cfgp), str(raw),
                                "--dry-run", "--yes"], capture_output=True, text=True,
                               env=env, cwd=root, timeout=300)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertIn("no probe case 'no-such-case' is registered", p.stdout + p.stderr)

    def test_the_shipped_arm_example_names_its_probe_case(self):
        ex = Path(__file__).resolve().parents[1] / "examples" / "configs" / "arm_ena" \
            / "arm_ena_stock.toml"
        if not ex.exists():
            self.skipTest("Example not in this tree is not distributed with the package")
        run = load_config(ex).run
        self.assertEqual(run["probe_case"], "arm-ena-2ds")
        self.assertEqual(run["probe_case_module"], "arrayprobe_uiops.register_arm_ena_2ds")


if __name__ == "__main__":
    unittest.main()
