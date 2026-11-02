# SPDX-License-Identifier: BSD-3-Clause
"""The newcomer's starting point is linked, consistent and runs.

``examples/1_getting_started/01_start_here.ipynb`` and ``examples/start_here/`` are the one place
a reader with
no Python or probe-processing background starts: raw file in, a first look at the output.
These tests hold the four things that make it a starting point rather than one more file:

* the root README links it within its first 40 lines, where a newcomer still reads;
* ``examples/README.md`` lists it as the first notebook;
* the command the notebook's "Step 2" shows is the command ``start_here/README.md`` gives,
  argument for argument, so the two routes cannot drift apart;
* ``start_here/run.toml`` processes the tracked dense demo flight
  (``tests/data/demo_flight_dense_raw.2DS``) and exits 0 -- measured at about 9 s, so the
  run is not behind the slow gate.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import repo_only

HERE = Path(__file__).resolve().parent
PORT = HERE.parent
ROOT = PORT
EXAMPLES = ROOT / "examples"
NOTEBOOK = EXAMPLES / "1_getting_started/01_start_here.ipynb"
START_HERE = EXAMPLES / "start_here"
TRACKED_RAW = HERE / "data" / "demo_flight_dense_raw.2DS"
LINK = "examples/1_getting_started/01_start_here.ipynb"
REPO_BLOB = "https://github.com/sgupta92/arrayprobe/blob/main/"
#: The public README is built from the PyPI description, whose links are pinned to the release tag
#: (tests/test_pypi_description_links_are_absolute.py). Spelled in parts so
#: tests/test_links_name_the_main_branch.py does not read the pattern as a link.
TAG_LINK = re.compile(re.escape("](https://github.com/sgupta92/" + "arrayprobe" + "/blob/v")
                      + r"\d+\.\d+\.\d+[^/)]*/" + re.escape(LINK + ")"))
STEM = "base160101000000"


def _fenced_lines(markdown: str) -> list[str]:
    """Every non-blank line inside a ``` fence, stripped."""
    lines: list[str] = []
    for block in re.findall(r"```[^\n]*\n(.*?)```", markdown, flags=re.S):
        lines.extend(line.strip() for line in block.splitlines() if line.strip())
    return lines


def _run_commands(markdown: str) -> list[list[str]]:
    """The ``arrayprobe run`` command lines in ``markdown``'s fences, split into argv."""
    return [shlex.split(line) for line in _fenced_lines(markdown) if "-m arrayprobe run " in line]


def _notebook_step2_markdown() -> str:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    for cell in cells:
        text = "".join(cell["source"])
        if cell["cell_type"] == "markdown" and text.lstrip().startswith("## Step 2"):
            return text
    raise AssertionError(f"{NOTEBOOK.name} has no markdown cell headed '## Step 2'")


@repo_only  # reads the repository-root README and examples/, not in the sdist
class StartHereIsLinked(unittest.TestCase):
    def test_root_readme_links_it_in_its_first_40_lines(self) -> None:
        # The shipped README links absolutely to this repository, so the link also works on PyPI.
        head = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:40]
        targets = (f"]({LINK})", f"]({REPO_BLOB}{LINK})")
        self.assertTrue(
            any(t in line for line in head for t in targets)
            or any(TAG_LINK.search(line) for line in head),
            f"README.md's first 40 lines carry no markdown link to {LINK}",
        )

    def test_examples_readme_lists_it_first(self) -> None:
        lines = (EXAMPLES / "README.md").read_text(encoding="utf-8").splitlines()
        separator = next(
            (i for i, line in enumerate(lines) if re.fullmatch(r"\|(\s*-+\s*\|)+", line.strip())),
            None,
        )
        self.assertIsNotNone(separator, "examples/README.md has no markdown table")
        first_row = lines[separator + 1]
        self.assertIn("(1_getting_started/01_start_here.ipynb)", first_row,
                      f"examples/README.md's first table row is not the start-here notebook: "
                      f"{first_row[:120]!r}")


@repo_only  # reads the repository-root README and examples/, not in the sdist
class StartHereRoutesAgree(unittest.TestCase):
    def test_notebook_step2_command_equals_start_here_readme_command(self) -> None:
        notebook = _run_commands(_notebook_step2_markdown())
        readme = _run_commands((START_HERE / "README.md").read_text(encoding="utf-8"))
        self.assertTrue(notebook, "the notebook's Step 2 shows no `arrayprobe run` command")
        self.assertEqual(notebook, readme,
                         "the notebook's Step 2 command and start_here/README.md's differ")

    def test_notebook_runs_the_command_it_shows(self) -> None:
        """The code cell after Step 2 passes the same arguments after ``-m arrayprobe``."""
        shown = _run_commands(_notebook_step2_markdown())[0]
        shown_args = shown[shown.index("arrayprobe") + 1:]
        expected = ["run", "examples/start_here/run.toml",
                    f"examples/start_here/output/{STEM}.2DS", "--yes"]
        self.assertEqual(shown_args, expected)
        cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
        code = "\n".join("".join(c["source"]) for c in cells if c["cell_type"] == "code")
        self.assertIn('"-m", "arrayprobe", "run", str(HERE / "run.toml"), str(RAW)', code)
        self.assertIn('HERE = Path("examples/start_here")', code)
        self.assertIn(f'RAW = OUT / "{STEM}.2DS"', code)


@repo_only  # reads the repository-root README and examples/, not in the sdist
class StartHereTomlRuns(unittest.TestCase):
    def test_run_toml_processes_the_tracked_dense_demo_flight(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(PORT / "src"), str(PORT), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            out = work / "output"
            out.mkdir()
            shutil.copy2(START_HERE / "run.toml", work / "run.toml")
            raw = out / f"{STEM}.2DS"
            # README step 2 writes the airspeed record the TOML names (tas_file); the raw
            # file it writes is then replaced by the tracked dense fixture.
            made = subprocess.run(
                [sys.executable, "-m", "arrayprobe", "make-demo-flight", "--dense", str(raw)],
                cwd=PORT, env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(made.returncode, 0, made.stderr[-2000:])
            self.assertTrue((out / f"{STEM}.aircraft.cdf").is_file())
            shutil.copy2(TRACKED_RAW, raw)
            done = subprocess.run(
                [sys.executable, "-m", "arrayprobe", "run", str(work / "run.toml"), str(raw),
                 "--yes"],
                cwd=PORT, env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0,
                             (done.stdout[-2000:] + "\n" + done.stderr[-2000:]))
            self.assertIn("ALL DONE", done.stdout)
            for name in (f"{STEM}.H.nc", f"proc.{STEM}.H.nc", f"sd.{STEM}.H.nc",
                         f"{STEM}.combined.H.2DS.cdf"):
                self.assertTrue((out / name).is_file(), f"the run did not write {name}")


if __name__ == "__main__":
    unittest.main()
