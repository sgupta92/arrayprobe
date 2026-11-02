# SPDX-License-Identifier: BSD-3-Clause
"""The triage viewer's IMPACTS habit vocabulary (Schima et al. 2024).

``triage_server.HABIT_CHOICES`` is read from the v3.5 engine's port of
``holroyd_new.m`` (``arrayprobe_uiops.habit._holroyd_new_impl``). The equality test
draws its other side from the vendored MATLAB file itself, so the two sides come
from different places. A verdict's ``habit`` field is optional: sidecars written
before it existed load unchanged (no label is lost).
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _upstream  # noqa: E402

from arrayprobe import triage_server as ts


def _holroyd_new_m() -> Path:
    return _upstream.require("uiops35") / "joefinlon-UIOPS-039be82" / "holroyd_new.m"


def _matlab_habit_letters() -> set[str]:
    """Every letter ``holroyd_new.m`` assigns to ``holroyd_habit``, comments stripped."""
    letters: set[str] = set()
    for line in _holroyd_new_m().read_text(encoding="utf-8", errors="replace").splitlines():
        code = line.split("%", 1)[0]
        letters.update(re.findall(r"holroyd_habit\s*=\s*'(.)'", code))
    return letters


def _vocabulary_matches(vocab, matlab_letters: set[str]) -> bool:
    return len(vocab) == len(set(vocab)) and set(vocab) == matlab_letters


class TestVocabularyIsTheEngines(unittest.TestCase):
    def test_vocabulary_equals_holroyd_new_m_letters(self):
        self.assertTrue(_holroyd_new_m().is_file(), _holroyd_new_m())
        matlab = _matlab_habit_letters()
        self.assertTrue(matlab, "no holroyd_habit assignments found in holroyd_new.m")
        self.assertTrue(_vocabulary_matches(ts.HABIT_CHOICES, matlab),
                        f"{ts.HABIT_CHOICES} vs holroyd_new.m {sorted(matlab)}")

    def test_vocabulary_is_read_from_the_v35_port(self):
        self.assertEqual(ts._schima_habit_letters(), ts.HABIT_CHOICES)

    def test_must_fire_a_tampered_vocabulary_fails_the_equality(self):
        matlab = _matlab_habit_letters()
        dropped = ts.HABIT_CHOICES[:-1]
        added = (*ts.HABIT_CHOICES, "Q" if "Q" not in matlab else "#")
        duplicated = (*ts.HABIT_CHOICES, ts.HABIT_CHOICES[0])
        for tampered in (dropped, added, duplicated):
            with mock.patch.object(ts, "HABIT_CHOICES", tampered):
                self.assertFalse(_vocabulary_matches(ts.HABIT_CHOICES, matlab), tampered)


class TestHabitOnVerdicts(unittest.TestCase):
    FLIGHT = "base000000000000.H"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _save(self, idx, **kw):
        return ts._save_verdict(self.dir, self.FLIGHT, idx, "real", source="human",
                                reviewer="tester", **kw)

    def test_old_sidecar_without_habit_loads_unchanged(self):
        old = {"7": {"verdict": "artifact", "note": "", "source": "human",
                     "at": "2026-09-01T00:00:00+00:00", "tool": "0.0"},
               "9": "real"}
        p = ts._verdicts_path(self.dir, self.FLIGHT)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(old), encoding="utf-8")
        self.assertEqual(ts._load_verdicts(self.dir, self.FLIGHT), old)
        data = self._save(8, habit=ts.HABIT_CHOICES[0])
        self.assertEqual(data["7"], old["7"])
        self.assertEqual(data["9"], old["9"])

    def test_valid_habit_round_trips_and_is_carried_forward(self):
        habit = ts.HABIT_CHOICES[-1]
        self._save(3, habit=habit)
        self.assertEqual(ts._load_verdicts(self.dir, self.FLIGHT)["3"]["habit"], habit)
        self._save(3)  # re-click without a habit: the label is not lost
        rec = ts._load_verdicts(self.dir, self.FLIGHT)["3"]
        self.assertEqual(rec["habit"], habit)
        self.assertEqual(rec["history"][0]["habit"], habit)

    def test_verdict_without_habit_has_no_habit_key(self):
        self._save(4)
        self.assertNotIn("habit", ts._load_verdicts(self.dir, self.FLIGHT)["4"])

    def test_invalid_habit_is_refused_and_nothing_saved(self):
        bad = "not-a-habit"
        self.assertNotIn(bad, ts.HABIT_CHOICES)
        with self.assertRaises(ValueError):
            self._save(5, habit=bad)
        self.assertNotIn("5", ts._load_verdicts(self.dir, self.FLIGHT))


if __name__ == "__main__":
    unittest.main()


def _imgproc_m() -> Path:
    return _upstream.require("uiops35") / "joefinlon-UIOPS-039be82" / "imgProc_sm.m"


def _widget(**kw) -> tuple[str, str]:
    from arrayprobe.triage_server import TriageServer
    kw.setdefault("flight_raw", "f")
    kw.setdefault("idx", 1)
    kw.setdefault("current", None)
    return TriageServer._verdict_widget(None, **kw)  # type: ignore[arg-type]


def _matlab_habit_words() -> dict[str, str]:
    """``{letter: word}`` from the ``iNewHabit == 1`` Description of ``holroyd_habit``."""
    text = _imgproc_m().read_text(encoding="utf-8", errors="replace")
    start = text.index("'ASCII habit code following the Holroyd (1987) algorithm '")
    block = text[start:text.index("else", start)]
    return {m.group(1): m.group(2).strip() for m in re.finditer(
        r'"(.)" or \d+: ([a-z/ -]+?)(?=[;)"])', block)}


class TestHabitButtons(unittest.TestCase):
    def test_one_button_per_choice_with_its_letter(self):
        html_, _ = _widget(current_phase="ice")
        found = re.findall(r"class='habit [^']*' data-h='(.)'", html_)
        self.assertEqual(tuple(found), ts.HABIT_CHOICES)

    def test_row_is_hidden_unless_ice_or_two_particles(self):
        self.assertIn("id='habit-row' hidden", _widget()[0])
        self.assertIn("id='habit-row' hidden", _widget(current_phase="drizzle")[0])
        self.assertNotIn("id='habit-row' hidden", _widget(current_phase="ice")[0])
        self.assertNotIn("id='habit-row' hidden", _widget(current="mixed")[0])

    def test_stored_habit_is_marked_selected_and_posted(self):
        html_, script = _widget(current_phase="ice", current_habit="l")
        self.assertIn("class='habit sel pbtn' data-h='l'", html_)
        self.assertIn("var habit = \"l\";", script)
        self.assertIn("habit: habit", script)

    def test_words_come_from_the_description_attribute(self):
        words = _matlab_habit_words()
        self.assertEqual(set(words), set(ts.HABIT_CHOICES))
        self.assertEqual(ts.HABIT_WORDS, words)

    def test_words_check_must_fire(self):
        words = dict(ts.HABIT_WORDS)
        words["l"] = "needles"
        self.assertNotEqual(words, _matlab_habit_words())

    def test_a_letter_without_a_word_is_shown_alone(self):
        with mock.patch.dict(ts.HABIT_WORDS, clear=True):
            html_, _ = _widget(current_phase="ice")
        self.assertIn("data-h='l' aria-pressed='false'>l</button>", html_)


class TestBulkPassthrough(unittest.TestCase):
    def test_bulk_save_stores_habit_on_every_index(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "triage_verdicts").mkdir()
            data = ts._save_verdicts_bulk(Path(d), "fl", [1, 2], "real", habit="l", reviewer="t")
            self.assertEqual([data[k]["habit"] for k in ("1", "2")], ["l", "l"])

    def test_bulk_without_habit_has_no_habit_key(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "triage_verdicts").mkdir()
            data = ts._save_verdicts_bulk(Path(d), "fl", [1], "real", reviewer="t")
            self.assertNotIn("habit", data["1"])

    def test_bulk_refuses_an_unknown_habit(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "triage_verdicts").mkdir()
            with self.assertRaises(ValueError):
                ts._save_verdicts_bulk(Path(d), "fl", [1], "real", habit="Z", reviewer="t")
