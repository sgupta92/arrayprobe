# SPDX-License-Identifier: BSD-3-Clause
"""Lazy access to the v3.1.4 validation engine, which the public distribution omits.

``lazy_module("arrayprobe.imgproc")`` returns a stand-in that imports the real module on first
attribute access and raises :class:`V314EngineAbsent` (an ``ImportError``) when it is not
installed. Attribute writes go to the real module so ``mock.patch.object`` behaves as on it.
"""

from __future__ import annotations

import importlib

# ``engine_present`` lives in the v3.5 engine so the ``uiops`` selector can ask the same
# question without importing this package (engines sit below the selector); re-exported here so
# ``mock.patch("arrayprobe._v314_lazy.engine_present")`` keeps reaching this package's callers.
from arrayprobe_uiops.engine_absence import ABSENT_MESSAGE, V314EngineAbsent, engine_present

__all__ = ["ABSENT_MESSAGE", "V314EngineAbsent", "engine_present", "lazy_module"]


class _Lazy:
    def __init__(self, name: str, message: str = ABSENT_MESSAGE) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_message", message)

    def _load(self):
        name = object.__getattribute__(self, "_name")
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                raise V314EngineAbsent(object.__getattribute__(self, "_message")) from exc
            raise

    def __getattr__(self, attr: str):
        return getattr(self._load(), attr)

    def __setattr__(self, attr: str, value) -> None:
        setattr(self._load(), attr, value)

    def __delattr__(self, attr: str) -> None:
        delattr(self._load(), attr)


def lazy_module(name: str, message: str = ABSENT_MESSAGE) -> _Lazy:
    """A stand-in for module ``name`` that imports it on first use, or raises V314EngineAbsent
    carrying ``message``."""
    return _Lazy(name, message)
