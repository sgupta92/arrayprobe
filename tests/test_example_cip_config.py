# SPDX-License-Identifier: BSD-3-Clause
"""The shipped CIP example, ``examples/configs/cip_uiops/cip_run.toml``, runs as written.

The example file is copied verbatim into a temporary directory, beside the tracked synthetic
SEA file (``tests/data/sea_raw_synthetic.sea``, CIP buffers only, written by
``make_sea_raw_synthetic.py``) and a synthetic 2D-S airspeed sidecar, and
driven through ``arrayprobe run`` exactly as its README says. Nothing in the file is rewritten,
so an example that stops running fails here rather than in a user's hands.

The airspeed sidecar is a constant 100 m/s, NOT a measurement, written over the fixture's CIP
clock span (13..109 s of day). v3.5 keys the CIP's particle blocks on the probe clock
(``sizeDist.m:758-759``, ``:913-918``), and on this fixture that clock has not been set to UTC,
so a UTC-span series would stop stage 4 at ``:918`` as upstream does
(``tests/test_run_flight_non_spec_probes.py`` pins that death).

In process, no subprocess, about 20 s: safe under a detached suite run.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
EXAMPLE = ROOT / "examples" / "configs" / "cip_uiops" / "cip_run.toml"
FIXTURE = Path(__file__).parent / "data" / "sea_raw_synthetic.sea"
STEM = "2016_09_06_06_40_17"

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
run_flight = None  # bound in setUpModule, the way tests/test_run_from_config_v35.py does


def setUpModule():
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)


from tests import _run_flight_state  # noqa: E402
from tests._repo import needs_enhancements  # noqa: E402

from arrayprobe import cli  # noqa: E402 (after the run_flight/sys.modules setup above)


def _stage_example(root: Path, toml_text: str | None = None) -> Path:
    """The example directory as a user would lay it out: the TOML, and ``data/`` beside it."""
    data = root / "data"
    data.mkdir(parents=True)
    shutil.copyfile(FIXTURE, data / f"{STEM}.sea")
    from arrayprobe.tools.make_tas_file import write_tas_csv
    sod = np.arange(13, 110, dtype=np.int64)
    hhmmss = (sod // 3600) * 10000 + ((sod % 3600) // 60) * 100 + sod % 60
    write_tas_csv(data / "base160906064017.tas.csv", hhmmss, np.full(sod.shape, 100.0),
                  seconds_of_day=sod)
    toml = root / "cip_run.toml"
    if toml_text is None:
        shutil.copyfile(EXAMPLE, toml)
    else:
        toml.write_text(toml_text, encoding="utf-8")
    return toml


def _run(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli.main(["run", *map(str, argv)])
    return rc, buf.getvalue()


@repo_only  # stages examples/, not in the sdist
@needs_enhancements
class TheShippedCipExampleRunsEndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _run_flight_state.preserve(cls, run_flight)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.root = Path(cls._tmp.name)
        cls.toml = _stage_example(cls.root)
        cls.rc, cls.log = _run(cls.toml)
        cls.out = cls.root / "out"

    def test_the_run_succeeds(self):
        self.assertEqual(self.rc, 0, self.log[-3000:])
        self.assertNotIn("FAILED", self.log)

    def test_it_writes_a_v35_size_distribution_for_the_cip(self):
        sd = self.out / f"sd.{STEM}.CIP.nc"
        self.assertTrue(sd.exists(), self.log[-3000:])
        stamp = run_flight.read_stamp(sd)
        self.assertTrue(stamp.startswith("engine=3.5"), stamp)
        self.assertIn("tas_series=probe_hk:base160906064017.tas.csv", stamp)

    def test_the_size_distribution_is_not_empty(self):
        import netCDF4
        with netCDF4.Dataset(self.out / f"sd.{STEM}.CIP.nc") as nc:
            self.assertEqual(nc.variables["count"].shape[1], 19)   # the CIP's 19 bins
            self.assertGreater(float(np.nansum(nc.variables["count"][:])), 0.0)

    def test_the_run_followed_the_probe_the_file_names(self):
        self.assertTrue((self.out / f"proc.{STEM}.CIP.nc").exists(), self.log[-3000:])
        self.assertFalse(list(self.out.glob("proc.*.2DC.nc")))

    def test_the_example_names_no_path_outside_its_own_directory(self):
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertNotIn("arrayprobe-" + "local-data", text)
        self.assertNotIn("DOES NOT RUN", text)


@repo_only  # stages examples/, not in the sdist
class TheExampleRefusesWhatItCannotHonour(unittest.TestCase):

    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.text = EXAMPLE.read_text(encoding="utf-8")

    def test_a_probe_the_preset_does_not_process_is_refused_by_name(self):
        text = self.text.replace('probe = "CIP"', 'probe = "2DC"')
        self.assertNotEqual(text, self.text)
        rc, log = _run(_stage_example(self.root, text))
        self.assertEqual(rc, 2, log[-2000:])
        self.assertIn("[run].probe = '2DC'", log)
        self.assertIn("UND_2016_CIP", log)
        self.assertFalse((self.root / "out").exists())

    def test_an_airspeed_glob_that_matches_nothing_is_refused(self):
        text = self.text.replace('tas_from_probe = ["data/*.tas.csv"]',
                                 'tas_from_probe = ["data/absent*.tas.csv"]')
        self.assertNotEqual(text, self.text)
        rc, log = _run(_stage_example(self.root, text))
        self.assertEqual(rc, 2, log[-2000:])
        self.assertIn("matches no file", log)
        self.assertFalse((self.root / "out").exists())


if __name__ == "__main__":
    unittest.main()
