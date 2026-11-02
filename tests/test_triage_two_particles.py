# SPDX-License-Identifier: BSD-3-Clause
"""The triage pages' additions: the two-particle sub-label and the context rows."""
import json
import tempfile
import unittest
from pathlib import Path

from arrayprobe import triage_server as ts


class TwoParticleSubLabel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _stored(self):
        return json.loads((self.dir / "triage_verdicts" / "f.json").read_text(encoding="utf-8"))

    def test_needs_a_two_particle_verdict_first(self):
        with self.assertRaises(LookupError):
            ts._save_parts(self.dir, "f", 7, 1, [2])
        ts._save_verdict(self.dir, "f", 7, "real", source="human", reviewer="test")
        with self.assertRaises(LookupError):
            ts._save_parts(self.dir, "f", 7, 1, [2])

    def test_stores_the_count_and_the_pieces(self):
        ts._save_verdict(self.dir, "f", 7, "mixed", source="human", phase="ice", reviewer="test")
        ts._save_parts(self.dir, "f", 7, 1, [2])
        rec = self._stored()["7"]
        self.assertEqual((rec["verdict"], rec["two_real"], rec["real_parts"], rec["phase"]),
                         ("mixed", 1, [2], "ice"))

    def test_refuses_shapes_that_do_not_add_up(self):
        ts._save_verdict(self.dir, "f", 7, "mixed", source="human", reviewer="test")
        for two, parts in ((3, None), (True, None), (0, [1]), (1, [1, 2]), (2, [1, 1]),
                           (1, [0]), (1, "1")):
            with self.assertRaises(ValueError, msg=(two, parts)):
                ts._save_parts(self.dir, "f", 7, two, parts)

    def test_a_count_without_pieces_is_allowed(self):
        ts._save_verdict(self.dir, "f", 7, "mixed", source="human", reviewer="test")
        ts._save_parts(self.dir, "f", 7, 2, None)
        self.assertNotIn("real_parts", self._stored()["7"])

    def test_survives_reclicking_two_particles_and_only_that(self):
        ts._save_verdict(self.dir, "f", 7, "mixed", source="human", reviewer="test")
        ts._save_parts(self.dir, "f", 7, 2, [1, 2])
        ts._save_verdict(self.dir, "f", 7, "mixed", source="human", reviewer="test")
        self.assertEqual(self._stored()["7"]["two_real"], 2)
        ts._save_verdict(self.dir, "f", 7, "real", source="human", reviewer="test")
        self.assertNotIn("two_real", self._stored()["7"])


