# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py --engine 3.5 --s2-jobs 2`` writes what ``--s2-jobs 1`` writes.

The library-level proof is ``tests/test_v35_spec_parallel.py``. This module drives the batch
driver's own stage 2 both ways on the tracked v3.5 raw fixture, in a subprocess bounded by a
timeout (a pool whose workers die at spawn hangs ``map``; see ``tests/test_spec_parallel.py``),
and compares every file the stage publishes. The driver stamps ``Creation Time`` from the
clock, so the subprocess pins ``run_flight.datetime`` to one instant. The only files left out
are the two run records, which describe the run rather than its output (``_RUN_RECORDS``).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PORT = Path(__file__).resolve().parents[1]
FIXTURE = PORT / "tests" / "data" / "v35_spec_raw_fixture"
TIMEOUT_S = 300

_SCRIPT = textwrap.dedent("""
    import sys
    from datetime import datetime as _datetime
    tools, raw, out, jobs = sys.argv[1:5]
    sys.path.insert(0, tools)
    import run_flight as rf

    class _Fixed(_datetime):
        @classmethod
        def now(cls, tz=None):
            return _datetime(2026, 9, 25, 0, 0, 0)

    rf.datetime = _Fixed
    sys.exit(rf.main([raw, "--engine", "3.5", "--profile", "stock-v3.5",
                      "--preset", "DEMO_2DS_H", "--stages", "2", "--out", out,
                      "--s2-jobs", jobs, "--yes"]))
""")


def _run(raw: Path, out: Path, jobs: int) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(PORT / "src"), str(PORT),
                                         env.get("PYTHONPATH", "")])
    argv = [sys.executable, "-c", _SCRIPT, str(PORT / "scripts"), str(raw), str(out), str(jobs)]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, env=env,
                              timeout=TIMEOUT_S, cwd=str(out.parent))
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"run_flight --s2-jobs {jobs} did not finish in {TIMEOUT_S}s; "
                             "a pool whose workers died at spawn is the known cause") from exc
    if done.returncode != 0:
        raise AssertionError(f"run_flight --s2-jobs {jobs} exited {done.returncode}\n"
                             f"{done.stdout[-3000:]}\n{done.stderr[-3000:]}")
    return done.stdout


#: Files that record how the run went rather than what it computed: the decode mode, and the
#: machine-load record the driver writes beside a run's products when it judges one.
_RUN_RECORDS = (".decode", ".load.json")


def _published(out: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.iterdir())
            if p.is_file() and not p.name.endswith(_RUN_RECORDS)}


class DriverS2JobsUnderEngine35(unittest.TestCase):

    def test_two_jobs_publish_the_same_files_as_one(self):
        tmp = Path(tempfile.mkdtemp(prefix="rf_v35_s2jobs_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        raw = tmp / "base160101000000.2DS"
        shutil.copyfile(FIXTURE, raw)
        serial_log = _run(raw, tmp / "serial", 1)
        parallel_log = _run(raw, tmp / "parallel", 2)
        want = _published(tmp / "serial")
        self.assertTrue(any(name.endswith(".nc") for name in want), want)
        got = _published(tmp / "parallel")
        self.assertEqual(sorted(got), sorted(want))
        differ = [name for name in want if got[name] != want[name]]
        self.assertEqual(differ, [], parallel_log[-3000:])
        self.assertIn("S2 parallel, 2 workers", parallel_log)
        self.assertNotIn("S2 parallel", serial_log)
        decode = next((tmp / "parallel").glob("*.decode")).read_text(encoding="utf-8")
        self.assertIn("mode=parallel jobs=2", decode)
        self.assertIn("seam_reruns=0", decode)


if __name__ == "__main__":
    unittest.main()
