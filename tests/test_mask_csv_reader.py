# SPDX-License-Identifier: BSD-3-Clause
"""``load_mask_csv`` reads the newline-free ``.MK.csv`` sidecar.

The sidecar itself is written by :class:`arrayprobe.readers.spec.SidecarWriter`
(``tests/test_spec_reader.py::test_mask_records_have_no_line_terminator``
pins the writer's own preserved-bug format); this module only reads it back.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from tests._repo import needs_v314_engine

from arrayprobe.readers.mask_csv import MaskRecord, load_mask_csv


class LoadingARealSidecar(unittest.TestCase):
    @needs_v314_engine
    def test_two_records_round_trip_with_no_newline_in_the_file(self):
        from arrayprobe.readers import spec  # the v3.1.4 writer; absent from the public tree

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            sc = spec.SidecarWriter(out)
            sc.mask(100, list(range(16)), 5, 9)
            sc.mask(200, [1] * 16, 6, 10)
            sc.flush()

            path = out + ".MK.csv"
            with open(path) as fh:
                text = fh.read()
            self.assertNotIn("\n", text, "the sidecar itself must stay newline-free")

            records = load_mask_csv(path)
            self.assertEqual(records, [
                MaskRecord(time_word=100, mask_bits=tuple(range(16)),
                           time_start=5, time_end=9),
                MaskRecord(time_word=200, mask_bits=(1,) * 16,
                           time_start=6, time_end=10),
            ])

class RefusingAMalformedFile(unittest.TestCase):
    def test_a_token_count_not_a_multiple_of_nineteen_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.MK.csv")
            with open(path, "w") as fh:
                fh.write("1, 2, 3, ")
            with self.assertRaises(ValueError):
                load_mask_csv(path)

    def test_an_empty_file_yields_no_records_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "empty.MK.csv")
            open(path, "w").close()
            self.assertEqual(load_mask_csv(path), [])


if __name__ == "__main__":
    unittest.main()
