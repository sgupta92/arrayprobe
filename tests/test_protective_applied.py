# SPDX-License-Identifier: BSD-3-Clause
"""Steps 4-5: the protective set resolved and stamped by steps 1-3 is actually APPLIED.

A ``protective=on:<names>`` stamp must name corrections that ran.

"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)
run_flight = sys.modules[_spec.name]

try:
    from arrayprobe_enhancements import pipeline, registry
except ImportError:                                   # pragma: no cover -- CI installs it
    pipeline = registry = None

GLITCH = "particle_time_glitch_fix"


class _Globals(unittest.TestCase):
    def setUp(self):
        self._saved = (run_flight.ACTIVE.name, run_flight.ENGINE, run_flight.PROTECTIVE_MODE,
                       run_flight.PROTECTIVE_ON)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        name, engine, mode, on = self._saved
        run_flight.use_preset(name)
        run_flight.ENGINE, run_flight.PROTECTIVE_MODE, run_flight.PROTECTIVE_ON = engine, mode, on
        self.tmp.cleanup()

    def _args(self, **kw):
        base = dict(config=None, enhancements=False, out=self.tmp.name, stages="12s",
                    iat_file=None, protective_worker=False)
        base.update(kw)
        return SimpleNamespace(**base)


@unittest.skipIf(pipeline is None, "arrayprobe_enhancements not installed")
class ProtectiveSetIsApplied(_Globals):
    def _cip(self):
        run_flight.use_preset("UND_2016_CIP")
        run_flight.ENGINE = "3.5"
        run_flight.PROTECTIVE_MODE = "auto"
        run_flight.PROTECTIVE_ON = run_flight.resolve_protective()

    def test_cip_applier_runs_the_set_with_drop_policy_and_no_config(self):
        self._cip()
        self.assertIn(GLITCH, run_flight.PROTECTIVE_ON)
        args = self._args()
        with mock.patch.object(pipeline, "apply_to_outputs", return_value=[{}]) as apply:
            rc = run_flight.apply_enhancements_to_run(
                args, ["stem1"], protective=run_flight.protective_to_apply(args))
        self.assertEqual(rc, 0)
        apply.assert_called_once()
        resolved = apply.call_args.args[4]
        on = sorted(n for n, v in resolved.items() if v)
        # The chain gets every name except the ones the driver applies in S4 (tas_grid_fix).
        self.assertEqual(on, sorted(run_flight.pipeline_protective(run_flight.PROTECTIVE_ON)))
        self.assertEqual(apply.call_args.kwargs["policies"], {GLITCH: {"policy": "drop"}})

    def test_stamp_names_only_what_is_applied(self):
        # Every stamped name has a chain adapter or is applied by the driver itself; since
        # 2026-09-26 tas_grid_fix is the latter (S4), no longer silently dropped.
        self._cip()
        for name in run_flight.PROTECTIVE_ON:
            self.assertTrue(name in pipeline._APPLIERS or name in run_flight.DRIVER_PROTECTIVE,
                            name)
        self.assertIn("tas_grid_fix", run_flight.PROTECTIVE_ON)
        self.assertIn(f"protective=on:{','.join(run_flight.PROTECTIVE_ON)}",
                      run_flight.proc_call_label())

    def test_a_jobs_worker_applies_nothing(self):
        self._cip()
        self.assertEqual(run_flight.protective_to_apply(self._args(protective_worker=True)), ())
        self.assertIn("--_protective-worker", _worker_cmd(self._args()))

    def test_oracles_lineage_invokes_nothing(self):
        for engine in ("3.1.4", "3.5"):
            run_flight.use_preset("ORACLES_2016_2DS_H")
            run_flight.ENGINE = engine
            for mode in ("auto", "on"):
                run_flight.PROTECTIVE_MODE = mode
                run_flight.PROTECTIVE_ON = run_flight.resolve_protective()
                self.assertEqual(run_flight.protective_to_apply(self._args()), ())
                self.assertNotIn("protective=", run_flight.proc_call_label())
                with mock.patch.object(pipeline, "apply_to_outputs") as apply:
                    # No --config, no --enhancements, empty set: the driver refuses (1)
                    # before touching the pipeline, as it always did.
                    run_flight.apply_enhancements_to_run(self._args(), ["s"], protective=())
                apply.assert_not_called()


def _worker_cmd(_args):
    """``_spawn_worker``'s source, read the way ``test_worker_argument_forwarding`` reads it."""
    import inspect
    return inspect.getsource(run_flight._spawn_worker)


@unittest.skipIf(pipeline is None, "arrayprobe_enhancements not installed")
class GlitchAdapterPolicy(unittest.TestCase):
    def _run(self, policies):
        outputs = SimpleNamespace(preset_probetype=1, policies=policies)
        # The keys the real corrected_proc_file returns and the adapter records.
        report = {"policy": "repair", "applied": {}, "counts": {}, "written": 0,
                  "port_cascade_before": 0, "port_cascade_after": 0}
        from arrayprobe_enhancements import particle_time_glitch_fix as mod
        with mock.patch.object(pipeline, "_enhanced_or_original", return_value=Path("p.nc")), \
                mock.patch.object(pipeline, "_enh_path", return_value=Path("e.nc")), \
                mock.patch.object(pipeline, "_tmp_for", return_value=Path("t.nc")), \
                mock.patch.object(pipeline, "_finish_enh_copy", return_value=Path("e.nc")), \
                mock.patch.object(mod, "corrected_proc_file", return_value=report) as fix:
            pipeline._apply_particle_time_glitch_fix(outputs)
        return fix.call_args

    def test_drop_reaches_the_glitch_fix(self):
        call = self._run({GLITCH: dict(registry.PROTECTIVE_POLICY[GLITCH])})
        self.assertEqual(call.kwargs.get("policy"), "drop")

    def test_no_policy_keeps_the_module_default(self):
        call = self._run({})
        self.assertNotIn("policy", call.kwargs)


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
