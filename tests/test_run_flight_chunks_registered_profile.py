# SPDX-License-Identifier: BSD-3-Clause
"""``--chunks`` with a profile reached through ``register_profile()``.

THE DEFECT.  A ``--chunks > 1`` worker is ``run_flight.py --_run-chunk``, re-exec'd as a fresh
``python`` subprocess (``stage3``'s ``cmd_base``).  A fresh interpreter's own
``arrayprobe.profiles.PROFILES`` starts with only the four shipped profiles
(:data:`arrayprobe.profiles.SHIPPED`).  A profile a fork added with ``register_profile()`` --
exactly what a fork is told to do -- is not there, so ``PROFILES[profile_name]``
(the ``--_run-chunk`` branch's own lookup) raised a bare ``KeyError`` in every worker, about two
seconds in, before a single record was written.  ``[fidelity].profile_module`` (``config.py``)
already exists to carry the registration into a fresh process by naming a module whose *import*
repeats it, and ``run_flight.py`` already threads ``PROFILE_MODULE`` into ``cmd_base`` and the
``--_run-chunk`` branch re-imports it -- but nothing checked that ``profile_module`` was actually
*set* before handing ``chunks`` fresh subprocesses a name none of them could resolve.  That gap is
exactly the shape ``config.py`` itself cannot close: ``load_config``'s ``fid["profile"] not in
PROFILES`` check (``config.py:337``) passes for a profile some out-of-band code already registered
in the *parent* process, whatever ``profile_module`` says or does not say, because by the time that
line runs the parent's own ``PROFILES`` already has the name. Only the moment ``stage3`` is about
to spawn fresh subprocesses knows the gap is there.

THE FIX (``run_flight.py``, ``stage3``'s ``chunks > 1`` branch).  Refuse, naming
``profile_module``, before any worker is spawned -- the same "fail before spawning" shape the
neighbouring v3.5 ``ChunkingNotEquivalent`` check just above it already uses, chosen over silently
guessing a module to import because a subprocess ``KeyError`` two seconds in is not a diagnosable
error, and there is no module name to carry automatically when
``profile_module`` was never given in the first place -- "carry automatically" already existed for
the case where ``profile_module`` *is* set (this file's second class proves it still works); what
was missing is the refusal for the case where it is not.

WHY THIS TEST LAUNCHES REAL SUBPROCESSES, BOTH LEVELS.  An in-process test -- import
``run_flight``, call ``register_profile()`` and ``stage3()``/``main()`` directly in this test's own
interpreter -- cannot see the defect: this process's own ``arrayprobe.profiles.PROFILES`` already
holds the registered name by the time anything checks it, which is exactly how the bug went
unnoticed in the lane that hit it (a registered profile "worked with --jobs 1" in-process and only
failed once real ``--chunks`` subprocesses were involved). Only a genuinely fresh interpreter --
one that never ran the registration -- can fail to resolve the name, so both the outer
``run_flight.py`` invocation and its ``--chunks`` workers are real ``python run_flight.py ...``
processes here, not mocked or called in-process.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
RUN_FLIGHT = TOOLS / "run_flight.py"

sys.path.insert(0, str(TOOLS))
from tests._repo import needs_v314_engine  # noqa: E402

import make_demo_flight  # noqa: E402

#: Written to <root>/registered_test_profile.py -- the [fidelity].profile_module this TOML
#: points at, mirroring config.py's own [fidelity] docstring example almost verbatim. Registers a
#: profile that is field-identical to ORACLES_PRODUCTION (only the name differs), so nothing about
#: S2/S3 behaviour is under test here except whether the NAME resolves in a fresh process.
_PROFILE_MODULE_SOURCE = (
    "import dataclasses\n"
    "from arrayprobe.profiles import ORACLES_PRODUCTION, register_profile\n"
    'register_profile(dataclasses.replace(ORACLES_PRODUCTION, name="FORK_TEST_PROFILE"))\n'
)

#: Written to <root>/preregistered_wrapper.py -- the entry point for the NEGATIVE test. It
#: registers the profile DIRECTLY (no profile_module involved at all), the way the original report
#: actually hit the bug: a fork's own launcher script calls register_profile() itself, in-process,
#: before ever touching run_flight.py. That makes the profile resolve fine in THIS (parent)
#: process -- config.py's "unknown profile" check (config.py:337) sees PROFILES already holding
#: the name and passes -- while [fidelity].profile_module stays unset because nothing in this
#: picture ever needed to name a module for THIS process to work. The gap is entirely in what a
#: freshly re-exec'd --chunks WORKER can see, which a bare `python run_flight.py ...` parent (this
#: file's first draft) cannot reach: that shape trips config.py's own earlier, blunter refusal
#: instead, before stage3 is ever called. runpy.run_path re-executes run_flight.py's own
#: __main__ block in THIS already-registered process, so sys.argv (this wrapper's own) is what
#: run_flight.main() reads, exactly as if `python run_flight.py <those args>` had been typed --
#: except the profile is already registered here, and only here.
_WRAPPER_SOURCE = (
    "import dataclasses\n"
    "import runpy\n"
    "from arrayprobe.profiles import ORACLES_PRODUCTION, register_profile\n"
    'register_profile(dataclasses.replace(ORACLES_PRODUCTION, name="FORK_TEST_PROFILE"))\n'
    f'runpy.run_path(r"{RUN_FLIGHT}", run_name="__main__")\n'
)

_PROFILE_NAME = "FORK_TEST_PROFILE"
_MODULE_NAME = "registered_test_profile_module"


def _root_with_flight() -> Path:
    root = Path(tempfile.mkdtemp())
    raw = root / "base160101000000.2DS"
    make_demo_flight.build_demo_flight(raw)  # default n_seconds=5, plenty for --chunks 2
    (root / f"{_MODULE_NAME}.py").write_text(_PROFILE_MODULE_SOURCE, encoding="utf-8")
    (root / "preregistered_wrapper.py").write_text(_WRAPPER_SOURCE, encoding="utf-8")
    return root, raw


def _toml(root: Path, *, with_profile_module: bool) -> Path:
    lines = ["[fidelity]", f'profile = "{_PROFILE_NAME}"']
    if with_profile_module:
        lines.append(f'profile_module = "{_MODULE_NAME}"')
    p = root / "run.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _cli_args(root: Path, raw: Path, toml: Path) -> list[str]:
    return [str(raw), "--config", str(toml), "--engine", "3.1.4", "--port-validation",
            "--preset", "DEMO_2DS_H", "--stages", "23",
            "--chunks", "2", "--out", str(root / "_decoded"), "--yes"]


def _run_via_profile_module(root: Path, raw: Path, toml: Path) -> subprocess.CompletedProcess:
    """The positive case's entry point: a plain ``python run_flight.py ...`` real subprocess,
    resolving the registered profile purely through ``[fidelity].profile_module`` -- both this
    process and its ``--chunks`` workers need ``root`` on ``PYTHONPATH`` to import it by name,
    and a worker gets it because ``stage3`` spawns workers with ``subprocess.Popen(cmd, ...)`` and
    no ``env=`` override (run_flight.py's own two ``Popen`` call sites), so whatever environment
    this outer process has is what a worker gets too."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(RUN_FLIGHT), *_cli_args(root, raw, toml)],
        cwd=root, env=env, capture_output=True, text=True, timeout=180,
    )


