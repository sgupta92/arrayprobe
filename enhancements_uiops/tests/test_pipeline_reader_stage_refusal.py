# SPDX-License-Identifier: BSD-3-Clause
"""Tests for the enhancements driver's refusal of reader-stage enhancements.

A reader-stage enhancement
(``last_record_fix``, ``pms_c6_routing_fix``) acts during decode, before the port ever runs,
so ``arrayprobe_enhancements.pipeline`` has no path to that input without re-decoding -- and a
re-decode path is explicitly out of scope. Closed by the author 2026-09-21: the driver refuses
explicitly, naming the module, the stage, and what to do instead, rather than staying silent.

The classification comes from :attr:`~arrayprobe_enhancements.registry.EnhancementSpec.stage`,
never a name list inside the driver -- :class:`ClassificationIsDerivedNotListed` is the guard
that keeps it that way.

These tests call :func:`pipeline.apply_to_outputs` directly on an *empty* output directory
rather than running the real port: the reader-stage branch only ever consults ``spec.stage``,
never the raw or decoded files, so a real flight run would exercise nothing this file does not
already cover, at the cost of a subprocess per test. ``test_pipeline_provenance.py`` still
covers the reader-stage skip as it appears inside a real end-to-end run.
"""

from __future__ import annotations

import contextlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arrayprobe_enhancements import applicability, pipeline, registry

#: The v3.1.4 engine is installed in the development repository and absent from a
#: release tree. Read from the engine, not from the enhancement modules whose omission
#: the test below checks, and not from a repository file above this distribution's root.
V314_INSTALLED = importlib.util.find_spec("arrayprobe.sizedist") is not None
#: Needs the v3.1.4 engine, so the release omits it (``registry.OMITTED`` there).
_LAST_RECORD_OMITTED = ("release view: last_record_fix needs the v3.1.4 engine and does not "
                        "ship; ReaderStageModuleOmittedFromTheRelease covers it there")


def _all_off() -> dict[str, bool]:
    return {name: False for name in registry.REGISTRY}


@contextlib.contextmanager
def simulated_release_view():
    """The release view inside the development tree: every ``REQUIRES_V314`` module moved
    from ``REGISTRY``/``APPLICABILITY`` to ``OMITTED``/``OMITTED_APPLICABILITY``, as the
    import-time pass does when the module file is absent. All four tables are restored."""
    names = sorted(applicability.REQUIRES_V314 & set(registry.REGISTRY))
    with mock.patch.dict(registry.REGISTRY), mock.patch.dict(registry.OMITTED),             mock.patch.dict(applicability.APPLICABILITY),             mock.patch.dict(applicability.OMITTED_APPLICABILITY):
        for n in names:
            registry.OMITTED[n] = registry.REGISTRY.pop(n)
            applicability.OMITTED_APPLICABILITY[n] = applicability.APPLICABILITY.pop(n)
        yield names


class ReaderStageIsRefusedExplicitly(unittest.TestCase):
    """The two shipped reader-stage modules, each named and explained on its own terms."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, resolved):
        [report] = pipeline.apply_to_outputs(
            "run.toml", "3.5", self.out_dir, ["nosuchstem"], resolved)
        return report

    @unittest.skipIf("last_record_fix" in registry.OMITTED, _LAST_RECORD_OMITTED)
    def test_last_record_fix_is_named_and_explained(self):
        resolved = _all_off()
        resolved["last_record_fix"] = True
        report = self._run(resolved)
        self.assertIn("last_record_fix", report["skipped"])
        reason = report["skipped"]["last_record_fix"]
        self.assertIn("last_record_fix", reason)
        self.assertIn("reader-stage", reason)
        self.assertIn("decode", reason)
        self.assertIn("read_binary_spec_with_last_record", reason)
        self.assertNotIn("last_record_fix", report["applied"])

    def test_pms_c6_routing_fix_is_named_and_explained(self):
        """Regression guard: the reason used to be one fixed string naming
        ``last_record_fix`` regardless of which reader-stage module was actually skipped."""
        resolved = _all_off()
        resolved["pms_c6_routing_fix"] = True
        report = self._run(resolved)
        reason = report["skipped"]["pms_c6_routing_fix"]
        self.assertIn("pms_c6_routing_fix", reason)
        self.assertIn("read_binary_PMS_corrected", reason)
        self.assertNotIn("last_record_fix", reason)

    @unittest.skipIf("last_record_fix" in registry.OMITTED, _LAST_RECORD_OMITTED)
    def test_both_together_are_each_named_correctly(self):
        resolved = _all_off()
        resolved["last_record_fix"] = True
        resolved["pms_c6_routing_fix"] = True
        report = self._run(resolved)
        self.assertIn("read_binary_spec_with_last_record",
                      report["skipped"]["last_record_fix"])
        self.assertIn("read_binary_PMS_corrected",
                      report["skipped"]["pms_c6_routing_fix"])


class ReaderStageModuleOmittedFromTheRelease(unittest.TestCase):
    """Release view: ``last_record_fix`` does not ship, so it is refused by name before the
    driver runs and never appears in a report; ``pms_c6_routing_fix`` is still refused as a
    reader-stage module."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _assert_release_view(self):
        self.assertIn("last_record_fix", registry.OMITTED)
        self.assertNotIn("last_record_fix", registry.REGISTRY)
        with self.assertRaisesRegex(registry.UnknownEnhancement, "last_record_fix.*v3.1.4"):
            registry.resolve({"last_record_fix": True}, engine="3.5")
        resolved = _all_off()
        resolved["pms_c6_routing_fix"] = True
        [report] = pipeline.apply_to_outputs(
            "run.toml", "3.5", self.out_dir, ["nosuchstem"], resolved)
        self.assertNotIn("last_record_fix", report["skipped"])
        self.assertNotIn("last_record_fix", report["applied"])
        self.assertIn("read_binary_PMS_corrected", report["skipped"]["pms_c6_routing_fix"])

    @unittest.skipUnless("last_record_fix" in registry.OMITTED,
                         "development view: last_record_fix ships")
    def test_last_record_fix_is_refused_by_name(self):
        self._assert_release_view()

    def test_last_record_fix_is_refused_by_name_simulated(self):
        with simulated_release_view():
            self._assert_release_view()

    def test_a_name_neither_registered_nor_omitted_still_fails(self):
        with simulated_release_view():
            with self.assertRaises(registry.UnknownEnhancement) as caught:
                registry.resolve({"last_record_fixx": True}, engine="3.5")
            self.assertIn("unknown enhancement", str(caught.exception))


