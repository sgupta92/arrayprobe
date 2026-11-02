# SPDX-License-Identifier: BSD-3-Clause
"""The CLI says which engine it runs, and refuses one it cannot.

Before 2026-09-12 the CLI ran the v3.1.4 engine and said nothing about it.
That was harmless while v3.1.4 was the only engine and unremarkable while it
was the default. It stopped being either on the day the author made v3.5 the
default: a command that silently runs the *non*-default engine, in a package
that ships both, is the exact confusion the decision was meant to remove
(*"cant confuse users with too many options and not knowing what
functions/enhancements apply to what"*).

**The refusal is the point.** ``--uiops-version 3.5`` could have been accepted
and ignored, or accepted and quietly downgraded. Either would mean a user's
explicit instruction silently not happening -- the failure this repository has
built checks against repeatedly, most recently in the enhancements resolver,
which raises rather than dropping a switched-on enhancement that does not apply
to the engine. So it exits non-zero, runs nothing, and says which three things
are missing.

**Two sides.** The refusal message's claims are checked against
``uiops.CATALOGUE`` -- ``combine`` really is ``FORK_ONLY``, the three named
v3.5 modules really do import -- rather than being prose that was true when
typed.
"""
from __future__ import annotations

import contextlib
import io
import unittest

from tests._repo import needs_v314_engine  # noqa: E402

import uiops
from arrayprobe import cli


