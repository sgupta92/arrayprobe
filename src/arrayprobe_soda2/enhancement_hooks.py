# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""Named hook points through which an optional correction package can substitute one port call.

Port tooling, not IDL: no ``.pro`` counterpart, and it computes nothing. The
"recorded, not applied" gap: ``arrayprobe soda2 run`` could only *record* which SODA-2
corrections a config turned on, because nothing let a correction reach the driver. This module
is that surface, kept on the port's side of the one-way boundary so the port never imports the
corrections -- ``arrayprobe_soda2_enhancements`` imports *this*, never the reverse
(``tests/test_no_enhancement_coupling.py``).

**What a hook point is.** Every port module binds its callees at import time
(``from .label_blobs import label_blobs``), and the driver chain looks each callee up in the
*consumer's* module globals at call time. A :class:`HookPoint` names one such binding --
consumer module, attribute, the call site that reads it -- so substituting that one global
changes exactly that one call and nothing else. No driver line had to change for this: the
bindings already exist, and the table below names them. (The alternative -- an explicit
``hooks.call("label_blobs", ...)`` at each call site -- would edit ``process_2d.py``,
``processbuffer_tail.py`` and four other port modules for no gain in what can be substituted.)

**No default behaviour change, measured rather than asserted.** At rest every consumer binding
*is* (identity, not equality) the port's own function captured when this module was imported;
:func:`pristine` reports it per point and ``tests/test_soda2_enhancement_hooks.py`` asserts it,
and also runs the driver with every point replaced by a counting pass-through to prove each named
binding is really called by the driver and that routing a call through a hook moves no written
value. :func:`overridden` restores the captured originals in ``finally``, so an exception inside
the ``with`` block cannot leave a substitution behind.

**Refusals.** An unknown point name, a point already overridden (no silent stacking: two
corrections on one point must be composed into one callable by whoever owns them), and a point
found not pristine on entry (someone else patched the binding) each raise :class:`HookError`.

Not thread-safe: the bindings are module globals, so a substitution is process-wide for the
duration of the ``with`` block. The SODA-2 driver is single-threaded.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import ModuleType
from typing import Any

__all__ = [
    "HOOK_POINTS",
    "HookError",
    "HookPoint",
    "Reconstruction",
    "active",
    "current",
    "original",
    "overridden",
    "pristine",
    "reconstruction_plan",
]


class HookError(RuntimeError):
    """A substitution was refused: unknown point, already overridden, or not pristine."""


@dataclass(frozen=True)
class HookPoint:
    """One call the driver chain makes through a module-global binding.

    ``consumer`` is the module whose global the call site reads; ``provider`` the module that
    defines the port's own function; ``attribute`` the name in both. ``call_site`` cites the
    port line (and the IDL line it ports) where the binding is read.
    """

    name: str
    consumer: str
    provider: str
    attribute: str
    call_site: str


@dataclass(frozen=True)
class Reconstruction:
    """How a *fresh interpreter* rebuilds one :func:`overridden` substitution from plain data.

    A substitution is a mapping of point name -> **function object**, and a function
    object neither pickles in general nor survives a ``spawn``-started worker's re-import of
    the package -- which is why ``process_2d_parallel.refuse_unsplittable`` refused ``jobs >
    1`` outright whenever anything was substituted. This dataclass is the narrow escape: the
    installer states *how to build the same mapping again from data*, and both halves of it
    are data.

    ``factory`` is ``"module.path:callable"``, importable by name in a fresh interpreter;
    ``payload`` is the one picklable argument it takes. :meth:`build` imports and calls it and
    returns the mapping. The installer is responsible for the factory being a pure function of
    its payload -- ``overridden`` checks that it rebuilds *the same point names*, which catches
    a stale or mismatched plan, and the parallel path's byte-identity test is what proves the
    rebuilt callables are the same corrections.

    A caller that passes an ad-hoc lambda through :func:`overridden` supplies no
    reconstruction, and stays refused. That is the honest residual: the refusal narrows from
    *"any live substitution"* to *"a substitution this process cannot rebuild by name"*.
    """

    factory: str
    payload: Any

    def build(self) -> dict[str, Callable[..., Any]]:
        """Import ``factory`` and call it on ``payload``; the substitution mapping."""
        mod_name, sep, attr = self.factory.partition(":")
        if not sep or not mod_name or not attr:
            raise HookError(f"reconstruction factory {self.factory!r} is not 'module:callable'")
        fn = getattr(_module(mod_name), attr)
        built = fn(self.payload)
        if not isinstance(built, Mapping):
            raise HookError(f"reconstruction factory {self.factory!r} returned "
                            f"{type(built).__name__}, not a mapping of point name -> callable")
        return dict(built)


