# SPDX-License-Identifier: BSD-3-Clause
"""Compatibility shim: time_convert moved into the arrayprobe package.

Kept so the Phase-1 tests (and any external caller) keep working unchanged
after the S0 restructure. New code should import from ``arrayprobe.time_convert``.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "src"))

from arrayprobe.time_convert import hhmmss_to_insec, insec_to_hhmmss  # noqa: E402,F401

__all__ = ["hhmmss_to_insec", "insec_to_hhmmss"]
