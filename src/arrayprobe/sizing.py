# SPDX-License-Identifier: BSD-3-Clause
"""The size-definition registry -- an extensibility seam.

UIOOPS has no such registry.  ``sizeDist.m:882-892`` hard-codes six particle-size
definitions behind a numeric ``d_choice``, and ``imgProc_sm.m:833`` calls
``dropsize`` unconditionally on every particle whatever its phase.  This module
is the seam the plan requires in its place, and it exists for one binding
reason, from the phase-neutrality directive of 2026-08-19:

    ``dropsize`` stays behind the sizing registry, never hard-wired as the
    sizing path.  Same for any liquid-tuned threshold.

``dropsize.m`` is liquid-specific *by construction*: its two lookup tables map a
measured chord to the diameter of the **equivalent-volume sphere of a raindrop**
of that chord, using the Heymsfield-Parrish drop-shape relations.  Applied to an
ice crystal the numbers are not merely imprecise, they answer a question nobody
asked -- "what raindrop would have cast this shadow".  Nothing in the MATLAB
prevents that; the guard below does.

How the guard works
-------------------

Every registered definition declares the phase it is valid for.  A definition
whose ``phase`` is not ``"any"`` cannot be selected through
:func:`universal_size_definition`, which is the accessor a generic pipeline
stage is expected to use -- so reaching :func:`dropsize` requires naming it, and
naming it is a decision that shows up in a diff and in the provenance stamp.

Scope note.  This is deliberately the *seam* and not the full ``d_choice``
machinery: the six numeric definitions live in ``sizeDist.m`` and get registered
in S4, when that file is ported.  Building them here would mean transcribing
``sizeDist.m`` from inside the drop-sizing module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = [
    "SizeDefinition",
    "PhaseValidity",
    "register_size_definition",
    "get_size_definition",
    "available_size_definitions",
    "universal_size_definition",
    "PhaseMismatchError",
]

#: The phases a size definition may claim.  ``"any"`` means the definition makes
#: no assumption about the particle's phase and may serve as a universal path.
PhaseValidity = str

_VALID_PHASES = frozenset({"any", "liquid", "ice"})


class PhaseMismatchError(ValueError):
    """Raised when a phase-restricted definition is asked to serve universally.

    Not a MATLAB behaviour -- MATLAB has no such check.  This is the executable
    form of the phase-neutrality directive, and it can only *refuse* a call; it
    never changes a number.
    """


@dataclass(frozen=True)
class SizeDefinition:
    """One named way of reducing a particle image to a diameter.

    Parameters
    ----------
    key:
        The registry name.  Stamped into output provenance, so it is part of the
        file contract once the framing stage writes it: treat renames as breaking changes.
    func:
        The callable.  Signatures deliberately differ between definitions -- a
        chord-table definition and a min-enclosing-circle definition do not take
        the same arguments -- so the registry carries no signature contract.
    phase:
        ``"any"``, ``"liquid"`` or ``"ice"``.  Anything but ``"any"`` is barred
        from :func:`universal_size_definition`.
    description:
        One line, shown by :func:`available_size_definitions`.
    provenance:
        ``file:line`` in the MATLAB source, or the literature reference.
    outputs:
        The names this definition produces, in order.
    """

    key: str
    func: Callable
    phase: PhaseValidity
    description: str
    provenance: str
    outputs: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.phase not in _VALID_PHASES:
            raise ValueError(
                f"phase must be one of {sorted(_VALID_PHASES)}, got {self.phase!r}"
            )


_REGISTRY: dict[str, SizeDefinition] = {}


def register_size_definition(definition: SizeDefinition) -> SizeDefinition:
    """Add a definition to the registry.  Re-registering a key is an error."""
    if definition.key in _REGISTRY:
        raise ValueError(f"size definition {definition.key!r} is already registered")
    _REGISTRY[definition.key] = definition
    return definition


def get_size_definition(key: str) -> SizeDefinition:
    """Look a definition up by name, phase restrictions and all.

    This is the accessor that *does* reach liquid-only definitions -- naming one
    is an explicit act, which is the whole point.
    """
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"unknown size definition {key!r}; "
            f"registered: {sorted(_REGISTRY)}"
        ) from None


def available_size_definitions() -> dict[str, SizeDefinition]:
    """Every registered definition, keyed by name."""
    return dict(_REGISTRY)


def universal_size_definition(key: str) -> SizeDefinition:
    """Look up a definition for use on particles of unknown phase.

    Raises :class:`PhaseMismatchError` for anything that declared a phase.  A
    generic pipeline stage -- one that does not know what it is looking at --
    calls this, so a liquid-tuned definition cannot become the default path by
    accident.
    """
    definition = get_size_definition(key)
    if definition.phase != "any":
        raise PhaseMismatchError(
            f"size definition {key!r} is valid only for phase "
            f"{definition.phase!r} and cannot be used as a universal sizing "
            f"path (the package's phase-neutrality directive, 2026-08-19). "
            f"Call get_size_definition({key!r}) to use it deliberately."
        )
    return definition
