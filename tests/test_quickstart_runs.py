# SPDX-License-Identifier: BSD-3-Clause
"""The published quickstart runs, verbatim, from a clean directory.

**Why this is not covered by ``test_make_demo_flight.py`` or ``test_end_to_end.py``.**
Both exercise the tool's own CLI or its builder function directly; neither reads the
commands a stranger following `docs/02-user-guide.md`'s "Quickstart"
section would actually type, or notices if that section drifts from what the tools
now accept -- the exact failure `test_paper_numbers.py`'s own commentary elsewhere
in this project calls out about hand-copied code blocks going stale silently. This
test extracts the fenced ``bash`` block from the published section and runs it for
real, the way a fresh clone would, so the doc page cannot go stale without failing
the suite.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import numpy as np
from tests._repo import PKG_ROOT, repo_only  # noqa: E402
from tests._slow import slow

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "02-user-guide.md"
#: Where the quickstart runs: the repository root (the directory `cd arrayprobe` enters).
PYTHON_PORT = PKG_ROOT
#: Where the quickstart writes: inside the repository, in `examples/start_here/output`.
OUTPUT = PYTHON_PORT / "examples" / "start_here" / "output"

_SECTION = re.compile(
    r"## Quickstart — no campaign data required\n(.*?)\n## ", re.S)
_FENCED = re.compile(r"```bash\n(.*?)```", re.S)


def _quickstart_commands() -> list[str]:
    """The commands inside the Quickstart section's own fenced block, in order."""
    text = PAGE.read_text(encoding="utf-8")
    section = _SECTION.search(text)
    assert section is not None, "Quickstart section not found in 02-user-guide.md"
    block = _FENCED.search(section.group(1))
    assert block is not None, "Quickstart section has no fenced bash block"
    # A `#` line in the block is a note to the reader (the page's own "on Linux / macOS use
    # .venv/bin/python"), not a command. It was counted as one until 2026-09-17, which made this
    # test fail on a comment nobody had run -- and because the test is @slow it is gated out of
    # the default suite, so it failed unseen rather than at the commit that added the comment.
    lines = [ln.strip() for ln in block.group(1).splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    assert lines and lines[0].startswith("cd arrayprobe"), (
        "the quickstart is documented from the repo root (`cd arrayprobe`); first line changed")
    return lines[1:]


def _quickstart_python_commands() -> list[list[str]]:
    """The block's interpreter lines, split; the `mkdir` line is run by the test itself."""
    commands = _quickstart_commands()
    assert commands[0].split()[0] == "mkdir", commands
    return [c.split() for c in commands[1:]]


def _shipped_readme() -> Path:
    """The README that ships: the release builder publishes the dev tree's
    ``docs/developer/PACKAGE_README.md`` as the public tree's ``README.md``."""
    dev = ROOT / "docs" / "developer" / "PACKAGE_README.md"
    return dev if dev.is_file() else ROOT / "README.md"


README = _shipped_readme()
PYPROJECT = PYTHON_PORT / "pyproject.toml"


def _section(title: str) -> str:
    """One ``## `` section of the shipped README, up to the next ``## `` heading."""
    text = README.read_text(encoding="utf-8").replace("\r\n", "\n")
    sec = text[text.index(f"\n{title}\n"):]
    end = sec.find("\n## ", 1)
    return sec if end < 0 else sec[:end]


def _readme_quickstart() -> list[list[str]]:
    """The Quickstart's bash block, one split command per line."""
    sec = _section("## Quickstart")
    block = sec[sec.index("```bash\n") + 8:]
    block = block[:block.index("```")]
    return [ln.split() for ln in block.splitlines() if ln.strip()]


def _readme_v35_first_run() -> list[str]:
    """The README's first v3.5 run: the Quickstart's ``arrayprobe run`` line, split."""
    runs = [c for c in _readme_quickstart() if c[1:2] == ["run"]]
    assert len(runs) == 1, f"expected one README Quickstart `run` command, found {runs}"
    return runs[0]


def _readme_make_demo() -> list[str]:
    """The Quickstart's ``make-demo-flight`` line, split."""
    makes = [c for c in _readme_quickstart() if c[1:2] == ["make-demo-flight"]]
    assert len(makes) == 1, f"expected one README Quickstart make-demo-flight, found {makes}"
    return makes[0]


def _declared_python_floor() -> str:
    m = re.search(r'^requires-python\s*=\s*">=\s*(\d+\.\d+)"',
                  PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert m is not None, "pyproject.toml declares no requires-python floor"
    return m.group(1)


class TheReadmeInstallAndFirstRunAreRunnableAsWritten(unittest.TestCase):
    """README.md's install block and first v3.5 run, read as a stranger reads them.

    A Linux walk of the README word for word (2026-09-26) failed twice. ``python3 -m venv``
    took the system's 3.11 and pip died on the numpy pin with an error that never names the
    Python version, because the floor was stated only after the command. And the one v3.5
    command the README gave used a bare ``arrayprobe`` (not on PATH: the install never
    activates the venv) with a TOML path relative to the repository root, while the install
    block leaves the reader in the repository root. The quickstart test below could not see
    either: it reads the user guide, not the README.

    The shipped README is now PyPI-first (``pip install arrayprobe``, then a Quickstart run
    from an empty folder); the clone venv lines live under "## Test (from a clone)". The
    tests read that page (``_shipped_readme``) and keep both lessons: the floor is named
    before any command it governs, and the first run works exactly as written.
    """

    @repo_only
    def test_the_floor_is_stated_before_the_install_command(self):
        floor = _declared_python_floor()
        install = _section("## Install")
        self.assertIn(f"Python {floor} or newer", install[:install.index("```")],
                      "README must state the Python floor before the install command it governs")

    @repo_only
    def test_the_posix_venv_is_made_from_a_named_interpreter_at_the_floor(self):
        floor = _declared_python_floor()
        clone = _section("## Test (from a clone)")
        block = clone[clone.index("```") + 3:]
        block = block[:block.index("```")]
        venv_lines = [ln for ln in block.splitlines() if "-m venv" in ln and "bin/python" in ln]
        self.assertEqual(len(venv_lines), 1, block)
        self.assertTrue(venv_lines[0].startswith(f"python{floor} -m venv"),
                        f"bare `python3` may be older than {floor} (it was 3.11 in the walk): "
                        f"{venv_lines[0]!r}")

    # Replaces "calls the venv interpreter": after `pip install arrayprobe` the console
    # script is on PATH, so the runnable form is the installed `arrayprobe` command.
    @repo_only
    def test_the_v35_first_run_calls_the_installed_console_script(self):
        args = _readme_v35_first_run()
        self.assertEqual(args[:2], ["arrayprobe", "run"],
                         f"the first run must use the console script `pip install` puts on "
                         f"PATH: {args}")
        make = _readme_make_demo()
        self.assertEqual(make[0], "arrayprobe", make)

    # Replaces "paths resolve from the repository root": the Quickstart runs from an empty
    # folder, so every path the run names must be one the make-demo-flight line creates.
    @repo_only
    def test_the_v35_first_run_paths_are_made_by_the_preceding_line(self):
        commands = _readme_quickstart()
        make, run = _readme_make_demo(), _readme_v35_first_run()
        self.assertLess(commands.index(make), commands.index(run),
                        "make-demo-flight must come before the run that reads its output")
        paths = [a for a in run[2:] if not a.startswith("-")]
        self.assertEqual(len(paths), 2, f"expected `arrayprobe run <toml> <raw>`: {run}")
        toml, raw = paths
        self.assertIn("--with-config", make, "the demo TOML is written only with --with-config")
        made_raw = make[-1]
        self.assertEqual(raw, made_raw,
                         "the README's raw file must be the one make-demo-flight builds")
        self.assertEqual(Path(toml), Path(made_raw).parent / "run.toml",
                         "--with-config writes run.toml beside the raw file, nowhere else")


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    """One documented command, with this process's interpreter for the venv's."""
    assert cmd[0] in (".venv/Scripts/python.exe", ".venv/bin/python.exe", ".venv/bin/python"), cmd
    result = subprocess.run([sys.executable, *cmd[1:]], cwd=PYTHON_PORT, capture_output=True,
                            text=True, timeout=timeout)
    assert result.returncode == 0, (
        f"{cmd!r} failed:\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


class _CleanOutput:
    """Run from an empty ``examples/start_here/output``; put a reader's folder back after.

    A folder left by an earlier run is moved aside, not run into: the driver resumes from the
    stage outputs it finds, so a stale ``sd``/combined file there was read back as this run's
    product (228 used-bin counts against the page's 48, measured 2026-10-16)."""

    def __enter__(self):
        self.aside = OUTPUT.with_name(f"output.quickstart-test-aside-{uuid.uuid4().hex[:8]}")
        self.had = OUTPUT.is_dir()
        if self.had:
            OUTPUT.rename(self.aside)
        OUTPUT.mkdir()
        return self

    def __exit__(self, *exc):
        if OUTPUT.is_dir():
            for path in sorted(OUTPUT.rglob("*"), key=lambda q: len(q.parts), reverse=True):
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
            OUTPUT.rmdir()
        if self.had:
            self.aside.rename(OUTPUT)


@slow  # real subprocess CLI commands (2026-09-14: ~4.6s measured)
@repo_only
class TheQuickstartRunsVerbatim(unittest.TestCase):
    def test_every_command_runs_and_the_combined_product_lands_in_the_output_folder(self):
        # The block: make the folder, build the demo (raw + aircraft file), run the TOML.
        # The `mkdir` line is done by the clean-output context (it must not collide with a
        # reader's own folder); the two interpreter lines are run as written.
        commands = _quickstart_commands()
        self.assertEqual(len(commands), 3, commands)
        self.assertEqual(commands[0],
                         "mkdir -p examples/start_here/output     # Linux, macOS, PowerShell "
                         "(re-runnable); in Windows cmd: if not exist examples\\start_here\\output "
                         "mkdir examples\\start_here\\output")
        self.assertIn("make-demo-flight", commands[1])
        self.assertTrue((PYTHON_PORT / "examples/start_here/run.toml").is_file())
        self.assertIn("examples/start_here/run.toml", commands[2])
        for cmd in commands[1:]:
            self.assertNotIn("../", cmd, "the quickstart must not write above the repository")
            self.assertNotIn("3.1.4", cmd, "the public release ships no v3.1.4 engine")
        import netCDF4
        # The page publishes the used-bin total for this very run; read it from the page, so a
        # changed count fails here rather than going stale in prose.
        page = PAGE.read_text(encoding="utf-8")
        m35 = re.search(r"engine 3\.5 counts \*\*(\d+) into used bins\*\*", page)
        self.assertIsNotNone(m35, "the page no longer publishes the 3.5 total")
        from arrayprobe.tools.make_demo_flight import DENSE_MEASURED_COUNTED_V35
        self.assertEqual(int(m35.group(1)), DENSE_MEASURED_COUNTED_V35)
        with _CleanOutput():
            result = None
            for cmd in _quickstart_python_commands():
                result = _run(cmd)
            self.assertIn("ALL DONE", result.stdout)
            # The product's name is read from the page, so the page and the driver's naming
            # are the two sides: engine 3.5 writes no `_2` (only a v3.1.4 run does), and this
            # literal said `_2` for a month after the rename because the test is @slow.
            named = re.search(r"the final\s+product is `examples/start_here/output/([^`]+)`", page)
            self.assertIsNotNone(named, "the page no longer names the final product")
            combined = OUTPUT / named.group(1)
            self.assertNotIn("_2.cdf", combined.name, "engine 3.5 products carry no `_2`")
            self.assertTrue(combined.is_file(), f"quickstart did not write {combined}")
            # rc==0, "ALL DONE" and the file existing are what a stranger saw on 2026-09-16
            # when the product was 99.72 % NaN with nothing having said so; assert the floor:
            # the page's count of particles reached a used bin.
            with netCDF4.Dataset(combined) as ds:
                ds.set_auto_mask(False)
                counts = np.asarray(ds.variables["Counts"][:], dtype="float64")
            self.assertEqual(int(np.nansum(counts)), int(m35.group(1)),
                             "the page's used-bin total is stale")

    # Replaces "runs from the repository root": the Quickstart runs from an empty folder.
    def test_the_readme_v35_first_run_runs_from_an_empty_folder(self):
        """The README's two Quickstart lines, verbatim bar ``arrayprobe`` -> this
        interpreter's ``-m arrayprobe``, run in a fresh empty directory."""
        import tempfile
        with tempfile.TemporaryDirectory() as empty:
            result = None
            for cmd in (_readme_make_demo(), _readme_v35_first_run()):
                assert cmd[0] == "arrayprobe", cmd
                result = subprocess.run([sys.executable, "-m", "arrayprobe", *cmd[1:]],
                                        cwd=empty, capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0,
                                 f"{cmd!r} failed:\nstdout={result.stdout}\n"
                                 f"stderr={result.stderr}")
            self.assertIn("ALL DONE", result.stdout)


if __name__ == "__main__":
    unittest.main()
