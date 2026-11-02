# SPDX-License-Identifier: BSD-3-Clause
"""Pins two malformed-input behaviours the pass-5 reader fuzz (item 8) found to
fail the same way as the original, so a later "robustness fix" cannot turn
them into a silent success without a test noticing.


"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe.readers import pms
from arrayprobe_soda2.spec_index import spec_index


class PmsHeaderWithoutTerminatorDies(unittest.TestCase):
    """``read_binary_PMS.m:103-106`` loops ``fgetl`` until a line strips to
    ``</OAP>``; at EOF ``fgetl`` returns ``-1`` and ``strtrim(-1)`` raises, so
    MATLAB dies. The port raises instead of returning zero records."""

    def test_a_file_with_no_oap_terminator_raises(self):
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            infile.write_bytes(b"<?xml version=\"1.0\"?>\n<OAP>\n" + b"\x00" * 64)
            with self.assertRaises(ValueError):
                pms.read_binary_PMS(str(infile), str(Path(d) / "out"))

    def test_an_empty_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            infile.write_bytes(b"")
            with self.assertRaises(ValueError):
                pms.read_binary_PMS(str(infile), str(Path(d) / "out"))


class SpecIndexOnAZeroedHeaderDies(unittest.TestCase):
    """``spec_index.pro:26-37``: a file whose first words are all zero matches
    its own first three words again at word 1, so ``buffsize = 2`` and
    ``ndataints = (buffsize - 16 - 2)/2`` is not a valid array length;
    ``uintarr(ndataints)`` at ``:37`` dies. The port dies too (a negative
    ``read`` length), rather than indexing a garbage buffer."""

    def test_an_all_zero_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.2DS"
            path.write_bytes(b"\x00" * 8228)
            with open(path, "rb") as f, self.assertRaises(ValueError):
                spec_index(f)


if __name__ == "__main__":
    unittest.main()
