# SPDX-License-Identifier: BSD-3-Clause
"""The migration guides' code is executed, not proof-read.

``docs/28-migrating-from-uiops.md`` prints the whole chain as Python calls, and
``29-migrating-from-soda2.md`` prints a ``[soda2]`` run configuration. A reader copies both as
specifications, so both are lifted out of the Markdown and handed to the thing they claim to
drive -- the same rule ``test_publish_ready.TheConfigurationPagesExamplesAreExecuted`` applies to
the configuration page. The shell lines on these pages are already parsed by
``test_publish_ready.EveryDocumentedCommandParses``; this module covers what that one cannot:
Python blocks and a TOML block, run for real.

Everything runs in a **subprocess from an empty temporary directory**, for the reason the
configuration-page test gives: a cold interpreter is how a reader runs it, and no state leaks into
later tests. The pages live outside ``python_port/``, so in a source distribution they are absent
and this module skips, by name, rather than failing.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "docs"
UIOPS_GUIDE = PAGES / "28-migrating-from-uiops.md"
SODA2_GUIDE = PAGES / "29-migrating-from-soda2.md"
SODA2_FIXTURE = Path(__file__).resolve().parent / "data" / "soda2_spec_frame_fixture"
ENGINE_GUIDE = PAGES / "27-choosing-an-engine.md"

#: Every page whose ``python`` fences this module executes. A new guide page with Python in it
#: is added here, and ``test_every_python_fence_on_a_guide_page_is_executed`` keeps the list from
#: silently missing one of the pages it names.
EXECUTED_PAGES = (UIOPS_GUIDE, ENGINE_GUIDE)

_SKIP = unittest.skipUnless(
    PAGES.is_dir(), "Docs/_build/pages is not part of a source distribution is not distributed "
                    "with the package")


def _fences(text: str, tag: str) -> list[str]:
    return re.findall(rf"```{tag}\n(.*?)```", text, re.S)


def _run_python(code: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], cwd=cwd, capture_output=True,
                          text=True, timeout=600)


@_SKIP
class TheUiopsGuideRuns(unittest.TestCase):
    def test_the_python_chain_runs_from_an_empty_directory(self):
        blocks = _fences(UIOPS_GUIDE.read_text(encoding="utf-8"), "python")
        self.assertEqual(len(blocks), 1,
                         "expected one Python block on the UIOPS migration guide; if it grew a "
                         "second, decide whether they run together and say so here")
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_python(blocks[0], tmp)
            self.assertEqual(result.returncode, 0,
                             "the Python chain printed on 28-migrating-from-uiops.md does not "
                             "run:\n" + result.stderr[-3000:])
            # The block's own promise: each stage writes the file the next one reads, ending
            # in the combined product under combine_sizedist.m's naming.
            for name in ("base160101000000.H.nc", "base160101000000.tas.csv", "proc.H.nc",
                         "sd.H.nc", "base160101000000.combined.H.2DS.cdf"):
                self.assertTrue((Path(tmp) / name).is_file(), f"the chain wrote no {name}")

    def test_the_runner_reports_a_broken_block(self):
        """The mutation: the printed block without the combine opt-in must fail."""
        block = _fences(UIOPS_GUIDE.read_text(encoding="utf-8"), "python")[0]
        self.assertIn("borrowed_combine=True", block)
        with tempfile.TemporaryDirectory() as tmp:
            broken = block.replace("borrowed_combine=True", "borrowed_combine=False")
            result = _run_python(broken, tmp)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BorrowedCombineNotEnabled", result.stderr)


@_SKIP
class TheSoda2GuideConfigurationRuns(unittest.TestCase):
    def _config(self, tmp: str) -> Path:
        (block,) = [b for b in _fences(SODA2_GUIDE.read_text(encoding="utf-8"), "toml")
                    if "[soda2]" in b]
        fixture = str(SODA2_FIXTURE).replace("\\", "/")
        outdir = tmp.replace("\\", "/") + "/"
        text, n_fn = re.subn(r'(?m)^fn = ".*"$', f'fn = "{fixture}"', block)
        text, n_out = re.subn(r'(?m)^outdir = ".*"$', f'outdir = "{outdir}"', text)
        self.assertEqual((n_fn, n_out), (1, 1),
                         "the guide's [soda2] block no longer has one fn and one outdir line; "
                         "this check would be running something other than the printed table")
        path = Path(tmp) / "soda2.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_printed_table_drives_soda2_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            code = ("import sys; from arrayprobe import cli; "
                    f"sys.exit(cli.main(['soda2', 'run', {str(config)!r}]))")
            result = _run_python(code, tmp)
            self.assertEqual(result.returncode, 0,
                             "the [soda2] table printed on 29-migrating-from-soda2.md does not "
                             "run:\n" + result.stderr[-3000:])
            sidecars = list(Path(tmp).glob("*.pbp.call"))
            self.assertEqual(len(sidecars), 1, f"expected one .pbp.call, got {sidecars}")


USER_GUIDE = PAGES / "02-user-guide.md"


def _load_test_combine():
    """``test_combine._write_sd_fixture``, loaded by path (``tests/`` is not a package)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_combine_fixture_for_guide", Path(__file__).resolve().parent / "test_combine.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


