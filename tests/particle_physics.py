# SPDX-License-Identifier: BSD-3-Clause
"""Compatibility shim: particle_physics moved into the arrayprobe package.

Kept so the Phase-1 tests (and any external caller) keep working unchanged
after the S0 restructure. New code should import from ``arrayprobe.particle_physics``.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "src"))

from arrayprobe.particle_physics import single_area, single_mass, single_vt  # noqa: E402,F401

__all__ = ["single_area", "single_mass", "single_vt"]
