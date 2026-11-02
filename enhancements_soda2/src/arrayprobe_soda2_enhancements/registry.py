# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""Which SODA-2 corrections are on for a run -- **opt-in, default OFF, same as the UIOOPS side**.

Same shape and same reasoning as ``arrayprobe_enhancements.registry``, **copied, not
imported** -- ``test_lineage_isolation.py`` forbids importing anything from the UIOOPS
enhancements lineage, so the two registries are two independent implementations of the same
small mechanism rather than one shared module two different packages would have to agree on.

**Flipped to opt-in 2026-09-28.** Until then every module here
defaulted ON (the dataclass's own ``default_on: bool = True``), while the UIOOPS registry has
always defaulted every module OFF and applied only :data:`PROTECTIVE`'s data-destroying-defect
corrections by default (the protective-corrections rule). A14 asked for the same policy here. The
five modules in :data:`PROTECTIVE` are the ones whose defect silently destroys or corrupts
written data on a path confirmed to reach real processing; ``BACKLOG_STATUS.md`` gives each
module's reason. The other fourteen are opt-in like every UIOOPS
enhancement.

Two differences from the UIOOPS registry:

* **No engine matrix.** SODA-2 has one source tree (``SODA2/abansemer-soda2-afcea15/``), so
  there is nothing like ``arrayprobe_enhancements.applicability`` to consult -- every
  registered module simply applies or does not, per the caller's ``[enhancements]`` table.
* **``LINEAGE_PROBES`` is empty.** The UIOOPS lineage's :func:`protective_set` withholds its
  protective corrections from the ORACLES 2D-S/HVPS probes, because the archived product of
  record for that lineage must stay reproducible. SODA-2 has never written an archived product
  of record for any probe -- ``docs/developer/SODA2_BESIDE_UIOPS.md``: *"The v3.1.4 lineage
  ... is what actually wrote the ORACLES 2016 2D-S/HVPS product of record"* (not SODA-2), and
  the UND SODA-2 delivery this port validates
  against is not treated as truth; it is a reference for this port and for nothing else. So no
  SODA-2 probe carries the carve-out today; :func:`protective_set` still takes ``probe``/
  ``probetype`` for the same call shape as the UIOOPS side, so a future decision narrowing
  this could add one without an interface change.
* **A required ``reachability`` field**, one of ``"live"`` / ``"latent"`` / ``"flagged"``,
  quoting the classification of how often the defect fires on real
  data -- so a driver (or ``arrayprobe soda2 enhancements``, stage 10) can show a user *why*
  a given correction is on by default rather than only *that* it is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "EnhancementSpec",
    "UnknownEnhancement",
    "REGISTRY",
    "register",
    "resolve",
    "resolve_from_config",
    "entry_point",
    "load_all",
    "apply",
    "PROTECTIVE_KEY",
    "PROTECTIVE",
    "LINEAGE_PROBES",
    "protective_set",
]

_REACHABILITY_VALUES = ("live", "latent", "flagged")


class UnknownEnhancement(KeyError):
    """A config named a correction this package does not ship.

    Raised rather than ignored: an ignored typo in an opt-*in* line would leave the
    correction switched off while the user believes they asked for it, and an ignored typo
    naming one of :data:`PROTECTIVE`'s default-on corrections as ``false`` would (silently)
    leave it running. Either way the file says something the run did not do.
    """


@dataclass(frozen=True)
class EnhancementSpec:
    """One correction's identity, as a config file may name it.

    ``name`` is the config key and the module stem -- deliberately the same string, so the
    registry and the files on disk can be compared directly
    (``test_registry.py::test_every_module_on_disk_is_registered_and_vice_versa`` does exactly
    that). ``finding`` is the SODA-2 finding id this corrects. ``reachability`` is
    validated against :data:`_REACHABILITY_VALUES` in :func:`register`, not left to the
    caller's honesty. ``entry_point`` is the public callable a driver reaches for, as a bare
    attribute name resolved against the module.
    """

    name: str
    summary: str
    finding: str
    reachability: str
    default_on: bool = False
    entry_point: str | None = None

    def __post_init__(self) -> None:
        if self.reachability not in _REACHABILITY_VALUES:
            raise ValueError(
                f"reachability={self.reachability!r} for {self.name!r}; "
                f"must be one of {_REACHABILITY_VALUES}"
            )


