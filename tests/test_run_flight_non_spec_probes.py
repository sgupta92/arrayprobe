# SPDX-License-Identifier: BSD-3-Clause
"""What the one-command driver does with a probe that is not a SPEC probe.

WHY THIS EXISTS (2026-09-17).  ``run_flight.py`` is the only end-to-end entry
point, and it decoded with ``read_binary_SPEC`` alone.  The rule that said so
lived as an inline ``probetype != 2`` inside :func:`load_presets` -- i.e. on the
path a ``--presets`` *file* takes, and on no other path.  A built-in preset or a
``--config`` run naming a CIP therefore walked straight into ``stage2`` and
would have decoded a DMT file with the SPEC decoder: a plausible, wrong
``.H.cdf``, which is the failure this driver's whole ``.call`` machinery exists
to prevent.  The gate now lives in one table, :data:`run_flight.S2_READERS`,
read by both.

WHERE THE BOUNDARY IS NOW (2026-09-18).  **Probetype 1 -- CIP and PIP --
is drivable.**  The blocker was never a missing reader; it was that the driver's
S2 contract wrote an H/V *pair* and had no name for a file that was never split.
:func:`run_flight.channel_token` is that name: the segment between stem and
suffix is the **channel** for a SPEC probe (``base….H.cdf``, unchanged byte for
byte, which is what keeps the fifteen validated flights' names and stamps as
they were) and the **probe** for a single-channel one (``<stem>.CIP.cdf``, the
name ``read_binary_SEA`` already writes of its own accord).

**Probetypes 0 and 3 -- 2DC, 2DP, Fast2DC -- became drivable 2026-09-19.**
``channel_token`` needed no change for them either; it was already
probetype-agnostic beyond the SPEC case (the ``== 2`` branch is its only special
case).  The actual gap was inside :func:`run_flight.stage2`: ``read_binary_PMS``
writes all three probe-identity outputs from one decode, under its own
lowercase names (``.2dc.cdf``/``.f2dc.cdf``/``.2dp.cdf``), which do not match the
uppercase name the naming convention already built -- a one-rename gap, not a
naming-schema one, settled by a naming decision in September 2026. Every
probetype S2 knows is now drivable; there is no probetype left for this file to
keep a "still refuses" case open on.

WHAT THIS FILE REFUSES TO LET DRIFT.

1. **A half-applied naming convention**, which is worse than none: it would
   produce files whose names imply a channel split that did not happen.  Four
   sites build or read that segment, and the tests below reach them through the
   driver's own functions -- including real calls into :func:`run_flight.stage3`
   and :func:`run_flight.stage4`, which return their target path before touching
   any file, so what is asserted is the code that runs and not a restatement of
   it.
2. **A stamp without its engine key.**  The hand-written lane scripts that
   produced every CIP result before today rolled their own JSON sidecars with no
   ``engine=``, and that is how a v3.1.4 CIP product came to be described as v3.5
   for a full day.  Every stamp this driver writes, on every probetype,
   names its engine.
3. **The refusal's factual claim, for the readers whose own signature makes it
   true.** It says the PMS/DMT/SEA readers do not split channels; that is
   asserted against the readers' own signatures rather than against the table
   that states it, so the two sides come from different places -- true whether
   or not the probetype it describes is currently drivable.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

from tests._driver import driver_source
from tests._repo import (
    needs_enhancements,
    needs_file,  # noqa: E402
    needs_v314_engine,  # noqa: E402
)

TOOLS = Path(__file__).resolve().parents[1] / "scripts"


def _load():
    """Import the driver by path -- ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("run_flight", module)
    spec.loader.exec_module(module)
    return module


def _write_synthetic_pms(raw: Path) -> None:
    """A three-record PMS file (2DC, 2DP, F2DC 'C4'), the record shape ``test_pms.py`` uses."""
    import struct

    import numpy as np

    def record(tag, second):
        header = struct.pack(">9H", 6, 6, second, 2016, 9, 6, 100, 0, 5)
        return bytes(tag) + header + bytes(np.zeros(4096, dtype=np.uint8))

    with open(raw, "wb") as fh:
        fh.write(b'<?xml version="1.0"?>\n<OAP>\n</OAP>\n')
        fh.write(record((67, 49), 1))  # 2DC
        fh.write(record((80, 1), 2))   # 2DP
        fh.write(record((67, 52), 3))  # F2DC 'C4'


#: Written out, not read from the port: this is what the probe registry said on
#: 2026-09-17, and a probe silently changing probetype would change which
#: decoder the driver reaches for.
EXPECTED_PROBETYPES = {
    "2DC": 0, "2DP": 0,
    "CIP": 1, "PIP": 1,
    "2DS": 2, "HVPS": 2,
    "Fast2DC": 3,
}

#: The probes that still have no driver path, and the ones that do.  Changing
#: either set is a deliberate act with a run behind it, which is why they are
#: written here rather than read from :data:`run_flight.S2_READERS`.  Empty
#: since 2026-09-19: every probetype S2 knows is now drivable.
STILL_REFUSED: tuple[str, ...] = ()
DRIVABLE = ("2DS", "HVPS", "CIP", "PIP", "2DC", "2DP", "Fast2DC")


