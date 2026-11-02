# SPDX-License-Identifier: BSD-3-Clause
"""``read_binary_PMS`` on a real NCAR RAF ``.2d`` file against its Octave golden.

The golden (``tests/data/us2_pms_rf05_octave_golden.json``, built by
``octave_oracle/run_us2_pms_rf05_bank.py``) holds the per-variable SHA-256 of what the unmodified
``read_binary_PMS.m`` wrote under Octave for ACE-1 1995 rf05 (9 ``C1`` + 5 ``P1`` records), and
records that the port agreed on every variable when it was built. The raw file is not tracked;
this test reads it from the path in ``ARRAYPROBE_RF05_2D`` and skips when that is unset or absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe.readers import pms

GOLDEN = Path(__file__).resolve().parent / "data" / "us2_pms_rf05_octave_golden.json"

# _release_fixture_guard: us2_pms_rf05_octave_golden.json is excluded from the release
if not GOLDEN.exists():
    raise unittest.SkipTest(
        "checks one real research flight's probe record, which this release does not distribute")
_RAW_ENV = os.environ.get("ARRAYPROBE_RF05_2D", "")
RAW = Path(_RAW_ENV) if _RAW_ENV else None


class TheGoldenItself(unittest.TestCase):
    """Runs without the raw file: the golden records a full Octave-port agreement."""

    def setUp(self):
        self.g = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_every_variable_agreed_when_the_golden_was_built(self):
        rows = [v for f in self.g["octave_vs_port"].values() for v in f.values()]
        self.assertEqual(len(rows), 30)
        self.assertEqual(set(rows), {"equal"})

    def test_counts_are_nine_2dc_and_five_2dp(self):
        self.assertEqual(self.g["port_counts"], [9, 0, 0, 5])

    def test_the_golden_names_no_path(self):
        text = GOLDEN.read_text(encoding="utf-8")
        self.assertNotIn(":/", text)
        self.assertNotIn("Users", text)


@unittest.skipUnless(
    RAW is not None and RAW.is_file(),
    "set ARRAYPROBE_RF05_2D to the path of the ACE-1 flight 5 raw 2D file to run this class (not "
    "distributed)",
)
class ThePortReproducesTheOctaveGolden(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import netCDF4

        cls.g = json.loads(GOLDEN.read_text(encoding="utf-8"))
        raw = RAW.read_bytes()
        cls.mismatch = hashlib.sha256(raw).hexdigest() != cls.g["raw_sha256"]
        cls.tmp = None
        if cls.mismatch:  # skipped per test in setUp, so the skips are counted
            return
        cls.tmp = tempfile.TemporaryDirectory()
        base = os.path.join(cls.tmp.name, "rf05")
        cls.counts = pms.read_binary_PMS(str(RAW), base)
        cls.got = {}
        for suffix in cls.g["outputs"]:
            with netCDF4.Dataset(base + suffix) as ds:
                ds.set_auto_maskandscale(False)
                dims = {n: len(d) for n, d in ds.dimensions.items()}
                vars_ = {}
                for n, v in ds.variables.items():
                    a = np.ascontiguousarray(v[...])
                    vars_[n] = {"dtype": a.dtype.str, "shape": list(a.shape),
                                "sha256": hashlib.sha256(a.tobytes()).hexdigest()}
            cls.got[suffix] = {"dimensions": dims, "variables": vars_}

    @classmethod
    def tearDownClass(cls):
        if cls.tmp is not None:
            cls.tmp.cleanup()

    def setUp(self):
        if self.mismatch:
            self.skipTest("the raw file differs from the one the stored result was built on")

    def test_counts(self):
        self.assertEqual(list(self.counts), self.g["port_counts"])

    def test_every_variable_matches_octave(self):
        for suffix, want in self.g["outputs"].items():
            with self.subTest(file=suffix):
                self.assertEqual(self.got[suffix], want)


if __name__ == "__main__":
    unittest.main()
