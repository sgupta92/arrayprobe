# SPDX-License-Identifier: BSD-3-Clause
"""Liquid water content from a particle size distribution.

Ported from: lwc_calc.m (UIOOPS v3.1.4)

``lwc_calc.m`` is byte-identical in v3.1.4 and v3.5, so the one translation lives in the v3.5
engine, ``arrayprobe_uiops.lwc``: code both engines share sits there and the v3.1.4 package
imports it, never the reverse. This module re-exports it **lazily** (PEP 562 ``__getattr__``),
so importing ``arrayprobe.lwc`` -- and through it ``arrayprobe.sizedist`` and
``arrayprobe.cli`` -- loads no v3.5 engine module; the first access to ``lwc_calc`` does.
Callers of ``arrayprobe.lwc.lwc_calc`` get the same function object as
``arrayprobe_uiops.lwc.lwc_calc``, so the computed bytes cannot differ between the engines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

#: Declared so the public surface is explicit rather than whatever happens not to
#: start with an underscore. The Phase-1 shims at ``<name>.py`` in the original flat layout import
#: these names directly, CONSTANTS INCLUDED -- omitting a constant here would not
#: break them, but omitting one from a shim does, which is why they are listed.
#: Every name here is re-exported from ``arrayprobe_uiops.lwc`` on first access.
__all__ = [
    "lwc_calc",
]

if TYPE_CHECKING:  # pragma: no cover - static typing only, never executed
    from arrayprobe_uiops.lwc import lwc_calc as lwc_calc


def __getattr__(name: str) -> Any:
    """Resolve a public name from ``arrayprobe_uiops.lwc`` on first access, and cache it."""
    if name in __all__:
        from arrayprobe_uiops import lwc as _home

        value = getattr(_home, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