class _WithPreset(unittest.TestCase):
    """A fixture that restores the module-level preset, whatever the test did."""

    def setUp(self):
        self.mod = _load()
        self._saved = self.mod.ACTIVE

    def tearDown(self):
        self.mod.use_preset(self._saved.name)


class EveryProbeGetsAnAnswer(_WithPreset):
    """No probe may fall off the table by being forgotten."""

    def test_every_probe_the_port_knows_is_classified(self):
        from arrayprobe import constants
        for probe in sorted(constants.IMGPROC_CONFIG):
            with self.subTest(probe=probe):
                plan = self.mod.s2_reader_for(probe)
                self.assertEqual(plan.probe, probe)
                self.assertIn(plan.probetype, self.mod.S2_READERS)
                self.assertTrue(plan.reader, "every probetype names its decoder")

    def test_the_probetype_of_each_probe_is_what_the_table_was_built_for(self):
        for probe, probetype in EXPECTED_PROBETYPES.items():
            with self.subTest(probe=probe):
                self.assertEqual(self.mod.s2_reader_for(probe).probetype, probetype)

    def test_an_unknown_probe_is_refused_by_name(self):
        with self.assertRaises(self.mod.UnsupportedProbe) as caught:
            self.mod.s2_reader_for("NOT_A_PROBE")
        self.assertIn("NOT_A_PROBE", str(caught.exception))

    def test_the_boundary_is_exactly_where_it_is_claimed_to_be(self):
        """THE boundary test.  Move it only with a measurement behind the move."""
        supported = {p for p in EXPECTED_PROBETYPES
                     if self.mod.s2_reader_for(p).supported}
        self.assertEqual(supported, set(DRIVABLE))

    def test_an_undrivable_probe_names_its_blocker_and_a_drivable_one_does_not(self):
        for probe in DRIVABLE:
            with self.subTest(probe=probe):
                self.assertEqual(self.mod.s2_reader_for(probe).blocker, "")
        for probe in STILL_REFUSED:
            with self.subTest(probe=probe):
                blocker = self.mod.s2_reader_for(probe).blocker
                self.assertIn("channel split", blocker)
                self.assertIn("the template", blocker)


class TheBlockerIsMeasuredAgainstTheReaders(_WithPreset):
    """The refusal's claim, checked against the readers rather than restated.

    The claim: ``read_binary_SPEC`` splits H/V and the non-SPEC readers do not.
    For probetypes 0 and 3 that is still why the driver refuses.  For probetype 1
    it is still true, and is now the reason the *name* carries the probe rather
    than a channel letter -- so the same signature fact is load-bearing on both
    sides of the boundary, and is asserted once here for both.
    """

    @needs_v314_engine
    def test_the_spec_reader_takes_channels_and_the_others_do_not(self):
        from arrayprobe.readers import dmt, pms, sea, spec
        self.assertIn(
            "channels", inspect.signature(spec.read_binary_SPEC).parameters,
            "if the SPEC reader stopped splitting channels the S2 contract moved")
        for reader in (dmt.read_binary_DMT, pms.read_binary_PMS, sea.read_binary_SEA):
            with self.subTest(reader=reader.__name__):
                self.assertNotIn(
                    "channels", inspect.signature(reader).parameters,
                    f"{reader.__name__} grew a channels argument. For PMS that means the "
                    f"blocker in run_flight.S2_READERS is no longer true and probetype 0/3 "
                    f"can be wired up; for DMT/SEA it means channel_token()'s reason for "
                    f"naming the probe instead of a channel has changed. Either way, re-check "
                    f"each row's recorded reason before touching the table")

    @needs_v314_engine
    def test_the_table_points_at_readers_that_exist(self):
        import importlib
        dotted_names = {d for d, _s in self.mod.S2_READERS.values()}
        for formats in self.mod.S2_FORMATS.values():
            dotted_names.update(formats.values())
        for dotted in sorted(dotted_names):
            with self.subTest(reader=dotted):
                module_name, _, attr = dotted.rpartition(".")
                module = importlib.import_module(module_name)
                self.assertTrue(callable(getattr(module, attr)),
                                f"{dotted} is not a callable this driver could call")


