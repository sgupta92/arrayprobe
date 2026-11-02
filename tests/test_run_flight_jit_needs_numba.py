# SPDX-License-Identifier: BSD-3-Clause
"""``--jit`` without numba is refused before any stage runs.

Without this guard a ``--jit`` run on an environment lacking numba decoded the whole
flight (hours on a real one) and then raised ``ModuleNotFoundError`` at S3, mid-log.
``run_flight.main`` now checks ``importlib.util.find_spec("numba")`` right after parsing
and returns 2, the code every other refused command line returns. numba's absence is
simulated here by patching ``find_spec``, so the test means the same thing whether or
not numba is installed in the venv running it.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import run_flight  # noqa: E402

#: The v3.1.4 validation engine ships in the development layout only. The --jit guard is
#: engine-independent (it runs right after parsing), so the public tree exercises it on v3.5.
_HAS_V314 = importlib.util.find_spec("arrayprobe.reject") is not None

_REAL_FIND_SPEC = importlib.util.find_spec


def _find_spec(numba_result):
    def fake(name, *args, **kwargs):
        if name == "numba":
            return numba_result
        return _REAL_FIND_SPEC(name, *args, **kwargs)
    return fake


class JitWithoutNumbaIsRefusedAtParsing(unittest.TestCase):
    def setUp(self):
        # main() assigns module globals (ENGINE, PROFILE, JIT, ...); put every one back.
        saved = {k: v for k, v in vars(run_flight).items() if k.isupper()}
        self.addCleanup(vars(run_flight).update, saved)
        self.logged: list[str] = []
        self.addCleanup(setattr, run_flight, "log", run_flight.log)
        run_flight.log = self.logged.append
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name) / "out"
        self.tas = Path(tmp.name) / "aircraft.cdf"
        self.tas.write_bytes(b"x")

    def _engine_args(self) -> list[str]:
        if _HAS_V314:
            return ["--engine", "3.1.4", "--port-validation"]
        return ["--engine", "3.5", "--profile", "stock-v3.5", "--borrowed-combine",
                "--stages", "234c", "--tas-file", str(self.tas)]

    def _main(self, *extra: str) -> int:
        return run_flight.main(
            [*self._engine_args(), "--preset", "ORACLES_2016_2DS_H", "--yes",
             "--out", str(self.out), *extra, "does_not_exist.2DS", "--dry-run"])

    def test_jit_without_numba_exits_2_with_the_install_command(self):
        with mock.patch("importlib.util.find_spec", _find_spec(None)):
            rc = self._main("--jit")
        self.assertEqual(rc, 2)
        text = "\n".join(self.logged)
        self.assertIn("--jit needs numba", text)
        self.assertIn('-m pip install "arrayprobe[jit]"', text)
        # The public tree ships no requirements files, so the advice names the extra.
        self.assertNotIn("requirements-extra.txt", text)
        self.assertFalse(any("PREFLIGHT" in ln for ln in self.logged),
                         "the refusal must come before preflight and every stage")
        self.assertFalse(self.out.exists(), "nothing may be written before the refusal")

    def test_jit_with_numba_present_passes_the_guard(self):
        """The guard names numba only: with it found, the run reaches preflight (and then
        fails there on the missing raw file, a different refusal)."""
        with mock.patch("importlib.util.find_spec", _find_spec(object())):
            rc = self._main("--jit")
        self.assertNotEqual(rc, 2)
        self.assertFalse(any("--jit needs numba" in ln for ln in self.logged))
        self.assertTrue(any("PREFLIGHT" in ln for ln in self.logged))

    def test_without_jit_numba_is_not_consulted(self):
        with mock.patch("importlib.util.find_spec", _find_spec(None)):
            self._main()
        self.assertFalse(any("--jit needs numba" in ln for ln in self.logged))
        self.assertTrue(any("PREFLIGHT" in ln for ln in self.logged))


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
