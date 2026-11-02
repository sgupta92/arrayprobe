# SPDX-License-Identifier: BSD-3-Clause
"""Reprocess-from-PBP (``soda2_process_2d, op, fn_pbp=...``,
``soda2_process_2d.pro:30-35``, ``:584-617``; ``spec_newtime.pro``;
``soda2_restore_pbp.pro``).

These tests pin the IDL behaviour read from the source, a round trip on the tracked
SPEC frame fixture, and ``spec_newtime`` against a GDL 8.4 golden on one-, two- and
three-buffer inputs (``gdl_oracle/run_soda2_spec_newtime_single_buffer_bank.py``).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe_soda2 import reprocess_pbp as R
from arrayprobe_soda2.process_2d import Soda2ProcessError, soda2_process_2d

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_soda2_process_2d_pbp import _frame_full_op  # noqa: E402

_PER_SECOND = ("spec1d", "spec2d", "count_accepted", "count_rejected", "count_missed",
               "conc1d", "activetime", "intspec_all", "intspec_accepted", "tas",
               "probetas", "corr_fac", "missed_hist", "zdspec")


def _direct_run(tmp: str):
    return soda2_process_2d(_frame_full_op(tmp, particlefile=0, ncdfparticlefile=1))


class ReprocessOnTheFrameFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.direct = _direct_run(self.tmp)
        assert self.direct is not None and self.direct.pbp_ncdf_path is not None
        self.fn = self.direct.pbp_ncdf_path

    def tearDown(self) -> None:
        import gc
        gc.collect()
        self._tmp.cleanup()

    def test_missing_pbp_file_stops(self) -> None:
        # `:32` -- `stop, 'PBP file not found.'`
        with self.assertRaisesRegex(Soda2ProcessError, "PBP file not found"):
            soda2_process_2d(_frame_full_op(self.tmp), fn_pbp=self.fn + ".absent")

    def test_spec_newtime_5_stops_on_a_truncated_rawtime(self) -> None:
        # The frame fixture's rawtime peaks at 2,621,481 (< 2^31), so
        # `spec_newtime.pro:7` stops before any particle is sorted.
        with self.assertRaisesRegex(R.SpecNewtimeStop, "full rawtime"):
            soda2_process_2d(_frame_full_op(self.tmp, ncdfparticlefile=1), fn_pbp=self.fn)

    def test_round_trip_matches_the_direct_run_when_time_is_unchanged(self) -> None:
        # With the particle time held at buffertime (what the direct SPEC
        # path uses, `soda2_particlesort.pro:28`), the reprocess branch sees
        # the same particles in the same seconds; on this fixture every
        # per-second output is equal, inttime's float32 storage included.
        with mock.patch.object(R, "spec_newtime",
                               lambda raw, buf, tas, yres: np.asarray(buf, float).copy()):
            again = soda2_process_2d(_frame_full_op(self.tmp, ncdfparticlefile=1),
                                     fn_pbp=self.fn)
        assert again is not None
        for name in _PER_SECOND:
            with self.subTest(name=name):
                np.testing.assert_array_equal(getattr(again, name), getattr(self.direct, name))

    def test_reprocess_writes_no_particle_files(self) -> None:
        # `:33-34` -- both particle-file switches are forced off.
        with mock.patch.object(R, "spec_newtime",
                               lambda raw, buf, tas, yres: np.asarray(buf, float).copy()):
            again = soda2_process_2d(_frame_full_op(self.tmp, particlefile=1, ncdfparticlefile=1),
                                     fn_pbp=self.fn)
        assert again is not None
        self.assertIsNone(again.pbp_ncdf_path)
        self.assertIsNone(again.pbp_csv_path)

    def test_599_inclusive_loop_halts_when_n_is_a_multiple_of_num2process(self) -> None:
        # 13 particles; num2process=13 makes `:599`'s second pass read at
        # offset 13, past the end.
        with mock.patch.object(R, "spec_newtime",
                               lambda raw, buf, tas, yres: np.asarray(buf, float).copy()):
            with self.assertRaises(R.PbpRestoreError):
                soda2_process_2d(_frame_full_op(self.tmp, ncdfparticlefile=1),
                                 fn_pbp=self.fn, num2process=13)

    def test_blocks_of_num2process_give_the_same_answer(self) -> None:
        with mock.patch.object(R, "spec_newtime",
                               lambda raw, buf, tas, yres: np.asarray(buf, float).copy()):
            whole = soda2_process_2d(_frame_full_op(self.tmp, ncdfparticlefile=1), fn_pbp=self.fn)
            split = soda2_process_2d(_frame_full_op(self.tmp, ncdfparticlefile=1),
                                     fn_pbp=self.fn, num2process=5)
        assert whole is not None and split is not None
        np.testing.assert_array_equal(whole.spec2d, split.spec2d)


class SpecNewtime(unittest.TestCase):
    def test_no_rollover_adds_2_32_to_the_last_particle(self) -> None:
        # `:13-14` -- `where` finds nothing, returns -1, and `dcounter[-1]`
        # is the last element.
        raw = np.array([2.0**31, 2.0**31 + 100, 2.0**31 + 200])
        buf = np.array([10.0, 10.0, 11.0])
        tas = np.full(3, 100.0, dtype=np.float32)
        t = R.spec_newtime(raw, buf, tas, 10.0)
        freq = float(np.float32(10.0) / (np.float32(1e6) * np.float32(100.0)))
        step_last = (100.0 + 2.0**32) * freq
        self.assertAlmostEqual(t[2] - t[1], step_last, places=6)

    def test_truncated_rawtime_stops(self) -> None:
        with self.assertRaises(R.SpecNewtimeStop):
            R.spec_newtime(np.array([1.0, 2.0]), np.array([0.0, 1.0]),
                           np.ones(2, np.float32), 10.0)


class SpecNewtimeAgainstGdl(unittest.TestCase):
    """``spec_newtime`` on the cases GDL 8.4 ran (golden
    ``tests/data/gdl_soda2_spec_newtime_single_buffer_golden.json``): one buffer
    halts at `:10`; with no positive buffer step, `:34`'s scalar subscript wraps
    ``buffertime`` to ``n-2`` while ``elaptime``'s array subscript clips to 0."""

    @classmethod
    def setUpClass(cls) -> None:
        import json
        golden = (Path(__file__).resolve().parent / "data"
                  / "gdl_soda2_spec_newtime_single_buffer_golden.json")
        cls.cases = json.loads(golden.read_text(encoding="utf-8"))["spec_newtime"]

    @staticmethod
    def _buffertime(text: str) -> np.ndarray:
        return np.array([float(v.strip().rstrip("d")) for v in text.strip("[]").split(",")])

    def _run(self, case: dict) -> np.ndarray:
        return R.spec_newtime(np.array(case["rawtime"]), self._buffertime(case["buffertime_idl"]),
                              np.full(case["n"], case["probetas"], np.float32), case["yres"])

    def test_spec_newtime_10_one_buffer_halts_as_gdl_does(self) -> None:
        case = self.cases["n1_equal"]
        self.assertEqual(case["halted_at"], "spec_newtime.pro:10")
        with self.assertRaises(R.SpecNewtimeSubscriptError):
            self._run(case)

    def test_spec_newtime_34_matches_gdl_on_every_ran_case(self) -> None:
        for name, case in self.cases.items():
            if "newtime" not in case:
                continue
            with self.subTest(name):
                got = self._run(case)
                np.testing.assert_allclose(got, case["newtime"], rtol=0, atol=1e-9)

    def test_spec_newtime_34_scalar_wraps_where_the_array_clips(self) -> None:
        # The case that told the two subscripts apart: the old port clipped both
        # and came out 1 s high.
        got = self._run(self.cases["n3_decreasing"])
        self.assertEqual(got[0], 4999.0)


if __name__ == "__main__":
    unittest.main()
