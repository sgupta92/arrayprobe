# SPDX-License-Identifier: BSD-3-Clause
"""Raw-file inventory flags empty and truncated files (raw-input inventory)."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_source

from arrayprobe import inventory as inv

_SRC = Path(__file__).resolve().parents[1] / "src"
_PREAMBLE = b"<?xml version='1.0'?>\n<OAP>\n<Probe id='P1'/>\n</OAP>\n"


def _literal(rel: str, name: str) -> int:
    """Second source: the integer literal assigned to ``name`` in the reader's source text."""
    text = (_SRC / rel).read_text(encoding="utf-8")
    m = re.search(rf"^{name}\s*=\s*(\d+)\b", text, re.M)
    if m:
        return int(m.group(1))
    # spec_core computes it; its value is stated in the line's comment
    m = re.search(rf"^{name}\s*=.*#\s*(\d+)\s*$", text, re.M)
    return int(m.group(1))


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def put(self, name, data):
        p = self.d / name
        p.write_bytes(data)
        return p


class TestFlags(_Tmp):
    def test_empty_file_is_flagged_empty(self):
        row = inv.inventory_row(self.put("base.2DS", b""))
        self.assertTrue(row["empty"])
        self.assertEqual(row["size"], 0)

    def test_spec_cut_mid_record_is_truncated(self):
        n = inv.RECORD_BYTES["spec"]
        row = inv.inventory_row(self.put("base.2DS", b"\x00" * (3 * n + 100)))
        self.assertTrue(row["truncated"])
        self.assertEqual(row["trailing_bytes"], 100)
        self.assertFalse(row["empty"])

    def test_clean_whole_records_are_not_flagged(self):
        for fmt, name in (("spec", "a.2DS"), ("dmt", "a.cip")):
            n = inv.RECORD_BYTES[fmt]
            row = inv.inventory_row(self.put(name, b"\x01" * (2 * n)))
            self.assertEqual(row["format_guess"], fmt)
            self.assertFalse(row["empty"])
            self.assertFalse(row["truncated"], fmt)

    def test_pms_2d_counts_records_after_the_oap_preamble(self):
        n = inv.RECORD_BYTES["pms_2d"]
        clean = inv.inventory_row(self.put("f.2d", _PREAMBLE + b"\x02" * (2 * n)))
        self.assertEqual(clean["format_guess"], "pms_2d")
        self.assertEqual(clean["header_bytes"], len(_PREAMBLE))
        self.assertFalse(clean["truncated"])
        cut = inv.inventory_row(self.put("g.2d", _PREAMBLE + b"\x02" * (2 * n - 7)))
        self.assertTrue(cut["truncated"])

    def test_unknown_format_flags_only_empty(self):
        row = inv.inventory_row(self.put("x.bin", b"\x00" * 17))
        self.assertIsNone(row["truncated"])
        self.assertFalse(row["empty"])

    def test_sha256_and_files_written(self):
        self.put("a.2DS", b"")
        self.put("b.2DS", b"\x00" * inv.RECORD_BYTES["spec"])
        rows = inv.inventory(self.d)
        self.assertEqual(len(rows), 2)
        out = self.d / "out" / "inventory"
        out.parent.mkdir()
        j, c = inv.write_inventory(rows, out)
        self.assertEqual(json.loads(j.read_text())[0]["sha256"],
                         "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertIn("truncated", c.read_text().splitlines()[0])

    def test_a_dotted_out_stem_keeps_every_dot(self):
        # ``with_suffix`` turned "inv_2026.10.28" into "inv_2026.10.json" until 2026-10-28.
        j, c = inv.write_inventory([], self.d / "inv_2026.10.28")
        self.assertEqual((j.name, c.name), ("inv_2026.10.28.json", "inv_2026.10.28.csv"))
        self.assertTrue(j.is_file() and c.is_file())

    def test_cli_refuses_a_missing_path_with_exit_2(self):
        import contextlib
        import io

        from arrayprobe import cli
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.main(["inventory", str(self.d / "absent"), "--out", str(self.d / "o")])
        self.assertEqual(rc, 2)
        self.assertIn("no such file or directory", err.getvalue())
        self.assertFalse((self.d / "o.json").exists())


@needs_source
class TestRecordLengthsAreTheReaders(unittest.TestCase):
    """Two sources: the inventory's table, and the integer in each reader's source text."""

    def test_record_lengths_equal_reader_constants(self):
        self.assertEqual(inv.RECORD_BYTES["spec"],
                         _literal("arrayprobe_uiops/spec_core.py", "RECORD_BYTES"))
        self.assertEqual(inv.RECORD_BYTES["dmt"],
                         _literal("arrayprobe/readers/dmt.py", "_RECORD_BYTES"))
        self.assertEqual(inv.RECORD_BYTES["pms_2d"],
                         _literal("arrayprobe_uiops/readers/pms.py", "_RECORD_BYTES"))

    def test_inventory_source_types_no_record_length(self):
        text = (_SRC / "arrayprobe" / "inventory.py").read_text(encoding="utf-8")
        code = text.split('"""', 2)[2]  # skip the module docstring
        for n in (4112, 4114, 4116):
            self.assertNotIn(str(n), code)


class TestMustFire(_Tmp):
    """The flag must fire on every cut point inside a record, and on none at a boundary."""

    def test_every_partial_tail_fires(self):
        n = inv.RECORD_BYTES["spec"]
        for tail in (1, n // 2, n - 1):
            row = inv.inventory_row(self.put(f"t{tail}.2DS", b"\x00" * (n + tail)))
            self.assertTrue(row["truncated"], tail)
        self.assertFalse(inv.inventory_row(self.put("w.2DS", b"\x00" * n))["truncated"])


if __name__ == "__main__":
    unittest.main()
