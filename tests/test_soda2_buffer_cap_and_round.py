# SPDX-License-Identifier: BSD-3-Clause
"""Two SODA-2 sites that survived single-point mutation (pass 5, item 3b, M61, M62).

* ``soda2_processbuffer.pro:339`` -- ``IF max(stopline) gt 10000 THEN return,
  nullbuffer``, strict.  The port's cap (``arrayprobe_soda2/processbuffer_spec.py``,
  ``_MAX_KEPT_STOPLINE``) is reached by no fixture, so raising it to 10001 left the
  suite green.  Driven here with ``spec_read_hk``/``spec_read_frame`` replaced by
  synthetic frames: a buffer whose kept slices end on line exactly 10 000 is kept,
  one ending on 10 001 is the null buffer.  *Derived* from ``:297-304``
  (``stopline = slicecount - 1``) and ``:339``.
* ``soda2_process_2d.pro:137``/``:168`` -- ``round(data.time[good])``: IDL
  ``ROUND`` rounds half away from zero.  The port's ``_idl_round`` does too, and
  ``np.round`` (half to even) disagrees only on exact halves, which no TAS fixture
  holds.  **Measured under GDL** (``print, round(2.5d), round(-2.5d), round(0.5d),
  round(1.5d)`` gives ``3 -3 1 2``, pass 5, item 3b).
"""
from __future__ import annotations

import types
import unittest
from unittest import mock

import numpy as np

from arrayprobe_soda2 import process_2d
from arrayprobe_soda2 import processbuffer_spec as pb


def _run(frame_slices):
    frames = [types.SimpleNamespace(error=0, image=np.zeros((n, 128), dtype=np.uint8),
                                    overload=0, particlecount=k, time=1000 * (k + 1),
                                    timetrunc=0)
              for k, n in enumerate(frame_slices)]
    op = pb.SpecOp(probetype="2DS", subformat=0, probeid="H", dofreject=0,
                   stretchcorrect=0, yres=10.0, res=10.0)
    misc = pb.SpecMisc(nimages=len(frames), hkpointers=[0] * len(frames),
                       imagepointers=list(range(len(frames))), probetas=100.0,
                       aircrafttas=100.0, lastclock=0.0, lastbufftime=-1.0, maxsfm=0.0)
    hk = types.SimpleNamespace(tas=100.0)
    with mock.patch.object(pb, "spec_read_hk", return_value=hk), \
            mock.patch.object(pb, "spec_read_frame", side_effect=frames):
        return pb.process_spec_buffer(None, 5.0, op, misc)


class TheStoplineCap(unittest.TestCase):
    def test_a_buffer_ending_on_line_10000_is_kept(self):
        got = _run([999] * 10 + [10])
        self.assertNotIsInstance(got, pb.NullBuffer)
        self.assertEqual(int(got.stopline.max()), 10000)

    def test_a_buffer_ending_on_line_10001_is_the_null_buffer(self):
        self.assertIsInstance(_run([999] * 10 + [11]), pb.NullBuffer)


class TheIdlRound(unittest.TestCase):
    def test_halves_round_away_from_zero_as_gdl_does(self):
        got = process_2d._idl_round(np.array([2.5, -2.5, 0.5, 1.5]))
        np.testing.assert_array_equal(got, [3.0, -3.0, 1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
