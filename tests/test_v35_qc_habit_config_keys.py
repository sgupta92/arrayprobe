# SPDX-License-Identifier: BSD-3-Clause
"""``[v35]`` config keys ``iQC``/``iNewHabit``.

Both are already required, no-MATLAB-default arguments of
``arrayprobe_uiops.imgproc.imgproc_sm_v35``, already carried in ``scripts/run_flight.py``'s
``V35_CALL`` and already stamped -- what was missing is a way for a run CONFIG to set them
instead of only ``V35_CALL``'s own hardcoded 0/0. This file pins: both states of each key,
an invalid value refused naming the file and key, the value reaching ``V35_CALL`` and the
``.call`` stamp, and that the existing ``iQC=1`` + ``--chunks`` refusal still fires
when ``iQC=1`` came from a config rather than from ``V35_CALL``'s own default.

Uses ``tests/test_run_flight_config.py``'s own lightweight harness (call ``_apply_config``
directly against a hand-built ``Namespace`` and a temp TOML) for the fast checks, so most of
this file needs no flight decode; only the last class runs the real CLI path, and even that
returns before any stage executes (the chunk gate is asked in ``main()``'s preflight, before
S2 runs).
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from arrayprobe.config import ConfigError, load_config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
# Registered before exec: run_flight's dataclass fields use `from __future__ import
# annotations`, which resolves via sys.modules -- test_run_flight_config.py's own note.
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)

from tests import _run_flight_state  # noqa: E402


def _toml(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "run.toml"
    path.write_text(text, encoding="utf-8")
    return path


class _Args:
    def __init__(self, **kw):
        self.iat_file = run_flight.IAT_FILE
        self.diode_corrected = False
        self.accept_unstamped = False
        self.engine = "3.5"
        self.__dict__.update(kw)


V35_BASE = '[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\n'


class ConfigValidatesV35Keys(unittest.TestCase):
    """``arrayprobe.config.load_config`` -- both states, bad values, wrong engine, empty/unknown."""

    def test_iqc_0_inewhabit_0_is_accepted(self):
        cfg = load_config(_toml(V35_BASE + "[v35]\niQC = 0\niNewHabit = 0\n"))
        self.assertEqual((cfg.v35_i_qc, cfg.v35_i_new_habit, cfg.v35_declared), (0, 0, True))

    def test_iqc_1_inewhabit_1_is_accepted(self):
        cfg = load_config(_toml(V35_BASE + "[v35]\niQC = 1\niNewHabit = 1\n"))
        self.assertEqual((cfg.v35_i_qc, cfg.v35_i_new_habit, cfg.v35_declared), (1, 1, True))

    def test_no_v35_section_is_none_and_not_declared(self):
        cfg = load_config(_toml(V35_BASE))
        self.assertEqual((cfg.v35_i_qc, cfg.v35_i_new_habit, cfg.v35_declared),
                         (None, None, False))

    def test_one_key_at_a_time_leaves_the_other_none(self):
        cfg = load_config(_toml(V35_BASE + "[v35]\niQC = 1\n"))
        self.assertEqual((cfg.v35_i_qc, cfg.v35_i_new_habit), (1, None))

    def test_invalid_value_is_refused_naming_file_and_key(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(_toml(V35_BASE + "[v35]\niQC = 2\n"))
        self.assertIn("[v35].iQC", str(cm.exception))
        self.assertIn("2", str(cm.exception))

    def test_bool_is_not_accepted_as_a_bit(self):
        # TOML true/false parse as Python bool, an int subclass -- _load_thresholds's own
        # pattern excludes it explicitly, and this must too.
        with self.assertRaises(ConfigError):
            load_config(_toml(V35_BASE + "[v35]\niQC = true\n"))

    def test_unknown_key_is_refused(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(_toml(V35_BASE + "[v35]\niQC = 1\niFooBar = 1\n"))
        self.assertIn("iFooBar", str(cm.exception))

    def test_empty_section_is_refused(self):
        with self.assertRaises(ConfigError):
            load_config(_toml(V35_BASE + "[v35]\n"))

    def test_v35_section_under_engine_314_is_refused(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(_toml('[fidelity]\nprofile = "ORACLES_PRODUCTION"\n'
                              '[run]\nengine = "3.1.4"\n[v35]\niQC = 1\n'))
        self.assertIn("[v35]", str(cm.exception))
        self.assertIn("3.5", str(cm.exception))

    def test_v35_section_with_no_engine_named_is_refused(self):
        # [run].engine defaults to 3.1.4 downstream when absent; [v35] must still be refused
        # rather than silently waiting for a default it cannot see here.
        with self.assertRaises(ConfigError):
            load_config(_toml('[fidelity]\nprofile = "ORACLES_PRODUCTION"\n[v35]\niQC = 1\n'))


class ApplyConfigSetsV35Call(unittest.TestCase):
    """``run_flight._apply_config`` mutates the run's own ``V35_CALL``, and the stamp carries it."""

    def setUp(self):
        # _apply_config rebinds V35_CALL, PROFILE, CONFIG_PATH ...; restore
        # every UPPER_CASE global, not only the one under test.
        _run_flight_state.preserve(self, run_flight)

    def _apply(self, toml_text, args=None, argv=()):
        args = args or _Args()
        args.config = _toml(toml_text)
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_flight._apply_config(args, None, list(argv))
        return out, buf.getvalue()

    def test_default_is_unchanged_with_no_v35_section(self):
        self._apply(V35_BASE)
        self.assertEqual(run_flight.V35_CALL.i_qc, 0)
        self.assertEqual(run_flight.V35_CALL.i_new_habit, 0)

    def test_iqc_1_inewhabit_1_reaches_v35_call_and_is_logged(self):
        args, log = self._apply(V35_BASE + "[v35]\niQC = 1\niNewHabit = 1\n")
        self.assertIsNotNone(args)
        self.assertEqual(run_flight.V35_CALL.i_qc, 1)
        self.assertEqual(run_flight.V35_CALL.i_new_habit, 1)
        self.assertIn("v35", log)

    def test_value_reaches_the_imgproc_stamp(self):
        self._apply(V35_BASE + "[v35]\niQC = 1\niNewHabit = 1\n")
        self.assertIn("iQC=1,iNewHabit=1", run_flight.V35_CALL.imgproc_stamp())

    def test_one_key_leaves_the_other_at_its_prior_value(self):
        self._apply(V35_BASE + "[v35]\niQC = 1\n")
        self.assertEqual(run_flight.V35_CALL.i_qc, 1)
        self.assertEqual(run_flight.V35_CALL.i_new_habit, 0)
        self.assertIn("iQC=1,iNewHabit=0", run_flight.V35_CALL.imgproc_stamp())


