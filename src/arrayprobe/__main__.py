# SPDX-License-Identifier: BSD-3-Clause
"""``python -m arrayprobe`` -- the same front door as the ``arrayprobe`` console script.

Before 2026-09-15 this file did not exist, so the first command a Python user
types, ``python -m arrayprobe --help``, failed with ``No module named
arrayprobe.__main__`` (the R1 independent review, row 2). It delegates to
:func:`arrayprobe.cli.main` and adds nothing: no argument of its own, no
default, no engine choice. ``tests/test_python_dash_m.py`` asserts that its
``--help`` output equals the console script's.
"""

from __future__ import annotations

import sys

from arrayprobe.cli import main

if __name__ == "__main__":
    sys.exit(main())