class OneFormatPerFileAndNoGuessing(_WithPreset):
    """A `.sea` and a `.cip` are different containers, and each would decode the
    other into plausible nonsense.  The driver picks by extension and refuses an
    extension it cannot identify, rather than choosing for the user."""

    def test_each_known_extension_reaches_its_own_reader(self):
        self.assertEqual(self.mod.s2_reader_for_raw("CIP", Path("f/2016_09_06.sea")),
                         "arrayprobe.readers.sea.read_binary_SEA")
        self.assertEqual(self.mod.s2_reader_for_raw("CIP", Path("f/16_09_06.cip")),
                         "arrayprobe.readers.dmt.read_binary_DMT")

    def test_the_extension_match_is_case_insensitive(self):
        self.assertEqual(self.mod.s2_reader_for_raw("CIP", Path("f/A.SEA")),
                         "arrayprobe.readers.sea.read_binary_SEA")

    def test_an_unknown_extension_is_refused_and_names_the_known_ones(self):
        with self.assertRaises(self.mod.UnsupportedProbe) as caught:
            self.mod.s2_reader_for_raw("CIP", Path("f/base160906064403.2DS"))
        message = str(caught.exception)
        self.assertIn(".sea", message)
        self.assertIn(".cip", message)

    def test_a_single_format_probetype_does_not_consult_the_file_name(self):
        """SPEC has one container, so any name reaches ``read_binary_SPEC``."""
        self.assertEqual(self.mod.s2_reader_for_raw("2DS", Path("f/anything.at.all")),
                         "arrayprobe.readers.spec.read_binary_SPEC")


class TheNamingConventionIsAppliedWholeOrNotAtAll(_WithPreset):
    """The piece that had to be coherent: one segment, four sites, one answer.

    A half-applied convention writes a file whose name asserts a channel split
    that never happened, which is the misleading-provenance failure this
    whole line of work exists to stop.  ``stage3`` and ``stage4`` are CALLED
    here, not paraphrased: both compute their target path and return it before
    opening anything, so a divergence between them and ``proc_path``/``sd_path``
    fails this test instead of writing a stray file at three in the morning.
    """

    def _names(self, preset: str, stem: str):
        self.mod.use_preset(preset)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            image = self.mod.image_path(stem, out)
            return {
                "image": image.name,
                "proc": self.mod.proc_path(stem, out).name,
                "sd": self.mod.sd_path(stem, out).name,
                "stage3": self.mod.stage3(image, out).name,
                "stage4": self.mod.stage4(self.mod.proc_path(stem, out), stem, out).name,
                "stamp": self.mod.image_call_label(),
            }

    def test_a_spec_preset_is_byte_for_byte_what_it_always_was(self):
        names = self._names("ORACLES_2016_2DS_H", "base160906064403")
        self.assertEqual(names["image"], "base160906064403.H.cdf")
        self.assertEqual(names["proc"], "proc.base160906064403.H.nc")
        self.assertEqual(names["sd"], "sd.base160906064403.H.nc")
        self.assertIn("channels=H", names["stamp"])

    def test_a_single_channel_preset_names_the_probe_and_never_a_channel(self):
        names = self._names("UND_2016_CIP", "2016_09_06_06_40_17")
        self.assertEqual(names["image"], "2016_09_06_06_40_17.CIP.cdf")
        self.assertEqual(names["proc"], "proc.2016_09_06_06_40_17.CIP.nc")
        self.assertEqual(names["sd"], "sd.2016_09_06_06_40_17.CIP.nc")
        for key in ("image", "proc", "sd"):
            with self.subTest(name=key):
                self.assertNotIn(".H.", names[key])
                self.assertNotIn(".V.", names[key])
        self.assertIn("channels=none", names["stamp"])

    def test_stage3_and_stage4_agree_with_the_path_functions_for_every_preset(self):
        """The half-applied-convention guard, over every shipped campaign."""
        for preset in sorted(self.mod.PRESETS):
            with self.subTest(preset=preset):
                names = self._names(preset, "some_flight_stem")
                self.assertEqual(names["stage3"], names["proc"])
                self.assertEqual(names["stage4"], names["sd"])

    def test_the_channel_token_is_the_channel_for_spec_and_the_probe_otherwise(self):
        for preset, expected in (("ORACLES_2016_2DS_H", "H"),
                                 ("ORACLES_2017_2DS_V", "V"),
                                 ("UND_2016_CIP", "CIP")):
            with self.subTest(preset=preset):
                self.mod.use_preset(preset)
                self.assertEqual(self.mod.channel_token(), expected)


class EveryStampNamesItsEngine(_WithPreset):
    """The thing the hand-written lane scripts omitted.

    A CIP `.call` written by a lane script was a JSON blob with no ``engine``
    key at all, so a v3.1.4 product read as whatever the reader assumed.  Every
    label this driver writes starts with its engine, on every probetype.
    """

    def test_the_cip_s2_stamp_starts_with_its_engine(self):
        self.mod.use_preset("UND_2016_CIP")
        self.assertTrue(self.mod.image_call_label().startswith("engine=3.1.4 "),
                        self.mod.image_call_label())

    def test_the_engine_key_is_what_changes_when_the_engine_does(self):
        self.mod.use_preset("UND_2016_CIP")
        v314 = self.mod.image_call_label()
        saved = self.mod.ENGINE
        try:
            self.mod.ENGINE = "3.5"
            v35 = self.mod.image_call_label()
        finally:
            self.mod.ENGINE = saved
        self.assertTrue(v35.startswith("engine=3.5 "), v35)
        self.assertNotEqual(v314, v35,
                            "two engines' decodes must not share one stamp: that is exactly "
                            "how a v3.1.4 CIP product got described as v3.5")

    def test_every_cip_stage_stamp_names_the_engine(self):
        self.mod.use_preset("UND_2016_CIP")
        for name, label in (("S2", self.mod.image_call_label()),
                            ("S3", self.mod.proc_call_label()),
                            ("S4", self.mod.sd_call_label(self.mod.IAT_FILE))):
            with self.subTest(stage=name):
                self.assertTrue(label.startswith("engine="), f"{name}: {label}")

    def test_the_cip_stamp_claims_no_profile_the_decoder_never_read(self):
        """``read_binary_SEA`` and ``read_binary_DMT`` take no profile, so naming
        one would be as false as naming a channel."""
        self.mod.use_preset("UND_2016_CIP")
        label = self.mod.image_call_label()
        self.assertNotIn("profile=", label)
        self.assertNotIn("spec_buffer_guard", label)


