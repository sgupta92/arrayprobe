# SPDX-License-Identifier: BSD-3-Clause
"""The synthetic DMT raw generator decodes through the shipped DMT reader.

``tests/data/make_dmt_raw_synthetic.py`` replaces the excluded real fixture;
this checks that it is deterministic and that ``read_binary_DMT`` decodes
every record, with one sync slice per particle on each canvas.
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.readers import dmt

_GEN = Path(__file__).resolve().parent / "data" / "make_dmt_raw_synthetic.py"


def _load():
    spec = importlib.util.spec_from_file_location("make_dmt_raw_synthetic", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SyntheticDmtRaw(unittest.TestCase):
    def setUp(self):
        self.gen = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="dmtsyn_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_two_runs_are_byte_identical(self):
        a = self.tmp / "a.cip"
        b = self.tmp / "b.cip"
        self.gen.main(["x", str(a)])
        self.gen.main(["x", str(b)])
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_reader_decodes_every_record_and_particle(self):
        raw, counts = self.gen.build()
        self.assertEqual(len(raw), self.gen.N_RECORDS * 4112)
        src = self.tmp / "synth.cip"
        src.write_bytes(raw)
        out = self.tmp / "synth.nc"
        n = dmt.read_binary_DMT(src, out)
        self.assertEqual(n, self.gen.N_RECORDS)
        self.assertEqual(dmt._n_decodable_records(src), self.gen.N_RECORDS)
        with netCDF4.Dataset(str(out)) as nc:
            data = np.asarray(nc.variables["data"][:])
            seconds = np.asarray(nc.variables["second"][:])
        self.assertEqual(seconds.tolist(), list(range(self.gen.N_RECORDS)))
        self.assertEqual(data.shape, (self.gen.N_RECORDS, 1700, 8))
        for k, expected in enumerate(counts):
            canvas = data[k]
            n_groups = int(np.argmax((canvas == -1).all(axis=1))) - 1
            syncs = int((canvas[:n_groups] == 0xAA).all(axis=1).sum())
            with self.subTest(record=k):
                self.assertEqual(syncs, expected)
        self.assertGreater(sum(counts), 40)


if __name__ == "__main__":
    unittest.main()
