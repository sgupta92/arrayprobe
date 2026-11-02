# SPDX-License-Identifier: BSD-3-Clause
"""The published real-data tour runs, verbatim.

Same reasoning as ``test_quickstart_runs.py``: this extracts the fenced ``bash``
block from the "Real-data tour" section of ``docs/02-user-guide.md``
and runs it for real, against the actual vendored ``ImagefileExamplePECAN`` file,
so the section cannot go stale (a renamed CLI positional, a moved vendor path, a
drifted particle count) without failing the suite.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

from tests import _upstream  # noqa: E402
from tests._repo import PKG_ROOT, repo_only  # noqa: E402
from tests._slow import slow

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "02-user-guide.md"
PYTHON_PORT = PKG_ROOT
PECAN_RAW = (_upstream.source("uiops314")
             / "ImagefileExamplePECAN")

_SECTION = re.compile(
    r"## Real-data tour — a genuinely recorded flight, no campaign access "
    r"needed\n(.*?)\n## ", re.S)
_FENCED = re.compile(r"```bash\n(.*?)```", re.S)


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops314")


def _tour_commands(text: str | None = None) -> list[str]:
    if text is None:
        text = PAGE.read_text(encoding="utf-8")
    section = _SECTION.search(text)
    assert section is not None, "Real-data tour section not found in 02-user-guide.md"
    # The tour block is found by its own first line, not by being the FIRST
    # bash block in the section: on 2026-09-11 the section gained a preceding
    # `gh api ...` fetch block (the PECAN file is no longer redistributed), and
    # a positional search would have silently started running that instead.
    # Exactly one block may open with `cd arrayprobe`, so an ambiguity fails
    # closed rather than picking one.
    blocks = [[ln.strip() for ln in b.splitlines() if ln.strip()]
              for b in _FENCED.findall(section.group(1))]
    tours = [b for b in blocks if b and b[0].split("#")[0].strip() == "cd arrayprobe"]
    assert len(tours) == 1, (
        "the tour is documented from the repository root; expected exactly one "
        f"fenced bash block opening with `cd arrayprobe`, found {len(tours)} "
        f"among {len(blocks)} block(s)")
    return tours[0][1:]


@repo_only
@unittest.skipUnless(
    PECAN_RAW.is_file(),
    # Not "file missing" -- the file is DELIBERATELY untracked, so on a fresh
    # clone this skip is the normal state and not a broken checkout. Its
    # redistribution terms are undetermined (the vendored LICENSE is verbatim
    # GPLv3 with no data clause, and no README states the data's provenance),
    # so it was untracked on 2026-09-11 and is declared in
    # test_upstream_tree_is_unmodified.py's DELIBERATELY_UNTRACKED. A skip that
    # only says "not present" invites the reader to conclude the tour is
    # broken; the tour works, the input just has to be fetched.
    f"{PECAN_RAW.name} is deliberately untracked (undetermined redistribution "
    f"terms) -- fetch it with `gh api repos/joefinlon/UIOPS/tarball/v3.1.4` and "
    f"place it at {PECAN_RAW.as_posix()} to run the tour")
@slow  # real subprocess CLI commands against a real flight, when present
# (2026-09-14: 0.0s measured here because it skips -- no _decoded/ flight in
# this worktree -- but real subprocess cost when it runs)
class TheRealDataTourRunsVerbatim(unittest.TestCase):
    def test_the_decode_runs_and_reproduces_the_documented_count(self):
        commands = _tour_commands()
        self.assertEqual(len(commands), 1, commands)

        python = sys.executable
        decoded = PYTHON_PORT / "pecan.decoded.nc"
        try:
            for cmd in commands:
                args = cmd.split()
                assert args[0] in (".venv/Scripts/python.exe", ".venv/bin/python.exe",
                                    ".venv/bin/python")
                args[0] = python
                # 600, not 120. Until 2026-10-10 the tour also ran image processing, a real
                # 300-record PIP run and takes ~90 s on an idle machine --
                # which is under 120 until something else is using the cores.
                # It timed out three times on 2026-09-10 while a flight
                # regression held six workers, and a timeout here reads as
                # "the published tour is broken", which is a false alarm the
                # next reader has to spend time disproving. The number is a
                # guard against a hang, not a performance assertion; there is
                # no benefit to keeping it tight.
                result = subprocess.run(
                    args, cwd=PYTHON_PORT, capture_output=True, text=True,
                    timeout=600)
                self.assertEqual(
                    result.returncode, 0,
                    f"{cmd!r} failed:\nstdout={result.stdout}\nstderr={result.stderr}")

            self.assertIn("wrote pecan.decoded.nc (records: 300)", result.stdout)
            from netCDF4 import Dataset
            with Dataset(decoded) as ds:
                self.assertEqual(ds.dimensions["time"].size, 300)
        finally:
            # The driver stamps each output with a `.call` sidecar beside it; `*.nc` is
            # gitignored but `*.nc.call` is not, so leaving them shows as untracked files.
            for stray in (decoded, decoded.with_name(decoded.name + ".call")):
                # A timed-out child is killed but Windows can still hold the
                # handle for a moment, and an unlink that raises here REPLACES
                # the real failure with a PermissionError -- which is what the
                # 2026-09-10 timeout actually surfaced as, hiding its own
                # cause. Cleanup must not be able to do that.
                try:
                    stray.unlink(missing_ok=True)
                except OSError:
                    pass


@repo_only
class TheBlockFinderFailsClosed(unittest.TestCase):
    """The selector above replaced a positional one; make it fire.

    A guard that has never been made to fail is a guard nobody has executed.
    Both ways the anchor can rot are exercised here: the tour block gone, and
    the tour block no longer unique.
    """

    _HEAD = ("## Real-data tour — a genuinely recorded flight, no campaign "
             "access needed\n")
    _TOUR = "```bash\ncd arrayprobe   # the repository root\necho one\necho two\n```\n"
    _OTHER = "```bash\ngh api repos/joefinlon/UIOPS/tarball/v3.1.4\n```\n"

    def _page(self, *blocks: str) -> str:
        return self._HEAD + "".join(blocks) + "\n## Next section\n"

    def test_a_preceding_block_does_not_become_the_tour(self):
        self.assertEqual(
            _tour_commands(self._page(self._OTHER, self._TOUR)),
            ["echo one", "echo two"])

    def test_no_tour_block_is_an_error(self):
        with self.assertRaises(AssertionError):
            _tour_commands(self._page(self._OTHER))

    def test_two_tour_blocks_are_an_error(self):
        with self.assertRaises(AssertionError):
            _tour_commands(self._page(self._TOUR, self._TOUR))


if __name__ == "__main__":
    unittest.main()
