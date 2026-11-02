# SPDX-License-Identifier: BSD-3-Clause
"""``scripts/run_flight.py`` -- the fidelity-configuration stamp beside each output.

THE INCIDENT THIS EXISTS FOR, 2026-08-30.  Flight 09/14 was started and two of
its four files were skipped as already done.  Their ``proc``/``sd`` files were
dated Aug 20-21; the reject-threshold correction landed Aug 28 (``2d0544f``),
so those files carried the *stock* thresholds -- ``rej_hollow=1``,
``max_edge_img_ar=6``, ``max_comp_img_ar=5`` -- while everything produced that
day carried the production ones.  Combining them would have put two
configurations inside one flight product, which is the error class this project
spent a week untangling on 09/06, and it would have produced a plausible number
rather than an error.

It was caught by reading a directory listing and noticing the dates.  That is
not a control, and the notes said so at the time: *"a .call-style sidecar
recording the reject config would make this detectable rather than something to
remember -- a candidate control, not yet built."*  This is that control.

The runner's skip is by **existence**, and existence does not record
configuration: no ``proc`` or ``sd`` file can be asked which thresholds made it
(adding an attribute of our own would break the byte-fidelity with MATLAB that
the package exists to demonstrate).  So the configuration is written beside the
output and compared on the next run.

These tests pin the *mechanism*, not today's defaults: every case names the
configuration it means, so they keep passing if a default ever changes -- and
the first one fails if the stamp ever stops distinguishing the two reject
configurations, which is the whole point.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_file  # noqa: E402

from arrayprobe.profiles import ORACLES_PRODUCTION, STOCK_V314
from arrayprobe_uiops.reject_core import DEFAULT_REJECT_CONFIG, ORACLES_PRODUCTION_REJECT_CONFIG

_SPEC = importlib.util.spec_from_file_location(
    "run_flight", Path(__file__).resolve().parent.parent / "scripts" / "run_flight.py")
# Use whichever module object is REGISTERED, never a private copy: an
# unconditional overwrite here clobbered test_run_from_config.py's own
# sys.modules["run_flight"] registration when both ran in one process --
# arrayprobe.cli._load_run_flight() then called into THIS module while that
# file's tests still asserted on its OWN (now stale) reference, so a run's
# PROFILE switch was invisible to it (green alone, red in the suite,
# discovered 2026-09-13 verifying the --tas-file step, Phase 2b). Same fix as
# test_run_from_config.py's own identical comment.
assert _SPEC is not None and _SPEC.loader is not None
if _SPEC.name in sys.modules:
    run_flight = sys.modules[_SPEC.name]
else:
    run_flight = importlib.util.module_from_spec(_SPEC)
    sys.modules[_SPEC.name] = run_flight
    _SPEC.loader.exec_module(run_flight)

STEM = "base160914093925"        # one of the two files the incident was found on


class ConfigLabelTests(unittest.TestCase):
    """What the stamp must distinguish, and what it must not."""

    def test_the_two_reject_configurations_get_different_labels(self):
        """The 09/14 trap, reduced to one assertion.

        ``STOCK_V314`` and ``ORACLES_PRODUCTION`` differ in exactly the three
        dated ``uioops_testing`` edits, and a stamp that did not separate them
        would have let the stale files through.
        """
        self.assertNotEqual(run_flight.config_label(STOCK_V314),
                            run_flight.config_label(ORACLES_PRODUCTION))

    def test_the_label_carries_the_thresholds_not_just_the_profile_name(self):
        """A name is not evidence -- the values have to be in the file.

        The two sides come from different places on purpose: the expected text
        is built here from ``reject.py``'s own configuration objects, while the
        label is built by the runner from whatever the profile carries.  A
        profile silently re-pointed at the other configuration fails here.
        """
        label = run_flight.config_label(ORACLES_PRODUCTION)
        self.assertIn(f"rej_hollow={ORACLES_PRODUCTION_REJECT_CONFIG.rej_hollow}", label)
        self.assertIn(
            f"max_edge_img_ar={ORACLES_PRODUCTION_REJECT_CONFIG.max_edge_img_ar}", label)
        self.assertIn(
            f"max_comp_img_ar={ORACLES_PRODUCTION_REJECT_CONFIG.max_comp_img_ar}", label)
        stock = run_flight.config_label(STOCK_V314)
        self.assertIn(f"rej_hollow={DEFAULT_REJECT_CONFIG.rej_hollow}", stock)

    def test_every_reject_field_is_stamped(self):
        """A field added to ``RejectConfig`` later must enter the stamp on its own.

        The label is built by walking the dataclass, so this holds without
        anyone remembering to update it -- and this test is what says that is a
        requirement rather than an implementation detail.
        """
        import dataclasses
        label = run_flight.config_label(ORACLES_PRODUCTION)
        for field in dataclasses.fields(ORACLES_PRODUCTION.reject_thresholds):
            self.assertIn(f"{field.name}=", label)

    def test_a_diode_mask_changes_the_label(self):
        """``--diode-corrected`` changes what S3 computes, so it changes the stamp."""
        self.assertNotEqual(run_flight.config_label(shadow_diode=None),
                            run_flight.config_label(shadow_diode=[95]))
        self.assertNotEqual(run_flight.config_label(shadow_diode=[77]),
                            run_flight.config_label(shadow_diode=[95]))

    def test_the_sd_label_carries_both_halves(self):
        """The twelfth-argument call (58 %) and the reject
        configuration (~40 % of large particles) are independent, and an sd file
        records neither.  Changing either one must change the stamp."""
        a = run_flight.sd_call_label(run_flight.IAT_FILE, ORACLES_PRODUCTION)
        self.assertNotEqual(a, run_flight.sd_call_label(None, ORACLES_PRODUCTION))
        self.assertNotEqual(a, run_flight.sd_call_label(run_flight.IAT_FILE, STOCK_V314))


class ImageLabelTests(unittest.TestCase):
    """S2's stamp -- the decode, one stage upstream of everything above.

    The reject thresholds never reach `read_binary_SPEC`, so it would be easy to
    think a `.H.cdf` is configuration-free. It is not: the ORACLES lineage
    predates Finlon's 2017-03-08 buffer guards and **dies** where stock skips a
    packet, and `channels` decides which channel files exist at all.
    """

    def test_the_buffer_guard_separates_the_profiles(self):
        self.assertNotEqual(run_flight.image_call_label(STOCK_V314),
                            run_flight.image_call_label(ORACLES_PRODUCTION))
        self.assertIn("spec_buffer_guard=True", run_flight.image_call_label(STOCK_V314))
        self.assertIn("spec_buffer_guard=False",
                      run_flight.image_call_label(ORACLES_PRODUCTION))

    def test_the_channel_selection_is_stamped(self):
        self.assertNotEqual(run_flight.image_call_label(channels="H"),
                            run_flight.image_call_label(channels="HV"))

    @needs_file("src/arrayprobe/readers/spec.py")
    def test_every_profile_field_the_decoder_reads_is_stamped(self):
        """The two sides come from different files, which is the point.

        One side is `readers/spec.py`'s own `profile.<field>` accesses, read out
        of the source; the other is the stamp text. A profile field that starts
        reaching the decoder therefore fails this test until it is stamped --
        rather than silently joining the class of differences a `.H.cdf` cannot
        be asked about.
        """
        import re
        source = (Path(run_flight.__file__).resolve().parents[1]
                  / "src" / "arrayprobe" / "readers" / "spec.py").read_text(encoding="utf-8")
        fields = set(re.findall(r"\bprofile\.([a-z_]+)", source))
        label = run_flight.image_call_label()
        # `name` is stamped as the `profile=` key itself, not as `name=`.
        for field in fields - {"name"}:
            self.assertIn(f"{field}=", label,
                          f"spec.py reads profile.{field}, which the S2 stamp omits")
        self.assertIn(f"profile={run_flight.PROFILE.name}", label)


class OutputStateTests(unittest.TestCase):
    """``absent`` / ``current`` / ``stale`` / ``unstamped`` -- four states, because
    the last two call for different answers (see :func:`run_flight.output_state`)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.proc = run_flight.proc_path(STEM, self.out)
        self.want = run_flight.proc_call_label()

    def test_absent(self):
        self.assertEqual(run_flight.output_state(self.proc, self.want), "absent")

    def test_unstamped_is_its_own_state(self):
        self.proc.touch()
        self.assertEqual(run_flight.output_state(self.proc, self.want), "unstamped")

    def test_stale_when_the_stamp_names_another_configuration(self):
        self.proc.touch()
        run_flight.write_stamp(self.proc, run_flight.config_label(STOCK_V314))
        self.assertEqual(run_flight.output_state(self.proc, self.want), "stale")

    def test_current_when_the_stamp_matches(self):
        self.proc.touch()
        run_flight.write_stamp(self.proc, self.want)
        self.assertEqual(run_flight.output_state(self.proc, self.want), "current")

    def test_a_stamp_with_no_output_is_absent_not_current(self):
        run_flight.write_stamp(self.proc, self.want)
        self.assertEqual(run_flight.output_state(self.proc, self.want), "absent")

    def test_the_stamp_survives_a_trailing_newline(self):
        self.proc.touch()
        run_flight.call_path(self.proc).write_text(self.want + "\n\n")
        self.assertEqual(run_flight.output_state(self.proc, self.want), "current")


