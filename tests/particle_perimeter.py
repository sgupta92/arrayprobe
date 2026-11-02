# SPDX-License-Identifier: BSD-3-Clause
"""Compatibility shim: particle_perimeter moved into the arrayprobe package.

Kept so the Phase-1 tests (and any external caller) keep working unchanged
after the S0 restructure. New code should import from ``arrayprobe.particle_perimeter``.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "src"))

from arrayprobe.particle_perimeter import (  # noqa: E402,F401
    BACKGROUND,
    SHADOWED,
    particle_perimeter,
    particle_perimeter_from_mask,
    particle_perimeter_setbased,
)

__all__ = [
    "BACKGROUND",
    "SHADOWED",
    "particle_perimeter",
    "particle_perimeter_from_mask",
    "particle_perimeter_setbased",
]
