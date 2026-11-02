# SPDX-License-Identifier: BSD-3-Clause
"""Alias of :mod:`arrayprobe_uiops.provenance`, the one ``.call`` sidecar parser.

The module moved to the v3.5 engine on 2026-09-30 (the rule that code both engines share lives
there, so deleting this package breaks nothing else). This file keeps ``from arrayprobe import
provenance`` working for the v3.1.4 callers and computes nothing.

The star import gives static readers (mypy, ruff) the public names; the ``sys.modules`` line
then makes ``arrayprobe.provenance`` the *same module object*, so a patch, ``__file__`` and the
private helpers all resolve to the real module rather than to a copy of its namespace.
"""

from __future__ import annotations

import sys

from arrayprobe_uiops import provenance as _impl
from arrayprobe_uiops.provenance import *  # noqa: F401,F403
from arrayprobe_uiops.provenance import __all__  # noqa: F401

sys.modules[__name__] = _impl