class TheDeclaredCampaignGateStillRefuses(_WithPreset):
    """``--presets`` must not be able to register an undrivable campaign, and
    must not be able to register a drivable one that lies about its channel."""

    def _write(self, tmp: Path, probe: str, orientation: str = "H") -> Path:
        path = tmp / "camps.toml"
        path.write_text(
            "[[campaign]]\n"
            'name = "TEST_CAMPAIGN"\n'
            f'probe = "{probe}"\n'
            f'orientation = "{orientation}"\n'
            'project = "TEST"\n'
            "d_choice = 6\n"
            "sa_method = 0\n"
            "pres_pa = 9e5\n"
            "temp_c = 15.0\n"
            'provenance = "a test, not a campaign"\n',
            encoding="utf-8")
        return path

    def test_a_2dc_campaign_is_accepted_and_names_the_probe(self):
        """Was ``..._is_refused_with_the_structural_reason`` until 2026-09-19
        2DC (probetype 0) is drivable now, the same way CIP became
        drivable on 2026-09-18 -- see
        ``test_a_cip_campaign_declaring_none_is_accepted_and_names_the_probe``
        just below, the precedent this mirrors."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "2DC", orientation="none")
            try:
                loaded = self.mod.load_presets(path)
                self.assertEqual(loaded[0].probe, "2DC")
                self.mod.use_preset("TEST_CAMPAIGN")
                self.assertEqual(self.mod.channel_token(), "2DC")
            finally:
                self.mod.PRESETS.pop("TEST_CAMPAIGN", None)

    def test_a_2dc_campaign_may_not_declare_a_channel_it_does_not_have(self):
        """The orientation rule (probetype != 2 => 'none') is generic, asserted
        here for a PMS probe the same way it already is for CIP below."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "2DC", orientation="H")
            with self.assertRaises(self.mod.PresetFileError) as caught:
                self.mod.load_presets(path)
            self.assertIn("'none'", str(caught.exception))
            self.assertNotIn("TEST_CAMPAIGN", self.mod.PRESETS)

    def test_an_unknown_probe_in_a_campaign_file_is_a_preset_file_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "NOT_A_PROBE")
            with self.assertRaises(self.mod.PresetFileError):
                self.mod.load_presets(path)

    def test_a_cip_campaign_may_not_declare_a_channel_it_does_not_have(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "CIP", orientation="H")
            with self.assertRaises(self.mod.PresetFileError) as caught:
                self.mod.load_presets(path)
            self.assertIn("'none'", str(caught.exception))
            self.assertNotIn("TEST_CAMPAIGN", self.mod.PRESETS)

    def test_a_cip_campaign_declaring_none_is_accepted_and_names_the_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "CIP", orientation="none")
            try:
                loaded = self.mod.load_presets(path)
                self.assertEqual(loaded[0].probe, "CIP")
                self.mod.use_preset("TEST_CAMPAIGN")
                self.assertEqual(self.mod.channel_token(), "CIP")
            finally:
                self.mod.PRESETS.pop("TEST_CAMPAIGN", None)

    def test_a_spec_campaign_may_not_declare_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "2DS", orientation="none")
            with self.assertRaises(self.mod.PresetFileError) as caught:
                self.mod.load_presets(path)
            self.assertIn("'H' or 'V'", str(caught.exception))


class TheShippedCipPresetSaysWhatItIs(_WithPreset):
    """A preset is a scientific claim, so this one's provenance has to carry its
    own limits -- there is no CIP raw+processed reference pair on this machine,
    so nothing produced through it has been validated against a UIOOPS product."""

    def test_the_cip_preset_is_shipped_and_reaches_probetype_1(self):
        self.assertIn("UND_2016_CIP", self.mod.PRESETS)
        preset = self.mod.PRESETS["UND_2016_CIP"]
        self.assertEqual(preset.probe, "CIP")
        self.assertEqual(preset.orientation, "none")
        self.assertEqual(self.mod.s2_reader_for(preset.probe).probetype, 1)

    def test_its_provenance_names_its_source_and_refuses_to_claim_validation(self):
        provenance = self.mod.PRESETS["UND_2016_CIP"].provenance
        self.assertIn("NOT VALIDATED", provenance)
        self.assertIn("cip_s1", provenance,
                      "the provenance must name the lane-script sidecars it came from")