@_SKIP
class TheUserGuideCombineLineRuns(unittest.TestCase):
    """02-user-guide.md's per-stage ``combine`` line, executed rather than only parsed (I1,
    2026-09-15). It printed ``--summary-time 064017`` for weeks: that parses, so
    ``test_publish_ready.EveryDocumentedCommandParses`` passed it, but ``combine_sizedist``
    slices the value as ``YY_MM_DD_HH_MM_SS`` and raises ``ValueError``.
    The sd input and the output path are swapped for a synthetic sd file and a temporary path;
    every other argument -- the flight date and the summary time -- is the page's own."""

    def _argv(self) -> list[str]:
        import shlex
        text = USER_GUIDE.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines()
                 if ln.startswith("python -m arrayprobe.cli combine ")]
        self.assertEqual(len(lines), 1, "expected one combine line on 02-user-guide.md")
        return shlex.split(lines[0])[3:]  # drop "python -m arrayprobe.cli"

    def _run(self, argv: list[str], tmp: Path) -> None:
        import numpy as np

        from arrayprobe import cli
        tc = _load_test_combine()
        sd = tmp / "sd.H.nc"
        times = np.array([64403.0, 64404.0, 64405.0])
        bin_mid = np.round(np.arange(0.005, 0.085, 0.01), 6)
        B, T = len(bin_mid), len(times)
        tc._write_sd_fixture(sd, times, bin_mid, conc_minR=np.ones((B, T)),
                             conc_AreaR=np.ones((B, T)), n=np.ones(T),
                             reject_ratio=np.zeros(T), count=np.ones((B, T)),
                             mean_area_ratio=np.ones((B, T)))
        self.assertEqual(argv[0], "combine")
        options = argv[argv.index("--flight-date"):]
        out = tmp / argv[argv.index("--flight-date") - 1]
        self.assertEqual(cli.main(["combine", str(sd), str(out), *options]), 0)
        self.assertTrue(out.is_file())

    def test_the_printed_combine_line_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(self._argv(), Path(tmp))

    def test_the_old_summary_time_is_refused(self):
        """The mutation: the value the page used to print must fail through the same runner."""
        argv = self._argv()
        argv[argv.index("--summary-time") + 1] = "064017"
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            self._run(argv, Path(tmp))


@_SKIP
class TheEngineGuideRuns(unittest.TestCase):
    """27-choosing-an-engine.md prints the project-level selector as a Python block; a reader
    copies it as the way to pick an engine, so it is run, not proof-read (added 2026-09-23 when
    the page's fence was found unexecuted by the check below)."""

    def test_the_selector_block_runs_from_an_empty_directory(self):
        blocks = _fences(ENGINE_GUIDE.read_text(encoding="utf-8"), "python")
        self.assertEqual(len(blocks), 1,
                         "expected one Python block on 27-choosing-an-engine.md; if it grew a "
                         "second, decide whether they run together and say so here")
        # The block's own promise, read back: each line binds an engine whose name is the one
        # its comment claims (default v3.5, then SODA-2).
        code = blocks[0] + "\nprint(arrayprobe.engine().name, eng.name)\n"
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_python(code, tmp)
        self.assertEqual(result.returncode, 0,
                         "the Python block printed on 27-choosing-an-engine.md does not run:\n"
                         + result.stderr[-3000:])
        self.assertEqual(result.stdout.split(), ["3.5", "soda2"])

    def test_the_runner_reports_an_unknown_engine(self):
        """The mutation: a selector call the project does not ship must fail through the
        same runner."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_python("import arrayprobe\narrayprobe.engine('9.9')\n", tmp)
        self.assertNotEqual(result.returncode, 0)


@_SKIP
class NoGuideSnippetIsSkipped(unittest.TestCase):
    def test_every_python_fence_on_a_guide_page_is_executed(self):
        """The two guide pages and the three explanation pages written with them: any Python
        fence on one of them is either executed above or a failure here, so a snippet added
        later cannot ship unexecuted."""
        guides = sorted(PAGES.glob("2[5-9]-*.md"))
        self.assertGreaterEqual(len(guides), 5, "the guide pages moved; update this glob")
        unexecuted = [p.name for p in guides
                      if _fences(p.read_text(encoding="utf-8"), "python")
                      and p not in EXECUTED_PAGES]
        self.assertEqual(unexecuted, [],
                         "these guide pages print Python that no test runs; add them to "
                         "EXECUTED_PAGES with a test that executes the block")


if __name__ == "__main__":
    unittest.main()
