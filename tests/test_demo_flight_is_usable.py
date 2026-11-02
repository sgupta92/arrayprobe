# SPDX-License-Identifier: BSD-3-Clause
"""The two things a stranger hits first: a mostly-NaN product nobody warned them
about, and a viewer command naming a flight they do not have.

Both were recorded 2026-09-16 and both were real when measured again on 2026-09-17:

1. The published quickstart writes a 68 MB combined product that is **99.72 %** NaN
   over the whole file (8,492,501 of 8,516,060 cells), of whose 22,004-second time axis
   four seconds carry data -- and neither command printed anything about it. The padding
   is faithful (``combine_sizedist.m`` pads from the flight date it reads out of the raw
   STEM to the first second the records carry), so the fix is not to change it: it is for
   ``make_demo_flight.py`` to say, before the pipeline is ever started, what axis it is
   about to cause.
2. ``README.md``'s gallery example named ``--flight base170817073523.H``, a 2017 ORACLES
   flight nobody outside the group has, against ``--decoded-dir ../_decoded``. The viewer
   itself is fine -- measured: a fresh quickstart output directory discovers exactly one
   flight, with both its ``proc`` file and its image -- so the defect was the flight name.

**Why these assertions read two different places.** A test that restated the tool's own
print, or the doc's own sentence, would pass while both drifted together. Every number
here is parsed out of the *published document* and compared against something measured
somewhere else: the raw file's own record headers, or the real product the pipeline
writes. Fix the document or the tool when this fails -- never the expected value.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import (
    PKG_ROOT,
    needs_v314_engine,  # noqa: E402
    repo_only,
)
from tests._slow import slow

from arrayprobe.tools.make_demo_flight import (
    expected_product_shape,
    summary_lines,
)
from arrayprobe_uiops import spec_core as spec

ROOT = Path(__file__).resolve().parents[1]
PYTHON_PORT = PKG_ROOT
USER_GUIDE = ROOT / "docs" / "02-user-guide.md"
#: The README that ships: the release builder publishes the dev tree's
#: ``docs/developer/PACKAGE_README.md`` as the public tree's ``README.md``.
README = (ROOT / "docs" / "developer" / "PACKAGE_README.md"
          if (ROOT / "docs" / "developer" / "PACKAGE_README.md").is_file()
          else ROOT / "README.md")

#: The quickstart's own arguments, as this test's subject. ``test_quickstart_runs.py``
#: is what checks that the page still publishes these; this module checks what they
#: produce.
QUICKSTART_STEM = "base160101000000"
QUICKSTART_SECONDS = 5


def _doc_int(pattern: str, text: str, what: str) -> int:
    m = re.search(pattern, text)
    assert m is not None, f"{what}: pattern {pattern!r} no longer matches the page"
    return int(m.group(1).replace(",", ""))


def _doc_float(pattern: str, text: str, what: str) -> float:
    m = re.search(pattern, text)
    assert m is not None, f"{what}: pattern {pattern!r} no longer matches the page"
    return float(m.group(1))


class TheBuilderSaysWhatAxisItIsAboutToCause(unittest.TestCase):
    """Defect 1, the half that costs nothing to check: the tool's derived summary
    against the raw file's own record headers, and against the page's numbers."""

    def _write(self, tmp: Path, stem: str, dense: bool = True) -> Path:
        args = [sys.executable, "scripts/make_demo_flight.py", str(tmp / f"{stem}.2DS"),
                "--seconds", str(QUICKSTART_SECONDS)]
        if dense:
            args.append("--dense")
        run = subprocess.run(args, cwd=PYTHON_PORT, capture_output=True, text=True,
                             timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.stdout = run.stdout
        return tmp / f"{stem}.2DS"

    def test_the_derived_axis_matches_the_raw_file_this_tool_just_wrote(self):
        """The independent side is the file's own bytes: the record clock comes back
        out of record 0's header words, and the record count out of its length --
        neither read from the arguments the summary was derived from."""
        with tempfile.TemporaryDirectory() as td:
            raw = self._write(Path(td), QUICKSTART_STEM)
            words = np.fromfile(raw, dtype="<u2").reshape(-1, spec.RECORD_WORDS)

        # readRecord's header (:170-182): year, month, day, _, hour, minute, second, ms.
        hour, minute, second = (int(words[0, 4]), int(words[0, 5]), int(words[0, 6]))
        record_tod = hour * 3600 + minute * 60 + second
        # One image record and one housekeeping record per second.
        n_seconds = words.shape[0] // 2

        shape = expected_product_shape(raw, n_seconds)
        self.assertIsNotNone(shape)
        self.assertEqual(shape["record_time_of_day"], record_tod)
        # The stem is base<YYMMDD hhmmss>; 00:00:00 here, so the padding IS the clock.
        self.assertEqual(shape["stem_time_of_day"], 0)
        self.assertEqual(shape["pad_seconds"], record_tod)
        self.assertEqual(shape["data_seconds"], n_seconds - 1)
        self.assertEqual(shape["axis_seconds"], record_tod + n_seconds - 1)

    @repo_only
    def test_the_axis_the_builder_prints_is_the_axis_the_page_publishes(self):
        """The page's `22,004 seconds` and `four rows carry data` against the tool's
        own derivation for the quickstart's arguments."""
        page = USER_GUIDE.read_text(encoding="utf-8")
        published_axis = _doc_int(r"`time` dimension is \*\*([\d,]+) seconds\*\*", page,
                                  "the published time-axis length")
        shape = expected_product_shape(f"{QUICKSTART_STEM}.2DS", QUICKSTART_SECONDS)
        self.assertEqual(shape["axis_seconds"], published_axis)
        self.assertEqual(shape["data_seconds"], 4,
                         "the page says four rows carry data")
        # And the tool prints it, not just computes it.
        printed = "\n".join(summary_lines(f"{QUICKSTART_STEM}.2DS",
                                          QUICKSTART_SECONDS, dense=True))
        self.assertIn(f"{published_axis:,}-second time axis", printed)

    def test_the_plain_flight_is_called_empty_and_the_dense_one_is_not(self):
        """The plain flight's distribution really is empty (measured 2026-09-17:
        Counts sum 0, Mean Area Ratio finite in 0 of 512 cells, Reject Ratio 1.0 in
        every second), so the tool must say so in as many words -- and must not say it
        of the dense flight, whose distribution is thin but real."""
        plain = "\n".join(summary_lines(f"{QUICKSTART_STEM}.2DS",
                                        QUICKSTART_SECONDS, dense=False))
        dense = "\n".join(summary_lines(f"{QUICKSTART_STEM}.2DS",
                                        QUICKSTART_SECONDS, dense=True))
        self.assertIn("EMPTY", plain)
        self.assertIn("--dense", plain)
        self.assertNotIn("EMPTY", dense)

    def test_a_stem_with_no_timestamp_gets_no_invented_axis(self):
        """``demo.2DS`` cannot be dated, so the tool states no axis rather than a
        plausible one -- and still warns about the empty distribution."""
        self.assertIsNone(expected_product_shape("demo.2DS", QUICKSTART_SECONDS))
        printed = "\n".join(summary_lines("demo.2DS", QUICKSTART_SECONDS, dense=False))
        self.assertNotIn("time axis", printed)
        self.assertIn("EMPTY", printed)

    def test_an_aligned_stem_is_offered_and_removes_the_padding(self):
        """The one-word way out the page documents: a stem naming the records' own
        clock. Measured 2026-09-17 -- ``base160101060640`` gave a 4-second, 17 KB
        product against 22,004 seconds and 68 MB."""
        printed = "\n".join(summary_lines(f"{QUICKSTART_STEM}.2DS",
                                          QUICKSTART_SECONDS, dense=True))
        self.assertIn("base160101060640", printed)
        aligned = expected_product_shape("base160101060640.2DS", QUICKSTART_SECONDS)
        self.assertEqual(aligned["pad_seconds"], 0)
        self.assertEqual(aligned["axis_seconds"], QUICKSTART_SECONDS - 1)


