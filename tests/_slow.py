# SPDX-License-Identifier: BSD-3-Clause
"""The ``ARRAYPROBE_SLOW`` gate (2026-09-14).

``@slow`` marks a test or class whose *cost is its own subject* -- a stall
timer that must actually outlast a stall, a cold-start-interpreter watchdog
test, a subprocess-driven example/notebook/paper build -- and which the
default ``unittest discover -s tests -p "test_*.py"`` run therefore skips.
Set ``ARRAYPROBE_SLOW=1`` to run the gated set too:

    ARRAYPROBE_SLOW=1 .venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"

Never gate a preserved-bug test or an Octave/GDL oracle test (the
Fidelity doctrine) -- those are the fidelity claim, and this module carries
no logic to stop someone from decorating one, so that rule stays a matter of
review, not of this file. What *is* mechanically checked --
``tests/test_slow_gate_is_exercised.py`` -- is that the gated set still runs
somewhere (CI's ``ARRAYPROBE_SLOW: "1"``) and that every ``@slow`` use decorates
a test the loader can actually collect, so a rename that silently orphaned a
gate would fail the suite rather than just quietly running zero gated tests.
"""

from __future__ import annotations

import os
import unittest

#: True exactly when ARRAYPROBE_SLOW=1 is set -- read once at import time so
#: `tests/test_slow_gate_is_exercised.py` can flip it via monkeypatching
#: os.environ before a fresh import in a subprocess, rather than needing this
#: module to re-read the environment on every decoration.
SLOW_ENABLED = os.environ.get("ARRAYPROBE_SLOW") == "1"

slow = unittest.skipUnless(
    SLOW_ENABLED,
    "cost is this test's own subject; set ARRAYPROBE_SLOW=1 to run it",
)