@unittest.skipUnless(V314_INSTALLED, "release view: the v3.1.4 engine does not ship")
class TheDevelopmentViewOmitsNothing(unittest.TestCase):
    """With the allow-list present (development), ``last_record_fix`` ships, so the
    reader-stage refusal above is tested exactly and its release-view skip cannot fire."""

    def test_last_record_fix_is_registered(self):
        self.assertEqual(registry.OMITTED, {})
        self.assertIn("last_record_fix", registry.REGISTRY)


class TheRefusalDoesNotFireForNonReaderModules(unittest.TestCase):
    """A proc-stage or no-stage module resolved ON, with no driver adapter, gets its own
    (different) named reason -- never the reader-stage message."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_unwired_proc_stage_module_is_not_called_reader_stage(self):
        # dmax_sensitivity: stage="proc", has an entry_point, but is not wired into
        # pipeline._APPLIERS -- a different, pre-existing "no driver adapter" reason.
        resolved = _all_off()
        resolved["dmax_sensitivity"] = True
        [report] = pipeline.apply_to_outputs(
            "run.toml", "3.5", self.out_dir, ["nosuchstem"], resolved)
        reason = report["skipped"]["dmax_sensitivity"]
        self.assertNotIn("reader-stage", reason)

    def test_a_none_stage_module_is_not_called_reader_stage(self):
        resolved = _all_off()
        resolved["md_relations"] = True
        [report] = pipeline.apply_to_outputs(
            "run.toml", "3.5", self.out_dir, ["nosuchstem"], resolved)
        reason = report["skipped"]["md_relations"]
        self.assertNotIn("reader-stage", reason)
        self.assertEqual(reason, pipeline._NO_STAGE_REASON)

    def test_a_wired_proc_stage_module_applies_rather_than_being_refused(self):
        # hole_edge_swap IS wired (pipeline._APPLIERS); with no proc file to find it
        # is a named ApplierSkip, but it must never be mistaken for the reader-stage one.
        resolved = _all_off()
        resolved["hole_edge_swap"] = True
        [report] = pipeline.apply_to_outputs(
            "run.toml", "3.5", self.out_dir, ["nosuchstem"], resolved)
        reason = report["skipped"]["hole_edge_swap"]
        self.assertNotIn("reader-stage", reason)


class ClassificationIsDerivedNotListed(unittest.TestCase):
    """The guard this refusal needs: a brand-new module registered with
    ``stage="reader"`` must be refused automatically, with no edit to pipeline.py naming it.
    If this test ever needs a driver-side edit to keep passing, the classification has
    regressed to exactly the kind of hard-coded name list this refusal was written to avoid."""

    NAME = "zz_test_only_reader_stage_dummy"

    def setUp(self):
        self.assertNotIn(self.NAME, registry.REGISTRY,
                         "test fixture name collided with a real registration")
        registry.register(registry.EnhancementSpec(
            name=self.NAME,
            summary="test-only fixture, never a real correction",
            entry_point="dummy_entry_point",
            stage="reader",
        ))
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)

    def tearDown(self):
        del registry.REGISTRY[self.NAME]
        self._tmp.cleanup()

    def test_the_new_module_is_refused_without_touching_the_driver(self):
        resolved = _all_off()
        resolved[self.NAME] = True
        [report] = pipeline.apply_to_outputs(
            "run.toml", "3.5", self.out_dir, ["nosuchstem"], resolved)
        reason = report["skipped"][self.NAME]
        self.assertIn(self.NAME, reason)
        self.assertIn("reader-stage", reason)
        self.assertIn("dummy_entry_point", reason)
        self.assertNotIn(self.NAME, report["applied"])

    def test_a_reader_stage_module_with_no_entry_point_still_refuses_cleanly(self):
        """entry_point=None is a real, registered state (see registry.py's docstring on
        modules registered-but-not-yet-wired); the message must degrade gracefully rather
        than crash or print a broken 'call None' sentence."""
        del registry.REGISTRY[self.NAME]
        registry.register(registry.EnhancementSpec(
            name=self.NAME,
            summary="test-only fixture, never a real correction",
            entry_point=None,
            stage="reader",
        ))
        resolved = _all_off()
        resolved[self.NAME] = True
        [report] = pipeline.apply_to_outputs(
            "run.toml", "3.5", self.out_dir, ["nosuchstem"], resolved)
        reason = report["skipped"][self.NAME]
        self.assertIn(self.NAME, reason)
        self.assertIn("reader-stage", reason)
        self.assertNotIn("None", reason)


if __name__ == "__main__":
    unittest.main()
