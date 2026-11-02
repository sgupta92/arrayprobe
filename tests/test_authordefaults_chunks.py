# SPDX-License-Identifier: BSD-3-Clause
"""No silent defaults in the port's entry points, the chunked-run step: ``--chunks`` with an
authordefaults file. The chunk guard admits the file, the worker re-loads it from an
``authordefaults=<path>`` tail token and refuses one whose hash no longer matches the parent's
profile name.
"""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from tests import _run_flight_state
from tests._profile_registry_guard import module_hooks

from arrayprobe.authordefaults import expected_filename, load_authordefaults, resolve_profile
from arrayprobe.driver import run_flight
from arrayprobe.profiles import is_v35_flavoured

SRC = Path(run_flight.__file__).resolve().parents[1]

_BODY = '''
[fidelity]
base_profile = "{base}"

[thresholds.max_edge_img_ar]
value = 4
citation = "test fixture, author-defaults chunk path"
'''


def _write(d: Path, base: str) -> Path:
    data = _BODY.format(base=base).encode("utf-8")
    p = d / expected_filename(data)
    p.write_bytes(data)
    return p


# resolve_profile() registers an authordefaults-<hash> profile; the shared helper removes
# it after the module (it leaked three into test_profile_registry_guard in one process).
setUpModule, tearDownModule = module_hooks()


class WorkerRefusesADriftedFile(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)

    def test_hash_mismatch_exits_naming_both(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), "STOCK_V314")
            ad = load_authordefaults(p)
            wrong = "authordefaults-0000000000000000"
            argv = ["--_run-chunk", str(Path(d) / "none.2DS"), "2DS", "ORACLES", wrong, "", "",
                    "30", str(Path(d) / "out.nc"), "1", "10", "engine=3.5",
                    f"authordefaults={p}"]
            with self.assertRaises(SystemExit) as ctx:
                run_flight.main(argv)
            msg = str(ctx.exception)
            self.assertIn(ad.hash, msg)
            self.assertIn(wrong, msg)


class EngineFlavour(unittest.TestCase):
    def test_v35_base_is_v35_flavoured_and_production_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            v35 = resolve_profile(load_authordefaults(_write(Path(d), "STOCK_V35")))
            prod = resolve_profile(load_authordefaults(_write(Path(d), "ORACLES_PRODUCTION")))
        self.assertTrue(is_v35_flavoured(v35))
        self.assertFalse(is_v35_flavoured(prod))


class NoDefaultCreepsBack(unittest.TestCase):
    """AST guard: both new carriers default to None, and the chunk guard names all three."""

    def test_defaults_are_none_and_guard_names_three(self):
        cfg = ast.parse((SRC / "config.py").read_text(encoding="utf-8"))
        rf_text = (SRC / "driver" / "run_flight.py").read_text(encoding="utf-8")
        rf = ast.parse(rf_text)
        run_cfg = next(n for n in ast.walk(cfg)
                       if isinstance(n, ast.ClassDef) and n.name == "RunConfig")
        fields = {n.target.id: n.value for n in run_cfg.body
                  if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        self.assertIsInstance(fields["authordefaults_path"], ast.Constant)
        self.assertIsNone(fields["authordefaults_path"].value)
        top = {n.target.id: n.value for n in rf.body
               if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        self.assertIsNone(top["AUTHORDEFAULTS_PATH"].value)
        guards = [ast.unparse(n.test) for n in ast.walk(rf) if isinstance(n, ast.If)
                  and any(isinstance(s, ast.Raise) and "ProfileNotReachableInChunkWorkers"
                          in ast.unparse(s) for s in n.body)]
        self.assertEqual(len(guards), 1, guards)
        for name in ("SHIPPED", "PROFILE_MODULE", "AUTHORDEFAULTS_PATH"):
            self.assertIn(name, guards[0])


if __name__ == "__main__":
    unittest.main()
