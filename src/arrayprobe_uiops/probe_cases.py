# SPDX-License-Identifier: BSD-3-Clause
"""Registered probe cases: a bin ladder v3.5's own ``switch`` does not have.

**Why this exists.** ``sizeDist.m``'s ``switch projectname`` / ``switch probename``
is a closed set of literal cases.  A campaign upstream never wrote a case for
falls to ``otherwise``, and on v3.5 the ``otherwise``/``'2DS'`` case carries the
**HVPS** ladder (``UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m:497-505``:
28 bins, first edge 0.2 mm, headed by the comment ``% For the HVPS``), with the
10 um ladder commented out below it.  v3.1.4's same block
(``UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/sizeDist.m:365-376``) has the comment
markers the other way round.  A 2D-S resolves 10-1280 um, so on v3.5 an
unlisted campaign's 2D-S size distribution is empty: measured on ARM ACE-ENA
2017-07-07, summed ``Size Distribution cm-3`` is **11168.6** on v3.1.4 against
**0.0100** on v3.5, same raw bytes.


**That behaviour is faithful and is not fixed here.**  :data:`V35_TABLES` and
:data:`V314_TABLES` are untouched; ``probe_defaults()`` keeps returning v3.5's
28-bin table for ``(unlisted campaign, '2DS')`` for ever.  What this module adds
is the thing upstream's switch has no room for: a **named** case a run may
select *instead of* the switch, so this package can process a campaign upstream
never wrote a case for.

**Opt-in, default-off.**  A run that names no case never touches this registry:
:func:`arrayprobe_uiops.sizedist.run` resolves through ``probe_defaults()``
exactly as before, bit for bit
(``tests/test_v35_probe_cases.py::TestDefaultIsBitIdentical``).

**Selection is by name; description is from Python**.  A bin
ladder is a set of constants, exactly like a threshold, so a config file or a
``--probe-case`` argument may *select* a registered case and may never describe
one.  Registration is a Python call, the same rule and the same mechanism as
:func:`arrayprobe.profiles.register_profile`.

**Every field must cite a vendored file:line.**  :class:`ProbeCase` refuses to
be built unless :data:`ProbeDefaults`' every field is accounted for in
``citations`` -- see :class:`UncitedProbeCaseField`.  A constant nobody can cite
is an invented constant, which this project's fidelity doctrine forbids
(never invent a fact to fill a gap).

**A registered name does not survive a re-exec.**  A ``--jobs`` worker
(``scripts/run_flight.py``) is a *fresh* subprocess that re-imports this module
and starts with an empty registry, so ``--probe-case NAME`` alone resolves
nowhere there -- the identical gap
a profile registered through ``PROFILE_MODULE`` has, and
it takes the identical answer: a module whose import registers the case
(:mod:`arrayprobe_uiops.register_arm_ena_2ds`), named by
``--probe-case-module`` and forwarded to every worker.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from types import MappingProxyType

from arrayprobe_uiops.sizedist_tables import OTHERWISE, V35_TABLES, ProbeDefaults

__all__ = [
    "ProbeCase",
    "UnknownProbeCase",
    "UncitedProbeCaseField",
    "DuplicateProbeCase",
    "PROBE_CASES",
    "register_probe_case",
    "resolve_probe_case",
    "register_v35_2ds_ladder_fix", "resolve_shipped_probe_case",
    "V35_2DS_LADDER_FIX",
    "REQUIRED_IA_THRESH_TYPE",
    "require_ia_thresh_type",
    "ACCEPTED_IA_THRESH_TYPES",
    "accept_ia_thresh_types",
]


class UnknownProbeCase(LookupError):
    """``--probe-case NAME`` named a case nothing has registered in this process."""


class UncitedProbeCaseField(ValueError):
    """A :class:`ProbeCase` left one of :class:`ProbeDefaults`' fields uncited.

    Not a style rule: the whole warrant for a case that upstream's ``switch``
    does not contain is that every constant in it was **read out of a vendored
    tree**, not chosen.  An uncited field is an invented one.
    """


class DuplicateProbeCase(ValueError):
    """Two different cases registered under one name.

    Re-registering the *same* case is a no-op -- importing a registration
    module twice must not explode -- but a second, different case under a name
    already taken would make ``--probe-case NAME`` mean whichever import ran
    last, which is the silent-wrong-output shape this project treats as serious.
    """


@dataclasses.dataclass(frozen=True)
class ProbeCase:
    """A named ``(num_bins, kk, and the eleven constants beside them)`` bundle.

    ``defaults`` is a plain :class:`ProbeDefaults` -- the same record
    ``probe_defaults()`` returns -- so a case reaches ``sizeDist``'s body
    through the identical path a stock case does and changes no code beyond the
    lookup.
    """

    name: str
    description: str
    defaults: ProbeDefaults
    citations: Mapping[str, str]

    def __post_init__(self) -> None:
        fields = set(ProbeDefaults.__dataclass_fields__)
        missing = sorted(fields - set(self.citations))
        if missing:
            raise UncitedProbeCaseField(
                f"probe case {self.name!r} cites no vendored file:line for "
                f"{missing}; every field of ProbeDefaults must name the line it "
                "was read from (arrayprobe_uiops/probe_cases.py's module docstring)"
            )
        extra = sorted(set(self.citations) - fields)
        if extra:
            raise UncitedProbeCaseField(
                f"probe case {self.name!r} cites {extra}, which is not a field of "
                "ProbeDefaults"
            )
        object.__setattr__(self, "citations", MappingProxyType(dict(self.citations)))


_REGISTRY: dict[str, ProbeCase] = {}

#: Read-only view of what this process has registered.  Empty in a fresh
#: process -- see the module docstring on ``--probe-case-module``.
PROBE_CASES: Mapping[str, ProbeCase] = MappingProxyType(_REGISTRY)


def register_probe_case(case: ProbeCase) -> ProbeCase:
    """Add ``case`` to this process's registry and return it.

    Idempotent for an identical case (so a registration module may be imported
    twice); raises :class:`DuplicateProbeCase` for a different one.
    """
    existing = _REGISTRY.get(case.name)
    if existing is not None and (
        existing.defaults != case.defaults or existing.description != case.description
    ):
        raise DuplicateProbeCase(
            f"probe case {case.name!r} is already registered with different "
            "contents; pick another name rather than shadowing it"
        )
    _REGISTRY[case.name] = case
    return case


def resolve_probe_case(name: str) -> ProbeCase:
    """The registered case ``name``, or :class:`UnknownProbeCase`."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownProbeCase(
            f"no probe case {name!r} is registered in this process. Registered: "
            f"{sorted(_REGISTRY)}. A case is registered by importing the module "
            "that calls register_probe_case() -- a name alone does not survive a "
            "fresh process (arrayprobe_uiops/probe_cases.py's module docstring)."
        ) from None


