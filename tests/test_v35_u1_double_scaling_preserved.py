# SPDX-License-Identifier: BSD-3-Clause
"""``imgProc_sm.m:1384,:1387,:1390`` (v3.5) -- three already-micron habit
metrics are multiplied by ``diode_size`` a second time, and the port
reproduces it.

WHAT THIS PROTECTS. ``holroyd_new.m:78,80,81`` (and ``holroyd_new_HVPS.m:74,
76,77``) return ``w_l_p``, ``m_g`` and ``p`` already converted to micrometres
(``x * probe_resolution * 1000``, ``probe_resolution = handles.diodesize`` in
mm). The netCDF writer then multiplies each by ``diode_size`` (mm) once more,
so ``width_length_percentile``, ``maximum_gap`` and ``holroyd_perimeter`` are
written as ``pixels * ds^2 * 1000`` under a ``Units = 'mm'`` attribute: a
factor ``1000*ds`` too large to be mm (10x on a 2D-S, 150x on an HVPS), or a
factor ``ds`` too small to be micrometres. ``arrayprobe_uiops/imgproc.py:1741,
1744,1747`` does the same (``* ds``). A well-meant "fix" on either side --
dropping the writer's multiply, or making ``holroyd_new`` return pixels --
fails this test.

MEASURED, not derived: the numbers below come from running the unmodified
``UIOPS-v3.5/joefinlon-UIOPS-039be82/holroyd_new.m`` under Octave 8.4
(``octave_oracle/run_v35_u1_double_scaling.m``, 2026-09-26) on three
synthetic shapes at both stock diode sizes, then applying the writer's
``* diode_size`` exactly as ``imgProc_sm.m:1384-1390`` does. The port agreed
bit for bit on every value.

"""

from __future__ import annotations

import tempfile
import unittest

import numpy as np
from tests.test_v35_imgproc import DS, _header, _record, _run, _square

from arrayprobe_uiops.habit import holroyd_new
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG, RecordGeometry, measure_record

# (shape, diodesize) -> (habit, w_l_p, m_g, p as holroyd_new returns them,
#                         then the three values the writer puts in the file)
OCTAVE = {
    ("rect", 0.010): ("l", 0.0, 0.0, 1020.0, 0.0, 0.0, 10.200000000000001),
    ("rect", 0.150): ("g", 0.0, 0.0, 15299.999999999998, 0.0, 0.0, 2294.9999999999995),
    ("gapped", 0.010): ("l", 0.0, 0.0, 1540.0, 0.0, 0.0, 15.4),
    ("gapped", 0.150): ("g", 0.0, 0.0, 23099.999999999996, 0.0, 0.0, 3464.9999999999995),
    ("stair", 0.010): ("i", 95.0, 0.0, 1420.0, 0.9500000000000001, 0.0, 14.200000000000001),
    ("stair", 0.150): ("g", 1425.0, 0.0, 21300.0, 213.75, 0.0, 3195.0),
}

# Perimeter-change count of the filled 40 x 20 rectangle in pixel units, as
# holroyd_new.m's calc_stat counts it (measured: p = 1020 um at ds = 0.010).
RECT_P_PIXELS = 102.0


def _rect():
    a = np.full((40, 128), "1")
    a[:, 49:69] = "0"          # MATLAB columns 50:69
    return a


def _gapped():
    b = np.full((40, 128), "1")
    b[0:18, 49:69] = "0"       # MATLAB rows 1:18
    b[22:40, 49:69] = "0"      # MATLAB rows 23:40 -- a 4-slice gap
    b[9:30, 69:75] = "0"       # MATLAB rows 10:30, columns 70:75
    return b


