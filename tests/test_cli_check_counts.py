# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe check-counts`` on the tracked demo-flight fixtures.

Exact closure exits 0 and says the probe's own total is not available; one
planted count cell exits 1 and names the second it sits in.
"""
import contextlib
import io
import os
import shutil
import tempfile
import unittest

import netCDF4
import numpy as np

from arrayprobe import cli

DATA = os.path.join(os.path.dirname(__file__), "data")
SD = os.path.join(DATA, "demo_flight_v35_sd.nc")
PROC = os.path.join(DATA, "demo_flight_v35_proc.nc")


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class TestCheckCounts(unittest.TestCase):

    def test_exact_closure_exits_zero_and_says_not_available(self):
        code, out, _ = _run(["check-counts", SD, PROC])
        self.assertEqual(code, 0, out)
        self.assertIn("closure: exact", out)
        self.assertIn("probe_reported: not available", out)
        # The one particle past the TAS axis is attributed, not silently dropped.
        self.assertIn("outside-tas-axis", out)

    def test_planted_residual_exits_one_and_names_the_second(self):
        tmp = tempfile.mkdtemp()
        try:
            bad = os.path.join(tmp, "sd.nc")
            shutil.copy(SD, bad)
            shutil.copy(os.path.splitext(SD)[0] + ".call", os.path.splitext(bad)[0] + ".call")
            with netCDF4.Dataset(bad, "r+") as ds:
                c = np.ma.filled(ds["count"][:], 0.0)
                c[1, 0] += 1.0
                ds["count"][:] = c
                planted_second = float(ds["time"][1])
            out_json = os.path.join(tmp, "closure.json")
            code, out, _ = _run(["check-counts", bad, PROC, "--out", out_json])
            self.assertEqual(code, 1, out)
            self.assertIn("closure: 1 seconds differ", out)
            self.assertIn(f"{planted_second:g} ", out)
            self.assertIn("residual=+1", out)
            self.assertTrue(os.path.isfile(out_json))
            # The planted cell is within a tolerance of 1, so the same pair closes.
            code, out, _ = _run(["check-counts", bad, PROC, "--tolerance", "1"])
            self.assertEqual(code, 0, out)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
