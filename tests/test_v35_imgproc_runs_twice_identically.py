# SPDX-License-Identifier: BSD-3-Clause
"""The v3.5 image-processing stage, run twice in one process, writes the same arrays.

The static half of this check is ``test_engines_read_no_clock_or_global_rng.py``: no
engine module reads global random state, and every clock read is classified. This file
is the measured half: ``imgproc_sm_v35`` is driven end to end on the tracked 2DC
fixture of ``test_v35_imgproc_probetypes.py`` twice, with the same arguments, and every
variable of the two outputs must be ``np.array_equal`` (NaN in the same places), every
variable attribute equal, and every global attribute equal -- ``Creation Time`` too,
because the same ``creation_time`` is passed both times. A hidden dependence on state
left by the first run (a module-level cache, a generator advanced by the first call)
would show here as a difference in the second.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover - netCDF4 is a core dependency
    netCDF4 = None

from tests.test_v35_imgproc_probetypes import _INPUTS, CREATION_TIME, SOFTWARE

from arrayprobe_uiops.imgproc import imgproc_sm_v35
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG


def _run(out: Path) -> int:
    return imgproc_sm_v35(
        str(_INPUTS["2DC"]), str(out), "2DC", 1, 1, "TEST",
        iRectEllipse=0, iCalcAllDiodeStats=1, iQC=0, iNewHabit=0,
        reject_config=STOCK_V35_REJECT_CONFIG, tas_time=None, tas=None,
        software=SOFTWARE, creation_time=CREATION_TIME,
    )


def _read(path: Path):
    with netCDF4.Dataset(str(path)) as ds:
        ds.set_auto_maskandscale(False)
        variables = {name: (np.array(v[:]),
                            {k: str(v.getncattr(k)) for k in v.ncattrs()})
                     for name, v in ds.variables.items()}
        globals_ = {k: str(ds.getncattr(k)) for k in ds.ncattrs()}
    return variables, globals_


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TheV35ImgprocRunsTwiceIdentically(unittest.TestCase):
    def test_two_runs_write_identical_arrays_and_attributes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            n1 = _run(tmp / "first.nc")
            n2 = _run(tmp / "second.nc")
            vars1, glob1 = _read(tmp / "first.nc")
            vars2, glob2 = _read(tmp / "second.nc")
        self.assertGreater(n1, 0, "the fixture produced no particles: nothing compared")
        self.assertEqual(n1, n2)
        self.assertEqual(list(vars1), list(vars2))
        self.assertGreaterEqual(len(vars1), 10)
        for name, (a1, att1) in vars1.items():
            a2, att2 = vars2[name]
            with self.subTest(variable=name):
                self.assertEqual(a1.dtype, a2.dtype)
                nan_ok = a1.dtype.kind in "fc"
                self.assertTrue(np.array_equal(a1, a2, equal_nan=nan_ok))
                self.assertEqual(att1, att2)
        self.assertEqual(glob1, glob2)


if __name__ == "__main__":
    unittest.main()
