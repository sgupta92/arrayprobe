# SPDX-License-Identifier: BSD-3-Clause
"""Alias of :mod:`arrayprobe_uiops.ncio`, the MATLAB ``netcdf.*`` layer both engines write through.

The module moved to the v3.5 engine on 2026-10-03 (code both engines share lives
there, so deleting this package breaks nothing else; the author approved the netCDF layer joining
the shared set although it imports netCDF4). This file keeps ``from arrayprobe import ncio``
working for the v3.1.4 callers and computes nothing.

The star import gives static readers (mypy, ruff) the public names; the ``sys.modules`` line
then makes ``arrayprobe.ncio`` the *same module object*, so a patch, ``__file__`` and the
private helpers (``_quiet_netcdf4_setitem``, ``_c_order``) all resolve to the real module rather
than to a copy of its namespace.
"""

from __future__ import annotations

import sys

from arrayprobe_uiops import ncio as _impl
from arrayprobe_uiops.ncio import *  # noqa: F401,F403
from arrayprobe_uiops.ncio import __all__  # noqa: F401
from arrayprobe_uiops.ncio import (  # noqa: F401  (private, for attributed_export)
    _quiet_netcdf4_setitem as _quiet_netcdf4_setitem,
)

sys.modules[__name__] = _impl
