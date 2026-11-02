# SPDX-License-Identifier: BSD-3-Clause
"""The driver resolves an aircraft file's true-airspeed variable, and says which.

Why this exists. On 2026-09-21 the author ruled that every non-ORACLES dataset
is processed on the v3.5 engine. ARM ACE-ENA was launched under ``stock-v3.5``
and died with ``KeyError: 'TAS'`` **after a 754-second decode** -- because
``stock-v3.5`` is the profile that requires an aircraft file at all, and ARM's
merged file calls true airspeed ``true_airspeed`` on a ``time`` axis rather
than UIOOPS's ``TAS``/``Time``.

The gap appeared exactly when the engine ruling made it reachable, which is the
useful part: a capability nobody had exercised was not missing, it was
*unmet*, and the failure surfaced at the end of the expensive stage rather than
in preflight.

Two properties are tested here, and the second is the one that keeps this
honest:

* a file using either convention is read; and
* a file using **neither** raises, naming what it tried and what the file
  actually carries -- it does not fall back on a guess. ``_TAS_VARIANTS`` grows
  only by someone reading a real file, and this test is what stops it growing
  by hunch.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

PORT = Path(__file__).resolve().parents[1]
for p in (str(PORT), str(PORT / "scripts"), str(PORT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import netCDF4 as nc  # noqa: E402

import run_flight  # noqa: E402


def _write_aircraft(path: Path, tas_name: str, time_name: str, n: int = 50):
    """A minimal aircraft file using the given variable names. The ARM pair carries what the
    real ARM AAF file carries (read 2026-09-23 off enaaafmergedF1.c1.20170706.082313.nc): a
    ``base_time`` (that day's midnight, Unix seconds) and ``units = "m/s"``."""
    with nc.Dataset(path, "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("time", n)
        t = d.createVariable(time_name, "f8", ("time",))
        v = d.createVariable(tas_name, "f8", ("time",))
        t[:] = np.arange(n, dtype=float)
        v[:] = np.linspace(90.0, 110.0, n)
        if tas_name == "true_airspeed":
            v.units = "m/s"
            d.createVariable("base_time", "i4")[...] = 1499299200


class EitherConventionIsRead(unittest.TestCase):
    def setUp(self):
        self._saved = run_flight.TAS_FILE
        self.tmp = Path(__file__).resolve().parent / "_tas_variant_tmp"
        self.tmp.mkdir(exist_ok=True)

    def tearDown(self):
        run_flight.TAS_FILE = self._saved
        for f in self.tmp.glob("*.nc"):
            f.unlink()
        self.tmp.rmdir()

    def _read(self, tas_name, time_name):
        path = self.tmp / f"{tas_name}_{time_name}.nc"
        _write_aircraft(path, tas_name, time_name)
        run_flight.TAS_FILE = str(path)
        return run_flight._aircraft_series()

    def test_the_uiops_convention_is_read(self):
        """``TAS``/``Time`` -- what ``imgProc_sm.m`` expects. Must stay first."""
        tas_time, tas = self._read("TAS", "Time")
        self.assertEqual(tas.shape, (50,))
        self.assertAlmostEqual(float(tas[0]), 90.0)
        self.assertAlmostEqual(float(tas_time[-1]), 49.0)

    def test_the_arm_convention_is_read(self):
        """``true_airspeed``/``time`` -- ARM AAF merged files.

        This is the case that failed in production, after the decode.
        """
        tas_time, tas = self._read("true_airspeed", "time")
        self.assertEqual(tas.shape, (50,))
        self.assertAlmostEqual(float(tas[0]), 90.0)
        # 49 s after base_time (midnight) is 00:00:49 -> HHMMSS 49; 50 samples, 000000..000049.
        self.assertAlmostEqual(float(tas_time[-1]), 49.0)

    def test_an_unknown_convention_raises_and_names_what_it_tried(self):
        """The half that stops `_TAS_VARIANTS` growing by guesswork.

        A file whose airspeed variable matches nothing must fail loudly and
        usefully, never silently pick a plausible-looking variable. Guessing
        here would put an unverified airspeed into every particle's sizing.
        """
        with self.assertRaises(KeyError) as caught:
            self._read("airspeed_true", "seconds")
        message = str(caught.exception)
        self.assertIn("TAS/Time", message)
        self.assertIn("true_airspeed/time", message)
        self.assertIn("do not guess", message)


class TheVariantTableIsHonest(unittest.TestCase):
    def test_the_uiops_pair_is_first(self):
        """Order is not cosmetic: the first entry is the one read silently.

        Every other variant logs that it was used, because a file that is not
        in UIOOPS's own convention is a fact the run's reader should see.
        """
        self.assertEqual(run_flight._TAS_VARIANTS[0][:2], ("TAS", "Time"))

    def test_every_variant_records_what_uses_it(self):
        for tas_name, time_name, why in run_flight._TAS_VARIANTS:
            with self.subTest(variant=tas_name):
                self.assertTrue(
                    why and len(why) > 15,
                    f"{tas_name}/{time_name} carries no note saying which real "
                    f"file forced it; a variant without a source is a guess")


if __name__ == "__main__":
    unittest.main()
