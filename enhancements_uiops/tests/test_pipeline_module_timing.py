# SPDX-License-Identifier: BSD-3-Clause
"""The enhancement pass names its own time split: one log line per module, nothing more.

``pipeline.apply_to_outputs`` prints ``<stem>: module <name> start`` before each applier and
``<stem>: module <name> done (<s> s)`` (or ``skipped (<s> s)``) after it, so a long pass's
log says which module the time went to. The timing is log-only: running the same pass under
a different clock writes the same files, variable for variable, and the same record.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

from arrayprobe_enhancements import pipeline, registry

ROOT = Path(__file__).resolve().parents[2]
PIP_PROC = ROOT / "tests" / "data" / "s7a_pip_octave_golden.nc"
STEM = "base160912120000"
ON = ("particle_time_glitch_fix", "int_arr_rollback_fix")


def _only(*names: str) -> dict[str, bool]:
    return {n: n in names for n in registry.REGISTRY}


def _variables(path: Path) -> dict[str, np.ndarray]:
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        return {k: np.asarray(v[:]) for k, v in ds.variables.items()}


@unittest.skipUnless(PIP_PROC.is_file(), "Probetype-1 proc fixture is not distributed with the "
                                         "package; this test runs in the development repository")
class EveryModuleLogsItsOwnTime(unittest.TestCase):

    def _run(self, clock=None) -> tuple[Path, str, dict]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        proc = out / f"proc.{STEM}.H.nc"
        shutil.copyfile(PIP_PROC, proc)
        with netCDF4.Dataset(proc, "a") as ds:
            for name in ("particle_time", "Time_in_seconds"):
                var = ds.variables[name]
                var.set_auto_mask(False)
                v = np.asarray(var[:]).ravel().copy()
                v[400] = 0          # one glitched header, so the glitch repair has work to do
                var[:] = v
        proc.with_name(proc.name + ".call").write_text("engine=3.5 profile=stock-v3.5\n",
                                                       encoding="utf-8")
        buf = io.StringIO()
        patch = (mock.patch.object(pipeline, "_clock", clock) if clock is not None
                 else contextlib.nullcontext())
        with patch, contextlib.redirect_stdout(buf):
            [report] = pipeline.apply_to_outputs("unused.toml", "3.5", out, [STEM], _only(*ON),
                                                 preset_probetype=1)
        return out, buf.getvalue(), report

    def test_each_applied_module_has_a_start_and_a_timed_done_line(self):
        _, log, report = self._run()
        self.assertEqual(sorted(report["applied"]), sorted(ON))
        for name in ON:
            self.assertEqual(log.count(f"{STEM}: module {name} start\n"), 1, log)
            self.assertRegex(log, rf"{STEM}: module {re.escape(name)} done \(\d+\.\d{{3}} s\)\n")
        # Modules left OFF are not named in the timing lines. No stage runner is lent here,
        # so the port's S4 cannot rebuild the sd from the enhanced proc: that is timed too.
        self.assertRegex(log, rf"{STEM}: module S4 \(sd rebuild\) failed \(\d+\.\d{{3}} s\)\n")
        timed = set(re.findall(rf"{STEM}: module (\S+) ", log))
        self.assertEqual(timed, set(ON) | {"S4"})

    def test_a_module_skipped_by_name_says_it_did_not_run(self):
        with mock.patch.dict(pipeline._APPLIERS):
            del pipeline._APPLIERS["int_arr_rollback_fix"]
            _, log, report = self._run()
        self.assertIn("int_arr_rollback_fix", report["skipped"])
        self.assertIn(f"{STEM}: module int_arr_rollback_fix skipped (not run)\n", log)
        self.assertNotIn(f"{STEM}: module int_arr_rollback_fix start", log)

    def test_the_clock_reaches_no_output(self):
        out_a, _, report_a = self._run()
        ticks = itertools.count(start=10**6, step=12345.678)
        out_b, log_b, report_b = self._run(clock=lambda: next(ticks))
        self.assertIn("(12345.678 s)", log_b)          # the swapped clock really was read
        self.assertEqual(json.dumps(report_a, sort_keys=True),
                         json.dumps(report_b, sort_keys=True))
        files_a = sorted(p.name for p in out_a.iterdir())
        self.assertEqual(files_a, sorted(p.name for p in out_b.iterdir()))
        compared = 0
        for name in files_a:
            if name.endswith(".nc"):
                va, vb = _variables(out_a / name), _variables(out_b / name)
                self.assertEqual(sorted(va), sorted(vb), name)
                for key in va:
                    self.assertTrue(np.array_equal(va[key], vb[key], equal_nan=True),
                                    f"{name}:{key}")
                compared += 1
            elif name.endswith((".json", ".call")):
                self.assertEqual((out_a / name).read_text(encoding="utf-8"),
                                 (out_b / name).read_text(encoding="utf-8"), name)
        self.assertGreaterEqual(compared, 2)            # the port's proc and the enhanced proc

# _release_fixture_guard: needs a real field-campaign file, not in the release
import unittest as _rfg_unittest  # noqa: E402
raise _rfg_unittest.SkipTest(
    "this test needs a real field-campaign PIP file (about 1,200 particles); the "
    "shipped fixture is a small synthetic stand-in, and this release does not include real data")

if __name__ == "__main__":
    unittest.main()
