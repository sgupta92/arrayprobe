# SPDX-License-Identifier: BSD-3-Clause
"""Four driver defects that each let a written number or a staleness decision go wrong silently.

1. ``--jobs`` workers were handed ``--tas-grid`` only when it was ``regular``. A parent that
   resolved ``probe`` (the explicit opt-out on a profile with no archived product) spawned
   workers that resolved ``regular`` for themselves, sized their files on the regular grid and
   stamped ``tas_grid=regular`` -- the opposite of what the parent was asked.
2. ``--chunks`` workers under engine 3.5 were not handed the run's ``iQC``/``iNewHabit``
   (``[v35]`` in a config): each worker computed with v3.5's defaults while the parent merged
   the chunks and stamped the proc file with the configured values.
3. An sd stamp from a TAS-chain run whose profile never reads an aircraft file (the v3.1.4
   ORACLES profiles) named the chain's tier but not its cutoff/default policy, although S4 sizes
   on the policy-substituted series; a run with another ``--tas-default-mps`` read the old sd as
   current and kept its numbers.
4. S4c refused a combine whose constituents disagree on having a TAS QC record only after it
   had written the product and its ``.call``; the next run then read that product as current,
   skipped it and exited 0.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import io
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np
from tests import _run_flight_state

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_run_flight_tas_chain as _chain_tests  # noqa: E402
from test_run_flight_tas_chain import (  # noqa: E402
    _nc_variables_equal,
    _StateIsolated,
    make_demo_flight,
)

setUpModule = _chain_tests.setUpModule


def _rf():
    return _chain_tests.run_flight


class _Isolated(_StateIsolated):
    """Restores every UPPER_CASE global of the driver (TAS_GRID, PROTECTIVE_MODE,
    PROTECTIVE_ON and V35_CALL included) through the shared helper, not a typed list."""

    def setUp(self):
        # _rf() is the module setUpModule bound; the helper snapshots all its globals.
        _run_flight_state.preserve(self, _rf())


class JobsWorkersGetTheResolvedTasGrid(_Isolated):

    def _ns(self, root: Path, tas_grid: str):
        return types.SimpleNamespace(
            stages="234", out=root, chunks=1, s2_jobs=1, iat_file="", preset="DEMO_2DS_H",
            tas_file=None, presets=None, config=None, allow_mixed_config=False,
            accept_unstamped=False, diode_corrected=False, engine="3.5",
            worker_stall_min=30.0, profile="arm-ena-stock-v3.5", tas_source="auto",
            tas_grid=tas_grid)

    def _worker_cmd(self, tas_grid: str) -> list[str]:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with mock.patch.object(_rf().subprocess, "Popen", return_value=mock.Mock()) as popen:
            _proc, log_f = _rf()._spawn_worker([root / "a.2DS"], self._ns(root, tas_grid),
                                                root / "worker.log")
        log_f.close()
        return popen.call_args.args[0]

    def test_a_probe_grid_parent_hands_its_workers_the_probe_grid(self):
        cmd = self._worker_cmd("probe")
        self.assertIn("--tas-grid", cmd)
        self.assertEqual(cmd[cmd.index("--tas-grid") + 1], "probe")

    def test_a_regular_grid_parent_still_hands_its_workers_the_regular_grid(self):
        cmd = self._worker_cmd("regular")
        self.assertEqual(cmd[cmd.index("--tas-grid") + 1], "regular")

    @unittest.skipUnless(
        importlib.util.find_spec("arrayprobe_uiops.register_arm_stock") is not None,
        "arrayprobe_uiops.register_arm_stock: the ARM ENA profile registration module is not "
        "in this distribution")
    def test_a_worker_left_to_itself_would_resolve_the_other_grid(self):
        """Why the forward matters: on this profile the worker's own default is ``regular``."""
        # I001: in the release tree, without the v3.1.4 package, ruff files these two apart.
        import arrayprobe_uiops.register_arm_stock  # noqa: F401, I001 -- registers the profile
        from arrayprobe.profiles import PROFILES
        rf = _rf()
        rf.PROFILE = PROFILES["arm-ena-stock-v3.5"]
        rf.PROTECTIVE_MODE = "auto"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rf.default_tas_grid("auto"), "regular")


