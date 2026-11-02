# SPDX-License-Identifier: BSD-3-Clause
"""Which enhancements are on for a run -- **opt-in, default OFF, in both pipelines**.

**One TOML file, one meaning** (the 2026-09-16 cold-start usability audit). An enhancement runs only where
``[enhancements].<name> = true`` says so, whether the file is handed to ``arrayprobe
run`` or to ``arrayprobe-enhanced run``. That is what ``README.md``, the enhancements
page and the example configuration's own comment have always said, and since
2026-09-16 it is also what the code does.

**What this replaced, and why.** The switchable-enhancements rule (user-directed 2026-09-10: *"all of them will
have to be in config file as an opt in as default but option for opt out"*) was read as
"the default is a property of which pipeline you invoked": the port default-OFF, this
package default-ON and opt-out by name, on the argument that installing
``arrayprobe-enhancements`` is itself the opt-in. The 2026-09-16 cold-start usability
audit measured the consequence. A config whose only line was ``outoffocus = false``
resolved **31 of 40** modules ON under the default v3.5 engine and applied four,
``hole_edge_swap`` and ``published_dof`` among them -- both of which change numbers. The
inversion was stated in exactly one place, an inline comment in the configuration page,
while every other public surface said opt-in. It did not fail; it changed the answer and
returned 0. The author approved the flip on that measurement.

* **The port** (``arrayprobe``, ``scripts/run_flight.py``) defaults every enhancement
  **OFF**, through :meth:`arrayprobe.config.RunConfig.enabled`. Unchanged, and it must
  stay that way: ``arrayprobe`` is a bug-for-bug reproduction of UIOOPS v3.1.4, and a
  correction that silently switched itself on would invalidate the ORACLES
  product-of-record reproduction everything else rests on.
* **This package** now reads the same table the same way. :func:`resolve` returns a
  decision for *every* registered enhancement so a driver has no implicit default left
  to invent, and ``arrayprobe_enhancements.pipeline`` refuses a config that carries no
  ``[enhancements]`` section at all rather than guessing which way the author meant it.

**The dependency arrow is unchanged.** This module imports nothing from ``arrayprobe``
-- :func:`resolve_from_config` takes an :class:`~arrayprobe.config.RunConfig` by duck
typing (``getattr(cfg, "enhancements", None)``), never importing the type it comes
from, so this package stays importable without the port installed. ``arrayprobe`` does
not import this module either, and ``tests/test_no_enhancement_coupling.py``
still fails if it ever does. The port needs no code change to support any of this --
``RunConfig.enhancements``
already carries the raw ``[enhancements]`` table verbatim, and resolving it is exactly
the job the core's own docstring declines ("validating them is the enhancements
package's job, and refusing here would couple the two in the direction
``test_no_enhancement_coupling.py`` forbids").

**Unknown names raise here.** The core returns ``False`` for a name it has never heard
of, because it cannot know what exists. This package can, so a typo'd
``wide_hollow_fx = true`` is an error rather than a silently-ignored line that leaves
the correction switched off while the user believes they asked for it -- the reason this
resolution step exists at all rather than being a ``dict.get``.

Design record: ``enhancements_uiops/docs/enhancement_registry_design.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from arrayprobe_enhancements import applicability

__all__ = [
    "EnhancementSpec",
    "UnknownEnhancement",
    "REGISTRY",
    "register",
    "resolve",
    "resolve_from_config",
    "entry_point",
    "ALL_KEY",
    "PROTECTIVE_KEY",
    "DEFAULT_SET_EXCLUSIONS",
    "default_set",
    "PROTECTIVE",
    "PROTECTIVE_POLICY",
    "LINEAGE_PROBES",
    "protective_set",
]


class UnknownEnhancement(KeyError):
    """A config named an enhancement this package does not ship.

    Raised rather than ignored: an ignored typo in an opt-*in* line leaves the
    correction switched off while the user believes they asked for it, and an ignored
    typo in an opt-*out* line would (before 2026-09-16) have left it running. Either way the
    file says something the run did not do, which is the thing this package refuses.
    """


@dataclass(frozen=True)
class EnhancementSpec:
    """One enhancement's identity, as a config file may name it.

    ``name`` is the config key and the module stem -- deliberately the same string, so
    the table below and the files on disk can be compared directly rather than through
    a mapping that could itself drift (``test_enhancement_registry.py`` does exactly
    that comparison).

    ``finding`` is the upstream-finding id this corrects, or ``None`` for a
    module that corrects nothing and adds capability instead. ``entry_point`` is the
    public callable a driver reaches for, as a bare attribute name resolved against the
    module -- ``None`` while a module is registered (selectable, resolvable) but not yet
    wired to a driver.

    ``stage`` fixes where in a run this enhancement applies, so a driver applying every
    ON enhancement in order has a total order to follow: ``"reader"`` (raw
    binary decode), ``"proc"`` (per-particle imgProc output), ``"sd"`` (size
    distribution / combine output), ``"product"`` (a post-combine export or copy), or
    ``"none"`` (a reference table or pure function with no file stage at all).

    ``consumes`` names what the entry point needs, as a frozenset: real netCDF variable
    names where the module reads a written file, the token ``"images"`` where it needs
    particle image arrays (not yet written to any file), ``"raw"`` where it reads raw
    probe binary, or an empty frozenset where it takes call arguments the run
    configuration supplies rather than anything read from a file (e.g. a pressure, a
    probe constant). This is metadata for the cross-cutting v3.5-openability test,
    not validated here -- a name that turns out wrong is that test's job to catch.

    ``default_on`` is **False for every module and must stay that way** (the 2026-09-16 cold-start usability audit).
    It is kept as a field only so the shape of this dataclass still matches the SODA-2
    lineage's copy; there is no module-level exemption from opt-in, and
    ``test_enhancement_opt_in.py::NothingIsOnByDefault`` fails if any spec sets it True.
    See :func:`resolve` for why the default was flipped. The one default-on path is not
    this field: :data:`PROTECTIVE` names the data-destroying-defect corrections the batch
    driver applies by default on probes with no archived product (the exception for data-destroying-defect corrections).
    """

    name: str
    summary: str
    finding: str | None = None
    default_on: bool = False
    entry_point: str | None = None
    stage: str = "none"
    consumes: frozenset[str] = field(default_factory=frozenset)
    #: True for a module that repairs what the v3.1.4 engine wrote; it ships only where that
    #: engine does (``applicability.REQUIRES_V314`` is the other side of this flag).
    requires_v314: bool = False


REGISTRY: dict[str, EnhancementSpec] = {}


def register(spec: EnhancementSpec) -> EnhancementSpec:
    """Add ``spec`` to :data:`REGISTRY`. Re-registering the same name is an error."""
    if spec.name in REGISTRY:
        raise ValueError(f"enhancement {spec.name!r} is already registered")
    REGISTRY[spec.name] = spec
    return spec


# --- The wired slice -------------------------------------------------------
#
# Three modules, wired end to end as proof that the mechanism works on real,
# heterogeneous enhancements rather than on a synthetic example: two corrections
# that replace a port function and one new capability that adds a
# derived product (no finding). The remaining modules are listed as a ratchet in
# `test_enhancement_registry.py` -- see that file and the design doc for the
# pattern each follows and why they are not all wired at once.

# `better_is_it_hollow` since 2026-09-12: the intent is *the better
# correction*, not v3.5's blankly. v3.5's rewrite fixed both defects and
# introduced an array-truthiness regression at
# `calculate_reject_unified.m:385`, so the entry point takes its improvement
# and declines its defect. Per-behaviour comparison in the module docstring;
# `tests/test_wide_hollow_vs_upstream.py` measures all three implementations.
register(EnhancementSpec(
    name="wide_hollow_fix",
    requires_v314=True,
    summary="The hollow test with both upstream defects corrected: full-width "
            "overlap, no middle-third scan window, and the any-overlap "
            "coverage guard v3.5 lost.",
    finding="the diode-32 hollow test",
    entry_point="better_is_it_hollow",
    stage="proc",
    consumes=frozenset({"images"}),
))

register(EnhancementSpec(
    name="spot_edge_fix",
    summary="Korolev spot_edge(147) reads 757 where the table means 0.757; recovers part_z.",
    finding="the missing decimal in spot_edge",
    entry_point="correct_part_z_size_factor",
    stage="proc",
    consumes=frozenset({"max_hole_diameter", "edge_at_max_hole", "part_z"}),
))

register(EnhancementSpec(
    name="dmax_sensitivity",
    summary="How far the six d_choice diameter definitions disagree for the same particle.",
    finding=None,
    entry_point="compute_sensitivity",
    stage="proc",
    consumes=frozenset({"image_length", "image_width", "image_diam_minR"}),
))

# Registered rather than added to the ratchet, which may only shrink -- and
# registering it is honest here, because there is nothing to wire: this module
# is a table, not a computation. `entry_point` names the lookup so a driver that
# wants a relation by name has one, and `default_on` is irrelevant to it in the
# usual sense (turning a registry "off" removes nothing from any output); it is
# registered so that a config file naming `md_relations` is resolved rather than
# rejected as a typo.
register(EnhancementSpec(
    name="md_relations",
    summary="Registry of mass-diameter relations: the four this repository has "
            "verified, plus the four the plan names as declared, coefficient-free gaps.",
    finding=None,
    entry_point="get",
    stage="none",
    consumes=frozenset(),
))

# Added 2026-09-14: a published mass-diameter power law, read
# directly from the paper and registered in md_relations above. Registered
# rather than wired to a stage or a `consumes` field, same standing as
# md_relations itself: nothing in the port or the pipeline calls it, a caller
# invokes mass_bf95() explicitly with a diameter already converted to the
# microns the paper's coefficients are fitted against (see the module
# docstring), so naming a `consumes` field here would assert a wiring that
# does not exist.
register(EnhancementSpec(
    name="brown_francis_1995",
    summary="Brown & Francis (1995) aggregate mass-diameter power law "
            "(M = 7.38e-11 * D**1.9, D in microns, M in grams), read "
            "directly from the paper and offered through md_relations.",
    finding=None,
    entry_point="mass_bf95",
    stage="none",
    consumes=frozenset(),
))

# --- The ratchet, registered 2026-09-14 -----------------------------
#
# The remaining 29 modules the ratchet in `test_enhancement_registry.py` named.
# Each `entry_point` was confirmed to exist by opening the module (grep of `^def `
# and `__all__`) before being named here -- never registered from the module's
# summary alone. `entry_point=None` marks a module that is a toolkit of several
# co-equal functions with no single "apply this" callable (same standing as
# `md_relations` above, which predates this pass) -- registered so a config file
# naming it resolves rather than raising `UnknownEnhancement`, not yet wired to a
# driver. `stage`/`consumes` are declared per the design in this module's
# docstring; `enhancement_registry_design.md` records the per-module survey this
# table is built from.

register(EnhancementSpec(
    name="hole_edge_swap",
    summary="C5 -- max_hole_diameter and edge_at_max_hole are swapped on the way "
            "to disk; this un-swaps them.",
    finding="the swapped hole variables",
    entry_point="correct_hole_edge_swap",
    stage="proc",
    consumes=frozenset({"max_hole_diameter", "edge_at_max_hole"}),
))

register(EnhancementSpec(
    name="int16_double_fix",
    summary="A2 -- cast image_length/image_width to double before the diodesize "
            "multiply, instead of after, for the five saturating d_choice branches.",
    finding="the int16 diameter saturation",
    entry_point=None,
    stage="sd",
    consumes=frozenset({"image_length", "image_width"}),
))

register(EnhancementSpec(
    name="conc_arear_fix",
    requires_v314=True,
    summary="A4 -- pre-divides image_diam_AreaR by diodesize so the port's own "
            "double-scaling multiply cancels out, then reruns sizedist.run() unmodified.",
    finding="the double-scaled area-ratio concentration",
    entry_point="corrected_sd_file",
    stage="sd",
    consumes=frozenset({"image_diam_AreaR"}),
))

register(EnhancementSpec(
    name="reshape_fix",
    summary="A6 -- recovers mean_area_ratio (and, unverified, its REJ_/"
            "mean_aspect_ratio_* siblings) from sizeDist.m's untransposed write.",
    finding="the missing mean-ratio transpose",
    entry_point="correct_reshaped_time_bin_array",
    stage="sd",
    consumes=frozenset({"mean_area_ratio"}),
))

register(EnhancementSpec(
    name="rollover_fix",
    summary="A5 -- corrects every midnight crossing in the per-second timehhmmss "
            "rollover, not only the first; the v3.5-superseded particle-time half "
            "is out of scope (partial-on-v35).",
    finding="the first-midnight-only rollover",
    entry_point="corrected_rollover",
    stage="sd",
    consumes=frozenset({"timehhmmss"}),
))

register(EnhancementSpec(
    name="spec_artefact_filter",
    summary="SPEC's own 2D-S artefact-removal criteria (roundness, splash, "
            "line/dot noise, noisy-diode exception) as a selectable second "
            "rejection scheme alongside the port's own auto_reject.",
    finding=None,
    entry_point=None,
    stage="proc",
    consumes=frozenset({"images"}),
))

register(EnhancementSpec(
    name="outoffocus",
    summary="A12 -- reruns the reject stage with the hollow block forced on to "
            "recompute part_z/size_factor, then applies Korolev's D_0 = D_m/size_factor "
            "(the dead sizeDist.m:793 multiply ran the wrong way) and a sphere area.",
    finding="the unapplied Korolev size correction",
    entry_point="apply_outoffocus",
    stage="proc",
    consumes=frozenset({"images", "image_diam_minR"}),
))

register(EnhancementSpec(
    name="overload_accounting_fix",
    summary="A8 -- recomputes sum_IntArr/sample_vol for particle-bearing seconds "
            "whose accepted population is empty, which sizeDist.m resets to 1.",
    finding="the no-accept second overwrite",
    entry_point="apply_overload_accounting",
    stage="sd",
    consumes=frozenset({"sum_IntArr", "sample_vol", "DMT_DOF_SPEC_OVERLOAD",
                        "Time_in_seconds"}),
))

register(EnhancementSpec(
    name="particle_time_int8_fix",
    summary="A15 -- recovers particle_time for 2DC/2DP/Fast2DC where an int8 "
            "hour/minute/second seed saturates it to 127.",
    finding="the int8 particle-time collapse",
    entry_point="corrected_proc_file",
    stage="proc",
    consumes=frozenset({"parent_rec_num", "Time", "Time_in_seconds",
                        "particle_millisec", "particle_microsec"}),
))

register(EnhancementSpec(
    name="pms_c6_routing_fix",
    summary="A11 -- routes a 'C6' (F2DC) record's scalar fields to the F2DC file "
            "instead of the 2DC file, matching the image it already routes correctly.",
    finding="the misfiled F2DC scalar fields",
    entry_point="read_binary_PMS_corrected",
    stage="reader",
    consumes=frozenset({"raw"}),
))

register(EnhancementSpec(
    name="intarr_threshold_fix",
    summary="B9 -- picks the first local minimum inside the crossover window "
            "instead of the histogram's global minimum. Variant-only on v3.5.",
    finding="the global-minimum inter-arrival threshold",
    entry_point="crossover_threshold",
    stage="sd",
    consumes=frozenset({"int_arr"}),
))

register(EnhancementSpec(
    name="diode_range_fix",
    summary="F3 -- validates a shadow-diode mask against the probe width instead "
            "of letting the image silently widen and the run exit part-way through.",
    finding="the image-widening diode number",
    entry_point="reilluminate_checked",
    stage="proc",
    consumes=frozenset({"images"}),
))

register(EnhancementSpec(
    name="mask_presence_fix",
    summary="F1 -- a missing or misnamed shadow-diode mask raises instead of "
            "silently leaving the run unmasked.",
    finding="the silent missing mask file",
    entry_point="check_mask",
    stage="proc",
    consumes=frozenset(),
))

register(EnhancementSpec(
    name="particle_number_all_fix",
    summary="C5b -- drops the always-fill-valued Particle_number_all column for "
            "probetype 0/3, where imgProc_sm.m defines it unconditionally but "
            "writes it only for probetype 1/2.",
    finding="the sometimes-written Particle_number_all",
    entry_point="corrected_proc_file",
    stage="proc",
    consumes=frozenset({"Particle_number_all"}),
))

register(EnhancementSpec(
    name="zero_image_recovery",
    requires_v314=True,
    summary="A10 -- the ORACLES fork's own break on a zero-image particle "
            "reproduced as an opt-in FidelityProfile flag. Variant-only on v3.5, "
            "which never has the break.",
    finding="the abandoned zero-image record",
    entry_point="with_zero_image_recovery",
    stage="proc",
    consumes=frozenset({"images"}),
))

register(EnhancementSpec(
    name="last_record_fix",
    requires_v314=True,
    summary="E5 -- decodes the final record of a SPEC raw file as a primary "
            "record, recovering particles the port's own reader drops.",
    finding="the dropped final raw record",
    entry_point="read_binary_spec_with_last_record",
    stage="reader",
    consumes=frozenset({"raw"}),
))

register(EnhancementSpec(
    name="int_arr_rollback_fix",
    summary="D3c -- gives probetype 1 the clock-rollback correction "
            "probetype 0 and 2 already have.",
    finding="the missing probetype-1 rollback correction",
    entry_point="proc_file_with_rollback_corrected",
    stage="proc",
    consumes=frozenset({"Time_in_seconds"}),
))

register(EnhancementSpec(
    name="particle_time_glitch_fix",
    summary="At the probetype-1 site (a CIP fix) -- repairs glitched CIP/PIP header "
            "particle times from their in-sequence neighbours and drops only the "
            "unrecoverable ones, so sizeDist.m:544-545 cannot shift the rest of the "
            "flight 24 h on one bad header.",
    finding="the first-midnight-only rollover",
    entry_point="corrected_proc_file",
    stage="proc",
    consumes=frozenset({"particle_time", "Time_in_seconds"}),
))

register(EnhancementSpec(
    name="tas_grid_fix",
    summary="A17 -- collapses duplicated TAS seconds in the housekeeping grid "
            "so no second's particles are discarded before sizedist.run().",
    finding="the duplicate TAS-second particle loss",
    entry_point="collapse_tas_grid",
    stage="sd",
    consumes=frozenset(),
))

register(EnhancementSpec(
    name="pressure_units_fix",
    requires_v314=True,
    summary="B7 -- reruns sizedist.run() with a pressure in hPa, as single_vt.m's "
            "own docstring documents, instead of the ORACLES drivers' raw 9e5.",
    finding="the unchecked pressure unit",
    entry_point="sd_file_at_pressure",
    stage="sd",
    consumes=frozenset(),
))

register(EnhancementSpec(
    name="analysis",
    summary="PSD moments, mass-weighted mean diameter, and leg-scale aggregation "
            "with propagated Poisson uncertainty, over a sizeDist/combine output.",
    finding=None,
    entry_point=None,
    stage="sd",
    consumes=frozenset({"conc_minR", "mass", "massBL", "bin_mid", "bin_dD", "count"}),
))

register(EnhancementSpec(
    name="arco_export",
    summary="Analysis-ready (chunked, per-variable-compressed, dtype-narrowed) "
            "re-encode of a port output file, lossless by default.",
    finding=None,
    entry_point="export",
    stage="product",
    consumes=frozenset({"*"}),
))

register(EnhancementSpec(
    name="arm_export",
    summary="A CF-1.9 + ARM Data File Standards structural copy of a port output "
            "file -- time representation, global attributes, udunits-corrected unit "
            "strings and bin bounds (via cf_export, rescale off); no value changes.",
    finding=None,
    entry_point="export",
    stage="product",
    consumes=frozenset({"time"}),
))

register(EnhancementSpec(
    name="cf_export",
    summary="A CF-1.10 sibling of a port sd file: CF time and size/area-ratio bin "
            "coordinates with bounds, SI udunits units with the scale recorded per "
            "variable, standard_name only where the CF table has one (time).",
    finding=None,
    entry_point="export",
    stage="product",
    consumes=frozenset({"*"}),
))

register(EnhancementSpec(
    name="poisson_uncertainty",
    summary="Per-bin and total Poisson counting uncertainty on sizeDist output, "
            "from the field's own N-particles-per-bin convention.",
    finding=None,
    entry_point=None,
    stage="sd",
    consumes=frozenset({"count"}),
))

register(EnhancementSpec(
    name="probe_crossover",
    summary="2D-S/HVPS crossover diagnostic: per-second agreement of two probes' "
            "concentrations over their shared size range, against counting "
            "statistics. Merges nothing.",
    finding=None,
    entry_point=None,
    stage="sd",
    consumes=frozenset({"time", "bin_min", "bin_max", "bin_dD", "conc_minR", "count"}),
))

register(EnhancementSpec(
    name="probe_uncertainty",
    summary="Published per-instrument-class sizing/concentration uncertainty "
            "(Baumgardner et al. 2017 Table 9-2) and the 2D-S pixel-resolution "
            "shape floor it implies.",
    finding=None,
    entry_point=None,
    stage="none",
    consumes=frozenset(),
))

register(EnhancementSpec(
    name="effective_density",
    summary="A published, habit-dependent ice effective-density relation "
            "(DOC-0223 Table 2.1), a genuinely independent third mass path.",
    finding=None,
    entry_point="effective_density",
    stage="proc",
    consumes=frozenset({"image_diam_minR", "image_area", "holroyd_habit"}),
))

register(EnhancementSpec(
    name="particle_clustering",
    summary="Unsupervised k-means clustering of particle populations on nine "
            "proc-file scalar fields, so one verdict on a medoid covers a whole cluster.",
    finding=None,
    entry_point="cluster_flight",
    stage="proc",
    consumes=frozenset({"image_length", "image_width", "image_diam_minR",
                        "image_diam_circle_fit", "image_perimeter", "image_area",
                        "percent_shadow_area", "max_hole_diameter", "area_hole_ratio",
                        "image_auto_reject", "edge_at_max_hole"}),
))

register(EnhancementSpec(
    name="ml_accept_reject",
    summary="Task #27 -- a diode-occupancy heuristic (Method A) and a numpy-only "
            "logistic-regression baseline (Method B) for stuck-diode-merge artifacts.",
    finding=None,
    entry_point="classify_stuck_diode_artifact",
    stage="proc",
    consumes=frozenset({"images"}),
))

register(EnhancementSpec(
    name="distance_rejection",
    summary="Korolev & Field (2015) Sect. 4 -- an inter-particle DISTANCE "
            "shattering threshold (TAS-corrected), alongside the port's own "
            "fixed-time one.",
    finding=None,
    entry_point="is_shattered_by_distance",
    stage="sd",
    consumes=frozenset({"Time_in_seconds"}),
))

#: airspeed and size-dependent depth of field, 2026-09-14. Registered default-OFF; flipped ON by
#: the default-on decision (integration I1, 2026-09-15). Its Python functions keep `enabled=False` as written.
# Author, 2026-09-15, verbatim: *"it should be for all by default, but users should be
# able to specify individual ones if someone is an expert user or wants to isolate impact of
# each of them."* That decision made this row ON by default, like every other row at the time -- but
# that was superseded by the 2026-09-16 cold-start usability audit: `default_on` is now False
# for every module, universally (see the class docstring above), and a config turns this one
# on individually with `[enhancements] published_dof = true`.
register(EnhancementSpec(
    name="published_dof",
    summary="The 2D-S depth of field from Gurganus & Lawson (2018) Eq. (1), "
            "c = 8 +/- 0.2, in place of calc_sa_randombins.m:42's constant; "
            "airspeed-independent inside their 190 m/s envelope. Default OFF since "
            "2026-09-16 (ON by default before then); individually selectable.",
    finding=None,
    entry_point="corrected_sd_file",
    stage="sd",
    consumes=frozenset({"bin_mid", "bin_dD", "conc_minR", "n"}),
))

register(EnhancementSpec(
    name="poisson_restore",
    summary="Korolev & Field (2015) Eq. 2 -- population-level Poisson restoration "
            "of intact particles the inter-arrival shattering test over-rejects.",
    finding=None,
    entry_point="scale_size_distribution",
    stage="sd",
    consumes=frozenset({"conc_minR"}),
))

# D3, 2026-09-14. Registered default-OFF; flipped ON by
# the default-on decision (integration I1, 2026-09-15). From Python the module's own keyword stays as written:
# `reaccept_every_event_fix.run_sizedist(run, ..., reaccept_every_event=True)`.
# Author, 2026-09-15, verbatim: *"it should be for all by default, but users should be
# able to specify individual ones if someone is an expert user or wants to isolate impact of
# each of them."* That decision made this row ON by default, like every other row at the time -- but
# that was superseded by the 2026-09-16 cold-start usability audit: `default_on` is now False
# for every module, universally (see the class docstring above), and a config turns this one
# on individually with `[enhancements] reaccept_every_event_fix = true`.
register(EnhancementSpec(
    name="reaccept_every_event_fix",
    requires_v314=True,
    summary="Shattering reacceptance scans from the first rBegin to the last rEnd of the "
            "second (v3.5's own type-3 bracket, sizeDist.m:1403-1427) instead of the first "
            "event only. Default OFF since 2026-09-16 (ON by default before then); "
            "individually selectable.",
    finding="the first-event-only reacceptance scan",
    entry_point="run_sizedist",
    stage="sd",
    consumes=frozenset({"Time_in_seconds", "image_diam_minR", "image_auto_reject"}),
))

register(EnhancementSpec(
    name="intarr_policy",
    summary="McFarquhar et al. (2017) p. 11.21 -- the inter-arrival threshold rule "
            "(min measured / 2 tau2 / min fitted) and the neighbour-removal count "
            "(0/1/2) as explicit options; off reproduces UIOPS.",
    finding=None,
    entry_point="flag_shattered",
    stage="sd",
    consumes=frozenset({"int_arr"}),
    # Opt-in like every module here; and even when a config names it, the module's own
    # InterArrivalPolicy parameter defaults to OFF, which is UIOOPS, so a resolved-on
    # module with its default parameter changes nothing.
))


register(EnhancementSpec(
    name="partial_image_habit",
    summary="Korolev & Sussman (2000) RABIT -- habit fractions for an ensemble including "
            "its accepted partial (edge-touching) images; refuses a probe it holds no "
            "retrieval matrix for, which today is every 2D-S and HVPS.",
    finding=None,
    entry_point="classify_population",
    stage="proc",
    consumes=frozenset({"images"}),
))


# F1, 2026-10-05 (the author's rule that processing learned from NCAR Process2D is an
# enhancement, opt-in, marked as Process2D-derived and never merged into an engine).
register(EnhancementSpec(
    name="field2006_shatter",
    summary="Derived from NCAR Process2D (NCAR/aircraft_oap, Apache-2.0): Field et al. "
            "(2006) per-second double-Poisson fit to the last 400 inter-arrival times, "
            "shattering cutoff 0.05/a1 (process2d.cpp:723-933). Opt-in: selected in a run "
            "configuration, it writes an enh.sd copy with the fit and corrfac-scaled conc.",
    finding=None,
    entry_point="Field2006State",
    stage="sd",
    consumes=frozenset({"Time_in_seconds"}),
))


#: Registered specs whose module this distribution does not carry: ``requires_v314`` modules
#: absent from disk, moved out of :data:`REGISTRY` at import. :func:`resolve` and
#: :func:`entry_point` refuse these by name with the reason.
OMITTED: dict[str, EnhancementSpec] = {}


def _omit_absent_v314_modules() -> None:
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(REGISTRY):
        if REGISTRY[name].requires_v314 and not os.path.exists(
                os.path.join(here, name + ".py")):
            OMITTED[name] = REGISTRY.pop(name)


_omit_absent_v314_modules()


def _omitted_message(name: str) -> str:
    return (f"enhancement {name!r} is not part of this distribution: it needs the v3.1.4 "
            "validation engine, which the public distribution omits; use --engine 3.5")


def resolve(requested: Mapping[str, bool] | None = None,
            engine: str = applicability.DEFAULT_ENGINE) -> dict[str, bool]:
    """Resolve a ``[enhancements]`` table into an on/off decision for every enhancement.

    **Opt-in: an enhancement is ON only where the table says ``true``.** ``requested`` is
    the raw table from the config file -- ``RunConfig.enhancements``, or ``None``/``{}``
    for "no config file said anything", which resolves *nothing* on. Every registered
    enhancement appears in the result, so a driver reads one complete decision.

    This was the other way round from the switchable-enhancements rule (2026-09-10) to the 2026-09-16 cold-start usability audit: an
    unmentioned module defaulted **on**, on the argument that installing this package is
    itself the opt-in. The 2026-09-16 cold-start usability audit measured what that meant
    in practice -- a config whose only line was ``outoffocus = false`` resolved **31 of 40**
    modules ON under the default v3.5 engine and applied four of them, two of which
    (``hole_edge_swap``, ``published_dof``) change numbers. Meanwhile ``README.md``, the
    enhancements page and the example configuration's own comment all said opt-in.
    A user who writes one line to enable one correction must get one correction, so the
    default now makes a behaviour-changing deviation an opt-in flag,
    defaulting OFF, and matches
    ``arrayprobe.config.RunConfig.enabled``, which the port has always read this way.

    ``engine`` is which UIOOPS port the run is against, defaulting to v3.5 since
    2026-09-12. An enhancement that does not apply to it resolves **off**, and
    one the config file switched **on** explicitly raises
    :class:`~arrayprobe_enhancements.applicability.NotApplicableToEngine`
    instead -- the difference matters, because four of these modules correct
    defects the UIOOPS developers fixed in v3.5, where applying one would
    silently double-correct rather than do nothing.

    Raises :class:`UnknownEnhancement` if the file names something unregistered, so a
    mistyped opt-*in* that would silently not happen is a loud failure instead.
    """
    requested = dict(requested or {})
    # `all = true` (2026-09-23) is the one key that is not a module: it switches on
    # :func:`default_set` for this engine, and every explicit `<name> = true/false` beside it
    # still wins. `all = false` is the same as leaving it out.
    use_default_set = bool(requested.pop(ALL_KEY, False))
    # `protective` is the batch driver's switch for the default-on corrections of PROTECTIVE,
    # read by scripts/run_flight.py; it names no module, so it resolves nothing here and is not
    # an unknown key either.
    requested.pop(PROTECTIVE_KEY, None)
    omitted = sorted(set(requested) & set(OMITTED))
    if omitted:
        raise UnknownEnhancement(_omitted_message(omitted[0]))
    unknown = sorted(set(requested) - set(REGISTRY))
    if unknown:
        raise UnknownEnhancement(
            f"unknown enhancement(s) {unknown}; known: {sorted(REGISTRY)}. "
            "Enhancements are opt-in, so an ignored key would be a correction the config "
            "asked for that would not run; this is an error rather than an ignored line."
        )
    for name, wanted in requested.items():
        if wanted:
            applicability.check(name, engine)
    base = default_set(engine) if use_default_set else frozenset()
    return {name: bool(requested.get(name, spec.default_on or name in base))
            and applicability.applicable(name, engine)
            for name, spec in REGISTRY.items()}


#: The ``[enhancements]`` key that asks for :func:`default_set` rather than naming modules.
ALL_KEY = "all"

#: The ``[enhancements]`` key for the batch driver's ``--protective`` switch (true = ``on``,
#: false = ``off``); not a module name, so :func:`resolve` sets it aside.
PROTECTIVE_KEY = "protective"

#: Modules :func:`default_set` leaves out, per engine, each with its reason. Opt-in by name
#: only: a config that says ``all = true`` does not get them, one that also says
#: ``<name> = true`` does.
#:
#: ``outoffocus`` on v3.5 -- author, 2026-09-23, on the deferred-work list: *"outoffocus:
#: ... make it an opt in?"* Measured on the ACE-ENA v3.5 runs: it changed **no**
#: ``image_diam_minR`` (the v3.5 engine already divides every ``'H'``-rejected particle by its
#: size factor, ``outoffocus.py``'s ``already`` guard), only ``image_area`` on 0.2-0.4 % of
#: particles, and it was about 68 of the 72 minutes of the 0707 enhancement pass. On v3.1.4 it
#: does change diameters, so it stays in that engine's default set.
DEFAULT_SET_EXCLUSIONS: dict[str, dict[str, str]] = {
    "3.5": {
        "outoffocus": "opt-in by name on v3.5: changes no "
                      "diameter on this engine, only image_area on 0.2-0.4 % of particles, "
                      "at about 94 % of the enhancement pass's time",
    },
}


def default_set(engine: str = applicability.DEFAULT_ENGINE) -> frozenset[str]:
    """What "all enhancements" means for ``engine``: every registered module applicable to it,
    minus :data:`DEFAULT_SET_EXCLUSIONS`. Selected by ``[enhancements] all = true``.

    The author's default (2026-09-20) is *v3.5 with all enhancements*. Until this
    function it existed only as hand-written config files naming 33 modules each
    (``v35_all_enhancements.toml``), so a module could be taken out of the default only by
    editing every such file. Computed from ``applicability``, never listed, so a new module
    joins it and a superseded one does not.
    """
    excluded = DEFAULT_SET_EXCLUSIONS.get(engine, {})
    return frozenset(name for name in REGISTRY
                     if applicability.applicable(name, engine) and name not in excluded)


#: Corrections for data-destroying upstream
#: defects run by default where no archived product exists -- every probetype except the ORACLES
#: 2D-S/HVPS lineage (probetype 2), where the archived product must stay reproducible.
#: Name -> the probetypes it protects. ``default_on`` stays False on every spec: the default is the
#: driver's (``run_flight.py --protective auto``), not the package's.
PROTECTIVE: dict[str, frozenset[int]] = {
    # A5, probetype-1 site: one bad header shifts the rest of the flight +24 h.
    "particle_time_glitch_fix": frozenset({1}),
    # A15: the int8 seed saturates particle_time at 127 (2DC/2DP = 0, Fast2DC = 3).
    "particle_time_int8_fix": frozenset({0, 3}),
    # A17: a duplicated TAS second loses every particle in it.
    "tas_grid_fix": frozenset({0, 1, 3}),
}

#: Keyword arguments a protective module runs with when it runs by default. ``drop`` invents no
#: values.
PROTECTIVE_POLICY: dict[str, dict[str, str]] = {
    "particle_time_glitch_fix": {"policy": "drop"},
}

#: The ORACLES validation lineage: never protected by default, whatever the engine.
LINEAGE_PROBES: frozenset[str] = frozenset({"2DS", "HVPS"})


def protective_set(engine: str, probe: str, probetype: int) -> frozenset[str]:
    """The protective corrections that run by default for ``probe`` on ``engine``.

    Empty for probetype 2 (2D-S/HVPS), whatever the engine, so the ORACLES 2D-S/HVPS
    products and their stamps are unchanged. Otherwise every :data:`PROTECTIVE` entry whose
    probetypes include ``probetype`` and that :func:`applicability.applicable` allows on ``engine``.
    """
    if probetype == 2 or probe in LINEAGE_PROBES:
        return frozenset()
    return frozenset(name for name, types in PROTECTIVE.items()
                     if probetype in types and applicability.applicable(name, engine))


def resolve_from_config(cfg, engine: str = applicability.DEFAULT_ENGINE
                        ) -> dict[str, bool]:
    """:func:`resolve` applied to an :class:`arrayprobe.config.RunConfig`.

    Reads ``cfg.enhancements``, the raw table the core carries verbatim and does not
    interpret. Accepts the object rather than the dict so a caller that already has a
    loaded config does not have to know which attribute holds it. ``engine`` is
    passed through unchanged.
    """
    return resolve(getattr(cfg, "enhancements", None), engine=engine)


def entry_point(name: str):
    """Import and return the public callable for enhancement ``name``.

    The lookup a driver uses once :func:`resolve` has said an enhancement is on.
    Raises :class:`UnknownEnhancement` for an unregistered name, and ``LookupError``
    for one registered without an ``entry_point`` (registered and selectable, but not
    yet wired to a driver -- see the design doc's remaining-work table).
    """
    if name in OMITTED:
        raise UnknownEnhancement(_omitted_message(name))
    if name not in REGISTRY:
        raise UnknownEnhancement(f"unknown enhancement {name!r}; known: {sorted(REGISTRY)}")
    spec = REGISTRY[name]
    if spec.entry_point is None:
        raise LookupError(
            f"enhancement {name!r} is registered but has no entry_point yet -- it can be "
            "selected and resolved, but no driver callable is wired to it. See "
            "enhancements_uiops/docs/enhancement_registry_design.md."
        )
    import importlib
    try:
        module = importlib.import_module(f"arrayprobe_enhancements.{name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"arrayprobe_enhancements.{name}":
            raise ImportError(
                f"enhancement {name!r} is not part of this distribution: it needs the v3.1.4 "
                "validation engine, which the public distribution omits; use --engine 3.5"
            ) from exc
        raise
    return getattr(module, spec.entry_point)