class Stage2RefusesBeforeItDecodes(_WithPreset):
    """The gate that did not exist before 2026-09-17.

    ``load_presets`` never sees a built-in or a ``--config`` preset, so this is
    the only thing standing between a still-refused probe and
    ``read_binary_SPEC``.  It must fire **before** any file is opened -- a
    refusal after a three-hour decode is not a refusal.
    """

    def test_stage2_decodes_a_2dc_preset_and_names_it_per_channel_token(self):
        """Was ``..._refuses_a_2dc_preset_without_touching_the_raw_file`` until
        2026-09-19: 2DC (probetype 0) is drivable now, so this
        asserts the September 2026 naming decision
        against a real :func:`run_flight.stage2` decode, not a restatement of
        it. No real 2DC raw file exists on this machine (confirmed absent
        again for this task); this is a fixture-level check, not an
        archived-product validation -- the same synthetic-record shape
        ``test_pms.py`` uses for the reader itself."""
        twodc = dataclasses.replace(self._saved, name="TEST_ONLY_2DC", probe="2DC",
                                    orientation="none")
        self.mod.PRESETS[twodc.name] = twodc
        try:
            self.mod.use_preset(twodc.name)
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                raw = out / "flight.PMS"
                _write_synthetic_pms(raw)
                target = self.mod.stage2(raw, out)
                self.assertEqual(target.name, "flight.2DC.cdf")
                self.assertEqual(target, self.mod.image_path("flight", out))
                self.assertTrue(target.exists())
                # The two siblings from the SAME decode, published untouched
                # under read_binary_PMS's own (lowercase, unrenamed) names --
                # the same shape as read_binary_SEA's unread sibling.
                self.assertTrue((out / "flight.f2dc.cdf").exists())
                self.assertTrue((out / "flight.2dp.cdf").exists())
                self.assertIn("probe=2DC", self.mod.read_stamp(target))
                # Inventory keys describe the input, not the configuration (driven stage2
                # writes none today; a main()-driven decode would).
                self.assertEqual(self.mod._strip_inventory(self.mod.read_stamp(target) or ""),
                                 self.mod.image_call_label())
                # The siblings carry no stamp of their own -- only the
                # requested probe's file is asserted current.
                self.assertIsNone(self.mod.read_stamp(out / "flight.f2dc.cdf"))
        finally:
            self.mod.PRESETS.pop(twodc.name, None)

    def test_a_non_spec_decode_stamps_the_raw_inventory_like_a_spec_one(self):
        """The non-SPEC S2 branch wrote ``want`` alone until 2026-10-28, so only 2D-S/HVPS
        decodes carried the inventory ``inventory_preflight`` promises every decode."""
        import hashlib

        twodc = dataclasses.replace(self._saved, name="TEST_ONLY_2DC", probe="2DC",
                                    orientation="none")
        self.mod.PRESETS[twodc.name] = twodc
        try:
            self.mod.use_preset(twodc.name)
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                raw = out / "flight.PMS"
                _write_synthetic_pms(raw)
                sha = hashlib.sha256(raw.read_bytes()).hexdigest()
                self.assertEqual(self.mod.inventory_preflight([raw]), 0)
                stamp = self.mod.read_stamp(self.mod.stage2(raw, out)) or ""
                self.assertIn("inventory_empty=0", stamp)
                self.assertIn(f"raw_sha256={sha}", stamp)
                self.assertEqual(self.mod._strip_inventory(stamp), self.mod.image_call_label())
        finally:
            self.mod.INVENTORY_ROWS.clear()
            self.mod.PRESETS.pop(twodc.name, None)

    def test_stage2_refuses_an_unidentifiable_cip_container_before_decoding(self):
        """The new silent-wrong-output path, closed where the old one was."""
        self.mod.use_preset("UND_2016_CIP")
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nothing.bin"
            with self.assertRaises(self.mod.UnsupportedProbe) as caught:
                self.mod.stage2(missing, Path(tmp))
            self.assertIn(".sea", str(caught.exception))

    def test_stage2_refuses_s2_jobs_for_a_probe_with_no_parallel_reader(self):
        """A flag that silently means nothing is how a speed claim becomes untrue."""
        self.mod.use_preset("UND_2016_CIP")
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "flight.sea"
            raw.write_bytes(b"")
            with self.assertRaises(self.mod.UnsupportedProbe) as caught:
                self.mod.stage2(raw, Path(tmp), s2_jobs=4)
            self.assertIn("--s2-jobs", str(caught.exception))

    def test_the_refusal_is_reported_as_REFUSED_not_as_a_crash(self):
        """``main`` labels it REFUSED, alongside UnverifiableProvenance."""
        source = driver_source("run_flight.py").read_text(encoding="utf-8")
        self.assertIn("except (UnverifiableProvenance, UnsupportedProbe) as exc:", source)


