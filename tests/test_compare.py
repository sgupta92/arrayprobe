# SPDX-License-Identifier: BSD-3-Clause
"""The diff-triage engine — the join, the tolerance classes, and the gate.

The thing this tool exists to prevent is a comparison that *looks* rigorous and is
not, so the tests are written against the two ways that happens.

**A bad alignment reads as a bad port.** One extra particle at index 12 makes an
element-wise diff report every subsequent row as wrong, and the resulting "40 of 41
variables differ" tells you nothing about the 40. :class:`JoinTest` builds exactly
that situation — same particles, one inserted — and requires the join to isolate the
insertion and leave everything else matched.

**A silent default reads as agreement.** A variable nobody assigned a tolerance to
must not quietly pass; it must block the gate. :class:`GateTest` pins that, because
the failure mode is invisible: the report is green and one column was never checked.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

from tests._repo import needs_v314_engine

from arrayprobe._v314_lazy import lazy_module
from arrayprobe.compare import (
    CLASSES,
    JOIN_KEY,
    PROC_CLASSES,
    ComparisonReport,
    compare_proc_files,
    compare_variables,
    format_report,
    join_particles,
)
from arrayprobe.ncio import _quiet_netcdf4_setitem
from arrayprobe.profiles import ORACLES_2016, STOCK_V314

_imgproc = lazy_module("arrayprobe.imgproc")

DATA = Path(__file__).parent / "data"
NOMASK = DATA / "s3o_nomask_octave_golden.nc"
MASK9 = DATA / "s3o_mask9_octave_golden.nc"


def write_particles(path, *, date, time, rec, pos_start, values=None, extra=None):
    """Write a minimal per-particle file carrying the join key plus one value."""
    n = len(rec)
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", None)
        ds.createDimension("pos_count", 2)
        for name, data in (("Date", date), ("Time", time), ("parent_rec_num", rec)):
            v = ds.createVariable(name, "i4", ("time",))
            v[:] = np.asarray(data, dtype=np.int32)
        p = ds.createVariable("position", "i2", ("time", "pos_count"))
        # netCDF4 sets .shape on the array it is handed, which NumPy 2.5
        # deprecates; ncio already owns the suppression for that.
        with _quiet_netcdf4_setitem():
            p[:] = np.column_stack([np.asarray(pos_start, dtype=np.int16),
                                    np.asarray(pos_start, dtype=np.int16) + 3])
        if values is not None:
            v = ds.createVariable("image_length", "i2", ("time",))
            v[:] = np.asarray(values, dtype=np.int16)
        if extra is not None:
            v = ds.createVariable(extra, "f8", ("time",))
            v[:] = np.zeros(n)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class JoinTest(unittest.TestCase):
    """Alignment before comparison — the point of the whole module."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _pair(self, a_kwargs, b_kwargs):
        a, b = self.dir / "a.nc", self.dir / "b.nc"
        write_particles(a, **a_kwargs)
        write_particles(b, **b_kwargs)
        with netCDF4.Dataset(a) as da, netCDF4.Dataset(b) as db:
            return join_particles(da, db)

    def test_identical_files_join_completely(self):
        kw = dict(date=[20160906] * 4, time=[64403] * 4, rec=[1, 1, 2, 2],
                  pos_start=[0, 10, 0, 10], values=[5, 6, 7, 8])
        j = self._pair(kw, dict(kw))
        self.assertEqual(j.n_matched, 4)
        self.assertEqual(j.join_fraction, 1.0)
        self.assertEqual(j.left_only.size, 0)
        self.assertEqual(j.right_only.size, 0)

    def test_one_inserted_particle_does_not_cascade(self):
        """The failure this module exists to prevent.

        B has one particle A does not. Element-wise, everything from that index on
        would disagree. Joined, exactly one particle is unmatched and the other
        four line up — including the values, which are deliberately *shifted* in
        B so that a positional comparison would report them all wrong.
        """
        a = dict(date=[20160906] * 4, time=[64403] * 4, rec=[1, 1, 2, 2],
                 pos_start=[0, 10, 0, 10], values=[5, 6, 7, 8])
        b = dict(date=[20160906] * 5, time=[64403] * 5, rec=[1, 1, 1, 2, 2],
                 pos_start=[0, 5, 10, 0, 10], values=[5, 99, 6, 7, 8])
        j = self._pair(a, b)
        self.assertEqual(j.n_matched, 4)
        self.assertEqual(j.left_only.size, 0)
        np.testing.assert_array_equal(j.right_only, [1])

        pa, pb = self.dir / "a.nc", self.dir / "b.nc"
        with netCDF4.Dataset(pa) as da, netCDF4.Dataset(pb) as db:
            verdicts = {v.name: v for v in compare_variables(da, db, j)}
        self.assertEqual(verdicts["image_length"].verdict, "EXACT",
                         "the joined particles agree; only the insertion differs")

    def test_unmatched_runs_are_collapsed(self):
        a = dict(date=[20160906] * 8, time=[64403] * 8, rec=[1] * 8,
                 pos_start=list(range(0, 80, 10)), values=list(range(8)))
        # B is missing indices 2,3,4 (one run) and 6 (a singleton).
        keep = [0, 1, 5, 7]
        b = dict(date=[20160906] * 4, time=[64403] * 4, rec=[1] * 4,
                 pos_start=[i * 10 for i in keep], values=keep)
        j = self._pair(a, b)
        runs = j.unmatched_runs("left")
        self.assertEqual(runs, [(2, 3), (6, 1)],
                         "three consecutive plus one singleton, not four losses")

    def test_duplicate_keys_are_surfaced(self):
        kw = dict(date=[20160906] * 3, time=[64403] * 3, rec=[1, 1, 1],
                  pos_start=[0, 0, 10], values=[1, 2, 3])
        j = self._pair(kw, dict(kw))
        self.assertGreater(j.duplicate_keys, 0)

    def test_a_measured_value_cannot_move_a_particle_across_the_join(self):
        """Every join-key component is framing-derived, deliberately."""
        a = dict(date=[20160906] * 3, time=[64403] * 3, rec=[1, 1, 2],
                 pos_start=[0, 10, 0], values=[5, 6, 7])
        b = dict(a, values=[500, 600, 700])
        j = self._pair(a, b)
        self.assertEqual(j.n_matched, 3)
        self.assertNotIn("image_length", JOIN_KEY)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class ToleranceClassTest(unittest.TestCase):
    @needs_v314_engine
    def test_every_proc_variable_is_classified(self):
        """A new variable must be given a class deliberately, not defaulted.

        This is the guard that keeps the gate meaningful: an unclassified column
        is one nobody has decided how to judge, and passing it silently is
        indistinguishable from checking it.
        """
        for profile in (STOCK_V314, ORACLES_2016):
            names = {s.name for s in _imgproc.imgproc_variables(profile)}
            missing = names - set(PROC_CLASSES)
            with self.subTest(profile=profile.name):
                self.assertEqual(
                    missing, set(),
                    f"unclassified proc variables: {sorted(missing)}. Assign a "
                    "tolerance class in compare.PROC_CLASSES.",
                )

    def test_classes_declare_whether_they_assert(self):
        self.assertTrue(CLASSES["A"].asserts)
        self.assertTrue(CLASSES["B"].asserts)
        self.assertTrue(CLASSES["D"].asserts)
        self.assertTrue(CLASSES["F"].asserts)
        # C and E are informational by design: asserting on an accumulated float
        # or a version-dependent code produces failures no-one can act on.
        self.assertFalse(CLASSES["C"].asserts)
        self.assertFalse(CLASSES["E"].asserts)

    def test_no_categorical_variable_is_asserted(self):
        for name in ("image_auto_reject", "holroyd_habit"):
            self.assertFalse(CLASSES[PROC_CLASSES[name]].asserts,
                             f"{name} must never be asserted -- two MATLAB "
                             "versions may legitimately disagree on it")


