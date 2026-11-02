# SPDX-License-Identifier: BSD-3-Clause
"""The campaign preset must reproduce the ORACLES call byte for byte.

WHY THIS EXISTS.  ``run_flight.py`` carried the ORACLES 2016 production call as
eight module-level constants, transcribed from ``uioops_testing/runsizedist.m``.
They are what fifteen validated flights were produced with, so a change to any
one of them changes what this project claims -- and the values are the kind that
fail quietly: a wrong ``sa_method`` or ``d_choice`` produces a plausible size
distribution, not an error.

On 2026-09-08 they became a named ``CampaignPreset`` so that a second
campaign, probe or channel is a new entry rather than an edit to the driver --
the package is meant for every campaign and hydrometeor type, and its only
end-to-end driver was wired to one deployment.  That refactor must not have moved
a value.  This file is the proof, and it states the expected values *literally*
rather than reading them from the preset: a test that asked the preset what the
preset says would pass no matter what the preset said.

The values below come from ``uioops_testing/runsizedist.m`` via the docstring
this driver has carried since it was written.  If one of them legitimately
changes, that is a fidelity decision and belongs in a commit that says so --
never a quiet edit here.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import unittest
from pathlib import Path

from tests._driver import driver_source

TOOLS = Path(__file__).resolve().parents[1] / "scripts"


def _load():
    """Import the driver by path -- ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("run_flight", module)
    spec.loader.exec_module(module)
    return module


#: The ORACLES 2016 production call, written out. Not derived from the code.
EXPECTED = {
    "probe": "2DS",
    "orientation": "H",
    "project": "ORACLES",
    "d_choice": 6,
    "sa_method": 0,
    "pres_pa": 9e5,
    "temp_c": 15.0,
}


