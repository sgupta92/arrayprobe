# SPDX-License-Identifier: BSD-3-Clause
"""``python -m arrayprobe`` works, and is the same front door as ``arrayprobe``.

The R1 independent review (2026-09-14, row 2) ran ``python -m arrayprobe
--help`` and got ``No module named arrayprobe.__main__``: the console script
worked, the form every Python user tries first did not. ``__main__.py`` now
delegates to ``cli.main``. These tests run it for real in a subprocess -- an
import of ``arrayprobe.__main__`` in-process would pass even if ``-m`` could
not find it -- and compare its help against two independent sides: the
parser's own ``format_help()`` (always available) and the installed console
script (when the environment has one; the ``dist`` CI job and every editable
install do).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import unittest
from pathlib import Path

import arrayprobe
from arrayprobe import cli

#: The ``src`` directory the tested ``arrayprobe`` was imported from. The
#: subprocess is pointed at it, so a worktree test does not silently exercise a
#: different checkout's package through the editable install.
_SRC = Path(arrayprobe.__file__).resolve().parent.parent


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_SRC)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    # argparse wraps help to the terminal width and (3.14+) may colour it;
    # pin both so the three sides format identically.
    env["COLUMNS"] = "100"
    env["NO_COLOR"] = "1"
    env.pop("FORCE_COLOR", None)
    return env


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, env=_env(),
                          timeout=120, check=False)


def _console_script() -> str | None:
    """The installed ``arrayprobe`` console script next to this interpreter.

    Looked up in the interpreter's own scripts directory first, so a stray
    ``arrayprobe`` elsewhere on PATH is never the thing compared.
    """
    scripts = Path(sysconfig.get_path("scripts"))
    for name in ("arrayprobe.exe", "arrayprobe"):
        if (scripts / name).is_file():
            return str(scripts / name)
    return shutil.which("arrayprobe")


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


class PythonDashMArrayprobe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dash_m = _run([sys.executable, "-m", "arrayprobe", "--help"])

    def test_python_dash_m_help_exits_zero(self):
        self.assertEqual(
            self.dash_m.returncode, 0,
            f"`python -m arrayprobe --help` failed:\n{self.dash_m.stderr}")
        self.assertNotIn("No module named", self.dash_m.stderr)

    def test_it_is_the_cli_parser_and_nothing_else(self):
        # Side one: the parser itself, formatted in-process at the same width, with the
        # maintainer subcommands left out of the listing exactly as ``cli.main`` leaves them.
        old = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = "100"
        try:
            expected = cli._hide_unlisted(cli.build_parser()).format_help()
        finally:
            if old is None:
                os.environ.pop("COLUMNS", None)
            else:
                os.environ["COLUMNS"] = old
        self.assertEqual(_normalise(self.dash_m.stdout), _normalise(expected))

    def test_it_equals_the_console_script_help(self):
        exe = _console_script()
        if exe is None:
            self.skipTest("no `arrayprobe` console script installed next to "
                          f"{sys.executable}; the parser-side test still ran")
        script = _run([exe, "--help"])
        self.assertEqual(script.returncode, 0, script.stderr)
        self.assertEqual(_normalise(self.dash_m.stdout), _normalise(script.stdout))

    def test_prog_name_is_arrayprobe_not_dunder_main(self):
        # argparse would print `usage: __main__.py` without cli's explicit prog;
        # the two front doors must introduce themselves by the same name.
        self.assertTrue(self.dash_m.stdout.lstrip().startswith("usage: arrayprobe"),
                        self.dash_m.stdout[:200])

    def test_a_subcommand_dispatches_through_dash_m(self):
        # --version goes through main() rather than stopping at the top-level
        # help, so this exercises the delegation, not only the parser.
        r = _run([sys.executable, "-m", "arrayprobe", "--version"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(arrayprobe.__version__, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
