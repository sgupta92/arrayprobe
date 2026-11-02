# SPDX-License-Identifier: BSD-3-Clause
"""A run that states no threshold policy is confirmed before it starts.

The author's instruction, 2026-09-17: *"i think the run_flight should ask the user if they want
enhancements on or off, and where to find information - or ask them to confirm the config file
first where all thresholds and an enhancement flag are obvious and evident."*

What these tests pin, in the order the design decides it:

1. **Who is asked.** Only the under-declared run -- no ``--regime``, no raw override, no
   ``[thresholds]`` section. A run whose policy the operator wrote down has already declared
   itself, and re-asking would train the reflex of dismissing the panel.
2. **How a detached run answers.** This project runs almost everything through
   a detached launcher, where ``nohup`` redirects stdin: a blocking prompt there would
   hang the run indefinitely, which is a *worse* failure than the silent default the gate exists
   to catch. So a non-terminal run refuses to start without ``--yes``, having printed everything
   it would have done.
3. **What the panel says.** Every threshold with its source tag, the enhancement policy,
   and pointers to documents that exist.
4. **That the workers inherit the decision** rather than each re-deciding or deadlocking.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests._repo import repo_only

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import run_flight  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


class _ArgsStub:
    """The two attributes the panel reads off ``args``, for the pure-function tests."""

    preset = "ORACLES_2016_2DS_H"
    stages = "234c"
    yes = False


class WhoIsAsked(unittest.TestCase):
    """:func:`run_flight.needs_confirmation` -- the whole point is that it is *not* every run."""

    def setUp(self):
        for name, value in (("ENGINE", "3.1.4"), ("REGIME_NAME", None),
                            ("AREA_RATIO_Z_OVERRIDE", None), ("DEFAULT_IAT_OVERRIDE", None),
                            ("THRESHOLDS_DECLARED", False)):
            self.addCleanup(setattr, run_flight, name, getattr(run_flight, name))
            setattr(run_flight, name, value)

    def test_a_run_that_states_nothing_is_asked(self):
        """The ARM-ENA shape: no regime, no override, no config -- the run that silently
        inherited ORACLES's own warm-liquid tuning for months."""
        self.assertTrue(run_flight.needs_confirmation(_ArgsStub()))

    def test_naming_a_regime_is_already_a_declaration(self):
        run_flight.REGIME_NAME = "ice"
        self.assertFalse(run_flight.needs_confirmation(_ArgsStub()))

    def test_a_raw_override_on_either_field_is_a_declaration(self):
        run_flight.AREA_RATIO_Z_OVERRIDE = 0.4
        self.assertFalse(run_flight.needs_confirmation(_ArgsStub()))
        run_flight.AREA_RATIO_Z_OVERRIDE = None
        run_flight.DEFAULT_IAT_OVERRIDE = 3e-6
        self.assertFalse(run_flight.needs_confirmation(_ArgsStub()))

    def test_a_config_with_a_thresholds_section_is_a_declaration(self):
        """This is the author's own 'or': *ask them to confirm the config file first where all
        thresholds ... are obvious and evident*. Writing them in the file IS the confirmation,
        which is also what gives an operator a reason to write them there."""
        run_flight.THRESHOLDS_DECLARED = True
        self.assertFalse(run_flight.needs_confirmation(_ArgsStub()))

    def test_engine_3_5_is_never_gated(self):
        """v3.5 resolves no regime and reads no ``tree``: there is no threshold decision here to
        confirm, and inventing a prompt for it would be theatre."""
        run_flight.ENGINE = "3.5"
        self.assertTrue(run_flight.needs_confirmation.__doc__)
        self.assertFalse(run_flight.needs_confirmation(_ArgsStub()))


class WhatThePanelSays(unittest.TestCase):

    def _lines(self):
        return run_flight.confirmation_lines(_ArgsStub(), run_flight._resolve_thresholds())

    def test_it_names_both_thresholds_with_their_source_tags(self):
        text = "\n".join(self._lines())
        self.assertIn("area_ratio_z", text)
        self.assertIn("default_int_arr_thresh", text)
        # The source tag, not a bare number: an unchosen value must not read like a chosen one.
        self.assertIn("(default)", text)

    def test_a_stock_value_is_explained_as_oracles_tuning_not_as_neutral(self):
        """The sentence the gate exists to put in front of somebody. 'default' looks like a safe
        default and is not one -- for a project/probe row with no entry of its own it is
        ORACLES's warm-liquid tuning (regimes.py's module docstring, measured)."""
        text = "\n".join(self._lines())
        self.assertIn("chosen by nobody", text)
        self.assertIn("ORACLES", text)

    def test_it_states_the_enhancement_policy_plainly(self):
        text = "\n".join(self._lines())
        self.assertIn("enhancements", text)
        self.assertIn("OFF", text)

    @repo_only  # reads a repository-only file, not in the sdist
    def test_every_document_it_points_at_exists(self):
        """A pointer to a file that is gone is worse than no pointer: it spends the reader's
        trust and gives nothing back. Checked against the repository, not asserted in prose."""
        for what, where in run_flight.CONFIRM_REFERENCES:
            with self.subTest(what):
                self.assertTrue((REPO / where).is_file(), f"{where} does not exist")

    def test_engine_3_5_says_so_rather_than_printing_thresholds_it_does_not_use(self):
        text = "\n".join(run_flight.confirmation_lines(_ArgsStub(), None))
        self.assertIn("n/a under --engine 3.5", text)


