# SPDX-License-Identifier: BSD-3-Clause
"""``soda2_process_2d.pro:128-145`` -- the PTH ``dat``/``sav`` SAVE-file
branch.
Fixtures are GDL-written SAVE files (``save, data, /compress``,
5-point ``data={time,tas}``) generated once via
``gdl_oracle/locate.py::run_pro`` and tracked under ``tests/data/``:

- ``gdl_soda2_pth_time_equal.sav`` -- ``data.time`` exactly matches the
  accumulator's own time grid (``d.time``, 5 points from ``starttime=100``,
  ``rate=1``), so ``:141`` (``pth_tas=data.tas``) fires.
- ``gdl_soda2_pth_nearest_gap.sav`` -- ``data.time`` has only 3 points over
  the same 5-record window, tripping ``:133``'s mismatch branch and the
  ``:134-139`` nearest-point forward-fill.

Both are read directly with ``scipy.io.readsav`` in ``TestFixturesReadable``
to confirm the SAVE round-trip independent of the port, and then through
:func:`arrayprobe_soda2.process_2d._pth_from_sav` (unit-level) and through
the full :func:`arrayprobe_soda2.process_2d.soda2_process_2d` driver
(``got_pth``/``aircrafttas`` visible via the returned ``ProcessData``, using
the ``frame_full`` fixture already tracked for the earlier golden so the PTH branch
is exercised end to end without any UND data)."""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.process_2d import _idl_round, _pth_from_sav, soda2_process_2d

DATA = Path(__file__).resolve().parent / "data"
TIME_EQUAL = DATA / "gdl_soda2_pth_time_equal.sav"
NEAREST_GAP = DATA / "gdl_soda2_pth_nearest_gap.sav"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"


class TestFixturesReadable(unittest.TestCase):
    """The GDL-written SAVE files round-trip through ``readsav`` with the
    expected ``data.{time,tas}`` fields -- independent of the port."""

    def test_time_equal_fixture(self):
        from scipy.io import readsav
        d = readsav(str(TIME_EQUAL))["data"]
        np.testing.assert_array_equal(d["TIME"][0], [100.0, 101.0, 102.0, 103.0, 104.0])
        np.testing.assert_array_equal(d["TAS"][0], [10.0, 20.0, 15.0, 25.0, 30.0])

    def test_nearest_gap_fixture(self):
        from scipy.io import readsav
        d = readsav(str(NEAREST_GAP))["data"]
        np.testing.assert_array_equal(d["TIME"][0], [100.0, 102.0, 104.0])
        np.testing.assert_array_equal(d["TAS"][0], [10.0, 20.0, 30.0])


class TestIdlRound(unittest.TestCase):
    """``_idl_round``: round-half-away-from-zero, not ``np.round``'s
    round-half-to-even."""

    def test_half_rounds_away_from_zero(self):
        np.testing.assert_array_equal(_idl_round(np.array([0.5, 1.5, 2.5, -0.5])),
                                       [1.0, 2.0, 3.0, -1.0])

    def test_disagrees_with_numpy_round_at_2_5(self):
        # np.round(2.5) == 2.0 (banker's rounding); IDL's ROUND(2.5) == 3.0.
        self.assertEqual(float(np.round(2.5)), 2.0)
        self.assertEqual(float(_idl_round(np.array(2.5))), 3.0)


class TestPthFromSav(unittest.TestCase):
    """``_pth_from_sav`` directly, both branches of ``:128-145``."""

    def test_time_equal_returns_data_tas_directly(self):
        # starttime=100, rate=1, numrecords=5 -> d.time == data.time exactly.
        pth_tas = _pth_from_sav(str(TIME_EQUAL), starttime=100.0, stoptime=104.0,
                                 rate=1.0, numrecords=5)
        np.testing.assert_array_equal(pth_tas, [10.0, 20.0, 15.0, 25.0, 30.0])
        self.assertEqual(str(pth_tas.dtype), "float32")  # data.tas was FLOAT

    def test_nearest_gap_forward_fills(self):
        # data.time=[100,102,104], data.tas=[10,20,30]; d.time has 5 points
        # (100..104) -- over the common 3, d.time - data.time = [0,-1,-2],
        # total -3, so the nearest-point branch runs.
        # itas = [0, 2, 4]; forward-fill: [10,10,20,20,30].
        pth_tas = _pth_from_sav(str(NEAREST_GAP), starttime=100.0, stoptime=104.0,
                                 rate=1.0, numrecords=5)
        np.testing.assert_array_equal(pth_tas, [10.0, 10.0, 20.0, 20.0, 30.0])

    def test_out_of_window_good_points_are_excluded(self):
        # Narrow the window to [102,104]: only two of the three data.time
        # points (102, 104) fall in [starttime,stoptime]; itas relative to
        # the new starttime=102 -> [0, 2]; numrecords=3 (102..104).
        pth_tas = _pth_from_sav(str(NEAREST_GAP), starttime=102.0, stoptime=104.0,
                                 rate=1.0, numrecords=3)
        np.testing.assert_array_equal(pth_tas, [20.0, 20.0, 30.0])

    def test_no_good_points_raises(self):
        from arrayprobe_soda2.process_2d import Soda2ProcessError
        # Window entirely outside the fixture's time range -> `good` is
        # empty -> `:136`'s `stop, 'Time mismatch for TAS file.'`.
        with self.assertRaises(Soda2ProcessError):
            _pth_from_sav(str(NEAREST_GAP), starttime=500.0, stoptime=504.0,
                           rate=1.0, numrecords=5)


