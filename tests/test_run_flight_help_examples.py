# SPDX-License-Identifier: BSD-3-Clause
"""The example commands in ``--help`` must be commands that actually work.

**Measured 2026-09-17, and this is why the test exists.** ``scripts/run_flight.py``'s module
docstring -- which is what ``--help`` prints, and therefore the first screen a new user reads --
carried three example invocations:

    .venv/Scripts/python.exe scripts/run_flight.py ../base160906*.2DS
    .venv/Scripts/python.exe scripts/run_flight.py --stages 23 ../base1609060*.2DS
    .venv/Scripts/python.exe scripts/run_flight.py --jobs 4 ../base*.2DS

**All three exited 2.** ``--preset`` became required on 2026-09-15 -- a deliberate and good change,
because a campaign is chosen by name or not at all -- and nothing connected that change to the
examples. They sat broken for two days on the most-read surface in the tool.

The failure shape is the one this project keeps meeting: a rule ("keep the examples current") that
lives only in someone's attention. So this is a control instead. It parses the invocations out of
the docstring and pushes each through the **real parser**, which means any future required flag,
renamed choice or removed option fails here rather than on a stranger's first run.

It deliberately does **not** execute the pipeline: argument acceptance is the claim being made, the
raw globs point at files no checkout has, and a flight run in a unit test would be its own defect.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("run_flight", run_flight)
_SPEC.loader.exec_module(run_flight)

#: An example invocation in the docstring: indented, invoking this script, and possibly continued
#: onto further lines with a trailing backslash the way a shell example normally is.
_EXAMPLE = re.compile(
    r"^\s+\S*python(?:\.exe)?\s+scripts/run_flight\.py\s+(.*(?:\\\n.*)*)$", re.M)


def _examples() -> list[str]:
    """Each example as one command string, continuations joined.

    Joining rather than requiring one long line: a wrapped shell example is the normal way to
    write one, and a test that forbade wrapping would push the docstring over the line-length
    limit the linter enforces -- two controls pulling against each other, with the documentation
    losing.
    """
    out = []
    for m in _EXAMPLE.finditer(run_flight.__doc__ or ""):
        out.append(" ".join(part.strip().rstrip("\\").strip()
                            for part in m.group(1).split("\n")))
    return out


class TheHelpExamplesParse(unittest.TestCase):
    def test_the_docstring_still_contains_examples(self):
        """An empty sweep passes every other assertion in this file vacuously."""
        self.assertGreaterEqual(
            len(_examples()), 3,
            "no example invocations found in run_flight's docstring -- either they were removed "
            "(then remove this test deliberately) or the pattern no longer matches them, in "
            "which case this file is checking nothing")

    def test_every_example_is_accepted_by_the_real_parser(self):
        """Run each example for real, in a subprocess, and assert it does not exit 2.

        Exit 2 is this driver's argument-and-configuration refusal; exit 1 is a run that was
        configured correctly and then found no files, which is what these globs produce in a
        checkout without campaign data and is the right outcome here. A subprocess rather than an
        in-process call because ``main()`` rebinds module globals (preset, profile, thresholds)
        that later tests in the same interpreter would inherit.
        """
        for src in _examples():
            argv = [a for a in shlex.split(src) if not a.endswith(".2DS")]
            with self.subTest(" ".join(argv)):
                r = subprocess.run(
                    [sys.executable, str(TOOLS / "run_flight.py"), *argv,
                     "--dry-run", "no-such-file.2DS"],
                    capture_output=True, text=True, timeout=180,
                    cwd=str(TOOLS.parent))
                self.assertNotEqual(
                    r.returncode, 2,
                    f"`run_flight.py {src}` exits 2 -- the help text is showing a command that "
                    f"does not work:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")

    def test_the_examples_name_a_preset_and_a_regime(self):
        """The two flags whose absence is silent rather than loud.

        ``--preset`` exits 2, which at least announces itself. ``--regime`` does not: a run that
        declares no threshold policy is gated and, with no terminal, refuses to start --
        so an example without it teaches a command that stops rather than runs.
        """
        for src in _examples():
            with self.subTest(src):
                self.assertIn("--preset", src)
                self.assertIn("--regime", src)


if __name__ == "__main__":
    unittest.main()