def _run(argv):
    """Run the CLI, returning (status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = cli.main(argv)
    return status, out.getvalue(), err.getvalue()


class TheEngineIsNamedRatherThanImplied(unittest.TestCase):
    # The per-stage commands run v3.1.4 where that engine is installed and v3.5 where it is
    # not (the public release), so the text must name the one this tree runs.
    STAGE_ENGINE = "v3.1.4" if cli._v314_engine_present() else "v3.5"

    def test_the_top_level_description_names_the_engine(self):
        text = cli.build_parser().format_help()
        self.assertIn(self.STAGE_ENGINE, text)
        self.assertIn("engines", text)

    def test_version_output_names_the_pipeline_engine(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                cli.main(["--version"])
        self.assertIn(f"UIOOPS {self.STAGE_ENGINE} engine", out.getvalue())


class AnUnwiredEngineIsRefusedNotIgnored(unittest.TestCase):
    @needs_v314_engine
    def test_asking_for_v35_exits_non_zero_and_runs_nothing(self):
        status, _out, err = _run(
            ["--uiops-version", "3.5", "combine", "a.nc", "b.nc",
             "--flight-date", "20160906", "--summary-time", "064017", "--engine", "3.1.4"])
        # --engine is required on combine (2026-09-26); a top-level 3.5 naming the other
        # engine is refused before anything runs.
        self.assertEqual(status, 2)
        self.assertIn("disagrees", err)
        self.assertIn("nothing was run", err)

    @needs_v314_engine
    def test_the_refusal_says_what_is_missing_rather_than_only_that_it_is(self):
        _status, _out, err = _run(
            ["--uiops-version", "3.5", "combine", "a.nc", "b.nc",
             "--flight-date", "20160906", "--summary-time", "064017", "--engine", "3.5"])
        # combine on 3.5 has no stock UIOOPS counterpart; the refusal names the opt-in.
        self.assertIn("--borrowed-combine", err)

    def test_naming_the_wired_engine_explicitly_is_accepted(self):
        """It must be possible to *say* 3.1.4, or the flag is decorative and
        a script cannot record which engine it asked for."""
        parser = cli.build_parser()
        args = parser.parse_args(
            ["--uiops-version", "3.1.4", "engines"])
        self.assertEqual(args.uiops_version, "3.1.4")
        self.assertIsNone(cli._refuse_unwired_engine(args))

    def test_the_default_is_the_wired_engine(self):
        """Naming nothing runs v3.1.4, because that is the only wired chain.
        The package default is v3.5, and the CLI's help says outright that
        these differ rather than leaving a reader to discover it."""
        args = cli.build_parser().parse_args(["engines"])
        self.assertEqual(args.uiops_version, "3.1.4")

    def test_the_subcommand_flag_does_not_clobber_the_top_level_one(self):
        """They share a spelling and must not share a store: a subparser
        option with the same dest overwrites whatever was given before the
        subcommand with its own default, which silently turned an explicit
        `--uiops-version 3.1.4` back into None."""
        args = cli.build_parser().parse_args(
            ["--uiops-version", "3.1.4", "engines", "--uiops-version", "3.5"])
        self.assertEqual(args.uiops_version, "3.1.4")
        self.assertEqual(args.engines_version, "3.5")


class TheRefusalsReasonsAreTrue(unittest.TestCase):
    """The message is prose; these are the facts it asserts."""

    def test_combine_really_is_fork_only(self):
        self.assertEqual(uiops.CATALOGUE["combine"].state, uiops.FORK_ONLY)

    def test_the_three_v35_modules_it_points_at_really_import(self):
        import importlib
        for name in ("arrayprobe_uiops.spec", "arrayprobe_uiops.imgproc",
                     "arrayprobe_uiops.sizedist"):
            with self.subTest(name):
                self.assertIsNotNone(importlib.import_module(name))

    def test_the_second_reason_names_the_v35_profiles_that_exist(self):
        """The second reason. Until 2026-09-13 it said no v3.5 profile existed
        and this test asserted exactly that; STOCK_V35 landing made it fail,
        as designed, and the message was rewritten. It now asserts the
        message names every v3.5-looking profile, so the next one registered
        fails this again and the prose has to catch up."""
        from arrayprobe import profiles
        from arrayprobe.cli import _V35_PIPELINE_GAPS
        # Profiles only: profiles.py also imports STOCK_V35_REJECT_CONFIG,
        # a reject configuration the profile points at, not a variant.
        named = [n for n in dir(profiles) if n.isupper() and isinstance(
            getattr(profiles, n), profiles.FidelityProfile)]
        v35ish = [n for n in named if "35" in n or "V3_5" in n]
        # Grew on 2026-09-17 when ORACLES_PRODUCTION_V35 shipped: the v3.5 engine
        # reads only reject_thresholds from a profile, so pinning STOCK_V35 pinned the
        # thresholds too and refused the author's side-by-side. This test fired exactly as
        # its docstring promised, and the CLI's second reason now names both.
        self.assertEqual(sorted(v35ish), ["ORACLES_PRODUCTION_V35", "STOCK_V35"],
                         f"profiles.py's v3.5 variants changed ({v35ish}); "
                         f"rewrite the CLI's second refusal reason")
        for name in v35ish:
            with self.subTest(profile=name):
                self.assertIn(name, " ".join(_V35_PIPELINE_GAPS),
                              f"{name} exists but the CLI's refusal reasons do not name it")
        self.assertIn("STOCK_V35", cli._V35_PIPELINE_GAPS[1])

    def test_every_reason_is_a_separate_sentence_of_substance(self):
        self.assertGreaterEqual(len(cli._V35_PIPELINE_GAPS), 3)
        self.assertTrue(all(len(r) > 40 for r in cli._V35_PIPELINE_GAPS))


class TheEnginesSubcommandExplains(unittest.TestCase):
    def test_it_describes_the_default_engine_by_default(self):
        status, out, _err = _run(["engines"])
        self.assertEqual(status, 0)
        self.assertIn("UIOPS 3.5", out)
        self.assertIn("the default", out)

    @needs_v314_engine
    def test_it_can_describe_the_other_engine(self):
        status, out, _err = _run(["engines", "--uiops-version", "3.1.4"])
        self.assertEqual(status, 0)
        self.assertIn("UIOPS 3.1.4", out)
        self.assertIn("layer 1", out)

    def test_describing_v35_is_not_refused(self):
        """``engines`` describes an engine rather than running one. Refusing
        it would make the one command that explains the situation the one
        command that cannot mention it."""
        status, out, _err = _run(["engines", "--uiops-version", "3.5"])
        self.assertEqual(status, 0)
        self.assertIn("layer 2", out)

    @needs_v314_engine
    def test_the_default_output_is_a_decision_not_the_catalogue(self):
        """A newcomer asking "which engine do I use" gets the three-way choice and
        the command for each, not forty module rows."""
        status, out, _err = _run(["engines"])
        self.assertEqual(status, 0)
        self.assertIn("Which engine to use", out)
        for name, _use, command in cli.ENGINE_DECISION:
            self.assertIn(name, out)
            if name == "UIOPS v3.1.4" and not cli._v314_engine_present():
                # The public distribution omits the engine, so it names no command for it.
                self.assertIn("not runnable in this package", out)
                self.assertNotIn(command, out)
            else:
                self.assertIn(command, out)
        self.assertIn("arrayprobe engines --catalogue", out)
        rows = [n for n in uiops.CATALOGUE if n and f"\n{n}\n" in out]
        self.assertEqual(rows, [], f"catalogue rows printed without --catalogue: {rows}")
        self.assertLess(len(out.splitlines()), 20)

    def test_the_decision_names_the_default_and_the_anchor_correctly(self):
        text = " ".join(" ".join(row) for row in cli.ENGINE_DECISION)
        self.assertIn("v3.5 (the default)", text)
        self.assertIn('[run].engine = "3.5"', text)
        self.assertIn('[run].engine = "3.1.4"', text)
        self.assertIn("arrayprobe soda2 run", text)
        self.assertIn("only to reproduce an archived UIOPS product", text)

    def test_the_full_catalogue_covers_every_module(self):
        _status, out, _err = _run(["engines", "--catalogue"])
        missing = [n for n in uiops.CATALOGUE if n and n not in out]
        self.assertEqual(missing, [],
                         f"modules absent from the printed catalogue: {missing}")

    def test_a_single_module_can_be_asked_about(self):
        status, out, _err = _run(["engines", "--module", "reject"])
        self.assertEqual(status, 0)
        self.assertIn("arrayprobe_uiops.reject", out)
        self.assertNotIn("\nlwc\n", out)

    def test_an_unknown_module_is_an_error(self):
        status, _out, err = _run(["engines", "--module", "nope"])
        self.assertEqual(status, 2)
        self.assertIn("nope", err)

    def test_it_distinguishes_the_states_a_user_acts_on(self):
        _status, out, _err = _run(["engines", "--catalogue"])
        for phrase in ("byte-identical", "NO stock UIOPS release",
                       "v3.5's own translation"):
            self.assertIn(phrase, out)


if __name__ == "__main__":
    unittest.main()
