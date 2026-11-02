# SPDX-License-Identifier: BSD-3-Clause
"""No test module calls ``_upstream.require`` at import time.

A ``unittest.SkipTest`` raised while a module imports is reported as a skip by ``discover`` but
crashes ``python -m unittest tests.<module>``: the loader catches only ImportError. Raised from
``setUpModule`` it is a skip under both. 36 modules carried the import-time call until the
release suite's skip review found the crash in a tree without the upstream sources.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
_AT_IMPORT = re.compile(r"^_upstream\.require\(", re.M)


def offenders(text: str) -> int:
    """How many column-0 (import-time) ``_upstream.require`` calls a module source holds."""
    return len(_AT_IMPORT.findall(text))


class UpstreamSkipIsNotAtImport(unittest.TestCase):
    def test_no_module_requires_an_upstream_tree_at_import(self):
        bad = [p.name for p in sorted(TESTS.glob("test_*.py"))
               if offenders(p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [], "move the call into setUpModule: " + ", ".join(bad))

    def test_the_check_fires(self):
        self.assertEqual(offenders('import x\n_upstream.require("uiops35")\n'), 1)
        self.assertEqual(offenders('def setUpModule():\n    _upstream.require("uiops35")\n'), 0)

    def test_the_sweep_sees_the_modules_that_call_it(self):
        # A sweep that reads no caller passes vacuously.
        callers = [p for p in TESTS.glob("test_*.py")
                   if "_upstream.require(" in p.read_text(encoding="utf-8")]
        self.assertGreaterEqual(len(callers), 10)


if __name__ == "__main__":
    unittest.main()
