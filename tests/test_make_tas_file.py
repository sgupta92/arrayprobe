# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe make-tas-file`` -- the aircraft file the v3.5 engine requires.

Built 2026-09-16 on the cold-start usability audit's finding 1.2: the default engine refuses to
run without an aircraft TAS file, and no public page stated what was in one. The auditor recovered
the schema by opening a tracked fixture with ``netCDF4``.

**The schema is checked against the engine, not against a document.** Every test below reads the
file back through the same call the port makes (``ncio.ncread(path, "TAS")`` /
``ncread(path, "Time")``, ``imgproc.py:531-532``), so a rename on either side fails here rather
than producing a file the engine silently cannot read. The last class runs the real v3.5 imgproc
stage on a file this tool wrote.
"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import ncio
from arrayprobe.tools import make_tas_file


class TheFileTheEngineReads(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def test_the_two_variables_are_named_and_typed_the_way_imgproc_reads_them(self):
        p = make_tas_file.write_tas_file(self.d / "a.cdf", [60638.0, 60639.0], [130.0, 131.0])
        # Exactly the two calls arrayprobe.imgproc makes, by the names it uses.
        np.testing.assert_allclose(np.asarray(ncio.ncread(p, "TAS"), dtype=float).ravel(),
                                   [130.0, 131.0])
        np.testing.assert_allclose(np.asarray(ncio.ncread(p, "Time"), dtype=float).ravel(),
                                   [60638.0, 60639.0])

    @needs_v314_engine
    def test_the_variable_names_are_the_ones_imgproc_asks_for(self):
        """Read off the port rather than repeated here, so the two sides differ."""
        src = (Path(make_tas_file.__file__).resolve().parents[1] / "imgproc.py").read_text()
        self.assertIn(f'ncread(tas_file, "{make_tas_file.TAS_VARIABLE}")', src)
        self.assertIn(f'ncread(tas_file, "{make_tas_file.TIME_VARIABLE}")', src)

    def test_it_matches_the_shipped_fixtures_shape(self):
        """``scripts/make_demo_reference.write_aircraft_v35`` writes the tracked v3.5 fixture;
        this tool must write the same shape or the documented schema is documenting one file
        and producing another."""
        import netCDF4
        fixture = Path(__file__).resolve().parent / "data" / "demo_flight_v35_aircraft.cdf"
        mine = make_tas_file.write_tas_file(self.d / "b.cdf", [60638.0], [130.0])
        with netCDF4.Dataset(fixture) as a, netCDF4.Dataset(mine) as b:
            self.assertEqual(set(a.variables), set(b.variables))
            for name in a.variables:
                self.assertEqual(a.variables[name].dtype, b.variables[name].dtype, name)
                self.assertEqual(a.variables[name].dimensions,
                                 b.variables[name].dimensions, name)

    def test_units_are_written_for_the_human_and_read_by_nobody(self):
        """The engine reads neither attribute (two bare ``ncread`` calls), so writing them
        changes no computed number -- but a user who opens the file should not have to guess
        that ``Time`` is HHMMSS."""
        import netCDF4
        p = make_tas_file.write_tas_file(self.d / "c.cdf", [60638.0], [130.0])
        with netCDF4.Dataset(p) as ds:
            self.assertEqual(ds.variables["Time"].units, "HHMMSS")
            self.assertEqual(ds.variables["TAS"].units, "m s-1")


class ItRefusesRatherThanGuesses(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(ValueError) as caught:
            make_tas_file.write_tas_file(self.d / "x.cdf", [1.0, 2.0], [130.0])
        self.assertIn("imgProc_sm.m:183-185", str(caught.exception))

    def test_an_empty_series_is_refused(self):
        with self.assertRaises(ValueError):
            make_tas_file.write_tas_file(self.d / "x.cdf", [], [])

    def test_a_constant_run_past_the_minute_is_refused_not_wrapped_wrongly(self):
        """HHMMSS does not carry by adding 1: 60659 + 1 would be 60660, not 60700. Writing
        that would put a time axis in the file that jumps, so it is refused instead."""
        with self.assertRaises(ValueError) as caught:
            make_tas_file.constant_tas(60650, 20, 130.0)
        self.assertIn("HHMMSS does not carry", str(caught.exception))

    def test_a_constant_inside_one_minute_is_fine(self):
        t, tas = make_tas_file.constant_tas(60638, 10, 130.0)
        np.testing.assert_allclose(t, np.arange(60638, 60648, dtype=float))
        self.assertEqual(set(np.unique(tas)), {130.0})

    def test_the_cli_needs_a_named_source_and_will_not_invent_one(self):
        with self.assertRaises(SystemExit):
            make_tas_file.main([str(self.d / "x.cdf")])
        with self.assertRaises(SystemExit):
            make_tas_file.main([str(self.d / "x.cdf"), "--constant-tas", "130"])


class FromTheDecodesOwnSidecar(unittest.TestCase):
    """The audit's own suggestion: the decode already writes ``<stem>.tas.csv``."""

    def test_the_first_two_columns_of_a_tas_csv_become_time_and_tas(self):
        d = Path(tempfile.mkdtemp())
        csv = d / "base160101000000.tas.csv"
        # A .tas.csv has nine columns; loadTASinfo_2DS.m's format string keeps the first two.
        csv.write_text("60638,130.5,0,0,0,0,0,0,0\n60639,131.5,0,0,0,0,0,0,0\n",
                       encoding="utf-8")
        t, tas = make_tas_file.tas_from_csv(csv)
        np.testing.assert_allclose(t, [60638.0, 60639.0])
        np.testing.assert_allclose(tas, [130.5, 131.5])
        p = make_tas_file.write_tas_file(d / "out.cdf", t, tas)
        np.testing.assert_allclose(np.asarray(ncio.ncread(p, "TAS"), dtype=float).ravel(),
                                   [130.5, 131.5])


class TheCliSubcommandAndTheToolAgree(unittest.TestCase):
    def test_make_tas_file_is_a_subcommand(self):
        from arrayprobe.cli import build_parser
        sub = build_parser()._subparsers._group_actions[0].choices
        self.assertIn("make-tas-file", sub)

    def test_the_subcommand_accepts_every_flag_the_tool_does(self):
        """The subcommand builds the tool's argv (``cli._make_tas_file``), so a flag added to
        one and not the other is a command that silently drops an option."""
        from arrayprobe.cli import build_parser
        sub = build_parser()._subparsers._group_actions[0].choices["make-tas-file"]
        cli_flags = {o for a in sub._actions for o in a.option_strings}
        tool_flags = {o for a in make_tas_file.build_parser()._actions
                      for o in a.option_strings} - {"-h", "--help"}
        self.assertTrue(tool_flags <= cli_flags, sorted(tool_flags - cli_flags))


# The rows 6430-6435 of base170821110122.tas.csv around 124838 verbatim in their
# first three columns; 124837 is absent and each 124838 duplicate equals a different neighbour.
_ROWS_124838 = """124834.999,139.899994,2232338652
124834.999,139.899994,2246328648
124835.999,139.399994,2260318657
124838.000,139.399994,2274258675
124838.000,138.899994,2288148680
124839.000,138.899994,2302038668
"""


def _csv(d: Path, text: str) -> Path:
    p = d / "base170821110122.tas.csv"
    p.write_text(text, encoding="utf-8")
    return p


def _run(argv) -> tuple[int, str]:
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = make_tas_file.main(argv)
    return rc, buf.getvalue()


class WriteTasFileFailsClosed(unittest.TestCase):
    """A2: the check that would have caught every ORACLES 2017 product running on 170 m/s."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def test_a_fractional_time_is_refused_citing_the_exact_match(self):
        with self.assertRaises(ValueError) as caught:
            make_tas_file.write_tas_file(self.d / "x.cdf", [124834.999, 124836.0], [1.0, 2.0])
        self.assertIn("imgProc_sm.m:727", str(caught.exception))
        self.assertIn("170 m/s", str(caught.exception))
        self.assertFalse((self.d / "x.cdf").exists())

    def test_a_repeated_time_is_refused_citing_the_matlab_failure(self):
        with self.assertRaises(ValueError) as caught:
            make_tas_file.write_tas_file(self.d / "x.cdf", [124838.0, 124838.0], [1.0, 2.0])
        self.assertIn("imgProc_sm.m:738", str(caught.exception))

    def test_a_non_finite_time_is_refused(self):
        with self.assertRaises(ValueError):
            make_tas_file.write_tas_file(self.d / "x.cdf", [np.nan, 124838.0], [1.0, 2.0])

    def test_a_whole_second_unique_series_is_accepted(self):
        p = make_tas_file.write_tas_file(self.d / "ok.cdf", [124838.0, 124839.0], [1.0, 2.0])
        self.assertTrue(p.exists())


class WholeSecondReductionI362(unittest.TestCase):
    """The author's rule on the function, both author choices exercised."""

    def _series(self, text):
        m = np.array([[float(x) for x in ln.split(",")[:2]] for ln in text.split()])
        return m[:, 0], m[:, 1]

    def test_the_defaults_are_the_authors_choices(self):
        self.assertEqual((make_tas_file.AUTHOR_SECOND_RULE,
                          make_tas_file.AUTHOR_NEIGHBOUR_RULE), ("round", "adjacent"))
        t, v = self._series(_ROWS_124838)
        a = make_tas_file.whole_second_series(t, v)
        b = make_tas_file.whole_second_series(t, v, second_rule="round", neighbour="adjacent")
        np.testing.assert_array_equal(a[0], b[0])
        np.testing.assert_array_equal(a[1], b[1])

    def test_an_out_of_range_row_falls_to_the_default_never_dropped(self):
        """The 163120 block of 110122: 119.9 beside 241403.0625. The row is set aside;
        a second with no in-range row takes the default -- the second is never dropped."""
        tt, vv, rep = make_tas_file.whole_second_series(
            [163119.0, 163120.0, 163120.0, 163121.0, 163122.0],
            [119.9, 119.9, 241403.0625, 119.9, 241403.0625])
        imp = [r for r in rep if r["class"] == "out-of-range"]
        self.assertEqual([(r["second"], r["remaining"], r["fallback"]) for r in imp],
                         [(163120, True, None), (163122, False, 170.0)])
        self.assertEqual(list(tt), [163119.0, 163120.0, 163121.0, 163122.0])
        self.assertEqual(list(vv), [119.9, 119.9, 119.9, 170.0])
        # 300 itself is kept; only above it is out of range.
        tt, _, rep = make_tas_file.whole_second_series([1.0], [300.0])
        self.assertEqual((list(tt), rep), ([1.0], []))

    def test_the_cutoff_and_the_default_are_options(self):
        pol = make_tas_file.TasPolicy(cutoff_mps=200.0, default_mps=150.0)
        tt, vv, _ = make_tas_file.whole_second_series([1.0, 2.0, 3.0], [250.0, -999.0, 199.0],
                                                      policy=pol)
        self.assertEqual(list(vv), [150.0, 150.0, 199.0])
        with self.assertRaises(ValueError):
            make_tas_file.TasPolicy(cutoff_mps=100.0, default_mps=170.0)

    @needs_v314_engine
    def test_the_documented_default_equals_the_engines_fallback(self):
        """Read from the engine and compared -- the builder never imports it."""
        from arrayprobe import imgproc
        self.assertEqual(make_tas_file.DEFAULT_FALLBACK_MPS, imgproc.TAS_FALLBACK)
        self.assertEqual(make_tas_file.TasPolicy(), make_tas_file.TasPolicy(300.0, 170.0))

    def test_identical_duplicates_collapse_and_are_reported(self):
        t, v = self._series(_ROWS_124838)
        _, _, rep = make_tas_file.whole_second_series(t, v, second_rule="floor",
                                                      neighbour="adjacent")
        r = next(r for r in rep if r["second"] == 124834)
        self.assertEqual((r["class"], r["kept"]), ("identical", 139.899994))

    def test_adjacent_neighbour_resolves_124838_to_the_matching_next_second(self):
        """s-1 = 124837 is absent; s+1 = 124839 is 138.9, which one candidate equals."""
        t, v = self._series(_ROWS_124838)
        for rule in make_tas_file.SECOND_RULES:
            tt, vv, rep = make_tas_file.whole_second_series(t, v, second_rule=rule,
                                                            neighbour="adjacent")
            r = next(r for r in rep if r["second"] == 124838)
            self.assertEqual((r["class"], r["kept"]), ("unambiguous", 138.899994), rule)
            self.assertTrue(r["prev_missing"])
            self.assertTrue(np.all(tt == np.floor(tt)), rule)
            self.assertEqual(np.unique(tt).size, tt.size, rule)
            self.assertEqual(vv[list(tt).index(124838.0)], 138.899994)

    def test_nearest_present_neighbour_leaves_124838_ambiguous(self):
        """The nearest present earlier second (124836 round / 124835 floor) is 139.4 and the
        next is 138.9: each candidate matches a different neighbour, so the rule picks none."""
        t, v = self._series(_ROWS_124838)
        for rule in make_tas_file.SECOND_RULES:
            tt, _, rep = make_tas_file.whole_second_series(t, v, second_rule=rule,
                                                           neighbour="nearest-present")
            r = next(r for r in rep if r["second"] == 124838)
            self.assertEqual((r["class"], r["kept"], r["fallback"]), ("ambiguous", None, 170.0),
                             rule)
            self.assertIn(124838.0, list(tt))     # kept, at the default

    def test_round_and_floor_carry_across_the_minute_in_seconds_of_day(self):
        tt, _, _ = make_tas_file.whole_second_series(
            [125959.6], [1.0], second_rule="round", neighbour="adjacent")
        self.assertEqual(list(tt), [130000.0])
        tt, _, _ = make_tas_file.whole_second_series(
            [125959.6], [1.0], second_rule="floor", neighbour="adjacent")
        self.assertEqual(list(tt), [125959.0])


class TheCliRefusesAmbiguityAndLogsEveryResolution(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.csv = _csv(self.d, _ROWS_124838)
        self.out = self.d / "base170821110122.aircraft.cdf"

    def test_no_flags_means_the_author_defaults_and_the_log_names_them(self):
        rc, text = _run([str(self.out), "--from-tas-csv", str(self.csv)])
        self.assertEqual(rc, 0, text)
        self.assertIn("--second-rule round --neighbour adjacent", text)
        self.assertIn("rows above 300 m/s, at/below 0 m/s or non-finite are set aside", text)
        self.assertIn("takes 170 m/s (never dropped)", text)
        self.assertIn("--on-unsettled default", text)

    def test_an_unknown_rule_is_an_argparse_error(self):
        with self.assertRaises(SystemExit), unittest.mock.patch("sys.stderr"):
            make_tas_file.main([str(self.out), "--from-tas-csv", str(self.csv),
                                "--second-rule", "nearest"])
        self.assertFalse(self.out.exists())

    def test_an_impossible_row_is_logged_and_stamped(self):
        import netCDF4
        csv = _csv(self.d, _ROWS_124838 + "124840.000,241403.0625,0\n")
        rc, text = _run([str(self.out), "--from-tas-csv", str(csv)])
        self.assertEqual(rc, 0, text)
        self.assertIn("TAS substituted: 124840 241403.0625 -> 170 m/s (above-cutoff",
                      text)
        with netCDF4.Dataset(self.out) as ds:
            self.assertEqual(ds.tas_substituted_seconds, "124840:above-cutoff")
            self.assertEqual(int(ds.tas_out_of_range_rows), 1)
            self.assertEqual(float(ds.tas_cutoff_mps), 300.0)
            self.assertEqual(float(ds.tas_default_mps), 170.0)
            self.assertIn("largest UIOPS tas_max", ds.tas_policy_note)
            i = list(ds["Time"][:]).index(124840.0)
            self.assertEqual(float(ds["TAS"][i]), 170.0)

    def test_both_options_reach_the_file_from_the_command_line(self):
        import netCDF4
        csv = _csv(self.d, _ROWS_124838 + "124840.000,241403.0625,0\n")
        rc, text = _run([str(self.out), "--from-tas-csv", str(csv), "--cutoff-mps", "250",
                         "--default-mps", "140"])
        self.assertEqual(rc, 0, text)
        with netCDF4.Dataset(self.out) as ds:
            self.assertEqual(ds.tas_policy, "cutoff=250.0,default=140.0")
            i = list(ds["Time"][:]).index(124840.0)
            self.assertEqual(float(ds["TAS"][i]), 140.0)

    def test_a_nonpositive_row_such_as_minus_999_is_dropped_like_an_impossible_one(self):
        """Author, "default yes": the decode's -999 no-TAS marker is not a speed."""
        import netCDF4
        csv = _csv(self.d, _ROWS_124838 + "124840.000,-999.0,0\n")
        rc, text = _run([str(self.out), "--from-tas-csv", str(csv)])
        self.assertEqual(rc, 0, text)
        self.assertIn("TAS substituted: 124840 -999.0 -> 170 m/s (non-positive", text)
        with netCDF4.Dataset(self.out) as ds:
            self.assertIn(124840.0, list(ds["Time"][:]))
            self.assertEqual(ds.tas_substituted_seconds, "124840:non-positive")
            self.assertTrue((ds["TAS"][:] > 0).all())

    def test_by_default_an_unsettled_second_takes_the_default_logged_and_stamped(self):
        """Author ruling: never drop -- the second takes the default value."""
        import netCDF4
        rc, text = _run([str(self.out), "--from-tas-csv", str(self.csv),
                         "--second-rule", "round", "--neighbour", "nearest-present"])
        self.assertEqual(rc, 0, text)
        self.assertIn("TAS substituted: 124838", text)
        self.assertIn("unsettled-duplicate", text)
        with netCDF4.Dataset(self.out) as ds:
            i = list(ds["Time"][:]).index(124838.0)
            self.assertEqual(float(ds["TAS"][i]), 170.0)
            self.assertEqual(ds.tas_substituted_seconds, "124838:unsettled-duplicate")
            self.assertEqual(int(ds.tas_substituted_count), 1)
            self.assertTrue(ds.tas_unsettled_rule.startswith("default"))

    def test_refuse_still_exits_nonzero_writes_nothing_and_names_it(self):
        rc, text = _run([str(self.out), "--from-tas-csv", str(self.csv),
                         "--second-rule", "round", "--neighbour", "nearest-present",
                         "--on-unsettled", "refuse"])
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.out.exists())
        self.assertIn("124838", text)
        self.assertIn("a choice is needed", text)
        self.assertIn("missing adjacent second: previous", text)

    def test_one_log_line_per_resolved_second_and_the_provenance_in_the_file(self):
        import netCDF4
        rc, text = _run([str(self.out), "--from-tas-csv", str(self.csv),
                         "--second-rule", "round", "--neighbour", "adjacent"])
        self.assertEqual(rc, 0, text)
        lines = [ln for ln in text.splitlines()
                 if ln.startswith("TAS duplicate resolved: ")]
        self.assertEqual([ln.split()[3] for ln in lines], ["124835", "124838"])
        self.assertIn("class=unambiguous kept=138.899994", lines[1])
        with netCDF4.Dataset(self.out) as ds:
            self.assertEqual(ds.tas_second_rule, "round")
            self.assertEqual(ds.tas_neighbour_rule, "adjacent")
            self.assertEqual(ds.tas_duplicate_rule, make_tas_file.TAS_DUPLICATE_RULE)
            self.assertEqual(int(ds.tas_duplicates_resolved), 2)
            self.assertEqual(ds.tas_duplicates_resolved_seconds, "124835,124838")
            self.assertIn("(measured)", ds.tas_source)
        t = np.asarray(ncio.ncread(self.out, "Time"), dtype=float).ravel()
        self.assertEqual(list(t), [124835.0, 124836.0, 124838.0, 124839.0])


if __name__ == "__main__":
    unittest.main()
