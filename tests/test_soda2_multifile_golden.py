# SPDX-License-Identifier: BSD-3-Clause
"""Facts recorded by scripts/validation/gdl/run_soda2_multifile_bank.py --synthetic
(SODA-2, more than one raw file), on the synthetic DMT/PADS raw
``dmt_raw_synthetic.cip`` and its two-file split
(``tests/data/make_dmt_synthetic_split.py``)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "gdl_soda2_multifile_synthetic_golden.json"
SPEC_GOLDEN = DATA / "gdl_soda2_multifile_golden.json"
STOP_MESSAGE = ("Multiple files not supported with SPEC format, "
                "need to concatenate raw files first")

sys.path.insert(0, str(DATA))
from make_dmt_synthetic_split import write_split  # noqa: E402


@unittest.skipUnless(SPEC_GOLDEN.exists(),
                     "the SPEC two-file case was recorded on a SPEC raw sample cut "
                     "from real probe data; that sample's GDL record is not shipped "
                     "in this package")
class TestSpecTwoFilesStops(unittest.TestCase):
    """Recorded only where the real SPEC sample's GDL golden exists."""

    def setUp(self):
        cases = json.loads(SPEC_GOLDEN.read_text(encoding="utf-8"))["cases"]
        self.case = {c["name"]: c for c in cases}["spec_two_files"]

    def test_soda2_process_2d_376_prints_the_stop_message(self):
        self.assertEqual(self.case["fn_count"], 2)
        self.assertIn(STOP_MESSAGE, self.case["stdout"])
        self.assertTrue(self.case["stop_message_printed"])

    def test_soda2_process_2d_376_stops_at_the_prompt(self):
        self.assertEqual(self.case["status"], "STOPPED")
        after = self.case["stdout"].split(STOP_MESSAGE, 1)[1]
        self.assertIn("GDL>", after)


class TestCipUnsplitBaseline(unittest.TestCase):
    """The unsplit DMT/PADS fixture through soda2_process_2d (the baseline the
    split pair of the :363-391 index concatenation is compared to)."""

    def setUp(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.case = {c["name"]: c for c in golden["cases"]}["cip_unsplit"]

    def test_buffer_count_is_the_fixture_size_over_the_pads_record(self):
        fixture = DATA / self.case["fixture"]
        self.assertEqual(self.case["fixture_bytes"], fixture.stat().st_size)
        self.assertEqual(self.case["buffer_count"] * self.case["buffer_bytes"],
                         self.case["fixture_bytes"])
        self.assertEqual(self.case["fn_count"], 1)

    def test_the_driver_ran_to_an_output_file(self):
        self.assertEqual(self.case["status"], "OK")
        self.assertGreater(self.case["NUMRECORDS"], 0)

    def test_a_separate_run_reproduces_the_dmt_bank_driver_golden(self):
        dmt = json.loads((DATA / "gdl_soda2_dmt_synthetic_golden.json")
                         .read_text(encoding="utf-8"))["driver"]
        for key, value in dmt.items():
            if key != "name":
                self.assertEqual(self.case[key], value, key)


class TestCipSplitMatchesUnsplit(unittest.TestCase):
    """Case (a): the fixture split at buffer 6 into two files, passed as a
    two-element fn. Every output field equals cip_unsplit's except CURRENTFILE
    and POINTER, the per-record file index and byte offset, which GDL records
    relative to the part each buffer came from."""

    BOOKKEEPING = {"name", "fixture", "fn_count", "buffer_bytes", "buffer_count",
                   "fixture_bytes", "part_bytes"}
    PER_FILE = {"CURRENTFILE", "POINTER"}

    def setUp(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cases = {c["name"]: c for c in golden["cases"]}
        self.split, self.unsplit = cases["cip_split"], cases["cip_unsplit"]
        self.not_recorded = golden["not_recorded"]
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.parts = write_split(Path(self._tmp.name))

    def test_twelve_buffers_over_two_files(self):
        self.assertEqual(self.split["buffer_count"], 12)
        self.assertEqual(self.split["fn_count"], 2)
        self.assertEqual([p.name for p in self.parts], self.split["fixture"])
        for path, size in zip(self.parts, self.split["part_bytes"], strict=True):
            self.assertEqual(path.stat().st_size, size)

    def test_parts_concatenate_to_the_unsplit_fixture(self):
        parts = b"".join(p.read_bytes() for p in self.parts)
        self.assertEqual(parts, (DATA / self.unsplit["fixture"]).read_bytes())

    def test_every_output_field_except_the_per_file_ones_equals_unsplit(self):
        self.assertEqual(self.split["status"], "OK")
        keys = (set(self.split) | set(self.unsplit)) - self.BOOKKEEPING - self.PER_FILE
        for key in keys:
            self.assertEqual(self.split.get(key), self.unsplit.get(key), key)

    def test_only_the_per_file_fields_differ(self):
        for key in self.PER_FILE:
            self.assertNotEqual(self.split[key], self.unsplit[key], key)

    def test_soda2_process_2d_684_writes_bufffile_and_buffpoint_per_buffer(self):
        # :684 writes currentfile:bufffile, pointer:buffpoint -- one entry per
        # buffer, not per record. :373/:380 set bufffile to the fn index of the
        # buffer's file; :372/:379 concatenate each file's own buffer offsets.
        part = self.split["part_bytes"][0]
        per_part = self.split["buffer_count"] // self.split["fn_count"]
        n = self.split["buffer_count"]
        self.assertEqual(len(self.split["CURRENTFILE"]), n)
        self.assertEqual(len(self.split["POINTER"]), n)
        self.assertEqual(self.split["CURRENTFILE"], [0] * per_part + [1] * per_part)
        self.assertEqual(self.unsplit["CURRENTFILE"], [0] * n)
        self.assertEqual(self.unsplit["POINTER"],
                         [i * self.split["buffer_bytes"] for i in range(n)])
        for f, p_split, p_unsplit in zip(self.split["CURRENTFILE"], self.split["POINTER"],
                                         self.unsplit["POINTER"], strict=True):
            self.assertEqual(p_split, p_unsplit - part * f)
        self.assertEqual(part, per_part * self.split["buffer_bytes"])

    def test_only_the_spec_case_is_unrecorded_on_synthetic_data(self):
        self.assertEqual(self.not_recorded, ["spec_two_files"])


if __name__ == "__main__":
    unittest.main()
