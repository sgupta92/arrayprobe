# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py --enh-jobs N`` reaches ``pipeline.apply_to_outputs(..., jobs=N)``, default 1.

The driver's ``--jobs`` means worker processes per file; the enhancement pass runs in the parent
after every worker has exited, so its own worker count is a separate option rather than a reuse of
``--jobs``. The pipeline is stubbed here: the parallel loop's equality with the serial one is the
enhancements package's own test (``enhancements_uiops/tests/test_outoffocus.py``).
"""
from __future__ import annotations

import argparse
import ast
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests._driver import driver_source  # noqa: E402

import run_flight  # noqa: E402


class _Stop(Exception):
    pass


def _parsed(*flags: str) -> argparse.Namespace:
    """The namespace main() builds from ``flags``, captured before anything runs."""
    seen: list[argparse.Namespace] = []
    real = argparse.ArgumentParser.parse_args

    def capture(self, args=None, namespace=None):
        ns = real(self, args, namespace)
        if hasattr(ns, "enh_jobs"):
            seen.append(ns)
            raise _Stop
        return ns

    with mock.patch.object(argparse.ArgumentParser, "parse_args", capture):
        try:
            run_flight.main(["raw.2DS", "--preset", "DEMO_2DS_H", "--engine", "3.5",
                             *flags])
        except _Stop:
            pass
    if not seen:
        raise AssertionError("main() never parsed the full command line")
    return seen[0]


class TheOptionParses(unittest.TestCase):

    def test_default_is_one(self):
        self.assertEqual(_parsed().enh_jobs, 1)

    def test_a_count_is_accepted(self):
        self.assertEqual(_parsed("--enh-jobs", "2").enh_jobs, 2)

    def test_it_is_not_the_per_file_jobs(self):
        ns = _parsed("--jobs", "3", "--enh-jobs", "2")
        self.assertEqual((ns.jobs, ns.enh_jobs), (3, 2))


class TheValueReachesThePipeline(unittest.TestCase):

    def _call_with(self, **extra) -> dict:
        calls: list[dict] = []

        def apply_to_outputs(*a, **kw):
            calls.append(kw)
            return []

        pipeline = types.SimpleNamespace(apply_to_outputs=apply_to_outputs,
                                         resolve_for_run=lambda cfg, engine: {})
        registry = types.SimpleNamespace(PROTECTIVE_POLICY={})
        pkg = types.ModuleType("arrayprobe_enhancements")
        pkg.pipeline = pipeline          # type: ignore[attr-defined]
        pkg.registry = registry          # type: ignore[attr-defined]
        modules = {"arrayprobe_enhancements": pkg,
                   "arrayprobe_enhancements.pipeline": pipeline,
                   "arrayprobe_enhancements.registry": registry}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, modules):
            args = argparse.Namespace(config=None, out=tmp, stages="", enhancements=False,
                                      **extra)
            rc = run_flight.apply_enhancements_to_run(args, ["stemA"],
                                                       protective=("some_correction",))
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_the_default_passes_jobs_one(self):
        self.assertEqual(self._call_with(enh_jobs=1)["jobs"], 1)

    def test_a_namespace_without_the_option_passes_jobs_one(self):
        self.assertEqual(self._call_with()["jobs"], 1)

    def test_enh_jobs_two_reaches_the_pipeline_as_jobs_two(self):
        self.assertEqual(self._call_with(enh_jobs=2)["jobs"], 2)


class TheValueIsWrittenNowhere(unittest.TestCase):
    """The driver reads ``enh_jobs`` in exactly one place: the keyword to ``apply_to_outputs``.

    Any second read (a stamp fragment, an attribute, a sidecar) would show here, which is the
    driver-side half of "N is recorded in none of the written files"; the file-side half is
    the enhancements package's own test of the written ``.enh.proc.nc``.
    """

    def test_the_only_read_is_the_pipeline_keyword(self):
        tree = ast.parse(driver_source("run_flight.py").read_text(encoding="utf-8"))
        reads = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and n.value == "enh_jobs"]
        reads += [n for n in ast.walk(tree)
                  if isinstance(n, ast.Attribute) and n.attr == "enh_jobs"]
        self.assertEqual(len(reads), 1, "enh_jobs is read somewhere besides the pipeline call")
        call_kw = [k for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == "apply_to_outputs"
                   for k in n.keywords if k.arg == "jobs"]
        self.assertEqual(len(call_kw), 1)
        inside = [n for n in ast.walk(call_kw[0].value)
                  if isinstance(n, ast.Constant) and n.value == "enh_jobs"]
        self.assertEqual(inside, reads)


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
