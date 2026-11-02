# SPDX-License-Identifier: BSD-3-Clause
"""The split SODA-2 loop overlaps its serial parts with the pool, and still writes serial bytes.

``run_parallel_loop`` hands chunk *j* to a worker as soon as the carry-in sweep has recorded
its start state, rather than after the whole sweep, and replays each chunk's bookkeeping as it
arrives in buffer order, flushing to ``soda2_particlesort`` mid-run exactly where the serial
loop does. ``tests/test_soda2_parallel.py`` proves byte identity through real pools (behind
``ARRAYPROBE_SLOW``). This module runs the same driver in process with an executor that
defers each chunk until its result is asked for, so it can observe the order of events and
compare with the serial run without a pool:

* every chunk is submitted before the sweep has walked the whole range, the first before it
  has walked any buffer;
* with ``num2process`` small enough that the replay flushes many times mid-run, every
  ``ProcessData`` array and the ``.pbp.csv`` equal the serial run's (the CSV's
  ``Date Processed`` line excepted, for the reason ``tests/test_soda2_parallel.py`` measures).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe_soda2 import process_2d
from arrayprobe_soda2 import process_2d_parallel as par
from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d

HERE = Path(__file__).resolve().parent
CIP_FIXTURE = HERE / "data" / "soda2_sea_cip_fixture.sea"
sys.path.insert(0, str(HERE))


def _cip_op(outdir: Path) -> dict:
    from test_soda2_cip_driver import _cip_op as base
    op = base([33000])
    op["outdir"] = str(outdir.resolve()) + "/"
    op["particlefile"] = 1
    op["ncdfparticlefile"] = 0
    op["savfile"] = 0
    return op


class _Deferred:
    def __init__(self, fn, arg) -> None:
        self.fn, self.arg = fn, arg

    def result(self):
        return self.fn(self.arg)


class _InlineExecutor:
    """Stands in for ``ProcessPoolExecutor``: runs the initializer here, and runs each
    submitted chunk only when its result is asked for, recording how far the sweep had got
    at each submission."""

    def __init__(self, events: list, front_calls: list, *, max_workers, initializer,
                 initargs, mp_context=None) -> None:
        # mp_context: the loop forces the "spawn" start method (a Linux-only fork
        # defect); running inline, there is no process to start.
        del max_workers, mp_context
        initializer(*initargs)
        self.events, self.front_calls = events, front_calls

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def submit(self, fn, arg):
        self.events.append(("submit", arg[0], self.front_calls[0]))
        return _Deferred(fn, arg)


#: ProcessData fields that cannot match between two runs: the processing time, and ``house``,
#: which ``tests/test_soda2_parallel.py`` excludes for its truncated repr.
EXCLUDED = {"date_processed", "house"}


@unittest.skipUnless(CIP_FIXTURE.is_file(), f"missing fixture {CIP_FIXTURE}")
class TheSplitOverlapsAndStaysByteIdentical(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="soda2overlap_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(self._reset_worker_globals)

    @staticmethod
    def _reset_worker_globals() -> None:
        par._CTX = None
        par._MISC_TEMPLATE = None

    def _run(self, tag: str, *, jobs: int, chunks: int = 0, num2process: int):
        """One in-process run into ``live/``, moved to ``tag/`` afterwards so both runs
        write through the same path. Returns the ProcessData, the events and the flushes."""
        live = self.tmp / "live"
        live.mkdir()
        events: list = []
        front_calls = [0]
        flushes = [0]
        real_front, real_flush = process_2d._front_half, process_2d._flush

        def counting_front(*a, **k):
            front_calls[0] += 1
            return real_front(*a, **k)

        def counting_flush(*a, **k):
            flushes[0] += 1
            return real_flush(*a, **k)

        def executor(**kw):
            return _InlineExecutor(events, front_calls, **kw)

        with mock.patch.object(process_2d, "_front_half", counting_front), \
                mock.patch.object(process_2d, "_flush", counting_flush), \
                mock.patch.object(par, "ProcessPoolExecutor", executor):
            d = soda2_process_2d(_cip_op(live), jobs=jobs, chunks=chunks,
                                 num2process=num2process)
        shutil.move(str(live), str(self.tmp / tag))
        return d, events, flushes[0]

    def _assert_same(self, a: ProcessData, b: ProcessData, what: str) -> None:
        for f in fields(ProcessData):
            if f.name in EXCLUDED:
                continue
            va, vb = getattr(a, f.name), getattr(b, f.name)
            with self.subTest(what=what, field=f.name):
                if isinstance(va, np.ndarray):
                    self.assertTrue(np.array_equal(va, vb, equal_nan=va.dtype.kind == "f"),
                                    f"{f.name} differs")
                elif f.name not in ("op",) and not f.name.endswith("_path"):
                    self.assertEqual(repr(va), repr(vb))

    def _csv_lines(self, tag: str) -> list[bytes]:
        [path] = list((self.tmp / tag).glob("*.pbp.csv"))
        return [ln for ln in path.read_bytes().splitlines(keepends=True)
                if not ln.startswith(b"Date Processed")]

    def test_every_chunk_is_submitted_while_the_sweep_is_still_walking(self):
        _, events, _ = self._run("p", jobs=2, chunks=4, num2process=process_2d.NUM2PROCESS)
        submits = [e for e in events if e[0] == "submit"]
        self.assertGreaterEqual(len(submits), 2)
        self.assertEqual(submits[0][2], 0, "chunk 0 waited for the sweep to walk a buffer")
        los = [lo for _, lo, _ in submits]
        self.assertEqual(los, sorted(los))
        # The sweep had walked exactly up to each chunk's first buffer when it was submitted.
        first = los[0]
        self.assertEqual([calls for _, _, calls in submits], [lo - first for lo in los])

    #: Thresholds measured on this fixture (serial run, flushes counted including the driver's
    #: final one): 505 flushes 6 times, 510 five, 540 twice; 520 leaves ``istop < 0`` at the
    #: end, so the driver returns None there (the preserved early ``return`` at `:576`), which
    #: the split must reproduce as well.
    THRESHOLDS = (505, 510, 520, 540)

    def test_mid_run_flushes_leave_every_byte_where_serial_puts_it(self):
        flush_counts = {}
        for num2process in self.THRESHOLDS:
            with self.subTest(num2process=num2process):
                ser, _, ser_flushes = self._run(f"s{num2process}", jobs=1,
                                                num2process=num2process)
                spl, _, spl_flushes = self._run(f"p{num2process}", jobs=3, chunks=5,
                                                num2process=num2process)
                flush_counts[num2process] = ser_flushes
                self.assertEqual(spl_flushes, ser_flushes)
                if ser is None:
                    self.assertIsNone(spl)
                    continue
                self.assertIsInstance(spl, ProcessData)
                self._assert_same(ser, spl, f"num2process={num2process}")
                self.assertEqual(self._csv_lines(f"p{num2process}"),
                                 self._csv_lines(f"s{num2process}"))
        # Not vacuous: at 505 the replay flushes on several buffers mid-run.
        self.assertGreater(flush_counts[505], 3)


if __name__ == "__main__":
    unittest.main()