class PartsGapIsRecorded(unittest.TestCase):
    """real_parts carry the piece gap they were numbered at; a legacy entry reads as gap 0."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _stored(self):
        return json.loads((self.dir / "triage_verdicts" / "f.json").read_text(encoding="utf-8"))

    def test_save_records_the_gap(self):
        ts._save_verdict(self.dir, "f", 7, "mixed", source="human", reviewer="test")
        ts._save_parts(self.dir, "f", 7, 1, [2], gap=3)
        self.assertEqual(self._stored()["7"]["parts_gap"], 3)
        ts._save_parts(self.dir, "f", 7, 1, [1])
        self.assertEqual(self._stored()["7"]["parts_gap"], ts.PIECE_GAP_DIODES)

    def test_legacy_entry_without_the_key_reads_as_gap_0(self):
        self.assertEqual(ts.parts_gap_of({"verdict": "mixed", "real_parts": [2]}), 0)
        self.assertEqual(ts.parts_gap_of({"verdict": "mixed", "real_parts": [2],
                                          "parts_gap": 5}), 5)
        self.assertEqual(ts.parts_gap_of({"verdict": "real"}), ts.PIECE_GAP_DIODES)
        self.assertEqual(ts.parts_gap_of(None), ts.PIECE_GAP_DIODES)

    def test_the_recorded_gap_numbers_that_entrys_pieces(self):
        import numpy as np

        from arrayprobe.triage_context import particle_parts
        c = np.zeros((4, 12), dtype=int)
        c[1, 1] = c[1, 5] = 1          # two pieces 3 empty diodes apart
        ts._save_verdict(self.dir, "f", 7, "mixed", source="human", reviewer="test")
        ts._save_parts(self.dir, "f", 7, 1, [2], gap=0)
        gap = ts.parts_gap_of(self._stored()["7"])
        self.assertEqual(len(particle_parts(c, gap=gap)), 2)
        self.assertEqual(len(particle_parts(c, gap=ts.PIECE_GAP_DIODES)), 1)

    def test_refuses_a_bad_gap(self):
        ts._save_verdict(self.dir, "f", 7, "mixed", source="human", reviewer="test")
        for g in (-1, True, "3"):
            with self.assertRaises(ValueError, msg=g):
                ts._save_parts(self.dir, "f", 7, 1, [2], gap=g)


class ContextRows(unittest.TestCase):
    def test_outcome_follows_the_code_and_shape_test_precedes_the_file_letter(self):
        info = {"particle_index": 1, "reject_code": "H", "habit_code": "s", "diam_minR": 0.1}
        extras = {"shape_habit": "t", "parts": 2,
                  "air_temperature": {"degC": -12.25, "source": "x.nc", "at": "14:22:21"}}
        keys = list(ts._info_with_extras(info, extras))
        self.assertEqual(keys, ["particle_index", "reject_code", "reject_outcome", "shape_habit",
                                "habit_code", "diam_minR", "parts", "air_temperature"])

    def test_the_rows_say_what_the_code_did_and_the_temperature(self):
        html = ts._kv_html(ts._info_with_extras(
            {"reject_code": "H", "habit_code": "s"},
            {"shape_habit": "t", "parts": 2,
             "air_temperature": {"degC": -12.25, "source": "x.nc", "at": "14:22:21"}}))
        self.assertIn("kept with its size corrected", html)
        self.assertIn("later screens", html)
        self.assertIn("-12.2 °C", html)
        self.assertIn("Holroyd shape test, re-run on this image", html)
        self.assertIn("numbered on the image", html)

    def test_no_met_folder_says_how_to_get_one(self):
        html = ts._kv_html({"air_temperature": {"degC": None, "why": "start with --met-dir"}})
        self.assertIn("not available: start with --met-dir", html)

    def test_a_rejected_code_says_so(self):
        html = ts._kv_html(ts._info_with_extras({"reject_code": "a"}, {}))
        self.assertIn("rejected: not counted in the size distribution", html)


if __name__ == "__main__":
    unittest.main()


class TheTwoParticleRowStaysHiddenUntilChosen(unittest.TestCase):
    """The row is hidden by its ``hidden`` attribute, which a ``display`` rule overrides
    unless the stylesheet restores it; shown early, a count click got a 409 and the 0/1/2
    keys were ignored (the reviewer's report, 2026-10-04)."""

    def test_the_stylesheet_lets_hidden_win(self):
        css = ts.STYLE.replace(" ", "")
        self.assertIn("[hidden]{display:none!important;}", css)

    def test_a_refused_count_names_the_missing_step(self):
        import inspect
        src = inspect.getsource(ts)
        self.assertIn("r.status === 409", src)
        self.assertIn('choose "Two particles" (T) first', src)


class TheCountRowLabelsInOneStep(unittest.TestCase):
    """The count row is always shown and says how many real particles the image holds:
    none real saves Artifact, all real saves Real, and only a mix is "Two particles" with
    the count (reviewer, 2026-10-04). Checked on the page's script text; the browser
    behaviour itself was exercised against a copy of the CIP queue."""

    def setUp(self):
        import inspect
        self.src = inspect.getsource(ts)

    def test_the_row_is_not_hidden_on_load(self):
        self.assertNotIn("{'' if current == 'mixed' else ' hidden'}", self.src)

    def test_none_real_is_artifact_and_all_real_is_real(self):
        self.assertIn("var direct = twoN === 0 ? 'artifact' : (allReal ? 'real' : null);",
                      self.src)
        self.assertIn("var allReal = twoN === 1 && nParts <= 1;", self.src)

    def test_a_mix_saves_two_particles_before_the_count(self):
        self.assertIn("countAfterVerdict = true;", self.src)
