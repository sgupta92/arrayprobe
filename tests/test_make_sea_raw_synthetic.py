# SPDX-License-Identifier: BSD-3-Clause
"""The synthetic SEA raw generator decodes through the shipped SEA reader.

``tests/data/make_sea_raw_synthetic.py`` writes a clean raw SEA input for the
tests that need one; this checks that it is deterministic, that the tracked
file is what the generator writes, and that ``read_binary_SEA`` decodes every
CIP buffer with no dropped record and no 2DC record.
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.readers import sea

_DATA = Path(__file__).resolve().parent / "data"
_GEN = _DATA / "make_sea_raw_synthetic.py"


def _load():
    spec = importlib.util.spec_from_file_location("make_sea_raw_synthetic", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SyntheticSeaRaw(unittest.TestCase):
    def setUp(self):
        self.gen = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="seasyn_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_two_runs_are_byte_identical(self):
        a = self.tmp / "a.sea"
        b = self.tmp / "b.sea"
        self.gen.main(["x", str(a)])
        self.gen.main(["x", str(b)])
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_tracked_file_is_what_the_generator_writes(self):
        raw, _ = self.gen.build()
        self.assertEqual((_DATA / self.gen.SYNTHETIC_OUTPUTS[0]).read_bytes(), raw)

    def test_reader_decodes_every_buffer(self):
        raw, counts = self.gen.build()
        self.assertEqual(len(counts), self.gen.N_BUFFERS)
        src = self.tmp / "synth.sea"
        src.write_bytes(raw)
        out = self.tmp / "synth"
        result = sea.read_binary_SEA(src, str(out))
        self.assertEqual(tuple(result), (self.gen.N_BUFFERS, 0, 0))
        with netCDF4.Dataset(f"{out}.CIP.cdf") as nc:
            data = np.asarray(nc.variables["data"][:])
            hour = np.asarray(nc.variables["hour"][:])
        self.assertEqual(data.shape, (self.gen.N_BUFFERS, 1700, 8))
        # The tag-0 records carry the UTC-like clock, never the probe clock.
        self.assertTrue((hour == self.gen.UTC_START[0]).all())


if __name__ == "__main__":
    unittest.main()
