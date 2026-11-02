# SPDX-License-Identifier: BSD-3-Clause
"""A raw file whose extension names a different probe than the preset is refused (C11).

The refusal is a positive contradiction only: an extension no table lists passes, and the override
stamp appears only when the override is used, so a matching run's stamps are unchanged.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from arrayprobe.driver import run_flight as rf

DEMO_RAW = Path(__file__).resolve().parent / "data" / "demo_flight_v35_raw.2DS"
if not DEMO_RAW.exists():
    DEMO_RAW = Path(__file__).resolve().parent / "data" / "demo_flight_v314_raw.2DS"


class TheExtensionTable(unittest.TestCase):
    def test_hvps_under_a_2ds_probe_is_refused_with_the_override_named(self):
        why = rf.preset_raw_mismatch("2DS", "x/base160906064343.HVPS")
        self.assertIn("--accept-preset-mismatch", why)
        self.assertIn("HVPS", why)

    def test_2ds_under_hvps_and_under_cip_are_refused(self):
        self.assertIsNotNone(rf.preset_raw_mismatch("HVPS", "a.2DS"))
        self.assertIsNotNone(rf.preset_raw_mismatch("CIP", "a.2DS"))

    def test_spec_container_under_a_cip_container_probe_is_refused_and_the_reverse(self):
        self.assertIsNotNone(rf.preset_raw_mismatch("2DS", "a.cip"))
        self.assertIsNotNone(rf.preset_raw_mismatch("2DS", "a.sea"))
        self.assertIsNone(rf.preset_raw_mismatch("CIP", "a.cip"))
        self.assertIsNone(rf.preset_raw_mismatch("CIP", "a.SEA"))

    def test_matching_and_unknown_extensions_pass(self):
        for probe, raw in [("2DS", "a.2DS"), ("2DS", "a.2ds"), ("HVPS", "a.HVPS"),
                           ("2DS", "a.bin"), ("2DS", "noext"), ("2DS", "a.2dc"),
                           ("NotAProbe", "a.cip")]:
            with self.subTest(probe=probe, raw=raw):
                self.assertIsNone(rf.preset_raw_mismatch(probe, raw))


class ThePreflightGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.raw = self.tmp / "base160101000000.HVPS"
        shutil.copy(DEMO_RAW, self.raw)
        self.out = self.tmp / "out"
        self.out.mkdir()
        self._saved = rf.ACCEPT_PRESET_MISMATCH
        self.addCleanup(setattr, rf, "ACCEPT_PRESET_MISMATCH", self._saved)

    def _preflight(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            ok = rf.preflight([self.raw], self.out, None)
        return ok, buf.getvalue()

    def test_mismatch_refuses_with_an_actionable_message(self):
        rf.ACCEPT_PRESET_MISMATCH = False
        ok, text = self._preflight()
        self.assertFalse(ok)
        self.assertIn("MISMATCH", text)
        self.assertIn("--accept-preset-mismatch", text)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_main_exits_nonzero_before_any_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = rf.main([str(self.raw), "--preset", "ORACLES_2016_2DS_H", "--engine", "3.5",
                          "--profile", "stock-v3.5", "--stages", "2", "--out", str(self.out)])
        self.assertNotEqual(rc, 0)
        self.assertIn("MISMATCH", buf.getvalue())
        self.assertEqual(list(self.out.iterdir()), [])

    def test_override_passes_preflight_with_a_warning(self):
        rf.ACCEPT_PRESET_MISMATCH = True
        ok, text = self._preflight()
        self.assertTrue(ok)
        self.assertIn("WARNING", text)
        self.assertNotIn("MISMATCH ", text.replace("accept-preset-mismatch", ""))


class TheStampIsUnchangedUnlessTheOverrideIsUsed(unittest.TestCase):
    def setUp(self):
        self._saved = rf.ACCEPT_PRESET_MISMATCH
        self.addCleanup(setattr, rf, "ACCEPT_PRESET_MISMATCH", self._saved)

    def test_no_token_by_default_and_token_on_every_stage_when_used(self):
        rf.ACCEPT_PRESET_MISMATCH = False
        plain = [rf.image_call_label(rf.ACTIVE.profile if hasattr(rf.ACTIVE, "profile") else None),
                 rf.proc_call_label(), rf.sd_call_label(None)]
        for label in plain:
            self.assertNotIn("accept_preset_mismatch", label)
        rf.ACCEPT_PRESET_MISMATCH = True
        for old, new in zip(plain, [
                rf.image_call_label(rf.ACTIVE.profile if hasattr(rf.ACTIVE, "profile") else None),
                rf.proc_call_label(), rf.sd_call_label(None)], strict=True):
            self.assertIn(" " + rf.ACCEPT_PRESET_MISMATCH_STAMP, new)
            self.assertEqual(new.replace(" " + rf.ACCEPT_PRESET_MISMATCH_STAMP, "", 1), old)

    def test_the_check_is_called_only_from_preflight(self):
        src = (Path(rf.__file__)).read_text(encoding="utf-8")
        self.assertEqual(src.count("preset_raw_mismatch(PROBE"), 1)


if __name__ == "__main__":
    unittest.main()
