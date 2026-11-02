# SPDX-License-Identifier: BSD-3-Clause
"""``MetFolder`` reads ORACLES P-3 merge files (``mrg1_P3_<date>_R<rev>.nc``) as well as ARM's.

The CIP labelling page showed no air temperature because the folder reader indexed only
ARM's ``enaaafmergedF1`` names; the ORACLES merge carries ``Static_Air_Temp`` on
``Start_UTC`` (seconds of the day), checked against its epoch ``time`` axis."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.triage_context import MetFolder


def _write(path: Path, date: str, start_utc, temp, shift_s: float = 0.0):
    midnight = dt.datetime.strptime(date, "%Y%m%d").replace(tzinfo=dt.UTC).timestamp()
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", len(start_utc))
        su = ds.createVariable("Start_UTC", "f8", ("time",))
        su.units = "seconds"
        su[:] = start_utc
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 1970-01-01 00:00:00.0"
        tv[:] = np.asarray(start_utc, float) + midnight + shift_s
        t = ds.createVariable("Static_Air_Temp", "f8", ("time",))
        t.units = "degrees Celcius"
        t[:] = temp


class OraclesMergeTemperature(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_the_temperature_at_a_record_second(self):
        _write(self.dir / "mrg1_P3_20160906_R36.nc", "20160906",
               [36000, 36001, 36002], [12.5, -9999.0, 11.0])
        met = MetFolder(self.dir)
        self.assertEqual(len(met), 1)
        self.assertEqual(met.temperature_at(20160906, 100000), (12.5, "mrg1_P3_20160906_R36.nc"))
        self.assertIsNone(met.temperature_at(20160906, 100001))  # missing value
        self.assertEqual(met.temperature_at(20160906, 100002)[0], 11.0)
        self.assertIsNone(met.temperature_at(20160907, 100000))  # no file of that date

    def test_a_file_whose_epoch_disagrees_with_its_name_reads_as_none(self):
        _write(self.dir / "mrg1_P3_20160906_R36.nc", "20160906", [36000], [12.5],
               shift_s=86400.0)
        self.assertIsNone(MetFolder(self.dir).temperature_at(20160906, 100000))


if __name__ == "__main__":
    unittest.main()
