# SPDX-License-Identifier: BSD-3-Clause
"""A direct ``scripts/run_flight.py --config`` honours the file's ``[run]`` table.

Found 2026-09-26 by a cold-user walk. ``arrayprobe run`` turns ``[run].preset/out/stages/
tas_file`` into flags; a direct ``run_flight.py --config`` read only ``[run].engine`` and
dropped the rest silently:

* the file's ``preset = "ORACLES_2016_2DS_H"`` and ``--preset DEMO_2DS_H`` ran DEMO, exit 0;
* ``out`` and ``stages`` were replaced by the argparse defaults (``../_decoded``, ``234``);
* a v3.5 file naming ``tas_file`` was refused for want of a TAS file, with a message telling
  the user to "set [run].tas_file" -- which the file already did.

Now the preset and probe are refused on disagreement (as the engine is), and out/stages/
tas_file fold in when the flag is absent, relative to the config file.
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import _run_flight_state  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
sys.modules.setdefault(_SPEC.name, importlib.util.module_from_spec(_SPEC))
run_flight = sys.modules[_SPEC.name]
if not hasattr(run_flight, "main"):
    _SPEC.loader.exec_module(run_flight)

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe.config import load_config  # noqa: E402

AIRCRAFT = ROOT / "tests" / "data" / "demo_flight_v35_aircraft.cdf"


class _Base(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.lines: list[str] = []
        real_log = run_flight.log
        run_flight.log = lambda msg, *a, **k: self.lines.append(str(msg))
        self.addCleanup(setattr, run_flight, "log", real_log)

    def _cfg(self, run_lines: str, profile: str = "stock-v3.5") -> Path:
        p = self.root / "run.toml"
        p.write_text(f'[fidelity]\nprofile = "{profile}"\n[run]\n{run_lines}', encoding="utf-8")
        return p


class ThePresetIsRestatedNeverOverridden(_Base):

    @needs_v314_engine
    def test_a_different_command_line_preset_is_refused_before_anything_runs(self):
        cfg = self._cfg('engine = "3.1.4"\npreset = "ORACLES_2016_2DS_H"\n',
                        profile="oracles-production")
        raw = self.root / "base160101000000.2DS"
        raw.write_bytes(b"")
        with redirect_stdout(io.StringIO()):
            rc = run_flight.main(["--config", str(cfg), "--engine", "3.1.4", "--port-validation",
                                  "--preset", "DEMO_2DS_H", "--yes",
                                  "--out", str(self.root / "out"), str(raw)])
        self.assertEqual(rc, 2)
        self.assertIn("--preset ORACLES_2016_2DS_H", "\n".join(self.lines))
        self.assertFalse((self.root / "out").exists())


class OutStagesAndTasFileFoldIn(_Base):

    def _args(self, **kw):
        base = dict(preset="DEMO_2DS_H", out=Path("../_decoded"), stages="234", tas_file=None)
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_absent_flags_take_the_files_values_relative_to_the_file(self):
        cfg = load_config(self._cfg('engine = "3.5"\npreset = "DEMO_2DS_H"\nout = "o"\n'
                                    'stages = "234c"\ntas_file = "air.cdf"\n'))
        args = run_flight._fold_run_table(cfg, self._args(), set())
        self.assertEqual(args.stages, "234c")
        self.assertEqual(args.out, (self.root / "o").resolve())
        self.assertEqual(args.tas_file, (self.root / "air.cdf").resolve())

    def test_a_given_flag_wins_and_says_so(self):
        cfg = load_config(self._cfg('engine = "3.5"\npreset = "DEMO_2DS_H"\nstages = "234c"\n'))
        args = run_flight._fold_run_table(cfg, self._args(stages="23"), {"--stages", "23"})
        self.assertEqual(args.stages, "23")
        self.assertTrue(any("--stages wins" in m for m in self.lines))

    def test_the_arrayprobe_run_path_passing_the_same_values_logs_nothing(self):
        cfg = load_config(self._cfg('engine = "3.5"\npreset = "DEMO_2DS_H"\nout = "o"\n'))
        out = (self.root / "o").resolve()
        run_flight._fold_run_table(cfg, self._args(out=out), {"--out", str(out)})
        self.assertEqual(self.lines, [])

    def test_a_probe_the_preset_does_not_process_is_refused(self):
        cfg = load_config(self._cfg('engine = "3.5"\npreset = "DEMO_2DS_H"\nprobe = "CIP"\n'))
        run_flight.use_preset("DEMO_2DS_H")
        self.assertIsNone(run_flight._fold_run_table(cfg, self._args(), set()))

    @unittest.skipUnless(AIRCRAFT.is_file(), "tracked demo aircraft file absent")
    def test_a_v35_file_naming_its_tas_file_is_no_longer_refused_for_lacking_one(self):
        shutil.copy(AIRCRAFT, self.root / AIRCRAFT.name)
        cfg = self._cfg(f'engine = "3.5"\npreset = "DEMO_2DS_H"\ntas_file = "{AIRCRAFT.name}"\n')
        raw = self.root / "base160101000000.2DS"
        # Non-empty: since 2026-10-06 the driver's input preflight
        # (driver/preflight_inputs._check_readable_file) refuses a 0-byte raw before
        # stage 2. A --dry-run never decodes it, so any byte will do.
        raw.write_bytes(b"\0")
        with redirect_stdout(io.StringIO()):
            rc = run_flight.main(["--config", str(cfg), "--engine", "3.5",
                                  "--preset", "DEMO_2DS_H", "--dry-run",
                                  "--out", str(self.root / "out"), str(raw)])
        text = "\n".join(self.lines)
        self.assertNotIn("none was given", text)
        self.assertEqual(rc, 0, text[-2000:])


if __name__ == "__main__":
    unittest.main()
