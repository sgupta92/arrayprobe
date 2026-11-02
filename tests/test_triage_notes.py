# SPDX-License-Identifier: BSD-3-Clause
"""A queue's machine notes read as named columns, and "code H" reads as the reject code.

A queue item's note is a machine string (``cold window, 55-100um, minR 83 um, code H, record
time 142221``). "code H" there is the automatic reject code -- H/h are the two hollow verdicts --
and never the Holroyd habit letter ``h`` (hexagonal): on the captured 2018-02-15 page, item 0's
note says ``code H`` while its own file gives ``reject_code H`` and ``habit_code s``. The queue
index shows the note's parts as columns in words with the letter in small type, a legend above
the table, and the note itself as a tooltip. These tests build the index on a stand-in with only
the attributes the method reads, so no server or image file is needed.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe.matlab_compat import HOLROYD_HABITS, REJECT_CODE_WORDS
from arrayprobe.triage_server import TriageServer, _save_verdict

FLIGHT = "base180215125340"
QUEUE = "iop2-cold"
NOTE_SIZE = "cold window, 55-100um, minR 83 um, code H, record time 142221"
NOTE_IA = "cold window, inter-arrival <= 1 us (0.29 us), minR 20 um, code h, record time 142410"
NOTE_UNKNOWN = "hand-picked by the author: looks like two drops touching"


class _Pages:
    """The attributes the queue index reads, and the real methods under test."""

    _queue_verdicts = TriageServer._queue_verdicts
    _render_queue_index = TriageServer._render_queue_index

    def __init__(self, decoded_dir: Path, queues: dict[str, list[dict]]):
        self.decoded_dir = decoded_dir
        self.queues = queues

    def _flights(self) -> dict[str, dict]:
        return {FLIGHT: {"probe": "2DS"}}


class ParseNote(unittest.TestCase):
    def test_the_size_bin_note_parses_to_its_fields(self):
        from arrayprobe.triage_server import parse_note
        got = parse_note(NOTE_SIZE)
        self.assertEqual(got["window"], "cold window")
        self.assertEqual(got["size_bin"], "55–100 µm")
        self.assertEqual(got["minR_um"], 83)
        self.assertEqual(got["code"], "H")
        self.assertEqual(got["record_time"], "14:22:21 UTC")
        self.assertNotIn("ia_us", got)

    def test_the_inter_arrival_note_parses_to_its_fields(self):
        from arrayprobe.triage_server import parse_note
        got = parse_note(NOTE_IA)
        self.assertEqual(got["window"], "cold window")
        self.assertEqual(got["ia_us"], 0.29)
        self.assertEqual(got["minR_um"], 20)
        self.assertEqual(got["code"], "h")
        self.assertEqual(got["record_time"], "14:24:10 UTC")
        self.assertNotIn("size_bin", got)

    def test_an_unknown_note_comes_back_verbatim(self):
        from arrayprobe.triage_server import parse_note
        self.assertEqual(parse_note(NOTE_UNKNOWN), {"text": NOTE_UNKNOWN})

    def test_a_note_with_one_unrecognised_part_is_not_half_parsed(self):
        from arrayprobe.triage_server import parse_note
        odd = NOTE_SIZE + ", something new"
        self.assertEqual(parse_note(odd), {"text": odd})


class WordsComeFromThePackageTables(unittest.TestCase):
    def test_every_habit_letter_has_a_word_and_only_those(self):
        from arrayprobe.triage_server import HABIT_WORDS
        self.assertEqual(set(HABIT_WORDS), set(HOLROYD_HABITS))

    def test_habit_groups_cover_every_letter_once(self):
        from arrayprobe.triage_server import HABIT_GROUPS
        letters = [c for _, group in HABIT_GROUPS for c in group if c]
        self.assertEqual(sorted(letters), sorted(HOLROYD_HABITS))

    def test_hollow_codes_read_as_the_reject_words(self):
        from arrayprobe.triage_server import reject_code_words
        self.assertEqual(reject_code_words("H"), REJECT_CODE_WORDS["H"])
        self.assertEqual(reject_code_words("h"), REJECT_CODE_WORDS["h"])
        self.assertIn("hollow", reject_code_words("H"))


class TheQueueIndex(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        items = [
            {"flight": f"{FLIGHT}.H", "particle_index": 11, "note": NOTE_SIZE},
            {"flight": f"{FLIGHT}.H", "particle_index": 12, "note": NOTE_IA},
            {"flight": f"{FLIGHT}.H", "particle_index": 13, "note": NOTE_UNKNOWN},
        ]
        self.pages = _Pages(self.dir, {QUEUE: items})
        _save_verdict(self.dir, FLIGHT, 11, "mixed", source="human", queue=QUEUE,
                      comment="two touching", phase="ice", reviewer="test")
        self.page = self.pages._render_queue_index(QUEUE).decode("utf-8")

    def test_code_H_renders_the_reject_word_never_hexagonal(self):
        self.assertIn(f"{REJECT_CODE_WORDS['H']}</span> <small class='muted'>H</small>",
                      self.page)
        self.assertNotIn("hexagonal</span> <small class='muted'>H</small>", self.page)

    def test_columns_and_legend(self):
        for head in ("Habit", "Smallest circle (µm)", "Reject code", "Record time",
                     "Your label", "Phase", "Comment"):
            self.assertIn(f"<th>{head}</th>", self.page)
        self.assertIn("H/h = hollow, accepted here", self.page)
        self.assertLess(self.page.index("H/h = hollow"), self.page.index("<table"))
        self.assertIn("<td>14:22:21 UTC</td>", self.page)
        self.assertIn("<td>83</td>", self.page)

    def test_the_note_moves_to_a_tooltip(self):
        self.assertIn(f"title='{NOTE_SIZE}'", self.page)
        self.assertNotIn(f">{NOTE_SIZE}<", self.page)

    def test_an_unknown_note_is_shown_verbatim(self):
        self.assertIn(f">{NOTE_UNKNOWN}<", self.page)

    def test_label_phase_and_comment_read_in_words(self):
        self.assertIn(">two particles</b>", self.page)
        self.assertNotIn(">mixed<", self.page)
        self.assertIn("<td>ice</td>", self.page)
        self.assertIn("✎", self.page)


if __name__ == "__main__":
    unittest.main()
