# SPDX-License-Identifier: BSD-3-Clause
"""A campaign declared in a user's own file, and every way that is refused.

WHY THIS EXISTS (2026-09-09).  ``run_flight.py`` served one campaign, one
probe and one channel as eight module-level constants; 2026-09-08 made them a
named ``CampaignPreset`` and 2026-09-09 made the choice a run-time one.  Both
steps left the same gap: adding a campaign still meant *editing the driver that
fifteen validated flights came out of*.  ``load_presets()`` closes it, and the
whole value of it is in what it refuses -- a loader that accepted a partial or
shadowing campaign would make a wrong run look like a described one.

Each test below is one of those refusals, and each was confirmed by removing the
check and watching this file go red (2026-09-09).  The positive tests state the
declared values literally rather than reading them back out of the loader, for
the same reason ``test_run_flight_preset.py`` does: a test that asks the object
what the object says passes whatever it says.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_v314_engine  # noqa: E402

TOOLS = Path(__file__).resolve().parents[1] / "scripts"

#: A complete, legitimate declaration. Every negative case below is this text
#: with one thing wrong, so what is under test is always the one difference.
GOOD = """[[campaign]]
name = "TESTCAMPAIGN_2DS_V"
probe = "2DS"
orientation = "V"
project = "TESTCAMPAIGN"
d_choice = 6
sa_method = 0
pres_pa = 9e5
temp_c = 15.0
provenance = "invented for tests/test_campaign_preset_file.py; reproduces nothing"
"""


def _load():
    """Import the driver by path -- ``scripts/`` is not a package.

    A fresh module object per call, so one test registering a campaign cannot
    reach the next: ``PRESETS`` and the derived globals are module state.
    """
    spec = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("run_flight", module)
    spec.loader.exec_module(module)
    return module


class _CampaignFileCase(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, text: str) -> Path:
        path = self.dir / "campaigns.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def refuses(self, text: str, *, because: str):
        with self.assertRaises(self.mod.PresetFileError) as caught:
            self.mod.load_presets(self.write(text))
        self.assertIn(because, str(caught.exception))
        return str(caught.exception)


class ADeclaredCampaignIsRegisteredWhole(_CampaignFileCase):
    def test_the_values_arrive_exactly_as_declared(self):
        (preset,) = self.mod.load_presets(self.write(GOOD))
        self.assertEqual(preset.name, "TESTCAMPAIGN_2DS_V")
        self.assertEqual(preset.probe, "2DS")
        self.assertEqual(preset.orientation, "V")
        self.assertEqual(preset.project, "TESTCAMPAIGN")
        self.assertEqual(preset.d_choice, 6)
        self.assertEqual(preset.sa_method, 0)
        self.assertEqual(preset.pres_pa, 9e5)
        self.assertEqual(preset.temp_c, 15.0)

    def test_an_integer_pressure_becomes_a_float(self):
        """TOML's 900000 and 9e5 are different types; the preset field is a float.

        Left as an int, ``pres_pa`` would reach ``sizedist`` as one and the two
        spellings of the same pressure would take different code paths in numpy.
        """
        (preset,) = self.mod.load_presets(
            self.write(GOOD.replace("pres_pa = 9e5", "pres_pa = 900000")))
        self.assertIsInstance(preset.pres_pa, float)
        self.assertEqual(preset.pres_pa, 9e5)

    def test_it_joins_the_registry_and_can_then_be_selected(self):
        self.mod.load_presets(self.write(GOOD))
        self.assertIn("TESTCAMPAIGN_2DS_V", self.mod.PRESETS)
        self.mod.use_preset("TESTCAMPAIGN_2DS_V")
        self.assertEqual(self.mod.ACTIVE.name, "TESTCAMPAIGN_2DS_V")
        self.assertEqual(self.mod.PROBE, "2DS")
        self.assertEqual(self.mod.ORIENTATION, "V")
        self.assertEqual(self.mod.PROJECT, "TESTCAMPAIGN")

    def test_the_stamp_follows_a_declared_campaign(self):
        """The trap that ``use_preset`` was written around, on this path too.

        ``image_call_label``'s ``channels`` default resolves from ``ACTIVE`` at
        call time; if it ever goes back to a captured value, a declared V
        campaign would stamp ``H`` onto its ``.V.cdf`` files and the next stage
        would accept them.
        """
        self.mod.load_presets(self.write(GOOD))
        self.mod.use_preset("TESTCAMPAIGN_2DS_V")
        self.assertIn("channels=V", self.mod.image_call_label())

    def test_the_builtin_presets_are_untouched_by_a_declaration(self):
        self.mod.load_presets(self.write(GOOD))
        self.assertEqual(self.mod.PRESETS["ORACLES_2016_2DS_H"].orientation, "H")
        self.assertEqual(self.mod.PRESETS["ORACLES_2016_2DS_H"].probe, "2DS")

    def test_two_campaigns_in_one_file_both_register(self):
        second = GOOD.replace("TESTCAMPAIGN_2DS_V", "TESTCAMPAIGN_2DS_H").replace(
            'orientation = "V"', 'orientation = "H"')
        loaded = self.mod.load_presets(self.write(GOOD + "\n" + second))
        self.assertEqual([p.name for p in loaded],
                         ["TESTCAMPAIGN_2DS_V", "TESTCAMPAIGN_2DS_H"])


class ACampaignIsStatedWholeOrNotAtAll(_CampaignFileCase):
    def test_a_missing_field_is_refused(self):
        for field in ("probe", "orientation", "project", "d_choice",
                      "sa_method", "pres_pa", "temp_c", "provenance"):
            with self.subTest(field=field):
                text = "".join(line for line in GOOD.splitlines(keepends=True)
                               if not line.startswith(f"{field} "))
                self.refuses(text, because="is missing")

    def test_an_unknown_key_is_refused(self):
        """A typo'd key would otherwise be ignored and its real field left unset."""
        self.refuses(GOOD + 'orientaton = "H"\n', because="does not know")

    def test_the_required_fields_are_the_dataclass_fields(self):
        """Derived, not typed again: a new field is required in the same edit."""
        import dataclasses
        self.assertEqual(
            self.mod.PRESET_FIELDS,
            tuple(f.name for f in dataclasses.fields(self.mod.CampaignPreset)))

    def test_provenance_must_say_something(self):
        self.refuses(GOOD.replace(
            '"invented for tests/test_campaign_preset_file.py; reproduces nothing"', '"  "'),
            because="somebody guessed")

    def test_a_number_where_a_name_belongs_is_refused(self):
        self.refuses(GOOD.replace('project = "TESTCAMPAIGN"', "project = 2016"),
                     because="must be a non-empty string")

    def test_a_boolean_is_not_an_integer(self):
        """``isinstance(True, int)`` is True in Python; ``d_choice = true`` is not a
        size definition."""
        self.refuses(GOOD.replace("d_choice = 6", "d_choice = true"),
                     because="must be an integer")

    def test_a_quoted_number_is_refused(self):
        self.refuses(GOOD.replace("pres_pa = 9e5", 'pres_pa = "9e5"'),
                     because="must be a number")