class Stage3SkipDecisionTests(unittest.TestCase):
    """What ``stage3`` does with an existing proc file, per state.

    ``_check_proc_state`` is the decision on its own, so it can be tested
    without a flight's worth of data -- the same reason ``sd_is_current`` was
    separated out in 2026-08-20.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.proc = run_flight.proc_path(STEM, self.out)
        self.want = run_flight.proc_call_label()
        self._log = run_flight.log
        self.lines = []
        run_flight.log = self.lines.append
        self.addCleanup(lambda: setattr(run_flight, "log", self._log))

    def test_a_current_proc_is_skipped(self):
        self.proc.touch()
        run_flight.write_stamp(self.proc, self.want)
        self.assertTrue(
            run_flight._check_proc_state(self.proc, self.want, "S3", False))

    def test_a_stale_proc_is_redone_and_says_what_it_was(self):
        """The 09/14 files, had they been stamped: known configuration, known
        to be wrong, so S3 runs again -- and the log names both sides rather
        than saying only that something was redone."""
        self.proc.touch()
        run_flight.write_stamp(self.proc, run_flight.config_label(STOCK_V314))
        self.assertFalse(
            run_flight._check_proc_state(self.proc, self.want, "S3", False))
        self.assertTrue(any("redo" in line for line in self.lines))
        self.assertTrue(any("rej_hollow=True" in line for line in self.lines),
                        "the log must name the configuration the file was built with")

    def test_an_unstamped_proc_is_REFUSED_not_guessed(self):
        """The state every proc file written before this control is in.

        Refused rather than redone: it may be current and it may not, and this
        driver cannot tell.  Redoing it unasked spends hours and overwrites what
        may be evidence; using it unasked is the incident.
        """
        self.proc.touch()
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight._check_proc_state(self.proc, self.want, "S3", False)

    def test_an_unstamped_proc_is_used_when_the_operator_accepts_it(self):
        """``--accept-unstamped`` is the operator's call, and the log says so --
        nothing is written claiming the file was verified."""
        self.proc.touch()
        self.assertTrue(
            run_flight._check_proc_state(self.proc, self.want, "S3", True))
        self.assertTrue(any("UNSTAMPED" in line for line in self.lines))
        self.assertIsNone(run_flight.read_stamp(self.proc),
                          "accepting an unstamped file must not stamp it")


class Stage4RefusesABadInputTests(unittest.TestCase):
    """``--stages 4`` skips S3, so ``stage4`` is the only place that can notice
    an sd file about to be built on top of the wrong proc file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.proc = run_flight.proc_path(STEM, self.out)
        self.proc.touch()
        (self.out / f"{STEM}.tas.csv").write_text("100000,150,0,0,0,0,0,0,0\n")
        self._log = run_flight.log
        run_flight.log = lambda *a, **k: None
        self.addCleanup(lambda: setattr(run_flight, "log", self._log))

    def test_a_stale_proc_is_refused(self):
        run_flight.write_stamp(self.proc, run_flight.config_label(STOCK_V314))
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.stage4(self.proc, STEM, self.out, run_flight.IAT_FILE)

    def test_an_unstamped_proc_is_refused(self):
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.stage4(self.proc, STEM, self.out, run_flight.IAT_FILE)

    def test_the_refusal_does_not_touch_an_existing_sd_file(self):
        """The 2026-08-27 data-loss incident's lesson, applied to the new path:
        a stage that declines to run must leave what is on disk alone."""
        sd = run_flight.sd_path(STEM, self.out)
        sd.write_bytes(b"the only surviving copy")
        run_flight.write_stamp(self.proc, run_flight.config_label(STOCK_V314))
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.stage4(self.proc, STEM, self.out, run_flight.IAT_FILE)
        self.assertEqual(sd.read_bytes(), b"the only surviving copy")


