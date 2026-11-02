# SPDX-License-Identifier: BSD-3-Clause
"""Which MATLAB variant a run is reproducing.

UIOOPS is not one program.  Stock v3.1.4 is a snapshot of a codebase that groups
fork, edit and re-fork, and the ORACLES reference output this port is validated
against was produced by one such fork -- the tree in
a local reference-data directory (set with ``ARRAYPROBE_REFERENCE_DATA``), dated
November 2016.  Where the two disagree, "faithful" is ambiguous until you say
*faithful to which*.  A :class:`FidelityProfile` is that answer, passed
explicitly so no call site ever guesses.

It exists from S2 onward because S2 is where the
first *provable* divergence turned up: the ORACLES variant predates Joe Finlon's
2017-03-08 image-buffer guards, so the two decoders behave differently on a
truncated packet (see :attr:`FidelityProfile.spec_buffer_guard`).

Two rules keep this from rotting into a settings bag:

1. **Every field names a specific divergence with file:line provenance on both
   sides.**  Not a preference, not a tuning knob -- a place where two MATLAB
   sources demonstrably differ.
2. **No field gets a "sensible" default that silently picks a side.**  The
   profile is a required argument wherever it matters.

Profiles compose with, but do not replace, :mod:`arrayprobe.constants`: the
config *tables* stay keyed on ``(project, probe)`` as MATLAB keys them, while the
profile selects which *source variant* is being reproduced.
"""

from __future__ import annotations

# Shared leaf (split slice 10a(i)): the type and the registry live in
# arrayprobe_uiops.profiles; these names are the SAME objects.
# Split slice 10a(ii): the v3.5 builders, their caches and the three
# register_*_v35 functions live in arrayprobe_uiops.profiles, which also
# registers the two lazy builders in _LAZY; these names are the SAME objects.
from arrayprobe_uiops.profiles import (  # noqa: F401 -- shared leaf  # noqa: F401 -- re-exported
    _BEHAVIOUR_FIELDS,
    _LAZY,
    _ORACLES_PROD_V35_NAME,
    _REGISTRY,
    _SHIPPED,
    _STOCK_V35_NAME,
    _V35_TREE_PROFILES,
    PROFILES,
    FidelityProfile,
    _build_oracles_production_v35,
    _build_stock_v35,
    _ProfileRegistry,
    is_v35_flavoured,
    profile,
    register_profile,
    register_stock_v35_image_assisted,
)
from arrayprobe_uiops.reject_core import DEFAULT_REJECT_CONFIG, ORACLES_PRODUCTION_REJECT_CONFIG

# NOTE: no ``from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG`` here.
# That import used to run unconditionally at module load, which is why
# ``import arrayprobe`` pulled in the whole v3.5 engine -- and, through
# ``arrayprobe.reject``, numba -- before any caller asked for anything
# (2026-09-15: measured at 2.24 s of a 2.75 s wall import).
# It is deferred to :func:`_build_stock_v35` below, run once on first actual
# need for :data:`STOCK_V35`, so the selector's "neither engine is imported
# at module level" property (``tests/test_uiops_selector.py``) also holds for
# the packages themselves, not just for ``uiops``.

__all__ = [
    "FidelityProfile",
    "STOCK_V314",
    "ORACLES_2016",
    "ORACLES_PRODUCTION",
    "STOCK_V35",  # noqa: F822 -- module __getattr__ below serves this lazily; see _build_stock_v35
    # noqa: F822 -- lazy too; see _build_oracles_production_v35
    "ORACLES_PRODUCTION_V35",  # noqa: F822
    "PROFILES",
    "SHIPPED",
    "profile",
    "register_profile",
    "is_v35_flavoured",
    "register_stock_v35_image_assisted",
]