class ADeclarationCannotChangeWhatAValidatedNameMeans(_CampaignFileCase):
    def test_shadowing_a_builtin_is_refused(self):
        """The name is what logs and ``.call`` stamps record.

        If a file could redefine ``ORACLES_2016_2DS_H``, a run stamped with that
        name would no longer mean the call that reproduces the archived products.
        """
        self.refuses(GOOD.replace("TESTCAMPAIGN_2DS_V", "ORACLES_2016_2DS_H"),
                     because="already a preset this driver ships")

    def test_shadowing_within_one_file_is_refused(self):
        self.refuses(GOOD + "\n" + GOOD, because="already a preset")

    def test_the_builtin_survives_the_attempt(self):
        self.refuses(GOOD.replace("TESTCAMPAIGN_2DS_V", "ORACLES_2016_2DS_H"),
                     because="already a preset this driver ships")
        self.assertEqual(self.mod.PRESETS["ORACLES_2016_2DS_H"].orientation, "H")


class APresetMayOnlyClaimReachTheDriverHas(_CampaignFileCase):
    def test_hv_is_refused_because_nothing_writes_that_file(self):
        """``read_binary_SPEC`` accepts ``"HV"``; S3 reads ``<stem>.<orientation>.cdf``."""
        self.refuses(GOOD.replace('orientation = "V"', 'orientation = "HV"'),
                     because="orientation must be 'H' or 'V'")

    def test_every_probetype_the_driver_declares_is_one_it_can_really_decode(self):
        """**The boundary this test guarded has moved twice, and has now closed.**

        Written against CIP, which was undrivable; moved to 2DC on 2026-09-18
        when CIP became drivable; and as of 2026-09-21 **no probe is on
        the other side of it at all**.  Measured rather than assumed: every entry
        in ``S2_READERS`` is marked supported, ``stage2`` carries real dispatch
        branches for ``read_binary_SEA``, ``read_binary_PMS``, ``read_binary_DMT``
        and ``read_binary_SPEC``, and a 2DC preset with a legal orientation loads
        without refusal.  ``docs/developer/COVERAGE_MATRIX.md`` -- generated, not written --
        agrees: **one** cell is ``refuses, defect`` (PIP under SODA-2, an
        unfinished port boundary in ``processbuffer_cip.py``), against the 25 an
        earlier count quoted.

        So the old assertion is retired rather than weakened, and this is what
        replaces it: the driver must not *declare* a reader it cannot reach.  The
        two sides come from different places -- ``S2_READERS``'s own table on one,
        ``stage2``'s dispatch source on the other -- so a probetype marked
        supported with no branch to run it fails here.

        ``stage2``'s docstring still says "Raw ``.2DS`` -> ``<base>.H.cdf``",
        which is stale and was read as evidence on 2026-09-21 before the dispatch
        was actually inspected.  That is recorded here because a docstring is not
        a measurement.
        """
        import inspect
        src = inspect.getsource(self.mod.stage2)
        unreachable = []
        for probetype, (dotted, supported) in sorted(self.mod.S2_READERS.items()):
            if not supported:
                continue
            attr = dotted.rsplit(".", 1)[-1]
            if attr not in src:
                unreachable.append(f"probetype {probetype}: {dotted}")
        self.assertEqual(
            unreachable, [],
            "S2_READERS marks these supported but stage2 has no dispatch branch "
            "that names the reader -- a probe the driver claims and cannot run:\n  "
            + "\n  ".join(unreachable))

    def test_an_orientation_the_format_has_no_channel_for_is_still_refused(self):
        """The refusal that DID fire where the old one was expected.

        A 2DC preset declaring ``orientation = "V"`` is refused because probetype
        0 has no channel split.  This assertion exists because that refusal was
        silently satisfying the retired test above by accident: the old check
        passed its ``because="probetype 0"`` on this message while believing it
        had exercised a reader refusal that no longer happens.
        """
        message = self.refuses(GOOD.replace('probe = "2DS"', 'probe = "2DC"'),
                               because="probetype 0")
        self.assertIn("orientation", message.lower())
        self.assertIn("read_binary_DMT", message)

    def test_the_other_spec_probe_is_accepted(self):
        (preset,) = self.mod.load_presets(
            self.write(GOOD.replace('probe = "2DS"', 'probe = "HVPS"')))
        self.assertEqual(preset.probe, "HVPS")

    def test_an_unknown_probe_carries_the_matlab_reason(self):
        self.refuses(GOOD.replace('probe = "2DS"', 'probe = "NOSUCHPROBE"'),
                     because="imgProc_sm.m:117")