def _stair():
    c = np.full((40, 128), "1")
    for i in range(1, 41):     # MATLAB: C(i, 50:(50+floor(i/2))) = '0'
        c[i - 1, 49:(50 + i // 2)] = "0"
    return c


SHAPES = {"rect": _rect, "gapped": _gapped, "stair": _stair}


def _as_written(value: float, ds: float) -> float:
    """``imgProc_sm.m:1384/1387/1390`` and ``imgproc.py:1741/1744/1747``:
    the habit metric times ``diode_size``, through the same numpy path."""
    return float((np.asarray([value]) * ds)[0])


class TestImgProc1384HabitMetricsAreScaledTwice(unittest.TestCase):

    def test_imgProc_1384_1387_1390_holroyd_new_outputs_match_octave_bit_for_bit(self):
        for (shape, ds), want in OCTAVE.items():
            with self.subTest(shape=shape, ds=ds):
                r = holroyd_new(SHAPES[shape](), probe_resolution=ds,
                                tas_ratio=1.0, bits_per_slice=128)
                self.assertEqual(r.holroyd_habit, want[0])
                # holroyd_new.m:78,80,81 -- already micrometres here.
                self.assertEqual((r.w_l_p, r.m_g, r.p), want[1:4])
                # imgProc_sm.m:1384,:1387,:1390 -- multiplied by diode_size again.
                got = tuple(_as_written(v, ds) for v in (r.w_l_p, r.m_g, r.p))
                self.assertEqual(got, want[4:7])

    def test_imgProc_1390_written_perimeter_is_1000_ds_times_the_mm_value(self):
        # The writer declares Units = 'mm' (imgProc_sm.m:642). The value it
        # writes is pixels * ds * 1000 * ds, i.e. 1000*ds times the mm figure.
        for ds, factor in ((0.010, 10.0), (0.150, 150.0)):
            with self.subTest(ds=ds):
                r = holroyd_new(_rect(), probe_resolution=ds,
                                tas_ratio=1.0, bits_per_slice=128)
                self.assertEqual(r.p, RECT_P_PIXELS * ds * 1000)        # um, :81
                written = _as_written(r.p, ds)                          # :1390
                perimeter_mm = RECT_P_PIXELS * ds
                self.assertAlmostEqual(written / perimeter_mm, factor, places=9)
                self.assertNotAlmostEqual(written, perimeter_mm)
                self.assertNotAlmostEqual(written, perimeter_mm * 1000)

    def test_imgProc_1390_the_writer_itself_multiplies_by_ds_again(self):
        """The same claim read back from a file the v3.5 writer wrote.

        ``_as_written`` above is this module's own arithmetic, so the two tests
        before it stayed green when ``arrayprobe_uiops/imgproc.py``'s
        ``holroyd_perimeter`` line lost its ``* ds`` (measured 2026-09-27). This
        one runs ``imgproc_sm_v35`` on one particle with ``iNewHabit = 1`` and
        compares the file's ``holroyd_perimeter`` with ``holroyd_new``'s
        micrometre value for the same particle: the file must hold ``1000 * ds``
        times the millimetre figure, never the millimetre figure itself.
        """
        particle = _square(0, 60, 6)
        geom = RecordGeometry(diodesize=DS, diodenum=128, tas_ratio=1.0,
                              i_new_habit=1, probename="2DS", i_calc_all_diode_stats=0)
        want = measure_record([particle], geom, STOCK_V35_REJECT_CONFIG)
        p_um = want.particles[0].new_habit.p                              # holroyd_new.m:81
        self.assertGreater(p_um, 0.0)
        with tempfile.TemporaryDirectory() as tmp:
            n, got = _run(tmp, [_record([particle], [1000])], [_header()], iNewHabit=1)
        self.assertEqual(n, 1)
        in_file = float(got["vars"]["holroyd_perimeter"][0])
        self.assertEqual(got["var_attrs"]["holroyd_perimeter"]["Units"], "mm")   # :642
        perimeter_mm = p_um / 1000.0
        self.assertAlmostEqual(in_file, p_um * DS, places=12)               # :1390
        self.assertAlmostEqual(in_file / perimeter_mm, 1000.0 * DS, places=9)
        self.assertNotAlmostEqual(in_file, perimeter_mm)
        self.assertNotAlmostEqual(in_file, p_um)


if __name__ == "__main__":
    unittest.main()