def _run_via_preregistered_wrapper(root: Path, raw: Path,
                                   toml: Path) -> subprocess.CompletedProcess:
    """The negative case's entry point -- see ``_WRAPPER_SOURCE`` for why a bare
    ``python run_flight.py`` parent cannot exercise the gap this test is about."""
    wrapper = root / "preregistered_wrapper.py"
    return subprocess.run(
        [sys.executable, str(wrapper), *_cli_args(root, raw, toml)],
        cwd=root, capture_output=True, text=True, timeout=180,
    )


class ChunksRefuseWithoutProfileModule(unittest.TestCase):
    """The negative case: the PARENT resolves ``FORK_TEST_PROFILE`` fine (pre-registered directly,
    the way the original report did it) but names no ``profile_module``, so nothing could be carried
    to a ``--chunks`` worker even in principle -- this must refuse before any worker starts, not
    fail inside N of them with a bare ``KeyError``."""

    def setUp(self):
        self.root, self.raw = _root_with_flight()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    @needs_v314_engine
    def test_refuses_naming_profile_module_before_any_worker_starts(self):
        toml = _toml(self.root, with_profile_module=False)
        proc = _run_via_preregistered_wrapper(self.root, self.raw, toml)
        out = proc.stdout + proc.stderr

        self.assertNotEqual(proc.returncode, 0, out)
        self.assertIn("profile_module", out, out)
        self.assertIn(_PROFILE_NAME, out, out)
        self.assertIn("ProfileNotReachableInChunkWorkers", out, out)
        # The old, undiagnosable failure this replaces must not be what actually got RAISED
        # instead -- "KeyError:" (Python's own "ExceptionType: message" traceback formatting) is
        # what an uncaught KeyError looks like; our own message legitimately says the word
        # "KeyError" in prose (explaining what it prevents), so that substring alone would be a
        # false positive here -- the colon is what distinguishes "mentioned" from "raised".
        self.assertNotIn("KeyError:", out, out)

    def test_no_chunk_worker_ever_ran(self):
        """Pins "before any worker starts", not merely "ends in failure somehow": no chunk file,
        no per-chunk log, nothing on disk that only a spawned worker would have created."""
        toml = _toml(self.root, with_profile_module=False)
        _run_via_preregistered_wrapper(self.root, self.raw, toml)
        decoded = self.root / "_decoded"
        leftover = list(decoded.glob("*.chunk*")) if decoded.exists() else []
        self.assertEqual(leftover, [], f"a chunk worker ran despite the refusal: {leftover}")