_PKG = "arrayprobe_soda2"


def _point(name: str, consumer: str, provider: str, call_site: str,
           attribute: str | None = None) -> HookPoint:
    return HookPoint(name=name, consumer=f"{_PKG}.{consumer}", provider=f"{_PKG}.{provider}",
                     attribute=attribute or name, call_site=call_site)


#: Every substitutable binding, keyed by point name. Ordered driver-outermost first.
HOOK_POINTS: dict[str, HookPoint] = {p.name: p for p in (
    _point("spec_index", "buildindex", "spec_index",
           "buildindex.py:28 (soda2_buildindex.pro -> spec_index)"),
    _point("open_pbp_ncdf", "process_2d", "pbp_writer",
           "process_2d.py:520 (soda2_process_2d.pro, ncdfparticlefile)"),
    _point("process_hk", "process_2d", "process_hk",
           "process_2d.py:534 (soda2_process_2d.pro -> process_hk)"),
    _point("process_spec_buffer", "processbuffer_spec", "processbuffer_spec",
           "processbuffer_spec.py:390 (soda2_processbuffer.pro -> spec_processbuffer)"),
    _point("binary_dof", "processbuffer_spec", "binary_dof",
           "processbuffer_spec.py:276 (spec_processbuffer.pro:303, dofreject == 3)"),
    _point("fixstuckbits", "processbuffer_tail", "fixstuckbits",
           "processbuffer_tail.py:196 (soda2_processbuffer.pro, stuckbits)"),
    _point("label_blobs", "processbuffer_tail", "label_blobs",
           "processbuffer_tail.py:253-257 (soda2_processbuffer.pro, the three label_blobs calls)"),
    _point("fillholes", "processbuffer_tail", "fillholes",
           "processbuffer_tail.py:287 (soda2_processbuffer.pro, the line before :716)"),
    _point("poisson_spot_correct", "processbuffer_tail", "poisson_spot_correct",
           "processbuffer_tail.py:289 (soda2_processbuffer.pro:716)"),
    _point("soda2_findsize", "processbuffer_tail", "findsize",
           "processbuffer_tail.py:295 (soda2_processbuffer.pro:719-737)"),
    _point("aspect_ratio", "findsize", "aspect_ratio",
           "findsize.py:247 (soda2_findsize.pro -> aspect_ratio)"),
    _point("axis_and_ratio", "aspect_ratio", "aspect_ratio",
           "aspect_ratio.py:528 (aspect_ratio.pro's axis/ratio block, :66 and :105)"),
)}


def _module(name: str) -> ModuleType:
    return importlib.import_module(name)


#: The port's own function behind every point, captured once, at import of this module --
#: the reference :func:`pristine` compares against by identity. Captured from the provider,
#: so a point whose consumer and provider are the same module still has an independent side.
_ORIGINALS: dict[str, Callable[..., Any]] = {
    name: getattr(_module(p.provider), p.attribute) for name, p in HOOK_POINTS.items()
}

_ACTIVE: dict[str, Callable[..., Any]] = {}

#: The :class:`Reconstruction` the live substitution was installed with, or ``None`` -- either
#: because nothing is substituted or because the installer supplied no way to rebuild it.
_PLAN: Reconstruction | None = None


def _get(name: str) -> HookPoint:
    try:
        return HOOK_POINTS[name]
    except KeyError:
        raise HookError(f"unknown SODA-2 hook point {name!r}; "
                        f"known: {sorted(HOOK_POINTS)}") from None