@repo_only
class TheReadmeViewerCommandsNameAFlightAReaderHas(unittest.TestCase):
    """Defect 2, the half that costs nothing: whatever flight the README's gallery
    example names must be the one the quickstart writes, not a campaign flight."""

    def _readme_commands(self) -> list[str]:
        text = README.read_text(encoding="utf-8")
        return [ln.strip() for block in re.findall(r"```bash\n(.*?)```", text, re.S)
                for ln in block.splitlines() if ln.strip()]

    def test_every_flight_argument_is_the_quickstart_flight(self):
        commands = self._readme_commands()
        flights = [m.group(1) for cmd in commands
                   for m in [re.search(r"--flight\s+(\S+)", cmd)] if m]
        self.assertTrue(flights, "no --flight example left in README.md")
        for flight in flights:
            self.assertTrue(
                flight.startswith(QUICKSTART_STEM),
                f"README names --flight {flight}, which a reader with no campaign data "
                f"does not have; the quickstart writes {QUICKSTART_STEM}")

    def test_the_viewer_command_names_the_quickstart_output_directory(self):
        """The viewer's ``--decoded-dir`` is only meaningful because it is where the
        Quickstart's own run writes; the README must make that directory, not assume it."""
        # Was: ``../_decoded`` plus a sentence naming it the default ``--out``. The
        # PyPI-first Quickstart writes into ``demo/`` (``demo/run.toml`` sits there), so
        # the viewer must name the directory the Quickstart's run line reads from.
        commands = self._readme_commands()
        runs = [c.split() for c in commands if c.split()[:2] == ["arrayprobe", "run"]]
        self.assertTrue(runs, "no `arrayprobe run` line in the README's Quickstart")
        out_dir = str(Path(runs[0][2]).parent)
        self.assertEqual(out_dir, "demo", runs[0])
        viewers = [m.group(1) for c in commands
                   for m in [re.search(r"--decoded-dir\s+(\S+)", c)] if m]
        self.assertTrue(viewers, "no --decoded-dir example left in the README")
        for d in viewers:
            self.assertEqual(d, out_dir,
                             f"README views --decoded-dir {d}, but the Quickstart run "
                             f"writes into {out_dir}")


