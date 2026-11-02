# SPDX-License-Identifier: BSD-3-Clause
"""Every ``arrayprobe`` subcommand that writes a product stamps what it wrote.

WHY THIS EXISTS (2026-09-18). Before this, the only stamp writer in the whole pipeline
was ``scripts/run_flight.py``'s ``write_stamp``, called after each of the driver's stages. The
library functions that actually write products -- the readers, ``imgproc_sm``, ``sizeDist``,
``combine_sizedist`` -- wrote nothing beside their output, so **every caller that was not the
driver produced an unstamped product**. That included the repository's own shipped single-stage
verbs, which the documentation offers as the way to run one stage: ``arrayprobe read-binary``,
``imgproc``, ``sizedist`` and ``combine``. The package documented a way to produce exactly what
``run_flight`` refuses, and the lane scripts that hand-rolled four incompatible JSON sidecars
did so because nothing shipped would stamp for them.

``imgproc`` was worse than unstamped: it was **hard-wired to v3.1.4 with no way to say so and
no way to ask for anything else**, while ``uiops`` has defaulted to v3.5 since 2026-09-12. A
user running the documented command got the non-default engine silently. ``--engine`` is now
required, which is the part of this that cannot be got wrong by omission -- argparse refuses
before any code runs.

**Firing tests, not happy paths.** Each case runs the real verb over a tracked fixture and
asserts a sidecar exists with the right engine; the ``--engine`` cases assert that *omitting*
the flag exits 2 and that the flag's value is what lands in the stamp, so a hard-wired default
sneaking back would fail here rather than pass quietly.

**Coverage note, stated rather than glossed**: the DMT
reader has no raw fixture in ``tests/data/`` small enough to run here -- the tracked DMT
material is processed output (``fo_*_cip_proc.nc.gz``), not raw. So the end-to-end decode test
covers ``--format spec`` on ``demo_flight_v314_raw.2DS``, and the DMT/PMS/SEA paths are covered
by asserting the stamp helper's output-path computation for each format instead, which is the
part that differs between them.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import cli, provenance

DATA = Path(__file__).resolve().parent / "data"
RAW_2DS = DATA / "demo_flight_v314_raw.2DS"


class ReadBinaryStamps(unittest.TestCase):
    """A decoded image file records the profile and channels that made it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    @needs_v314_engine
    @unittest.skipUnless(RAW_2DS.is_file(), "demo_flight_v314_raw.2DS not present")
    def test_spec_decode_leaves_a_stamp_naming_engine_and_profile(self):
        out = self.d / "demo"
        code = cli.main(["read-binary", str(RAW_2DS), str(out), "--format", "spec",
                         "--profile", "oracles-production", "--channels", "H",
                         "--engine", "3.1.4"])
        self.assertEqual(code, 0)
        written = out.with_name("demo.H.cdf")
        self.assertTrue(written.is_file(), "the reader wrote nothing to stamp")
        stamp = provenance.read(written)
        self.assertIsNotNone(stamp, "the decoded file carries no .call sidecar")
        self.assertEqual(stamp.engine, "3.1.4")
        self.assertEqual(stamp.profile, "oracles-production")
        self.assertEqual(stamp.stage, "S2")
        self.assertEqual(provenance.state(written), "stamped")

    @needs_v314_engine
    @unittest.skipUnless(RAW_2DS.is_file(), "demo_flight_v314_raw.2DS not present")
    def test_the_stamp_records_the_raw_file_it_decoded(self):
        """Not for re-running -- S2 cannot be re-run from a stamp -- but so that "which raw
        file is this?" has an answer beside the product rather than in someone's memory."""
        out = self.d / "demo"
        cli.main(["read-binary", str(RAW_2DS), str(out), "--format", "spec",
                  "--profile", "oracles-production", "--channels", "H",
                         "--engine", "3.1.4"])
        stamp = provenance.read(out.with_name("demo.H.cdf"))
        self.assertEqual(stamp.fields.get("raw"), RAW_2DS.name)
        self.assertEqual(stamp.fields.get("format"), "spec")

    @needs_v314_engine
    def test_the_output_paths_are_computed_per_format(self):
        """The stamp must land on what the reader wrote. SPEC writes ``<outfile>.<channel>.cdf``
        per ``--channels``, PMS ``<outfile>.{2dc,f2dc,2dp}.cdf``, SEA ``<outfile>.{CIP,2DC}.cdf``
        and DMT ``outfile`` verbatim. Getting this wrong would produce an orphan stamp beside a
        product with none -- worse than no stamp, because it asserts a file that is not there.
        (Until 2026-09-26 this test asserted PMS and SEA write ``outfile`` verbatim, which their
        readers never did, so their real products went unstamped.)"""
        parser = cli.build_parser()
        args = parser.parse_args(["read-binary", "in", "out", "--format", "spec",
                                  "--profile", "p", "--channels", "HV", "--engine", "3.1.4"])
        self.assertEqual([p.name for p in cli._read_binary_outputs(args)],
                         ["out.H.cdf", "out.V.cdf"])
        args = parser.parse_args(["read-binary", "in", "out", "--format", "spec",
                                  "--profile", "p", "--channels", "H", "--engine", "3.1.4"])
        self.assertEqual([p.name for p in cli._read_binary_outputs(args)], ["out.H.cdf"])
        expected = {"dmt": ["out.nc"],
                    "pms": ["out.nc.2dc.cdf", "out.nc.f2dc.cdf", "out.nc.2dp.cdf"],
                    "sea": ["out.nc.CIP.cdf", "out.nc.2DC.cdf"]}
        for fmt, names in expected.items():
            args = parser.parse_args(["read-binary", "in", "out.nc", "--format", fmt,
                                      "--engine", "3.1.4"])
            self.assertEqual([p.name for p in cli._read_binary_outputs(args)], names)

    def test_a_path_that_was_not_written_is_not_stamped(self):
        """``_stamp`` skips a missing path. The firing case for the rule above."""
        cli._stamp([self.d / "never_written.nc"], engine="3.1.4", stage="S2", profile="p")
        self.assertFalse(provenance.call_path(self.d / "never_written.nc").exists())


