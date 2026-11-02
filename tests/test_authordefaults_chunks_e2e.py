# SPDX-License-Identifier: BSD-3-Clause
"""No silent defaults in the port's entry points, the chunked-run step, end to end: an
authordefaults file with ``--chunks``.

Two real ``run_flight.py`` subprocesses on a demo flight, both naming the same authordefaults file
over ``ORACLES_PRODUCTION``: ``--chunks 2`` must write output identical to ``--chunks 1``. That also
proves the chunk guard admits the file (a refusal would exit non-zero before any worker ran). The
S3 ``.call`` sidecar must carry the file's ``authordefaults:<path>#<sha>`` stamp, and an in-process
``--_run-chunk`` with the right ``authordefaults-<hash>`` profile name must set
``AUTHORDEFAULTS_STAMP`` to the file's own stamp before it fails on a missing raw file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _run_flight_state  # noqa: E402
from _profile_registry_guard import module_hooks  # noqa: E402
from arrayprobe.authordefaults import expected_filename, load_authordefaults
from arrayprobe.driver import run_flight

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
RUN_FLIGHT = TOOLS / "run_flight.py"

sys.path.insert(0, str(TOOLS))
from tests._repo import needs_v314_engine  # noqa: E402

import make_demo_flight  # noqa: E402

NONDETERMINISTIC_ATTRS = frozenset({"Creation Time", "Image Source"})

_BODY = '''
[fidelity]
base_profile = "ORACLES_PRODUCTION"

[thresholds.max_edge_img_ar]
value = 4
citation = "test fixture, author-defaults chunk path end to end"
'''


def _write_ad(d: Path) -> Path:
    data = _BODY.encode("utf-8")
    p = d / expected_filename(data)
    p.write_bytes(data)
    return p


def _assert_identical(tc: unittest.TestCase, path_a: Path, path_b: Path) -> None:
    """Copied from ``test_run_flight_chunk_resume.py``."""
    with netCDF4.Dataset(path_a) as a, netCDF4.Dataset(path_b) as b:
        tc.assertEqual(list(a.variables), list(b.variables))
        for name in a.variables:
            va = np.asarray(a.variables[name][:]).astype(np.float64)
            vb = np.asarray(b.variables[name][:]).astype(np.float64)
            tc.assertTrue(np.array_equal(va, vb, equal_nan=True), f"{name}: values differ")
        for attr in a.ncattrs():
            if attr not in NONDETERMINISTIC_ATTRS:
                tc.assertEqual(getattr(a, attr), getattr(b, attr), attr)


def _run(root: Path, raw: Path, toml: Path, chunks: int, out: Path) -> subprocess.CompletedProcess:
    args = [str(raw), "--config", str(toml), "--engine", "3.1.4", "--port-validation",
            "--preset", "DEMO_2DS_H", "--stages", "23",
            "--chunks", str(chunks), "--out", str(out), "--yes"]
    return subprocess.run([sys.executable, str(RUN_FLIGHT), *args], cwd=root,
                          env=os.environ.copy(), capture_output=True, text=True, timeout=300)


def _products(d: Path) -> dict[str, Path]:
    return {p.relative_to(d).as_posix(): p for p in d.rglob("*")
            if p.suffix in (".nc", ".cdf") and ".chunk" not in p.name}


# The in-process --_run-chunk registers an authordefaults-<hash> profile; the shared helper
# removes it after the module (it leaked into test_profile_registry_guard in one process).
setUpModule, tearDownModule = module_hooks()


class ChunkedEqualsSerialWithAuthorDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="authordefaults_e2e_"))
        raw = cls.root / "base160101000000.2DS"
        make_demo_flight.build_demo_flight(raw)
        cls.ad_path = _write_ad(cls.root)
        cls.ad = load_authordefaults(cls.ad_path)
        toml = cls.root / "run.toml"
        toml.write_text(f'[fidelity]\nauthordefaults = "{cls.ad_path.as_posix()}"\n',
                        encoding="utf-8")
        cls.serial_out = cls.root / "serial"
        cls.chunked_out = cls.root / "chunked"
        cls.serial = _run(cls.root, raw, toml, 1, cls.serial_out)
        cls.chunked = _run(cls.root, raw, toml, 2, cls.chunked_out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    @needs_v314_engine
    def test_both_runs_succeed_so_the_chunk_guard_admits_the_file(self):
        for proc in (self.serial, self.chunked):
            out = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, out)
            self.assertNotIn("ProfileNotReachableInChunkWorkers", out, out)
            self.assertIn("ALL DONE", out, out)
        self.assertIn("2 chunks", self.chunked.stdout + self.chunked.stderr)

    @needs_v314_engine
    def test_chunked_output_is_identical_to_serial(self):
        a, b = _products(self.serial_out), _products(self.chunked_out)
        self.assertTrue(a, "serial run wrote no netCDF product")
        self.assertEqual(sorted(a), sorted(b))
        for name in a:
            with self.subTest(product=name):
                _assert_identical(self, a[name], b[name])

    @needs_v314_engine
    def test_s3_call_stamp_carries_the_authordefaults_file(self):
        for out in (self.serial_out, self.chunked_out):
            calls = [p.read_text(encoding="utf-8") for p in out.rglob("*.call")]
            stamped = [c for c in calls if "authordefaults:" in c and self.ad.hash in c]
            self.assertTrue(stamped, f"no .call under {out} carries {self.ad.stamp()}: {calls}")


class WorkerCarriesTheStamp(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        old = (run_flight.AUTHORDEFAULTS_STAMP, run_flight.AUTHORDEFAULTS_PATH)

        def _restore():
            run_flight.AUTHORDEFAULTS_STAMP, run_flight.AUTHORDEFAULTS_PATH = old
        self.addCleanup(_restore)

    def test_run_chunk_sets_the_stamp_before_failing_on_a_missing_raw(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_ad(Path(d))
            ad = load_authordefaults(p)
            argv = ["--_run-chunk", str(Path(d) / "none.2DS"), "2DS", "ORACLES",
                    f"authordefaults-{ad.hash}", "", "", "30", str(Path(d) / "out.nc"),
                    "1", "10", "engine=3.5", f"authordefaults={p}"]
            run_flight.AUTHORDEFAULTS_STAMP = None
            with self.assertRaises(FileNotFoundError):
                run_flight.main(argv)
            self.assertEqual(run_flight.AUTHORDEFAULTS_STAMP, ad.stamp())

    def test_a_failing_chunk_leaves_no_stall_timer_armed(self):
        # A raise inside the chunk once left faulthandler's stall dump armed in
        # the calling process; 27 minutes later its dump crashed the test suite
        # (2026-10-13). Every start must be matched by a cancel.
        import faulthandler
        events = []
        with tempfile.TemporaryDirectory() as d:
            p = _write_ad(Path(d))
            ad = load_authordefaults(p)
            argv = ["--_run-chunk", str(Path(d) / "none.2DS"), "2DS", "ORACLES",
                    f"authordefaults-{ad.hash}", "", "", "30", str(Path(d) / "out.nc"),
                    "1", "10", "engine=3.5", f"authordefaults={p}"]
            with mock.patch.object(faulthandler, "dump_traceback_later",
                                   lambda *a, **k: events.append("start")), \
                    mock.patch.object(faulthandler, "cancel_dump_traceback_later",
                                      lambda: events.append("cancel")):
                with self.assertRaises(FileNotFoundError):
                    run_flight.main(argv)
        self.assertIn("start", events)
        self.assertEqual(events[-1], "cancel", events)
        self.assertEqual(events.count("start"), events.count("cancel"), events)


if __name__ == "__main__":
    unittest.main()
