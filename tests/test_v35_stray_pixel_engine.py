# SPDX-License-Identifier: BSD-3-Clause
"""Step 2 of the stray-pixel correction: wired into the v3.5 engine.

Off (the library default)
is bit-identical to a run without the keyword; on adds the two per-particle variables and the
``arrayprobe_stray_pixel`` global, and changes only corrected particles.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

from tests.test_v35_imgproc_probetypes import _INPUTS, CREATION_TIME, SOFTWARE

from arrayprobe_uiops import stray_pixel
from arrayprobe_uiops.imgproc import STRAY_PIXEL_VARIABLES, imgproc_sm_v35
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG, RecordGeometry, measure_record


def _run(out: Path, **kw) -> int:
    return imgproc_sm_v35(
        str(_INPUTS["2DC"]), str(out), "2DC", 1, 1, "TEST",
        iRectEllipse=0, iCalcAllDiodeStats=1, iQC=0, iNewHabit=0,
        reject_config=STOCK_V35_REJECT_CONFIG, tas_time=None, tas=None,
        software=SOFTWARE, creation_time=CREATION_TIME, **kw)


def _read(path: Path):
    with netCDF4.Dataset(str(path)) as ds:
        ds.set_auto_maskandscale(False)
        return ({n: np.array(v[:]) for n, v in ds.variables.items()},
                {k: str(ds.getncattr(k)) for k in ds.ncattrs()})


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestEngineWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.n_plain = _run(tmp / "plain.nc")
        cls.n_off = _run(tmp / "off.nc", stray_pixel_fix=False)
        cls.n_on = _run(tmp / "on.nc", stray_pixel_fix=True)
        cls.plain, cls.g_plain = _read(tmp / "plain.nc")
        cls.off, cls.g_off = _read(tmp / "off.nc")
        cls.on, cls.g_on = _read(tmp / "on.nc")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_off_is_bit_identical_to_no_keyword(self):
        self.assertGreater(self.n_plain, 0)
        self.assertEqual(self.n_plain, self.n_off)
        self.assertEqual(list(self.plain), list(self.off))
        for name, a in self.plain.items():
            with self.subTest(variable=name):
                self.assertTrue(np.array_equal(a, self.off[name],
                                               equal_nan=a.dtype.kind in "fc"))
        self.assertEqual(self.g_plain, self.g_off)
        self.assertNotIn("arrayprobe_stray_pixel", self.g_off)

    def test_on_adds_the_two_variables_and_the_global(self):
        self.assertEqual(self.n_on, self.n_plain)
        names = [v[0] for v in STRAY_PIXEL_VARIABLES]
        self.assertEqual(list(self.on), list(self.plain) + names)
        self.assertEqual(self.g_on["arrayprobe_stray_pixel"], stray_pixel.STAMP_ON)
        self.assertEqual(stray_pixel.STAMP_ON, "on:g8,n2,m9")

    def test_on_changes_only_corrected_particles(self):
        removed = self.on["image_stray_pixels_removed"]
        unc = self.on["image_diam_minR_uncorrected"]
        untouched = removed == 0
        self.assertTrue(np.isnan(unc[untouched]).all())
        # Uncorrected size is what the off run wrote, for every particle it applies to.
        np.testing.assert_array_equal(unc[~untouched],
                                      self.plain["image_diam_minR"][~untouched])
        for name in ("image_diam_minR", "image_area", "image_auto_reject", "Time"):
            with self.subTest(variable=name):
                a = self.plain[name]
                self.assertTrue(np.array_equal(a[untouched], self.on[name][untouched],
                                               equal_nan=a.dtype.kind in "fc"))


def _drop(n=40, d=12, r0=5, c0=5):
    """ASCII image (49 lit, 48 shadowed) with a d-diode disc at (r0, c0)."""
    yy, xx = np.mgrid[0:n, 0:64]
    cy, cx = r0 + d / 2 - 0.5, c0 + d / 2 - 0.5
    shadow = (yy - cy) ** 2 + (xx - cx) ** 2 <= (d / 2) ** 2
    return np.where(shadow, 48, 49).astype(np.uint8)


class TestCorrectEngineImage(unittest.TestCase):
    geom = RecordGeometry(diodesize=0.01, diodenum=64, tas_ratio=1.0, i_new_habit=0,
                          probename="2DS", i_calc_all_diode_stats=0)

    def _measure(self, c):
        return measure_record([c], self.geom, STOCK_V35_REJECT_CONFIG).particles[0]

    def test_drop_plus_one_stray_is_resized_to_the_drop_and_retested(self):
        drop = _drop()
        dirty = drop.copy()
        dirty[35, 60] = 48
        fixed, removed = stray_pixel.correct_engine_image(dirty)
        self.assertEqual(removed, 1)
        self.assertTrue(np.array_equal(fixed, drop))
        clean_p, dirty_p, fixed_p = (self._measure(x) for x in (drop, dirty, fixed))
        self.assertEqual(fixed_p.minR, clean_p.minR)
        self.assertGreater(dirty_p.minR, 2 * clean_p.minR)
        self.assertEqual(fixed_p.auto_reject, clean_p.auto_reject)

    def test_two_real_drops_and_a_clean_drop_are_untouched(self):
        two = _drop()
        two[np.where(_drop(r0=25, c0=40) == 48)] = 48
        for c in (two, _drop()):
            out, removed = stray_pixel.correct_engine_image(c)
            self.assertEqual(removed, 0)
            self.assertIs(out, c)


if __name__ == "__main__":
    unittest.main()