class ChunksStillRefusesIqc1FromConfig(unittest.TestCase):
    """The ``--chunks`` + ``iQC=1`` refusal reads ``V35_CALL.i_qc`` live, so a config-set
    value must still trip it for a probetype-2 probe -- confirmed through the real CLI path
    (``[run].engine = "3.5"``, the ``DEMO_2DS_H`` preset). The gate fires in ``main()``'s
    preflight before S2 runs, so this returns immediately rather than decoding anything."""

    def setUp(self):
        for name in ("PROBE", "PROJECT", "PROFILE", "PROFILE_MODULE", "TAS_FILE", "JIT",
                     "ENGINE", "V35_CALL", "ACTIVE", "ORIENTATION", "D_CHOICE", "SA_METHOD",
                     "PRES_PA", "TEMP_C"):
            self.addCleanup(setattr, run_flight, name, getattr(run_flight, name))

    def test_iqc_1_from_config_still_refuses_chunks_for_2ds(self):
        from arrayprobe import cli

        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)

        _mdf_spec = importlib.util.spec_from_file_location(
            "make_demo_flight", ROOT / "scripts" / "make_demo_flight.py")
        make_demo_flight = importlib.util.module_from_spec(_mdf_spec)
        sys.modules.setdefault(_mdf_spec.name, make_demo_flight)
        _mdf_spec.loader.exec_module(make_demo_flight)
        raw = root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)

        toml = root / "run.toml"
        toml.write_text(
            '[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\n'
            'preset = "DEMO_2DS_H"\nout = "_decoded"\nstages = "23"\n'
            '[v35]\niQC = 1\n', encoding="utf-8")

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(["run", str(toml), str(raw), "--chunks", "2", "--yes"])
        text = out.getvalue() + err.getvalue()
        self.assertEqual(rc, 2, text)
        self.assertIn("iQC=1", text)


if __name__ == "__main__":
    unittest.main()
