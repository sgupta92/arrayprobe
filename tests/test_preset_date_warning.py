# SPDX-License-Identifier: BSD-3-Clause
"""A raw stem whose flight date is outside a campaign preset's window logs a warning and the run
continues (C11, date half).  A warning is a log line only: no computed number or stamp changes."""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from arrayprobe.driver import run_flight as rf

WINDOWS = {"CAMPAIGN_X": (date(2016, 8, 1), date(2016, 10, 31), "test table")}


class TheDateWarning(unittest.TestCase):
    def test_an_in_window_date_gives_no_warning(self):
        self.assertIsNone(rf.preset_date_warning("CAMPAIGN_X", "d/base160906064343.2DS", WINDOWS))

    def test_an_out_of_window_date_warns_naming_preset_date_and_window(self):
        why = rf.preset_date_warning("CAMPAIGN_X", "d/base160101000000.2DS", WINDOWS)
        self.assertIn("CAMPAIGN_X", why)
        self.assertIn("2016-01-01", why)
        self.assertIn("2016-08-01 to 2016-10-31", why)

    def test_a_preset_without_a_window_is_not_checked(self):
        self.assertIsNone(
            rf.preset_date_warning("MY_TOML_PRESET", "d/base160101000000.2DS", WINDOWS))
        self.assertIsNone(rf.preset_date_warning("DEMO_2DS_H", "d/base160101000000.2DS"))

    def test_an_unparseable_stem_is_not_checked(self):
        for name in ("flight1.2DS", "base16010100.2DS", "base161399000000.2DS"):
            self.assertIsNone(rf.preset_date_warning("CAMPAIGN_X", f"d/{name}", WINDOWS), name)

    def test_no_shipped_preset_has_a_window_without_a_source(self):
        for name, (first, last, source) in rf.PRESET_FLIGHT_WINDOWS.items():
            self.assertIn(name, rf.PRESETS)
            self.assertLessEqual(first, last)
            self.assertTrue(source.strip())

    def test_the_campaign_presets_carry_the_espo_deployment_windows(self):
        self.assertEqual(set(rf.PRESET_FLIGHT_WINDOWS),
                         {"ORACLES_2016_2DS_H", "UND_2016_CIP", "ORACLES_2017_2DS_V"})
        # flights this repository validates or processes lie inside their campaign's window
        for preset, stem in (("ORACLES_2016_2DS_H", "base160906064017"),
                             ("UND_2016_CIP", "base160912000000"),
                             ("ORACLES_2017_2DS_V", "base170812000000")):
            self.assertIsNone(rf.preset_date_warning(preset, f"d/{stem}.2DS"), preset)
        self.assertIsNotNone(rf.preset_date_warning("ORACLES_2017_2DS_V", "d/base160906064017.2DS"))


class ThePreflightOnlyLogs(unittest.TestCase):
    def test_a_warned_preflight_proceeds_and_logs_one_warning(self):
        raw = Path(__file__).resolve().parent / "data" / "demo_flight_v35_raw.2DS"
        if not raw.exists():
            raw = raw.with_name("demo_flight_v314_raw.2DS")
        self.assertTrue(raw.exists())
        table = {rf.ACTIVE.name: (date(2020, 1, 1), date(2020, 2, 1), "test table")}
        with tempfile.TemporaryDirectory() as out, mock.patch.dict(
                rf.PRESET_FLIGHT_WINDOWS, table, clear=True):
            dst = Path(out) / "base160101000000.2DS"
            shutil.copyfile(raw, dst)
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                rf.preflight([dst], Path(out), None)
            text = buf.getvalue()
        self.assertEqual(text.count("outside the"), 1, text)
        self.assertNotIn("MISMATCH", text)


if __name__ == "__main__":
    unittest.main()
