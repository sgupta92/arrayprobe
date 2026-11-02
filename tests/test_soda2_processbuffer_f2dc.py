# SPDX-License-Identifier: BSD-3-Clause
"""soda2_processbuffer.pro:28-78 (Fast-2DC), hand-derived Cases A-F."""
import unittest

import numpy as np

from arrayprobe_soda2.processbuffer_f2dc import F2dcMisc, F2dcOp, process_f2dc_buffer
from arrayprobe_soda2.processbuffer_spec import NullBuffer

BLANK = 0xFFFFFFFFFFFFFFFF
SYNC = 0xAAAA000000000000
M64 = 0xFFFFFFFFFFFFFFFF


def _case_a():
    img = np.full(512, BLANK, dtype=np.uint64)
    img[0] = SYNC | 1000
    img[1:4] = ~(0x7 << 30) & M64
    img[10] = SYNC | 0x100000000000 | 2000
    img[11:13] = ~(0x1 << 20) & M64
    img[20] = SYNC | 3000
    return img


class CaseA(unittest.TestCase):
    def test_v2(self):
        img = _case_a()
        misc = F2dcMisc()
        p = process_f2dc_buffer(img, 50.0, 100.0, F2dcOp("F2DC_v2"), misc)
        self.assertEqual(p.num_images, 3)
        np.testing.assert_array_equal(p.rawtime, [1000, 2000, 3000])
        np.testing.assert_array_equal(p.dof, [1, 0, 1])
        clk = 1e8 / 3.0
        np.testing.assert_array_equal(p.time_sfm, np.array([1000, 2000, 3000]) / clk)
        self.assertEqual(p.reftime, 3000 / clk)
        np.testing.assert_array_equal(p.startline, [0, 1, 11, 21])
        np.testing.assert_array_equal(p.stopline, [0, 9, 19])
        np.testing.assert_array_equal(p.particle_count, [0, 0, 0])
        np.testing.assert_array_equal(p.inttime, [0, 0, 0])
        self.assertEqual(misc.f2d_remainder_slices, 492)
        self.assertEqual(int(misc.f2d_remainder[0]), BLANK)
        self.assertEqual(misc.lastbufftime, 50.0)
        # dec2bin64: column 0 is bit 63, so bits 30-32 are columns 31-33.
        self.assertEqual(list(np.flatnonzero(p.bitimage[1])), [31, 32, 33])
        self.assertEqual(list(np.flatnonzero(p.bitimage[11])), [43])
        self.assertEqual(p.bitimage[0].sum(), 0)  # blanked sync row
        self.assertEqual(p.bitimage[20].sum(), 0)

    def test_v1(self):
        p = process_f2dc_buffer(_case_a(), 50.0, 100.0, F2dcOp("F2DC"), F2dcMisc())
        np.testing.assert_array_equal(p.rawtime, [1000, 2000, 3000])
        np.testing.assert_array_equal(p.dof, [1, 1, 1])
        np.testing.assert_array_equal(p.time_sfm, np.array([1000, 2000, 3000]) / 12.0e6)


class CaseB(unittest.TestCase):
    def test_carry_over(self):
        misc = F2dcMisc()
        op = F2dcOp("F2DC_v2")
        process_f2dc_buffer(_case_a(), 50.0, 100.0, op, misc)
        b2 = np.full(512, BLANK, dtype=np.uint64)
        b2[0:5] = ~(0x3 << 40) & M64
        b2[5] = SYNC | 4000
        b2[30] = SYNC | 5000
        b2[100] = SYNC | 6000
        p = process_f2dc_buffer(b2, 51.0, 100.0, op, misc)
        np.testing.assert_array_equal(p.rawtime, [4000, 5000, 6000])
        np.testing.assert_array_equal(p.startline, [0, 498, 523, 593])
        np.testing.assert_array_equal(p.stopline, [496, 521, 591])
        self.assertEqual(p.bitimage.shape, (1004, 64))
        self.assertEqual(misc.f2d_remainder_slices, 1004 - 592)


class CaseC(unittest.TestCase):
    def test_two_syncs_null_and_state_cleared(self):
        misc = F2dcMisc()
        process_f2dc_buffer(_case_a(), 50.0, 100.0, F2dcOp("F2DC_v2"), misc)
        self.assertEqual(misc.f2d_remainder_slices, 492)
        b = np.full(512, BLANK, dtype=np.uint64)
        b[3] = SYNC | 1
        b[9] = SYNC | 2
        p = process_f2dc_buffer(b, 51.0, 100.0, F2dcOp("F2DC_v2"), misc)
        self.assertIsInstance(p, NullBuffer)
        self.assertEqual(p.rejectbuffer, 1)
        self.assertEqual(misc.f2d_remainder_slices, 0)

    def test_no_sync(self):
        misc = F2dcMisc()
        p = process_f2dc_buffer(np.full(512, BLANK, dtype=np.uint64), 1.0, 1.0,
                                F2dcOp("F2DC"), misc)
        self.assertIsInstance(p, NullBuffer)


class CaseD(unittest.TestCase):
    def test_sync_at_511(self):
        img = _case_a()
        img[511] = SYNC | 4000
        misc = F2dcMisc()
        process_f2dc_buffer(img, 1.0, 1.0, F2dcOp("F2DC_v2"), misc)
        self.assertEqual(misc.f2d_remainder_slices, 1)
        self.assertEqual(int(misc.f2d_remainder[0]), BLANK)


class CaseE(unittest.TestCase):
    def test_dof_passthrough(self):
        p = process_f2dc_buffer(_case_a(), 1.0, 1.0, F2dcOp("F2DC_v2"), F2dcMisc())
        self.assertEqual(p.dof.dtype, np.uint8)
        np.testing.assert_array_equal(p.dof, [1, 0, 1])


class CaseF(unittest.TestCase):
    def test_remainder_overflow_raises(self):
        misc = F2dcMisc(f2d_remainder_slices=500)
        b = np.full(512, BLANK, dtype=np.uint64)
        misc.f2d_remainder[:500] = BLANK
        misc.f2d_remainder[0:3] = [SYNC | 1, SYNC | 2, SYNC | 3]
        with self.assertRaisesRegex(IndexError, ":73"):
            process_f2dc_buffer(b, 1.0, 1.0, F2dcOp("F2DC_v2"), misc)


if __name__ == "__main__":
    unittest.main()