class ThePresetIsTheOraclesCall(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_the_active_preset_matches_the_transcribed_call(self):
        active = self.mod.ACTIVE
        for field, want in EXPECTED.items():
            with self.subTest(field=field):
                self.assertEqual(
                    getattr(active, field), want,
                    f"{field} moved. This is the call fifteen validated flights were "
                    f"produced with; changing it is a fidelity decision, not a refactor.")

    #: The module names kept for the rest of the file, and the preset field each derives from.
    DERIVED = [("PROBE", "probe"), ("ORIENTATION", "orientation"), ("PROJECT", "project"),
               ("D_CHOICE", "d_choice"), ("SA_METHOD", "sa_method"),
               ("PRES_PA", "pres_pa"), ("TEMP_C", "temp_c")]

    def test_the_module_names_agree_with_the_preset(self):
        m = self.mod
        for name, field in self.DERIVED:
            with self.subTest(name=name):
                self.assertEqual(
                    getattr(m, name), getattr(m.ACTIVE, field),
                    f"{name} no longer equals ACTIVE.{field}.")

    def test_the_module_names_are_derived_and_not_typed_again(self):
        """Value equality cannot see this, which is the point.

        A constant re-typed with the *same* value passes every value check ever
        written and then drifts the first time the preset changes. Mutation
        testing caught exactly that on 2026-09-08: replacing ``PROBE =
        ACTIVE.probe`` with ``PROBE = "2DS"`` was denied by nothing, because
        "2DS" is what the preset says. So this reads the source instead.
        """
        src = driver_source("run_flight.py").read_text(encoding="utf-8")
        typed = []
        for name, field in self.DERIVED:
            want = f"{name} = ACTIVE.{field}"
            if want not in src:
                typed.append(f"{name} is not written as `{want}`")
        self.assertEqual(
            typed, [],
            "A module constant is typed rather than derived from ACTIVE. It agrees "
            "today and drifts the moment the preset changes -- which no value "
            f"comparison can detect. {typed}")

    def test_every_preset_names_where_it_came_from(self):
        """A preset whose origin nobody can name is a set of numbers somebody guessed."""
        for name, preset in self.mod.PRESETS.items():
            with self.subTest(preset=name):
                self.assertTrue(
                    preset.provenance and preset.provenance.strip(),
                    f"preset {name} has no provenance. Say which driver script or "
                    f"campaign document its values were transcribed from.")
                self.assertEqual(
                    preset.name, name,
                    f"preset registered as {name!r} calls itself {preset.name!r}")

    def test_the_registry_contains_the_active_preset(self):
        self.assertIn(
            self.mod.ACTIVE.name, self.mod.PRESETS,
            "the active preset is not in PRESETS, so nothing could select it by name")

    def test_a_preset_is_immutable(self):
        """Chosen whole, by name -- never assembled field by field at runtime."""
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.mod.ACTIVE.orientation = "V"  # type: ignore[misc]


class SwitchingThePresetReachesEverythingDerivedFromIt(unittest.TestCase):
    """``use_preset`` must move every name, including the ones bound early.

    **The trap, and the reason this class executes the switch instead of reading
    the code.** ``run_flight`` keeps the preset's fields as module globals
    because the whole file, its tests and two flat shims read them that way, so
    ``use_preset`` rebinds those globals. A rebound global does not reach a
    *default argument*: ``def f(channels=ORIENTATION)`` captures the value when
    the ``def`` executes. ``image_call_label`` had exactly that signature, so
    after switching to a V preset it would have gone on stamping ``H`` -- onto a
    file written as ``.V.cdf``, which the next stage then reads the stamp of and
    accepts. Every configuration stamp in this driver exists to stop precisely
    that class of silent mismatch.

    Value equality on the constants cannot see it, and neither can reading the
    source. Only calling the function after the switch can, which is what this
    does.
    """

    def setUp(self):
        self.mod = _load()
        self.addCleanup(self.mod.use_preset, self.mod.ACTIVE.name)

    def test_every_derived_name_follows_the_switch(self):
        m = self.mod
        chosen = m.use_preset("ORACLES_2017_2DS_V")
        self.assertIs(m.ACTIVE, chosen)
        for name, field in ThePresetIsTheOraclesCall.DERIVED:
            with self.subTest(name=name):
                self.assertEqual(
                    getattr(m, name), getattr(chosen, field),
                    f"{name} did not follow use_preset. Add it to use_preset's "
                    f"global rebinding -- a name left behind keeps the previous "
                    f"campaign's value silently.")
        self.assertEqual(m.ORIENTATION, "V")

    def test_the_stamp_follows_the_switch(self):
        """The default-argument trap, executed rather than reasoned about."""
        m = self.mod
        before = m.image_call_label()
        self.assertIn("channels=H", before,
                      "the stamp does not name the channel any more; re-anchor "
                      "this test rather than dropping it.")
        m.use_preset("ORACLES_2017_2DS_V")
        after = m.image_call_label()
        self.assertIn(
            "channels=V", after,
            "image_call_label still stamps the orientation this module was "
            "imported with. A default argument binds at definition time, so it "
            "must resolve from ACTIVE inside the body. As written, a .V.cdf "
            "would carry an H stamp and the next stage would accept it: "
            f"{after!r}")

    def test_an_output_path_follows_the_switch(self):
        m = self.mod
        out = Path("out")
        h = m.proc_path("base170817073523", out)
        m.use_preset("ORACLES_2017_2DS_V")
        v = m.proc_path("base170817073523", out)
        self.assertNotEqual(
            h, v,
            "the proc path does not carry the channel, so an H run and a V run "
            "of the same flight would write to one file and the second would "
            "silently overwrite the first")
        self.assertIn(".V", v.name)

    def test_an_unknown_preset_names_what_is_known(self):
        with self.assertRaises(KeyError) as caught:
            self.mod.use_preset("NOT_A_CAMPAIGN")
        message = str(caught.exception)
        self.assertIn("ORACLES_2016_2DS_H", message,
                      "the error does not list the presets that do exist, which "
                      "is the one thing the caller needs")

    def test_the_switch_is_reachable_from_the_command_line(self):
        """A preset nothing can select is a preset that does not exist."""
        src = driver_source("run_flight.py").read_text(encoding="utf-8")
        self.assertIn('"--preset"', src,
                      "run_flight.py has presets but no --preset flag, so the "
                      "only end-to-end driver still serves one campaign")
        self.assertIn("choices=sorted(PRESETS)", src,
                      "--preset does not offer the registry, so a new preset "
                      "would be unselectable until someone edited the flag too")


class TheVerticalChannelPresetDoesNotClaimValidation(unittest.TestCase):
    """It makes the channel reachable. That is all it may say.

    The nine 2017 V products of record exist and none has been reproduced, so
    this preset is a *capability*, not a result. The distinction is exactly the
    one this project keeps having to make -- ``run_flight.py`` could not target
    the V channel at all until 2026-09-09, and the fix for that is reach, not
    evidence. If a V product is later reproduced, this test is what has to be
    changed deliberately, in the commit that says so.
    """

    def setUp(self):
        self.mod = _load()

    def test_it_says_it_is_not_validated(self):
        preset = self.mod.PRESETS["ORACLES_2017_2DS_V"]
        self.assertIn(
            "NOT YET VALIDATED", preset.provenance,
            "the V preset no longer says it is unvalidated. If that is because a "
            "2017 V product has now been reproduced, say so here and cite the "
            "run; do not simply delete the caveat.")

    def test_it_differs_from_the_validated_call_only_in_the_channel(self):
        """Anything else differing would be an unstated fidelity decision."""
        h = self.mod.PRESETS["ORACLES_2016_2DS_H"]
        v = self.mod.PRESETS["ORACLES_2017_2DS_V"]
        differing = sorted(
            f.name for f in dataclasses.fields(h)
            if f.name not in ("name", "provenance")
            and getattr(h, f.name) != getattr(v, f.name))
        self.assertEqual(
            differing, ["orientation"],
            "the V preset differs from the validated call in more than the "
            f"channel: {differing}. Each extra difference is a fidelity decision "
            f"and needs its own provenance, not a shared one.")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