# ---------------------------------------------------------------------------
# The general 2D-S ladder: v3.5's otherwise/'2DS' constants on v3.1.4's ladder.
# ---------------------------------------------------------------------------

_V314_SIZEDIST = "UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/sizeDist.m"
_V35_SIZEDIST = "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"

#: Where every field of the 2D-S ladder case's defaults was read from -- shared by
#: :data:`V35_2DS_LADDER_FIX` and :data:`ARM_ENA_2DS`, whose defaults are identical.
#:
#: The case is v3.5's own ``otherwise``/``'2DS'`` record with ``num_bins`` and
#: ``bins`` taken from v3.1.4's same block -- the only two fields on which the
#: two releases' ``otherwise``/``'2DS'`` cases differ at all (measured:
#: ``tests/test_v35_probe_cases.py::TestArmEnaCase``,
#: ``test_it_differs_from_stock_v35_in_exactly_two_fields``).
#: So eleven fields cite v3.5, and the two that name the ladder cite v3.1.4.
_V35_2DS_LADDER_CITATIONS = {
    "num_diodes": f"{_V35_SIZEDIST}:499 -- num_diodes = 128",
    "diodesize": f"{_V35_SIZEDIST}:500 -- diodesize = .010",
    "armdst": f"{_V35_SIZEDIST}:501 -- armdst = 63.",
    "num_bins": f"{_V314_SIZEDIST}:374 -- num_bins = 128 (v3.5's :502 is the HVPS 28)",
    "bins": (
        f"{_V314_SIZEDIST}:376 -- kk = diodesize/2:diodesize:(num_bins+0.6)*diodesize "
        f"(the identical line is commented out at {_V35_SIZEDIST}:507)"
    ),
    "probetype": f"{_V35_SIZEDIST}:508 -- probetype = 2",
    "tasMax": f"{_V35_SIZEDIST}:509 -- tasMax = 170",
    "applyIntArrThresh": f"{_V35_SIZEDIST}:514 -- applyIntArrThresh = 0",
    "defaultIntArrThresh": f"{_V35_SIZEDIST}:515 -- defaultIntArrThresh = 4e-6",
    "reaccptShatrs": f"{_V35_SIZEDIST}:516 -- reaccptShatrs = 0",
    "reaccptD": f"{_V35_SIZEDIST}:517 -- reaccptD = 0.5",
    "reaccptMaxIA": f"{_V35_SIZEDIST}:518 -- reaccptMaxIA = 1e-6",
    "intar_threshold_defaulted": (
        f"{_V35_SIZEDIST}:520 -- intar_threshold = ones(size(tas_time))*defaultIntArrThresh"
    ),
    "calls_getPECANparams": (
        f"{_V35_SIZEDIST}:497-520 -- the otherwise/'2DS' case calls getPECANparams() nowhere"
    ),
}