class ChunkWorkersGetTheV35Switches(_Isolated):
    """A real ``--chunks 2`` S3 under engine 3.5 with ``iNewHabit=1``: every worker is told the
    switch, and the merged proc equals a serial run with the same switch, variable for
    variable."""

    ENGINE = ("--engine", "3.5", "--profile", "stock-v3.5")

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _rf().main(argv)
        self.assertEqual(rc, 0, buf.getvalue())

    def test_chunked_equals_serial_under_i_new_habit(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        dirs = {k: root / k for k in ("serial", "chunked")}
        for d in dirs.values():
            d.mkdir()
            raw = d / "base160101000000.2DS"
            make_demo_flight.build_demo_flight(raw, n_seconds=3)
            self._run(["--preset", "DEMO_2DS_H", *self.ENGINE, "--stages", "2", "--yes",
                       "--out", str(d), str(raw)])
        switched = dataclasses.replace(_rf().V35_CALL, i_new_habit=1)
        s3 = ["--preset", "DEMO_2DS_H", *self.ENGINE, "--stages", "3", "--yes",
              "--tas-source", "probe"]
        with mock.patch.object(_rf(), "V35_CALL", switched):
            self._run([*s3, "--out", str(dirs["serial"]),
                       str(dirs["serial"] / "base160101000000.2DS")])
            real_popen = _rf().subprocess.Popen
            with mock.patch.object(_rf().subprocess, "Popen",
                                   side_effect=lambda *a, **kw: real_popen(*a, **kw)) as popen:
                self._run([*s3, "--chunks", "2", "--out", str(dirs["chunked"]),
                           str(dirs["chunked"] / "base160101000000.2DS")])
        workers = [c.args[0] for c in popen.call_args_list if "--_run-chunk" in c.args[0]]
        self.assertGreaterEqual(len(workers), 2, "no chunk workers were spawned")
        for cmd in workers:
            self.assertIn("v35_call=iQC:0,iNewHabit:1", cmd)
        ok, msg = _nc_variables_equal(dirs["serial"] / "proc.base160101000000.H.nc",
                                      dirs["chunked"] / "proc.base160101000000.H.nc")
        self.assertTrue(ok, msg)


class SdStampNamesTheChainPolicy(_Isolated):

    def _chain(self, policy):
        rf = _rf()
        return rf._tas_sources.ChainResult(
            mode="auto", tier="merge", source="oracles-p3-merge", path="m.nc",
            time=np.array([120000.0]), tas=np.array([100.0]), policy=policy, steps=[],
            substituted=[], lines=[], provenance={})

    def _sd_label(self, profile, engine, policy):
        rf = _rf()
        rf.ENGINE, rf.PROFILE = engine, profile
        rf.TAS_POLICY = policy
        rf.TAS_CHAIN = self._chain(policy)
        rf.TAS_FILE = None
        return rf.sd_call_label(rf.IAT_FILE)

    def test_a_different_default_makes_the_sd_stale_on_a_profile_that_reads_no_tas(self):
        rf = _rf()
        a = self._sd_label(rf.ORACLES_PRODUCTION, "3.1.4", rf._mtf.TasPolicy())
        b = self._sd_label(rf.ORACLES_PRODUCTION, "3.1.4",
                           rf._mtf.TasPolicy(default_mps=150.0))
        self.assertFalse(rf._stamps_equivalent(a, b))
        self.assertFalse(rf._stamps_equivalent(b, a))

    def test_a_stamp_written_before_the_policy_was_named_reads_as_the_default_policy(self):
        rf = _rf()
        now = self._sd_label(rf.ORACLES_PRODUCTION, "3.1.4", rf._mtf.TasPolicy())
        older = " ".join(t for t in now.split(" ") if not t.startswith("tas_series_policy="))
        self.assertNotEqual(older, now)
        self.assertTrue(rf._stamps_equivalent(older, now))
        other = self._sd_label(rf.ORACLES_PRODUCTION, "3.1.4",
                               rf._mtf.TasPolicy(default_mps=150.0))
        self.assertFalse(rf._stamps_equivalent(older, other))

    def test_a_profile_that_reads_tas_names_the_policy_once(self):
        rf = _rf()
        label = self._sd_label(rf.STOCK_V35, "3.5", rf._mtf.TasPolicy())
        self.assertEqual(label.count("tas_policy="), 1)
        self.assertNotIn("tas_series_policy=", label)


class CombineRefusesBeforeWriting(_Isolated):

    def _setup_sds(self, out: Path, stems):
        rf = _rf()
        rf.ENGINE = "3.1.4"
        sds = []
        for stem in stems:
            sd = rf.sd_path(stem, out)
            sd.write_bytes(b"sd")
            rf.write_stamp(sd, "engine=3.1.4 iat_file=x profile=oracles-production")
            sds.append(sd)
        rec = rf._tas_sources.qc_record(None, rf._mtf.TasPolicy(), [120000.0], [],
                                        legacy_subs=[])
        rf._tas_sources.write_qc_sidecar(sds[0], rec)
        return sds

    def test_a_refused_combine_leaves_no_product_to_skip_next_time(self):
        rf = _rf()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        stems = ["base160101000000", "base160101010000"]
        self._setup_sds(out, stems)

        def fake_combine(sd_files, partial, first_stem, borrowed):
            Path(partial).write_bytes(b"combined")

        target = rf.combine_out_path(stems, out)
        with mock.patch.object(rf, "_combine_call", side_effect=fake_combine), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                rf.stage_combine(stems, out)
            self.assertFalse(target.exists())
            self.assertFalse(rf.call_path(target).exists())
            # The same inputs are refused again, not skipped as a finished product.
            with self.assertRaises(SystemExit):
                rf.stage_combine(stems, out)


if __name__ == "__main__":
    unittest.main()