class PreflightProvenanceTests(unittest.TestCase):
    """A dry run has to say this *before* the hours are committed, not after."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "out"
        self.out.mkdir()
        self.raw = Path(self._tmp.name) / f"{STEM}.2DS"
        self.raw.write_bytes(b"\0" * 1024)
        self.addCleanup(self._tmp.cleanup)

    def _run(self, **kw):
        printed = []
        real = run_flight.log
        run_flight.log = printed.append
        try:
            ok = run_flight.preflight([self.raw], self.out, run_flight.IAT_FILE, **kw)
        finally:
            run_flight.log = real
        return ok, printed

    def test_an_unstamped_proc_refuses_the_run(self):
        run_flight.proc_path(STEM, self.out).touch()
        ok, lines = self._run()
        self.assertFalse(ok)
        self.assertTrue(any("UNSTAMPED" in line for line in lines))
        self.assertTrue(any("REFUSING" in line for line in lines))

    def test_accept_unstamped_lets_it_through(self):
        run_flight.proc_path(STEM, self.out).touch()
        ok, lines = self._run(accept_unstamped=True)
        self.assertTrue(ok)
        self.assertFalse(any("REFUSING" in line for line in lines))

    def test_a_stale_proc_is_reported_and_priced_as_work_to_do(self):
        """Not "S4 only": a proc file built with the other configuration is
        redone, so the estimate must include S3 rather than promising 53
        seconds of work."""
        proc = run_flight.proc_path(STEM, self.out)
        proc.touch()
        run_flight.write_stamp(proc, run_flight.config_label(STOCK_V314))
        ok, lines = self._run()
        self.assertTrue(ok)
        self.assertTrue(any("REDONE" in line for line in lines))
        self.assertTrue(any("to do" in line for line in lines))
        self.assertFalse(any("S4 only" in line for line in lines))

    def test_a_current_proc_with_no_sd_is_S4_only(self):
        proc = run_flight.proc_path(STEM, self.out)
        proc.touch()
        run_flight.write_stamp(proc, run_flight.proc_call_label())
        ok, lines = self._run()
        self.assertTrue(ok)
        self.assertTrue(any("S4 only" in line for line in lines))


class Stage2ProvenanceTests(unittest.TestCase):
    """When the decode's provenance is enforced, and when it deliberately is not."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.raw = self.out / f"{STEM}.2DS"
        self.raw.write_bytes(b"\0" * 16)
        self.image = self.out / f"{STEM}.H.cdf"
        self.image.touch()
        self.lines = []
        self._log = run_flight.log
        run_flight.log = self.lines.append
        self.addCleanup(lambda: setattr(run_flight, "log", self._log))

    def test_an_unstamped_decode_is_refused_when_it_will_be_read(self):
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.stage2(self.raw, self.out)

    def test_a_decode_from_another_profile_is_refused_not_silently_redone(self):
        """Re-decoding is hours, and the runner cannot tell whether the
        difference matters to what the operator wants -- so it stops and says
        what it found rather than choosing for them."""
        run_flight.write_stamp(self.image, run_flight.image_call_label(STOCK_V314))
        with self.assertRaises(run_flight.UnverifiableProvenance) as caught:
            run_flight.stage2(self.raw, self.out)
        self.assertIn("spec_buffer_guard=True", str(caught.exception))

    def test_a_current_decode_is_skipped(self):
        run_flight.write_stamp(self.image, run_flight.image_call_label())
        self.assertEqual(run_flight.stage2(self.raw, self.out), self.image)
        self.assertTrue(any("skip" in line for line in self.lines))

    def test_an_unstamped_decode_nothing_will_read_is_not_refused(self):
        """The twelve decodes already on disk are in this state. Their proc
        files are current, so S3 never opens them; refusing on a file no output
        depends on would block a resume for no gain. The log still says what the
        provenance state was, rather than passing over it in silence."""
        run_flight.stage2(self.raw, self.out, enforce_provenance=False)
        self.assertTrue(any("unstamped" in line for line in self.lines),
                        self.lines)


