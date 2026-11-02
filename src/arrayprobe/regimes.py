# SPDX-License-Identifier: BSD-3-Clause
"""Named, evidence-based size-distribution (``sizeDist``) thresholds -- cloud-regime defaults.

**Why this exists.** ``run_flight.py`` hard-codes ``tree="production"`` for
every run, so a project name ``sizedist_config`` does not recognise
(``constants.PROJECTS_PRODUCTION`` is ``("PECAN", "GPM")`` only) falls through to the
``otherwise`` branch -- which is the archived production configuration's tuned row
(``area_ratio_z=0.5``, ``default_int_arr_thresh=6e-6``), because that campaign is itself an
``otherwise`` case (constants.py:663-680). The ACE-ENA chain has been running those values since it
started, not by choice. **Measured**: ``constants.sizedist_config("ARM_ENA", "2DS", "production")
== constants.sizedist_config("ORACLES", "2DS", "production")``.

The author's requirement (verbatim): *"the runs should be configurable - if the user doesnt
provide thresholds, the defaults should be regime based - like liquid warm clouds/ice clouds etc.,
not oracles thresholds blindly"*, later widened: *"it needs to be user-flexible - so raw values in
toml maybe and also regime selector"* -- the rule that (a config file may only *select*, never
*describe*, a threshold) is explicitly lifted for the two fields named here, and only these two.
Every other fidelity-sensitive field (``rej_hollow``, ``max_edge_img_ar``, ``max_comp_img_ar``,
``spec_buffer_guard``, ``hvps_reader``, ``zero_image_particle_recovery`` -- the
:class:`~arrayprobe_uiops.reject_core.RejectConfig` / :class:`~arrayprobe.profiles.FidelityProfile`
fields)
stays selection-only, guarded by ``arrayprobe.config._FORBIDDEN``.

**This module changes no computed number by itself.** A run that names no regime and gives no
override resolves exactly the values ``run_flight.py`` has always hard-coded
(``tree="production"``, ``reject=None`` -> :data:`arrayprobe_uiops.sizedist_core.ORACLES_REJECT`,
``default_int_arr_thresh`` from ``constants.sizedist_config(..., "production")``) --
:func:`resolve_thresholds` with no arguments reproduces that path bit-for-bit
(``tests/test_regimes.py::TestFidelity``). Regime selection is a choice being made explicit, not a
new computation.

**Where a field cannot be justified from evidence this repository holds, it is left at stock and
says so.** No ice-specific or mixed-phase-specific S4 threshold exists anywhere in this codebase
(measured: ``constants.py``'s two switch tables hold only PECAN/GPM/ORACLES-shaped rows, never a
phase-labelled one) -- inventing one would be fabricating a value, which this package never does.
:data:`ICE` and :data:`MIXED` therefore carry stock's own values, named as such, with a
concrete note on what evidence would settle a real one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arrayprobe_uiops.reject_core import RejectConfig

__all__ = [
    "Regime", "ResolvedField", "ResolvedThresholds",
    "LIQUID_WARM", "ICE", "MIXED", "REGIMES", "register_regime",
    "ThresholdValidationError", "resolve_thresholds",
    "Inherit", "INHERIT", "REJECT_FIELDS", "UncitedRegimeField",
    "resolve_reject", "regime_reject_values", "regime_reject_sources",
]


@dataclass(frozen=True)
class Inherit:
    """The explicit "this regime does not set this reject field" marker, with its reason.

    A regime slot holding an :class:`Inherit` takes the run's profile value for that field
    (:func:`resolve_reject`). The reason is required: an inherited slot is a decision like any
    other and says
    why it was made.
    """

    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise UncitedRegimeField(
                "an Inherit marker must state its reason (a non-empty string)")


class UncitedRegimeField(ValueError):
    """A :class:`Regime` reject slot set to a value with no citation, or of the wrong type.

    The shape of ``arrayprobe_uiops.probe_cases.UncitedProbeCaseField``: refused at construction,
    so a regime that types a threshold without naming the vendored ``file:line`` or measurement
    record it came from never exists (the never-invent-a-threshold rule).
    """


INHERIT = Inherit(reason="inherits the profile's reject set; no regime-specific datum")
"""The sentinel the three shipped regimes carry on all six reject slots, so every ``--regime``
run resolves to the same eight thresholds it did before the slots existed."""

#: The six :class:`~arrayprobe_uiops.reject_core.RejectConfig` fields a regime may carry, with the
#: type
#: each must hold when set (``calculate_reject_unified.m:71-77``; ``reject.py``'s
#: ``RejectConfig``). ``tests/test_regimes_reject_slots.py`` asserts this tuple equals
#: ``RejectConfig``'s own field list, so the two cannot drift apart.
REJECT_FIELDS: tuple[str, ...] = (
    "rej_zero_area", "rej_split", "rej_hollow",
    "shadowed_area", "max_edge_img_ar", "max_comp_img_ar",
)
_REJECT_BOOL_FIELDS = frozenset({"rej_zero_area", "rej_split", "rej_hollow"})


class ThresholdValidationError(ValueError):
    """A user-supplied raw threshold value that fails a physically-grounded bound.

    Bounds are asserted only where the repository holds a reason to assert one (area ratio is
    bounded to (0, 1] by its own definition -- image area divided by an enclosing shape's area);
    where no such reason exists (``default_int_arr_thresh``'s upper end -- no evidence here bounds
    a plausible inter-arrival threshold), nothing is asserted, and that is stated rather than an
    invented limit being enforced silently.
    """


@dataclass(frozen=True)
class Regime:
    """One named, evidence-based bundle of size-distribution-stage threshold defaults.

    Both fields are cited individually -- ``area_ratio_z`` and ``default_int_arr_thresh`` are
    independent MATLAB literals (the campaign-configured ``sizeDist.m:849`` and ``:269``) with
    no shared history, so a regime that could justify one and not the other is expected, not an
    oversight.
    """

    name: str
    area_ratio_z: float
    area_ratio_z_justification: str
    default_int_arr_thresh: float
    default_int_arr_thresh_justification: str
    provenance: str
    """The regime's own rationale -- what evidence ties these particular numbers to this cloud
    type, or the explicit statement that none does and values are stock's own."""

    # The six S3 reject thresholds (author, 2026-09-30: "let a regime carry all eight
    # thresholds"). Each is a cited value or an :class:`Inherit` carrying its reason; a value
    # needs a non-empty ``<field>_justification`` naming a vendored file:line or a measurement
    # record, or construction raises :class:`UncitedRegimeField`. Defaulting to INHERIT keeps
    # every regime written before the slots existed constructible and unchanged in effect.
    rej_zero_area: bool | Inherit = INHERIT
    rej_zero_area_justification: str = ""
    rej_split: bool | Inherit = INHERIT
    rej_split_justification: str = ""
    rej_hollow: bool | Inherit = INHERIT
    rej_hollow_justification: str = ""
    shadowed_area: float | Inherit = INHERIT
    shadowed_area_justification: str = ""
    max_edge_img_ar: float | Inherit = INHERIT
    max_edge_img_ar_justification: str = ""
    max_comp_img_ar: float | Inherit = INHERIT
    max_comp_img_ar_justification: str = ""

    def __post_init__(self) -> None:
        for f in REJECT_FIELDS:
            value = getattr(self, f)
            if isinstance(value, Inherit):
                continue
            if f in _REJECT_BOOL_FIELDS:
                ok = isinstance(value, bool)
                want = "a bool"
            else:
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                want = "a number (not a bool)"
            if not ok:
                raise UncitedRegimeField(
                    f"regime {self.name!r}: {f}={value!r} must be {want} or an Inherit marker "
                    "(RejectConfig's field type, reject.py)")
            justification = getattr(self, f + "_justification")
            if not isinstance(justification, str) or not justification.strip():
                raise UncitedRegimeField(
                    f"regime {self.name!r} sets {f}={value!r} but cites nothing: a regime's "
                    f"reject value needs {f}_justification naming the vendored file:line or "
                    "measurement record it came from, or the slot must be an Inherit marker "
                    "with its reason")


LIQUID_WARM = Regime(
    name="liquid-warm",
    area_ratio_z=0.5,
    area_ratio_z_justification=(
        "sizeDist.m:849 (campaign-configured copy), "
        "\"Changed from .2 to .5 for ORACLES - Siddhant Gupta - "
        "11/1/17\" -- read. ORACLES 2016 sampled marine stratocumulus off Namibia, warm liquid "
        "cloud (derived from the campaign's own description); a tighter "
        "area-ratio cut is consistent with rejecting non-circular artefacts among spherical "
        "liquid drops, which is what an area-ratio gate measures on a round particle."
    ),
    default_int_arr_thresh=6e-6,
    default_int_arr_thresh_justification=(
        "sizeDist.m:269 (campaign-configured copy; constants.py:589), "
        "\"Changed from 1e-6 to 6e-6 for "
        "ORACLES\" -- read. Same campaign, same warm marine-stratocumulus tuning; no independent "
        "shattering-rate measurement for this value is held by this repository beyond the "
        "dated MATLAB comment itself."
    ),
    provenance=(
        "ORACLES_PRODUCTION's own dated 'for ORACLES' edits to the MATLAB source, named as a "
        "regime rather than arriving as the unnamed 'otherwise' fallback a campaign that never "
        "chose them would silently inherit (a measured defect)."
    ),
    rej_zero_area=INHERIT,
    rej_split=INHERIT,
    rej_hollow=INHERIT,
    shadowed_area=INHERIT,
    max_edge_img_ar=INHERIT,
    max_comp_img_ar=INHERIT,
)

ICE = Regime(
    name="ice",
    area_ratio_z=0.2,
    area_ratio_z_justification=(
        "NOT JUSTIFIED FOR ICE -- left at stock's own value "
        "(arrayprobe_uiops.sizedist_core.STOCK_REJECT, "
        "measured 2026-08-19 against UIOPS-v3.1.4 and the OptArrProbDataProcessing variant tree, "
        "both .2). No ice-specific area-ratio value exists anywhere in this codebase's two "
        "sizeDist.m switch tables (constants.py) -- inventing one would be the fabrication "
        "the project's rule against inventing values forbids. An area-ratio gate tuned on "
        "spherical liquid drops "
        "(LIQUID_WARM's .5) measures a different thing on ice habit, so it is not carried "
        "over either. WHAT WOULD SETTLE A REAL VALUE: labelled ice-phase particle images from a "
        "campaign with independent phase information (ARM context such as cloud "
        "phase, temperature and companion probes)."
    ),
    default_int_arr_thresh=4e-6,
    default_int_arr_thresh_justification=(
        "NOT JUSTIFIED FOR ICE -- left at stock's own per-probe default for the 2D-S "
        "(constants.SIZEDIST_CONFIG, project='otherwise', probe='2DS', 4e-6 s). No "
        "ice-specific inter-arrival threshold is held by this repository; ORACLES's 6e-6 is the "
        "same warm-liquid tuning as its area_ratio_z. WHAT WOULD SETTLE A REAL VALUE: measured "
        "shattering inter-arrival-time statistics on a known-ice flight segment."
    ),
    provenance=(
        "No evidence this repository holds justifies an ice-specific S4 threshold pair, so this "
        "regime states stock's own values by name rather than letting a fallback silently supply "
        "a warm-liquid campaign's numbers. See the per-field notes for what would settle each one."
    ),
    rej_zero_area=INHERIT,
    rej_split=INHERIT,
    rej_hollow=INHERIT,
    shadowed_area=INHERIT,
    max_edge_img_ar=INHERIT,
    max_comp_img_ar=INHERIT,
)

MIXED = Regime(
    name="mixed",
    area_ratio_z=0.2,
    area_ratio_z_justification=(
        "NOT JUSTIFIED FOR MIXED PHASE -- same as ICE: no mixed-phase-specific evidence is held "
        "by this repository; left at stock's .2 (arrayprobe_uiops.sizedist_core.STOCK_REJECT)."
    ),
    default_int_arr_thresh=4e-6,
    default_int_arr_thresh_justification=(
        "NOT JUSTIFIED FOR MIXED PHASE -- same as ICE: no mixed-phase-specific evidence is held "
        "by this repository; left at stock's per-probe default for the 2D-S, 4e-6 s."
    ),
    provenance=(
        "No evidence this repository holds distinguishes a mixed-phase S4 threshold pair from "
        "ICE's; both sit at stock's values until measured campaign context (ARM "
        "cloud-phase, temperature and companion-probe data) settles one for either."
    ),
    rej_zero_area=INHERIT,
    rej_split=INHERIT,
    rej_hollow=INHERIT,
    shadowed_area=INHERIT,
    max_edge_img_ar=INHERIT,
    max_comp_img_ar=INHERIT,
)

_REGIMES: dict[str, Regime] = {r.name: r for r in (LIQUID_WARM, ICE, MIXED)}
REGIMES: MappingProxyType[str, Regime] = MappingProxyType(_REGIMES)
"""Every regime this module ships. A fork adds its own with :func:`register_regime` -- from
Python, with per-field justification required, never by describing one in a config file (the same
constraint :func:`arrayprobe.profiles.register_profile` holds a fork's profile to)."""


def register_regime(new: Regime) -> Regime:
    """Register a fork's own :class:`Regime`, the same way
    :func:`arrayprobe.profiles.register_profile` registers a fork's
    :class:`~arrayprobe.profiles.FidelityProfile`.

    Registering constructs the object in Python, where every field's justification is named; a
    config file may only *select* the name afterwards, never describe the numbers.
    """
    if not isinstance(new, Regime):
        raise TypeError(f"register_regime takes a Regime, got {type(new).__name__}")
    if new.name in _REGIMES:
        raise ValueError(
            f"{new.name!r} is already a registered regime ({sorted(_REGIMES)}); a fork's regime "
            "may not shadow a shipped name")
    _REGIMES[new.name] = new
    return new


#: Physical bound on area_ratio_z: an area ratio (image area / enclosing-shape area) is bounded to
#: (0, 1] by its own definition, regardless of cloud regime -- the one bound this repository can
#: assert without inventing a threshold value.
_AREA_RATIO_BOUNDS = (0.0, 1.0)


#: The pre-2026-10-16 spelling of the ``"default"`` source tag. Writers emit only
#: ``"default"``; readers of already-written stamps accept this too.
LEGACY_DEFAULT_SOURCE = "stock"


def is_default_source(source: str) -> bool:
    """True for the built-in-fallback tag in either spelling (``default``, or the old ``stock``)."""
    return source in ("default", LEGACY_DEFAULT_SOURCE)


@dataclass(frozen=True)
class ResolvedField:
    """One resolved threshold value, tagged with WHERE it came from and why.

    ``source`` is one of ``"regime:<name>"``, ``"user:<path>"`` or ``"default"`` (the built-in
    fallback nobody chose -- see :func:`resolve_thresholds`'s no-argument case) -- three
    different epistemic objects that must never be blurred: a value someone typed into a TOML is
    not the same claim as a named regime's cited default.

    ``"default"`` is the built-in fallback nobody chose, and its meaning depends on the tree: for
    the production tree it is ``ORACLES_REJECT`` (area_ratio_z 0.5, the 2017 production edit,
    ``sizedist_core.py``); for the stock tree it is ``STOCK_REJECT`` (0.2, unmodified UIOOPS). It
    does NOT mean "unmodified UIOOPS uses this value". Stamps written before 2026-10-16 spell it
    ``"stock"``; every reader accepts both (:data:`LEGACY_DEFAULT_SOURCE`).
    """

    value: float
    source: str
    justification: str

    def render(self) -> str:
        """``"<value> (<source>)"`` -- the one line both the startup print and the ``.call``
        stamp use, so the two can never say something different about the same run."""
        return f"{self.value:g} ({self.source})"


@dataclass(frozen=True)
class ResolvedThresholds:
    """The two size-distribution threshold fields in force for one run, each with its provenance.

    Returned by :func:`resolve_thresholds` and consumed by ``scripts/run_flight.py`` in three
    places that must never disagree: the startup print, the confirmation panel and the
    ``.call`` stamp. The two fields are kept separate rather than collapsed into one "source"
    because a run may mix origins -- a regime for one and a raw override for the other -- and
    reporting both as whichever was set last is exactly the blurring this module exists to prevent.
    """

    area_ratio_z: ResolvedField
    default_int_arr_thresh: ResolvedField


def resolve_reject(regime: Regime | None, profile_reject: RejectConfig) -> RejectConfig:
    """The :class:`~arrayprobe_uiops.reject_core.RejectConfig` a run uses: the regime's cited
    values over the profile's.

    Each of the six slots the regime marks :class:`Inherit` takes ``profile_reject``'s value; each
    it sets replaces it. ``regime=None`` returns ``profile_reject`` itself, unchanged. With the
    three shipped regimes (all six INHERIT) the result equals ``profile_reject`` field for field,
    so a ``--regime`` run keeps its profile's reject set (``tests/test_regimes_reject_slots.py``).
    Precedence above the regime (a ``user:`` override) is the driver's, not this function's.

    """
    if regime is None:
        return profile_reject
    if not isinstance(regime, Regime):
        raise TypeError(f"resolve_reject takes a Regime or None, got {type(regime).__name__}")
    # Any: dataclasses.replace's per-field types are checked against one dict value type.
    supplied: dict[str, Any] = dict(regime_reject_values(regime))
    return replace(profile_reject, **supplied) if supplied else profile_reject


def regime_reject_values(regime: Regime) -> dict[str, bool | float]:
    """The reject slots the regime sets, ``{field: value}``; the Inherit slots are left out."""
    out: dict[str, bool | float] = {}
    for f in REJECT_FIELDS:
        value = getattr(regime, f)
        if not isinstance(value, Inherit):
            out[f] = value
    return out


def regime_reject_sources(regime: Regime | None) -> dict[str, str]:
    """``{field: "regime:<name>"}`` for each reject slot the regime sets; empty when it sets none.

    Lists only the fields the regime supplied, so a stamp built from it stays absent when unused
    (design record section 3's ``reject_sources=`` key).
    """
    if regime is None:
        return {}
    return {f: f"regime:{regime.name}" for f in regime_reject_values(regime)}


def _legacy_reject(tree: str):
    # The thresholds live in the shared v3.5 core (arrayprobe.sizedist re-exports the same
    # objects), so this works whether or not the v3.1.4 engine is installed.
    from arrayprobe_uiops.sizedist_core import ORACLES_REJECT, STOCK_REJECT
    return ORACLES_REJECT if tree == "production" else STOCK_REJECT


def _legacy_default_int_arr_thresh(projectname: str, probename: str, tree: str) -> float:
    # Deferred import, same reason: constants.py has no reason to import this module.
    from .constants import sizedist_config
    return sizedist_config(projectname, probename, tree).default_int_arr_thresh


def resolve_thresholds(
    regime_name: str | None = None,
    area_ratio_z_override: float | None = None,
    default_int_arr_thresh_override: float | None = None,
    override_source: str = "user",
    *,
    area_ratio_z_source: str | None = None,
    default_int_arr_thresh_source: str | None = None,
    projectname: str = "ORACLES",
    probename: str = "2DS",
    tree: str = "production",
) -> ResolvedThresholds:
    """Resolve the two size-distribution threshold fields, tagging where each value came from.

    **No arguments** (the default): reproduces exactly what ``run_flight.py`` has always
    hard-coded for every project, named rather than silently applied --
    ``arrayprobe_uiops.sizedist_core.ORACLES_REJECT.area_ratio_z`` (0.5) and the production
    ``otherwise/2DS``
    row's ``default_int_arr_thresh`` (6e-6, ``constants.py:674-680``). This is the production-tuned
    pair an unrecognised project was found silently inheriting -- kept as the literal
    no-argument default so nothing about an already-validated run changes, but tagged
    ``"default"`` (meaning: the historical hard-coded fallback, not a regime anyone chose) rather
    than arriving with no name at all.

    ``regime_name``: one of :data:`REGIMES`. Supplies both fields unless overridden below.

    ``*_override``: a raw value from a config file or the command line -- the rule that a
    config file may only select, never set a threshold, is lifted for exactly these two fields
    Validated before being accepted:
    ``area_ratio_z`` must fall in (0, 1] (an area ratio's own definition bounds it there); no bound
    is asserted on ``default_int_arr_thresh`` beyond being a positive, finite number of seconds,
    because no evidence this repository holds justifies an upper limit -- said here rather than an
    invented one being silently enforced.

    ``override_source`` names where an override came from (typically a config file path or
    ``"cli"``), embedded in the returned field's ``source`` as ``"user:<override_source>"``.
    ``area_ratio_z_source``/``default_int_arr_thresh_source`` (keyword-only) override it per
    field -- needed because a run may mix sources (one field from ``--area-ratio-z``, the other
    from ``[thresholds]``), which the coordinating driver must tag distinctly rather than
    reporting both as coming from wherever the last one was set.

    ``projectname``/``probename``/``tree`` (keyword-only) matter only for the no-regime,
    no-override "default" fallback: ``default_int_arr_thresh`` is looked up from
    ``constants.sizedist_config(projectname, probename, tree)`` exactly as ``sizedist.run`` itself
    would, so the fallback stays probe-correct rather than a single literal borrowed from the 2D-S
    case (HVPS and CIP take a different value in the same ``otherwise`` row --
    constants.py:663-688). Default to ``"ORACLES"``/``"2DS"``/``"production"``, which
    reproduces exactly the call every validated flight has used to date.
    """
    if regime_name is not None and regime_name not in REGIMES:
        raise ValueError(f"unknown regime {regime_name!r}; known: {sorted(REGIMES)}")
    regime = REGIMES[regime_name] if regime_name is not None else None

    if area_ratio_z_override is not None:
        lo, hi = _AREA_RATIO_BOUNDS
        if not (lo < area_ratio_z_override <= hi):
            raise ThresholdValidationError(
                f"area_ratio_z={area_ratio_z_override!r} is outside ({lo}, {hi}]: an area ratio "
                "(image area / enclosing-shape area) is bounded there by its own definition, "
                "regardless of cloud regime")
        _src = area_ratio_z_source if area_ratio_z_source is not None else override_source
        area_field = ResolvedField(
            value=float(area_ratio_z_override), source=f"user:{_src}",
            justification=f"raw value from {_src}, not tied to a named regime")
    elif regime is not None:
        area_field = ResolvedField(
            value=regime.area_ratio_z, source=f"regime:{regime.name}",
            justification=regime.area_ratio_z_justification)
    else:
        legacy = _legacy_reject(tree)
        area_field = ResolvedField(
            value=legacy.area_ratio_z, source="default",
            justification=("no regime or override given -- the historical hard-coded fallback "
                            "every run before 2026-09-17 used unnamed: " + legacy.provenance))

    if default_int_arr_thresh_override is not None:
        if not (default_int_arr_thresh_override > 0.0
                and default_int_arr_thresh_override < float("inf")):
            raise ThresholdValidationError(
                f"default_int_arr_thresh={default_int_arr_thresh_override!r} must be a positive, "
                "finite number of seconds; no upper bound is asserted (no evidence held here "
                "justifies one)")
        _isrc = (default_int_arr_thresh_source if default_int_arr_thresh_source is not None
                else override_source)
        iat_field = ResolvedField(
            value=float(default_int_arr_thresh_override), source=f"user:{_isrc}",
            justification=f"raw value from {_isrc}, not tied to a named regime")
    elif regime is not None:
        iat_field = ResolvedField(
            value=regime.default_int_arr_thresh, source=f"regime:{regime.name}",
            justification=regime.default_int_arr_thresh_justification)
    else:
        legacy_iat = _legacy_default_int_arr_thresh(projectname, probename, tree)
        iat_field = ResolvedField(
            value=legacy_iat, source="default",
            justification=(
                f"no regime or override given -- the historical hard-coded fallback: "
                f"constants.sizedist_config({projectname!r}, {probename!r}, {tree!r})"
                f".default_int_arr_thresh, applied before 2026-09-17 to every project this "
                f"driver ran (for ORACLES/2DS/production this is "
                f"sizeDist.m:269 (campaign-configured copy), "
                f"'Changed from 1e-6 to 6e-6 for ORACLES', constants.py:674-680), named rather "
                f"than silent from here on"))

    return ResolvedThresholds(area_ratio_z=area_field, default_int_arr_thresh=iat_field)