@needs_v314_engine
class ImgprocRequiresAnEngine(unittest.TestCase):
    """The hard-wiring is gone, and its absence is enforced by argparse."""

    def _args(self, *extra):
        return ["imgproc", "in.nc", "out.nc", "2DS", "1", "1", "PROJ",
                "--profile", "oracles-production", *extra]

    def test_omitting_engine_exits_2_and_runs_nothing(self):
        """The firing test. Until 2026-09-18 this command line ran, and ran v3.1.4."""
        with self.assertRaises(SystemExit) as caught:
            cli.build_parser().parse_args(self._args())
        self.assertEqual(caught.exception.code, 2)

    def test_the_flag_accepts_only_the_two_engines(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(self._args("--engine", "3.3"))

    def test_both_engines_parse(self):
        for version in ("3.1.4", "3.5"):
            args = cli.build_parser().parse_args(self._args("--engine", version))
            self.assertEqual(args.engine, version)

    def test_engine_3_5_refuses_rather_than_defaulting_the_arguments_it_lacks(self):
        """v3.5's ``imgProc_sm`` requires ``iNewHabit``, a reject config, the TAS arrays and a
        software string, each keyword-only and each a fidelity choice. This verb's flags carry
        none of them, so it refuses and names the route that does, rather than inventing four
        defaults -- ``cli``'s own rule that a front door never defaults a fidelity choice."""
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(self._args("--engine", "3.5"))
        self.assertEqual(code, 2)
        message = err.getvalue()
        self.assertIn("iNewHabit", message)
        self.assertIn("arrayprobe run", message)


class TheStampHelperIsHonest(unittest.TestCase):
    """What ``_stamp`` writes, checked directly -- the three verbs above all route through it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.product = self.d / "proc.x.nc"
        self.product.write_bytes(b"")

    def test_it_writes_a_driver_format_stamp_the_parser_reads_back(self):
        cli._stamp([self.product], engine="3.5", stage="S3", profile="stock-v3.5",
                   extra={"probe": "2DS"})
        stamp = provenance.read(self.product)
        self.assertEqual(stamp.format, "driver")
        self.assertEqual((stamp.engine, stamp.profile, stamp.stage), ("3.5", "stock-v3.5", "S3"))
        self.assertEqual(stamp.fields.get("probe"), "2DS")

    def test_engine_comes_first_so_the_stamp_stays_greppable(self):
        cli._stamp([self.product], engine="3.1.4", stage="S4", profile=None)
        self.assertTrue(provenance.read(self.product).raw.startswith("engine=3.1.4 "))

    def test_a_cli_stamp_is_marked_as_one(self):
        """It records this verb's arguments, not a whole driver configuration, so ``reprocess``
        will refuse to re-run from it. The stamp says which kind it is rather than implying
        more than it knows."""
        cli._stamp([self.product], engine="3.1.4", stage="S3", profile="p")
        self.assertEqual(provenance.read(self.product).fields.get("writer"), "arrayprobe-cli")


class EveryWritingVerbStamps(unittest.TestCase):
    """The class-level check, so a *new* writing verb that forgets is caught.

    Fixing the instance and not the class is the failure this repository has recorded twice.
    The four verbs that write a product are enumerated from the parser, and each handler's
    compiled code must reference the stamp helper.
    """

    WRITERS = {
        "read-binary": "_run_read_binary",
        "imgproc": "_run_imgproc",
        "sizedist": "_run_sizedist",
        "combine": "_run_combine",
    }

    def test_each_writing_handler_calls_the_stamp_helper(self):
        for verb, handler in sorted(self.WRITERS.items()):
            with self.subTest(verb=verb):
                func = getattr(cli, handler)
                self.assertIn("_stamp", func.__code__.co_names,
                              f"{verb} writes a product and does not stamp it")

    def test_the_enumeration_is_not_vacuous(self):
        """If the handlers were renamed away, the loop above would pass over an empty set."""
        self.assertEqual(len(self.WRITERS), 4)
        for handler in self.WRITERS.values():
            self.assertTrue(callable(getattr(cli, handler, None)))


class TheProvenanceVerbIsRegistered(unittest.TestCase):
    """``arrayprobe provenance`` is the fix every refusal message points at, so it has to exist."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_it_parses(self):
        args = cli.build_parser().parse_args(["provenance", "a.nc", "b.nc", "--require"])
        self.assertEqual([p.name for p in args.paths], ["a.nc", "b.nc"])
        self.assertTrue(args.require)

    def test_require_exits_1_on_a_directory_holding_an_unstamped_product(self):
        """The firing half: ``--require`` has to be able to fail, or it is decoration."""
        (self.d / "proc.a.nc").write_bytes(b"")
        self.assertEqual(cli.main(["provenance", str(self.d), "--require"]), 1)

    def test_require_exits_0_when_everything_is_stamped(self):
        p = self.d / "proc.a.nc"
        p.write_bytes(b"")
        provenance.write(p, engine="3.1.4", profile="oracles-production", stage="S3")
        self.assertEqual(cli.main(["provenance", str(self.d), "--require"]), 0)

    def test_without_require_it_reports_and_does_not_judge(self):
        (self.d / "proc.a.nc").write_bytes(b"")
        self.assertEqual(cli.main(["provenance", str(self.d)]), 0)


if __name__ == "__main__":
    unittest.main()