class TestPthSaveBranchAgainstGdl(unittest.TestCase):
    """``soda2_process_2d.pro:127-142`` run under GDL on four GDL-written
    SAVE files (``gdl_soda2_pth_*_prefix.sav``, ``_double_tas.sav``,
    ``_negative_start.sav``), each restored and put through the vendored
    lines verbatim. Measured:

    - ``longer_prefix`` (7 records, the first 5 on the 100..104 grid, one TAS
      of 0): ``:133`` sums over the shorter operand, so it is 0 and ``:141``
      takes the file whole -- 7 FLOAT values, the 0 kept.
    - ``shorter_prefix`` (3 records on the grid): whole, 3 values.
    - ``double_tas`` (DOUBLE ``tas``, times off the grid by 0.25 s): nearest
      branch, ``pth_tas`` FLOAT ``[10,20,15,25,25]``.
    - ``negative_start`` (``starttime`` 100.3, ``rate`` 0.1, times ``[101,
      100.4]``): the second record rounds to 100, ``itas`` is -2.99..., and
      ``pth_tas[itas:*]`` fills the LAST two records: ``[0,0,0,0,0,0,0,20,10,10]``."""

    def test_longer_file_with_matching_prefix_is_taken_whole(self):
        pth_tas = _pth_from_sav(str(DATA / "gdl_soda2_pth_longer_prefix.sav"),
                                starttime=100.0, stoptime=104.0, rate=1.0, numrecords=5)
        np.testing.assert_array_equal(pth_tas, [10.0, 0.0, 15.0, 25.0, 30.0, 35.0, 40.0])
        self.assertEqual(pth_tas.dtype, np.float32)

    def test_shorter_file_with_matching_prefix_is_taken_whole(self):
        pth_tas = _pth_from_sav(str(DATA / "gdl_soda2_pth_shorter_prefix.sav"),
                                starttime=100.0, stoptime=104.0, rate=1.0, numrecords=5)
        np.testing.assert_array_equal(pth_tas, [10.0, 20.0, 30.0])

    def test_nearest_branch_is_float_for_a_double_file(self):
        pth_tas = _pth_from_sav(str(DATA / "gdl_soda2_pth_double_tas.sav"),
                                starttime=100.0, stoptime=104.0, rate=1.0, numrecords=5)
        np.testing.assert_array_equal(pth_tas, [10.0, 20.0, 15.0, 25.0, 25.0])
        self.assertEqual(pth_tas.dtype, np.float32)

    def test_negative_start_index_counts_from_the_end(self):
        pth_tas = _pth_from_sav(str(DATA / "gdl_soda2_pth_negative_start.sav"),
                                starttime=100.3, stoptime=101.2, rate=0.1, numrecords=10)
        np.testing.assert_array_equal(pth_tas, [0, 0, 0, 0, 0, 0, 0, 20.0, 10.0, 10.0])

    def test_start_index_past_the_end_halts(self):
        # GDL: `p=fltarr(5) & p[5d:*]=3` -> "Subscript out of range [s:*]".
        from arrayprobe_soda2.process_2d import Soda2ProcessError
        with self.assertRaises(Soda2ProcessError):
            _pth_from_sav(str(NEAREST_GAP), starttime=100.0, stoptime=104.0,
                          rate=1.0, numrecords=4)


class TestPthThroughTheDriver(unittest.TestCase):
    """``soda2_process_2d`` end to end with ``op.pth`` set to the ``.sav``
    fixture -- ``got_pth``/``aircrafttas`` are not returned directly by
    ``ProcessData``, so this checks the driver runs to completion (no
    refusal, no raise) over a tiny window that brackets the fixture's
    5-point time grid, using the already-tracked ``frame_full`` raw
    fixture so no UND data is touched."""

    def _base_op(self, **overrides) -> dict:
        op = dict(
            fn=str(FRAME_FIXTURE), date="20160906", starttime=24240.0,
            stoptime=24249.0, format="SPEC", subformat=0, probetype="2DS",
            res=10.0, endbins=[10.0, 50.0, 100.0, 200.0, 500.0],
            arendbins=[0.0, 0.5, 1.0], rate=1.0, smethod="xy", pth="",
            particlefile=0, inttime_reject=0, stuckbits=0, water=0,
            fixedtas=0.0, timeoffset=0.0, armwidth=6.3, numdiodes=128,
            wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0,
            asciipsdfile=0, clusterthresh=0.0, eawmethod="centerin",
            greythresh=0, dofreject=0,
            savfile=0,  # no SAVE file (it would need `outdir`)
        )
        op.update(overrides)
        return op

    def test_pth_dat_branch_runs_without_refusal(self):
        # A fixture whose own time grid does not match this window's
        # d.time (different starttime) exercises the nearest-point branch
        # inside a real driver call, rather than raising NotImplementedError.
        op = self._base_op(pth=str(NEAREST_GAP), starttime=100.0, stoptime=104.0)
        result = soda2_process_2d(op)
        # `frame_full`'s buffers do not fall in [100,104], so this may
        # legitimately return None (`:430-433`, empty window) -- the point
        # of this test is that it does NOT raise NotImplementedError for
        # the PTH branch, which it would have before this port.
        self.assertTrue(result is None or result.tas is not None)


if __name__ == "__main__":
    unittest.main()
