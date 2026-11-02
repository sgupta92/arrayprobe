# SPDX-License-Identifier: BSD-3-Clause
"""``[fidelity]``, ``[shattering]``, ``[masking]`` and ``[export]`` refuse an unknown key, and a
section written as a top-level value is a one-line refusal rather than a traceback.

Found 2026-09-26 by a cold-user walk of ``load_config``: ``[masking.diode]`` (for ``diodes``),
``[export] formt = "NETCDF4"``, ``[fidelity] profle_module = ...`` and ``[shattering]
threshhold = ...`` all loaded cleanly and were ignored, so the run did something other than
what the file said -- the ``[combine]`` loophole closed on 2026-09-20
(``test_config_spellings_and_combine_keys.py``), in four more tables. And ``masking = [3]`` or
``run = "x"`` at the top level raised ``AttributeError`` / ``ValueError`` out of the loader.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_file  # noqa: E402

from arrayprobe.config import ConfigError, load_config

BASE = '[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\n'


def _load(body: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "run.toml"
        p.write_text(body, encoding="utf-8")
        return load_config(p)


class UnknownKeysAreRefusedByName(unittest.TestCase):

    def test_each_typo_is_refused_naming_the_section_and_the_key(self):
        cases = {
            '[fidelity]\nprofile = "stock-v3.5"\nprofle_module = "x"\n[run]\nengine = "3.5"\n':
                ("[fidelity]", "profle_module"),
            BASE + '[shattering]\nthreshold_file = "a.cdf"\nthreshhold = "b"\n':
                ("[shattering]", "threshhold"),
            BASE + "[masking.diode]\nbase160101000000 = [3]\n": ("[masking]", "diode"),
            BASE + '[export]\nformt = "NETCDF4"\n': ("[export]", "formt"),
        }
        for body, (section, key) in cases.items():
            with self.subTest(section=section):
                with self.assertRaises(ConfigError) as cm:
                    _load(body)
                self.assertIn(section, str(cm.exception))
                self.assertIn(key, str(cm.exception))

    def test_the_real_keys_still_load(self):
        cfg = _load(BASE + '[shattering]\nthreshold_file = "a.cdf"\n'
                    "[masking]\ndiodes = { base160101000000 = [3, 128] }\n"
                    '[export]\nformat = "NETCDF4"\n')
        self.assertEqual(cfg.shattering_threshold_file, "a.cdf")
        self.assertEqual(cfg.diode_masks, {"base160101000000": (3, 128)})
        self.assertEqual(cfg.export_format, "NETCDF4")

    @needs_file("scripts/oracles_2016_2ds.toml")
    def test_the_shipped_oracles_config_still_loads(self):
        cfg = load_config(Path(__file__).resolve().parents[1] / "scripts" / "oracles_2016_2ds.toml")
        self.assertTrue(cfg.diode_masks)


class WrongShapesAreOneLineRefusals(unittest.TestCase):

    def test_a_section_written_as_a_top_level_value_is_refused(self):
        for body in ('run = "x"\n' + '[fidelity]\nprofile = "stock-v3.5"\n',
                     "masking = 3\n" + BASE):
            with self.subTest(body=body.splitlines()[0]):
                with self.assertRaises(ConfigError) as cm:
                    _load(body)
                self.assertIn("table", str(cm.exception))

    def test_masking_diodes_as_a_list_is_refused(self):
        with self.assertRaises(ConfigError) as cm:
            _load(BASE + "[masking]\ndiodes = [3]\n")
        self.assertIn("[masking].diodes", str(cm.exception))

    def test_a_non_string_threshold_file_is_refused(self):
        with self.assertRaises(ConfigError) as cm:
            _load(BASE + "[shattering]\nthreshold_file = 3\n")
        self.assertIn("threshold_file", str(cm.exception))


class AnExportFormatTheEngineCannotWriteIsRefused(unittest.TestCase):
    """No writer reads ``[export].format`` (``test_config_keys_are_consumed.py``'s UNREAD row):
    each engine fixes its own. A 3.1.4 file asking for NETCDF4 used to load, run to ALL DONE and
    write NETCDF3_CLASSIC products -- the file said one thing and the run did another."""

    def test_the_other_format_is_refused_when_the_file_names_the_engine(self):
        for engine, other in (("3.1.4", "NETCDF4"), ("3.5", "NETCDF3_CLASSIC")):
            with self.subTest(engine=engine), self.assertRaises(ConfigError) as cm:
                _load(f'[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "{engine}"\n'
                      f'[export]\nformat = "{other}"\n')
            self.assertIn("cannot be honoured", str(cm.exception))

    def test_the_engines_own_format_and_an_absent_section_still_load(self):
        for engine, own in (("3.1.4", "NETCDF3_CLASSIC"), ("3.5", "NETCDF4")):
            head = f'[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "{engine}"\n'
            with self.subTest(engine=engine):
                self.assertEqual(_load(head + f'[export]\nformat = "{own}"\n').export_format, own)
                _load(head)


if __name__ == "__main__":
    unittest.main()
