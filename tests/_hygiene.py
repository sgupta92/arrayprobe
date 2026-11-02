# SPDX-License-Identifier: BSD-3-Clause
"""The ``ARRAYPROBE_HYGIENE`` gate (added 2026-09-25).

``@hygiene`` marks a test class whose subject is the *documents*, not the code:
count propagation, the paper's text and build, the instruction ledger and rules,
STATUS/plan/changelog consistency, docs-site and link checks. None of these
computes a number the port writes, so the default local run
(``unittest discover -s tests -p "test_*.py"``) skips them and the edit-test loop
stays short. Set ``ARRAYPROBE_HYGIENE=1`` to run them too; CI's "Run the suite"
and "Coverage" steps set it, and so does the close-out full-suite run:

    ARRAYPROBE_SLOW=1 ARRAYPROBE_HYGIENE=1 .venv/Scripts/python.exe \
        -m unittest discover -s tests -p "test_*.py"

It is a class decorator, never a ``setUpModule`` skip: a ``SkipTest`` raised from a
module or class fixture drops the tests from the count instead of reporting them as
skipped (``tests/test_class_level_skips_are_visible.py``), while ``skipUnless`` on the
class is counted per method.

Never gate an oracle, golden, preserved-bug or byte-identity test -- those are the
fidelity claim and run on every run. ``tests/test_hygiene_gate_is_exercised.py``
enforces the registry both ways, refuses fidelity-named modules, and checks CI and
the project guidance, so the gated set cannot silently stop running anywhere.
"""

from __future__ import annotations

import os
import unittest

#: True exactly when ARRAYPROBE_HYGIENE=1 is set, read once at import time.
HYGIENE_ENABLED = os.environ.get("ARRAYPROBE_HYGIENE") == "1"

hygiene = unittest.skipUnless(
    HYGIENE_ENABLED,
    "document/repository-consistency guard; set ARRAYPROBE_HYGIENE=1 to run it "
    "(CI and the close-out run do)",
)