class CombineProvenanceTests(unittest.TestCase):
    """S4c is where a stale file stops being harmless.

    A wrong ``sd`` file sitting on disk changes nothing; merged into a flight
    product it changes the number a paper is written from, and the product
    carries ten variables and no global attributes, so it cannot be asked
    afterwards which configurations went into it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.lines = []
        self._log = run_flight.log
        run_flight.log = self.lines.append
        self.addCleanup(lambda: setattr(run_flight, "log", self._log))

    def _sd(self, stem, stamp=...):
        path = run_flight.sd_path(stem, self.out)
        path.touch()
        if stamp is ...:
            stamp = run_flight.sd_call_label(run_flight.IAT_FILE)
        if stamp is not None:
            run_flight.write_stamp(path, stamp)
        return (stem, path)

    def test_files_that_agree_are_combined_and_the_configuration_is_logged(self):
        present = [self._sd("base160914075451"), self._sd("base160914093925")]
        run_flight.check_combine_provenance(present)
        self.assertTrue(any("all 2 file(s)" in line for line in self.lines))

    def test_two_configurations_are_REFUSED_by_default(self):
        """The 09/14 flight as it would have been combined: two files newly
        produced under the production thresholds, two carrying the stock ones
        from before 2026-08-28."""
        production = run_flight.sd_call_label(run_flight.IAT_FILE, ORACLES_PRODUCTION)
        stock = run_flight.sd_call_label(run_flight.IAT_FILE, STOCK_V314)
        present = [self._sd("base160914075451", production),
                   self._sd("base160914093925", stock)]
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.check_combine_provenance(present)

    def test_a_refused_mixture_is_listed_file_by_file_before_it_refuses(self):
        """A refusal that does not say which file is the odd one out just moves
        the work back to reading directory listings, which is what failed."""
        present = [
            self._sd("base160914075451",
                     run_flight.sd_call_label(run_flight.IAT_FILE, ORACLES_PRODUCTION)),
            self._sd("base160914093925",
                     run_flight.sd_call_label(run_flight.IAT_FILE, STOCK_V314)),
        ]
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.check_combine_provenance(present)
        self.assertTrue(any("base160914093925" in line and "rej_hollow=True" in line
                            for line in self.lines))
        self.assertTrue(any("base160914075451" in line and "rej_hollow=False" in line
                            for line in self.lines))

    def test_a_deliberate_mixture_is_allowed_when_asked_for(self):
        """The 09/06 archived product IS a mixture -- ``064403`` under
        ``rej_hollow=1`` and the other four under 0 (and the mixed
        combine is the measured better reproduction). The control makes that
        explicit; it does not forbid it."""
        present = [
            self._sd("base160906064403",
                     run_flight.sd_call_label(run_flight.IAT_FILE, STOCK_V314)),
            self._sd("base160906075333",
                     run_flight.sd_call_label(run_flight.IAT_FILE, ORACLES_PRODUCTION)),
        ]
        run_flight.check_combine_provenance(present, allow_mixed=True)
        self.assertTrue(any("MIXED" in line for line in self.lines))

    def test_an_unstamped_sd_is_refused(self):
        present = [self._sd("base160914075451"), self._sd("base160914093925", None)]
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.check_combine_provenance(present)

    def test_an_unstamped_sd_passes_when_accepted(self):
        present = [self._sd("base160914075451", None)]
        run_flight.check_combine_provenance(present, accept_unstamped=True)

    # --- The product's own sidecar (2026-09-16 cold-start usability audit) -------------
    #
    # The v3.1.4 combine wrote NO .call sidecar until this date, while the v3.5 branch did.
    # So on the engine that carries the layer-1 claim, the one file a paper is written from
    # was the one file with no record of how it was made -- against README's "every stage
    # writes a .call sidecar beside its output". Measured by the 2026-09-16 cold-start
    # usability audit (2.6): `find _decoded -name "*call*"` returned three sidecars after
    # `--stages 234c`, for the decode, the proc and the sd, and none for the product.

    def test_the_stamp_names_the_engine_the_inputs_and_how_they_were_built(self):
        present = [self._sd("base160914075451"), self._sd("base160914093925")]
        stamp = run_flight._combine_stamp([p for _, p in present])
        self.assertTrue(stamp.startswith(f"engine={run_flight.ENGINE} "), stamp)
        self.assertIn("combine=oracles-fork:combine_sizedist.m", stamp)
        for stem, path in present:
            self.assertIn(path.name, stamp, stem)
        # The inputs' own configuration, carried through rather than re-derived: this is
        # what makes the product answerable at all, since it carries no global attributes.
        self.assertIn(run_flight.sd_call_label(run_flight.IAT_FILE), stamp)

    def test_an_allowed_mixture_is_named_as_mixed_rather_than_silently_picking_one(self):
        present = [
            self._sd("base160906064403",
                     run_flight.sd_call_label(run_flight.IAT_FILE, STOCK_V314)),
            self._sd("base160906075333",
                     run_flight.sd_call_label(run_flight.IAT_FILE, ORACLES_PRODUCTION)),
        ]
        stamp = run_flight._combine_stamp([p for _, p in present])
        self.assertIn("MIXED(2 configurations", stamp)

    def test_an_accepted_unstamped_input_is_said_not_hidden(self):
        present = [self._sd("base160914075451", None)]
        self.assertIn("<unstamped>", run_flight._combine_stamp([p for _, p in present]))


class WorkerForwardingTests(unittest.TestCase):
    """``--accept-unstamped`` must reach the workers.

    Same failure as the 2026-08-27 ``--diode-corrected`` bug: a worker gets only
    the flags ``_spawn_worker`` explicitly lists, so an unforwarded one turns
    into every worker refusing files the parent already accepted.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._popen = run_flight.subprocess.Popen
        self._log = run_flight.log
        run_flight.log = lambda *a, **k: None
        self.addCleanup(lambda: setattr(run_flight, "log", self._log))
        self.addCleanup(lambda: setattr(run_flight.subprocess, "Popen", self._popen))

    def _spawn(self, accept_unstamped):
        seen = []

        class _FakeProc:
            # pid/poll: pair G's run_parallel now waits through _await_workers,
            # which polls rather than blocks on a bare .wait().
            pid = 0

            def poll(self_inner):
                return 0

            def wait(self_inner, timeout=None):
                return 0

        run_flight.subprocess.Popen = lambda cmd, **kw: (seen.append(cmd), _FakeProc())[1]

        class _Args:
            pass
        args = _Args()
        args.out = self.out
        args.stages = "234"
        args.iat_file = run_flight.IAT_FILE
        args.jobs = 2
        args.chunks = 1
        args.diode_corrected = False
        args.accept_unstamped = accept_unstamped
        args.s2_jobs = 1
        # Four more flags were added to the forwarded flags to _spawn_worker. This file has
        # its own _Args, separate from test_run_flight.py's, and was missed when
        # they were added -- the class the mechanical forwarding check cannot
        # see, because it checks run_flight.py's source, not its callers.
        args.preset = run_flight.PROFILE.name
        args.presets = None
        args.config = None
        args.allow_mixed_config = False
        # The --tas-file step (Phase 2b) added a sixth forwarded flag to _spawn_worker
        # (--tas-file), same shape as the four added earlier -- see the comment
        # above this stub.
        args.tas_file = None
        # Pair G (2026-09-13) added a seventh forwarded flag (--worker-stall-min).
        args.worker_stall_min = 30.0
        args.engine = "3.1.4"  # --engine is required; _spawn_worker reads it
        run_flight.run_parallel(args, [Path("a.2DS"), Path("b.2DS")])
        return seen

    def test_forwarded_when_given(self):
        cmds = self._spawn(True)
        self.assertTrue(cmds)
        for cmd in cmds:
            self.assertIn("--accept-unstamped", cmd)

    def test_not_forwarded_when_not_given(self):
        for cmd in self._spawn(False):
            self.assertNotIn("--accept-unstamped", cmd)


if __name__ == "__main__":
    unittest.main()