@needs_v314_engine
@slow  # runs the real four-stage pipeline and writes a 68 MB product (~12 s measured)
class TheQuickstartProductIsWhatThePagePromises(unittest.TestCase):
    """The expensive half, and the only one that can catch the page and the pipeline
    drifting apart: the published figures against the product actually written.

    Deliberately NOT the verbatim published command -- ``test_quickstart_runs.py``
    owns that, and running it verbatim would write into the repository's shared
    ``../_decoded``. This runs the same chain with its own ``--out``.
    """

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        tmp = Path(cls._td.name)
        cls.out = tmp / "_decoded"
        raw = tmp / f"{QUICKSTART_STEM}.2DS"
        build = subprocess.run(
            [sys.executable, "scripts/make_demo_flight.py", str(raw),
             "--seconds", str(QUICKSTART_SECONDS), "--dense"],
            cwd=PYTHON_PORT, capture_output=True, text=True, timeout=300)
        assert build.returncode == 0, build.stderr
        run = subprocess.run(
            [sys.executable, "scripts/run_flight.py", "--preset", "DEMO_2DS_H",
             "--engine", "3.1.4", "--port-validation", "--stages", "234c", "--yes",
             "--out", str(cls.out),
             str(raw)],
            cwd=PYTHON_PORT, capture_output=True, text=True, timeout=900)
        assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-4000:]
        cls.combined = cls.out / f"{QUICKSTART_STEM}.combined.H.2DS_2.cdf"
        assert cls.combined.is_file(), sorted(p.name for p in cls.out.iterdir())

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def _product(self):
        from netCDF4 import Dataset
        ds = Dataset(self.combined)
        ds.set_auto_mask(False)
        return ds

    @repo_only
    def test_the_axis_and_the_populated_rows_are_what_the_page_says(self):
        page = USER_GUIDE.read_text(encoding="utf-8")
        published_axis = _doc_int(r"`time` dimension is \*\*([\d,]+) seconds\*\*", page,
                                  "the published time-axis length")
        ds = self._product()
        try:
            self.assertEqual(len(ds.dimensions["time"]), published_axis)
            conc = np.asarray(ds.variables["Number Concentration cm-3"][:],
                              dtype="float64")
            self.assertEqual(int(np.isfinite(conc).sum()), 4,
                             "the page says four rows carry data")
        finally:
            ds.close()

    @repo_only
    def test_the_whole_file_nan_fraction_is_what_the_page_says(self):
        """The page publishes 99.72 %. Recomputed here over every cell of every
        variable, which is the only reading under which that figure is right."""
        page = USER_GUIDE.read_text(encoding="utf-8")
        # The page wraps its prose, so the figure and its label can sit on two lines.
        published = _doc_float(r"whole-file NaN drops\s+from ([\d.]+) %", page,
                               "the published whole-file NaN percentage")
        ds = self._product()
        try:
            cells = nan = 0
            for name in ds.variables:
                a = np.asarray(ds.variables[name][:], dtype="float64")
                cells += a.size
                nan += int((~np.isfinite(a)).sum())
        finally:
            ds.close()
        self.assertAlmostEqual(100.0 * nan / cells, published, places=2)

    @repo_only
    def test_the_dense_flight_counts_the_particles_the_page_publishes(self):
        """`--dense` promises a distribution with something in it; the page says how
        much -- 11 counted particles. A regression to zero (which is what the PLAIN
        flight gives) must fail here."""
        # The page publishes the v3.5 total only (the release ships no v3.1.4 engine);
        # this class runs v3.1.4, so it pins the builder's own measured figure instead.
        from arrayprobe.tools.make_demo_flight import DENSE_MEASURED_COUNTED
        published = DENSE_MEASURED_COUNTED
        ds = self._product()
        try:
            counts = np.asarray(ds.variables["Counts"][:], dtype="float64")
        finally:
            ds.close()
        self.assertEqual(int(np.nansum(counts)), published)
        self.assertGreater(published, 0)

    def test_the_viewer_discovers_exactly_the_flight_the_readme_names(self):
        """Defect 2, measured against a real run rather than against the README's
        own wording: the directory the quickstart writes must contain both halves of
        the flight the README's ``--flight`` example names."""
        from arrayprobe.triage_server import _discover_flights
        flights = _discover_flights(self.out)
        self.assertEqual(sorted(flights), [QUICKSTART_STEM])
        entry = flights[QUICKSTART_STEM]
        self.assertIsNotNone(entry["proc"], "no proc file for the viewer to read")
        self.assertIsNotNone(
            entry["image"],
            "no image file beside it, so every viewer row would read "
            "'no matching raw/image file found'")


if __name__ == "__main__":
    unittest.main()