STOCK_V314 = FidelityProfile(
    name="stock-v3.1.4",
    description="joefinlon/UIOPS v3.1.4 as shipped (UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/).",
    spec_buffer_guard=True,
    hvps_reader="spec",
    diode_stats_counts_shadowed=True,
    zero_image_particle_recovery=True,
    time_in_seconds_from_tas=True,
    inter_arrival_in_seconds=True,
    shadow_diode_reillumination=False,
    imgproc_output_typing="typed",
    nan_tas_substitution=True,
    reject_thresholds=DEFAULT_REJECT_CONFIG,
)

ORACLES_2016 = FidelityProfile(
    name="oracles-2016",
    description=(
        "The behaviour a field campaign's modified UIOOPS used, November 2016 vintage. "
        "Predates the 2017-03-08 buffer guards; ships its own read_binary_hvps."
    ),
    spec_buffer_guard=False,
    hvps_reader="hvps",
    diode_stats_counts_shadowed=False,
    zero_image_particle_recovery=False,
    time_in_seconds_from_tas=False,
    inter_arrival_in_seconds=False,
    shadow_diode_reillumination=False,
    imgproc_output_typing="all-double",
    nan_tas_substitution=False,
    reject_thresholds=DEFAULT_REJECT_CONFIG,
)

ORACLES_PRODUCTION = FidelityProfile(
    name="oracles-production",
    description=(
        "The thresholds a field campaign's modified UIOOPS used, with its "
        "nine-argument imgProc_sm. Differs from oracles-2016 in two places: the "
        "stuck-diode re-illumination block (c(:,shadow_diode)='1'); and the reject "
        "thresholds -- the modified calculate_reject_unified.m:73-77 sets "
        "rej_hollow=0, max_edge_img_ar=4, max_comp_img_ar=4, measured to be what "
        "the archived products were made with (see reject.py). Its imgProc_sm "
        "differs from the stock file by that one block, one progress disp and two "
        "comment typo fixes."
    ),
    spec_buffer_guard=False,
    hvps_reader="hvps",
    diode_stats_counts_shadowed=False,
    zero_image_particle_recovery=False,
    time_in_seconds_from_tas=False,
    inter_arrival_in_seconds=False,
    shadow_diode_reillumination=True,
    imgproc_output_typing="all-double",
    nan_tas_substitution=False,
    reject_thresholds=ORACLES_PRODUCTION_REJECT_CONFIG,
)



for _p in (STOCK_V314, ORACLES_2016, ORACLES_PRODUCTION):
    _REGISTRY.setdefault(_p.name, _p)

SHIPPED: frozenset[str] = frozenset(
    {p.name for p in (STOCK_V314, ORACLES_2016, ORACLES_PRODUCTION)}
    | {_STOCK_V35_NAME, _ORACLES_PROD_V35_NAME})
"""The four names this package ships, fixed at import and never added to.

Kept separately from :data:`PROFILES` so that "is this one of ours?" survives a
registration. Complete from the start (``stock-v3.5`` included) even though the
object behind that name is built lazily.
"""
_SHIPPED.update(SHIPPED)


def __getattr__(name: str) -> FidelityProfile:
    """Module-level lazy attribute: ``profiles.STOCK_V35`` triggers the build.

    Only reached when normal attribute lookup misses -- i.e. before
    :func:`_build_stock_v35` has ever run, since it is only then that this
    module's namespace has no ``STOCK_V35`` of its own. ``from arrayprobe.
    profiles import STOCK_V35`` goes through this too, the same as any other
    attribute access.
    """
    if name in ("STOCK_V35", "ORACLES_PRODUCTION_V35"):
        import arrayprobe_uiops.profiles as _v35_profiles

        return getattr(_v35_profiles, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """``dir(profiles)`` lists the lazy :data:`STOCK_V35` too (PEP 562), so code that
    enumerates the module's profiles still finds it; listing it builds nothing."""
    return sorted(set(globals()) | {"STOCK_V35", "ORACLES_PRODUCTION_V35"})