@unittest.skipUnless(netCDF4 is not None and NOMASK.is_file() and MASK9.is_file(),
                     "Goldens are not distributed with the package; the test needs files that are "
                     "not part of this release")
class RealFileTest(unittest.TestCase):
    """Against the S3o goldens, whose differences are already characterised."""

    def test_a_file_against_itself_is_accepted(self):
        report = compare_proc_files(NOMASK, NOMASK)
        self.assertEqual(report.join.join_fraction, 1.0)
        self.assertEqual(report.failures, [])
        self.assertEqual(report.unclassified, [])
        self.assertTrue(report.accepted())
        self.assertTrue(all(v.verdict == "EXACT" for v in report.variables))

    def test_the_mask_difference_joins_completely_but_differs_in_value(self):
        """A mask cannot change framing, so the join must be perfect regardless.

        This is the cleanest available demonstration that the join and the value
        comparison are independent: 41 variables, 18 of them differing, and every
        particle still matched.

        18, not the 23 it was until 2026-08-28: the S3o goldens are now made with
        ``uioops_testing/calculate_reject_unified.m`` (``rej_hollow=0``) on the
        Octave path, so the five hollow-derived outputs are constant fall-through
        values that a mask cannot move.  Measured, and pinned in
        ``test_imgproc_shadow_diode`` from the other side.
        """
        report = compare_proc_files(NOMASK, MASK9)
        self.assertEqual(report.join.join_fraction, 1.0)
        self.assertEqual(report.join.n_matched, 99)
        differing = [v for v in report.variables if v.verdict != "EXACT"]
        self.assertEqual(len(differing), 18)
        self.assertFalse(report.accepted())

    def test_categorical_differences_come_back_as_transitions(self):
        report = compare_proc_files(NOMASK, MASK9)
        by_name = {v.name: v for v in report.variables}
        reject = by_name["image_auto_reject"]
        self.assertEqual(reject.tclass, "E")
        self.assertEqual(reject.verdict, "INFO",
                         "class E is reported, never asserted")
        self.assertTrue(reject.confusion, "a confusion matrix must be produced")
        # Re-illuminating diodes un-rejects particles: the codes move toward
        # '0' (48, not rejected), and that direction is the finding.
        self.assertTrue(
            any(right == 48.0 for (_, right) in reject.confusion),
            "expected transitions into the not-rejected code",
        )

    def test_filtering_the_table_cannot_turn_a_failure_green(self):
        """`--var` narrows the *table*, never the verdict.

        Filtering to a class E variable -- which never asserts -- would otherwise
        print ACCEPTED: True while forty other variables went unexamined. The CLI
        computes acceptance over the whole file and passes it in, so the two can
        never drift apart.
        """
        report = compare_proc_files(NOMASK, MASK9)
        whole_file = report.accepted()
        self.assertFalse(whole_file)

        report.variables = [v for v in report.variables
                            if v.name == "image_auto_reject"]
        self.assertTrue(report.accepted(),
                        "the filtered report on its own does look acceptable -- "
                        "which is exactly why the verdict must not come from it")
        text = format_report(report, accepted=whole_file)
        self.assertIn("ACCEPTED: False", text)

    def test_report_is_ascii_and_mentions_the_join_first(self):
        text = format_report(compare_proc_files(NOMASK, MASK9))
        text.encode("ascii")     # the CLI prints this to a cp1252 console
        self.assertLess(text.index("JOIN"), text.index("VARIABLE"))