REGISTRY: dict[str, EnhancementSpec] = {}


def register(spec: EnhancementSpec) -> EnhancementSpec:
    """Add ``spec`` to :data:`REGISTRY`. Re-registering the same name is an error."""
    if spec.name in REGISTRY:
        raise ValueError(f"enhancement {spec.name!r} is already registered")
    REGISTRY[spec.name] = spec
    return spec


#: The ``[enhancements]`` key for a driver's own protective on/off switch (e.g. ``arrayprobe
#: soda2 run --protective off``); not a module name, so :func:`resolve` sets it aside.
PROTECTIVE_KEY = "protective"

#: The protective-corrections rule applied to SODA-2: the corrections for
#: data-destroying upstream defects that run by default. Unlike
#: the UIOOPS side's :data:`arrayprobe_enhancements.registry.PROTECTIVE`, this is a flat name
#: set rather than a name -> probetypes map: none of the five needs a probetype restriction --
#: each reaches every probe its own hook point applies to.
PROTECTIVE: frozenset[str] = frozenset({
    # S4-x + S5-f: corrupts real particle image pixels (spuriously zeroes/reconstructs a
    # diode column) whenever no diode actually deviates; live via
    # soda2_processbuffer.pro:615's always-defined `h=sbhist` whenever stuckbits=1.
    "no_stuck_diode_fix",
    # S4-i: drops every particle in a file's own last buffer, which spec_index.pro:71's
    # `numbuffs-2` loop never scans -- every file has a last buffer.
    "last_buffer_index_fix",
    # S4-o: a same-timestamp buffer pair never adds the first particle's own inttime, and
    # the shortfall cascades onto every later particle's arrival time in the run.
    "same_time_buffer_fix",
    # S6-k: the archived .pbp.nc file's own rejectionflag variable is declared a signed
    # byte, so the depth-of-field reject bit (128) reads back as -128 through any
    # type-honouring reader -- corrupts a field in the delivered output itself.
    "pbp_rejectionflag_ubyte",
    # S4-z: the dilation kernel-size clamp under-sizes for the production dilatelength=2
    # call on a 1-2 slice ROI, silently leaving fragments of one particle apart (or merging
    # them wrongly) instead of the intended reconstruction.
    "dilation_clamp_fix",
})

#: SODA-2 probes whose archived product must stay reproducible, and so never get a
#: protective correction by default -- empty. SODA-2 has never written an archived product
#: for any probe (see the module docstring); the UIOOPS lineage's own version of this
#: set is ``{"2DS", "HVPS"}`` because that lineage's v3.1.4 engine wrote the ORACLES 2016
#: 2D-S/HVPS archived product. Kept as a named, empty set (rather than omitted) so a future
#: decision narrowing this can add a probe here without touching :func:`protective_set`'s
#: signature or callers.
LINEAGE_PROBES: frozenset[str] = frozenset()


def protective_set(probe: str = "", probetype: str = "") -> frozenset[str]:
    """The protective corrections that run by default for ``probe``/``probetype``.

    Same call shape as ``arrayprobe_enhancements.registry.protective_set(engine, probe,
    probetype)`` minus the engine argument (SODA-2 has one source tree). Returns
    :data:`PROTECTIVE` unless ``probe`` is in :data:`LINEAGE_PROBES`, which is empty today, so
    this returns :data:`PROTECTIVE` for every probe until one is added.
    ``probetype`` is accepted for the same reason and is not read yet -- no member of
    :data:`PROTECTIVE` needs a probetype restriction (see its own comments).
    """
    if probe in LINEAGE_PROBES:
        return frozenset()
    return PROTECTIVE