def _v35_2ds_ladder_defaults() -> ProbeDefaults:
    """v3.5's own ``otherwise``/``'2DS'`` record with ``num_bins`` and ``bins`` from v3.1.4's.

    Read from the two vendored tables only (:data:`_V35_2DS_LADDER_CITATIONS`), so the general
    correction depends on no campaign case."""
    from arrayprobe_uiops.sizedist_tables import V314_TABLES

    stock = V35_TABLES[OTHERWISE]["2DS"]
    v314 = V314_TABLES[OTHERWISE]["2DS"]
    return dataclasses.replace(stock, num_bins=v314.num_bins, bins=v314.bins)


#: ``v35-2ds-ladder-fix``: the swapped-bin-table correction (default on). Built by
#: :func:`register_v35_2ds_ladder_fix`; ``None`` until then.
V35_2DS_LADDER_FIX: ProbeCase | None = None


def register_v35_2ds_ladder_fix() -> ProbeCase:
    """Build, register and return ``v35-2ds-ladder-fix`` (swapped-bin-table fix).

    v3.5's ``otherwise``/``'2DS'`` case with the 2D-S 128-bin ladder that upstream left
    commented out at ``sizeDist.m:506-507`` in place of the HVPS table at ``:502-505``: v3.5's
    own constants and v3.1.4's ``:374``/``:376`` ladder, which is the commented-out line, built
    directly from the two vendored tables (:func:`_v35_2ds_ladder_defaults`). It registers no
    other case. A campaign case built on the same record sizes identically to the batch
    driver's default-on bin-table correction; this is a separate name so a stamp names the
    correction, not a campaign."""
    global V35_2DS_LADDER_FIX
    V35_2DS_LADDER_FIX = register_probe_case(
        ProbeCase(
            name="v35-2ds-ladder-fix",
            description=(
                "Swapped-bin-table correction: a 2D-S on v3.5's otherwise branch is sized "
                "on the 2D-S 128-bin "
                "10 um ladder upstream commented out at sizeDist.m:506-507, not the HVPS 28-bin "
                "0.2-30 mm table at :502-505. Default on in the batch driver on engine 3.5."
            ),
            defaults=_v35_2ds_ladder_defaults(),
            citations=dict(_V35_2DS_LADDER_CITATIONS),
        )
    )
    return V35_2DS_LADDER_FIX


def resolve_shipped_probe_case(name: str) -> ProbeCase:
    """:func:`resolve_probe_case`, registering a case every install carries on first use.

    ``v35-2ds-ladder-fix`` ships with the package, so a name quoted anywhere (``--probe-case``,
    a run TOML's ``probe_case``, ``tune settings``) resolves in a fresh process without a
    ``--probe-case-module``. The one helper behind the batch driver's preflight and
    :func:`arrayprobe.tune.settings.resolve_probe_defaults`; any other unregistered name is
    refused exactly as :func:`resolve_probe_case` refuses it."""
    if name == "v35-2ds-ladder-fix" and name not in _REGISTRY:
        register_v35_2ds_ladder_fix()
    return resolve_probe_case(name)


#: The ``iaThreshType`` a case needs before its shattering constants act at all. Under
#: iaThreshType 0 (the driver's plain call with no threshold file) ``sizeDist`` runs no
#: shattering block, so a gate-on case's gate would silently do nothing and the run would
#: write the gate-off numbers under the gate-on name. ``scripts/run_flight.py`` refuses such a
#: run; type 2 is selected by ``[shattering].ia_thresh_type = 2`` in the run's config
#: (``sizeDist.m:520`` in ``UIOPS-v3.5/joefinlon-UIOPS-039be82/``, the per-second default).
_REQUIRED_IA_THRESH_TYPE: dict[str, int] = {}
REQUIRED_IA_THRESH_TYPE: Mapping[str, int] = MappingProxyType(_REQUIRED_IA_THRESH_TYPE)


def require_ia_thresh_type(name: str, ia_thresh_type: int) -> None:
    """Record that registered case ``name`` acts only under ``ia_thresh_type``.

    Called by the module that registers such a case, beside its
    :func:`register_probe_case` call, so the requirement exists wherever the case does."""
    _REQUIRED_IA_THRESH_TYPE[name] = ia_thresh_type


#: The ``iaThreshType`` values under which a case's shattering constants act, for a case that
#: accepts more than one (for example 1, a ``--iat-file`` threshold file, ``sizeDist.m:1213``,
#: and 2, its own ``defaultIntArrThresh``, ``:1308``, never 0).  Filled by
#: :func:`accept_ia_thresh_types` beside the case's :func:`register_probe_case` call;
#: ``scripts/run_flight.py`` refuses a run outside the set, as it does for
#: :data:`REQUIRED_IA_THRESH_TYPE`.
_ACCEPTED_IA_THRESH_TYPES: dict[str, frozenset[int]] = {}
ACCEPTED_IA_THRESH_TYPES: Mapping[str, frozenset[int]] = MappingProxyType(_ACCEPTED_IA_THRESH_TYPES)


def accept_ia_thresh_types(name: str, ia_thresh_types: frozenset[int]) -> None:
    """Record that registered case ``name`` acts under each of ``ia_thresh_types`` and no other."""
    _ACCEPTED_IA_THRESH_TYPES[name] = frozenset(ia_thresh_types)
