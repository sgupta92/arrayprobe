# SPDX-License-Identifier: BSD-3-Clause
"""Two ways a config file could say something the run did not do.

Both found by the cold-user end-to-end walk.


**1. A profile spelling the documentation uses and the loader refused (§4.2).**
``config._ALIASES`` was hand-written with the three v3.1.4-era profiles in it, so
``profile = "ORACLES_PRODUCTION"`` worked and ``profile = "STOCK_V35"`` -- the spelling
``profiles.py`` binds the object to, and the one
``docs/06-configuration.md`` mixes into the same sentence as ``stock-v3.5``
-- did not. The registry itself was made derived in September precisely so a new
profile could not be missed; the alias table was left hand-written and missed both v3.5
profiles the moment they shipped. It is derived now, and **this is what holds it
derived**: the two sides come from different places -- the spelling from a transform
over ``profiles.SHIPPED``, the object from ``getattr(profiles, spelling)``, the module's
own Python attribute.

**2. ``[combine]`` accepted any key at all (§1, F2).** ``load_config`` popped
``borrowed`` and kept the remainder in ``RunConfig.combine``, which no consumer reads,
with no unknown-key check -- unlike ``[run]``, ``[thresholds]`` and ``[v35]``, which
each refuse an unknown key by name. A config carrying
``[combine].totally_made_up_key`` ran to ``ALL DONE``, exit 0, and so did a typo'd
``borrowd = true``, which is the case that costs a user a day: the run stitched the way
the file said it should not.

``tests/test_config_keys_are_consumed.py`` cannot catch either: it sweeps ``RunConfig``
*fields*, and its own LIMIT paragraph names ``combine`` as a field whose generic name
matches an unrelated ``.combine`` in a consumer (``arrayprobe_uiops.combine``). A
field-level sweep cannot see a key that never becomes a field, and it was right to say
so rather than claim the coverage.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe import config, profiles

BASE_V35 = '[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\n'


def _load(text: str) -> config.RunConfig:
    path = Path(tempfile.mkdtemp()) / "run.toml"
    path.write_text(text, encoding="utf-8")
    return config.load_config(path)


class EveryShippedProfileAnswersToBothOfItsSpellings(unittest.TestCase):
    def test_the_constant_spelling_of_every_shipped_profile_is_selectable(self):
        for name in sorted(profiles.SHIPPED):
            spelling = config._constant_spelling(name)
            with self.subTest(profile=name, spelling=spelling):
                self.assertIn(spelling, config.PROFILES,
                              f"{name!r} is spelled {spelling!r} in profiles.py and in every "
                              "Python caller, and a config file cannot name it that way")
                self.assertIs(config.PROFILES[spelling], config.PROFILES[name])

    def test_the_spelling_is_the_modules_own_attribute_name(self):
        """The two sides: the transform, and what ``profiles.py`` actually binds. If a
        future profile is named so that the transform misses (an underscore in the
        ``name`` field, say), this fails here rather than at a user's command line."""
        for name in sorted(profiles.SHIPPED):
            spelling = config._constant_spelling(name)
            with self.subTest(profile=name):
                attribute = getattr(profiles, spelling, None)
                self.assertIsNotNone(
                    attribute, f"profiles.py has no attribute {spelling!r} for profile {name!r}")
                self.assertIs(attribute, config.PROFILES[spelling])

    def test_a_config_file_can_name_the_v35_profile_the_documentation_names(self):
        self.assertIs(_load('[fidelity]\nprofile = "STOCK_V35"\n').profile,
                      profiles.STOCK_V35)
        self.assertIs(_load('[fidelity]\nprofile = "ORACLES_PRODUCTION_V35"\n').profile,
                      profiles.ORACLES_PRODUCTION_V35)

    def test_the_refusal_still_lists_every_accepted_spelling(self):
        """What saves a user today, and what this change must not cost them: the
        unknown-profile refusal names all of them, both spellings of each."""
        with self.assertRaises(config.ConfigError) as caught:
            _load('[fidelity]\nprofile = "stock-v3.6"\n')
        message = str(caught.exception)
        for name in sorted(profiles.SHIPPED):
            self.assertIn(name, message)
            self.assertIn(config._constant_spelling(name), message)


class TheCombineTableRefusesAnUnknownKey(unittest.TestCase):
    def test_a_junk_key_is_refused_by_name(self):
        with self.assertRaises(config.ConfigError) as caught:
            _load(BASE_V35 + '[combine]\nborrowed = true\ntotally_made_up_key = "nothing"\n')
        message = str(caught.exception)
        self.assertIn("totally_made_up_key", message)
        self.assertIn("borrowed", message)

    def test_a_misspelled_borrowed_is_refused_rather_than_silently_off(self):
        """The case that costs a day: the file says stitch with the borrowed combine,
        the run does not, and nothing says why."""
        with self.assertRaises(config.ConfigError):
            _load(BASE_V35 + "[combine]\nborrowd = true\n")

    def test_the_one_real_key_still_works_both_ways(self):
        self.assertTrue(_load(BASE_V35 + "[combine]\nborrowed = true\n").borrowed_combine)
        self.assertFalse(_load(BASE_V35 + "[combine]\nborrowed = false\n").borrowed_combine)
        self.assertFalse(_load(BASE_V35).borrowed_combine)

    def test_it_refuses_in_the_same_shape_as_the_other_three_tables(self):
        """``[run]``, ``[thresholds]`` and ``[v35]`` each say which key is unknown and
        which are known. This one now does too -- read against those three, so the
        message cannot drift into a different idiom."""
        for text, section in (
            (BASE_V35 + "[combine]\nnope = true\n", "[combine]"),
            ('[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\nnope = true\n',
             "[run]"),
            ('[fidelity]\nprofile = "stock-v3.1.4"\n[thresholds]\nnope = 1\n', "[thresholds]"),
            (BASE_V35 + "[v35]\nnope = 1\n", "[v35]"),
        ):
            with self.subTest(section=section):
                with self.assertRaises(config.ConfigError) as caught:
                    _load(text)
                message = str(caught.exception)
                self.assertIn(f"{section} has unknown key(s) ['nope']", message)
                self.assertIn("known:", message)

    def test_nothing_is_stored_from_that_table_any_more(self):
        """``RunConfig.combine`` can now only ever be empty: ``borrowed`` is popped into
        its own field and every other key is refused above. Recorded here so the next
        pass over that dataclass knows the field is dead rather than merely unused."""
        self.assertEqual(_load(BASE_V35 + "[combine]\nborrowed = true\n").combine, {})


if __name__ == "__main__":
    unittest.main()
