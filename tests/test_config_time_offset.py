# SPDX-License-Identifier: BSD-3-Clause
"""``[time_offset]``: the run-configuration spelling of engine 3.5's probe-clock offset
(``--time-offset-s`` / ``--time-offset-evidence`` / ``--time-offset-tas-clock``).

Pins: the three keys load and validate together at load time; the section is refused unless
``[run].engine = "3.5"``; ``run_flight.py`` takes it when no flag is given and the flags win
over it whole; absent, nothing is set and the sd ``.call`` stamp is unchanged.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests import _run_flight_state

from arrayprobe.config import ConfigError, load_config

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_flight", _ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)

_BASE = '[fidelity]\nprofile = "stock-v3.5"\n\n[run]\nengine = "3.5"\n'
_SECTION = ('\n[time_offset]\nseconds = -100\nevidence = "SPEC vs aircraft TAS lag"\n'
            'tas_clock = "probe"\n')


def _write(text: str) -> Path:
    p = Path(tempfile.mkdtemp()) / "run.toml"
    p.write_text(text, encoding="utf-8")
    return p


class LoadAndValidate(unittest.TestCase):

    def test_absent_is_none(self):
        self.assertIsNone(load_config(_write(_BASE)).time_offset)

    def test_all_three_load(self):
        cfg = load_config(_write(_BASE + _SECTION))
        self.assertEqual(cfg.time_offset, (-100, "SPEC vs aircraft TAS lag", "probe"))

    def test_partial_section_is_refused(self):
        for drop in ("seconds", "evidence", "tas_clock"):
            text = "\n".join(line for line in _SECTION.splitlines()
                             if not line.startswith(drop))
            with self.subTest(missing=drop), self.assertRaises(ConfigError) as cm:
                load_config(_write(_BASE + text + "\n"))
            self.assertIn("required together", str(cm.exception))

    def test_bad_values_are_refused_at_load(self):
        for bad in ("seconds = 1.5", "seconds = 0", "seconds = 90000", "seconds = true",
                    'tas_clock = "gps"', 'evidence = "  "'):
            key = bad.split(" ")[0]
            text = "\n".join(bad if line.startswith(key) else line
                             for line in _SECTION.splitlines())
            with self.subTest(value=bad), self.assertRaises(ConfigError):
                load_config(_write(_BASE + text + "\n"))

    def test_unknown_key_is_refused(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(_write(_BASE + _SECTION + "offset_ms = 5\n"))
        self.assertIn("unknown key", str(cm.exception))

    def test_refused_unless_engine_35(self):
        for run in ('[run]\nengine = "3.1.4"\n', ""):
            text = '[fidelity]\nprofile = "ORACLES_PRODUCTION"\n\n' + run + _SECTION
            with self.subTest(run=run), self.assertRaises(ConfigError) as cm:
                load_config(_write(text))
            self.assertIn("engine 3.5 only", str(cm.exception))


class TheDriverMerge(unittest.TestCase):

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)

    def _main(self, config_text, extra=()):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main(["--engine", "3.5", "--preset", "ORACLES_2016_2DS_H",
                                  "--config", str(_write(config_text)), *extra,
                                  "nosuch-raw.2DS"])
        return rc, buf.getvalue()

    def test_config_sets_it(self):
        _rc, out = self._main(_BASE + _SECTION)
        self.assertEqual(run_flight.TIME_OFFSET, (-100, "SPEC vs aircraft TAS lag", "probe"))
        self.assertIn("config    time_offset: -100 s", out)

    def test_command_line_wins_whole(self):
        _rc, out = self._main(_BASE + _SECTION,
                              ("--time-offset-s", "78", "--time-offset-evidence", "flag",
                               "--time-offset-tas-clock", "aircraft"))
        self.assertEqual(run_flight.TIME_OFFSET, (78, "flag", "aircraft"))
        self.assertIn("[time_offset] given but the command line's", out)

    def test_absent_leaves_the_default_stamp_unchanged(self):
        self._main(_BASE)
        self.assertIsNone(run_flight.TIME_OFFSET)
        run_flight.ENGINE = "3.5"
        run_flight.TAS_FILE = None
        default = run_flight.sd_call_label(None)
        self.assertNotIn("time_offset", default)
        # The section, once taken, only appends the offset fragment to that same stamp.
        self._main(_BASE + _SECTION)
        run_flight.ENGINE = "3.5"
        run_flight.TAS_FILE = None
        with_offset = run_flight.sd_call_label(None)
        # The time_sv_fix marker closes the stamp after the offset fragment.
        sv = f" {run_flight.TIME_SV_FIX_STAMP_KEY}"
        head, _, tail = default.partition(sv)
        self.assertTrue(with_offset.startswith(head + " time_offset_s=-100 "), with_offset)
        if tail:
            self.assertTrue(with_offset.endswith(sv + tail), with_offset)

if __name__ == "__main__":
    unittest.main()
