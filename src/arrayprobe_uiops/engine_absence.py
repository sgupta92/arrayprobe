# SPDX-License-Identifier: BSD-3-Clause
"""Whether the earlier translation is installed, and the error raised when it is asked for and
this distribution lacks it.

Here, in the v3.5 engine, because both the earlier translation's lazy loader and the ``uiops``
selector use them, and code both share lives in the v3.5 engine (neither the selector nor the
engines import the earlier translation).
"""

from __future__ import annotations

import importlib.util
import os

#: The module whose presence stands for the earlier translation's engine.
_PROBE = "arrayprobe.reject"


def engine_present() -> bool:
    """True when the earlier translation's engine modules are importable here.

    ``ARRAYPROBE_FORCE_V314_ABSENT=1`` makes this return False even where the modules are
    installed. It is a test hook, so a subprocess can see the surface a distribution without
    the engine shows; users never set it.
    """
    if os.environ.get("ARRAYPROBE_FORCE_V314_ABSENT") == "1":
        return False
    try:
        return importlib.util.find_spec(_PROBE) is not None
    except (ImportError, ValueError):
        return False


ABSENT_MESSAGE = (
    "This package processes data with UIOOPS v3.5 (--engine 3.5; in Python, "
    "arrayprobe.engine(\"3.5\")). The engine named here is not part of this package."
)


class V314EngineAbsent(ImportError):
    """Raised when the earlier translation's module is asked for and this distribution lacks it."""
