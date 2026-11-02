# SPDX-License-Identifier: BSD-3-Clause
"""The v3.5 example in ``arrayprobe``'s package docstring runs as written.

It is the first Python a user reads, so it is executed rather than trusted: the first literal
block of ``arrayprobe.__doc__`` runs verbatim in a temporary directory holding the file names it
uses -- ``flight.sea`` (the tracked synthetic SEA file, CIP buffers only) and ``airspeed.tas.csv``
(a
constant 100 m/s over the fixture's CIP-clock span, NOT a measurement; see
``tests/test_example_cip_config.py`` for why the span is the probe clock).

The second block, the validation path, names archived ORACLES files that are not tracked, so
only its shape is checked: it stays marked as the validation path and names the anchor engine's
own functions.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

import numpy as np

import arrayprobe

FIXTURE = Path(__file__).parent / "data" / "sea_raw_synthetic.sea"


def _blocks(doc: str) -> list[str]:
    """Every reST literal block (``::`` then an indented body) in ``doc``, dedented."""
    out = []
    for m in re.finditer(r"::\n\n((?:(?:    .*)?\n)+)", doc):
        out.append(textwrap.dedent(m.group(1)))
    return out


class TheDefaultEngineExampleRuns(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.blocks = _blocks(arrayprobe.__doc__)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        root = Path(cls._tmp.name)
        shutil.copyfile(FIXTURE, root / "flight.sea")
        from arrayprobe.tools.make_tas_file import write_tas_csv
        sod = np.arange(13, 102, dtype=np.int64)
        hhmmss = (sod // 3600) * 10000 + ((sod % 3600) // 60) * 100 + sod % 60
        write_tas_csv(root / "airspeed.tas.csv", hhmmss, np.full(sod.shape, 100.0),
                      seconds_of_day=sod)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            exec(compile(cls.blocks[0], "arrayprobe.__doc__[example]", "exec"), {})
        finally:
            os.chdir(cwd)
        cls.root = root

    def test_the_first_example_selects_the_default_engine(self):
        self.assertIn("ap.engine()", self.blocks[0])
        self.assertEqual(arrayprobe.engine().name, "3.5")

    def test_it_writes_a_v35_size_distribution_with_counts(self):
        import netCDF4

        from arrayprobe import ncio
        sd = self.root / "sd.nc"
        self.assertTrue(sd.exists())
        self.assertEqual(ncio.engine_of(self.root / "proc.nc"), "3.5")
        with netCDF4.Dataset(sd) as nc:
            self.assertEqual(nc.variables["count"].shape[1], 19)
            self.assertGreater(float(np.nansum(nc.variables["count"][:])), 0.0)


class TheValidationPathStaysMarked(unittest.TestCase):

    def test_the_anchor_example_is_second_and_labelled(self):
        doc = arrayprobe.__doc__
        blocks = _blocks(doc)
        self.assertGreaterEqual(len(blocks), 2)
        self.assertIn("ap.read_binary_SPEC", blocks[1])
        self.assertIn("2DS_intArrThreshold_MISSING.cdf", blocks[1])
        self.assertLess(doc.index("The validation path"), doc.index(blocks[1].splitlines()[2]))


if __name__ == "__main__":
    unittest.main()
