# SPDX-License-Identifier: BSD-3-Clause
"""Shared assertions for the queue shell scripts that split a code root from a data root.

``cold_v35_runs.sh`` and the 2D-S ladder-fix script both set ``DATA=<repository root>`` and
``CODE=${CODE:-<same root>}``, import the packages from ``$CODE`` and refuse (exit 3) to start
when the import does not resolve there. The checks are the same for both, so they live here;
each test module adds the assertion that is about its own script. The root is matched by shape
(an absolute path ending in ``/Projects/arrayprobe``), never spelt, so no home path appears in a
test.
"""

from __future__ import annotations

import re
import unittest

_DATA = re.compile(r"^DATA=(\S+/Projects/arrayprobe)$", re.M)
_CODE = re.compile(r"^CODE=\$\{CODE:-(\S+?)\}$", re.M)
LAUNCHER = "scripts/launch_detached.sh"


def check_code_and_data_roots(tc: unittest.TestCase, text: str) -> None:
    """Assert ``text`` splits CODE from DATA, defaults both to one root, and checks the import."""
    data = _DATA.search(text)
    tc.assertIsNotNone(data, "no DATA=<root>/Projects/arrayprobe line")
    code = _CODE.search(text)
    tc.assertIsNotNone(code, "no CODE=${CODE:-<root>} line")
    assert data is not None and code is not None  # for the type checker
    tc.assertEqual(data.group(1), code.group(1), "CODE must default to the DATA root")
    tc.assertIn("P=$CODE/python_port\n", text)
    tc.assertNotIn("$REPO", text)
    tc.assertIn(
        'export PYTHONPATH="$CODE/python_port/src;$CODE/enhancements_uiops/src;'
        '$CODE/enhancements_soda2/src;$CODE/python_port"', text)
    tc.assertIn(
        '-c "import arrayprobe, arrayprobe_uiops; '
        'print(arrayprobe.__file__, arrayprobe_uiops.__file__)"', text)
    tc.assertIn("exit 3", text)
    tc.assertIn("does not resolve under CODE", text)
    # the guard sits before the first run of the driver
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    first_run = next(i for i, ln in enumerate(lines) if "scripts/run_flight.py" in ln)
    guard = next(i for i, ln in enumerate(lines) if ln.startswith("export PYTHONPATH="))
    tc.assertLess(guard, first_run)
    # the launch comment names CODE
    tc.assertIn(f"CODE=<fixed-commit worktree> sh {LAUNCHER}", text)
