# SPDX-License-Identifier: BSD-3-Clause
"""A rerun of ``scripts/v35_ab_summary.py --write`` must not overwrite a superseded entry.

**The incident this guards against.** The 2026-09-15 change fixed the wrong-sign
``outoffocus.py`` direction and marked the old (multiply-direction) ``v35_outoffocus`` figures
``superseded`` in ``docs/measurements.json``, keeping the old numbers as the record of what was
measured under the bug. ``v35_ab_summary.py``'s ``main`` rewrites that key wholesale
(``registry.update(results)``) on every ``--write`` run. Without a guard, the very next rerun --
which now measures the corrected direction -- would silently drop the ``superseded`` marker, the
``superseded_reason`` and the old figures, with no trace that anything had ever been wrong. A later change
added ``archive_superseded_before_overwrite`` to stop that: before a key already carrying
``"superseded"`` is replaced, its whole old entry is copied to ``<key>_superseded_<date>``.

This test exercises the archiving function directly against a small in-memory registry -- it does
not run the full measurement pipeline (that needs a decoded v3.5 dense reference and is exercised
elsewhere).
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
# The tool loads the repository's scripts/make_demo_reference.py at import; an unpacked sdist
# has no repository around it, so the module reports itself skipped there.
if not (_TOOLS.parents[1] / "scripts" / "make_demo_reference.py").is_file():
    raise unittest.SkipTest("needs the repository's scripts/, which the sdist does not carry")
sys.path.insert(0, str(_TOOLS))

from v35_ab_summary import archive_superseded_before_overwrite  # noqa: E402


class ArchivesTheSupersededEntryBeforeOverwrite(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "v35_outoffocus": {
                "engine": "3.5",
                "n_changed": 40,
                "median_size_factor_among_changed": 1.897,
                "superseded": "2026-09-15",
                "superseded_reason": "measured with the multiply, the wrong direction",
            },
            "v35_hole_edge_swap": {
                "engine": "3.5",
                "n_swapped": 40,
            },
        }
        self.original = copy.deepcopy(self.registry)

    def test_a_superseded_entry_is_copied_to_an_archive_key(self):
        archive_key = archive_superseded_before_overwrite(self.registry, "v35_outoffocus")
        self.assertEqual(archive_key, "v35_outoffocus_superseded_2026-09-15")
        self.assertIn(archive_key, self.registry)
        self.assertEqual(self.registry[archive_key], self.original["v35_outoffocus"])

    def test_the_live_entry_still_exists_until_the_caller_overwrites_it(self):
        # archive_superseded_before_overwrite only copies -- it never deletes the live key.
        # The caller (main) then does registry.update(results), which replaces it.
        archive_superseded_before_overwrite(self.registry, "v35_outoffocus")
        self.assertEqual(self.registry["v35_outoffocus"], self.original["v35_outoffocus"])

    def test_a_non_superseded_entry_is_left_alone(self):
        archive_key = archive_superseded_before_overwrite(self.registry, "v35_hole_edge_swap")
        self.assertIsNone(archive_key)
        self.assertEqual(self.registry, self.original)

    def test_a_missing_key_is_a_no_op(self):
        archive_key = archive_superseded_before_overwrite(self.registry, "v35_does_not_exist")
        self.assertIsNone(archive_key)
        self.assertEqual(self.registry, self.original)

    def test_a_second_rerun_does_not_clobber_the_first_archive(self):
        # Simulate main(): archive, then overwrite with a fresh (also-superseded, hypothetically)
        # measurement, twice in a row -- the second archive must not stomp on the first.
        archive_superseded_before_overwrite(self.registry, "v35_outoffocus")
        self.registry["v35_outoffocus"] = {
            "engine": "3.5",
            "n_changed": 0,
            "superseded": "2026-09-15",
            "superseded_reason": "a second, unrelated wrong measurement, for this test only",
        }
        second_archive_key = archive_superseded_before_overwrite(self.registry, "v35_outoffocus")
        self.assertEqual(second_archive_key, "v35_outoffocus_superseded_2026-09-15_2")
        self.assertIn("v35_outoffocus_superseded_2026-09-15", self.registry)
        self.assertIn("v35_outoffocus_superseded_2026-09-15_2", self.registry)

    def test_the_real_registry_entry_the_guard_was_built_for_is_still_marked_superseded(self):
        # docs/measurements.json is the actual file this tool writes. If a rerun has already
        # happened without the guard, this catches it having silently dropped the marker.
        import json
        registry_path = Path(__file__).resolve().parents[1] / "docs" / "measurements.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        entry = registry.get("v35_outoffocus", {})
        self.assertIn("superseded", entry,
                      "v35_outoffocus lost its superseded marker -- a rerun of "
                      "v35_ab_summary.py may have overwritten it without archiving")


if __name__ == "__main__":
    unittest.main()
