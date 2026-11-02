# SPDX-License-Identifier: BSD-3-Clause
"""STOCK_V35: every field cites a v3.5 line, agreeing with what Octave read from that source.

Two independent readers of the same claim: ``arrayprobe_uiops.profile.STOCK_V35_PROVENANCE``
was typed by hand from the vendored v3.5 tree; ``tests/data/v35_profile_octave_golden.json``
was produced by Octave running ``octave_oracle/run_v35_profile_oracle.m`` against the same,
unmodified tree (``octave_oracle/run_v35_profile_bank.py``). They can only agree by both
being right about the source.
"""
import json
import unittest
from pathlib import Path

from tests import _upstream
from tests._repo import repo_only

from arrayprobe import profiles
from arrayprobe.profiles import PROFILES, SHIPPED, STOCK_V35, STOCK_V314
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG
from arrayprobe_uiops.profile import STOCK_V35_PROVENANCE, V35_TREE

ROOT = Path(__file__).resolve().parents[1]
TREE = ROOT.joinpath(*V35_TREE)
GOLDEN = json.loads((Path(__file__).parent / "data" / "v35_profile_octave_golden.json").read_text())


def _lines(name):
    path = _upstream.cited_path("/".join((*V35_TREE, name)))
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _aslist(x):
    """jsonencode collapses a 1-element MATLAB numeric vector to a JSON scalar,
    and Octave's [] (no match) to a JSON empty array. Normalise both to a list
    so every ``*_lines`` field can be compared the same way."""
    if isinstance(x, list):
        return x
    return [x]


class ProvenanceLinesSayWhatTheTableSays(unittest.TestCase):
    @repo_only
    def test_every_cited_line_contains_its_token(self):
        for p in STOCK_V35_PROVENANCE:
            src = _lines(p.file)
            with self.subTest(field=p.field):
                if not p.lines:  # absence claim
                    found = any(p.token in line for line in src)
                    self.assertFalse(found, f"{p.token} found in {p.file}")
                    continue
                for n in p.lines:
                    self.assertIn(p.token, src[n - 1], f"{p.file}:{n}")

    def test_every_profile_field_has_a_provenance_row(self):
        fields = {p.field.split(".")[0] for p in STOCK_V35_PROVENANCE}
        self.assertEqual(fields, set(STOCK_V35.__dataclass_fields__) - {"name", "description"})

    def test_table_values_are_the_profile_values(self):
        for p in STOCK_V35_PROVENANCE:
            obj = STOCK_V35
            for part in p.field.split("."):
                obj = getattr(obj, part)
            with self.subTest(field=p.field):
                self.assertEqual(obj, p.value)


class OctaveReadTheSameConstants(unittest.TestCase):
    """Side A: the profile (typed). Side B: Octave parsing the vendored source (golden)."""

    def test_reject_thresholds(self):
        names = ("rej_zero_area", "rej_split", "rej_hollow",
                  "shadowed_area", "max_edge_img_ar", "max_comp_img_ar")
        for name in names:
            with self.subTest(name=name):
                got = getattr(STOCK_V35.reject_thresholds, name)
                self.assertEqual(float(got), GOLDEN["reject"][name]["value"])
                row = next(p for p in STOCK_V35_PROVENANCE
                           if p.field == f"reject_thresholds.{name}")
                self.assertEqual(row.lines, (GOLDEN["reject"][name]["line"],))

    def test_buffer_guard_lines(self):
        self.assertEqual(_aslist(GOLDEN["spec_buffer_guard_lines"]), [322, 326, 333, 356, 360, 367])
        self.assertTrue(STOCK_V35.spec_buffer_guard)

    def test_hvps_reader_has_nothing_else_to_be(self):
        self.assertFalse(GOLDEN["read_binary_hvps_exists"])
        self.assertEqual(STOCK_V35.hvps_reader, "spec")

    def test_diode_stats(self):
        self.assertEqual(_aslist(GOLDEN["diode_stats_lit_lines"]), [])
        self.assertEqual(_aslist(GOLDEN["diode_stats_shadowed_lines"]), [1208, 1210, 1211])
        self.assertTrue(STOCK_V35.diode_stats_counts_shadowed)

    def test_zero_image_recovery(self):
        self.assertEqual(_aslist(GOLDEN["zero_image_recovery_lines"]), [773, 1311])
        self.assertTrue(STOCK_V35.zero_image_particle_recovery)

    def test_time_and_inter_arrival(self):
        self.assertEqual(_aslist(GOLDEN["tas_lookup_lines"]), [1133])
        self.assertEqual(_aslist(GOLDEN["inter_arrival_lines"]), [1176])
        self.assertTrue(STOCK_V35.time_in_seconds_from_tas)
        self.assertTrue(STOCK_V35.inter_arrival_in_seconds)

    def test_no_shadow_diode_block(self):
        self.assertEqual(GOLDEN["shadow_diode_count"], 0)
        self.assertFalse(STOCK_V35.shadow_diode_reillumination)

    def test_typed_output(self):
        self.assertEqual(_aslist(GOLDEN["int16_auto_reject_lines"]), [1352])
        self.assertEqual(STOCK_V35.imgproc_output_typing, "typed")
        # F2: engine contract (NETCDF4 vs classic), not a profile axis.
        self.assertEqual(_aslist(GOLDEN["netcdf_create_mode"]), ["NETCDF4"])


class TheProfileIsWhatV9Ran(unittest.TestCase):
    def test_reject_thresholds_are_the_v9_object(self):
        """v9_compare.py:41,55 ran the goldens with STOCK_V35_REJECT_CONFIG; identity
        carries V9's zero-disagreement result to the profile."""
        self.assertIs(STOCK_V35.reject_thresholds, STOCK_V35_REJECT_CONFIG)

    def test_same_values_as_stock_v314_different_provenance(self):
        for f in set(STOCK_V314.__dataclass_fields__) - {"name", "description"}:
            with self.subTest(field=f):
                self.assertEqual(getattr(STOCK_V35, f), getattr(STOCK_V314, f))
        self.assertNotEqual(STOCK_V35.description, STOCK_V314.description)
        self.assertIn("v3.5", STOCK_V35.description)


class ItIsShipped(unittest.TestCase):
    def test_registered_and_shipped(self):
        self.assertIn("stock-v3.5", SHIPPED)
        self.assertIs(PROFILES["stock-v3.5"], STOCK_V35)
        self.assertIs(profiles.profile("stock-v3.5"), STOCK_V35)


if __name__ == "__main__":
    unittest.main()
