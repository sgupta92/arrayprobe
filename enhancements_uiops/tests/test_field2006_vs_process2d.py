# SPDX-License-Identifier: BSD-3-Clause
"""field2006_shatter against compiled NCAR Process2D, value for value.

The golden file is written by the ``field2006-oracle`` job of
``.github/workflows/process2d-build.yml``: it compiles process2d.cpp's fit,
bins, histogram and cutoff lines verbatim (extracted by line range at a pinned
aircraft_oap commit) into ``field2006_harness.cpp``
and runs them on ``data/field2006_queues.csv``. Save the job's artifact file as
``data/field2006_process2d_golden.csv``; until then this module skips.

Tolerances. Histogram counts: exact (float32 bin endpoints are built the same
way on both sides). Fit parameters and the residual: ``rtol=1e-9`` — both sides
compute in double, but the C ``exp`` (glibc) and numpy's ``exp`` may differ by an
ulp, and up to 50 damped Gauss-Newton steps can amplify that well above 1e-16
while staying far below any physical significance. ``pcutoff`` and ``corrfac``
are float32 stores: ``rtol=1e-6`` (a few float32 ulps). NaN and inf must match
as NaN and inf.

OPEN, NAMED EXPECTED DIFFERENCE (unsettled 2026-10-05): NCAR's compiled fit gives NaN on
``initial_queue`` (``itq = {1}``: 399 zeros in
bin 0, one 1-s entry in bin 34, ysum = 400 >= 10, so the fit runs from
a1 = 1/x[0] ~ 7.9e6 and is not refused by the :236 low-count branch). This
module's transcription is said to return finite values there. Not yet decided
whether that is a transcription error (fix to match NaN) or a libm/ordering
difference; the golden file is not in the repository, so nothing here has been
measured. ``test_fit_cutoff_and_corrfac`` will report it on ``initial_queue``
once the golden lands; settle it then, not by loosening ``_close``.
"""

from __future__ import annotations

import hashlib
import math
import pathlib
import unittest

import numpy as np

from arrayprobe_enhancements import field2006_shatter as f6

DATA = pathlib.Path(__file__).with_name("data")
QUEUES = DATA / "field2006_queues.csv"
GOLDEN = DATA / "field2006_process2d_golden.csv"
WORKFLOW = ".github/workflows/process2d-build.yml (job field2006-oracle)"

RTOL_FIT = 1e-9
RTOL_F32 = 1e-6


def _queues() -> dict[str, np.ndarray]:
    out = {}
    for line in QUEUES.read_text(encoding="ascii").splitlines():
        if line:
            qid, *vals = line.split(",")
            out[qid] = np.array([float(v) for v in vals])
    return out


def _queues_sha256() -> str:
    # Hash with LF endings, as the Linux runner sees the file.
    return hashlib.sha256(QUEUES.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _close(got: float, want: float, rtol: float) -> bool:
    if math.isnan(want) or math.isinf(want):
        return (math.isnan(got) and math.isnan(want)) or got == want
    return math.isclose(got, want, rel_tol=rtol, abs_tol=0.0)


@unittest.skipUnless(GOLDEN.exists(),
                     f"{GOLDEN.name} is not distributed with the package; this test runs in the "
                     "development repository")
class TestAgainstCompiledProcess2D(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        lines = GOLDEN.read_text(encoding="ascii").splitlines()
        cls.header = lines[0]
        cols = lines[1].split(",")
        cls.rows = {}
        for line in lines[2:]:
            if line:
                rec = dict(zip(cols, line.split(","), strict=True))
                cls.rows[rec["queue_id"]] = rec
        cls.queues = _queues()

    def test_golden_was_made_from_this_fixture(self) -> None:
        self.assertIn(f"queues_sha256={_queues_sha256()}", self.header)

    def test_every_queue_is_in_the_golden(self) -> None:
        self.assertEqual(set(self.rows), set(self.queues))

    def test_histogram_is_exact(self) -> None:
        for qid, q in self.queues.items():
            with self.subTest(queue=qid):
                want = [int(self.rows[qid][f"c{i}"]) for i in range(f6.N_INTERARRIVAL_BINS)]
                self.assertEqual(f6.histogram(q).tolist(), want)

    def test_fit_cutoff_and_corrfac(self) -> None:
        for qid, q in self.queues.items():
            row = self.rows[qid]
            a = np.zeros(3)
            ret = f6.dpoisson_fit(f6.bin_midpoints(),
                                  f6.histogram(q).astype(np.float32), a)
            pc = f6.cutoff(float(a[1]))
            cf = f6.correction_factor(pc, float(a[1]))
            for name, got, want, rtol in [
                    ("ret", ret, float(row["ret"]), RTOL_FIT),
                    ("a0", a[0], float(row["a0"]), RTOL_FIT),
                    ("a1", a[1], float(row["a1"]), RTOL_FIT),
                    ("a2", a[2], float(row["a2"]), RTOL_FIT),
                    ("pcutoff", pc, float(row["pcutoff"]), RTOL_F32),
                    ("corrfac", cf, float(row["corrfac"]), RTOL_F32)]:
                with self.subTest(queue=qid, value=name):
                    self.assertTrue(_close(float(got), want, rtol),
                                    f"{qid} {name}: python {got!r}, process2d {want!r}")


class TestFixture(unittest.TestCase):

    def test_fixture_is_what_its_generator_writes(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "make_field2006_queues", DATA / "make_field2006_queues.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        want = {qid: q for qid, q in mod.queues()}
        got = _queues()
        self.assertEqual(list(got), list(want))
        for qid in want:
            self.assertTrue(np.array_equal(got[qid], want[qid]), qid)


if __name__ == "__main__":
    unittest.main()