def original(name: str) -> Callable[..., Any]:
    """The port's own function behind point ``name``."""
    _get(name)
    return _ORIGINALS[name]


def current(name: str) -> Callable[..., Any]:
    """What the call site behind point ``name`` would call right now."""
    p = _get(name)
    return getattr(_module(p.consumer), p.attribute)


def pristine() -> dict[str, bool]:
    """Per point: is the consumer's binding the port's own function (identity)?"""
    return {name: current(name) is _ORIGINALS[name] for name in HOOK_POINTS}


def active() -> dict[str, str]:
    """Points currently overridden -> the replacement's qualified name."""
    return {name: f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', repr(fn))}"
            for name, fn in sorted(_ACTIVE.items())}


def reconstruction_plan() -> Reconstruction | None:
    """The live substitution's :class:`Reconstruction`, or ``None``.

    ``None`` means one of two different things and the caller must treat them the same way:
    nothing is substituted, or something is and its installer gave no way to rebuild it in a
    fresh interpreter. Only a non-``None`` plan licenses carrying the substitution into a
    ``spawn``-started worker (``process_2d_parallel``).
    """
    return _PLAN


@contextmanager
def overridden(replacements: Mapping[str, Callable[..., Any]], *,
               reconstruction: Reconstruction | None = None) -> Iterator[dict[str, str]]:
    """Substitute the named bindings for the duration of the ``with`` block.

    Yields :func:`active`'s view of what was substituted. An empty mapping substitutes nothing
    and is allowed, so a caller need not special-case "every correction off".

    ``reconstruction`` states how a fresh interpreter rebuilds ``replacements`` from
    plain data; it is **checked here, not trusted** -- the factory is imported and called and
    must produce the same point names, so a plan that has drifted from what is being installed
    fails at install time rather than in a worker. Omitted, the substitution is process-local
    and ``jobs > 1`` stays refused.
    """
    for name in replacements:
        _get(name)
        if name in _ACTIVE:
            raise HookError(f"hook point {name!r} is already overridden by {active()[name]}; "
                            "compose the corrections into one callable instead of stacking")
        if current(name) is not _ORIGINALS[name]:
            raise HookError(f"hook point {name!r} is not pristine: "
                            f"{HOOK_POINTS[name].consumer}.{HOOK_POINTS[name].attribute} was "
                            "rebound outside enhancement_hooks")
        if not callable(replacements[name]):
            raise HookError(f"replacement for hook point {name!r} is not callable")
    if reconstruction is not None:
        rebuilt = reconstruction.build()
        if sorted(rebuilt) != sorted(replacements):
            raise HookError(
                f"reconstruction {reconstruction.factory!r} rebuilds hook points "
                f"{sorted(rebuilt)} but {sorted(replacements)} are being installed; a plan "
                "that does not reproduce the substitution would carry a DIFFERENT set of "
                "corrections into a worker process")
        not_callable = sorted(n for n, fn in rebuilt.items() if not callable(fn))
        if not_callable:
            raise HookError(f"reconstruction {reconstruction.factory!r} rebuilt "
                            f"{not_callable} as non-callables")
    global _PLAN
    # Two `overridden` blocks on disjoint points can nest. Neither plan then describes the
    # whole live substitution, so the combined state is declared unrebuildable and `jobs > 1`
    # goes back to being refused -- the conservative direction.
    previous_plan, previous_active = _PLAN, bool(_ACTIVE)
    installed: list[str] = []
    try:
        for name, fn in replacements.items():
            p = HOOK_POINTS[name]
            setattr(_module(p.consumer), p.attribute, fn)
            _ACTIVE[name] = fn
            installed.append(name)
        if installed:
            _PLAN = None if previous_active else reconstruction
        yield active()
    finally:
        for name in reversed(installed):
            p = HOOK_POINTS[name]
            setattr(_module(p.consumer), p.attribute, _ORIGINALS[name])
            del _ACTIVE[name]
        if installed:
            _PLAN = previous_plan
