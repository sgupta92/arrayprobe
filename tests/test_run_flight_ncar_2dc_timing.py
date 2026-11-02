# SPDX-License-Identifier: BSD-3-Clause
"""The batch driver's NCAR 2DC timing-word conversion (``--ncar-2dc-timing``): on by default for
an engine-3.5 probetype-0 run, opt-out, refused under port validation and under ``--chunks``, and
stamped into the proc ``.call`` label of a 2DC run only. Modelled on
``tests/test_run_flight_stray_pixel.py``."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
from tests._repo import needs_enhancements, needs_v314_engine  # noqa: E402

import _run_flight_state  # noqa: E402
import run_flight  # noqa: E402

CAMPAIGNS = """
[[campaign]]
name = "TESTCAMP_2DC"
probe = "2DC"
orientation = "none"
project = "TESTCAMP"
d_choice = 6
sa_method = 0
pres_pa = 86470.0
temp_c = 14.5
provenance = "synthetic preset for tests/test_run_flight_ncar_2dc_timing.py"

[[campaign]]
name = "TESTCAMP_2DS_H"
probe = "2DS"
orientation = "H"
project = "TESTCAMP"
d_choice = 6
sa_method = 0
pres_pa = 86470.0
temp_c = 14.5
provenance = "synthetic preset for tests/test_run_flight_ncar_2dc_timing.py"
"""


class ResolveDefault(unittest.TestCase):
    def test_engine_35_defaults_on(self):
        self.assertTrue(run_flight.resolve_ncar_2dc_timing("3.5"))

    def test_cli_off_is_the_opt_out(self):
        self.assertFalse(run_flight.resolve_ncar_2dc_timing("3.5", "off"))

    def test_config_false_is_the_opt_out(self):
        self.assertFalse(run_flight.resolve_ncar_2dc_timing("3.5", None, False))

    def test_cli_wins_over_config(self):
        self.assertTrue(run_flight.resolve_ncar_2dc_timing("3.5", "on", False))
        self.assertFalse(run_flight.resolve_ncar_2dc_timing("3.5", "off", True))

    def test_port_validation_is_off_and_refuses_on(self):
        self.assertFalse(run_flight.resolve_ncar_2dc_timing("3.1.4"))
        with self.assertRaises(ValueError):
            run_flight.resolve_ncar_2dc_timing("3.1.4", "on")
        with self.assertRaises(ValueError):
            run_flight.resolve_ncar_2dc_timing("3.1.4", None, True)


class DryRun(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        self._saved_presets = dict(run_flight.PRESETS)
        self.addCleanup(lambda: (run_flight.PRESETS.clear(),
                                 run_flight.PRESETS.update(self._saved_presets)))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.presets = self.tmp / "campaigns.toml"
        self.presets.write_text(CAMPAIGNS, encoding="utf-8")

    def _run(self, preset: str, raw_name: str, *extra: str) -> tuple[int, str]:
        raw = self.tmp / raw_name
        raw.write_bytes(b"\0" * 4096)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = run_flight.main(["--presets", str(self.presets), "--preset", preset,
                                  "--out", str(self.tmp / "_decoded"), "--dry-run", "--yes",
                                  *extra, str(raw)])
        return rc, buf.getvalue()

    def _run_2dc(self, *extra: str) -> tuple[int, str]:
        return self._run("TESTCAMP_2DC", "base180101000000.2DC", "--profile", "stock-v3.5",
                         *extra)

    @needs_enhancements  # a 2DC run's default-on protective corrections import it (rc 2 without)
    def test_v35_2dc_dry_run_stamps_on_by_default(self):
        rc, out = self._run_2dc("--engine", "3.5")
        self.assertNotEqual(rc, 2, out)
        self.assertIn(" ncar_2dc_timing=on:fix2dimage", run_flight.proc_call_label(), out)

    @needs_enhancements  # a 2DC run's default-on protective corrections import it (rc 2 without)
    def test_off_flag_stamps_off(self):
        rc, out = self._run_2dc("--engine", "3.5", "--ncar-2dc-timing", "off")
        self.assertNotEqual(rc, 2, out)
        self.assertIn(" ncar_2dc_timing=off", run_flight.proc_call_label(), out)

    @needs_v314_engine
    def test_engine_314_with_the_flag_is_refused(self):
        rc, out = self._run_2dc("--engine", "3.1.4", "--port-validation",
                                "--ncar-2dc-timing", "on")
        self.assertEqual(rc, 2, out)
        self.assertIn("NCAR 2DC timing conversion is engine 3.5 only", out)

    def test_chunks_with_it_on_is_refused(self):
        rc, out = self._run_2dc("--engine", "3.5", "--chunks", "2")
        self.assertEqual(rc, 2, out)
        self.assertIn("NCAR 2DC timing conversion on", out)

    def test_a_2ds_v35_stamp_has_no_fragment(self):
        rc, out = self._run("TESTCAMP_2DS_H", "base180101000000.2DS", "--engine", "3.5",
                            "--profile", "stock-v3.5")
        self.assertNotIn("ncar_2dc_timing=", run_flight.proc_call_label(), out)


if __name__ == "__main__":
    unittest.main()
