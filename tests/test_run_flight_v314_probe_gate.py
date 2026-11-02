# SPDX-License-Identifier: BSD-3-Clause
"""The batch driver runs the v3.1.4 engine on 2D-S and HVPS only.

The author's rule: "V314 is only to test Oracle's 2DS and HVPS pre-processing". The v3.1.4
engine exists to reproduce the archived ORACLES 2D-S/HVPS products and to validate the port
against them; every other probe is processed with engine 3.5 or SODA-2. The driver once refused
only CIP/PIP under ``--engine 3.1.4`` and let 2DC, 2DP and Fast2DC through.

This module asserts the allow-list itself, and runs ``main`` for every other probe the port knows,
through a declared campaign file, so each is shown to exit 2 with a message naming engine 3.5
before any stage runs. The library port's readers for those probes are untouched: they stay ported
and tested, and only the driver's gate is closed.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests._repo import (
    needs_enhancements,  # noqa: E402
    needs_v314_engine,  # noqa: E402
)

from arrayprobe import constants

_TOOLS = Path(__file__).resolve().parents[1] / "scripts"


def _load():
    """The driver, imported the way the other driver tests import it (``scripts/`` is on the path)."""  # noqa: E501
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    import run_flight
    return run_flight


def _campaign(path: Path, probe: str, name: str) -> Path:
    orientation = "H" if constants.imgproc_config(probe).probetype == 2 else "none"
    path.write_text(
        "[[campaign]]\n"
        f'name = "{name}"\n'
        f'probe = "{probe}"\n'
        f'orientation = "{orientation}"\n'
        'project = "TEST"\n'
        "d_choice = 6\n"
        "sa_method = 0\n"
        "pres_pa = 9e5\n"
        "temp_c = 15.0\n"
        'provenance = "a test, not a campaign"\n',
        encoding="utf-8")
    return path


class TheV314AllowListIsTwoProbes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_the_allow_list_is_exactly_2ds_and_hvps(self):
        self.assertEqual(self.mod.V314_PROBES, frozenset({"2DS", "HVPS"}))

    def test_every_allowed_probe_is_one_the_port_knows(self):
        self.assertLessEqual(self.mod.V314_PROBES, set(constants.IMGPROC_CONFIG))

    def test_there_are_probes_outside_it_so_the_sweep_below_is_not_empty(self):
        others = set(constants.IMGPROC_CONFIG) - self.mod.V314_PROBES
        self.assertGreaterEqual(others, {"CIP", "PIP", "2DC", "2DP", "Fast2DC"})


@needs_enhancements
class EveryOtherProbeIsRefusedUnderV314(unittest.TestCase):
    _saved: Any  # assigned in setUpClass/setUp; see there for the value
    mod: Any  # assigned in setUpClass/setUp; see there for the value

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        cls._saved = cls.mod.ACTIVE
        cls.addClassCleanup(lambda: cls.mod.use_preset(cls._saved.name))

    def _main(self, probe: str, engine: str, tmp: Path) -> tuple[int, str]:
        # A name per probe: main() switches preset only when the name differs from the one in
        # force, so reusing one name would silently keep the first probe.
        name = f"V314_GATE_{probe.upper()}"
        presets = _campaign(tmp / "camps.toml", probe, name)
        raw = tmp / "base160906064017.raw"
        raw.write_bytes(b"")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = self.mod.main([str(raw), "--presets", str(presets),
                                    "--preset", name, "--engine", engine,
                                    *(["--port-validation"] if engine == "3.1.4" else []),
                                    "--stages", "2", "--out", str(tmp / "out")])
        finally:
            self.mod.use_preset(self._saved.name)
            self.mod.PRESETS.pop(name, None)
        return rc, buf.getvalue()

    @needs_v314_engine
    def test_each_probe_outside_the_list_exits_2_naming_engine_35(self):
        others = sorted(set(constants.IMGPROC_CONFIG) - self.mod.V314_PROBES)
        for probe in others:
            with self.subTest(probe=probe), tempfile.TemporaryDirectory() as tmp:
                rc, out = self._main(probe, "3.1.4", Path(tmp))
                self.assertEqual(rc, 2, out[-2000:])
                self.assertIn(f"REFUSED   probe {probe} ", out)
                self.assertIn("--engine 3.5", out)
                self.assertFalse((Path(tmp) / "out").exists()
                                 and any((Path(tmp) / "out").glob("*.nc")))

    @needs_v314_engine
    def test_the_gate_does_not_fire_for_the_two_allowed_probes(self):
        for probe in sorted(self.mod.V314_PROBES):
            with self.subTest(probe=probe), tempfile.TemporaryDirectory() as tmp:
                _, out = self._main(probe, "3.1.4", Path(tmp))
                self.assertNotIn("REFUSED   probe", out)


if __name__ == "__main__":
    unittest.main()