class TheDecodedNameIsTheReadersNotTheEngines(_WithPreset):
    """S2's extension belongs to the reader that writes the file.

    **The incident, 2026-09-21.** The first CIP run through this driver under
    ``--engine 3.5`` decoded all 23,939 records correctly into
    ``<stem>.CIP.cdf`` -- and then failed with *"S2 did not leave a current
    <stem>.CIP.nc -- a prerequisite was silently missing"*. 4.4 minutes and
    2.6 GB spent writing exactly the right file under a name the next stage
    never looked for, because ``_IMAGE_SUFFIX`` was keyed on the **engine**
    while the suffix is a property of the **reader**.

    Only probetype 2 has a v3.5 decoder of its own (``arrayprobe_uiops/spec.py``),
    so only probetype 2's name moves with ``--engine``. ``read_binary_SEA`` is
    byte-identical between the two vendored MATLAB trees and writes ``.cdf``
    either way (``readers/sea.py:167``); ``read_binary_PMS`` and
    ``read_binary_DMT`` have no v3.5 variant at all.

    Checked in both engines and on both sides of the boundary, because a fix
    that quietly renamed probetype 2's v3.5 output would break the naming of
    every 2D-S file this project has written.
    """

    def _with_engine(self, engine: str):
        saved = self.mod.ENGINE
        self.mod.ENGINE = engine
        self.addCleanup(setattr, self.mod, "ENGINE", saved)

    def test_a_non_spec_probe_keeps_cdf_under_both_engines(self):
        for probe in ("CIP", "PIP", "2DC", "2DP", "Fast2DC"):
            for engine in ("3.1.4", "3.5"):
                with self.subTest(probe=probe, engine=engine):
                    self._with_engine(engine)
                    self.assertEqual(
                        ".cdf", self.mod.image_suffix_for_probe(probe),
                        f"{probe} decodes through a reader shipped once for both "
                        f"engines, which writes .cdf; naming it .nc under engine "
                        f"{engine} is what made the CIP run decode 2.6 GB and then "
                        "report its own output missing")

    def test_a_spec_probe_still_follows_the_engine(self):
        """The half that must not regress: 2D-S naming is unchanged."""
        for probe in ("2DS", "HVPS"):
            for engine, want in (("3.1.4", ".cdf"), ("3.5", ".nc")):
                with self.subTest(probe=probe, engine=engine):
                    self._with_engine(engine)
                    self.assertEqual(
                        want, self.mod.image_suffix_for_probe(probe),
                        "probetype 2 is the one probetype with a v3.5 decoder of "
                        "its own, so its suffix does follow the engine -- and "
                        "fifteen validated flights' file names depend on it")

    def test_image_path_uses_the_reader_aware_suffix(self):
        """The call site, not only the helper -- the defect was at the call site."""
        source = driver_source("run_flight.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "_IMAGE_SUFFIX[ENGINE]}", source,
            "image_path is interpolating the engine-keyed table directly again; "
            "use image_suffix_for_probe(), which asks which reader writes the file")