class GateTest(unittest.TestCase):
    """`accepted()` — what blocks it, and why each blocker is there."""

    def _report(self, **kw):
        from arrayprobe.compare import JoinResult, VariableVerdict

        join = kw.pop("join", JoinResult(np.arange(100), np.arange(100),
                                         np.array([], int), np.array([], int),
                                         100, 100))
        variables = kw.pop("variables", [VariableVerdict("x", "A", "EXACT")])
        return ComparisonReport(join, variables)

    def test_clean_report_is_accepted(self):
        self.assertTrue(self._report().accepted())

    def test_an_unclassified_variable_blocks_acceptance(self):
        from arrayprobe.compare import VariableVerdict

        r = self._report(variables=[VariableVerdict("mystery", "?", "INFO")])
        self.assertFalse(r.accepted(),
                         "a column nobody decided how to judge is not evidence "
                         "of agreement")

    def test_a_failing_asserting_class_blocks_acceptance(self):
        from arrayprobe.compare import VariableVerdict

        r = self._report(variables=[VariableVerdict("image_length", "A", "DIFF", 1, 99)])
        self.assertFalse(r.accepted())

    def test_an_informational_class_does_not_block_acceptance(self):
        from arrayprobe.compare import VariableVerdict

        r = self._report(variables=[
            VariableVerdict("image_auto_reject", "E", "INFO", 22, 99),
            VariableVerdict("Time_in_seconds", "C", "INFO", 5, 99),
        ])
        self.assertTrue(r.accepted())

    def test_duplicate_join_keys_block_acceptance(self):
        from arrayprobe.compare import JoinResult

        join = JoinResult(np.arange(100), np.arange(100), np.array([], int),
                          np.array([], int), 100, 100, duplicate_keys=2)
        self.assertFalse(self._report(join=join).accepted(),
                         "if the key does not identify a particle, every value "
                         "comparison built on it is meaningless")

    def test_a_poor_join_blocks_acceptance(self):
        from arrayprobe.compare import JoinResult

        join = JoinResult(np.arange(90), np.arange(90), np.arange(90, 100),
                          np.array([], int), 100, 100)
        self.assertFalse(self._report(join=join).accepted())
        self.assertAlmostEqual(join.join_fraction, 0.9)


if __name__ == "__main__":
    unittest.main()
