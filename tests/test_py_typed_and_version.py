# SPDX-License-Identifier: BSD-3-Clause
"""Two things a released package owes its users: its types, and its version.

**Both were missing until 2026-09-12, and neither could have been noticed from
inside this repository.**

`py.typed` — every package here is fully annotated and `mypy src` is clean, but
PEP 561 says an installed package's annotations are invisible to a downstream
type checker unless the package ships a `py.typed` marker. `mypy src` runs
against the *source tree*, where the marker is irrelevant, so the local checks
were green and a user installing the wheel got nothing. The marker also has to
reach the wheel: one that sits in `src/` and is not named in
`[tool.setuptools.package-data]` is the same as no marker at all, which is why
this file checks both halves.

`--version` — a user could not ask the command what code produced their output.
That matters more here than in most packages: the whole claim is that specific
numbers come out. The `.call` sidecar already records the *arguments*; this
records the *code*.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from tests._repo import needs_source

PORT = Path(__file__).resolve().parents[1]
SRC = PORT / "src"
PYPROJECT = PORT / "pyproject.toml"


def _shipped_packages() -> list[Path]:
    """Top-level packages under ``src/``, found rather than listed.

    A fourth port would otherwise ship without a marker until somebody
    remembered to add its name here -- which is exactly how the three that
    exist went eighteen months without one.
    """
    return sorted(d for d in SRC.iterdir()
                  if d.is_dir() and (d / "__init__.py").is_file())


@needs_source
class EveryShippedPackageDeclaresItsTypes(unittest.TestCase):
    def test_there_are_packages_to_check(self):
        """Guards the check: an empty list makes the next test vacuous."""
        self.assertGreaterEqual(
            len(_shipped_packages()), 3,
            f"found only {[d.name for d in _shipped_packages()]} under src/")

    def test_each_one_has_a_py_typed_marker(self):
        missing = [d.name for d in _shipped_packages()
                   if not (d / "py.typed").is_file()]
        self.assertEqual(
            missing, [],
            f"these packages ship annotations a downstream type checker will "
            f"ignore, because PEP 561 needs the marker: {missing}")

    def test_setuptools_is_told_to_package_the_marker(self):
        """A marker that does not reach the wheel is not a marker.

        Checked against the build configuration rather than by building, so
        the failure names the missing line instead of a missing file in a
        tarball.
        """
        with open(PYPROJECT, "rb") as fh:
            cfg = tomllib.load(fh)
        package_data = (cfg.get("tool", {}).get("setuptools", {})
                        .get("package-data", {}))
        patterns = [p for globs in package_data.values() for p in globs]
        self.assertIn(
            "py.typed", patterns,
            "pyproject.toml does not tell setuptools to include py.typed, so "
            f"the markers under src/ never reach a wheel. Found: {package_data}")

    def test_the_marker_says_why_it_exists(self):
        """An empty file is valid PEP 561 and tells the next reader nothing
        about why it may not be deleted."""
        for pkg in _shipped_packages():
            with self.subTest(package=pkg.name):
                text = (pkg / "py.typed").read_text(encoding="utf-8")
                self.assertIn("PEP 561", text)


class TheCommandCanSayWhichVersionItIs(unittest.TestCase):
    def test_version_flag_prints_the_package_version(self):
        from arrayprobe import __version__
        from arrayprobe.cli import build_parser

        with self.assertRaises(SystemExit) as caught:
            build_parser().parse_args(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertTrue(__version__, "the package reports no version at all")

    def test_it_runs_as_an_actual_command(self):
        """The parser test above would pass on a flag no user can reach.

        Run as a subprocess, which is how a user meets it -- and which also
        catches an import-time failure the in-process test would not, since
        the module is already imported by then.
        """
        from arrayprobe import __version__
        out = subprocess.run(
            [sys.executable, "-m", "arrayprobe.cli", "--version"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        self.assertIn(__version__, out.stdout + out.stderr)
        self.assertIn("arrayprobe", out.stdout + out.stderr)

    def test_the_version_it_prints_is_the_one_pyproject_declares(self):
        """Two sides from different places. `test_version.py` already pairs
        the module against pyproject; this pairs what the COMMAND prints
        against pyproject, which is the string a user would quote in a paper.
        """
        from arrayprobe import __version__
        with open(PYPROJECT, "rb") as fh:
            declared = tomllib.load(fh)["project"]["version"]
        self.assertEqual(__version__, declared)


if __name__ == "__main__":
    unittest.main()
