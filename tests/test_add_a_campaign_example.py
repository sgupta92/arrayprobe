# SPDX-License-Identifier: BSD-3-Clause
"""The add-a-campaign page's worked example (its section 8) is re-run, not read.

Each fenced ``bash`` block in that section that starts with ``arrayprobe`` is
run as a CLI subprocess in a scratch copy of the tracked demo fixtures, and
the first line the command prints (or, for ``--out FILE``, the first line of
that file) must equal the first line of the ``text`` block that follows it on
the page, ignoring a leading ``[HH:MM:SS]`` stamp. A pasted output that drifts
from the command fails here; a re-paste from a fresh run fixes it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._slow import slow

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "44-add-a-campaign.md"
DATA = Path(__file__).resolve().parent / "data"
FIXTURES = (
    "demo_flight_v314_raw.2DS",
    "demo_flight_v35_aircraft.cdf",
    "demo_flight_v35_run.toml",
    "demo_flight_v35_sd.nc",
    "demo_flight_v35_sd.call",
)
STAMP = re.compile(r"^\[\d\d:\d\d:\d\d\] ")


def _section_8(text: str) -> str:
    start = text.index("## 8. Worked example")
    return text[start:]


def _pairs(section: str) -> list[tuple[str, str]]:
    """(command, expected first output line) for every bash block in order."""
    blocks = re.findall(r"```(\w+)\n(.*?)```", section, flags=re.S)
    out: list[tuple[str, str]] = []
    for i, (lang, body) in enumerate(blocks):
        if lang != "bash":
            continue
        cmd = body.strip()
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if nxt is None or nxt[0] != "text":
            continue
        out.append((cmd, nxt[1].splitlines()[0]))
    return out


def _run(cmd: str) -> str:
    """Run one page command as a real CLI subprocess and return its first line.

    A subprocess, not ``cli.main`` in-process: the preset line a run prints
    first is emitted before in-process stdout capture sees it, so capture
    through ``cli.main`` misses the first pasted line.
    The child imports the same tree this test runs from.
    """
    import arrayprobe
    argv = cmd.split()[1:]
    env = dict(os.environ)
    src = str(Path(arrayprobe.__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(
        [src] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    proc = subprocess.run(
        [sys.executable, "-m", "arrayprobe.cli", *argv],
        capture_output=True, text=True, env=env, cwd=os.getcwd(), timeout=600)
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
        if out.is_file():
            return out.read_text(encoding="utf-8").splitlines()[0]
    lines = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]
    return lines[0] if lines else ""


@slow
class TestWorkedExampleRuns(unittest.TestCase):
    def test_every_pasted_first_line_is_what_the_command_prints(self):
        section = _section_8(PAGE.read_text(encoding="utf-8"))
        pairs = _pairs(section)
        self.assertGreaterEqual(len(pairs), 5, "section 8 lost its command blocks")
        tmp = Path(tempfile.mkdtemp(prefix="add_campaign_"))
        cwd = os.getcwd()
        try:
            (tmp / "raw").mkdir()
            (tmp / "inv").mkdir()
            shutil.copy(DATA / FIXTURES[0], tmp / "raw")
            for name in FIXTURES[1:]:
                shutil.copy(DATA / name, tmp)
            toml = (tmp / "demo_flight_v35_run.toml").read_text(encoding="utf-8")
            (tmp / "run234.toml").write_text(
                toml.replace('stages = "234c"', 'stages = "234"')
                .replace("_decoded", "_decoded234"),
                encoding="utf-8")
            os.chdir(tmp)
            for cmd, expected in pairs:
                # The tools print the operating system's own path separator; the page
                # shows the POSIX one, so compare with separators folded.
                got = STAMP.sub("", _run(cmd)).replace("\\", "/")
                self.assertEqual(got, STAMP.sub("", expected).replace("\\", "/"), cmd)
        finally:
            os.chdir(cwd)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
