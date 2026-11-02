# SPDX-License-Identifier: BSD-3-Clause
"""``tests/_upstream.cited_path``: reading a cited upstream line goes through the tree gate.

Three test helpers read ``UIOPS-v3.5/...`` files from the repository root directly. In a checkout
without the upstream trees (the public repository, where they do not ship) the read raised
``FileNotFoundError`` instead of skipping by name. Found by the built public tree's suite,
2026-10-12.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _upstream
from tests._repo import repo_only

REL = "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"


class CitedPathGoesThroughTheGate(unittest.TestCase):
    @repo_only
    def test_an_absent_tree_skips_by_name(self):
        with tempfile.TemporaryDirectory() as empty, \
                mock.patch.dict(os.environ, {"ARRAYPROBE_UIOPS35_TREE": empty,
                                             _upstream.REQUIRE_ENV: ""}):
            with self.assertRaises(unittest.SkipTest) as cm:
                _upstream.cited_path(REL)
        self.assertIn("UPSTREAM_TREE_ABSENT: uiops35", str(cm.exception))

    @repo_only
    def test_a_present_tree_resolves_through_the_override(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "joefinlon-UIOPS-039be82" / "sizeDist.m"
            target.parent.mkdir()
            target.write_text("x\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"ARRAYPROBE_UIOPS35_TREE": root}):
                self.assertEqual(_upstream.cited_path(REL), target)

    def test_a_path_under_no_upstream_tree_is_repository_relative(self):
        self.assertEqual(_upstream.cited_path("tests/data/x.json"),
                         _upstream.ROOT / "tests" / "data" / "x.json")


if __name__ == "__main__":
    unittest.main()
