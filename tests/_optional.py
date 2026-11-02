# SPDX-License-Identifier: BSD-3-Clause
"""Whether an optional companion package imports in a fresh interpreter.

The port's suite runs with or without the enhancement packages installed (CI's port job installs
neither), so a test that needs one -- directly, or through a subprocess it launches -- skips when
it is absent. The question is put to a fresh interpreter, never answered in this process: on CI
(2026-10-01) the suite's own process could import ``arrayprobe_enhancements`` and
``arrayprobe_soda2_enhancements`` after sibling test modules had changed ``sys.path``, while the
driver subprocesses those tests launched could not, so five tests failed where they should have
skipped. A fresh interpreter sees what the subprocesses see, and what a user's install sees.
"""
from __future__ import annotations

import functools
import subprocess
import sys
import unittest

#: The companion distributions the port never requires.
OPTIONAL_PACKAGES = ("arrayprobe_enhancements", "arrayprobe_soda2_enhancements")


@functools.cache
def importable(name: str) -> bool:
    """True if ``import <name>`` succeeds in a fresh ``sys.executable`` (this environment)."""
    done = subprocess.run([sys.executable, "-c", f"import {name}"],
                          capture_output=True, timeout=120)
    return done.returncode == 0


def requires(name: str):
    """``unittest.skipUnless`` on :func:`importable`, with the reason a reader needs."""
    return unittest.skipUnless(importable(name),
                               f"{name} is not installed in this environment: the port runs "
                               "without it, and this test exercises it")


def optional_package_of(target: str | None) -> str | None:
    """The optional package a dotted target (``pkg.module:func``) lives in, else ``None``."""
    top = (target or "").split(":")[0].split(".")[0]
    return top if top in OPTIONAL_PACKAGES else None
