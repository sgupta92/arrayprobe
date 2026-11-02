# SPDX-License-Identifier: BSD-3-Clause
"""The driver knows the flight date and the run pressure; the context now carries them.

WHY (2026-09-21, measured on a real ARM run). Applying all 33 applicable corrections to
ACE-ENA 2017-07-07 produced a provenance sidecar in which **14 of 29 skips said "no driver
adapter"**, and four of those named values the run had in hand the whole time:

    cf_export                 needs the flight date for the CF time axis, not in the config
                              and never read off a file name
    tas_grid_fix              needs a run pressure not recoverable from the .call stamp
    pressure_units_fix        same gap
    reaccept_every_event_fix  re-running sizeDist needs the run's own call arguments
                              (pressure, threshold file)

**Nothing was missing. Nothing crossed the boundary.** `run_flight` computes `ddate` for
sizeDist's own argument list and holds `PRES_PA` from the preset; neither reached the
enhancement pipeline, so corrections reported themselves inapplicable when they were merely
unwired. That is a wiring gap being reported as a scientific limit, which is the more
expensive of the two mistakes because it looks like a finished answer.

WHAT THESE TESTS PIN, and the emphasis is on the refusals:

- Both values resolve from the *preset*, by the same private-module route `preset_probetype`
  already uses -- one loader, not two.
- **Neither ever defaults.** A pressure enters sample volume and a date becomes a CF time
  axis; a guessed pressure moves every concentration in the file while looking ordinary, and
  a guessed date puts a wrong time axis on a standards-conformant file. Both are `None` on
  any doubt, and `None` makes the dependent correction skip exactly as it does today.
- The date is read off the raw stem in **one** place, range-checked, because `base999999999999`
  is a well-formed stem and not a date.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parents[1] / "src"))

from arrayprobe_enhancements.pipeline import (  # noqa: E402
    _flight_date_from_stem,
    _preset,
    _preset_pres_pa,
    _preset_probetype,
)


class _Cfg:
    """The two attributes the resolvers touch on a RunConfig."""

    def __init__(self, preset=None):
        self.run = {"preset": preset} if preset else {}


class ThePresetResolvesOnce(unittest.TestCase):
    def test_a_real_preset_resolves(self):
        self.assertIsNotNone(_preset(_Cfg("ORACLES_2016_2DS_H")))

    def test_probetype_and_pressure_come_from_the_same_preset(self):
        """One loader, two readers -- the property the refactor exists to hold.

        If these ever disagree about which preset they resolved, two routes have appeared.
        """
        cfg = _Cfg("ORACLES_2016_2DS_H")
        preset = _preset(cfg)
        self.assertEqual(_preset_pres_pa(cfg), float(preset.pres_pa))
        self.assertIsNotNone(_preset_probetype(cfg))

    def test_the_pressure_is_a_real_number_not_a_placeholder(self):
        v = _preset_pres_pa(_Cfg("ORACLES_2016_2DS_H"))
        self.assertIsInstance(v, float)
        self.assertGreater(v, 1e4, "a static pressure in Pa should be far above 10 kPa")


class NeitherValueIsEverGuessed(unittest.TestCase):
    def test_no_preset_named_gives_no_pressure(self):
        self.assertIsNone(_preset_pres_pa(_Cfg()))

    def test_an_unknown_preset_gives_no_pressure(self):
        self.assertIsNone(_preset_pres_pa(_Cfg("NO_SUCH_CAMPAIGN_2DS_H")))

    def test_an_unknown_preset_gives_no_probetype_either(self):
        self.assertIsNone(_preset_probetype(_Cfg("NO_SUCH_CAMPAIGN_2DS_H")))


class TheFlightDateIsReadOffTheStemOrNotAtAll(unittest.TestCase):
    def test_a_real_stem_parses(self):
        self.assertEqual(_flight_date_from_stem("base170707102822"), "20170707")
        self.assertEqual(_flight_date_from_stem("base160906064017"), "20160906")

    def test_it_agrees_with_the_drivers_own_derivation(self):
        """Two sides from different places: this function, and `run_flight.stage4`'s literal.

        `stage4` builds sizeDist's `ddate` as `f"20{raw_stem[4:10]} {raw_stem[10:16]}"`. The
        date half of that string must be what this returns, or the CF time axis and the
        sizeDist call would disagree about which day the flight was.
        """
        for stem in ("base170707102822", "base160906064017"):
            drivers = f"20{stem[4:10]}"
            self.assertEqual(_flight_date_from_stem(stem), drivers)

    def test_a_stem_that_is_not_a_flight_yields_nothing(self):
        for bad in ("notaflight", "", "base", "base1707"):
            self.assertIsNone(_flight_date_from_stem(bad), bad)

    def test_a_well_formed_stem_that_is_not_a_date_yields_nothing(self):
        """`base999999999999` is exactly the right shape and month 99 does not exist.

        A length-and-digits check alone would accept it and produce "20999999" -- a CF time
        axis on a file that then looks entirely standards-conformant.
        """
        self.assertIsNone(_flight_date_from_stem("base999999999999"))
        self.assertIsNone(_flight_date_from_stem("base170007102822"))  # month 00
        self.assertIsNone(_flight_date_from_stem("base171307102822"))  # month 13
        self.assertIsNone(_flight_date_from_stem("base170700102822"))  # day 00


class TheContextFieldsExistAndDefaultToNothing(unittest.TestCase):
    def test_the_dataclass_carries_both_and_neither_is_required(self):
        from arrayprobe_enhancements.pipeline import _RunOutputs
        fields = {f.name for f in _RunOutputs.__dataclass_fields__.values()}
        self.assertIn("preset_pres_pa", fields)
        self.assertIn("flight_date", fields)
        out = _RunOutputs(out_dir=Path("."), raw_stem="s", engine="3.5",
                          image=None, proc=None, sd=None, combined=None)
        self.assertIsNone(out.preset_pres_pa)
        self.assertIsNone(out.flight_date)


if __name__ == "__main__":
    unittest.main()
