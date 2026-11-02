# SPDX-License-Identifier: BSD-3-Clause
"""Acceptance tests: ``run_flight.py``'s TAS source-chain wiring (T2, 2026-09-23).

Four things this module proves -- the T2 plan's acceptance list
(the TAS execution plan's step 3), plus the author's
E2 ruling the same day for the last one:

* every default stamp (``TAS_SOURCE`` unset, so ``TAS_CHAIN`` stays ``None``) is unchanged from
  the module as it stood before this wiring landed (compared against the git blob at
  :data:`PRE_WIRING_REV`, the wiring commit's parent -- not ``HEAD``, which after the commit is
  the wiring itself -- and not a hand-copied string);
* ``_stamps_equivalent`` still holds for those stamps;
* the default S4 (``stage4``) output is bit-identical, variable for variable, to a run through
  that same pre-wiring module, on the same demo flight;
* ``stage4`` hands ``sizeDist`` the chain's own values, not the raw ``<stem>.tas.csv``, once a
  run opts into a chain (``TAS_SOURCE`` set) -- for an ``aircraft``-tier chain, and (E2, author,
  2026-09-23: *"yes"* to the plan's question on the probe tier) for a ``probe``-tier chain too: S4
  no longer reads the raw probe csv unmodified once a run opts in, so an out-of-range row
  reaches ``sizeDist`` as the policy default, not as itself, the same as any other tier.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np
from tests import _run_flight_state
from tests._repo import needs_v314_engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"

_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules.setdefault("make_demo_flight", make_demo_flight)
_DEMO_SPEC.loader.exec_module(make_demo_flight)

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
run_flight = None  # bound in setUpModule, the same pattern every sibling test module uses


#: The stages-2-3 output directory shared by :class:`_WithProcAndCsv` (built on first use).
_PROC_CACHE = None


def tearDownModule():
    global _PROC_CACHE
    if _PROC_CACHE is not None:
        _PROC_CACHE.cleanup()
        _PROC_CACHE = None


def setUpModule():
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)


#: The last commit before the TAS source-chain wiring landed (T2 is 96ace1a; this is its parent,
#: an ancestor of master). The baseline used to be ``HEAD``, which was right only while the wiring
#: sat uncommitted: once 96ace1a was committed, ``HEAD:`` *was* the wiring, both sides of every
#: comparison below were the same file, and they passed by construction (found by the chunked-run
#: verifier, 2026-09-23). Pinned, and :func:`_pre_wiring_run_flight` refuses any baseline that
#: already carries the wiring, so repointing it at a later commit fails instead of passing.
PRE_WIRING_REV = "0a7480b226f5229ea7bc427bee273ae134f4363d"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _run_flight_at(rev: str, module_name: str):
    """``scripts/run_flight.py`` as it stood at ``rev``, loaded from the git blob rather than
    hand-copied, so the comparison cannot drift from what that commit actually has. Skips --
    naming why -- when this clone lacks ``rev`` (a shallow checkout: CI's ``actions/checkout``
    default is depth 1), rather than silently falling back to a baseline that is not one."""
    if _git("cat-file", "-e", f"{rev}^{{commit}}").returncode != 0:
        raise unittest.SkipTest(
            f"baseline {rev[:7]} is not in this clone (shallow checkout?); the pre-wiring "
            "comparison needs it -- run in a full clone, or fetch with fetch-depth: 0")
    # `git show <rev>:<path>` takes <path> relative to the repo ROOT, never to `cwd=` --
    # computed rather than hand-spelled ("scripts/run_flight.py") so this does not
    # silently break if the package ever moves within the repo.
    toplevel = Path(_git("rev-parse", "--show-toplevel").stdout.strip())
    rel = (TOOLS / "run_flight.py").resolve().relative_to(toplevel.resolve()).as_posix()
    # A historical commit has its own layout: before the repository's layout move the driver
    # lived under ``python_port/``, so the path is looked up in the commit's own tree.
    if _git("cat-file", "-e", f"{rev}:{rel}").returncode != 0:
        # Before the layout move the driver was ``python_port/tools/run_flight.py``.
        for cand in (f"python_port/{rel}", "python_port/tools/run_flight.py"):
            if _git("cat-file", "-e", f"{rev}:{cand}").returncode == 0:
                rel = cand
                break
    shown = _git("show", f"{rev}:{rel}")
    if shown.returncode != 0:
        raise AssertionError(f"git show {rev[:7]}:{rel} failed: {shown.stderr}")
    tmp = Path(tempfile.mkdtemp()) / f"{module_name}.py"
    tmp.write_text(shown.stdout, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(module_name, tmp)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _pre_wiring_run_flight():
    """``scripts/run_flight.py`` at :data:`PRE_WIRING_REV` -- the baseline the TAS source-chain
    wiring (step 3) had not yet touched. Refuses a baseline that already has the wiring
    (``TAS_CHAIN``): that comparison would be the module against itself."""
    mod = _run_flight_at(PRE_WIRING_REV, "run_flight_pre_wiring")
    if hasattr(mod, "TAS_CHAIN"):
        raise AssertionError(
            f"baseline {PRE_WIRING_REV[:7]} already carries the TAS chain wiring (TAS_CHAIN), so "
            "a 'default path unchanged' comparison against it would test nothing")
    return mod


def _run_default_flight(module, out_dir: Path, raw: Path) -> Path:
    """``--preset DEMO_2DS_H --stages 234``, no ``--config``, no ``--tas-source``: the
    completely untouched-by-the-chain default path, through whichever ``run_flight`` module is
    passed in."""
    # R4: the current driver refuses --engine 3.1.4 without --port-validation; the
    # frozen pre-wiring copy predates the flag (it has no PORT_VALIDATION global) and rejects it.
    flag = ["--port-validation"] if hasattr(module, "PORT_VALIDATION") else []
    argv = ["--engine", "3.1.4", *flag, "--preset", "DEMO_2DS_H", "--stages", "234", "--yes",
            "--out", str(out_dir), str(raw)]
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = module.main(argv)
    assert rc == 0, buf.getvalue()
    return out_dir / f"sd.{raw.stem}.H.nc"


def _nc_variables_equal(a: Path, b: Path) -> tuple[bool, str]:
    """Every variable, ``np.array_equal`` -- ``'Creation Time'`` is a global attribute, not a
    variable, so comparing only variables already excludes it without special-casing it."""
    with netCDF4.Dataset(a) as da, netCDF4.Dataset(b) as db:
        if set(da.variables) != set(db.variables):
            return False, f"variable sets differ: {set(da.variables)} vs {set(db.variables)}"
        for name in da.variables:
            va, vb = da.variables[name][:], db.variables[name][:]
            # equal_nan=True: several sd variables (e.g. total_area on a flight this small)
            # are legitimately all-NaN, and plain np.array_equal treats NaN != NaN, which
            # would report an identical NaN pattern as "differs".
            if not np.array_equal(np.asarray(va), np.asarray(vb), equal_nan=True):
                return False, f"variable {name!r} differs"
    return True, ""


class _StateIsolated(unittest.TestCase):
    """Snapshot/restore the module globals this suite touches -- test_run_flight_any_profile.py
    and test_run_from_config_v35.py's own pattern, so one test's TAS_CHAIN/TAS_SOURCE cannot
    leak into the next."""

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)


class DefaultStampsAreUnaffected(_StateIsolated):
    """T2 acceptance #1: capture ``proc_call_label()``/``sd_call_label(...)`` for a default run
    (no ``--config``, no ``--tas-source``) before and after the wiring."""

    def test_proc_and_sd_stamps_match_the_pre_wiring_module(self):
        self.assertIsNone(run_flight.TAS_CHAIN)
        head = _pre_wiring_run_flight()
        # The current stamps may carry R4's port_validation=on token (set once any v3.1.4
        # main() ran in this process); the frozen copy cannot. Equal once that token is off.
        strip = run_flight._strip_port_validation
        self.assertEqual(strip(run_flight.proc_call_label()), head.proc_call_label())
        self.assertEqual(strip(run_flight.sd_call_label(run_flight.IAT_FILE)),
                         head.sd_call_label(head.IAT_FILE))

    def test_the_baseline_guard_rejects_a_module_that_has_the_wiring(self):
        """The guard fires: ``HEAD`` carries the wiring, so it would be refused as a baseline --
        the exact state that made this comparison vacuous once 96ace1a was committed."""
        head = _run_flight_at("HEAD", "run_flight_head_guard_check")
        self.assertTrue(hasattr(head, "TAS_CHAIN"))
        self.assertFalse(hasattr(_pre_wiring_run_flight(), "TAS_CHAIN"))

    def test_stamps_equivalent_holds(self):
        proc = run_flight.proc_call_label()
        sd = run_flight.sd_call_label(run_flight.IAT_FILE)
        self.assertTrue(run_flight._stamps_equivalent(proc, proc))
        self.assertTrue(run_flight._stamps_equivalent(sd, sd))


class DefaultStage4OutputIsBitIdentical(_StateIsolated):
    """T2 acceptance #2: the same demo flight, run end to end through the pre-wiring module and
    through the current one, must write the same ``sd`` file, variable for variable."""

    def test_sd_file_matches_the_pre_wiring_module(self):
        head = _pre_wiring_run_flight()
        with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
            raw_a = Path(da) / "base160101000000.2DS"
            raw_b = Path(db) / "base160101000000.2DS"
            make_demo_flight.build_demo_flight(raw_a, n_seconds=3)
            make_demo_flight.build_demo_flight(raw_b, n_seconds=3)
            sd_a = _run_default_flight(run_flight, Path(da), raw_a)
            sd_b = _run_default_flight(head, Path(db), raw_b)
            self.assertTrue(sd_a.exists())
            self.assertTrue(sd_b.exists())
            ok, msg = _nc_variables_equal(sd_a, sd_b)
            self.assertTrue(ok, msg)


class _WithProcAndCsv(_StateIsolated):
    """A real ``proc.*.nc`` + ``<stem>.tas.csv`` pair, built through stages 2-3 of the current
    module on a tiny demo flight -- the input :func:`run_flight.stage4` needs regardless of
    which TAS series it is then handed."""

    def _build_proc_and_csv(self):
        """Stages 2-3 run once per module (the first caller builds it, with every assertion
        below); each test then gets its own copy of the files, because stage4 writes into
        ``out``. Speed only (TEST_SPEEDUP, 2026-09-26): the chain's inputs are unchanged."""
        global _PROC_CACHE
        if _PROC_CACHE is None:
            _PROC_CACHE = self._build_proc_and_csv_uncached()
        src = Path(_PROC_CACHE.name)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        shutil.copytree(src, out, dirs_exist_ok=True)
        raw = out / "base160101000000.2DS"
        proc = out / f"proc.{raw.stem}.H.nc"
        tas_csv = out / f"{raw.stem}.tas.csv"
        self.assertTrue(proc.exists())
        self.assertTrue(tas_csv.exists())
        return out, raw, proc, tas_csv

    def _build_proc_and_csv_uncached(self):
        tmp = tempfile.TemporaryDirectory()
        out = Path(tmp.name)
        raw = out / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw, n_seconds=3)
        argv = ["--engine", "3.1.4", "--port-validation", "--preset", "DEMO_2DS_H",
                "--stages", "23", "--yes", "--out", str(out), str(raw)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main(argv)
        self.assertEqual(rc, 0, buf.getvalue())
        proc = out / f"proc.{raw.stem}.H.nc"
        tas_csv = out / f"{raw.stem}.tas.csv"
        self.assertTrue(proc.exists())
        self.assertTrue(tas_csv.exists())
        return tmp

    def _run_stage4_mocked(self, out, raw, proc, chain):
        run_flight.TAS_CHAIN = chain
        run_flight.TAS_POLICY = chain.policy
        with mock.patch.object(run_flight.sizedist, "run") as mocked:
            mocked.side_effect = lambda *a, **kw: Path(a[1]).write_bytes(b"")
            run_flight.stage4(proc, raw.stem, out, run_flight.IAT_FILE)
        self.assertTrue(mocked.called)
        return mocked.call_args


class AircraftChainFeedsSizedistTheChainValues(_WithProcAndCsv):
    """T2 acceptance #3: with an aircraft chain, ``sizedist.run`` receives the aircraft values."""

    @needs_v314_engine
    def test_stage4_hands_sizedist_the_aircraft_series(self):
        out, raw, proc, tas_csv = self._build_proc_and_csv()
        probe_t, _probe_tas = run_flight.load_tas_info(tas_csv)
        policy = run_flight._mtf.TasPolicy()
        seconds = np.unique(np.floor(probe_t).astype(np.int64))
        aircraft_value = 61.5  # distinct from whatever the synthetic demo probe csv carries
        chain = run_flight._tas_sources.ChainResult(
            mode="auto", tier="aircraft", source="oracles-p3-merge",
            path=str(out / "fake_merge.nc"), time=seconds.astype(np.float64),
            tas=np.full(seconds.shape, aircraft_value), policy=policy,
            steps=[], substituted=[], lines=[], provenance={})
        call = self._run_stage4_mocked(out, raw, proc, chain)
        got_tas = call.args[2]
        self.assertTrue(np.all(got_tas == aircraft_value),
                        f"sizedist.run's tas argument was not the aircraft series: {got_tas}")


class EnhancedSizedistAlsoUsesTheChain(_WithProcAndCsv):
    """The enhanced S4 (``EnhancedStages.sizedist``, which re-runs sizeDist on ``enh.proc``)
    must get the same chain series as :func:`run_flight.stage4`. Until 2026-09-23 it re-read the
    probe's raw ``.tas.csv``, so on a chain run the enhanced sd/combined products were sized on
    a different airspeed from the ordinary ones: on ARM 07-06, the stuck 6.0 m/s housekeeping
    value instead of ARM's ``true_airspeed``. Found by the ARM queue preparation."""

    @needs_v314_engine
    def test_enhanced_sizedist_hands_sizedist_the_aircraft_series(self):
        out, raw, proc, tas_csv = self._build_proc_and_csv()
        probe_t, _probe_tas = run_flight.load_tas_info(tas_csv)
        seconds = np.unique(np.floor(probe_t).astype(np.int64))
        aircraft_value = 61.5
        chain = run_flight._tas_sources.ChainResult(
            mode="auto", tier="aircraft", source="arm-aaf-merged",
            path=str(out / "fake_aaf.nc"), time=seconds.astype(np.float64),
            tas=np.full(seconds.shape, aircraft_value), policy=run_flight._mtf.TasPolicy(),
            steps=[], substituted=[], lines=[], provenance={})
        run_flight.TAS_CHAIN = chain
        run_flight.TAS_POLICY = chain.policy
        stages = run_flight.EnhancedStages(out, run_flight.IAT_FILE)
        with mock.patch.object(run_flight.sizedist, "run") as mocked:
            mocked.side_effect = lambda *a, **kw: Path(a[1]).write_bytes(b"")
            stages.sizedist(proc, raw.stem, out / f"{raw.stem}.enh.sd.nc")
        self.assertTrue(mocked.called)
        got_tas = mocked.call_args.args[2]
        self.assertTrue(np.all(got_tas == aircraft_value),
                        f"the enhanced S4 did not get the chain's series: {got_tas}")

    @needs_v314_engine
    def test_without_a_chain_the_enhanced_sizedist_reads_the_probe_csv(self):
        out, raw, proc, tas_csv = self._build_proc_and_csv()
        _t, probe_tas = run_flight.load_tas_info(tas_csv)
        self.assertIsNone(run_flight.TAS_CHAIN)
        stages = run_flight.EnhancedStages(out, run_flight.IAT_FILE)
        with mock.patch.object(run_flight.sizedist, "run") as mocked:
            mocked.side_effect = lambda *a, **kw: Path(a[1]).write_bytes(b"")
            stages.sizedist(proc, raw.stem, out / f"{raw.stem}.enh.sd.nc")
        np.testing.assert_array_equal(mocked.call_args.args[2], probe_tas)


class ProbeTierAlsoAppliesThePolicy(_WithProcAndCsv):
    """Author's E2 ruling, 2026-09-23 (yes to the plan's question on the probe tier): once a run
    opts into a chain, S4 never reads the raw probe ``.tas.csv`` again, even when the chain
    resolved to the ``probe`` tier itself -- it reads the chain's own policy-substituted
    series, through the same :func:`~arrayprobe.tools.tas_sources.series_for_sizedist` path an
    aircraft tier uses. So an out-of-range row (the -999 no-TAS marker, or 241,403 m/s) reaches
    ``sizeDist`` as ``TasPolicy.default_mps``, not as itself."""

    @needs_v314_engine
    def test_an_out_of_range_second_reaches_sizedist_as_the_default(self):
        out, raw, proc, tas_csv = self._build_proc_and_csv()
        probe_t, _probe_tas = run_flight.load_tas_info(tas_csv)
        policy = run_flight._mtf.TasPolicy()
        seconds = np.unique(np.floor(probe_t).astype(np.int64))
        # The chain's own series, as reduce_probe_csv would have built it: one row per second,
        # a normal in-range value everywhere except the one second the probe-tier reduction
        # found out of range and substituted to the policy default (its own job, exercised
        # directly here rather than through resolve_chain, which tests/test_tas_sources.py
        # covers).
        chain_tas = np.full(seconds.shape, 55.0)
        chain_tas[0] = policy.default_mps
        chain = run_flight._tas_sources.ChainResult(
            mode="probe", tier="probe", source="probe-tas-csv", path=str(tas_csv),
            time=seconds.astype(np.float64), tas=chain_tas, policy=policy,
            steps=[], substituted=[], lines=[], provenance={})
        call = self._run_stage4_mocked(out, raw, proc, chain)
        got_tas, got_time = call.args[2], call.args[3]
        first_second = got_time == seconds[0]
        self.assertTrue(np.all(got_tas[first_second] == policy.default_mps),
                        "the substituted second did not reach sizedist.run as the default")
        self.assertTrue(np.all(got_tas[~first_second] == 55.0),
                        "every other second should still be the chain's own (in-range) value, "
                        "not the raw csv's")

    def test_sd_call_label_names_the_probe_tier_chain(self):
        """The tas_series= fragment fires for a probe-tier chain too (E2), not only aircraft --
        config_label's own tas_chain= fragment already named which chain ran; this is the
        second, sd-only fragment naming which SERIES built the file."""
        policy = run_flight._mtf.TasPolicy()
        chain = run_flight._tas_sources.ChainResult(
            mode="probe", tier="probe", source="probe-tas-csv", path="x.tas.csv",
            time=np.array([120000.0]), tas=np.array([55.0]), policy=policy,
            steps=[], substituted=[], lines=[], provenance={})
        run_flight.TAS_CHAIN = chain
        label = run_flight.sd_call_label(run_flight.IAT_FILE)
        self.assertIn("tas_series=probe:probe-tas-csv", label)


class ChunkWorkersUseTheChainFileAndPolicy(_StateIsolated):
    """A real ``--chunks 2`` S3 under ``--tas-source`` (chunked-run verifier, 2026-09-23): the
    workers are handed the chain's own file and the parent's policy, and their merged proc is
    bit-identical to a serial S3 run with the same flags.

    Discriminating by construction: the merge-like file carries 350 m/s and the run's cutoff is
    400. The parent keeps 350; a worker that fell back to the module default policy (cutoff 300)
    would turn it into 170, and a worker without the chain file would use the engine's 170
    fallback -- either way its Time_in_seconds would not match the serial run's."""

    TAS_MPS = 350.0
    #: Engine 3.5, the engine every TAS-chain re-run uses and the one whose probetype-2
    #: --chunks is prefix-primed to byte-identity. Engine 3.1.4 has no such priming, so
    #: its chunked Time_in_seconds differs from serial whatever the TAS source (measured with the
    #: legacy --tas-file path too, 2026-09-23) -- not a property of the chain.
    ENGINE = ("--engine", "3.5", "--profile", "stock-v3.5")

    def _merge_like(self, path: Path, seconds_hhmmss) -> None:
        sod = [(s // 10000) * 3600 + (s // 100 % 100) * 60 + s % 100 for s in seconds_hhmmss]
        with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
            ds.createDimension("t", len(sod))
            t = ds.createVariable("Start_UTC", "f8", ("t",))
            t.units = "seconds"
            t[:] = sod
            v = ds.createVariable("True_Air_Speed", "f8", ("t",))
            v.units = "kts"
            v[:] = np.full(len(sod), self.TAS_MPS / (1852.0 / 3600.0))

    def _s3(self, out: Path, raw: Path, extra: list[str]) -> str:
        argv = ["--preset", "DEMO_2DS_H", *self.ENGINE, "--stages", "3",
                "--yes", "--tas-source", "merge", "--tas-search", str(out.parent / "merge"),
                "--tas-cutoff-mps", "400", *extra, "--out", str(out), str(raw)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main(argv)
        self.assertEqual(rc, 0, buf.getvalue())
        return buf.getvalue()

    def test_chunked_s3_matches_serial_and_workers_get_file_and_policy(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        dirs = {k: root / k for k in ("serial", "chunked", "merge")}
        for d in dirs.values():
            d.mkdir()
        for k in ("serial", "chunked"):
            raw = dirs[k] / "base160101000000.2DS"
            make_demo_flight.build_demo_flight(raw, n_seconds=3)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_flight.main(["--preset", "DEMO_2DS_H", *self.ENGINE, "--stages", "2",
                                      "--yes", "--out", str(dirs[k]), str(raw)])
            self.assertEqual(rc, 0, buf.getvalue())
        probe_t, _ = run_flight.load_tas_info(dirs["serial"] / "base160101000000.tas.csv")
        secs = sorted(set(np.floor(probe_t).astype(int).tolist()))
        self._merge_like(dirs["merge"] / "mrg1_P3_20160101_R1.nc",
                         list(range(secs[0] - 2, secs[-1] + 3)))

        self._s3(dirs["serial"], dirs["serial"] / "base160101000000.2DS", [])
        real_popen = run_flight.subprocess.Popen
        with mock.patch.object(run_flight.subprocess, "Popen",
                               side_effect=lambda *a, **kw: real_popen(*a, **kw)) as popen:
            self._s3(dirs["chunked"], dirs["chunked"] / "base160101000000.2DS",
                     ["--chunks", "2"])
        chain_file = str(dirs["chunked"] / "base160101000000.tas_merge.cdf")
        worker_cmds = [c.args[0] for c in popen.call_args_list if "--_run-chunk" in c.args[0]]
        self.assertGreaterEqual(len(worker_cmds), 2, "no chunk workers were spawned")
        for cmd in worker_cmds:
            self.assertEqual(cmd[cmd.index("--_run-chunk") + 6], chain_file)
            self.assertIn("tas_policy=cutoff=400.0,default=170.0", cmd)
        a = dirs["serial"] / "proc.base160101000000.H.nc"
        b = dirs["chunked"] / "proc.base160101000000.H.nc"
        ok, msg = _nc_variables_equal(a, b)
        self.assertTrue(ok, msg)
        stamp = (dirs["chunked"] / "proc.base160101000000.H.nc.call").read_text()
        self.assertIn("tas_chain=merge:oracles-p3-merge "
                      "tas_policy=(cutoff=400.0,default=170.0)", stamp)
        with netCDF4.Dataset(chain_file) as ds:
            self.assertTrue(np.all(np.asarray(ds.variables["TAS"][:]) == self.TAS_MPS))


if __name__ == "__main__":
    unittest.main()
