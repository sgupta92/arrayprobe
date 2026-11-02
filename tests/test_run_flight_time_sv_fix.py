# SPDX-License-Identifier: BSD-3-Clause
"""Default-on corrections through the driver: S4's v3.5 sizeDist call
applies the time-grid (skipped second) and
zero-sample-volume corrections by default, stamps their counts, and turns both
off under ``--protective off``; engine 3.1.4's call and stamp are unchanged.

The sizeDist calls are replaced by recorders, so these tests check what the driver passes and
stamps on synthetic input; the arithmetic itself is tested in ``test_v35_time_sv_fix.py``.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe.driver import run_flight as rf
from arrayprobe_uiops import sizedist as v35_sizedist

#: A floored time vector with one duplicate beside a skipped second (moved) and one
#: back-to-back repeat with no hole beside it (left, counted).
T_IN = np.array([120000.4, 120001.2, 120001.7, 120003.0, 120004.0, 120005.0, 120005.5,
                 120006.0])
TAS = np.full(T_IN.size, 100.0)


class _FakeV35Sizedist:
    fix_time_grid = staticmethod(v35_sizedist.fix_time_grid)
    count_duplicate_seconds = staticmethod(v35_sizedist.count_duplicate_seconds)
    # The driver's HVPS-bin-table check (bin_table_fix_on) resolves the probe's table through
    # the engine's sizedist module; the real functions answer it, since only run() is recorded.
    probe_defaults = staticmethod(v35_sizedist.probe_defaults)
    register_v35_2ds_ladder_fix = staticmethod(v35_sizedist.register_v35_2ds_ladder_fix)

    def __init__(self):
        self.calls = []

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"_zero_sv_seconds": 2}


class _FakeEngine:
    def __init__(self, sd):
        self._sd = sd

    def module(self, name):
        assert name == "sizedist", name
        return self._sd


def _call(engine: str, protective: str):
    fake = _FakeV35Sizedist()
    with mock.patch.object(rf, "ENGINE", engine), \
            mock.patch.object(rf, "PROTECTIVE_MODE", protective), \
            mock.patch.object(rf, "_v35", lambda: _FakeEngine(fake)), \
            mock.patch.object(rf.sizedist, "run") as v314_run:
        stamp = rf._sizedist_call(Path("proc.nc"), Path("sd.nc"), "base160906064017",
                                  T_IN, TAS, None)
    return stamp, fake, v314_run


class TestEngine35(unittest.TestCase):
    @needs_v314_engine
    def test_default_corrects_and_stamps_the_counts(self):
        stamp, fake, v314 = _call("3.5", "auto")
        v314.assert_not_called()
        (args, kwargs), = fake.calls
        self.assertIs(kwargs["zero_sv_nan"], True)
        np.testing.assert_array_equal(
            args[3], [120000, 120001, 120002, 120003, 120004, 120005, 120005, 120006])
        self.assertEqual(stamp, " zero_sv_seconds=2 time_grid_fix=1 time_grid_unresolved=1")

    @needs_v314_engine
    def test_protective_on_is_the_same_as_default(self):
        self.assertEqual(_call("3.5", "on")[0], _call("3.5", "auto")[0])

    @needs_v314_engine
    def test_protective_off_is_the_stock_call(self):
        stamp, fake, _ = _call("3.5", "off")
        (args, kwargs), = fake.calls
        self.assertNotIn("zero_sv_nan", kwargs)
        np.testing.assert_array_equal(args[3], np.floor(T_IN))
        self.assertEqual(stamp, "")


class TestEngine314Unchanged(unittest.TestCase):
    @needs_v314_engine
    def test_no_correction_no_stamp_whatever_the_mode(self):
        for mode in ("auto", "on", "off"):
            with self.subTest(mode=mode):
                stamp, fake, v314 = _call("3.1.4", mode)
                self.assertEqual(stamp, "")
                self.assertEqual(fake.calls, [])
                v314.assert_called_once()
                args, kwargs = v314.call_args
                np.testing.assert_array_equal(args[3], np.floor(T_IN))
                self.assertNotIn("zero_sv_nan", kwargs)

    def test_fix_never_active_on_3_1_4(self):
        with mock.patch.object(rf, "ENGINE", "3.1.4"), \
                mock.patch.object(rf, "PROTECTIVE_MODE", "on"):
            self.assertFalse(rf.v35_time_sv_fix_active())


class TestStampEquivalence(unittest.TestCase):
    def test_counts_do_not_make_a_product_stale(self):
        want = "engine=3.5 preset=X"
        got = want + rf.time_sv_counts_stamp(3, 1, 0)
        self.assertTrue(rf._stamps_equivalent(got, want))

    def test_marker_on_refuses_an_off_input_and_back(self):
        on, off = "engine=3.5 preset=X time_sv_fix=on", "engine=3.5 preset=X time_sv_fix=off"
        self.assertFalse(rf._stamps_equivalent(on + rf.time_sv_counts_stamp(1, 0, 0), off))
        self.assertFalse(rf._stamps_equivalent(off, on))

    def test_absent_marker_reads_as_off_never_on(self):
        legacy = "engine=3.5 preset=X"
        self.assertTrue(rf._stamps_equivalent(legacy, legacy + " time_sv_fix=off"))
        self.assertFalse(rf._stamps_equivalent(legacy, legacy + " time_sv_fix=on"))

    def test_label_carries_marker_on_3_5_only(self):
        for engine, mode, marker in (("3.5", "auto", " time_sv_fix=on"),
                                     ("3.5", "off", " time_sv_fix=off"),
                                     ("3.1.4", "auto", None)):
            with mock.patch.object(rf, "ENGINE", engine), \
                    mock.patch.object(rf, "PROTECTIVE_MODE", mode):
                label = rf.sd_call_label(None)
            if marker is None:
                self.assertNotIn("time_sv_fix=", label)
            else:
                self.assertIn(marker, label)

    def test_strip_leaves_other_tokens(self):
        self.assertEqual(rf._strip_time_sv_counts("a=1 zero_sv_seconds=4 b=2 time_grid_fix=0"),
                         "a=1 b=2")


class TestCountDuplicateSeconds(unittest.TestCase):
    def test_back_to_back_repeat_counted(self):
        self.assertEqual(v35_sizedist.count_duplicate_seconds([1, 2, 2, 2, 3]), 2)

    def test_clean_and_short_inputs(self):
        self.assertEqual(v35_sizedist.count_duplicate_seconds([1, 2, 3]), 0)
        self.assertEqual(v35_sizedist.count_duplicate_seconds([5]), 0)


if __name__ == "__main__":
    unittest.main()