class TheFileItselfIsChecked(_CampaignFileCase):
    def test_an_unknown_table_is_refused(self):
        self.refuses(GOOD + "\n[fidelity]\nprofile = 1\n", because="unknown table(s)")

    def test_an_empty_file_is_refused(self):
        self.refuses("# nothing here\n", because="no [[campaign]] entry")

    def test_a_missing_file_raises_rather_than_registering_nothing(self):
        with self.assertRaises(OSError):
            self.mod.load_presets(self.dir / "does_not_exist.toml")

    def test_the_documented_example_is_a_file_the_loader_accepts(self):
        """The example in ``load_presets``'s docstring is the one users will copy.

        An example that no longer loads is worse than none: it is read as a
        specification. So it is extracted and run rather than trusted.
        """
        doc = self.mod.load_presets.__doc__
        block = doc.split("[[campaign]]", 1)[1].split("\n\n", 1)[0]
        text = "[[campaign]]\n" + "\n".join(
            line.strip() for line in block.splitlines() if line.strip())
        (preset,) = self.mod.load_presets(self.write(text))
        self.assertEqual(preset.name, "ORACLES_2018_2DS_H")


class TheCommandLineReachesIt(_CampaignFileCase):
    """The loader is worth nothing if ``--preset`` cannot then name the campaign.

    ``--preset``'s ``choices`` is fixed when the argument is added, so a
    campaign registered after the parser was built would be rejected as unknown
    -- which is why ``--presets`` is read by a throwaway parser first.
    """

    def _main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(argv)
        return code, out.getvalue()

    @needs_v314_engine
    def test_a_declared_campaign_can_be_selected_from_the_command_line(self):
        # `--engine 3.1.4` became REQUIRED here on 2026-09-21, and the flag is the whole change
        # to this test. GOOD declares `project = "TESTCAMPAIGN"`, which is not ORACLES, and
        # a non-ORACLES preset with no `--engine` is refused before anything runs:
        # the 3.1.4 default would otherwise produce a number the engine-scope rule forbids
        # quoting. The engine
        # named is 3.1.4 rather than 3.5 only because this test is about preset SELECTION and
        # 3.1.4 keeps it a one-flag change -- the refusal itself is covered by
        # tests/test_engine_default_refused_off_oracles.py, which owns that boundary.
        path = self.write(GOOD)
        code, out = self._main(["--presets", str(path), "--preset", "TESTCAMPAIGN_2DS_V",
                                "--engine", "3.1.4", "--port-validation",
                                "--dry-run", "--out", str(self.dir / "out"),
                                str(self.dir / "base170101000000.2DS")])
        self.assertIn("declared campaign TESTCAMPAIGN_2DS_V", out)
        self.assertIn("preset TESTCAMPAIGN_2DS_V", out)
        self.assertEqual(self.mod.ACTIVE.name, "TESTCAMPAIGN_2DS_V")
        # The raw file does not exist, so preflight fails and --dry-run says so.
        # What is under test is that the campaign was accepted, not the run.
        self.assertEqual(code, 1)

    def test_the_provenance_is_logged_where_the_run_is_logged(self):
        path = self.write(GOOD)
        _, out = self._main(["--presets", str(path), "--preset", "TESTCAMPAIGN_2DS_V",
                             "--dry-run", "--out", str(self.dir / "out"),
                             str(self.dir / "base170101000000.2DS")])
        self.assertIn("reproduces nothing", out)

    def test_a_bad_campaign_file_stops_the_run_with_its_reason(self):
        path = self.write(GOOD.replace("TESTCAMPAIGN_2DS_V", "ORACLES_2016_2DS_H"))
        code, out = self._main(["--presets", str(path), "--dry-run",
                                "--out", str(self.dir / "out"),
                                str(self.dir / "base170101000000.2DS")])
        self.assertEqual(code, 2)
        self.assertIn("already a preset this driver ships", out)

    @needs_v314_engine
    def test_naming_the_built_in_default_preset_changes_nothing_else(self):
        """Formerly ``test_without_the_flag_nothing_changes``: before 2026-09-15 (R4s)
        ``--preset`` had a default and this asserted OMITTING it left ``ACTIVE`` untouched.
        ``--preset`` is required now (no argparse default to omit), so this instead names the
        same campaign explicitly and checks that doing so, with no ``--presets`` file, changes
        nothing about the campaign lookup itself."""
        code, out = self._main(["--preset", "ORACLES_2016_2DS_H", "--engine", "3.1.4",
                                "--port-validation", "--dry-run",
                                "--out", str(self.dir / "out"),
                                str(self.dir / "base170101000000.2DS")])
        self.assertNotIn("declared campaign", out)
        self.assertEqual(self.mod.ACTIVE.name, "ORACLES_2016_2DS_H")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
