# SPDX-License-Identifier: BSD-3-Clause
"""Stratified review samples.

The plan's clause is *"so a labelled set can state its own coverage"*, and that
is what these tests hold the code to. A sample that quietly omits the strata it
could not fill would still produce a queue file, still produce labels, and still
produce an accuracy number -- one that silently excludes exactly the particles
nobody looked at. So the assertions here are mostly about what the coverage
statement must keep saying, not about the draw.

The draw itself is seeded, and that is asserted too: a queue nobody can
regenerate is not evidence of anything.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from arrayprobe.review_sampling import (
    COVERAGE_KEY,
    SIZE_EDGES,
    STRATIFIERS,
    Sample,
    Stratum,
    stratum_labels,
)

PROC = Path(__file__).resolve().parent / "data" / "v35_sizedist_synthetic.proc.nc"


def _synthetic_proc(path: Path, n: int = 60) -> Path:
    """A proc file with known strata, so the assertions can be exact.

    Built here rather than mocked: `Sample` reads a netCDF, and a test that
    stubbed the read would stop covering the part most likely to break -- the
    variable names in ``STRATIFIERS``.
    """
    rng = np.random.default_rng(7)
    with Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", n)
        codes = np.array([ord("0")] * (n // 2) + [ord("z")] * (n - n // 2))
        v = ds.createVariable("image_auto_reject", "i2", ("time",))
        v[:] = codes
        v = ds.createVariable("holroyd_habit", "i2", ("time",))
        v[:] = np.array([ord("t"), ord("s")] * (n // 2))
        v = ds.createVariable("image_diam_minR", "f8", ("time",))
        # Spread across three of the size bins, none in the top two.
        v[:] = rng.choice([0.02, 0.07, 0.15], size=n)
        v = ds.createVariable("image_center_in", "i2", ("time",))
        v[:] = np.ones(n)
    return path


class LabellingIsReadable(unittest.TestCase):
    def test_character_codes_become_characters(self):
        got = stratum_labels("reject_code", np.array([ord("0"), ord("z")]))
        self.assertEqual(list(got), ["0", "z"])

    def test_an_unprintable_code_is_shown_as_its_number(self):
        """Rather than mangled into a control character nobody can grep for."""
        self.assertEqual(list(stratum_labels("habit", np.array([7]))), ["#7"])

    def test_size_labels_name_their_own_edges(self):
        got = stratum_labels("size_bin", np.array([0.01, 0.07, 5.0]))
        self.assertEqual(list(got), ["0-0.05mm", "0.05-0.1mm", "1-infmm"])

    def test_a_nan_diameter_is_labelled_not_dropped(self):
        """A flight with such particles is saying something."""
        self.assertEqual(list(stratum_labels("size_bin", np.array([np.nan]))),
                         ["out-of-range"])

    def test_every_stratifier_names_a_real_proc_variable(self):
        """The table and the shipped synthetic proc fixture must not drift apart.

        Two sides from different places: the names come from STRATIFIERS, the
        variables from a file on disk.
        """
        self.assertTrue(PROC.is_file(), f"synthetic proc fixture missing: {PROC}")
        with Dataset(str(PROC)) as ds:
            present = set(ds.variables)
        missing = [v for v in STRATIFIERS.values() if v not in present]
        self.assertEqual(missing, [], f"STRATIFIERS names variables the tracked "
                                      f"synthetic proc fixture does not have: {missing}")


class TheSampleStatesItsCoverage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.proc = _synthetic_proc(self.dir / "proc.nc")

    def test_an_empty_stratum_is_listed_with_a_count_of_zero(self):
        """The assertion the whole design rests on.

        The synthetic flight has nothing above 0.2 mm. Those strata must appear
        in the coverage with `available: 0` -- dropping them would make the
        sample look like complete coverage of a size range it never saw.
        """
        s = Sample("f", self.proc, by=["size_bin"], n_per_stratum=3)
        cov = s.coverage()
        empty = [row for row in cov["strata"] if row["available"] == 0]
        self.assertTrue(empty, "no empty stratum was recorded at all")
        self.assertEqual(cov["n_strata"], len(SIZE_EDGES) - 1)
        self.assertEqual(cov["n_strata_empty"], len(empty))

    def test_an_under_filled_stratum_takes_what_it_has_and_says_so(self):
        s = Sample("f", self.proc, by=["reject_code"], n_per_stratum=10_000)
        cov = s.coverage()
        self.assertEqual(cov["n_strata_under_filled"], cov["n_strata"])
        for row in cov["strata"]:
            self.assertEqual(row["taken"], row["available"])
            self.assertTrue(row["under_filled"])

    def test_a_full_stratum_is_not_reported_as_under_filled(self):
        """The other direction, so the flag means something."""
        s = Sample("f", self.proc, by=["reject_code"], n_per_stratum=2)
        self.assertEqual(s.coverage()["n_strata_under_filled"], 0)

    def test_the_cross_product_is_over_observed_values(self):
        s = Sample("f", self.proc, by=["reject_code", "habit"], n_per_stratum=1)
        self.assertEqual(s.coverage()["n_strata"], 4)   # 2 codes x 2 habits

    def test_the_coverage_records_the_seed_and_the_file(self):
        s = Sample("f", self.proc, by=["habit"], n_per_stratum=2, seed=11)
        cov = s.coverage()
        self.assertEqual(cov["seed"], 11)
        self.assertEqual(cov["proc_file"], "proc.nc")
        self.assertEqual(cov["by"], ["habit"])


class TheDrawIsReproducible(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.proc = _synthetic_proc(self.dir / "proc.nc")

    def test_the_same_seed_gives_the_same_particles(self):
        a = Sample("f", self.proc, by=["habit"], n_per_stratum=4, seed=3)
        b = Sample("f", self.proc, by=["habit"], n_per_stratum=4, seed=3)
        self.assertEqual(a.items(), b.items())

    def test_a_different_seed_gives_a_different_draw(self):
        """Otherwise `seed` is decoration and the reproducibility claim is empty."""
        a = Sample("f", self.proc, by=["habit"], n_per_stratum=4, seed=3)
        b = Sample("f", self.proc, by=["habit"], n_per_stratum=4, seed=4)
        self.assertNotEqual(a.items(), b.items())

    def test_only_accepted_restricts_to_what_imgproc_accepted(self):
        s = Sample("f", self.proc, by=["reject_code"], n_per_stratum=100,
                   only_accepted=True)
        drawn = {row["stratum"][0] for row in s.coverage()["strata"] if row["taken"]}
        self.assertEqual(drawn, {"0"})


class TheQueueFileIsNotClobbered(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.proc = _synthetic_proc(self.dir / "proc.nc")
        self.path = self.dir / "queues.json"

    def test_a_second_sample_adds_to_the_file(self):
        """A reviewer's other queues live in that file."""
        Sample("f", self.proc, by=["habit"], n_per_stratum=1).write(self.path)
        Sample("f", self.proc, by=["reject_code"], n_per_stratum=1).write(self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        queues = [k for k in data if k != COVERAGE_KEY]
        self.assertEqual(len(queues), 2)
        self.assertEqual(set(data[COVERAGE_KEY]), set(queues))

    def test_the_queue_entries_are_the_shape_the_server_reads(self):
        from arrayprobe.triage_server import _load_queue_file

        Sample("f", self.proc, by=["habit"], n_per_stratum=2).write(self.path)
        loaded = _load_queue_file(self.path)
        self.assertIn(COVERAGE_KEY, loaded,
                      "the coverage key must survive the server's own reader")
        for name, items in loaded.items():
            if name == COVERAGE_KEY:
                continue
            for item in items:
                self.assertIn("flight", item)
                self.assertIn("particle_index", item)

    def test_a_file_that_is_not_a_queue_file_is_refused(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(ValueError):
            Sample("f", self.proc, by=["habit"], n_per_stratum=1).write(self.path)


class BadArgumentsAreRefused(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proc = _synthetic_proc(Path(tmp.name) / "proc.nc")

    def test_an_unknown_stratifier_is_refused_not_ignored(self):
        """Ignoring it would produce a 'stratified' sample that is not one."""
        with self.assertRaises(ValueError) as caught:
            Sample("f", self.proc, by=["colour"], n_per_stratum=1)
        self.assertIn("colour", str(caught.exception))

    def test_no_stratifier_at_all_is_refused(self):
        with self.assertRaises(ValueError):
            Sample("f", self.proc, by=[], n_per_stratum=1)

    def test_a_non_positive_n_is_refused(self):
        with self.assertRaises(ValueError):
            Sample("f", self.proc, by=["habit"], n_per_stratum=0)


class TheSummaryReadsLikeAStatement(unittest.TestCase):
    def test_it_names_the_empty_and_the_thin_strata(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _synthetic_proc(Path(tmp) / "proc.nc")
            text = Sample("f", proc, by=["size_bin"], n_per_stratum=1000).summary()
        self.assertIn("strata", text)
        self.assertIn("none of", text)
        self.assertIn("thinner", text)


class TheStratumRecordIsHonestOnItsOwn(unittest.TestCase):
    def test_under_filled_compares_against_what_was_requested(self):
        """Read back from a file, a stratum must still know it fell short."""
        s = Stratum(key=("x",), available=2, taken=2, requested=5)
        self.assertTrue(s.under_filled)
        self.assertTrue(s.as_dict()["under_filled"])

    def test_a_satisfied_stratum_is_not_under_filled(self):
        s = Stratum(key=("x",), available=9, taken=5, requested=5)
        self.assertFalse(s.under_filled)


if __name__ == "__main__":
    unittest.main()