def resolve(requested: Mapping[str, bool] | None = None,
            protective: frozenset[str] = frozenset()) -> dict[str, bool]:
    """Resolve an ``[enhancements]`` table into an on/off decision for every correction.

    **Opt-in: a correction is ON only where the table says ``true``, except for the names in
    ``protective``**, which resolve ON unless the table explicitly says ``false`` for them.
    ``requested`` is the raw table from the config file, or ``None``/``{}`` for "no config
    file said anything". ``protective`` is normally :func:`protective_set` applied to the
    run's own probe -- callers that do not pass it get pure opt-in, same as
    ``arrayprobe_enhancements.registry.resolve`` with no default set selected. Every
    registered correction appears in the result. The ``"protective"`` key, if present, names
    no module (it is the caller's own on/off switch, e.g. ``arrayprobe soda2 run
    --protective``) and is set aside rather than treated as unknown.

    Raises :class:`UnknownEnhancement` if the file names something unregistered.
    """
    requested = dict(requested or {})
    requested.pop(PROTECTIVE_KEY, None)
    unknown = sorted(set(requested) - set(REGISTRY))
    if unknown:
        raise UnknownEnhancement(
            f"unknown SODA-2 enhancement(s) {unknown}; known: {sorted(REGISTRY)}. "
            "An ignored key would be a correction the config asked for (or asked off) that "
            "would not happen; this is an error rather than an ignored line."
        )
    return {name: bool(requested.get(name, spec.default_on or name in protective))
            for name, spec in REGISTRY.items()}


def resolve_from_config(cfg, protective: frozenset[str] = frozenset()) -> dict[str, bool]:
    """:func:`resolve` applied to a config object carrying an ``enhancements`` mapping
    attribute (e.g. ``arrayprobe.config.RunConfig``, once stage 10 wires ``engine =
    "soda2"`` through it -- see the ``[enhancements.soda2]`` note in the SODA-2 enhancements design)."""
    return resolve(getattr(cfg, "enhancements", None), protective=protective)


def entry_point(name: str):
    """Import and return the public callable for correction ``name``.

    Raises :class:`UnknownEnhancement` for an unregistered name, and ``LookupError`` for one
    registered without an ``entry_point``.
    """
    if name not in REGISTRY:
        raise UnknownEnhancement(f"unknown SODA-2 enhancement {name!r}; known: {sorted(REGISTRY)}")
    spec = REGISTRY[name]
    if spec.entry_point is None:
        raise LookupError(
            f"enhancement {name!r} is registered but has no entry_point yet -- it can be "
            "selected and resolved, but no driver callable is wired to it."
        )
    import importlib
    module = importlib.import_module(f"arrayprobe_soda2_enhancements.{name}")
    return getattr(module, spec.entry_point)


def load_all() -> dict[str, EnhancementSpec]:
    """Import every correction module so each one's import-time :func:`register` has run.

    Registration is an import side effect, so :data:`REGISTRY` is only complete after this --
    the reason a partial by-name test run once saw it short (stage 8)."""
    import importlib
    import pkgutil

    import arrayprobe_soda2_enhancements as pkg
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name != "registry" and not mod.name.startswith("_"):
            importlib.import_module(f"{pkg.__name__}.{mod.name}")
    return REGISTRY


def apply(resolved: Mapping[str, bool]):
    """Context manager: apply every resolved-ON correction the driver adapter can route,
    for the duration of the ``with`` block around ``soda2_process_2d``.

    Yields the record a ``.pbp.call`` sidecar carries: ``applied`` (names), ``skipped``
    (resolved-ON names the adapter cannot route, each with its reason) and ``hook_points``
    (which corrections were composed into which port binding). See
    ``arrayprobe_soda2_enhancements._adapter`` and ``arrayprobe_soda2.enhancement_hooks``.
    With every correction resolved OFF nothing is substituted and the run is the port's."""
    load_all()
    from arrayprobe_soda2_enhancements._adapter import applied
    return applied(resolved)
