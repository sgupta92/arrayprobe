# SPDX-License-Identifier: BSD-3-Clause
"""Every value ``load_config`` stores is read by some consumer, or the page says it is not.

Found 2026-09-14, fixed 2026-09-15: ``[export].format``
was parsed and validated into ``RunConfig.export_format`` and read by nothing -- the v3.1.4
writers always write ``NETCDF3_CLASSIC`` and the v3.5 writers ``NETCDF4`` -- while
``docs/06-configuration.md`` presented the key as selecting the output format. A
documented option that does nothing is a claim the code does not keep.

THE CHECK. Every field of :class:`arrayprobe.config.RunConfig` (the one place a TOML value
lands) must be read as ``.<field>`` in a consumer: a ``.py`` file under ``python_port/src``,
``python_port/tools``, ``enhancements_uiops/src`` or ``enhancements_soda2/src``, other than
``config.py`` itself. The two sides come from different places: the field list from the
dataclass, the uses from the consumers' source.

THE EXCEPTION, recorded rather than hidden. ``UNREAD`` names a field that is deliberately not
consumed, with the reason and the phrase the configuration page must carry so a reader is told.
Today that is ``export_format`` alone. It stays loaded (removing the key would break every
config file that sets it) and validated (a typo is still an error), but it selects nothing.

LIMIT. A field with a generic name (``run``, ``source``, ``profile``, ``combine``) can match an
unrelated ``.run``/``.source`` attribute, so for those this proves less than for the distinctive
ones. A wrong match can only hide an unread field, never invent one.
"""

from __future__ import annotations

import dataclasses
import re
import unittest
from pathlib import Path

from tests._repo import repo_only

from arrayprobe.config import RunConfig

PORT = Path(__file__).resolve().parents[1]
ROOT = PORT
CONSUMER_DIRS = (PORT / "src", PORT / "scripts", ROOT / "enhancements_uiops" / "src",
                 ROOT / "enhancements_soda2" / "src")
CONFIG_PY = PORT / "src" / "arrayprobe" / "config.py"
CONFIG_PAGE = ROOT / "docs" / "06-configuration.md"

#: field -> (the TOML key, why it is unread, the phrase 06-configuration.md must carry)
UNREAD = {
    "export_format": ("[export].format",
                      "the engine fixes the format (v3.1.4 NETCDF3_CLASSIC, v3.5 NETCDF4)",
                      "no writer reads it"),
}


def _consumer_text() -> str:
    parts = []
    for d in CONSUMER_DIRS:
        if d.is_dir():
            parts += [p.read_text(encoding="utf-8", errors="replace")
                      for p in d.rglob("*.py") if p.resolve() != CONFIG_PY.resolve()]
    return "\n".join(parts)


def unread_fields(names, text: str) -> list[str]:
    return sorted(n for n in names if not re.search(rf"\.{re.escape(n)}\b", text))


@repo_only
class EveryConfigValueIsConsumed(unittest.TestCase):
    def setUp(self):
        self.fields = [f.name for f in dataclasses.fields(RunConfig)]
        self.text = _consumer_text()

    def test_every_field_is_read_or_declared_unread(self):
        missing = [n for n in unread_fields(self.fields, self.text) if n not in UNREAD]
        self.assertEqual(missing, [],
                         "RunConfig fields no consumer reads: a config key that does nothing. "
                         "Wire it in, or add it to UNREAD with the reason and say so on "
                         "06-configuration.md")

    def test_a_declared_unread_field_is_still_unread(self):
        """The exception list only shrinks: once a writer reads ``export_format``, drop the row."""
        now_read = [n for n in UNREAD if n not in unread_fields(UNREAD, self.text)]
        self.assertEqual(now_read, [], "these are consumed now; remove them from UNREAD")

    @unittest.skipUnless(CONFIG_PAGE.is_file(), "docs/_build/pages is not in this tree")
    def test_the_configuration_page_says_which_keys_select_nothing(self):
        page = CONFIG_PAGE.read_text(encoding="utf-8")
        for _field, (key, _why, phrase) in UNREAD.items():
            self.assertIn(key, page)
            self.assertIn(phrase, page, f"06-configuration.md must say {key} is unread")

    def test_the_check_fires(self):
        """Mutation: a field nothing reads is reported; the same field, once read, is not."""
        self.assertEqual(unread_fields(["zz_unread_key"], self.text), ["zz_unread_key"])
        self.assertEqual(unread_fields(["zz_unread_key"], "cfg.zz_unread_key"), [])


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