class TheCipChainReachesStage4OnEngine35(unittest.TestCase):
    """Step 1 of the September 2026 CIP driver plan, as corrected by the root
    cause found for the first CIP run's stage-4 failure.

    The first CIP run through the driver died in S4 because its TAS spanned the
    UTC ``Time`` axis, while v3.5 ``sizeDist.m:758-759`` builds ``starttime`` from
    the TAS file's timestamps and ``:918`` indexes the particle blocks keyed on
    the **probe clock** (``particle_time``, hhmmss). On this fixture the probe
    clock reads 000013..000141 while UTC reads 180334..180502, so a UTC-span TAS
    runs ``starttime`` past the last particle block. That death is upstream
    behaviour, preserved in the engine; the driver's S4 particle-clock guard now
    refuses the run before reaching it, and the second test pins the refusal.

    ``--protective off``: the protective set (``particle_time_glitch_fix``,
    default-ON for CIP) runs its own S4 on the enhanced proc straight after S3,
    before this test can write the TAS file, and fails the whole run with
    "no <stem>.tas.csv". The protective chain is not under test here.
    """

    STEM = "2016_09_06_06_40_17"
    COMMON = ["--preset", "UND_2016_CIP", "--engine", "3.5", "--profile", "stock-v3.5",
              "--protective", "off"]

    @classmethod
    def setUpClass(cls):
        import shutil
        cls.mod = _load()
        cls._saved = cls.mod.ACTIVE
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.addClassCleanup(lambda: cls.mod.use_preset(cls._saved.name))
        root = Path(cls._tmp.name)
        cls.raw = root / f"{cls.STEM}.sea"
        shutil.copyfile(Path(__file__).parent / "data" / "sea_raw_synthetic.sea", cls.raw)
        cls.s3_out = root / "s3"
        cls.rc23, cls.log23 = cls._main(cls.raw, cls.s3_out, "23")

    @classmethod
    def _main(cls, raw, out, stages):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = cls.mod.main([str(raw), *cls.COMMON, "--stages", stages, "--out", str(out)])
        return rc, buf.getvalue()

    @needs_file("scripts/cip_housekeeping_tas.py")
    def _stage4_with_tas(self, name, lo, hi):
        """Copy the S2/S3 outputs, write a constant-TAS file over ``lo..hi`` s of day, run S4."""
        import shutil

        import numpy as np
        spec = importlib.util.spec_from_file_location(
            "cip_housekeeping_tas", TOOLS / "cip_housekeeping_tas.py")
        tasmod = importlib.util.module_from_spec(spec)
        # @dataclass looks its module up in sys.modules, so register before exec.
        tasmod = sys.modules.setdefault("cip_housekeeping_tas", tasmod)
        spec.loader.exec_module(tasmod)
        out = Path(self._tmp.name) / name
        shutil.copytree(self.s3_out, out)
        sod = np.arange(lo, hi + 1, dtype=np.int64)
        # 100 m/s is NOT a measurement: this fixture has no usable airspeed, and the
        # test is about the clock frame the TAS series is indexed in, not its values.
        tasmod.write_tas_csv(out / f"{self.STEM}.tas.csv", sod, np.full(sod.shape, 100.0))
        rc, text = self._main(self.raw, out, "4")
        return out, rc, text

    @staticmethod
    def _insec(hhmmss):
        h = int(hhmmss)
        return (h // 10000) * 3600 + ((h // 100) % 100) * 60 + h % 100

    def _particle_span(self):
        from netCDF4 import Dataset
        with Dataset(self.s3_out / f"proc.{self.STEM}.CIP.nc") as nc:
            pt = nc.variables["particle_time"][:]
        return self._insec(pt.min()), self._insec(pt.max())

    def test_stage23_succeeded(self):
        self.assertEqual(self.rc23, 0, self.log23[-2000:])
        self.assertTrue((self.s3_out / f"proc.{self.STEM}.CIP.nc").exists())

    def test_a_probe_clock_tas_reaches_sd_on_engine_35(self):
        from arrayprobe import ncio
        # The span is the probe clock (particle_time), deliberately not UTC `Time`:
        # sizeDist.m:758-759 derive starttime from the TAS timestamps and :918 indexes
        # the particle blocks with it, and those blocks are keyed on the probe clock.
        lo, hi = self._particle_span()
        out, rc, text = self._stage4_with_tas("s4_probe_clock", lo, hi)
        self.assertEqual(rc, 0, text[-2000:])
        sd = out / f"sd.{self.STEM}.CIP.nc"
        self.assertTrue(sd.exists(), text[-2000:])
        self.assertTrue(self.mod.read_stamp(sd).startswith("engine=3.5"),
                        self.mod.read_stamp(sd))
        self.assertEqual(ncio.engine_of(out / f"proc.{self.STEM}.CIP.nc"), "3.5")

    def test_a_utc_span_tas_is_refused_before_sizedist_918(self):
        """A UTC-span TAS against the probe clock: the driver refuses before sizeDist.

        65014..65102 s of day is the fixture's UTC ``Time`` span (180334..180502),
        the span the failed run used. Stock v3.5 dies on
        it at ``sizeDist.m:918`` (``starttime`` past the last particle block); that
        engine-level death stays pinned in ``test_v35_sizedist_probetype1.py``. Since
        22589c6 (CIP_V35_SD_EMPTY_1830) the driver's S4 particle-clock guard fails
        closed first, because 0 of the proc's particles land on the TAS axis; under
        ``--protective off`` it derives no clock offset (corrections off), so it refuses."""
        out, rc, text = self._stage4_with_tas("s4_utc", 65014, 65102)
        self.assertEqual(rc, 1, text[-2000:])
        self.assertIn("REFUSED", text)
        self.assertIn("have a particle_time second on the TAS axis", text)
        self.assertNotIn("MatlabIndexError", text)
        self.assertFalse((out / f"sd.{self.STEM}.CIP.nc").exists())


@needs_enhancements
class TheCipDefaultRunGetsItsAirspeedFromThe2DS(unittest.TestCase):
    """The plan of record (section 1 item 4), and the author's decision
    of 2026-09-24: CIP airspeed is the 2D-S's record of the same aircraft
    (``arrayprobe.driver.tas_from_probe_housekeeping``), passed as ``--tas-from-probe``.

    Before this, the default-ON protective set (``particle_time_glitch_fix``) ran its own S4
    after ANY stage selection and failed a ``--stages 23`` CIP run on a ``<stem>.tas.csv`` the
    CIP decode never writes. Both states are pinned here, with the protective set left at its
    default (no ``--protective off``, unlike the class above):

    * ``--stages 23``, no airspeed: the set is deferred, the run succeeds.
    * ``--stages 234 --tas-from-probe <2D-S sidecar>``: the airspeed file is built, S4 and the
      protective set's S4 both run, and the sd stamp names the series.

    The "2D-S sidecar" here is synthetic: a constant 100 m/s, NOT a measurement, written on the
    fixture's probe-clock span (13..101 s) because v3.5 keys probetype 1's particle blocks on
    the CIP clock (``sizeDist.m:758-759``, ``:913-918``). A real
    2D-S sidecar is UTC; where the CIP clock is not, S4 dies at ``:918`` as upstream does.
    """

    STEM = "2016_09_06_06_40_17"
    COMMON = ["--preset", "UND_2016_CIP", "--profile", "stock-v3.5"]

    @classmethod
    def setUpClass(cls):
        import shutil

        import numpy as np

        from arrayprobe.tools.make_tas_file import write_tas_csv
        cls.mod = _load()
        cls._saved = cls.mod.ACTIVE
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.addClassCleanup(lambda: cls.mod.use_preset(cls._saved.name))
        root = Path(cls._tmp.name)
        cls.raw = root / f"{cls.STEM}.sea"
        shutil.copyfile(Path(__file__).parent / "data" / "sea_raw_synthetic.sea", cls.raw)
        cls.hk = root / "base160906064017.tas.csv"
        sod = np.arange(13, 102, dtype=np.int64)
        hhmmss = (sod // 3600) * 10000 + ((sod % 3600) // 60) * 100 + sod % 60
        write_tas_csv(cls.hk, hhmmss, np.full(sod.shape, 100.0), seconds_of_day=sod)
        cls.out23 = root / "s23"
        cls.rc23, cls.log23 = cls._main(cls.out23, "--engine", "3.5", "--stages", "23")
        cls.out234 = root / "s234"
        cls.rc234, cls.log234 = cls._main(cls.out234, "--engine", "3.5", "--stages", "234",
                                          "--tas-from-probe", str(cls.hk))

    @classmethod
    def _main(cls, out, *extra):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = cls.mod.main([str(cls.raw), *cls.COMMON, *extra, "--out", str(out)])
        return rc, buf.getvalue()

    def test_a_stage23_run_defers_the_protective_set_and_succeeds(self):
        self.assertEqual(self.rc23, 0, self.log23[-3000:])
        self.assertIn("PROTECTIVE deferred", self.log23)
        self.assertNotIn("FAILED", self.log23)
        self.assertTrue((self.out23 / f"proc.{self.STEM}.CIP.nc").exists())
        self.assertFalse((self.out23 / f"{self.STEM}.tas.csv").exists())

    def test_the_2ds_airspeed_reaches_sd_and_the_protective_set_runs(self):
        self.assertEqual(self.rc234, 0, self.log234[-3000:])
        self.assertTrue((self.out234 / f"{self.STEM}.tas.csv").exists())
        sd = self.out234 / f"sd.{self.STEM}.CIP.nc"
        self.assertTrue(sd.exists(), self.log234[-3000:])
        stamp = self.mod.read_stamp(sd)
        self.assertTrue(stamp.startswith("engine=3.5"), stamp)
        self.assertIn(f"tas_series=probe_hk:{self.hk.name}", stamp)
        self.assertIn("protective=on:", stamp)
        self.assertNotIn("PROTECTIVE deferred", self.log234)
        self.assertTrue(list(self.out234.glob(f"{self.STEM}.enh.*.nc")), self.log234[-3000:])

    def test_the_built_series_is_the_stand_alone_tools_merge(self):
        import numpy as np
        got = np.loadtxt(self.out234 / f"{self.STEM}.tas.csv", delimiter=",", usecols=(0, 1))
        want = np.loadtxt(self.hk, delimiter=",", usecols=(0, 1))
        np.testing.assert_array_equal(got, want)

    def _refused(self, *extra):
        out = Path(self._tmp.name) / f"refused_{len(extra)}_{abs(hash(extra))}"
        rc, text = self._main(out, *extra)
        self.assertEqual(rc, 2, text[-2000:])
        self.assertFalse(any(out.glob("*.nc")) if out.exists() else False)
        return text

    @needs_v314_engine
    def test_v314_on_cip_still_refuses_with_the_new_input(self):
        text = self._refused("--engine", "3.1.4", "--port-validation", "--stages", "234",
                             "--tas-from-probe", str(self.hk))
        from arrayprobe._v314_lazy import ABSENT_MESSAGE, engine_present
        if engine_present():
            self.assertIn("REFUSED   probe CIP", text)
        else:
            # Without v3.1.4 installed the refusal is the absent-engine message.
            self.assertIn(ABSENT_MESSAGE, text)
        self.assertIn("--engine 3.5", text)

    def test_a_missing_sidecar_is_refused_before_anything_runs(self):
        text = self._refused("--engine", "3.5", "--tas-from-probe",
                             str(Path(self._tmp.name) / "absent.tas.csv"))
        self.assertIn("not found", text)

    def test_it_is_refused_together_with_tas_source(self):
        self._refused("--engine", "3.5", "--tas-from-probe", str(self.hk),
                      "--tas-source", "probe")

    def test_it_is_refused_on_a_probe_whose_s2_writes_its_own(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = self.mod.main([str(self.raw), "--preset", "ORACLES_2016_2DS_H",
                                "--engine", "3.5", "--tas-from-probe", str(self.hk),
                                "--out", str(Path(self._tmp.name) / "refused_2ds")])
        self.assertEqual(rc, 2, buf.getvalue()[-2000:])
        self.assertIn("probetype 1", buf.getvalue())

    def test_the_flag_reaches_every_worker(self):
        src = inspect.getsource(self.mod._spawn_worker)
        self.assertIn('"--tas-from-probe"', src)


if __name__ == "__main__":
    unittest.main()
