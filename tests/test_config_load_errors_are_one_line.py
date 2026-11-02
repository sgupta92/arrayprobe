# SPDX-License-Identifier: BSD-3-Clause
"""A malformed, missing or refused config file is a one-line exit 2 from every driver.

Found 2026-09-26 by a cold-user walk. ``load_config`` let ``tomllib.TOMLDecodeError`` escape,
so a missing ``]`` printed a traceback, exit 1, from ``arrayprobe run``, ``arrayprobe soda2
run`` and ``arrayprobe-enhanced run``; a directory given as the config raised
``PermissionError`` on Windows; and ``scripts/run_flight.py --config`` let every
``ConfigError`` -- an unknown ``[run]`` key, say -- and a missing file escape as tracebacks
while ``arrayprobe run`` reported the same file in one line.
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]

_ARM_EXAMPLES = ROOT / "examples" / "configs" / "arm_ena"


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


#: The ARM ENA example configs and their registration module are development-only; the
#: release ships neither, so the tests that load them skip there.
_needs_arm_example = unittest.skipUnless(
    _ARM_EXAMPLES.is_dir(),
    "Examples/configs/arm_ena/ is not distributed with the package",
)
_needs_arm_example_and_module = unittest.skipUnless(
    _ARM_EXAMPLES.is_dir() and _has_module("arrayprobe_uiops.register_arm_stock"),
    "examples/configs/arm_ena/ and arrayprobe_uiops.register_arm_stock: the ARM ENA example "
    "and its profile registration module are not in this distribution",
)
sys.path.insert(0, str(ROOT / "tests"))
import _run_flight_state  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
sys.modules.setdefault(_SPEC.name, importlib.util.module_from_spec(_SPEC))
run_flight = sys.modules[_SPEC.name]
if not hasattr(run_flight, "main"):
    _SPEC.loader.exec_module(run_flight)

from arrayprobe import cli  # noqa: E402
from arrayprobe.config import ConfigError, load_config  # noqa: E402


class _Files(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bad = self.root / "bad.toml"
        self.bad.write_text('[fidelity\nprofile = "stock-v3.5"\n', encoding="utf-8")
        self.unknown = self.root / "unknown.toml"
        self.unknown.write_text('[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\n'
                                "bogus = 1\n", encoding="utf-8")
        self.raw = self.root / "base160101000000.2DS"
        self.raw.write_bytes(b"")


class TheLoaderRaisesConfigError(_Files):

    def test_invalid_toml_is_a_config_error_naming_the_file(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(self.bad)
        self.assertIn("not valid TOML", str(cm.exception))
        self.assertIn("bad.toml", str(cm.exception))

    def test_invalid_toml_is_still_a_toml_decode_error_for_existing_callers(self):
        import tomllib
        with self.assertRaises(tomllib.TOMLDecodeError):
            load_config(self.bad)

    def test_a_utf8_byte_order_mark_is_accepted(self):
        """Windows PowerShell 5.1's ``Set-Content -Encoding utf8`` writes one; tomllib refused
        the whole file over it with "Invalid statement (at line 1, column 1)"."""
        cfg = self.root / "bom.toml"
        cfg.write_bytes(b"\xef\xbb\xbf" + b'[fidelity]\nprofile = "stock-v3.5"\n')
        self.assertEqual(load_config(cfg).profile.name, "stock-v3.5")

    def test_utf16_is_refused_by_name(self):
        """PowerShell 5.1's ``>`` redirect writes UTF-16LE with a BOM."""
        cfg = self.root / "u16.toml"
        cfg.write_bytes('[fidelity]\nprofile = "stock-v3.5"\n'.encode("utf-16"))
        with self.assertRaises(ConfigError) as cm:
            load_config(cfg)
        self.assertIn("UTF-16", str(cm.exception))

    @repo_only  # reads examples/, not in the sdist
    @_needs_arm_example
    def test_a_presets_file_with_a_bom_is_accepted_too(self):
        presets = ROOT / "examples" / "configs" / "arm_ena" / "arm_ena_2ds.presets.toml"
        copy = self.root / "p.toml"
        copy.write_bytes(b"\xef\xbb\xbf" + presets.read_bytes())
        _run_flight_state.preserve(self, run_flight)
        try:
            loaded = run_flight.load_presets(copy)
        except run_flight.PresetFileError as exc:
            self.assertNotIn("TOML", str(exc))   # refused on content, never on the BOM
        else:
            self.assertTrue(loaded)

    def test_a_directory_is_a_config_error_not_a_permission_error(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(self.root)
        self.assertIn("is a directory", str(cm.exception))


class AnUnimportableProfileModuleSaysWhereItIs(_Files):
    """An ARM run configuration, ``arm_ena_stock.toml``, names
    ``profile_module = "arm_ena_stock_profile"``,
    a file beside it. Run from ``python_port/`` without that directory on PYTHONPATH, the
    refusal said only "No module named ..."."""

    def test_a_module_beside_the_config_is_named_with_the_directory_to_add(self):
        cfg = self.root / "run.toml"
        cfg.write_text('[fidelity]\nprofile = "stock-v3.5"\n'
                       'profile_module = "zz_not_on_path_profile"\n', encoding="utf-8")
        (self.root / "zz_not_on_path_profile.py").write_text("", encoding="utf-8")
        with self.assertRaises(ConfigError) as cm:
            load_config(cfg)
        self.assertIn("PYTHONPATH", str(cm.exception))
        self.assertIn(str(self.root.resolve()), str(cm.exception))

    @repo_only  # reads examples/, not in the sdist
    @_needs_arm_example_and_module
    def test_the_shipped_arm_example_loads_with_no_pythonpath_change(self):
        """Since 2026-09-29 the ARM example runs on v3.5 and names a profile module
        that ships in the package, so it needs no PYTHONPATH entry; the error message for a
        module that is not importable is the test above. Run in a subprocess, so the profile
        it registers cannot leak into this process's registry."""
        import subprocess
        example = ROOT / "examples" / "configs" / "arm_ena" / "arm_ena_stock.toml"
        code = ("from arrayprobe.config import load_config; "
                f"print(load_config(r'{example}').profile.name)")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(r.stdout.strip().splitlines()[-1], "arm-ena-stock-v3.5")


class EveryDriverExitsTwoInOneLine(_Files):

    def _cli(self, *argv):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, err.getvalue()

    def test_arrayprobe_run_and_soda2_run(self):
        for argv in (["run", str(self.bad), str(self.raw)],
                     ["soda2", "run", str(self.bad), "--out", str(self.root / "o")]):
            with self.subTest(argv=argv[:2]):
                rc, err = self._cli(*argv)
                self.assertEqual(rc, 2)
                self.assertIn("not valid TOML", err)
                self.assertNotIn("Traceback", err)

    def test_run_flight_config(self):
        _run_flight_state.preserve(self, run_flight)
        lines: list[str] = []
        real_log = run_flight.log
        run_flight.log = lambda msg, *a, **k: lines.append(str(msg))
        self.addCleanup(setattr, run_flight, "log", real_log)
        for cfg, expect in ((self.bad, "not valid TOML"), (self.unknown, "bogus"),
                            (self.root / "missing.toml", "missing.toml")):
            with self.subTest(cfg=cfg.name):
                lines.clear()
                with redirect_stdout(io.StringIO()):
                    rc = run_flight.main(["--config", str(cfg), "--engine", "3.5",
                                          "--preset", "DEMO_2DS_H", "--yes",
                                          "--out", str(self.root / "o"), str(self.raw)])
                self.assertEqual(rc, 2)
                self.assertIn(expect, "\n".join(lines))

    def test_arrayprobe_enhanced_run(self):
        try:
            from arrayprobe_enhancements import pipeline
        except ImportError:
            self.skipTest("arrayprobe_enhancements is not installed")
        for cfg, expect in ((self.bad, "not valid TOML"), (self.root / "missing.toml", "missing")):
            with self.subTest(cfg=cfg.name):
                err = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    rc = pipeline.main(["run", str(cfg), str(self.raw)])
                self.assertEqual(rc, 2)
                self.assertIn(expect, err.getvalue())


if __name__ == "__main__":
    unittest.main()
