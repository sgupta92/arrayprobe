# SPDX-License-Identifier: BSD-3-Clause
import sys as _sys
import typing as _typing

from arrayprobe_uiops import intarr as _impl

# Static view for type checkers only: the alias below replaces this module at run time,
# so mypy would otherwise see an empty module. No run-time effect.
if _typing.TYPE_CHECKING:
    from arrayprobe_uiops.intarr import *  # noqa: F403

_sys.modules[__name__] = _impl
