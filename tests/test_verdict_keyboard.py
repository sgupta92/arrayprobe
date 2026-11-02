# SPDX-License-Identifier: BSD-3-Clause
"""Keyboard labelling: every verdict has a key, and the key path is the click path.

WHY. Author request, 2026-09-16: *"have it the version where i can just use the
keyboard and keys"*. A labelling pass is hundreds of particles and reaching for
the mouse on each one is most of the cost, so the viewer binds one key per
verdict plus next/previous.

THE DESIGN THIS TEST PROTECTS. The keys dispatch a **click on the existing
button**; they do not POST. That keeps saving, the selected-button highlight,
queue provenance and queue auto-advance on a single code path. A second path
here would be a second thing to keep correct, and the two would drift the way
the plain and queue particle pages were deliberately stopped from drifting by
sharing ``_verdict_widget`` in the first place.

The viewer never changes a computed number -- it visualises and labels -- which
is why it lives in the port at all, so nothing here may touch the chain.
"""
from __future__ import annotations

import re
import unittest

from arrayprobe.triage_server import (  # noqa: F401
    _VERDICT_KEYS,
    COMMENT_MAX_CHARS,
    VALID_VERDICTS,
    TriageServer,
    _clean_comment,
    _verdict_record,
)


def widget(**kw) -> tuple[str, str]:
    """Render the shared widget.

    ``_verdict_widget`` touches no instance attribute, so ``None`` stands in for
    ``self``; if that ever stops being true this call raises rather than quietly
    testing something else.
    """
    kw.setdefault("flight_raw", "base170707102822.H")
    kw.setdefault("idx", 150422)
    kw.setdefault("current", None)
    return TriageServer._verdict_widget(None, **kw)  # type: ignore[arg-type]


class EveryVerdictHasExactlyOneKey(unittest.TestCase):
    def test_the_two_sets_agree(self) -> None:
        """A verdict with no key would render a button no key reaches."""
        self.assertEqual(set(VALID_VERDICTS), set(_VERDICT_KEYS),
                         "every verdict needs a key and every key a verdict")

    def test_keys_are_unique(self) -> None:
        keys = list(_VERDICT_KEYS.values())
        self.assertEqual(len(keys), len(set(keys)), f"duplicate verdict key in {_VERDICT_KEYS}")

    def test_keys_are_single_lowercase_letters(self) -> None:
        for verdict, key in _VERDICT_KEYS.items():
            with self.subTest(verdict=verdict):
                self.assertRegex(key, r"^[a-z]$")

    def test_navigation_keys_do_not_collide_with_verdict_keys(self) -> None:
        """``n``/``p`` move through a queue, so no verdict may claim them."""
        self.assertFalse({"n", "p"} & set(_VERDICT_KEYS.values()),
                         "a verdict key collides with next/previous")


class TheRenderedWidgetCarriesTheKeys(unittest.TestCase):
    def test_every_button_declares_its_key(self) -> None:
        actions, _ = widget()
        for verdict, key in _VERDICT_KEYS.items():
            with self.subTest(verdict=verdict):
                self.assertIn(f"data-v='{verdict}'", actions)
                self.assertIn(f"data-key='{key}'", actions)

    def test_the_keys_are_shown_to_the_reviewer(self) -> None:
        """An unadvertised shortcut is one nobody uses."""
        actions, _ = widget()
        self.assertIn("keyhint", actions)
        for key in _VERDICT_KEYS.values():
            self.assertIn(f"<kbd>{key}</kbd>", actions)


class TheKeyPathIsTheClickPath(unittest.TestCase):
    """The point of the design: keys must not POST on their own."""

    def test_the_handler_clicks_the_button(self) -> None:
        _, script = widget()
        self.assertIn("keydown", script)
        self.assertIn("b.click()", script)

    def test_there_is_exactly_one_fetch_in_the_script(self) -> None:
        """Two fetches would mean the keyboard had grown its own save path."""
        _, script = widget()
        self.assertEqual(1, len(re.findall(r"fetch\(", script)),
                         "the keyboard must reuse the button's fetch, not add one")


class TheHandlerStaysOutOfTheWay(unittest.TestCase):
    def test_typing_in_a_field_does_not_label(self) -> None:
        _, script = widget()
        self.assertIn("INPUT", script)
        self.assertIn("TEXTAREA", script)
        self.assertIn("isContentEditable", script)

    def test_browser_shortcuts_are_left_alone(self) -> None:
        _, script = widget()
        for mod in ("ctrlKey", "metaKey", "altKey"):
            with self.subTest(modifier=mod):
                self.assertIn(mod, script)

    def test_escape_hands_the_keyboard_back(self) -> None:
        """Otherwise a reviewer who typed a comment must reach for the mouse."""
        _, script = widget()
        self.assertIn("Escape", script)
        self.assertIn("blur()", script)


class TheCommentBox(unittest.TestCase):
    """Author request, 2026-09-16: *"add a box for the user to leave a comment
    if the answer is complex"*. Four verdicts cannot describe every image, and a
    reviewer who cannot say why has to round to the nearest verdict."""

    def test_the_box_is_rendered_and_capped(self) -> None:
        actions, _ = widget()
        self.assertIn("<textarea", actions)
        self.assertIn("id='comment'", actions)
        self.assertIn(f"maxlength='{COMMENT_MAX_CHARS}'", actions)

    def test_the_comment_is_posted_with_the_verdict(self) -> None:
        """One save, not two -- the comment rides the verdict it explains."""
        _, script = widget()
        self.assertIn("comment:", script)
        self.assertEqual(1, len(re.findall(r"fetch\(", script)))

    def test_an_absent_box_does_not_break_the_save(self) -> None:
        """The plain particle page and the queue page share this script, and a
        page without the box must still post rather than throw."""
        _, script = widget()
        self.assertIn("|| {}", script.replace("{{", "{").replace("}}", "}"))


class CommentsAreStoredOnlyWhenTheyExist(unittest.TestCase):
    def test_a_blank_comment_is_nothing(self) -> None:
        self.assertIsNone(_clean_comment("   \n "))
        self.assertIsNone(_clean_comment(None))

    def test_a_comment_is_trimmed_and_capped(self) -> None:
        self.assertEqual("two drops", _clean_comment("  two drops  "))
        self.assertEqual(COMMENT_MAX_CHARS, len(_clean_comment("x" * (COMMENT_MAX_CHARS + 500))))

    def test_a_non_string_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _clean_comment(42)

    def test_the_record_gains_the_key_only_when_commented(self) -> None:
        """A label made without a comment keeps exactly its previous shape."""
        plain = _verdict_record("real", "", "human", reviewer="test")
        self.assertNotIn("comment", plain)
        noted = _verdict_record("real", "", "human", comment="touching pair", reviewer="test")
        self.assertEqual("touching pair", noted["comment"])

    def test_a_comment_is_free_text_not_an_identifier(self) -> None:
        """_LABEL_OK governs ids; prose must not be held to it."""
        prose = "two touching drops; called it real on the larger (50/50, honestly)"
        self.assertEqual(prose, _clean_comment(prose))


if __name__ == "__main__":
    unittest.main()