class HowANonTerminalRunAnswers(unittest.TestCase):
    """The constraint that decides the design: ``launch_detached.sh`` closes stdin."""

    def _confirm(self, *, yes: bool, isatty: bool, answer: str = ""):
        args = _ArgsStub()
        args.yes = yes
        buf = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=isatty), \
                mock.patch("builtins.input", return_value=answer), \
                redirect_stdout(buf):
            rc = run_flight.confirm_or_declare(args, run_flight._resolve_thresholds())
        return rc, buf.getvalue()

    def test_no_terminal_and_no_flag_refuses_rather_than_blocking(self):
        rc, out = self._confirm(yes=False, isatty=False)
        self.assertEqual(rc, 2)
        self.assertIn("stdin is not a terminal", out)
        # It must say what to do next, in a form that can be pasted.
        self.assertIn("--regime", out)
        self.assertIn("--yes", out)

    def test_no_terminal_never_calls_input(self):
        """Not merely 'returns 2': it must not so much as *reach* a blocking read, because the
        failure being prevented is a detached run hanging until somebody notices."""
        args = _ArgsStub()
        with mock.patch.object(sys.stdin, "isatty", return_value=False), \
                mock.patch("builtins.input", side_effect=AssertionError("must not ask")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(
                run_flight.confirm_or_declare(args, run_flight._resolve_thresholds()), 2)

    def test_the_flag_accepts_without_a_prompt(self):
        rc, out = self._confirm(yes=True, isatty=True)
        self.assertEqual(rc, 0)
        self.assertIn("confirmed by --yes", out)

    def test_a_terminal_yes_proceeds(self):
        rc, out = self._confirm(yes=False, isatty=True, answer="y")
        self.assertEqual(rc, 0)

    def test_a_terminal_anything_else_stops(self):
        for answer in ("", "n", "no", "later"):
            with self.subTest(answer):
                rc, out = self._confirm(yes=False, isatty=True, answer=answer)
                self.assertEqual(rc, 2, "the default must be to not run")
                self.assertIn("nothing ran", out)

    def test_the_panel_is_printed_before_the_question_either_way(self):
        for isatty in (True, False):
            with self.subTest(isatty=isatty):
                _, out = self._confirm(yes=False, isatty=isatty, answer="n")
                self.assertIn("confirm this run", out)
                self.assertIn("area_ratio_z", out)


class WorkersInheritTheDecision(unittest.TestCase):
    """``--jobs N`` re-execs this file per worker. A worker's stdin is a pipe, so it can never be
    asked; and the parent cannot have reached ``run_parallel`` without passing the gate."""

    def _worker_cmd(self, **overrides):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            args = mock.Mock()
            args.out, args.stages, args.chunks = out, "234c", 1
            args.worker_stall_min, args.s2_jobs = 30, 1
            args.iat_file, args.preset = "", "ORACLES_2016_2DS_H"
            args.tas_file = args.presets = args.config = None
            args.jit = args.allow_mixed_config = False
            args.accept_unstamped = args.diode_corrected = False
            args.engine = "3.1.4"
            args.regime = args.area_ratio_z = args.default_int_arr_thresh = None
            args.tas_max = args.pecan_params = None
            # The TAS source chain's flags, which _spawn_worker forwards.
            args.tas_source = args.tas_search = None
            args.tas_cutoff_mps = args.tas_default_mps = None
            # The probe-clock offset flags, which _spawn_worker forwards since cb13a09.
            args.time_offset_s = args.time_offset_evidence = args.time_offset_tas_clock = None
            for k, v in overrides.items():
                setattr(args, k, v)
            with mock.patch("subprocess.Popen") as popen:
                # _spawn_worker hands back the open log handle for the caller to close; with
                # Popen mocked there is no child to close it, and Windows will not delete the
                # temporary directory underneath a still-open file.
                _, log_f = run_flight._spawn_worker(
                    [out / "base160906064000.2DS"], args, out / "w.log")
                log_f.close()
            return popen.call_args[0][0]

    def test_a_worker_carries_the_parents_assent(self):
        self.assertIn("--yes", self._worker_cmd())

    def test_a_worker_carries_the_regime(self):
        """Missing from the forwarded list for the whole of the day ``--regime`` existed: a
        parent's regime would have reached no worker, every one of them silently falling back to
        the stock pair and stamping its own ``sd`` files with it -- the fifth flag to go missing
        from that list, after --diode-corrected, --accept-unstamped, --s2-jobs and --preset."""
        cmd = self._worker_cmd(regime="ice")
        self.assertIn("--regime", cmd)
        self.assertEqual(cmd[cmd.index("--regime") + 1], "ice")

    def test_a_worker_carries_raw_overrides_without_losing_precision(self):
        cmd = self._worker_cmd(area_ratio_z=0.35, default_int_arr_thresh=6e-6)
        self.assertEqual(float(cmd[cmd.index("--area-ratio-z") + 1]), 0.35)
        self.assertEqual(
            float(cmd[cmd.index("--default-int-arr-thresh") + 1]), 6e-6)

    def test_a_worker_carries_the_time_offset(self):
        cmd = self._worker_cmd(time_offset_s=-2.5, time_offset_evidence="ev",
                               time_offset_tas_clock="tc")
        self.assertEqual(float(cmd[cmd.index("--time-offset-s") + 1]), -2.5)
        self.assertEqual(cmd[cmd.index("--time-offset-evidence") + 1], "ev")
        self.assertEqual(cmd[cmd.index("--time-offset-tas-clock") + 1], "tc")


if __name__ == "__main__":
    unittest.main()