class ChunksSucceedWithProfileModuleSet(unittest.TestCase):
    """The positive case, proving the already-existing "carry automatically" path still works:
    PROFILE_MODULE correctly threaded through cmd_base and re-imported by --_run-chunk (the
    OTHER disposition) must not have been disturbed by adding the refusal above."""

    def setUp(self):
        self.root, self.raw = _root_with_flight()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    @needs_v314_engine
    def test_real_chunk_workers_resolve_the_registered_profile_and_finish(self):
        toml = _toml(self.root, with_profile_module=True)
        proc = _run_via_profile_module(self.root, self.raw, toml)
        out = proc.stdout + proc.stderr

        self.assertEqual(proc.returncode, 0, out)
        self.assertNotIn("KeyError:", out, out)
        self.assertNotIn("ProfileNotReachableInChunkWorkers", out, out)
        self.assertIn("S3 start  base160101000000.H.cdf (5 records, 2 chunks)", out, out)
        self.assertIn("S3 done", out, out)
        self.assertIn("ALL DONE", out, out)
        # Each worker's own completion line (`log(f"S3 chunk {n} done: ...")`, in --_run-chunk)
        # goes to ITS OWN log file (stage3 opens each with stdout=log_f), which a SUCCESSFUL merge
        # then deletes (:1960) -- so it cannot be read after the fact. The proof that each FRESH
        # interpreter individually resolved PROFILES["FORK_TEST_PROFILE"], rather than merely the
        # parent, is structural instead: stage3 refuses to merge unless every chunk_path.done
        # exists AND its claimed count matches the chunk file's own `time` dimension (:1926-1940,
        # "two sides from two places") -- a worker whose --_run-chunk branch died on
        # PROFILES[profile_name] (a KeyError, before any record is written) leaves no .done file
        # and no chunk file, which is exactly what that check exists to catch. "S3 done" plus
        # rc==0 is reachable only past that check, for BOTH of the two real worker subprocesses
        # this run spawned.
        decoded = self.root / "_decoded"
        leftover_chunks = list(decoded.glob("*.chunk*"))
        self.assertEqual(leftover_chunks, [],
                         "a successful run should have merged and cleaned up every chunk "
                         f"artifact: {leftover_chunks}")


if __name__ == "__main__":
    unittest.main()
